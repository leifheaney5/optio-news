"""One-shot entrypoint for the scheduled digest service."""

from main import app, job


def run_job():
    """Run the digest once inside the Flask application context."""
    with app.app_context():
        return job()


if __name__ == '__main__':
    run_job()
