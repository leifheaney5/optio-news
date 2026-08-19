"""Loaded automatically by Python after installation into site-packages.

Optio's legacy app configuration passes ``sslmode=require`` to psycopg2 for
all PostgreSQL URLs. Railway private Postgres can be non-TLS. Default to
libpq's ``prefer`` behavior while preserving strict TLS through
``OPTIO_DB_SSLMODE=require`` when an external database requires it.
"""

import os

try:
    import psycopg2
except ImportError:
    psycopg2 = None

if psycopg2 is not None and not getattr(psycopg2, "_optio_ssl_compat", False):
    _original_connect = psycopg2.connect

    def _optio_connect(*args, **kwargs):
        if kwargs.get("sslmode") == "require":
            kwargs["sslmode"] = os.getenv("OPTIO_DB_SSLMODE", "prefer")
        return _original_connect(*args, **kwargs)

    psycopg2.connect = _optio_connect
    psycopg2._optio_ssl_compat = True
