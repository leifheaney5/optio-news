"""Interpreter-level compatibility for Optio's PostgreSQL connection.

Python imports ``sitecustomize`` automatically during normal startup when this
repository is on ``sys.path``. Optio historically passes ``sslmode=require`` to
psycopg2 for every PostgreSQL URL; Railway private Postgres may be non-TLS. Use
libpq's ``prefer`` mode by default while preserving an explicit strict-TLS opt-in
through ``OPTIO_DB_SSLMODE=require``.
"""

import os

try:
    import psycopg2
except ImportError:  # tooling/build phases may not have runtime deps installed yet
    psycopg2 = None

if psycopg2 is not None and not getattr(psycopg2, "_optio_ssl_compat", False):
    _original_connect = psycopg2.connect

    def _optio_connect(*args, **kwargs):
        if kwargs.get("sslmode") == "require":
            kwargs["sslmode"] = os.getenv("OPTIO_DB_SSLMODE", "prefer")
        return _original_connect(*args, **kwargs)

    psycopg2.connect = _optio_connect
    psycopg2._optio_ssl_compat = True
