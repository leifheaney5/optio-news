"""One-shot ingestion entrypoint for a separately scaled worker service."""

from main import app
from ingestion import ingest_once


if __name__ == '__main__':
    with app.app_context():
        ingest_once()
