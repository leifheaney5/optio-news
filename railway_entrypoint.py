"""Railway entrypoint for Optio.

Optio historically forced psycopg2 ``sslmode=require`` for every PostgreSQL
connection. Railway private-network Postgres can be non-TLS, which makes the
application exit before binding its HTTP port. Use libpq's ``prefer`` behavior
by default: negotiate TLS when the server supports it and fall back otherwise.
Set OPTIO_DB_SSLMODE=require to enforce TLS for an external database.
"""

import os
import threading

import psycopg2

_original_connect = psycopg2.connect


def _railway_compatible_connect(*args, **kwargs):
    if kwargs.get("sslmode") == "require":
        kwargs["sslmode"] = os.getenv("OPTIO_DB_SSLMODE", "prefer")
    return _original_connect(*args, **kwargs)


psycopg2.connect = _railway_compatible_connect

import main  # noqa: E402  (must import after psycopg2 compatibility hook)


if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=main.run_scheduler, daemon=True)
    scheduler_thread.start()

    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None
    main.logging.info("Starting web server on port %s", port)
    main.app.run(
        debug=debug,
        host="0.0.0.0",
        port=port,
        use_reloader=False,
    )
