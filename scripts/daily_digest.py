"""Send one Optio daily digest and exit.

This is intended for a Railway cron service. Importing ``main`` starts Optio's
existing cache warm in a daemon thread; wait for that single crawl to finish and
reuse its cache instead of launching a duplicate feed crawl.
"""
from __future__ import annotations

import logging
from pathlib import Path
import sys
import time

# ``python scripts/daily_digest.py`` makes scripts/ sys.path[0]; explicitly add
# the repository root so importing the existing application module is reliable
# in Railway and local shells alike.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app, cache_is_warming, create_email_content, fetch_articles, send_email  # noqa: E402


def main() -> int:
    deadline = time.monotonic() + 180
    while cache_is_warming() and time.monotonic() < deadline:
        time.sleep(1)

    with app.app_context():
        articles = fetch_articles(force_refresh=False)
        if not articles:
            # Covers a failed/empty startup warm or a future startup mode where
            # warming is disabled for serverless web instances.
            articles = fetch_articles(force_refresh=True)

        if not articles:
            logging.warning("No articles available; daily digest not sent.")
            return 0

        send_email(create_email_content(articles))
        logging.info("Daily digest sent from one-shot cron job.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
