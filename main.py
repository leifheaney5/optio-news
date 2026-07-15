import os
import time
import logging
import feedparser
import schedule
import requests as http_requests
from datetime import datetime, timedelta, date
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import smtplib
import threading
import socket
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict, Counter
import re

load_dotenv()

logging.basicConfig(level=logging.INFO)

# A single unreachable feed must never hang the whole fetch
socket.setdefaulttimeout(10)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-in-prod')

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

# Global cache for articles
articles_cache = []
cache_timestamp = None
# Single-flight guard: only one thread fetches the 70+ feeds at a time
_fetch_lock = threading.Lock()

# ==================== Per-User Feed Helpers ====================

def get_user_hidden_feeds(user_id):
    """Get set of hidden feed URLs for a given user"""
    try:
        rows = UserFeed.query.filter_by(user_id=user_id, is_hidden=True).all()
        return {row.url for row in rows}
    except Exception as e:
        logging.error(f"Error fetching hidden feeds: {e}")
        return set()

def get_user_added_feeds(user_id):
    """Returns {category: [url, ...]} for feeds a user has added"""
    try:
        rows = UserFeed.query.filter_by(user_id=user_id, is_added=True).all()
        result = {}
        for row in rows:
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

def _fetch_one_feed(category, url):
    """Fetch and parse a single RSS feed. Returns a list of article dicts."""
    logging.info(f"Fetching: {url}")
    out = []
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        logging.warning(f"Feed fetch failed, skipping: {url} ({e})")
        return out
    if feed.bozo:
        logging.warning(f"Bad feed, skipping: {url}")
        return out

    for entry in feed.entries[:8]:
        try:
            # Get publication date
            pub_date = datetime.now()
            try:
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    time_tuple = entry.published_parsed
                    pub_date = datetime(int(time_tuple[0]), int(time_tuple[1]), int(time_tuple[2]),
                                      int(time_tuple[3]), int(time_tuple[4]), int(time_tuple[5]))
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    time_tuple = entry.updated_parsed
                    pub_date = datetime(int(time_tuple[0]), int(time_tuple[1]), int(time_tuple[2]),
                                      int(time_tuple[3]), int(time_tuple[4]), int(time_tuple[5]))
            except (ValueError, TypeError, IndexError):
                # If date parsing fails, use current time
                pass

            domain = url.split('/')[2] if len(url.split('/')) > 2 else url

            # Extract image from media_thumbnail, media_content, or enclosure
            image_url = ''
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get('url', '')
            elif hasattr(entry, 'media_content') and entry.media_content:
                image_url = entry.media_content[0].get('url', '')
            elif hasattr(entry, 'enclosures') and entry.enclosures:
                for enc in entry.enclosures:
                    if enc.get('type', '').startswith('image/'):
                        image_url = enc.get('href', enc.get('url', ''))
                        break
            # Fallback: pull first <img> from summary or full-content HTML
            if not image_url:
                html_blobs = [getattr(entry, 'summary', '')]
                for c in (getattr(entry, 'content', None) or []):
                    html_blobs.append(c.get('value', ''))
                for blob in html_blobs:
                    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', blob)
                    if m:
                        image_url = m.group(1)
                        break

            out.append({
                'title': entry.title,
                'author': getattr(entry, 'author', 'N/A'),
                'link': entry.link,
                'summary': getattr(entry, 'summary', 'No summary available'),
                'category': category,
                'site': domain,
                'feed_url': url,
                'published': pub_date.isoformat(),
                'published_display': pub_date.strftime('%b %d, %Y %I:%M %p'),
                'image_url': image_url,
            })
        except AttributeError as e:
            logging.warning(f"Missing attribute in entry from {url}: {e}. Skipping entry.")
        except Exception as e:
            logging.error(f"Error processing entry from {url}: {e}")
    return out


def _extract_og_image(url):
    """Fetch a page and return its og:image / twitter:image URL, if any."""
    try:
        resp = http_requests.get(url, timeout=6, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; OptioBotPreview/1.0)'
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        tag = (soup.find('meta', property='og:image')
               or soup.find('meta', attrs={'name': 'twitter:image'})
               or soup.find('meta', attrs={'property': 'twitter:image'}))
        if tag and tag.get('content'):
            img = tag['content'].strip()
            if img.startswith('http'):
                return img
    except Exception:
        pass
    return ''


def _enrich_missing_images(articles, max_lookups=160):
    """For articles whose feed carried no image, pull og:image from the
    article page itself. Runs in parallel; failures just leave the article
    on the headline-first treatment."""
    missing = [a for a in articles if not a.get('image_url')][:max_lookups]
    if not missing:
        return
    logging.info(f"Enriching {len(missing)} articles with og:image lookups")
    with ThreadPoolExecutor(max_workers=16) as pool:
        for article, img in zip(missing, pool.map(lambda a: _extract_og_image(a['link']), missing)):
            if img:
                article['image_url'] = img
    found = sum(1 for a in missing if a.get('image_url'))
    logging.info(f"og:image enrichment found {found}/{len(missing)} images")


def fetch_articles(force_refresh=False):
    """Fetch articles from RSS feeds with caching.

    Feeds are fetched in parallel, and only one fetch runs at a time
    process-wide: concurrent callers get the current cache immediately
    instead of piling up duplicate 70-feed crawls.
    """
    global articles_cache, cache_timestamp

    # Return cached articles if less than 30 minutes old
    if not force_refresh and cache_timestamp and articles_cache:
        age = datetime.now() - cache_timestamp
        if age < timedelta(minutes=30):
            logging.info("Returning cached articles")
            return articles_cache

    if not _fetch_lock.acquire(blocking=False):
        # Another thread is already crawling the feeds — serve what we have.
        logging.info("Fetch already in progress; returning current cache")
        return articles_cache

    try:
        # Snapshot to avoid mutation while iterating
        pairs = [(category, url)
                 for category, urls in rss_feeds.items()
                 for url in list(urls)]

        articles = []
        with ThreadPoolExecutor(max_workers=12) as pool:
            for feed_articles in pool.map(lambda p: _fetch_one_feed(*p), pairs):
                articles.extend(feed_articles)

        # Image-forward: fill in missing article imagery from the pages themselves
        _enrich_missing_images(articles)

        # Update cache
        articles_cache = articles
        cache_timestamp = datetime.now()
        return articles
    finally:
        _fetch_lock.release()


def cache_is_warming():
    """True while the very first crawl is still running (no cache yet)."""
    return cache_timestamp is None and _fetch_lock.locked()

def extract_trending_topics(articles, top_n=10):
    """
    Extract trending topics using named-entity heuristics + article-spread scoring.
    Prefers proper nouns (people, places, orgs, events) spread across many articles.
    """
    now = datetime.now()
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

def create_email_content(articles):
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
        </p>
      </body>
    </html>
    """

def send_email(html_content):
    sender = os.getenv('SENDER_EMAIL')
    receiver = os.getenv('RECEIVER_EMAIL')
    pwd = os.getenv('APP_PASSWORD')
    if not (sender and receiver and pwd):
        logging.error("Missing one of SENDER_EMAIL, RECEIVER_EMAIL, APP_PASSWORD")
        return

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
    except Exception as e:
        logging.error(f"Email error: {e}")

# ==================== Auth Routes ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html', categories=list(rss_feeds.keys()))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if not email or not password:
            flash('Email and password are required.', 'error')
        elif password != confirm:
            flash('Passwords do not match.', 'error')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'error')
        else:
            user = User(
                email=email,
                password_hash=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for('index'))
    return render_template('register.html', categories=list(rss_feeds.keys()))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ==================== Flask Routes ====================

@app.route('/')
@login_required
def index():
    """Main page route"""
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
    """API endpoint to fetch articles with filtering"""
    category = request.args.get('category', 'all')
    search = request.args.get('search', '').lower()

    articles = fetch_articles()

    # Filter out feeds hidden by this user
    user_hidden = get_user_hidden_feeds(current_user.id)
    if user_hidden:
        articles = [a for a in articles if a.get('feed_url') not in user_hidden]

    # Filter by category
    if category != 'all':
        articles = [a for a in articles if a['category'] == category]

    # Filter by search term
    if search:
        articles = [a for a in articles if
                    search in a['title'].lower() or
                    search in a['summary'].lower()]

    # Calculate total active feeds
    total_feeds = sum(len(feeds) for feeds in rss_feeds.values())
    active_feeds = total_feeds - len(user_hidden)

    return jsonify({
        'articles': articles,
        'count': len(articles),
        'cached': cache_timestamp.isoformat() if cache_timestamp else None,
        'feed_count': active_feeds,
        # True only during the very first crawl after startup — tells the
        # frontend to keep its skeletons up and retry shortly.
        'warming': cache_is_warming()
    })

# Memoized trending results, keyed by category, valid for one article-cache
# generation. Movement ranks persist across generations for ▲/▼ badges.
_trending_memo = {}
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
    articles = fetch_articles()

    # Serve memoized results while the article cache generation is unchanged
    memo = _trending_memo.get(category)
    if memo and memo[0] == cache_timestamp:
        return jsonify(memo[1])

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
    _trending_memo[category] = (cache_timestamp, payload)
    logging.info(f"Trending computed for '{category}': {len(trending)} topics")
    return jsonify(payload)

@app.route('/api/refresh')
@login_required
def refresh_articles():
    """Force refresh articles"""
    articles = fetch_articles(force_refresh=True)
    return jsonify({
        'success': True,
        'count': len(articles),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/feeds')
@login_required
def get_feeds():
    """Get all RSS feeds with their status for the current user"""
    user_hidden = get_user_hidden_feeds(current_user.id)
    feeds_list = []
    for category, urls in rss_feeds.items():
        for url in urls:
            domain = url.split('/')[2] if len(url.split('/')) > 2 else url
            feeds_list.append({
                'url': url,
                'category': category,
                'name': domain,
                'hidden': url in user_hidden
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
    existing = UserFeed.query.filter_by(user_id=current_user.id, url=feed_url).first()
    if existing:
        existing.is_hidden = True
    else:
        db.session.add(UserFeed(user_id=current_user.id, category=category, url=feed_url, is_hidden=True))
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
    existing = UserFeed.query.filter_by(user_id=current_user.id, url=feed_url).first()
    if existing:
        existing.is_hidden = False
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
    active_urls = set(rss_feeds.get(category, []))
    suggestions = [
        f for f in available_feeds[category]
        if f['url'] not in active_urls
    ][:3]
    return jsonify({'suggestions': suggestions, 'category': category})

@app.route('/api/feeds/add', methods=['POST'])
@login_required
def add_feed():
    """Add a new feed to the active feeds (persisted in DB + global dict)"""
    data = request.json
    feed_url = data.get('url')
    category = data.get('category')
    if not feed_url or not category:
        return jsonify({'error': 'URL and category required'}), 400
    if category not in rss_feeds:
        return jsonify({'error': 'Invalid category'}), 400
    # Add to global dict so all users benefit immediately
    if feed_url not in rss_feeds[category]:
        rss_feeds[category].append(feed_url)
    # Persist to DB for this user
    existing = UserFeed.query.filter_by(user_id=current_user.id, url=feed_url).first()
    if existing:
        existing.is_added = True
        existing.is_hidden = False
    else:
        db.session.add(UserFeed(user_id=current_user.id, category=category, url=feed_url, is_added=True))
    db.session.commit()
    fetch_articles(force_refresh=True)
    return jsonify({'success': True, 'message': f'Feed added to {category}', 'url': feed_url})

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
    """Scheduled job to send email"""
    arts = fetch_articles(force_refresh=True)
    if arts:
        html = create_email_content(arts)
        send_email(html)
        logging.info("Daily email sent successfully")
    else:
        logging.warning("No articles fetched for scheduled job.")

def run_scheduler():
    """Run the scheduler in a background thread"""
    while True:
        schedule.run_pending()
        time.sleep(60)

# Schedule email for 9am daily
schedule.every().day.at("09:00").do(job)

# ==================== App Startup (runs on import + __main__) ====================
def _startup():
    """Initialize DB tables and re-hydrate user-added feeds. Safe to call multiple times."""
    with app.app_context():
        db.create_all()
        try:
            added_rows = UserFeed.query.filter_by(is_added=True).all()
            for row in added_rows:
                if row.category in rss_feeds and row.url not in rss_feeds[row.category]:
                    rss_feeds[row.category].append(row.url)
            logging.info(f"Loaded {len(added_rows)} user-added feeds into rss_feeds")
        except Exception as e:
            logging.warning(f"Could not load user-added feeds on startup: {e}")

    # Warm the article cache in the background so the first user request is fast
    def _warm_cache():
        with app.app_context():
            try:
                logging.info("Warming article cache in background...")
                fetch_articles(force_refresh=True)
                logging.info("Article cache warmed successfully")
            except Exception as e:
                logging.warning(f"Cache warm failed (non-fatal): {e}")

    warm_thread = threading.Thread(target=_warm_cache, daemon=True)
    warm_thread.start()

_startup()

if __name__ == "__main__":
    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Start Flask web server (use PORT env var for Railway, fallback to 5000 locally)
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('RAILWAY_ENVIRONMENT') is None  # disable debug in production
    logging.info(f"Starting web server on port {port}")
    app.run(debug=debug, host='0.0.0.0', port=port, use_reloader=False)
