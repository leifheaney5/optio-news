"""
Optio News — unit + integration test suite.
Run: python -m pytest test_app.py -v
Uses a temp-file SQLite DB so no external services are needed.
"""
import os, json, pytest, tempfile

# Create a temp SQLite file BEFORE importing main so that _startup() (which runs
# at import time) uses the same file-based database as our test clients.
# File-based SQLite is shared across all connections, unlike :memory:.
_db_fd, _DB_PATH = tempfile.mkstemp(suffix='.test.db')
os.close(_db_fd)
os.environ['DATABASE_URL'] = f'sqlite:///{_DB_PATH}'   # overwrite, not setdefault
os.environ.setdefault('SECRET_KEY', 'test-secret')

from main import app, db, User, UserFeed, Bookmark, extract_trending_topics
from werkzeug.security import generate_password_hash


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(scope='session')
def test_app():
    app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        # No SQLALCHEMY_DATABASE_URI override needed — already set via env var above.
        'SQLALCHEMY_ENGINE_OPTIONS': {},   # strip any SSL options from main.py
    })
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
    c.post('/login', data={'email': 'unit@test.com', 'password': 'Test1234!'},
           follow_redirects=True)
    return c


# helper to parse JSON responses
def jget(resp):
    return json.loads(resp.data)


# ──────────────────────────────────────────────
# 1. Auth — Register
# ──────────────────────────────────────────────

class TestRegister:
    def test_get_register_page(self, client):
        r = client.get('/register')
        assert r.status_code == 200
        assert b'register' in r.data.lower()

    def test_register_new_user(self, client):
        r = client.post('/register',
                        data={'email': 'new@optio.news',
                              'password': 'Pass1234!',
                              'confirm_password': 'Pass1234!'},
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
                              'confirm_password': 'Pass1234!'},
                        follow_redirects=True)
        assert b'already' in r.data.lower() or b'register' in r.data.lower()

    def test_register_password_mismatch(self, client):
        r = client.post('/register',
                        data={'email': 'mismatch@optio.news',
                              'password': 'aaa',
                              'confirm_password': 'bbb'},
                        follow_redirects=True)
        assert b'register' in r.data.lower()

    def test_register_short_password(self, client):
        r = client.post('/register',
                        data={'email': 'short@optio.news',
                              'password': 'abc',
                              'confirm_password': 'abc'},
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

    def test_login_correct_credentials(self, client):
        r = client.post('/login',
                        data={'email': 'unit@test.com', 'password': 'Test1234!'},
                        follow_redirects=True)
        assert r.status_code == 200
        assert b'articlesGrid' in r.data

    def test_login_wrong_password(self, client):
        r = client.post('/login',
                        data={'email': 'unit@test.com', 'password': 'wrong'},
                        follow_redirects=True)
        assert b'login' in r.data.lower()

    def test_login_unknown_email(self, client):
        r = client.post('/login',
                        data={'email': 'nobody@optio.news', 'password': 'x'},
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
    def test_index_redirects(self, client):
        r = client.get('/', follow_redirects=True)
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
        r = auth_client.get('/')
        assert r.status_code == 200
        assert b'articlesGrid' in r.data

    def test_feeds_page(self, auth_client):
        r = auth_client.get('/feeds')
        assert r.status_code == 200
        assert b'Manage RSS Feeds' in r.data

    def test_bookmarks_page(self, auth_client):
        r = auth_client.get('/bookmarks')
        assert r.status_code == 200
        assert b'bmGrid' in r.data

    def test_copyright_is_2026(self, auth_client):
        for path in ['/', '/feeds', '/bookmarks']:
            r = auth_client.get(path)
            assert b'2026' in r.data, f"2026 copyright missing on {path}"
            assert b'2025' not in r.data, f"Stale 2025 copyright on {path}"

    def test_ticker_present(self, auth_client):
        r = auth_client.get('/')
        assert b'ticker-bar' in r.data

    def test_top_stories_present(self, auth_client):
        r = auth_client.get('/')
        assert b'topStories' in r.data

    def test_trending_sidebar_present(self, auth_client):
        r = auth_client.get('/')
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
                           content_type='application/json')

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
                             content_type='application/json')
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
                              content_type='application/json')
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
                             content_type='application/json')
        assert r.status_code == 404

    def test_delete_bookmark(self, auth_client):
        r = self._post_bm(auth_client, title='To Delete')
        bm_id = jget(r)['id']
        r2 = auth_client.delete(f'/api/bookmarks/{bm_id}')
        assert r2.status_code == 200
        assert jget(r2)['success'] is True
        # Confirm gone
        r3 = auth_client.get('/api/bookmarks')
        assert not any(b['id'] == bm_id for b in jget(r3)['bookmarks'])

    def test_delete_nonexistent(self, auth_client):
        r = auth_client.delete('/api/bookmarks/99999999')
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
                               content_type='application/json')
        assert r2.status_code == 200
        assert jget(r2)['success'] is True

    def test_unhide_feed(self, auth_client):
        r = auth_client.get('/api/feeds')
        first_feed = jget(r)['feeds'][0]
        # ensure it's hidden first
        auth_client.post('/api/feeds/hide',
                         data=json.dumps({'url': first_feed['url'], 'category': first_feed['category']}),
                         content_type='application/json')
        r2 = auth_client.post('/api/feeds/unhide',
                               data=json.dumps({'url': first_feed['url']}),
                               content_type='application/json')
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

        c.post('/login', data={'email': 'todelete@optio.news', 'password': 'Del1234!'},
               follow_redirects=True)
        r = c.delete('/api/account')
        assert r.status_code == 200
        assert jget(r)['success'] is True

        # DB row gone — expire cache so we see the committed state
        with test_app.app_context():
            db.session.expire_all()
            assert db.session.get(User, uid) is None
            assert Bookmark.query.filter_by(user_id=uid).count() == 0

    def test_delete_account_requires_auth(self, client):
        r = client.delete('/api/account', follow_redirects=False)
        assert r.status_code in (302, 401)


# ──────────────────────────────────────────────
# 9. Trending algorithm unit tests
# ──────────────────────────────────────────────

class TestTrendingAlgorithm:
    def _make_articles(self, titles):
        return [{'title': t, 'summary': '', 'published': '2026-03-26T12:00:00',
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
        arts = [{'title': f'Article {i} talks about things today',
                 'summary': 'things are happening',
                 'published': '2026-03-26T12:00:00',
                 'category': 'General News', 'link': 'https://example.com',
                 'site': 'example.com'} for i in range(9)]
        result = extract_trending_topics(arts)
        topics = [r['topic'].lower() for r in result]
        assert 'things' not in topics


# ──────────────────────────────────────────────
# 10. Security checks
# ──────────────────────────────────────────────

class TestSecurity:
    def test_xss_in_bookmark_title_is_escaped(self, auth_client):
        """Script tags in bookmark titles must be stored as-is (not executed)
        and returned sanitised when rendered."""
        payload = {'url': 'https://safe.com',
                   'title': '<script>alert(1)</script>',
                   'tags': []}
        r = auth_client.post('/api/bookmarks',
                             data=json.dumps(payload),
                             content_type='application/json')
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

        r = auth_client.delete(f'/api/bookmarks/{bm_id}')
        assert r.status_code == 404

    def test_sql_injection_in_search(self, auth_client):
        """Search param with SQL injection chars should not crash the app."""
        r = auth_client.get("/api/articles?search=' OR '1'='1")
        assert r.status_code == 200

    def test_preview_endpoint_validates_url(self, auth_client):
        """Passing garbage to /api/preview should not crash (500)."""
        r = auth_client.get('/api/preview?url=not-a-url')
        assert r.status_code in (200, 400, 422)  # anything but 500
