#!/bin/sh
# =============================================================
# Model Link container entrypoint.
# Fixed runtime constants are configured below — edit here instead
# of rebuilding the image or overriding CMD.
# =============================================================

set -e

# ---- Fixed runtime constants --------------------------------
APP_MODULE="app.main:app"
HOST="0.0.0.0"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"
KEEPALIVE_TIMEOUT="1200"   # seconds, matches upstream LLM long streams
LOG_LEVEL="${LOG_LEVEL:-info}"

# ---- Metabase statistics source ------------------------------
# Used only when STATS_DATA_SOURCE=metabase. Values below are the
# production defaults; an environment variable of the same name, if set,
# takes precedence (override per-deploy without editing this script).
export METABASE_CARD_ID="${METABASE_CARD_ID:-15763}"
export METABASE_DATABASE_ID="${METABASE_DATABASE_ID:-13371347}"

# Stable field lib/uuid values for the columns exposed by the source card.
export METABASE_FIELD_DS_UUID="${METABASE_FIELD_DS_UUID:-5c6bddf7-f7cc-40a1-9892-15931084b009}"
export METABASE_FIELD_DS_TIME_UUID="${METABASE_FIELD_DS_TIME_UUID:-ea042777-dc07-4fbe-bcc1-d54d5d21d5f8}"
export METABASE_FIELD_ACTUALAMOUNTUSD_UUID="${METABASE_FIELD_ACTUALAMOUNTUSD_UUID:-16467cc1-fc49-4bb3-b18c-ddbe92a8f14f}"
export METABASE_FIELD_APIKEYNAME_UUID="${METABASE_FIELD_APIKEYNAME_UUID:-cd0859f0-7ad4-4f20-a72d-70b8d51ffca1}"
export METABASE_FIELD_APIKEYHASH_UUID="${METABASE_FIELD_APIKEYHASH_UUID:-c6347ebc-e05e-40db-8cb8-b643e392bdf5}"
export METABASE_FIELD_GROUPID_UUID="${METABASE_FIELD_GROUPID_UUID:-744b503c-26ac-427f-b0ee-8254acdb61c0}"
export METABASE_FIELD_USERNAME_UUID="${METABASE_FIELD_USERNAME_UUID:-4aa42d29-277e-4930-9e7f-a367db3a0f6f}"
export METABASE_FIELD_MODELNAME_UUID="${METABASE_FIELD_MODELNAME_UUID:-34e90419-ae9b-4a66-917f-95668b425b67}"
export METABASE_FIELD_INPUTTOKENS_UUID="${METABASE_FIELD_INPUTTOKENS_UUID:-9d78d634-714b-4034-9e3b-6ead7162429e}"
export METABASE_FIELD_OUTPUTTOKENS_UUID="${METABASE_FIELD_OUTPUTTOKENS_UUID:-ef5c9754-63b2-4d5a-aeb8-ebda03120675}"
export METABASE_FIELD_REASONINGTOKENS_UUID="${METABASE_FIELD_REASONINGTOKENS_UUID:-c76d05d4-01ae-4410-a532-2c5e947b3978}"
export METABASE_FIELD_CACHEDTOKENS_UUID="${METABASE_FIELD_CACHEDTOKENS_UUID:-d34763d3-82a2-4d38-930a-58b0934c2926}"
export METABASE_FIELD_CACHECREATIONTOKENS_UUID="${METABASE_FIELD_CACHECREATIONTOKENS_UUID:-a9d7a79b-0f5c-46f4-85f0-25fa91e98fe8}"
export METABASE_FIELD_CURRENCY_UUID="${METABASE_FIELD_CURRENCY_UUID:-9fb6da5f-45fd-4a06-9675-d31753916b55}"
export METABASE_FIELD_OUTPUTIMAGENUMBER_UUID="${METABASE_FIELD_OUTPUTIMAGENUMBER_UUID:-ea5ed76f-b94d-4fe9-8085-1ec8956666ed}"
export METABASE_FIELD_OUTPUTVIDEONUMBER_UUID="${METABASE_FIELD_OUTPUTVIDEONUMBER_UUID:-472dcdbb-e165-498a-8223-0a8326eea7e0}"
export METABASE_FIELD_OUTPUTAUDIOSECONDS_UUID="${METABASE_FIELD_OUTPUTAUDIOSECONDS_UUID:-00929096-d1fd-4ea0-b201-aaa06a5f967e}"
export METABASE_FIELD_WEBSEARCHREQUESTS_UUID="${METABASE_FIELD_WEBSEARCHREQUESTS_UUID:-ccad4122-51d7-4ab2-8d22-60652a2c8934}"

# ---- Launch the ASGI server ---------------------------------
# Note: DB migrations are NOT run here. Run them out-of-band
# (deploy pipeline / manual) via:
#   FLASK_APP=manage.py uv run flask db upgrade
echo "[entrypoint] starting uvicorn on ${HOST}:${PORT} (${WORKERS} worker(s))..."
exec uv run uvicorn "$APP_MODULE" \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --timeout-keep-alive "$KEEPALIVE_TIMEOUT" \
    --log-level "$LOG_LEVEL"
