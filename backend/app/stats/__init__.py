"""Statistics backends.

The summary-stat endpoints in ``routes/usage.py`` switch between a local DB
aggregation (default) and a Metabase dataset card based on the
``STATS_DATA_SOURCE`` config (``db`` or ``metabase``). Only one source is
active at a time; there is no automatic fallback.

See ``metabase_client.py`` for coverage notes (which endpoints/fields the card
supports and which stay on DB regardless of the switch).
"""
