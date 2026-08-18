"""Send one Optio daily digest and exit.

This is intended for a Railway cron service. Importing ``main`` starts Optio's
existing cache warm in a daemon thread; wait for that single crawl to finish and
reuse its cache instead of launching a duplicate feed crawl.
"""
from __future__ import annotations

import logging
import time

from main import app, cache_is_warming, create_email_content, fetch_articles, send_email


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
