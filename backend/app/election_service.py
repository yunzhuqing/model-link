"""
Distributed Leader Election Service
====================================

Uses the **tooz** coordination library to perform leader election among
multiple application instances.  Supports both *single-node* (file-based
driver) and *distributed* (e.g. Redis / Zookeeper / etcd / Consul …)
deployments — controlled entirely via the ``COORDINATOR_URL`` environment
variable.

The election mechanism uses **distributed locking** — which is supported
by *every* tooz backend (file, Redis, ZooKeeper, etcd, Consul, MySQL,
PostgreSQL, memcached …).  The node that holds the lock is the leader;
all other nodes are followers.  When the leader dies or releases the lock,
another node will acquire it and become the new leader.

Environment variables
---------------------
``COORDINATOR_URL``
    The tooz backend URL.  Examples:

    * ``file:///tmp/model-link-coordinator``  – single-node / local dev (file-based, no external service)
    * ``redis://localhost:6379``              – distributed via Redis
    * ``zookeeper://host1:2181,host2:2181``   – distributed via ZooKeeper
    * ``etcd3+http://localhost:2379``         – distributed via etcd v3
    * ``consul://localhost:8500``             – distributed via Consul
    * ``mysql://user:pass@host/db``           – distributed via MySQL
    * ``postgresql://user:pass@host/db``      – distributed via PostgreSQL

    When **not set** (or empty), the service falls back to the ``file://``
    driver — a lightweight file-system lock-based coordinator that requires
    no external service, perfect for single-node / local development.

``ELECTION_GROUP``
    The name used for the distributed lock (election partition).
    Defaults to ``model-link-leader``.

``NODE_ID``
    A unique identifier for this node.  Defaults to ``<hostname>-<pid>``.

``ELECTION_HEARTBEAT_INTERVAL``
    How often (in seconds) the heartbeat / lock-renew loop runs.  Defaults
    to ``10``.

Public helpers
--------------
``start_election()``
    Call once at application startup (already wired in ``create_app``).

``is_leader() -> bool``
    Thread-safe check — use anywhere in your business logic::

        from app.election_service import is_leader

        if is_leader():
            # only the leader runs this code path
            ...

``get_node_id() -> str``
    Returns the identifier of the current node.

``get_leader_node_id() -> str | None``
    Returns the identifier of the *current* leader (may be another node),
    or ``None`` if no leader has been elected yet.

``stop_election()``
    Graceful shutdown — called automatically via an ``atexit`` hook but can
    also be invoked manually.
"""
from __future__ import annotations

import atexit
import logging
import os
import platform
import threading
from typing import Optional

logger = logging.getLogger("election")

# ── Configuration ────────────────────────────────────────────────────────────

_DEFAULT_COORDINATOR = "file:///tmp/model-link-coordinator"
_DEFAULT_GROUP = "model-link-leader"
_DEFAULT_HEARTBEAT = 10  # seconds


def _get_node_id() -> str:
    """Build a node identifier from hostname + PID (unless overridden)."""
    return os.getenv(
        "NODE_ID",
        f"{platform.node()}-{os.getpid()}",
    )


# ── In-memory state ──────────────────────────────────────────────────────────

_lock = threading.Lock()
_is_leader: bool = False
_leader_node_id: Optional[str] = None
_node_id: str = ""
_started: bool = False
_coordinator = None          # tooz coordinator instance
_election_lock = None        # tooz distributed lock
_stop_event = threading.Event()


# ── Public API ───────────────────────────────────────────────────────────────

def is_leader() -> bool:
    """Return ``True`` if the current node is the elected leader."""
    with _lock:
        return _is_leader


def get_node_id() -> str:
    """Return this node's identifier."""
    return _node_id


def get_leader_node_id() -> Optional[str]:
    """Return the node-id of the current leader, or ``None``."""
    with _lock:
        return _leader_node_id


def start_election() -> None:
    """
    Start leader election in a background daemon thread.

    Safe to call multiple times — only the first invocation has any effect.
    """
    global _started, _node_id
    with _lock:
        if _started:
            return
        _started = True

    _node_id = _get_node_id()
    logger.info(f"[election] Node ID: {_node_id}")

    thread = threading.Thread(
        target=_election_loop,
        daemon=True,
        name="leader-election",
    )
    thread.start()

    # Make sure we clean up on interpreter exit
    atexit.register(stop_election)


def stop_election() -> None:
    """Gracefully leave the group and close the coordinator."""
    global _coordinator, _started, _election_lock, _is_leader, _leader_node_id
    _stop_event.set()

    # Release the election lock if we hold it
    if _election_lock is not None:
        try:
            _election_lock.release()
            logger.info("[election] Election lock released.")
        except Exception:
            pass
    _election_lock = None

    coord = _coordinator
    if coord is not None:
        try:
            coord.stop()
            logger.info("[election] Coordinator stopped.")
        except Exception as exc:
            logger.warning(f"[election] Error stopping coordinator: {exc}")
    _coordinator = None

    with _lock:
        _is_leader = False
        _leader_node_id = None
    _started = False


# ── Internal loop ────────────────────────────────────────────────────────────

def _election_loop() -> None:
    """
    Main election lifecycle executed in a background thread.

    Uses a **distributed lock** as the election mechanism:

    1. Connect to the coordination backend.
    2. Acquire a named lock (non-blocking).  If acquired → leader.
    3. Heartbeat at a regular interval; periodically re-check / try to
       acquire the lock if not currently the leader.

    This approach works with *every* tooz backend (file, redis, zookeeper,
    etcd, consul, mysql, postgresql, memcached, ipc …).
    """
    global _coordinator, _election_lock, _is_leader, _leader_node_id

    coordinator_url = os.getenv("COORDINATOR_URL", "").strip() or _DEFAULT_COORDINATOR
    group_name = os.getenv("ELECTION_GROUP", _DEFAULT_GROUP)
    heartbeat = float(os.getenv("ELECTION_HEARTBEAT_INTERVAL", _DEFAULT_HEARTBEAT))

    logger.info(
        f"[election] Starting election — backend={coordinator_url}, "
        f"group={group_name}, heartbeat={heartbeat}s"
    )

    # ------------------------------------------------------------------
    # 1. Create & start the coordinator
    # ------------------------------------------------------------------
    try:
        from tooz import coordination  # type: ignore[import-untyped]

        # Ensure the directory exists for the file:// driver
        if coordinator_url.startswith("file://"):
            file_path = coordinator_url[len("file://"):]
            os.makedirs(file_path, exist_ok=True)

        _coordinator = coordination.get_coordinator(
            coordinator_url,
            _node_id.encode("utf-8"),
        )
        _coordinator.start(start_heart=True)
        logger.info("[election] Coordinator connected.")
    except Exception as exc:
        logger.error(f"[election] Failed to start coordinator: {exc}")
        # Fall back to "always leader" so a single dev node still works.
        with _lock:
            _is_leader = True
            _leader_node_id = _node_id
        logger.warning("[election] Falling back to standalone leader mode.")
        return

    # ------------------------------------------------------------------
    # 2. Create the distributed lock for election
    # ------------------------------------------------------------------
    lock_name = f"{group_name}-leader-lock".encode("utf-8")
    _election_lock = _coordinator.get_lock(lock_name)
    logger.info(f"[election] Using lock-based election (lock={lock_name!r})")

    # ------------------------------------------------------------------
    # 3. Try to acquire the lock immediately
    # ------------------------------------------------------------------
    _try_acquire_leadership()

    # ------------------------------------------------------------------
    # 4. Heartbeat + re-election loop
    # ------------------------------------------------------------------
    while not _stop_event.is_set():
        try:
            _coordinator.heartbeat()
        except Exception as exc:
            logger.warning(f"[election] Heartbeat error: {exc}")
            with _lock:
                _is_leader = False
                _leader_node_id = None

        # If we are not the leader, keep trying to acquire the lock
        if not is_leader():
            _try_acquire_leadership()

        _stop_event.wait(timeout=heartbeat)

    logger.info("[election] Election loop terminated.")


def _try_acquire_leadership() -> None:
    """Attempt to acquire the distributed lock (non-blocking)."""
    global _is_leader, _leader_node_id

    if _election_lock is None:
        return

    try:
        acquired = _election_lock.acquire(blocking=False)
        if acquired:
            with _lock:
                _is_leader = True
                _leader_node_id = _node_id
            logger.info(f"[election] 🏆 This node ({_node_id}) acquired the leader lock.")
        else:
            with _lock:
                if _is_leader:
                    # We lost the lock
                    logger.info(f"[election] This node ({_node_id}) lost leadership.")
                _is_leader = False
                # We don't know who the leader is in lock-based mode
                _leader_node_id = None
    except Exception as exc:
        logger.error(f"[election] Error acquiring lock: {exc}")
        with _lock:
            _is_leader = False
            _leader_node_id = None
