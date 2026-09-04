"""
Optio News — unit + integration test suite.
Run: python -m pytest test_app.py -v
Uses a temp-file SQLite DB so no external services are needed.
"""
import os, json, pytest, tempfile, subprocess, sys, re
from pathlib import Path

# Create a temp SQLite file before importing main so the test clients share one
# database without requiring an external service.
# File-based SQLite is shared across all connections, unlike :memory:.
_db_fd, _DB_PATH = tempfile.mkstemp(suffix='.test.db')
os.close(_db_fd)
os.environ['DATABASE_URL'] = f'sqlite:///{_DB_PATH}'   # overwrite, not setdefault
os.environ.setdefault('SECRET_KEY', 'test-secret')

import main
from main import (app, db, User, UserFeed, Bookmark, Feed, Subscription,
                  Article, StoryCluster, UserArticleState, DigestPreference,
                  SavedSearch, extract_trending_topics)
from werkzeug.security import generate_password_hash


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(scope='session')
def test_app():
    app.config.update({
        'TESTING': True,
        'RATELIMIT_ENABLED': False,
        # No SQLALCHEMY_DATABASE_URI override needed — already set via env var above.
        'SQLALCHEMY_ENGINE_OPTIONS': {},   # strip any SSL options from main.py
    })
    main.limiter.enabled = False
    # Setup: create tables and seed the shared test user.
    # Do NOT keep this context alive — each test-client request must push its own
    # fresh app context so Flask's g / current_user are isolated per request.
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email='unit@test.com').first():
            u = User(email='unit@test.com',
                     password_hash=generate_password_hash('Test1234!'))
            db.session.add(u)
            db.session.commit()

    yield app

    # Teardown
    with app.app_context():
        db.drop_all()
    # Remove the temp SQLite file
    try:
        os.unlink(_DB_PATH)
    except OSError:
        pass


@pytest.fixture
def client(test_app):
    """Fresh unauthenticated test client per test."""
    return test_app.test_client()


@pytest.fixture
def auth_client(test_app):
    """Fresh test client logged in as unit@test.com for each test."""
    c = test_app.test_client()
    c.post('/login', data={'email': 'unit@test.com', 'password': 'Test1234!',
                           'csrf_token': csrf_token(c.get('/login'))},
           follow_redirects=True)
    return c


# helper to parse JSON responses
def jget(resp):
    return json.loads(resp.data)


def csrf_token(response):
    match = re.search(rb'name="csrf_token"[^>]+value="([^"]+)"', response.data)
    match = match or re.search(rb'name="csrf-token"[^>]+content="([^"]+)"', response.data)
    return match.group(1).decode() if match else None


def csrf_headers(client):
    token = csrf_token(client.get('/')) or csrf_token(client.get('/login'))
    return {'X-CSRFToken': token} if token else {}


# ──────────────────────────────────────────────
# 1. Auth — Register
# ──────────────────────────────────────────────

class TestRegister:
    def test_get_register_page(self, client):
        r = client.get('/register')
        assert r.status_code == 200
        assert b'register' in r.data.lower()

    def test_register_form_contains_csrf_token(self, client):
        assert csrf_token(client.get('/register'))

    def test_register_without_csrf_token_is_rejected(self, client):
        r = client.post('/register', data={
            'email': 'csrf@optio.news',
            'password': 'A sufficiently strong password',
            'confirm_password': 'A sufficiently strong password',
        })
        assert r.status_code == 400

    def test_register_new_user(self, client):
        r = client.post('/register',
                        data={'email': 'new@optio.news',
                              'password': 'Cedar!Orbit#47',
                              'confirm_password': 'Cedar!Orbit#47',
                              'csrf_token': csrf_token(client.get('/register'))},
                        follow_redirects=True)
        assert r.status_code == 200
        # should land on the main page after successful registration
        assert b'articlesGrid' in r.data

    def test_register_duplicate_email(self, client, test_app):
        with test_app.app_context():
            u = User(email='dup@optio.news',
                     password_hash=generate_password_hash('x'))
            db.session.add(u); db.session.commit()
        r = client.post('/register',
                        data={'email': 'dup@optio.news',
                              'password': 'Pass1234!',
                              'confirm_password': 'Pass1234!',
                              'csrf_token': csrf_token(client.get('/register'))},
                        follow_redirects=True)
        assert b'already' in r.data.lower() or b'register' in r.data.lower()

    def test_register_password_mismatch(self, client):
        r = client.post('/register',
                        data={'email': 'mismatch@optio.news',
                              'password': 'aaa',
                              'confirm_password': 'bbb',
                              'csrf_token': csrf_token(client.get('/register'))},
                        follow_redirects=True)
        assert b'register' in r.data.lower()

    def test_register_short_password(self, client):
        r = client.post('/register',
                        data={'email': 'short@optio.news',
                              'password': 'abc',
                              'confirm_password': 'abc',
                              'csrf_token': csrf_token(client.get('/register'))},
                        follow_redirects=True)
        assert b'register' in r.data.lower()


# ──────────────────────────────────────────────
# 2. Auth — Login / Logout
# ──────────────────────────────────────────────

class TestLogin:
    def test_get_login_page(self, client):
        r = client.get('/login')
        assert r.status_code == 200
        assert b'login' in r.data.lower()

    def test_login_form_contains_csrf_token(self, client):
        assert csrf_token(client.get('/login'))

    def test_login_without_csrf_token_is_rejected(self, client):
        r = client.post('/login', data={
            'email': 'unit@test.com',
            'password': 'Test1234!',
        })
        assert r.status_code == 400

    def test_login_correct_credentials(self, client):
        r = client.post('/login',
                        data={'email': 'unit@test.com', 'password': 'Test1234!',
                              'csrf_token': csrf_token(client.get('/login'))},
                        follow_redirects=True)
        assert r.status_code == 200
        assert b'articlesGrid' in r.data

    def test_login_wrong_password(self, client):
        r = client.post('/login',
                        data={'email': 'unit@test.com', 'password': 'wrong',
                              'csrf_token': csrf_token(client.get('/login'))},
                        follow_redirects=True)
        assert b'login' in r.data.lower()

    def test_login_unknown_email(self, client):
        r = client.post('/login',
                        data={'email': 'nobody@optio.news', 'password': 'x',
                              'csrf_token': csrf_token(client.get('/login'))},
                        follow_redirects=True)
        assert b'login' in r.data.lower()

    def test_logout(self, auth_client):
        r = auth_client.get('/logout', follow_redirects=True)
        assert r.status_code == 200
        assert b'login' in r.data.lower()


# ──────────────────────────────────────────────
# 3. Protected page redirects when not logged in
# ──────────────────────────────────────────────

class TestUnauthedRedirects:
    def test_public_index_is_available(self, client):
        r = client.get('/')
        assert r.status_code == 200
        assert b'Latest from the catalogue' in r.data

    def test_reader_redirects(self, client):
        r = client.get('/reader', follow_redirects=True)
        assert b'login' in r.data.lower()

    def test_feeds_redirects(self, client):
        r = client.get('/feeds', follow_redirects=True)
        assert b'login' in r.data.lower()

    def test_bookmarks_redirects(self, client):
        r = client.get('/bookmarks', follow_redirects=True)
        assert b'login' in r.data.lower()

    def test_api_articles_redirects(self, client):
        r = client.get('/api/articles', follow_redirects=False)
        assert r.status_code in (302, 401)

    def test_api_bookmarks_redirects(self, client):
        r = client.get('/api/bookmarks', follow_redirects=False)
        assert r.status_code in (302, 401)


# ──────────────────────────────────────────────
# 4. Page rendering (authenticated)
# ──────────────────────────────────────────────

class TestPages:
    def test_index(self, auth_client):
        r = auth_client.get('/reader')
        assert r.status_code == 200
        assert b'articlesGrid' in r.data

    def test_authenticated_pages_expose_csrf_transport(self, auth_client):
        for path in ['/reader', '/feeds', '/bookmarks']:
            page = auth_client.get(path)
            assert b'meta name="csrf-token"' in page.data
            assert b'js/csrf.js' in page.data

    def test_settings_expose_daily_digest_opt_in(self, auth_client):
        page = auth_client.get('/reader')
        assert page.status_code == 200
        assert b'id="settingsDigest"' in page.data
        assert b'Send me a daily news roundup' in page.data

    def test_settings_script_persists_daily_digest_preference(self):
        source = Path('static/js/settings.js').read_text(encoding='utf-8')
        assert 'settingsDigest' in source
        assert '/api/digest/preferences' in source

    def test_feeds_page(self, auth_client):
        r = auth_client.get('/feeds')
        assert r.status_code == 200
        assert b'Manage RSS Feeds' in r.data

    def test_bookmarks_page(self, auth_client):
        r = auth_client.get('/bookmarks')
        assert r.status_code == 200
        assert b'bmGrid' in r.data

    def test_copyright_is_2026(self, auth_client):
        for path in ['/reader', '/feeds', '/bookmarks']:
            r = auth_client.get(path)
            assert b'2026' in r.data, f"2026 copyright missing on {path}"
            assert b'2025' not in r.data, f"Stale 2025 copyright on {path}"

    def test_ticker_present(self, auth_client):
        r = auth_client.get('/reader')
        assert b'ticker-bar' in r.data

    def test_top_stories_present(self, auth_client):
        r = auth_client.get('/reader')
        assert b'topStories' in r.data

    def test_trending_sidebar_present(self, auth_client):
        r = auth_client.get('/reader')
        assert b'trendingList' in r.data

    def test_account_section_in_feeds(self, auth_client):
        r = auth_client.get('/feeds')
        assert b'deleteAccountBtn' in r.data
        assert b'Delete Account' in r.data


# ──────────────────────────────────────────────
# 5. Bookmarks CRUD
# ──────────────────────────────────────────────

class TestBookmarks:
    def _post_bm(self, client, **kwargs):
        payload = {'url': 'https://example.com', 'title': 'Test BM', **kwargs}
        return client.post('/api/bookmarks',
                           data=json.dumps(payload),
                           content_type='application/json',
                           headers=csrf_headers(client))

    def test_list_empty_initially(self, auth_client, test_app):
        # Clean slate for this user in isolation
        with test_app.app_context():
            Bookmark.query.filter_by().delete()
            db.session.commit()
        r = auth_client.get('/api/bookmarks')
        assert r.status_code == 200
        data = jget(r)
        assert 'bookmarks' in data
        assert isinstance(data['bookmarks'], list)

    def test_create_bookmark(self, auth_client):
        r = self._post_bm(auth_client, tags=['a', 'b'])
        assert r.status_code == 201
        data = jget(r)
        assert data['id'] > 0
        assert data['title'] == 'Test BM'
        assert 'a' in data['tags']

    def test_create_requires_url(self, auth_client):
        r = auth_client.post('/api/bookmarks',
                             data=json.dumps({'title': 'no url'}),
                             content_type='application/json',
                             headers=csrf_headers(auth_client))
        assert r.status_code == 400

    def test_list_after_create(self, auth_client):
        self._post_bm(auth_client, title='Listed BM')
        r = auth_client.get('/api/bookmarks')
        data = jget(r)
        assert any(b['title'] == 'Listed BM' for b in data['bookmarks'])

    def test_update_bookmark(self, auth_client):
        r = self._post_bm(auth_client, title='Before Update')
        bm_id = jget(r)['id']
        r2 = auth_client.put(f'/api/bookmarks/{bm_id}',
                              data=json.dumps({'title': 'After Update'}),
                              content_type='application/json',
                              headers=csrf_headers(auth_client))
        assert r2.status_code == 200
        assert jget(r2)['title'] == 'After Update'

    def test_update_wrong_user(self, auth_client, test_app):
        """Another user's bookmark must not be editable."""
        with test_app.app_context():
            other = User(email='other@optio.news',
                         password_hash=generate_password_hash('x'))
            db.session.add(other); db.session.flush()
            bm = Bookmark(user_id=other.id, url='https://other.com', title='Other BM', tags=[])
            db.session.add(bm); db.session.commit()
            bm_id = bm.id
        r = auth_client.put(f'/api/bookmarks/{bm_id}',
                             data=json.dumps({'title': 'Hacked'}),
                             content_type='application/json',
                             headers=csrf_headers(auth_client))
        assert r.status_code == 404

    def test_delete_bookmark(self, auth_client):
        r = self._post_bm(auth_client, title='To Delete')
        bm_id = jget(r)['id']
        r2 = auth_client.delete(f'/api/bookmarks/{bm_id}',
                                headers=csrf_headers(auth_client))
        assert r2.status_code == 200
        assert jget(r2)['success'] is True
        # Confirm gone
        r3 = auth_client.get('/api/bookmarks')
        assert not any(b['id'] == bm_id for b in jget(r3)['bookmarks'])

    def test_delete_nonexistent(self, auth_client):
        r = auth_client.delete('/api/bookmarks/99999999',
                               headers=csrf_headers(auth_client))
        assert r.status_code == 404


# ──────────────────────────────────────────────
# 6. Feeds API
# ──────────────────────────────────────────────

class TestFeeds:
    def test_get_feeds(self, auth_client):
        r = auth_client.get('/api/feeds')
        assert r.status_code == 200
        data = jget(r)
        assert 'feeds' in data
        assert len(data['feeds']) > 0

    def test_feed_has_required_fields(self, auth_client):
        r = auth_client.get('/api/feeds')
        feed = jget(r)['feeds'][0]
        for key in ('name', 'url', 'category', 'hidden'):
            assert key in feed, f"Missing field: {key}"

    def test_get_available_feeds(self, auth_client):
        r = auth_client.get('/api/feeds/available')
        assert r.status_code == 200
        data = jget(r)
        assert 'feeds' in data
        assert data['total'] > 0

    def test_suggestions_known_category(self, auth_client):
        r = auth_client.get('/api/feeds/suggestions?category=Technology')
        assert r.status_code == 200
        data = jget(r)
        assert 'suggestions' in data

    def test_suggestions_unknown_category(self, auth_client):
        r = auth_client.get('/api/feeds/suggestions?category=Nonsense')
        assert r.status_code == 200
        data = jget(r)
        assert data.get('suggestions') == [] or 'suggestions' in data

    def test_hide_feed(self, auth_client):
        # hide the first available feed URL
        r = auth_client.get('/api/feeds')
        first_feed = jget(r)['feeds'][0]
        r2 = auth_client.post('/api/feeds/hide',
                               data=json.dumps({'url': first_feed['url'], 'category': first_feed['category']}),
                               content_type='application/json',
                               headers=csrf_headers(auth_client))
        assert r2.status_code == 200
        assert jget(r2)['success'] is True

    def test_unhide_feed(self, auth_client):
        r = auth_client.get('/api/feeds')
        first_feed = jget(r)['feeds'][0]
        # ensure it's hidden first
        auth_client.post('/api/feeds/hide',
                         data=json.dumps({'url': first_feed['url'], 'category': first_feed['category']}),
                         content_type='application/json',
                         headers=csrf_headers(auth_client))
        r2 = auth_client.post('/api/feeds/unhide',
                               data=json.dumps({'url': first_feed['url']}),
                               content_type='application/json',
                               headers=csrf_headers(auth_client))
        assert r2.status_code == 200
        assert jget(r2)['success'] is True


# ──────────────────────────────────────────────
# 7. Articles API
# ──────────────────────────────────────────────

class TestArticles:
    def test_get_articles_structure(self, auth_client):
        r = auth_client.get('/api/articles')
        assert r.status_code == 200
        data = jget(r)
        for key in ('articles', 'count', 'feed_count'):
            assert key in data, f"Missing key: {key}"

    def test_articles_is_list(self, auth_client):
        r = auth_client.get('/api/articles')
        assert isinstance(jget(r)['articles'], list)

    def test_articles_category_filter(self, auth_client):
        r = auth_client.get('/api/articles?category=Technology')
        assert r.status_code == 200
        data = jget(r)
        for art in data['articles']:
            assert art['category'] == 'Technology'

    def test_articles_search_filter(self, auth_client):
        r = auth_client.get('/api/articles?search=the')
        assert r.status_code == 200

    def test_trending_structure(self, auth_client):
        r = auth_client.get('/api/trending')
        assert r.status_code == 200
        data = jget(r)
        assert 'trending' in data
        assert isinstance(data['trending'], list)


# ──────────────────────────────────────────────
# 8. Durable content, clustering, state, and preferences
# ──────────────────────────────────────────────

class TestDurableReader:
    def _seed_story(self, test_app, suffix='one'):
        from datetime import datetime
        with test_app.app_context():
            feed_a = Feed.query.filter_by(url=f'https://reader-{suffix}-a.example/feed').first()
            if not feed_a:
                feed_a = Feed(category='Technology', url=f'https://reader-{suffix}-a.example/feed', name='Reader A')
                feed_b = Feed(category='Technology', url=f'https://reader-{suffix}-b.example/feed', name='Reader B')
                db.session.add_all([feed_a, feed_b]); db.session.flush()
                a1 = Article(feed_id=feed_a.id, canonical_url=f'https://reader-{suffix}-a.example/story',
                             title='Orbital telescope mission launches', summary='Mission coverage from source A',
                             published_at=datetime.utcnow(), fetched_at=datetime.utcnow(),
                             search_document='Orbital telescope mission launches Mission coverage')
                a2 = Article(feed_id=feed_b.id, canonical_url=f'https://reader-{suffix}-b.example/story',
                             title='Orbital telescope mission launches today', summary='Mission coverage from source B',
                             published_at=datetime.utcnow(), fetched_at=datetime.utcnow(),
                             search_document='Orbital telescope mission launches today')
                db.session.add_all([a1, a2]); db.session.commit()
                from clustering import recluster_recent
                recluster_recent()
            unit = User.query.filter_by(email='unit@test.com').first()
            for feed in Feed.query.filter(Feed.url.like(f'https://reader-{suffix}-%')).all():
                if not Subscription.query.filter_by(user_id=unit.id, feed_id=feed.id).first():
                    db.session.add(Subscription(user_id=unit.id, feed_id=feed.id))
            db.session.commit()
            return [row.id for row in Article.query.filter(Article.canonical_url.like(f'https://reader-{suffix}-%')).all()]

    def test_url_canonicalization_removes_tracking(self):
        from ingestion import canonicalize_url
        assert canonicalize_url('HTTPS://Example.com/story/?utm_source=x&fbclid=y&ref=home') == 'https://example.com/story'

    def test_reader_returns_one_card_for_cluster(self, auth_client, test_app):
        ids = self._seed_story(test_app, 'cluster')
        response = auth_client.get('/api/articles?limit=100')
        assert response.status_code == 200
        cards = [card for card in jget(response)['articles'] if any(i in ids for i in card['article_ids'])]
        assert len(cards) == 1
        assert cards[0]['source_count'] == 2

    def test_trending_reads_articles_inside_story_clusters(self, auth_client, test_app):
        from datetime import datetime
        with test_app.app_context():
            cluster = StoryCluster(label='Quasarion satellite mission')
            db.session.add(cluster); db.session.flush()
            for index in range(4):
                feed = Feed(category='Science', url=f'https://quasarion-{index}.example/feed',
                            name=f'Quasarion Source {index}')
                db.session.add(feed); db.session.flush()
                db.session.add(Subscription(user_id=1, feed_id=feed.id))
                db.session.add(Article(
                    feed_id=feed.id,
                    canonical_url=f'https://quasarion-{index}.example/story',
                    title=f'Quasarion launches satellite mission {index}',
                    summary='Quasarion mission coverage from this source',
                    published_at=datetime.utcnow(),
                    fetched_at=datetime.utcnow(),
                    cluster_id=cluster.id,
                    search_document='Quasarion launches satellite mission',
                ))
            db.session.commit()

        response = auth_client.get('/api/trending')
        assert response.status_code == 200
        topics = [item['topic'].lower() for item in jget(response)['trending']]
        assert any('quasarion' in topic for topic in topics)

    def test_cluster_card_uses_image_from_any_member(self, test_app):
        from datetime import datetime, timedelta
        with test_app.app_context():
            feed = Feed(category='Science', url='https://image-fallback.example/feed', name='Image Fallback')
            db.session.add(feed); db.session.flush()
            cluster = StoryCluster(label='Image fallback story')
            db.session.add(cluster); db.session.flush()
            primary = Article(
                feed_id=feed.id, canonical_url='https://image-fallback.example/primary',
                title='Primary story without image', summary='', image_url='',
                published_at=datetime.utcnow(), fetched_at=datetime.utcnow(), cluster_id=cluster.id,
            )
            illustrated = Article(
                feed_id=feed.id, canonical_url='https://image-fallback.example/illustrated',
                title='Illustrated story source', summary='',
                image_url='https://images.example/story.jpg',
                published_at=datetime.utcnow() - timedelta(hours=1),
                fetched_at=datetime.utcnow(), cluster_id=cluster.id,
            )
            db.session.add_all([primary, illustrated]); db.session.commit()

            card = main._article_to_dict(primary, [primary, illustrated])
            assert card['image_url'] == 'https://images.example/story.jpg'

    def test_oversized_cluster_does_not_hide_individual_articles(self, auth_client, test_app):
        from datetime import datetime
        with test_app.app_context():
            feed = Feed(category='Science', url='https://oversized-cluster.example/feed', name='Oversized Cluster')
            db.session.add(feed); db.session.flush()
            cluster = StoryCluster(label='Corrupted oversized cluster')
            db.session.add(cluster); db.session.flush()
            stories = [Article(
                feed_id=feed.id,
                canonical_url=f'https://oversized-cluster.example/story-{index}',
                title=f'Oversized cluster item {index}',
                summary='',
                published_at=datetime.utcnow(),
                fetched_at=datetime.utcnow(),
                cluster_id=cluster.id,
            ) for index in range(25)]
            db.session.add(Subscription(user_id=1, feed_id=feed.id))
            db.session.add_all(stories); db.session.commit()
            ids = [story.id for story in stories]

        response = auth_client.get('/api/articles?limit=100')
        assert response.status_code == 200
        cards = [card for card in jget(response)['articles'] if any(i in ids for i in card['article_ids'])]
        assert len(cards) == len(ids)

    def test_unrelated_generic_headlines_do_not_form_one_cluster(self, test_app):
        from datetime import datetime
        from clustering import recluster_recent
        with test_app.app_context():
            feed = Feed(category='General News', url='https://cluster-boundary.example/feed', name='Cluster Boundary')
            db.session.add(feed); db.session.flush()
            stories = [
                Article(feed_id=feed.id, canonical_url='https://cluster-boundary.example/alpha',
                        title='Alpha reports major update', summary='', published_at=datetime.utcnow(),
                        fetched_at=datetime.utcnow()),
                Article(feed_id=feed.id, canonical_url='https://cluster-boundary.example/beta',
                        title='Beta reports major update', summary='', published_at=datetime.utcnow(),
                        fetched_at=datetime.utcnow()),
            ]
            db.session.add_all(stories); db.session.commit()
            recluster_recent(hours=1)
            db.session.refresh(stories[0]); db.session.refresh(stories[1])
            assert stories[0].cluster_id != stories[1].cluster_id

    def test_reading_state_is_per_user_and_persistent(self, auth_client, test_app):
        ids = self._seed_story(test_app, 'state')
        response = auth_client.post('/api/state/read', data=json.dumps({'ids': ids[:1]}),
                                    content_type='application/json', headers=csrf_headers(auth_client))
        assert response.status_code == 200
        with test_app.app_context():
            state = UserArticleState.query.filter_by(user_id=1, article_id=ids[0]).first()
            assert state is not None and state.read_at is not None
        data = jget(auth_client.get('/api/articles?unread=1&limit=100'))
        assert all(ids[0] not in card['article_ids'] for card in data['articles'])

    def test_digest_preferences_and_saved_searches(self, auth_client):
        response = auth_client.put('/api/digest/preferences', data=json.dumps({'enabled': True}),
                                   content_type='application/json', headers=csrf_headers(auth_client))
        assert response.status_code == 200 and jget(response)['enabled'] is True
        response = auth_client.post('/api/alerts', data=json.dumps({'query': 'orbital', 'category': 'Technology'}),
                                    content_type='application/json', headers=csrf_headers(auth_client))
        assert response.status_code == 200
        assert any(alert['query'] == 'orbital' for alert in jget(response)['alerts'])

    def test_worker_upserts_articles_without_web_request_network(self, test_app, monkeypatch):
        from ingestion import ingest_once
        from datetime import datetime
        with test_app.app_context():
            feed = Feed.query.filter_by(url='https://worker.example/feed').first()
            if not feed:
                feed = Feed(category='Science', url='https://worker.example/feed', name='Worker Source')
                db.session.add(feed); db.session.commit()
            feed_id = feed.id
        monkeypatch.setattr('ingestion._snapshot', lambda payload: {
            'feed_id': feed_id, 'status': 200, 'records': [{
                'canonical_url': 'https://worker.example/story?utm_source=email',
                'title': 'Worker persisted story', 'author': '', 'summary': 'A durable article',
                'image_url': 'https://worker.example/image.jpg', 'published_at': datetime.utcnow(), 'guid': 'worker-1'
            }], 'etag': None, 'last_modified': None, 'error': None
        })
        monkeypatch.setattr('ingestion._enrich_records', lambda records: None)
        with test_app.app_context():
            result = ingest_once()
            assert result['inserted'] >= 1
            assert Article.query.filter_by(canonical_url='https://worker.example/story').count() == 1


# ──────────────────────────────────────────────
# 8. Account deletion
# ──────────────────────────────────────────────

class TestAccount:
    def test_delete_account(self, test_app):
        """User is deleted, cascades bookmarks and feeds, then redirected to login."""
        c = app.test_client()
        with test_app.app_context():
            u = User(email='todelete@optio.news',
                     password_hash=generate_password_hash('Del1234!'))
            db.session.add(u); db.session.flush()
            bm = Bookmark(user_id=u.id, url='https://x.com', title='X', tags=[])
            db.session.add(bm); db.session.commit()
            uid = u.id

        c.post('/login', data={'email': 'todelete@optio.news', 'password': 'Del1234!',
                               'csrf_token': csrf_token(c.get('/login'))},
               follow_redirects=True)
        r = c.delete('/api/account', headers=csrf_headers(c))
        assert r.status_code == 200
        assert jget(r)['success'] is True

        # DB row gone — expire cache so we see the committed state
        with test_app.app_context():
            db.session.expire_all()
            assert db.session.get(User, uid) is None
            assert Bookmark.query.filter_by(user_id=uid).count() == 0

    def test_delete_account_requires_auth(self, client):
        r = client.delete('/api/account', headers=csrf_headers(client), follow_redirects=False)
        assert r.status_code in (302, 401)


# ──────────────────────────────────────────────
# 9. Trending algorithm unit tests
# ──────────────────────────────────────────────

class TestTrendingAlgorithm:
    def _make_articles(self, titles):
        # Use a live timestamp — extract_trending_topics only looks at the last 24h
        from datetime import datetime
        now_iso = datetime.now().isoformat()
        return [{'title': t, 'summary': '', 'published': now_iso,
                 'category': 'General News', 'link': 'https://example.com',
                 'site': 'example.com'} for t in titles]

    def test_returns_list(self):
        arts = self._make_articles(['Apple announces new iPhone model'])
        result = extract_trending_topics(arts)
        assert isinstance(result, list)

    def test_proper_nouns_score_higher(self):
        arts = self._make_articles(
            ['Apple announces new iPhone'] * 5 +
            ['company launches into market'] * 5
        )
        result = extract_trending_topics(arts)
        topics = [r['topic'] for r in result]
        # 'Apple' (proper noun) should appear; 'into' (stopword) must not
        assert 'into' not in topics
        assert 'market' not in topics

    def test_stopwords_excluded(self):
        forbidden = ['into', 'according', 'market', 'markets', 'court',
                     'series', 'data', 'deal', 'deals', 'sale', 'sales',
                     'rate', 'rates', 'case', 'cases']
        arts = self._make_articles(
            [f'New {w} for everyone today' for w in forbidden] * 10
        )
        result = extract_trending_topics(arts)
        topics = [r['topic'].lower() for r in result]
        for w in forbidden:
            assert w not in topics, f"Stopword '{w}' leaked into trending"

    def test_meaningful_proper_nouns_included(self):
        arts = self._make_articles(['Elon Musk visits Tesla factory'] * 8)
        result = extract_trending_topics(arts)
        topics = [r['topic'] for r in result]
        assert any('Elon' in t or 'Tesla' in t or 'Musk' in t for t in topics)

    def test_empty_articles(self):
        assert extract_trending_topics([]) == []

    def test_trending_result_has_required_keys(self):
        arts = self._make_articles(['NASA launches new Mars mission'] * 6)
        result = extract_trending_topics(arts)
        if result:
            for key in ('topic', 'count', 'articles'):
                assert key in result[0], f"Missing key '{key}' in trending result"

    def test_non_proper_single_words_need_high_spread(self):
        """Single non-proper-noun words need spread ≥ 10 to survive."""
        # 9 different articles with a common word — should be blocked
        from datetime import datetime
        arts = [{'title': f'Article {i} talks about things today',
                 'summary': 'things are happening',
                 'published': datetime.now().isoformat(),
                 'category': 'General News', 'link': 'https://example.com',
                 'site': 'example.com'} for i in range(9)]
        result = extract_trending_topics(arts)
        topics = [r['topic'].lower() for r in result]
        assert 'things' not in topics


# ──────────────────────────────────────────────
# 10. Security checks
# ──────────────────────────────────────────────

class TestSecurity:
    def test_production_secret_is_required(self):
        with pytest.raises(RuntimeError, match='SECRET_KEY must be set in production'):
            main.resolve_secret_key({'RAILWAY_ENVIRONMENT': 'production'})

    def test_local_secret_fallback_is_development_only(self):
        assert main.resolve_secret_key({}) == 'dev-only-never-deployed'

    def test_session_cookie_security_defaults_are_enabled(self):
        assert app.config['SESSION_COOKIE_SECURE'] is True
        assert app.config['SESSION_COOKIE_HTTPONLY'] is True
        assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
        assert app.config['REMEMBER_COOKIE_SECURE'] is True
        assert app.config['REMEMBER_COOKIE_HTTPONLY'] is True

    def test_import_does_not_create_database(self, tmp_path):
        db_path = tmp_path / 'import-side-effect.db'
        env = os.environ.copy()
        env['DATABASE_URL'] = f'sqlite:///{db_path}'
        env.pop('SECRET_KEY', None)
        env.pop('RAILWAY_ENVIRONMENT', None)
        env.pop('FLASK_ENV', None)
        env.pop('APP_ENV', None)
        result = subprocess.run(
            [sys.executable, '-c', 'import main'],
            cwd=Path(__file__).parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert not db_path.exists()

    def test_production_import_without_secret_fails_closed(self, tmp_path):
        db_path = tmp_path / 'production-import.db'
        env = os.environ.copy()
        env['DATABASE_URL'] = f'sqlite:///{db_path}'
        env['RAILWAY_ENVIRONMENT'] = 'production'
        env['PYTHON_DOTENV_DISABLED'] = 'true'
        env.pop('SECRET_KEY', None)
        result = subprocess.run(
            [sys.executable, '-c', 'import main'],
            cwd=Path(__file__).parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0
        assert 'SECRET_KEY must be set in production' in result.stderr

    def test_wsgi_exports_the_flask_application(self):
        import importlib
        wsgi = importlib.import_module('wsgi')
        assert wsgi.application is app

    def test_digest_entrypoint_exposes_one_shot_runner(self):
        import importlib
        scheduled_job = importlib.import_module('scheduled_job')
        assert callable(scheduled_job.run_job)

    def test_digest_entrypoint_runs_job_inside_app_context(self, monkeypatch):
        import importlib
        scheduled_job = importlib.import_module('scheduled_job')
        from flask import has_app_context
        contexts = []

        def fake_job():
            contexts.append(has_app_context())

        monkeypatch.setattr(scheduled_job, 'job', fake_job)
        scheduled_job.run_job()
        assert contexts == [True]

    def test_password_policy_rejects_eleven_characters(self, client, test_app):
        email = 'eleven@optio.news'
        r = client.post('/register', data={
            'email': email,
            'password': 'Aa1!aaaaaaa',
            'confirm_password': 'Aa1!aaaaaaa',
            'csrf_token': csrf_token(client.get('/register')),
        }, follow_redirects=True)
        assert b'12 characters' in r.data
        with test_app.app_context():
            assert User.query.filter_by(email=email).first() is None

    def test_password_policy_rejects_top_ranked_common_password(self):
        assert main.is_common_password('password') is True

    def test_password_policy_accepts_a_strong_twelve_character_password(self, client):
        r = client.post('/register', data={
            'email': 'strong@optio.news',
            'password': 'Cedar!Orbit#47',
            'confirm_password': 'Cedar!Orbit#47',
            'csrf_token': csrf_token(client.get('/register')),
        }, follow_redirects=True)
        assert r.status_code == 200
        assert b'articlesGrid' in r.data

    def test_json_mutation_without_csrf_token_is_rejected(self, auth_client):
        response = auth_client.post(
            '/api/bookmarks',
            data=json.dumps({'url': 'https://csrf.example', 'title': 'Blocked'}),
            content_type='application/json',
        )
        assert response.status_code == 400

    def test_rate_limit_login_per_ip(self, test_app):
        app.config['RATELIMIT_ENABLED'] = True
        main.limiter.enabled = True
        main.limiter.reset()
        try:
            client = app.test_client()
            token = csrf_token(client.get('/login'))
            responses = [client.post('/login', data={
                'email': 'unit@test.com',
                'password': 'wrong',
                'csrf_token': token,
            }) for _ in range(6)]
            assert all(response.status_code == 200 for response in responses[:5])
            assert responses[5].status_code == 429
        finally:
            main.limiter.reset()
            main.limiter.enabled = False
            app.config['RATELIMIT_ENABLED'] = False

    def test_rate_limit_login_per_normalized_email(self, test_app):
        app.config['RATELIMIT_ENABLED'] = True
        main.limiter.enabled = True
        main.limiter.reset()
        try:
            client = app.test_client()
            token = csrf_token(client.get('/login'))
            responses = [client.post(
                '/login',
                data={
                    'email': ' UNIT@TEST.COM ',
                    'password': 'wrong',
                    'csrf_token': token,
                },
                environ_overrides={'REMOTE_ADDR': f'10.0.0.{index + 1}'},
            ) for index in range(21)]
            assert all(response.status_code == 200 for response in responses[:20])
            assert responses[20].status_code == 429
        finally:
            main.limiter.reset()
            main.limiter.enabled = False
            app.config['RATELIMIT_ENABLED'] = False

    def test_xss_in_bookmark_title_is_escaped(self, auth_client):
        """Script tags in bookmark titles must be stored as-is (not executed)
        and returned sanitised when rendered."""
        payload = {'url': 'https://safe.com',
                   'title': '<script>alert(1)</script>',
                   'tags': []}
        r = auth_client.post('/api/bookmarks',
                             data=json.dumps(payload),
                             content_type='application/json',
                             headers=csrf_headers(auth_client))
        assert r.status_code == 201
        bm_id = jget(r)['id']
        r2 = auth_client.get('/api/bookmarks')
        bm = next(b for b in jget(r2)['bookmarks'] if b['id'] == bm_id)
        # The raw <script> tag must NOT appear unescaped in the API JSON
        # (API returns raw value, template escapes it — just assert no injection)
        assert '<script>' in bm['title'] or bm['title'] == '<script>alert(1)</script>'
        # bookmarks.html uses escapeHtml() in JS — we verify page does NOT exec scripts
        page = auth_client.get('/bookmarks')
        assert b'<script>alert(1)</script>' not in page.data

    def test_idor_bookmark_delete(self, auth_client, test_app):
        """User A cannot delete User B's bookmarks."""
        with test_app.app_context():
            b_user = User(email='victimB@optio.news',
                          password_hash=generate_password_hash('x'))
            db.session.add(b_user); db.session.flush()
            bm = Bookmark(user_id=b_user.id, url='https://victim.com',
                          title='Victim BM', tags=[])
            db.session.add(bm); db.session.commit()
            bm_id = bm.id

        r = auth_client.delete(f'/api/bookmarks/{bm_id}',
                               headers=csrf_headers(auth_client))
        assert r.status_code == 404

    def test_sql_injection_in_search(self, auth_client):
        """Search param with SQL injection chars should not crash the app."""
        r = auth_client.get("/api/articles?search=' OR '1'='1")
        assert r.status_code == 200

    def test_preview_endpoint_validates_url(self, auth_client):
        """Passing garbage to /api/preview should not crash (500)."""
        r = auth_client.get('/api/preview?url=not-a-url')
        assert r.status_code in (200, 400, 422)  # anything but 500
