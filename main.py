import os
import logging
import requests as http_requests
from datetime import datetime, timedelta, date
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from bs4 import BeautifulSoup
from zxcvbn import zxcvbn
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import smtplib
import socket
from collections import defaultdict, Counter
import re
from itsdangerous import URLSafeTimedSerializer, BadSignature
from urllib.parse import urlsplit

if os.getenv('PYTHON_DOTENV_DISABLED', '').lower() not in {'1', 'true', 'yes'}:
    load_dotenv()

logging.basicConfig(level=logging.INFO)

# A single unreachable feed must never hang the whole fetch
socket.setdefaulttimeout(10)

def resolve_secret_key(environ=None):
    """Return the configured signing key, refusing known defaults in prod."""
    environ = os.environ if environ is None else environ
    secret_key = environ.get('SECRET_KEY')
    if secret_key:
        return secret_key

    is_production = (
        bool(environ.get('RAILWAY_ENVIRONMENT'))
        or environ.get('FLASK_ENV') == 'production'
        or environ.get('APP_ENV') == 'production'
    )
    if is_production:
        raise RuntimeError('SECRET_KEY must be set in production')
    return 'dev-only-never-deployed'

app = Flask(__name__)
app.config.update(
    SECRET_KEY=resolve_secret_key(),
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE='Lax',
)
csrf = CSRFProtect(app)

if os.getenv('SENTRY_DSN'):
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=os.getenv('SENTRY_DSN'), integrations=[FlaskIntegration()],
                        traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.05')))
    except ImportError:
        logging.warning('SENTRY_DSN is set but sentry-sdk is not installed')


def rate_limit_email_key():
    """Return a stable limiter key for the submitted normalized email."""
    payload = request.get_json(silent=True) or {}
    email = request.form.get('email', '') or payload.get('email', '')
    email = email.strip().lower()
    return f'email:{email}' if email else get_remote_address()


limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
    default_limits=[],
)


def is_common_password(password):
    """Return true for a full-password dictionary match in the top 10,000."""
    result = zxcvbn(password)
    last_index = len(password) - 1
    return any(
        match.get('pattern') == 'dictionary'
        and match.get('rank', float('inf')) <= 10000
        and match.get('i') == 0
        and match.get('j') == last_index
        for match in result.get('sequence', [])
    )

# Fix Railway's postgres:// prefix — SQLAlchemy 2.x requires postgresql://
_db_url = os.getenv('DATABASE_URL', 'sqlite:///optionews.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
_engine_opts = {'pool_pre_ping': True, 'pool_recycle': 300}
if _db_url.startswith('postgresql://'):
    _engine_opts['connect_args'] = {'sslmode': 'require'}
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = _engine_opts

@app.before_request
def redirect_www():
    """Redirect www.optio.news → optio.news"""
    if request.host.startswith('www.'):
        url = request.url.replace('www.', '', 1)
        return redirect(url, code=301)

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ==================== Database Models ====================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    feeds = db.relationship('UserFeed', backref='user', lazy=True, cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='user', lazy=True, cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', backref='user', lazy=True, cascade='all, delete-orphan')
    article_states = db.relationship('UserArticleState', backref='user', lazy=True, cascade='all, delete-orphan')
    digest_preferences = db.relationship('DigestPreference', backref='user', lazy=True, cascade='all, delete-orphan')
    saved_searches = db.relationship('SavedSearch', backref='user', lazy=True, cascade='all, delete-orphan')

class UserFeed(db.Model):
    __tablename__ = 'user_feeds'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(64), nullable=False)
    url = db.Column(db.String(512), nullable=False)
    is_hidden = db.Column(db.Boolean, default=False)
    is_added = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Bookmark(db.Model):
    __tablename__ = 'bookmarks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    url = db.Column(db.String(2048), nullable=False)
    title = db.Column(db.String(512), nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(2048))
    tags = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TopicStat(db.Model):
    """Daily mention counts per trending topic — the baseline for burst
    detection ('unusually hot today' vs 'always in the news')."""
    __tablename__ = 'topic_stats'
    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(128), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False)
    count = db.Column(db.Integer, default=0)
    __table_args__ = (db.UniqueConstraint('topic', 'day', name='uq_topic_day'),)


class Feed(db.Model):
    """Durable feed catalogue shared by workers and web processes."""
    __tablename__ = 'feeds'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(64), nullable=False, index=True)
    url = db.Column(db.String(512), unique=True, nullable=False)
    name = db.Column(db.String(256), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    etag = db.Column(db.String(512))
    last_modified = db.Column(db.String(512))
    last_fetched_at = db.Column(db.DateTime)
    last_success_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    subscriptions = db.relationship('Subscription', backref='feed', lazy=True, cascade='all, delete-orphan')
    articles = db.relationship('Article', backref='feed', lazy=True)


class Subscription(db.Model):
    """A user's follow/hide state for a feed; never mutate the global catalogue."""
    __tablename__ = 'subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    feed_id = db.Column(db.Integer, db.ForeignKey('feeds.id'), nullable=False)
    is_hidden = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'feed_id', name='uq_subscription_user_feed'),)


class StoryCluster(db.Model):
    __tablename__ = 'story_clusters'
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    articles = db.relationship('Article', backref='cluster', lazy=True)


class Article(db.Model):
    __tablename__ = 'articles'
    id = db.Column(db.Integer, primary_key=True)
    feed_id = db.Column(db.Integer, db.ForeignKey('feeds.id'), nullable=False, index=True)
    canonical_url = db.Column(db.String(2048), unique=True, nullable=False)
    title = db.Column(db.String(1024), nullable=False)
    author = db.Column(db.String(512))
    summary = db.Column(db.Text)
    image_url = db.Column(db.String(2048))
    published_at = db.Column(db.DateTime, nullable=False, index=True)
    content_hash = db.Column(db.String(64), index=True)
    guid = db.Column(db.String(2048))
    cluster_id = db.Column(db.Integer, db.ForeignKey('story_clusters.id'), index=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    search_document = db.Column(db.Text)
    states = db.relationship('UserArticleState', backref='article', lazy=True, cascade='all, delete-orphan')


class UserArticleState(db.Model):
    __tablename__ = 'user_article_states'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('articles.id'), nullable=False)
    first_seen_at = db.Column(db.DateTime)
    last_impression_at = db.Column(db.DateTime)
    read_at = db.Column(db.DateTime)
    dismissed_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('user_id', 'article_id', name='uq_article_state_user_article'),)


class DigestPreference(db.Model):
    __tablename__ = 'digest_preferences'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    cadence = db.Column(db.String(32), default='daily', nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SavedSearch(db.Model):
    __tablename__ = 'saved_searches'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    search_text = db.Column('query', db.String(256), nullable=False)
    category = db.Column(db.String(64))
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'query', 'category', name='uq_saved_search_user_query_category'),)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Expanded RSS feeds with more categories
rss_feeds = {
    "Technology": [
        # Startups & Analysis
        "https://techcrunch.com/feed/",
        # Product & Gadget Coverage
        "https://www.theverge.com/rss/index.xml",
        "https://www.engadget.com/rss.xml",
        # Deep‑dive & Labs
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        # Industry Trends & Reviews
        "https://www.wired.com/feed/category/tech/latest/rss",
        "https://www.technologyreview.com/feed/",
        # Community & Hacker Culture
        "https://news.ycombinator.com/rss",
        # Additional Tech Sources
        "https://www.cnet.com/rss/news/",
        "https://www.zdnet.com/news/rss.xml",
        "https://www.techmeme.com/feed.xml"
    ],

    "Finance": [
        # Market News & Breaking Analysis
        "https://feeds.marketwatch.com/marketwatch/topstories/",
        "https://www.reuters.com/markets/rss",
        "https://finance.yahoo.com/news/rssindex",
        "https://seekingalpha.com/feed.xml",
        # TV & Web Financial Coverage
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://news.alphastreet.com/feed",
        "https://www.investors.com/feed/",
        # Additional Finance Sources
        "https://www.fool.com/feeds/index.aspx",
        "https://www.wsj.com/xml/rss/3_7085.xml"
    ],

    "General News": [
        # Global & World
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://rss.cnn.com/rss/cnn_topstories.rss",
        "https://www.reuters.com/reuters/topNews",
        # U.S. & Regional
        "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
        "https://www.theguardian.com/us-news/rss",
        # Wire Services & Aggregators
        "https://news.google.com/rss",
        "https://apnews.com/apf-topnews",
        "https://www.npr.org/rss/rss.php?id=1001",
        # Additional News Sources
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.independent.co.uk/rss"
    ],
    
    "Sports": [
        "https://www.espn.com/espn/rss/news",
        "https://www.cbssports.com/rss/headlines/",
        "https://www.si.com/rss/si_topstories.rss",
        "https://bleacherreport.com/articles/feed",
        "https://www.thescore.com/rss/news",
        # Additional Sports Sources
        "https://www.skysports.com/rss/12040",
        "https://www.foxsports.com/rss",
        "https://www.goal.com/feeds/en/news"
    ],
    
    "Science": [
        "https://www.sciencedaily.com/rss/all.xml",
        "https://www.sciencenews.org/feed",
        "https://www.nature.com/nature.rss",
        "https://feeds.feedburner.com/ScienceDaily",
        "https://www.popsci.com/feed",
        "https://www.space.com/feeds/all",
        # Additional Science Sources
        "https://phys.org/rss-feed/",
        "https://www.scientificamerican.com/feed/",
        "https://www.livescience.com/feeds/all"
    ],
    
    "Business": [
        "https://www.forbes.com/business/feed/",
        "https://www.businessinsider.com/rss",
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://fortune.com/feed/",
        "https://www.entrepreneur.com/latest.rss",
        # Additional Business Sources
        "https://www.inc.com/rss/",
        "https://hbr.org/feed",
        "https://www.fastcompany.com/rss"
    ],
    
    "Entertainment": [
        "https://variety.com/feed/",
        "https://deadline.com/feed/",
        "https://www.hollywoodreporter.com/feed/",
        "https://ew.com/feed/",
        "https://www.rollingstone.com/feed/",
        # Additional Entertainment Sources
        "https://www.vulture.com/feed/",
        "https://www.imdb.com/news/rss/",
        "https://www.avclub.com/rss"
    ],
    
    "Music": [
        "https://www.stereogum.com/feed/",
        "https://rateyourmusic.com/rss/feed",
        "https://daily.bandcamp.com/feed/",
        "https://pitchfork.com/rss/reviews/albums/"
    ],
    
    "Health": [
        "https://www.health.com/rss",
        "https://feeds.webmd.com/rss/rss.aspx?RSSSource=RSS_PUBLIC",
        "https://www.medicalnewstoday.com/rss/news.xml",
        "https://www.healthline.com/rss",
        "https://www.prevention.com/rss.xml",
        # Additional Health Sources
        "https://www.mayoclinic.org/rss",
        "https://www.everydayhealth.com/rss/",
        "https://www.menshealth.com/rss/all.xml/"
    ],

    "Politics": [
        "https://www.politico.com/rss/politics08.xml",
        "https://thehill.com/feed/",
        "https://feeds.npr.org/1014/rss.xml",
        "https://www.theguardian.com/politics/rss",
        "https://feeds.bbci.co.uk/news/politics/rss.xml"
    ],

    "Gaming": [
        "https://www.polygon.com/rss/index.xml",
        "https://kotaku.com/rss",
        "https://www.pcgamer.com/rss/",
        "https://www.eurogamer.net/feed",
        "https://www.gamespot.com/feeds/mashup/"
    ],

    "Travel": [
        "https://www.atlasobscura.com/feeds/latest",
        "https://skift.com/feed/",
        "https://www.cntraveler.com/feed/rss",
        "https://www.travelpulse.com/rss.xml",
        "https://www.lonelyplanet.com/news/feed/atom/"
    ],

    "Food": [
        "https://www.eater.com/rss/index.xml",
        "https://www.bonappetit.com/feed/rss",
        "https://www.seriouseats.com/rss",
        "https://food52.com/blog.rss",
        "https://www.foodandwine.com/feeds/all"
    ]
}

# ==================== Per-User Feed Helpers ====================

def feed_display_name(url):
    """Use a stable host label when a feed has no editorial name."""
    try:
        return url.split('/')[2]
    except (IndexError, AttributeError):
        return url


def seed_feed_catalog(commit=True):
    """Create/update the curated feed catalogue during an explicit operation."""
    changed = False
    for category, urls in rss_feeds.items():
        for url in urls:
            feed = Feed.query.filter_by(url=url).first()
            if feed is None:
                db.session.add(Feed(category=category, url=url, name=feed_display_name(url)))
                changed = True
            elif feed.category != category or not feed.active:
                feed.category = category
                feed.active = True
                changed = True
    if commit and changed:
        db.session.commit()
    return changed


def get_or_create_feed(url, category, name=None):
    """Return a durable feed row without changing any user's subscriptions."""
    feed = Feed.query.filter_by(url=url).first()
    if feed is None:
        feed = Feed(category=category, url=url, name=name or feed_display_name(url))
        db.session.add(feed)
        db.session.flush()
    else:
        feed.category = category or feed.category
        feed.name = name or feed.name or feed_display_name(url)
        feed.active = True
    return feed


def is_safe_remote_url(url):
    """Reject malformed or local feed targets before a worker fetches them."""
    try:
        parts = urlsplit((url or '').strip())
        host = (parts.hostname or '').lower()
        return (parts.scheme in {'http', 'https'} and bool(host)
                and not parts.username and not parts.password
                and host not in {'localhost', '127.0.0.1', '::1', '0.0.0.0'}
                and not host.endswith('.local'))
    except ValueError:
        return False


def get_user_subscriptions(user_id):
    return Subscription.query.filter_by(user_id=user_id).all()

def get_user_hidden_feeds(user_id):
    """Get hidden feed URLs for a given user from durable per-user state."""
    try:
        rows = Subscription.query.join(Feed).filter(
            Subscription.user_id == user_id,
            Subscription.is_hidden.is_(True)
        ).all()
        hidden = {row.feed.url for row in rows}
        # Read legacy rows during the migration window so no preference is lost.
        hidden.update(row.url for row in UserFeed.query.filter_by(user_id=user_id, is_hidden=True).all())
        return hidden
    except Exception as e:
        logging.error(f"Error fetching hidden feeds: {e}")
        return set()

def get_user_added_feeds(user_id):
    """Returns {category: [url, ...]} for feeds a user has added"""
    try:
        rows = Subscription.query.join(Feed).filter(Subscription.user_id == user_id).all()
        result = {}
        for row in rows:
            if row.feed:
                result.setdefault(row.feed.category, []).append(row.feed.url)
        for row in UserFeed.query.filter_by(user_id=user_id, is_added=True).all():
            result.setdefault(row.category, []).append(row.url)
        return result
    except Exception as e:
        logging.error(f"Error fetching added feeds: {e}")
        return {}

# Available feeds that users can add
available_feeds = {
    "Technology": [
        {"url": "https://arstechnica.com/feed/", "name": "Ars Technica (alt)"},
        {"url": "https://www.theverge.com/tech/rss/index.xml", "name": "The Verge Tech"},
        {"url": "https://www.gizmodo.com/rss", "name": "Gizmodo"},
    ],
    "Finance": [
        {"url": "https://www.ft.com/?format=rss", "name": "Financial Times"},
        {"url": "https://www.barrons.com/rss", "name": "Barron's"},
        {"url": "https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headline", "name": "Investopedia"},
    ],
    "General News": [
        {"url": "https://www.usatoday.com/rss/", "name": "USA Today"},
        {"url": "https://www.politico.com/rss/politics08.xml", "name": "Politico"},
        {"url": "https://www.washingtonpost.com/rss", "name": "Washington Post"},
    ],
    "Sports": [
        {"url": "https://sports.yahoo.com/rss/", "name": "Yahoo Sports"},
        {"url": "https://www.marca.com/rss.html", "name": "Marca"},
        {"url": "https://www.sbnation.com/rss/current", "name": "SB Nation"},
    ],
    "Science": [
        {"url": "https://www.newscientist.com/feed/home", "name": "New Scientist"},
        {"url": "https://www.smithsonianmag.com/rss/latest_articles/", "name": "Smithsonian"},
        {"url": "https://www.quantamagazine.org/feed/", "name": "Quanta Magazine"},
    ],
    "Business": [
        {"url": "https://www.businessweek.com/feed/", "name": "Bloomberg Businessweek"},
        {"url": "https://www.economist.com/rss", "name": "The Economist"},
        {"url": "https://www.inc.com/rss/5000.xml", "name": "Inc 5000"},
    ],
    "Entertainment": [
        {"url": "https://www.avclub.com/rss", "name": "AV Club"},
        {"url": "https://www.billboard.com/feed/", "name": "Billboard (alt)"},
        {"url": "https://www.thewrap.com/feed/", "name": "The Wrap"},
    ],
    "Music": [
        {"url": "https://www.residentadvisor.net/xml/rss/news.xml", "name": "Resident Advisor"},
        {"url": "https://www.factmag.com/feed/", "name": "FACT Magazine"},
        {"url": "https://daily.bandcamp.com/feed/", "name": "Bandcamp Daily"},
    ],
    "Health": [
        {"url": "https://www.medicaldaily.com/rss", "name": "Medical Daily"},
        {"url": "https://www.womenshealthmag.com/rss/all.xml/", "name": "Women's Health"},
        {"url": "https://www.healthday.com/rss/", "name": "HealthDay"},
    ]
}

def _parse_article_cursor(cursor):
    """Parse the stable published_at_id keyset cursor."""
    if not cursor:
        return None
    try:
        timestamp, article_id = cursor.rsplit('_', 1)
        return datetime.fromisoformat(timestamp), int(article_id)
    except (ValueError, TypeError):
        return None


def _article_score(article, state, source_counts, topic_counts, cluster_size):
    """Explainable, deliberately small ranking model for a user's reader."""
    now = datetime.utcnow()
    age_hours = max(0.0, (now - article.published_at).total_seconds() / 3600)
    recency = max(0.0, 1.0 - age_hours / 72.0)
    impressions, reads = source_counts.get(article.feed_id, (0, 0))
    source_affinity = (reads + 1) / (impressions + 2)
    topic_key = article.feed.category if article.feed else ''
    topic_impressions, topic_reads = topic_counts.get(topic_key, (0, 0))
    topic_affinity = (topic_reads + 1) / (topic_impressions + 2)
    burst = 1.0
    cluster_signal = min(cluster_size, 5) / 5.0
    score = (0.30 * source_affinity + 0.25 * topic_affinity
             + 0.20 * recency + 0.15 * burst + 0.10 * cluster_signal)
    if state and state.read_at:
        reason = 'Previously read'
    elif source_affinity >= 0.6:
        reason = f'From a source you return to: {article.feed.name}'
    elif topic_affinity >= 0.6:
        reason = f'Fits your {topic_key} reading pattern'
    elif cluster_size > 1:
        reason = f'Covered by {cluster_size} sources'
    else:
        reason = 'Fresh from your followed sources'
    return round(score, 4), reason


def _article_to_dict(article, members=None, state_map=None, reason='Fresh from your followed sources', score=0):
    members = members or [article]
    state_map = state_map or {}
    states = [state_map.get(member.id) for member in members]
    image_url = next((member.image_url.strip() for member in members
                      if (member.image_url or '').strip()), '')
    sources = []
    seen_sources = set()
    for member in members:
        source = member.feed.name if member.feed else feed_display_name(member.canonical_url)
        if source not in seen_sources:
            seen_sources.add(source)
            sources.append({'name': source, 'url': member.feed.url if member.feed else ''})
    published = article.published_at
    return {
        'id': article.id,
        'article_ids': [member.id for member in members],
        'cluster_id': article.cluster_id or article.id,
        'title': article.title,
        'author': article.author or 'N/A',
        'link': article.canonical_url,
        'summary': article.summary or '',
        'category': article.feed.category if article.feed else 'General News',
        'site': article.feed.name if article.feed else feed_display_name(article.canonical_url),
        'feed_url': article.feed.url if article.feed else '',
        'published': published.isoformat(),
        'published_display': published.strftime('%b %d, %Y %I:%M %p'),
        'image_url': image_url,
        'sources': sources,
        'source_count': len(sources),
        'is_read': bool(states and all(state and state.read_at for state in states)),
        'is_seen': bool(states and any(state and state.first_seen_at for state in states)),
        'reason': reason,
        'score': score,
    }


def query_persisted_articles(user_id=None, category='all', search='', unread=False,
                             cursor=None, limit=30):
    """Read durable content; this function never performs network I/O."""
    limit = max(1, min(int(limit or 30), 100))
    if user_id is None:
        visible_feed_ids = None
    else:
        subscriptions = get_user_subscriptions(user_id)
        if subscriptions:
            visible_feed_ids = {s.feed_id for s in subscriptions if not s.is_hidden}
        else:
            visible_feed_ids = None  # legacy users see the curated catalogue
    query = Article.query.join(Feed)
    if visible_feed_ids is not None:
        if not visible_feed_ids:
            return [], None
        query = query.filter(Article.feed_id.in_(visible_feed_ids))
    if category and category != 'all':
        query = query.filter(Feed.category == category)
    if search:
        term = search.strip()
        # PostgreSQL uses its native web-search parser; SQLite remains useful
        # for local development and tests with a bounded substring fallback.
        if db.session.bind and db.session.bind.dialect.name == 'postgresql':
            document = db.func.to_tsvector('english', db.func.coalesce(Article.search_document, ''))
            query = query.filter(document.op('@@')(db.func.websearch_to_tsquery('english', term)))
        else:
            needle = f'%{term.lower()}%'
            query = query.filter(db.or_(db.func.lower(Article.title).like(needle),
                                        db.func.lower(db.func.coalesce(Article.summary, '')).like(needle)))
    parsed_cursor = _parse_article_cursor(cursor)
    if parsed_cursor:
        cursor_time, cursor_id = parsed_cursor
        query = query.filter(db.or_(Article.published_at < cursor_time,
                                    db.and_(Article.published_at == cursor_time,
                                            Article.id < cursor_id)))
    query = query.order_by(Article.published_at.desc(), Article.id.desc())
    rows = query.limit(limit * 8).all()
    if not rows:
        return [], None

    state_map = {}
    if user_id is not None:
        state_map = {state.article_id: state for state in UserArticleState.query.filter(
            UserArticleState.user_id == user_id,
            UserArticleState.article_id.in_([row.id for row in rows])
        ).all()}
        rows = [row for row in rows if not state_map.get(row.id) or not state_map[row.id].dismissed_at]
        if unread:
            rows = [row for row in rows if not state_map.get(row.id) or not state_map[row.id].read_at]

    source_counts = defaultdict(lambda: [0, 0])
    topic_counts = defaultdict(lambda: [0, 0])
    if user_id is not None:
        history = UserArticleState.query.filter_by(user_id=user_id).all()
        history_articles = {a.id: a for a in Article.query.filter(
            Article.id.in_([item.article_id for item in history])
        ).all()} if history else {}
        for item in history:
            historical = history_articles.get(item.article_id)
            if not historical:
                continue
            source_counts[historical.feed_id][0] += 1
            topic_counts[historical.feed.category][0] += 1
            if item.read_at:
                source_counts[historical.feed_id][1] += 1
                topic_counts[historical.feed.category][1] += 1

    scored = []
    cluster_sizes = {}
    for row in rows:
        size = len(row.cluster.articles) if row.cluster else 1
        cluster_sizes[row.cluster_id or row.id] = size
        score, reason = _article_score(row, state_map.get(row.id), source_counts, topic_counts, size)
        scored.append((row, score, reason))
    scored.sort(key=lambda item: (-item[1], -item[0].published_at.timestamp(), -item[0].id))

    groups = []
    group_map = {}
    for row, score, reason in scored:
        key = row.cluster_id or row.id
        if cluster_sizes.get(key, 1) > 24:
            # A bad historical cluster must not hide hundreds of unrelated
            # stories behind one card while the next worker rebuilds it.
            key = row.id
        if key not in group_map:
            group_map[key] = {'primary': row, 'members': [], 'score': score, 'reason': reason}
            groups.append(group_map[key])
        group_map[key]['members'].append(row)
    groups = groups[:limit]
    cards = [_article_to_dict(group['primary'], group['members'], state_map,
                              group['reason'], group['score']) for group in groups]
    last_row = groups[-1]['members'][-1] if groups else None
    next_cursor = (f'{last_row.published_at.isoformat()}_{last_row.id}' if last_row else None)
    return cards, next_cursor


def fetch_articles(force_refresh=False, user_id=None):
    """Legacy-compatible read wrapper; ingestion belongs to the worker."""
    return query_persisted_articles(user_id=user_id)[0]


def query_recent_articles_for_trending(user_id, hours=24, limit=500):
    """Return raw recent articles for trend analysis, not grouped cards."""
    query = Article.query.join(Feed)
    subscriptions = get_user_subscriptions(user_id)
    if subscriptions:
        visible_feed_ids = {s.feed_id for s in subscriptions if not s.is_hidden}
        if not visible_feed_ids:
            return []
        query = query.filter(Article.feed_id.in_(visible_feed_ids))

    dismissed_ids = {state.article_id for state in UserArticleState.query.filter_by(
        user_id=user_id
    ).all() if state.dismissed_at}
    if dismissed_ids:
        query = query.filter(~Article.id.in_(dismissed_ids))

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    rows = query.filter(Article.published_at >= cutoff).order_by(
        Article.published_at.desc(), Article.id.desc()
    ).limit(limit).all()
    return [_article_to_dict(row, [row]) for row in rows]


def cache_is_warming():
    """Compatibility flag retained for older clients; web reads are DB-backed."""
    return False

def extract_trending_topics(articles, top_n=10):
    """
    Extract trending topics using named-entity heuristics + article-spread scoring.
    Prefers proper nouns (people, places, orgs, events) spread across many articles.
    """
    now = datetime.utcnow()
    recent_articles = []
    for article in articles:
        try:
            pub_date = datetime.fromisoformat(article['published'])
            if now - pub_date <= timedelta(hours=24):
                recent_articles.append(article)
        except (ValueError, KeyError):
            continue

    if not recent_articles:
        return []

    # ── Stopwords ────────────────────────────────────────────────────────────
    STOP = {
        # articles / conjunctions / prepositions
        'the','a','an','and','or','but','in','on','at','to','for','of','with',
        'by','from','as','is','was','are','were','be','been','being','have',
        'has','had','do','does','did','will','would','could','should','may',
        'might','must','can','this','that','these','those','it','its',
        # pronouns
        'their','there','here','his','her','she','he','they','we','you','your',
        'our','my','me','him','them','us','who','whose','whom','what','which',
        'where','when','why','how','whether','wherever','whenever','whatever',
        'behind','inside','outside','beyond','despite','among','though','although',
        # common verbs
        'said','says','say','say','told','tell','tells','telling','get','gets',
        'got','getting','make','makes','made','making','see','sees','saw','seen',
        'going','went','go','goes','come','comes','came','take','takes','took',
        'taken','give','gives','gave','given','keep','kept','let','lets','run',
        'runs','ran','put','set','try','tried','tries','want','wants','wanted',
        'need','needs','needed','become','became','feel','felt','seem','seemed',
        'help','helped','helps','work','works','worked','use','used','uses',
        'show','showed','shown','shows','find','finds','found','call','calls',
        'called','turn','turns','turned','start','starts','started','end','ends',
        'move','moves','moved','bring','brings','brought','leave','left','leaves',
        'change','changes','changed','include','includes','included','meet',
        'meets','met','pay','pays','paid','add','adds','added','lose','lost',
        # adverbs / linking words
        'more','most','also','just','now','not','no','yes','well','still','even',
        'however','therefore','thus','hence','moreover','furthermore','meanwhile',
        'otherwise','instead','rather','quite','almost','already','always',
        'never','often','sometimes','usually','really','actually','literally',
        'very','too','so','yet','only','away','back','out','up','down','off',
        'over','again','then','than','both','either','neither','nor','each',
        'few','any','some','all','such','own','same','too','every','other',
        'another','less','least','much','many','around','along','per','via',
        # time words
        'today','yesterday','week','month','year','day','time','years','days',
        'weeks','months','hours','hour','minutes','minute','soon','recently',
        'monday','tuesday','wednesday','thursday','friday','saturday','sunday',
        'january','february','march','april','june','july','august','september',
        'october','november','december',
        # numbers / quantities
        'one','two','three','four','five','six','seven','eight','nine','ten',
        'first','second','third','last','next','million','billion','trillion',
        'thousand','hundred','percent','cent',
        # news/media jargon (too generic to be "trending")
        'news','report','reports','reported','reporting','story','stories',
        'article','articles','update','updates','latest','breaking','live',
        'exclusive','opinion','analysis','review','reviews','watch','read',
        'reading','click','share','tweet','post','comment','subscribe','follow',
        'appear','appeared','appears','seem','like','likely','new','old',
        'amid','ahead','after','before','during','under','against','across',
        'between','within','without','about','around','since','until','while',
        'into','onto','upon','according','including','following','regarding',
        # generic descriptors
        'good','bad','great','big','small','large','little','high','low','long',
        'short','young','early','late','best','worst','better','worse','right',
        'wrong','clear','major','key','top','full','whole','wide','open','free',
        'real','true','possible','likely','known','given','local','former',
        'current','recent','next','previous','main','general','special','public',
        'private','official','federal','state','national','global','international',
        'significant','important','growing','increasing','rising','falling',
        'leading','leading','according','multiple','several','various','different',
        # generic standalone nouns (too broad to be meaningful trends)
        'market','markets','court','courts','series','deal','deals','data',
        'case','cases','bill','bills','plan','plans','move','moves','role',
        'claim','claims','rule','rules','risk','risks','rate','rates','cost',
        'costs','poll','polls','vote','votes','issue','issues','price','prices',
        'sale','sales','loss','losses','gain','gains','growth','fund','funds',
        'call','calls','talk','talks','walk','race','race','shot','shots',
        'line','lines','lead','leads','hold','holds','draw','draws','game',
        'games','test','tests','term','terms','step','steps','fact','facts',
        'half','quarter','round','point','points','level','levels','stage',
        'source','sources','impact','effect','effects','effort','efforts',
        'support','response','result','results','number','numbers','amount',
        'total','figure','figures','record','records','demand','supply',
        # generic people/place nouns
        'people','person','man','woman','men','women','child','children','world',
        'country','countries','city','cities','region','area','place','home',
        'government','official','officials','president','minister','leader',
        'company','companies','business','businesses','group','groups','team',
        'teams','party','parties','side','member','members','family','families',
        'investor','investors','consumer','consumers','worker','workers',
        'player','players','student','students','citizen','citizens',
        # digital/web noise
        'https','http','www','com','net','org','html','pdf','nbsp','amp','quot',
        'apos','hellip','mdash','ndash','rsquo','lsquo','rdquo','ldquo',
        # quantifiers / modal
        'dont','doesnt','didnt','wont','wouldnt','cant','couldnt','shouldnt',
        'hasnt','havent','hadnt','isnt','arent','wasnt','werent',
    }

    # Phrases that are always in the news and never actually "trending"
    GENERIC_PHRASES = {
        'social media','fake news','climate change','breaking news','live blog',
        'read more','find out','click here','sign up','log in','learn more',
        'check out','follow us','join us','contact us','terms conditions',
        'privacy policy','cookie policy','all rights','rights reserved',
        'artificial intelligence','machine learning','interest rates',
        'stock market','wall street','white house','united states','united kingdom',
        'european union','middle east','north korea','south korea',
    }

    # ── Score by unique-article spread + proper-noun bonus ───────────────────
    # word -> set of article indices that mention it
    word_articles: dict = {}
    phrase_articles: dict = {}

    for idx, article in enumerate(recent_articles):
        title = article.get('title', '')
        summary = article.get('summary', '')

        # Collect which words are CAPITALISED in the title (proper noun signal)
        title_proper = set()
        for tok in title.split():
            clean = re.sub(r'[^a-zA-Z]', '', tok)
            if clean and clean[0].isupper() and clean.lower() not in STOP:
                title_proper.add(clean.lower())

        text = f"{title} {summary}".lower()
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-z#\d]+;', ' ', text)
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        words = [w for w in text.split()
                 if w.isalpha() and len(w) > 3 and w not in STOP]

        for w in words:
            word_articles.setdefault(w, set()).add(idx)

        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            if bigram not in GENERIC_PHRASES:
                phrase_articles.setdefault(bigram, set()).add(idx)
            if i < len(words) - 2:
                trigram = f"{words[i]} {words[i+1]} {words[i+2]}"
                if trigram not in GENERIC_PHRASES:
                    phrase_articles.setdefault(trigram, set()).add(idx)

    # ── Per-article metadata for diversity + recency scoring ────────────────
    art_site = [a.get('site', '') for a in recent_articles]
    art_age_h = []
    for a in recent_articles:
        try:
            age_h = (now - datetime.fromisoformat(a['published'])).total_seconds() / 3600
        except (ValueError, KeyError, TypeError):
            age_h = 24.0
        art_age_h.append(max(0.0, age_h))

    def diversity_mult(art_set):
        """More distinct outlets → more genuinely trending. A topic pushed by
        a single outlet many times is that outlet's obsession, not news."""
        sites = {art_site[i] for i in art_set}
        if len(sites) == 1 and len(art_set) >= 4:
            return 0.5
        return 1.0 + 0.12 * (min(len(sites), 6) - 1)

    def recency_mult(art_set):
        """Mentions from the last 6 hours count 1.5x — velocity over volume."""
        weights = [1.5 if art_age_h[i] <= 6 else 1.0 for i in art_set]
        return sum(weights) / len(weights)

    # ── Proper-noun signals from titles ──────────────────────────────────────
    proper_noun_counts: dict = {}
    pair_counts: dict = {}
    for article in recent_articles:
        toks = [re.sub(r'[^a-zA-Z]', '', t) for t in article.get('title', '').split()]
        toks = [t for t in toks if t]
        for tok in toks:
            if len(tok) > 3 and tok[0].isupper() and tok.lower() not in STOP:
                proper_noun_counts[tok.lower()] = proper_noun_counts.get(tok.lower(), 0) + 1
        # Adjacent capitalised pairs ("Elon Musk", "World Cup") form entities
        for i in range(len(toks) - 1):
            a, b = toks[i], toks[i + 1]
            if (len(a) > 1 and len(b) > 1 and a[0].isupper() and b[0].isupper()
                    and a.lower() not in STOP and b.lower() not in STOP):
                key = f"{a.lower()} {b.lower()}"
                pair_counts[key] = pair_counts.get(key, 0) + 1

    # Words consumed by a recurring entity pair should not trend on their own
    # (prevents "York" ranking separately from "New York"). Only suppress a
    # component when the pair itself survived tokenization as a phrase
    # candidate — otherwise the topic would vanish entirely.
    merged_components = set()
    for pair, c in pair_counts.items():
        if c >= 2 and pair in phrase_articles:
            merged_components.update(pair.split())

    # ── Build candidate list ─────────────────────────────────────────────────
    candidates = []

    for word, art_set in word_articles.items():
        spread = len(art_set)
        if spread < 3:
            continue
        if word in merged_components:
            continue  # the entity phrase will carry this word
        is_proper = proper_noun_counts.get(word, 0) >= 2
        score = (spread * (2.5 if is_proper else 1.0)
                 * diversity_mult(art_set) * recency_mult(art_set))
        candidates.append({'topic': word, 'score': score, 'spread': spread,
                           'is_phrase': False, 'is_proper': is_proper})

    for phrase, art_set in phrase_articles.items():
        spread = len(art_set)
        if spread < 2:
            continue
        # Phrase is "proper" if at least one word is a known proper noun
        phrase_words = phrase.split()
        is_proper = any(proper_noun_counts.get(w, 0) >= 2 for w in phrase_words)
        # Prefer longer, more specific phrases; recurring title entities most of all
        length_bonus = 1.4 if len(phrase_words) == 3 else 1.2
        entity_bonus = 1.6 if pair_counts.get(phrase, 0) >= 2 else 1.0
        score = (spread * length_bonus * entity_bonus * (2.5 if is_proper else 1.0)
                 * diversity_mult(art_set) * recency_mult(art_set))
        candidates.append({'topic': phrase, 'score': score, 'spread': spread,
                           'is_phrase': True, 'is_proper': is_proper})

    # Sort by score descending
    candidates.sort(key=lambda x: x['score'], reverse=True)

    # ── De-duplicate: skip if substring of already accepted topic ────────────
    trending = []
    seen_words: set = set()

    for c in candidates:
        t_lower = c['topic'].lower()
        t_words = set(t_lower.split())

        # Skip if all words already covered by an accepted topic
        if t_words.issubset(seen_words):
            continue
        # Skip if this topic is a substring of an already accepted one
        if any(t_lower in accepted for accepted in seen_words):
            continue
        # Non-proper single words need very high spread to qualify
        if not c['is_phrase'] and not c['is_proper'] and c['spread'] < 10:
            continue

        display = ' '.join(w.capitalize() for w in c['topic'].split())
        seen_words.update(t_words)

        trending.append({
            'topic': display,
            'count': c['spread'],
            'score': round(c['score'], 2),
            'articles': []
        })

        if len(trending) >= top_n:
            break

    # ── Attach related articles + 24h mention sparkline + rising signal ─────
    for td in trending:
        t_lower = td['topic'].lower()
        matched = []
        buckets = [0] * 8          # eight 3-hour buckets, oldest → newest
        last6 = 0
        prev18 = 0
        for idx, article in enumerate(recent_articles):
            haystack = f"{article['title']} {article['summary']}".lower()
            if t_lower in haystack or all(w in haystack for w in t_lower.split()):
                matched.append(article)
                age = art_age_h[idx]
                bucket = 7 - min(int(age // 3), 7)
                buckets[bucket] += 1
                if age <= 6:
                    last6 += 1
                else:
                    prev18 += 1
        # Rising: disproportionate share of mentions in the last 6 hours
        td['rising'] = last6 >= 2 and last6 * 3 > prev18
        td['buckets'] = buckets
        td['sites'] = len({a['site'] for a in matched}) if matched else 0
        # Related articles: prefer ones with imagery
        matched.sort(key=lambda a: 0 if a.get('image_url') else 1)
        td['articles'] = [{
            'title': a['title'],
            'link': a['link'],
            'site': a['site'],
            'category': a['category'],
            'image_url': a.get('image_url', '')
        } for a in matched[:3]]

    return trending

def create_email_content(articles, unsubscribe_url=None):
    """Create HTML email content from articles"""
    import html
    from collections import defaultdict
    
    # Group articles by category
    grouped = defaultdict(list)
    for art in articles:
        grouped[art['category']].append(art)
    
    article_html = ""
    for category in sorted(grouped.keys()):
        article_html += f'<h2 style="color: #2563eb; margin-top: 30px;">{category}</h2>'
        for art in grouped[category]:
            # Escape HTML entities in title
            title = html.escape(art['title'])
            # Strip HTML tags from summary but keep the text
            import re
            summary = re.sub('<[^<]+?>', '', art['summary'])
            summary = html.unescape(summary)[:200] + '...' if len(summary) > 200 else html.unescape(summary)
            
            article_html += f"""
            <div style="margin-bottom: 20px; padding: 15px; background: #f5f7fa; border-left: 3px solid #2563eb;">
                <h3 style="margin-top: 0;">
                    <a href="{art['link']}" style="color: #1a1a1a; text-decoration: none;">{title}</a>
                </h3>
                <p style="color: #4a5568; margin: 10px 0;">{summary}</p>
                <p style="font-size: 12px; color: #a0aec0;">
                    <strong>{art['site']}</strong> • {art['published_display']}
                </p>
            </div>
            """
    
    return f"""
    <html>
      <head>
        <style>
          body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #ffffff; }}
          h1 {{ color: #2563eb; }}
          a {{ color: #2563eb; }}
        </style>
      </head>
      <body>
        <h1>Optio News - Your Daily News Briefing</h1>
        <p style="color: #4a5568;">Here are today's top stories from across {len(grouped)} categories:</p>
        {article_html}
        <hr style="margin-top: 40px; border: none; border-top: 1px solid #d1d5db;">
        <p style="text-align: center; color: #a0aec0; font-size: 12px;">
          You're receiving this because you subscribed to Optio News daily digest.
          {f'<br><a href="{unsubscribe_url}">Unsubscribe</a>' if unsubscribe_url else ''}
        </p>
      </body>
    </html>
    """

def send_email(html_content, receiver):
    sender = os.getenv('SENDER_EMAIL')
    pwd = os.getenv('APP_PASSWORD')
    if not (sender and receiver and pwd):
        logging.warning("Digest email disabled: configure SENDER_EMAIL, APP_PASSWORD, and a recipient")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Optio News - Your Daily News Briefing"
    msg['From'] = sender
    msg['To'] = receiver
    msg.attach(MIMEText(html_content, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, pwd)
            server.sendmail(sender, receiver, msg.as_string())
        logging.info("Email sent!")
        return True
    except Exception as e:
        logging.error(f"Email error: {e}")
        return False

# ==================== Auth Routes ====================

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
@limiter.limit('20 per hour', key_func=rate_limit_email_key, methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('reader'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('reader'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html', categories=list(rss_feeds.keys()))

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
@limiter.limit('20 per hour', key_func=rate_limit_email_key, methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('reader'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not email or not password:
            flash('Email and password are required.', 'error')
        elif password != confirm:
            flash('Passwords do not match.', 'error')
        elif len(password) < 12:
            flash('Password must be at least 12 characters.', 'error')
        elif is_common_password(password):
            flash('Choose a less common password.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'error')
        else:
            user = User(
                email=email,
                password_hash=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.flush()
            seed_feed_catalog(commit=False)
            selected = [category for category in request.form.getlist('categories')
                        if category in rss_feeds]
            if not selected:
                selected = list(rss_feeds.keys())[:3]
            for category in selected:
                for url in rss_feeds[category]:
                    feed = get_or_create_feed(url, category)
                    db.session.add(Subscription(user_id=user.id, feed_id=feed.id))
            db.session.add(DigestPreference(user_id=user.id, enabled=False, cadence='daily'))
            db.session.commit()
            login_user(user)
            return redirect(url_for('reader'))
    return render_template('register.html', categories=list(rss_feeds.keys()))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ==================== Flask Routes ====================

@app.route('/')
def index():
    """Public front door with a small server-rendered story sample."""
    with app.app_context():
        seed_feed_catalog()
        public_articles, _ = query_persisted_articles(category='all', limit=12)
    return render_template('landing.html', categories=list(rss_feeds.keys()),
                           articles=public_articles, user=current_user)


@app.route('/reader')
@login_required
def reader():
    """Authenticated personalized reader."""
    return render_template('index.html', categories=list(rss_feeds.keys()), user=current_user)

@app.route('/feeds')
@login_required
def feeds_page():
    """Feed management page"""
    return render_template('feeds.html', user=current_user)

@app.route('/bookmarks')
@login_required
def bookmarks_page():
    """Bookmarks page"""
    return render_template('bookmarks.html', user=current_user)

@app.route('/api/articles')
@login_required
def get_articles_api():
    """Database-only personalized article endpoint with keyset pagination."""
    category = request.args.get('category', 'all')
    search = request.args.get('search', '').strip()
    unread = request.args.get('unread', '').lower() in {'1', 'true', 'yes'}
    try:
        limit = int(request.args.get('limit', 30))
    except ValueError:
        limit = 30
    articles, next_cursor = query_persisted_articles(
        user_id=current_user.id, category=category, search=search,
        unread=unread, cursor=request.args.get('cursor'), limit=limit,
    )
    unread_articles, _ = query_persisted_articles(user_id=current_user.id, unread=True, limit=100)
    subscriptions = get_user_subscriptions(current_user.id)
    feed_count = len({subscription.feed_id for subscription in subscriptions if not subscription.is_hidden})
    if not subscriptions:
        feed_count = Feed.query.filter_by(active=True).count() or sum(len(feeds) for feeds in rss_feeds.values())

    return jsonify({
        'articles': articles,
        'count': len(articles),
        'next_cursor': next_cursor,
        'feed_count': feed_count,
        'unread_count': len(unread_articles),
        'storage': 'database',
    })

_trending_prev_ranks = {}

def _apply_burst_scoring(trending):
    """Re-rank by burstiness: a topic's spread today vs its own 7-day
    baseline. Kills perennial topics unless they are genuinely spiking."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    try:
        for td in trending:
            key = td['topic'].lower()
            rows = TopicStat.query.filter(
                TopicStat.topic == key,
                TopicStat.day < today,
                TopicStat.day >= week_ago
            ).all()
            baseline = (sum(r.count for r in rows) / len(rows)) if rows else 0
            if baseline == 0:
                burst = 1.5          # never seen before — genuinely new
            else:
                burst = max(0.5, min(3.0, td['count'] / baseline))
            td['score'] = round(td['score'] * burst, 2)

        trending.sort(key=lambda t: t['score'], reverse=True)

        # Record today's counts (keep the max seen today per topic)
        for td in trending:
            key = td['topic'].lower()
            row = TopicStat.query.filter_by(topic=key, day=today).first()
            if row:
                row.count = max(row.count, td['count'])
            else:
                db.session.add(TopicStat(topic=key, day=today, count=td['count']))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.warning(f"Burst scoring skipped: {e}")
    return trending


@app.route('/api/trending')
@login_required
def get_trending_topics():
    """Trending topics from the last 24 hours, optionally per category."""
    category = request.args.get('category', 'all')
    articles = query_recent_articles_for_trending(current_user.id)

    if category != 'all':
        articles = [a for a in articles if a['category'] == category]

    # Over-fetch so burst re-ranking has room to reshuffle before trimming
    trending = extract_trending_topics(articles, top_n=20)
    if category == 'all':
        trending = _apply_burst_scoring(trending)
    trending = trending[:10]

    # Movement badges vs the previous computation for this category
    prev = _trending_prev_ranks.get(category, {})
    for i, td in enumerate(trending):
        rank = i + 1
        if not prev:
            td['change'] = 0            # first run — no movement story to tell
        elif td['topic'] not in prev:
            td['change'] = 'new'
        else:
            td['change'] = prev[td['topic']] - rank
    _trending_prev_ranks[category] = {td['topic']: i + 1 for i, td in enumerate(trending)}

    payload = {
        'trending': trending,
        'count': len(trending),
        'period': '24 hours',
        'category': category
    }
    logging.info(f"Trending computed for '{category}': {len(trending)} topics")
    return jsonify(payload)

@app.route('/api/refresh')
@login_required
def refresh_articles():
    """Signal that the worker should fetch; never crawl feeds in a web request."""
    return jsonify({
        'success': True,
        'status': 'worker_refresh_scheduled',
        'timestamp': datetime.utcnow().isoformat()
    })


# ==================== Reading State, Digest, and Alerts ====================

def _mutate_article_state(field):
    data = request.get_json(silent=True) or {}
    raw_ids = data.get('ids', data.get('article_ids', []))
    if isinstance(raw_ids, (int, str)):
        raw_ids = [raw_ids]
    article_ids = []
    for raw_id in raw_ids or []:
        try:
            article_ids.append(int(raw_id))
        except (ValueError, TypeError):
            continue
    article_ids = list(dict.fromkeys(article_ids))[:200]
    now = datetime.utcnow()
    changed = 0
    for article_id in article_ids:
        if not db.session.get(Article, article_id):
            continue
        state = UserArticleState.query.filter_by(user_id=current_user.id, article_id=article_id).first()
        if state is None:
            state = UserArticleState(user_id=current_user.id, article_id=article_id)
            db.session.add(state)
        if field == 'first_seen_at' and state.first_seen_at is None:
            state.first_seen_at = now
        if field == 'read_at':
            state.read_at = now
            state.first_seen_at = state.first_seen_at or now
        if field == 'dismissed_at':
            state.dismissed_at = now
        if field == 'undismissed_at':
            state.dismissed_at = None
        state.last_impression_at = now
        changed += 1
    db.session.commit()
    return jsonify({'success': True, 'updated': changed})


@app.route('/api/state/seen', methods=['POST'])
@login_required
def mark_articles_seen():
    return _mutate_article_state('first_seen_at')


@app.route('/api/state/read', methods=['POST'])
@login_required
def mark_articles_read():
    return _mutate_article_state('read_at')


@app.route('/api/state/dismiss', methods=['POST'])
@login_required
def dismiss_articles():
    return _mutate_article_state('dismissed_at')


@app.route('/api/state/undismiss', methods=['POST'])
@login_required
def undismiss_articles():
    return _mutate_article_state('undismissed_at')


@app.route('/api/state/mark-all-read', methods=['POST'])
@login_required
def mark_all_articles_read():
    visible, _ = query_persisted_articles(user_id=current_user.id, limit=100)
    ids = [article_id for card in visible for article_id in card.get('article_ids', [])]
    now = datetime.utcnow()
    for article_id in ids:
        state = UserArticleState.query.filter_by(user_id=current_user.id, article_id=article_id).first()
        if state is None:
            state = UserArticleState(user_id=current_user.id, article_id=article_id)
            db.session.add(state)
        state.read_at = now
        state.first_seen_at = state.first_seen_at or now
        state.last_impression_at = now
    db.session.commit()
    return jsonify({'success': True, 'updated': len(ids)})


def _digest_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='optio-digest-unsubscribe')


@app.route('/api/digest/preferences', methods=['GET', 'PUT', 'POST'])
@login_required
def digest_preferences_api():
    preference = DigestPreference.query.filter_by(user_id=current_user.id).first()
    if preference is None:
        preference = DigestPreference(user_id=current_user.id, enabled=False, cadence='daily')
        db.session.add(preference)
    if request.method in {'PUT', 'POST'}:
        data = request.get_json(silent=True) or request.form
        if 'enabled' in data:
            value = data.get('enabled')
            preference.enabled = value if isinstance(value, bool) else str(value).lower() in {'1', 'true', 'yes', 'on'}
        cadence = data.get('cadence')
        if cadence in {'daily', 'weekly'}:
            preference.cadence = cadence
        db.session.commit()
    return jsonify({'enabled': preference.enabled, 'cadence': preference.cadence})


@app.route('/digest/unsubscribe/<token>')
def digest_unsubscribe(token):
    try:
        payload = _digest_serializer().loads(token, max_age=60 * 60 * 24 * 90)
        user_id = int(payload['user_id'])
    except (BadSignature, KeyError, TypeError, ValueError):
        abort(404)
    preference = DigestPreference.query.filter_by(user_id=user_id).first()
    if preference:
        preference.enabled = False
        db.session.commit()
    return render_template('unsubscribe.html')


@app.route('/api/alerts', methods=['GET', 'POST'])
@login_required
def saved_searches_api():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        query_text = (data.get('query') or '').strip()[:256]
        category = (data.get('category') or '').strip()[:64] or None
        if not query_text:
            return jsonify({'error': 'query required'}), 400
        existing = SavedSearch.query.filter_by(user_id=current_user.id, search_text=query_text, category=category).first()
        if existing:
            existing.enabled = True
        else:
            db.session.add(SavedSearch(user_id=current_user.id, search_text=query_text, category=category))
        db.session.commit()
    alerts = SavedSearch.query.filter_by(user_id=current_user.id).order_by(SavedSearch.created_at.desc()).all()
    return jsonify({'alerts': [{'id': a.id, 'query': a.search_text, 'category': a.category, 'enabled': a.enabled} for a in alerts]})


@app.route('/api/alerts/<int:alert_id>', methods=['DELETE'])
@login_required
def delete_saved_search(alert_id):
    alert = SavedSearch.query.filter_by(id=alert_id, user_id=current_user.id).first_or_404()
    db.session.delete(alert)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/feeds')
@login_required
def get_feeds():
    """Get the durable feed catalogue and this user's subscription state."""
    seed_feed_catalog()
    user_hidden = get_user_hidden_feeds(current_user.id)
    subscriptions = {subscription.feed_id: subscription for subscription in get_user_subscriptions(current_user.id)}
    feeds_list = []
    for feed in Feed.query.filter_by(active=True).order_by(Feed.category, Feed.name).all():
        subscription = subscriptions.get(feed.id)
        feeds_list.append({
            'id': feed.id,
            'url': feed.url,
            'category': feed.category,
            'name': feed.name,
            'hidden': feed.url in user_hidden or bool(subscription and subscription.is_hidden),
            'followed': bool(subscription and not subscription.is_hidden),
            'last_success_at': feed.last_success_at.isoformat() if feed.last_success_at else None,
            'last_error': feed.last_error,
        })
    return jsonify({
        'feeds': feeds_list,
        'total': len(feeds_list),
        'hidden_count': len(user_hidden)
    })

@app.route('/api/feeds/hide', methods=['POST'])
@login_required
def hide_feed():
    """Hide a specific feed for the current user"""
    data = request.json
    feed_url = data.get('url')
    category = data.get('category', '')
    if not feed_url:
        return jsonify({'error': 'URL required'}), 400
    feed = get_or_create_feed(feed_url, category)
    existing = Subscription.query.filter_by(user_id=current_user.id, feed_id=feed.id).first()
    if existing:
        existing.is_hidden = True
    else:
        db.session.add(Subscription(user_id=current_user.id, feed_id=feed.id, is_hidden=True))
    db.session.commit()
    user_hidden = get_user_hidden_feeds(current_user.id)
    return jsonify({'success': True, 'message': f'Feed hidden', 'hidden_count': len(user_hidden)})

@app.route('/api/feeds/unhide', methods=['POST'])
@login_required
def unhide_feed():
    """Unhide a specific feed for the current user"""
    data = request.json
    feed_url = data.get('url')
    if not feed_url:
        return jsonify({'error': 'URL required'}), 400
    feed = Feed.query.filter_by(url=feed_url).first()
    existing = Subscription.query.filter_by(user_id=current_user.id, feed_id=feed.id).first() if feed else None
    if existing:
        existing.is_hidden = False
    legacy = UserFeed.query.filter_by(user_id=current_user.id, url=feed_url).first()
    if legacy:
        legacy.is_hidden = False
    db.session.commit()
    user_hidden = get_user_hidden_feeds(current_user.id)
    return jsonify({'success': True, 'message': f'Feed restored', 'hidden_count': len(user_hidden)})

@app.route('/api/feeds/available')
@login_required
def get_available_feeds():
    """Get list of available feeds that can be added"""
    return jsonify({
        'feeds': available_feeds,
        'total': sum(len(feeds) for feeds in available_feeds.values())
    })

@app.route('/api/feeds/suggestions')
@login_required
def get_feed_suggestions():
    """Return up to 3 unsubscribed available feeds for a given category"""
    category = request.args.get('category', '')
    if not category or category not in available_feeds:
        return jsonify({'suggestions': []})
    active_urls = {subscription.feed.url for subscription in get_user_subscriptions(current_user.id)
                   if subscription.feed and not subscription.is_hidden}
    suggestions = [
        f for f in available_feeds[category]
        if f['url'] not in active_urls
    ][:3]
    return jsonify({'suggestions': suggestions, 'category': category})

@app.route('/api/feeds/add', methods=['POST'])
@login_required
def add_feed():
    """Follow a feed for this user without mutating the global catalogue config."""
    data = request.json
    feed_url = data.get('url')
    category = data.get('category')
    if not feed_url or not category:
        return jsonify({'error': 'URL and category required'}), 400
    if not is_safe_remote_url(feed_url):
        return jsonify({'error': 'A public http(s) feed URL is required'}), 400
    if category not in rss_feeds:
        return jsonify({'error': 'Invalid category'}), 400
    feed = get_or_create_feed(feed_url, category)
    existing = Subscription.query.filter_by(user_id=current_user.id, feed_id=feed.id).first()
    if existing:
        existing.is_hidden = False
    else:
        db.session.add(Subscription(user_id=current_user.id, feed_id=feed.id, is_hidden=False))
    db.session.commit()
    return jsonify({'success': True, 'message': f'Feed added to {category}; worker will ingest it', 'url': feed_url})

# ==================== Preview API ====================

@app.route('/api/preview')
@login_required
def preview_url():
    """Fetch og: metadata for a given URL (ported from Webmark's preview.js)"""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parameter required'}), 400
    try:
        resp = http_requests.get(url, timeout=8, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; OptioBotPreview/1.0)'
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        def og(prop):
            tag = soup.find('meta', property=f'og:{prop}') or soup.find('meta', attrs={'name': prop})
            return tag['content'].strip() if tag and tag.get('content') else ''
        title = og('title') or (soup.title.string.strip() if soup.title else '') or url
        return jsonify({
            'title': title,
            'description': og('description'),
            'image': og('image'),
            'site_name': og('site_name'),
            'url': url
        })
    except Exception as e:
        logging.warning(f"Preview fetch failed for {url}: {e}")
        return jsonify({'title': '', 'description': '', 'image': '', 'site_name': '', 'url': url})

# ==================== Bookmarks API ====================

def _bookmark_to_dict(b):
    return {
        'id': b.id,
        'url': b.url,
        'title': b.title,
        'description': b.description,
        'image_url': b.image_url,
        'tags': b.tags or [],
        'created_at': b.created_at.isoformat()
    }

@app.route('/api/bookmarks', methods=['GET'])
@login_required
def get_bookmarks():
    bmarks = Bookmark.query.filter_by(user_id=current_user.id).order_by(Bookmark.created_at.desc()).all()
    return jsonify({'bookmarks': [_bookmark_to_dict(b) for b in bmarks]})

@app.route('/api/bookmarks', methods=['POST'])
@login_required
def create_bookmark():
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url required'}), 400
    title = data.get('title', '').strip() or url
    b = Bookmark(
        user_id=current_user.id,
        url=url,
        title=title,
        description=data.get('description', ''),
        image_url=data.get('image_url', ''),
        tags=data.get('tags', [])
    )
    db.session.add(b)
    db.session.commit()
    return jsonify(_bookmark_to_dict(b)), 201

@app.route('/api/bookmarks/<int:bookmark_id>', methods=['PUT'])
@login_required
def update_bookmark(bookmark_id):
    b = Bookmark.query.filter_by(id=bookmark_id, user_id=current_user.id).first_or_404()
    data = request.json or {}
    if 'title' in data:
        b.title = data['title'].strip() or b.title
    if 'description' in data:
        b.description = data['description']
    if 'tags' in data:
        b.tags = data['tags']
    if 'image_url' in data:
        b.image_url = data['image_url']
    db.session.commit()
    return jsonify(_bookmark_to_dict(b))

@app.route('/api/bookmarks/<int:bookmark_id>', methods=['DELETE'])
@login_required
def delete_bookmark(bookmark_id):
    b = Bookmark.query.filter_by(id=bookmark_id, user_id=current_user.id).first_or_404()
    db.session.delete(b)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/account', methods=['DELETE'])
@login_required
def delete_account():
    user = db.session.get(User, current_user.id)
    logout_user()
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})

# ==================== Scheduled Job ====================

def job():
    """Worker job: ingest once, then send each opted-in user's digest."""
    from ingestion import ingest_once
    result = ingest_once()
    sent = 0
    for preference in DigestPreference.query.filter_by(enabled=True, cadence='daily').all():
        user_articles, _ = query_persisted_articles(user_id=preference.user_id, limit=20)
        if not user_articles:
            continue
        token = _digest_serializer().dumps({'user_id': preference.user_id})
        base_url = os.getenv('PUBLIC_BASE_URL', 'https://optio.news').rstrip('/')
        html = create_email_content(user_articles, f'{base_url}/digest/unsubscribe/{token}')
        if send_email(html, receiver=preference.user.email):
            sent += 1
    logging.info('Digest job complete: %s', {'ingestion': result, 'sent': sent})
    return {'ingestion': result, 'sent': sent}

def initialize_database():
    """Create the current schema as an explicit one-off operation."""
    with app.app_context():
        db.create_all()

if __name__ == "__main__":
    # Start Flask web server (use PORT env var for Railway, fallback to 5000 locally)
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('RAILWAY_ENVIRONMENT') is None  # disable debug in production
    logging.info(f"Starting web server on port {port}")
    app.run(debug=debug, host='0.0.0.0', port=port, use_reloader=False)
