"""Railway entrypoint for Optio.

The PostgreSQL compatibility hook is installed from ``optio_runtime_compat``
and loaded automatically by Python before this module runs. This entrypoint
only owns Optio's web/scheduler startup so database compatibility logic has one
source of truth.
"""

import os
import threading

import main


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
