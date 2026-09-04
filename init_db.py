"""Create Optio's current database tables as an explicit one-off operation."""

from main import app, initialize_database, seed_feed_catalog


if __name__ == '__main__':
    initialize_database()
    with app.app_context():
        seed_feed_catalog()
    print('Optio database initialized.')
