"""One-shot Optio daily digest runner for Railway cron."""
from __future__ import annotations

from main import app, job


def main() -> int:
    with app.app_context():
        job()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
