"""
Quart application factory for Model Link AI Gateway.
"""
import asyncio
import logging
import logging.handlers
import os
import uuid
from contextvars import ContextVar

from quart import Quart, send_from_directory
from quart_cors import cors as quart_cors_init
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# ContextVar to hold the current request ID so it can be injected into log records.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Logging filter that injects the current request_id into every log record."""

    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


class SafePercentStyle(logging.PercentStyle):
    """PercentStyle that substitutes missing keys with '-' instead of raising KeyError."""

    def format(self, record):
        record_dict = record.__dict__
        for key in ("request_id",):
            if key not in record_dict:
                record_dict[key] = "-"
        return self._format(record)


class LogFormatter(logging.Formatter):
    """Log formatter that supports customizable output via LOG_FORMAT env variable."""

    def __init__(self):
        format_string = os.getenv(
            "LOG_FORMAT",
            "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
        )
        datefmt = os.getenv("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S")
        super().__init__(format_string, datefmt=datefmt)
        self._style = SafePercentStyle(format_string)


def _configure_logging() -> None:
    """
    Configure application logging based on environment variables.

    Supported environment variables:
        LOG_LEVEL       (str)  : DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
        LOG_NAME        (str)  : Logger name and log file name (without .log extension) (default: "model-link")
        LOG_DIR         (str)  : Directory to write log files to (e.g. "/var/log/model-link").
                                 When set, logs are written to both stderr and ``{LOG_DIR}/{LOG_NAME}.log``.
                                 The directory will be created automatically.
        LOG_FORMAT      (str)  : Python log format string
                                 (default: "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        LOG_DATE_FORMAT (str)  : Date/time format string (default: "%Y-%m-%d %H:%M:%S")

    The default format includes timestamp, logger name, level, and message — suitable
    for both local development and production log aggregators.

    Example LOG_FORMAT values:
        - JSON for log aggregation:
          ``LOG_FORMAT={"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}``
        - Minimal:
          ``LOG_FORMAT=[%(levelname)s] %(message)s``
        - With file/line info:
          ``LOG_FORMAT=%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s``
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, level_name, None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    log_name = os.getenv("LOG_NAME", "model-link")
    log_dir = os.getenv("LOG_DIR", "")
    formatter = LogFormatter()

    handlers: list[logging.Handler] = []

    # Always log to stderr
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)

    # Optional file logging — writes to {LOG_DIR}/{LOG_NAME}.log
    # Example: LOG_DIR=/var/log/model-link, LOG_NAME=gateway
    #          → /var/log/model-link/gateway.log
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, f"{log_name}")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            maxBytes=50 * 1024 * 1024,  # 50 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    # Configure the root logger (empty name "").
    #
    # All child loggers (e.g. "gateway", "gateway_responses", "uvicorn",
    # "quart") inherit these handlers via propagation, so every module
    # that calls ``logging.getLogger("some-name")`` will see output.
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.addFilter(RequestIdFilter())
    for h in handlers:
        root_logger.addHandler(h)

    # Suppress overly verbose third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
    logging.getLogger("redis").setLevel(logging.WARNING)


# Configure logging early — before any module-level getLogger() calls
_configure_logging()

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()

# ── Async DB engine and session factory ──────────────────────────────────────
# Used by all async route handlers. The sync ``db`` (Flask-SQLAlchemy) is kept
# for Alembic migrations and startup/bootstrap queries.

from sqlalchemy.ext.asyncio import create_async_engine as _create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker as _async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
from sqlalchemy.pool import NullPool as _NullPool

_async_engine = None
_async_session_factory = None
_main_event_loop: "asyncio.AbstractEventLoop | None" = None


def get_main_event_loop():
    """Return the main asyncio event loop captured at app startup.

    Used by services that run on background threads (e.g. the election
    callback thread) but need to schedule coroutines on the loop where
    the shared async SQLAlchemy engine lives.
    """
    return _main_event_loop


def _build_async_db_url() -> str:
    """Build an async database URL from the DATABASE_URL env var.

    Handles both sync URLs (mysql+pymysql:// → mysql+aiomysql://) and
    already-async URLs (returned as-is).
    """
    database_url = os.getenv('DATABASE_URL', 'sqlite:///./sql_app.db')
    # Already async — return as-is
    if "+aiomysql" in database_url or "+asyncpg" in database_url or "+aiosqlite" in database_url:
        return database_url
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("mysql+pymysql://"):
        return database_url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    if database_url.startswith("mysql://"):
        return database_url.replace("mysql://", "mysql+aiomysql://", 1)
    if database_url.startswith("sqlite://"):
        return database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return database_url


def _ensure_sync_db_url(database_url: str) -> str:
    """Convert an async URL back to sync format for Flask-SQLAlchemy.

    mysql+aiomysql:// → mysql+pymysql://
    postgresql+asyncpg:// → postgresql://
    sqlite+aiosqlite:// → sqlite://
    """
    if "+aiomysql" in database_url:
        return database_url.replace("+aiomysql", "+pymysql", 1)
    if "+asyncpg" in database_url:
        return database_url.replace("+asyncpg", "", 1)
    if "+aiosqlite" in database_url:
        return database_url.replace("+aiosqlite", "", 1)
    return database_url


def get_db_session() -> _AsyncSession:
    """Return a new async DB session. Caller is responsible for closing it.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(select(Model).where(...))
    """
    return _async_session_factory()


async def _init_async_engine():
    """Initialise the async engine and session factory."""
    global _async_engine, _async_session_factory, _main_event_loop
    # Capture the main loop so background threads can schedule coroutines onto it.
    _main_event_loop = asyncio.get_running_loop()
    async_url = _build_async_db_url()
    _async_engine = _create_async_engine(
        async_url,
        pool_size=int(os.getenv('SQLALCHEMY_POOL_SIZE', 10)),
        max_overflow=int(os.getenv('SQLALCHEMY_MAX_OVERFLOW', 20)),
        pool_timeout=int(os.getenv('SQLALCHEMY_POOL_TIMEOUT', 30)),
        pool_recycle=int(os.getenv('SQLALCHEMY_POOL_RECYCLE', 600)),
        pool_pre_ping=os.getenv('SQLALCHEMY_POOL_PRE_PING', 'true').lower() == 'true',
    )

    # When the underlying TCP transport is closed (MySQL killed the connection,
    # network blip, load-balancer timeout), the pre-ping and terminate writes
    # may raise a bare RuntimeError("unable to perform operation on
    # <TCPTransport closed=True>") instead of a DBAPI disconnection error.
    # This is most common with uvloop but can happen with plain asyncio too.
    #
    # _do_ping_w_event only catches `loaded_dbapi.Error` (e.g. pymysql.Error),
    # so RuntimeError bypasses the is_disconnect check entirely and propagates
    # to the caller.  We wrap the aiomysql dialect's do_ping and do_terminate
    # to translate RuntimeError into a proper DBAPI OperationalError so the
    # pool can recognise stale connections and invalidate them transparently.
    _original_do_ping = _async_engine.sync_engine.dialect.do_ping

    def _do_ping_wrapper(dbapi_connection, orig=_original_do_ping):
        try:
            return orig(dbapi_connection)
        except RuntimeError as e:
            if "closed" in str(e).lower():
                # 2013 = CR_SERVER_LOST — recognised by MySQL dialect's
                # is_disconnect as a disconnection, so the pool discards
                # this connection and gets a fresh one.
                raise _async_engine.sync_engine.dialect.loaded_dbapi.OperationalError(
                    2013, str(e)
                ) from e
            raise

    _async_engine.sync_engine.dialect.do_ping = _do_ping_wrapper

    _original_do_terminate = _async_engine.sync_engine.dialect.do_terminate

    def _do_terminate_wrapper(dbapi_connection, orig=_original_do_terminate):
        try:
            return orig(dbapi_connection)
        except RuntimeError as e:
            if "closed" in str(e).lower():
                return  # transport already gone, nothing to terminate
            raise

    _async_engine.sync_engine.dialect.do_terminate = _do_terminate_wrapper

    _async_session_factory = _async_sessionmaker(
        _async_engine, class_=_AsyncSession, expire_on_commit=False,
    )


async def _dispose_async_engine():
    """Dispose the async engine. Called on shutdown."""
    global _async_engine
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None


def create_app(config=None):
    """Create and configure the Quart application."""
    app = Quart(__name__)
    
    # Load configuration
    database_url = os.getenv('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    # Ensure the sync URL for Flask-SQLAlchemy (strip async driver prefix)
    sync_db_url = _ensure_sync_db_url(database_url) if database_url else 'sqlite:///./sql_app.db'

    app.config['SQLALCHEMY_DATABASE_URI'] = sync_db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Allow large request bodies (base64 images can be several MB)
    app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB default

    # Timeout settings for Quart/ASGI request handling.
    app.config['BODY_TIMEOUT'] = int(os.getenv('BODY_TIMEOUT', 300))
    app.config['RESPONSE_TIMEOUT'] = int(os.getenv('RESPONSE_TIMEOUT', 2400))

    # Database connection pooling settings for long-lived connections.
    engine_options = {
        'pool_size': int(os.getenv('SQLALCHEMY_POOL_SIZE', 10)),
        'max_overflow': int(os.getenv('SQLALCHEMY_MAX_OVERFLOW', 20)),
        'pool_timeout': int(os.getenv('SQLALCHEMY_POOL_TIMEOUT', 30)),
        'pool_recycle': int(os.getenv('SQLALCHEMY_POOL_RECYCLE', 600)),
        'pool_pre_ping': os.getenv('SQLALCHEMY_POOL_PRE_PING', 'true').lower() == 'true',
    }
    # MySQL-specific connect args (pymysql supports these; other drivers don't)
    if 'mysql' in sync_db_url:
        engine_options['connect_args'] = {
            'connect_timeout': int(os.getenv('DB_CONNECT_TIMEOUT', 10)),
            'read_timeout': int(os.getenv('DB_READ_TIMEOUT', 30)),
            'write_timeout': int(os.getenv('DB_WRITE_TIMEOUT', 30)),
        }
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
    
    # Apply any custom config
    if config:
        app.config.update(config)
    
    # Initialize extensions with app
    db.init_app(app)
    migrate.init_app(app, db)

    # Flask-SQLAlchemy auto-registers a sync teardown_appcontext that calls
    # `db.session.remove()`. Under Quart this crashes with "Working outside of
    # application context" because Quart's app context doesn't set Flask's
    # _cv_app ContextVar. Since route handlers no longer touch db.session
    # (they use `async with get_db_session()` instead), it's safe to drop.
    app.teardown_appcontext_funcs[:] = [
        fn for fn in app.teardown_appcontext_funcs
        if not getattr(fn, '__qualname__', '').startswith('SQLAlchemy.')
    ]

    # ── Per-request hooks (request-id only; no DB session lifecycle) ────────
    # All route handlers now open short-lived sessions explicitly via
    # `async with get_db_session() as s:`. The legacy g.db_session pattern
    # was removed because it tied each DB connection to the full request
    # lifetime — including minutes-long upstream LLM calls — which exhausted
    # the connection pool under concurrency.

    @app.before_request
    async def _assign_request_id():
        """Extract X-Request-Id from incoming request headers or generate a new one."""
        from quart import g, request
        req_id = request.headers.get("X-Request-Id")
        if not req_id:
            req_id = str(uuid.uuid4())
        g.request_id = req_id
        request_id_var.set(req_id)

    @app.after_request
    async def _add_request_id_header(response):
        """Include X-Request-Id in the response headers."""
        from quart import g
        req_id = getattr(g, "request_id", None)
        if req_id:
            response.headers["X-Request-Id"] = req_id
        return response


    # Enable CORS for all origins
    quart_cors_init(app, allow_origin="*")

    # Optionally enable aiodebug.log_slow_callbacks for diagnosing event-loop
    # stalls. Activated only when AIODEBUG_SLOW is set (e.g. "0.05" for 50ms);
    # leaving it unset means zero overhead in production.
    _aiodebug_threshold = os.getenv("AIODEBUG_SLOW")
    if _aiodebug_threshold:
        async def _enable_aiodebug():
            import asyncio
            from aiodebug import log_slow_callbacks
            threshold = float(_aiodebug_threshold)
            log_slow_callbacks.enable(threshold)
            asyncio.get_running_loop().set_debug(True)
            logging.getLogger("gateway").info(
                "aiodebug.log_slow_callbacks enabled (threshold=%.3fs)", threshold
            )
        app.before_serving(_enable_aiodebug)

    # Optional per-task duration tracing. TASK_TRACE_SLOW sets the slow-task
    # threshold (seconds); TASK_TRACE_WATCHDOG (also seconds) additionally
    # starts a watchdog that dumps the await-stack of any task still running
    # past the threshold, so we can see *where* it is stuck.
    _task_trace_threshold = os.getenv("TASK_TRACE_SLOW")
    if _task_trace_threshold:
        _task_trace_watchdog = os.getenv("TASK_TRACE_WATCHDOG")
        async def _enable_task_tracing():
            from app._task_tracing import enable
            enable(
                float(_task_trace_threshold),
                float(_task_trace_watchdog) if _task_trace_watchdog else None,
            )
        app.before_serving(_enable_task_tracing)

    # Initialise the async DB engine. This must happen before any routes are served.
    app.before_serving(_init_async_engine)

    # Schedule the async exchange-rate refresh on startup.
    from app.exchange_rate_service import start_daily_refresh as _start_exchange_rate_refresh
    app.before_serving(lambda: _start_exchange_rate_refresh() or None)

    # Initialise the storage backend eagerly so any misconfiguration
    # (e.g. missing S3 bucket name) surfaces at startup rather than on
    # the first background-response request.
    from app.storage import get_storage_backend as _init_storage
    _init_storage()

    # Initialise the cache middleware (memory or Redis, based on CACHE_BACKEND env).
    from app.cache import init_async_cache as _init_async_cache
    _init_async_cache()

    # Dispose async engine on shutdown.
    app.after_serving(_dispose_async_engine)

    # Close async cache and exchange rate task on shutdown.
    from app.cache import close_async_cache as _close_async_cache
    from app.exchange_rate_service import stop_daily_refresh as _stop_daily_refresh
    from app.http_client import close_all_shared_clients as _close_shared_http_clients
    from app.monitoring.langfuse_tracer import flush_all_clients as _flush_langfuse_clients

    async def _shutdown_cleanup():
        await _close_async_cache()
        await _stop_daily_refresh()
        await _close_shared_http_clients()
        # Langfuse flush is sync and blocking — run off the event loop.
        await asyncio.to_thread(_flush_langfuse_clients)

    app.after_serving(_shutdown_cleanup)

    # Start the distributed leader-election service.
    # In single-node / dev setups (no COORDINATOR_URL) the node automatically
    # becomes leader.  In production, set COORDINATOR_URL to a shared backend
    # (e.g. redis://…, zookeeper://…) so that exactly one instance is elected.
    from app.election_service import start_election as _start_election, register_on_leader, register_on_lost_leader

    # Register the usage-sync daemon to start only when this node becomes leader,
    # and stop it immediately when leadership is lost.
    from app.usagerecord.sync_service import start_usage_sync as _start_usage_sync, stop_usage_sync as _stop_usage_sync
    register_on_leader(lambda: _start_usage_sync(app))
    register_on_lost_leader(_stop_usage_sync)

    from app.usagerecord.compress_service import start_compress_service as _start_compress, stop_compress_service as _stop_compress
    register_on_leader(lambda: _start_compress(app))
    register_on_lost_leader(_stop_compress)

    from app.usagerecord.background_resync_service import start_background_resync as _start_bg_resync, stop_background_resync as _stop_bg_resync
    register_on_leader(lambda: _start_bg_resync(app))
    register_on_lost_leader(_stop_bg_resync)

    _start_election()

    # Register blueprints
    from app.routes.users import users_bp
    from app.routes.providers import providers_bp
    from app.routes.gateway import gateway_bp
    from app.routes.gateway_responses import gateway_responses_bp
    from app.routes.embeddings import embeddings_bp
    from app.routes.images import images_bp
    from app.routes.rerank import rerank_bp
    from app.routes.apikeys import apikeys_bp
    from app.routes.model_templates import model_templates_bp
    from app.routes.usage import usage_bp
    from app.routes.permissions import permissions_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(users_bp)
    app.register_blueprint(providers_bp, url_prefix='/api')
    app.register_blueprint(gateway_bp)
    app.register_blueprint(gateway_responses_bp)
    app.register_blueprint(embeddings_bp)
    app.register_blueprint(images_bp)
    app.register_blueprint(rerank_bp)
    app.register_blueprint(apikeys_bp, url_prefix='/api')
    app.register_blueprint(model_templates_bp, url_prefix='/api')
    app.register_blueprint(usage_bp)
    app.register_blueprint(permissions_bp, url_prefix='/api')
    app.register_blueprint(admin_bp)
    # Import and register tags blueprint
    from app.routes.tags import tags_bp
    app.register_blueprint(tags_bp, url_prefix='/api')
    
    # Serve React frontend if static folder exists, otherwise API-only mode
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')
    static_dir = os.path.abspath(static_dir)

    if os.path.isdir(static_dir) and os.path.isfile(os.path.join(static_dir, 'index.html')):
        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        async def serve_react(path):
            """Serve React frontend. API routes take priority via blueprints."""
            # Serve static files (JS, CSS, images, etc.)
            if path and os.path.isfile(os.path.join(static_dir, path)):
                return await send_from_directory(static_dir, path)
            # For all other routes, serve index.html (React Router handles client-side routing)
            return await send_from_directory(static_dir, 'index.html')
    else:
        # API-only mode (no frontend build present)
        @app.route('/')
        async def index():
            return {
                "message": "Welcome to AI Gateway API",
                "docs": "/docs",
                "endpoints": {
                    "openai_chat_completions": "/v1/chat/completions",
                    "anthropic_messages": "/v1/messages",
                    "openai_responses": "/v1/responses",
                    "models": "/v1/models",
                    "providers": "/api/providers/",
                    "register": "/register",
                    "login": "/token"
                }
            }

    @app.route('/health')
    async def health():
        from app.election_service import is_leader, get_node_id, get_leader_node_id
        return {
            "status": "healthy",
        }

    @app.route('/monitor/election')
    async def monitor_election():
        """Return leader election status and group membership.

        Response JSON:
            node_id: this node's identifier
            is_leader: whether this node is the elected leader
            leader_node_id: current leader's node identifier (None if unknown)
            group_members: dict of {node_id: capabilities} for all group members
            coordinator: backend URL, group name, and heartbeat interval
        """
        from app.election_service import (
            is_leader, get_node_id, get_leader_node_id,
            get_group_members, get_coordinator_info,
        )

        return {
            "node_id": get_node_id(),
            "is_leader": is_leader(),
            "leader_node_id": get_leader_node_id(),
            "group_members": get_group_members(),
            "coordinator": get_coordinator_info(),
        }

    @app.route('/monitor/threads')
    async def monitor_threads():
        """Return information about all running Python threads.

        This is useful for debugging thread leaks, hung background tasks,
        and general runtime introspection.

        Response JSON:
            thread_count: total number of active threads
            threads: list of thread details (id, name, daemon, alive, state)
        """
        import threading
        import sys
        import traceback

        # Grab current stack frames for all threads so we can include
        # a lightweight "state" description (top frame location).
        frames = sys._current_frames()

        threads_info = []
        for t in threading.enumerate():
            frame = frames.get(t.ident)
            if frame:
                # Format the top-most stack frame as a short location string
                top_frame = traceback.extract_stack(frame, limit=1)[0]
                current_location = f"{top_frame.filename}:{top_frame.lineno} in {top_frame.name}"
                stack_trace = "".join(traceback.format_stack(frame))
            else:
                current_location = "N/A"
                stack_trace = "N/A"

            threads_info.append({
                "id": t.ident,
                "name": t.name,
                "daemon": t.daemon,
                "alive": t.is_alive(),
                "current_location": current_location,
                "stack_trace": stack_trace,
            })

        return {
            "thread_count": threading.active_count(),
            "threads": threads_info,
        }

    return app