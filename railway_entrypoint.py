"""Compatibility entrypoint for Railway smoke checks and legacy starts."""

import os

from main import app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("RAILWAY_ENVIRONMENT") is None
    app.run(debug=debug, host="0.0.0.0", port=port, use_reloader=False)
