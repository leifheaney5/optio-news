import os
import time
import logging
import feedparser
import schedule
import requests as http_requests
from datetime import datetime, timedelta
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
from collections import defaultdict, Counter
import re

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-in-prod')

# Fix Railway's postgres:// prefix — SQLAlchemy 2.x requires postgresql://
_db_url = os.getenv('DATABASE_URL', 'sqlite:///optionews.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True, 'pool_recycle': 300}

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
    ]
}

# Global cache for articles
articles_cache = []
cache_timestamp = None

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

def fetch_articles(force_refresh=False):
    """Fetch articles from RSS feeds with caching"""
    global articles_cache, cache_timestamp
    
    # Return cached articles if less than 30 minutes old
    if not force_refresh and cache_timestamp and articles_cache:
        age = datetime.now() - cache_timestamp
        if age < timedelta(minutes=30):
            logging.info("Returning cached articles")
            return articles_cache
    
    articles = []
    domain_to_category = {}
    
    # Build domain to category mapping
    for category, urls in rss_feeds.items():
        for url in urls:
            domain = url.split('/')[2] if len(url.split('/')) > 2 else url
            domain_to_category[domain] = category
    
    for category, urls in rss_feeds.items():
        for url in urls:
            logging.info(f"Fetching: {url}")
            feed = feedparser.parse(url)
            if feed.bozo:
                logging.warning(f"Bad feed, skipping: {url}")
                continue
            
            for entry in feed.entries[:8]:  # Increased from 5 to 8 per feed
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
                    
                    articles.append({
                        'title': entry.title,
                        'author': getattr(entry, 'author', 'N/A'),
                        'link': entry.link,
                        'summary': getattr(entry, 'summary', 'No summary available'),
                        'category': category,
                        'site': domain,
                        'feed_url': url,
                        'published': pub_date.isoformat(),
                        'published_display': pub_date.strftime('%b %d, %Y %I:%M %p')
                    })
                except AttributeError as e:
                    logging.warning(f"Missing attribute in entry from {url}: {e}. Skipping entry.")
                except Exception as e:
                    logging.error(f"Error processing entry from {url}: {e}")
    
    # Update cache
    articles_cache = articles
    cache_timestamp = datetime.now()
    
    return articles

def extract_trending_topics(articles, top_n=10):
    """
    Extract trending topics from articles using keyword frequency analysis.
    
    This function analyzes articles from the last 24 hours to identify trending topics
    by counting word and phrase frequencies. It filters out common stopwords and generic
    terms to surface more meaningful trends.
    
    Algorithm:
    1. Filter articles to only include those from the last 24 hours
    2. Extract and clean text from titles and summaries (remove HTML entities)
    3. Count frequencies of:
       - Individual words (minimum 4 characters, appearing at least 4 times)
       - Two-word phrases (appearing at least 3 times)
       - Three-word phrases (appearing at least 3 times)
    4. Weight phrases 2x higher than single words (more specific = more relevant)
    5. Filter out generic patterns like "read more", "click here", etc.
    6. Return top N topics with their mention counts and related articles
    
    Args:
        articles: List of article dictionaries with 'title', 'summary', 'published', 'link'
        top_n: Number of top trending topics to return (default: 10)
    
    Returns:
        List of dictionaries with keys:
        - topic: The trending keyword or phrase
        - count: Number of mentions across articles
        - articles: List of related articles (up to 3) with title and link
    """
    
    # Filter articles from last 24 hours
    now = datetime.now()
    recent_articles = []
    for article in articles:
        try:
            pub_date = datetime.fromisoformat(article['published'])
            if now - pub_date <= timedelta(hours=24):
                recent_articles.append(article)
        except (ValueError, KeyError):
            # If date parsing fails, skip this article
            continue
    
    if not recent_articles:
        return []
    
    # Common stopwords to ignore (simple list)
    stop_words = {
        # Articles, conjunctions, prepositions
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
        'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
        'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this',
        'that', 'these', 'those', 'it', 'its', 'their', 'there', 'here',
        
        # News-specific words
        'said', 'says', 'new', 'news', 'report', 'reports', 'reported', 
        'today', 'yesterday', 'week', 'month', 'year', 'day', 'time',
        'article', 'articles', 'story', 'stories', 'post', 'update', 'updates',
        
        # Common verbs and adverbs
        'more', 'most', 'also', 'just', 'now', 'get', 'gets', 'got', 'getting',
        'one', 'two', 'three', 'first', 'second', 'third', 'last', 'next',
        'after', 'over', 'according', 'about', 'up', 'out', 'all', 'years',
        'going', 'make', 'makes', 'made', 'making', 'see', 'sees', 'saw', 'seen',
        'way', 'back', 'many', 'much', 'how', 'take', 'takes', 'took', 'taken',
        
        # Question words and pronouns
        'what', 'when', 'where', 'who', 'why', 'which', 'whose', 'whom',
        'than', 'then', 'them', 'his', 'her', 'she', 'he', 'they', 'we', 
        'you', 'your', 'our', 'my', 'me', 'him', 'them', 'us', 'their',
        
        # Direction and position words
        'into', 'through', 'during', 'before', 'after', 'above', 'below', 
        'between', 'under', 'behind', 'front', 'inside', 'outside',
        
        # Quantifiers and determiners
        'each', 'few', 'some', 'such', 'only', 'own', 'same', 'so', 'than', 
        'too', 'very', 'dont', 'doesnt', 'didnt', 'wont', 'wouldnt', 'cant',
        'every', 'any', 'both', 'either', 'neither', 'other', 'another',
        
        # Generic business/company terms
        'company', 'companies', 'business', 'businesses', 'corporation', 'inc',
        'corp', 'ltd', 'llc', 'group', 'international', 'global', 'national',
        
        # Time-related generic terms
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
        'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
        'september', 'october', 'november', 'december',
        
        # Numbers and quantities
        'million', 'billion', 'trillion', 'thousand', 'hundred', 'thousand',
        'percent', 'per', 'cent', 'number', 'numbers',
        
        # Common adjectives
        'good', 'bad', 'great', 'big', 'small', 'large', 'little', 'high', 
        'low', 'long', 'short', 'old', 'young', 'early', 'late', 'best', 
        'worst', 'better', 'worse', 'less', 'least', 'right', 'wrong',
        
        # Generic people/place terms
        'people', 'person', 'man', 'woman', 'men', 'women', 'child', 'children',
        'world', 'country', 'countries', 'city', 'cities', 'state', 'states',
        'place', 'area', 'region',
        
        # Media/tech generic terms
        'video', 'videos', 'image', 'images', 'photo', 'photos', 'picture',
        'show', 'shows', 'watch', 'watching', 'read', 'reading',
        
        # HTML entities and common artifacts
        'nbsp', 'amp', 'quot', 'apos', 'lt', 'gt', 'copy', 'reg', 'trade',
        'hellip', 'mdash', 'ndash', 'rsquo', 'lsquo', 'rdquo', 'ldquo',
        
        # Action verbs (too generic)
        'get', 'put', 'set', 'use', 'find', 'give', 'tell', 'ask', 'work',
        'seem', 'feel', 'try', 'leave', 'call', 'want', 'need', 'become',
        'let', 'begin', 'help', 'talk', 'turn', 'start', 'show', 'hear',
        'play', 'run', 'move', 'live', 'believe', 'bring', 'happen', 'write',
        'provide', 'sit', 'stand', 'lose', 'pay', 'meet', 'include', 'continue',
        
        # Website/online terms
        'https', 'http', 'www', 'com', 'net', 'org', 'html', 'pdf', 'jpg',
        'png', 'gif', 'link', 'click', 'share', 'tweet', 'post', 'comment',
        
        # Generic modal/linking words
        'not', 'no', 'yes', 'well', 'still', 'even', 'however', 'therefore',
        'thus', 'hence', 'moreover', 'furthermore', 'meanwhile', 'otherwise',
        'instead', 'rather', 'quite', 'almost', 'already', 'always', 'never',
        'often', 'sometimes', 'usually', 'really', 'actually', 'literally'
    }
    
    # Extract and count multi-word phrases (2-3 words) and single words
    phrase_counter = Counter()
    word_counter = Counter()
    
    for article in recent_articles:
        # Combine title and summary for better context
        text = f"{article['title']} {article['summary']}"
        text = text.lower()
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Remove HTML entities
        text = re.sub(r'&[a-z]+;', ' ', text)
        text = re.sub(r'&#\d+;', ' ', text)
        
        # Remove special characters but keep hyphens in words
        text = re.sub(r'[^\w\s-]', ' ', text)
        
        # Clean up multiple spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Simple tokenization - split by spaces
        words = text.split()
        
        # Filter words - must be alphabetic, longer than 2 chars, not in stopwords
        words = [w for w in words if w.isalpha() and len(w) > 2 and w not in stop_words]
        
        # Count single words
        word_counter.update(words)
        
        # Extract 2-word and 3-word phrases
        for i in range(len(words) - 1):
            two_word = f"{words[i]} {words[i+1]}"
            phrase_counter[two_word] += 1
            
            if i < len(words) - 2:
                three_word = f"{words[i]} {words[i+1]} {words[i+2]}"
                phrase_counter[three_word] += 1
    
    # Combine and rank topics
    # Phrases are weighted higher (2x) since they're more specific
    all_topics = []
    
    # Generic phrase patterns to exclude
    generic_phrase_patterns = [
        'read more', 'find out', 'click here', 'sign up', 'log in',
        'learn more', 'check out', 'follow us', 'join us', 'contact us',
        'terms conditions', 'privacy policy', 'cookie policy',
        'copyright all', 'rights reserved', 'all rights'
    ]
    
    # Add top phrases with higher weight
    for phrase, count in phrase_counter.most_common(50):
        # Must appear at least 3 times for better quality
        if count >= 3:
            phrase_lower = phrase.lower()
            
            # Skip generic phrases
            if any(pattern in phrase_lower for pattern in generic_phrase_patterns):
                continue
                
            # Skip phrases that are all numbers or very short words
            phrase_words = phrase.split()
            if all(len(w) <= 2 for w in phrase_words):
                continue
            
            all_topics.append({
                'topic': phrase.title(),
                'count': count * 2,  # Weight phrases higher
                'type': 'phrase'
            })
    
    # Add top single words
    for word, count in word_counter.most_common(50):
        # Must appear at least 4 times and be at least 4 characters for better quality
        if count >= 4 and len(word) >= 4:
            # Don't add if it's part of a common phrase
            word_lower = word.lower()
            is_in_phrase = any(word_lower in phrase['topic'].lower() 
                              for phrase in all_topics[:10])
            if not is_in_phrase:
                all_topics.append({
                    'topic': word.title(),
                    'count': count,
                    'type': 'word'
                })
    
    # Sort by count and get top N
    all_topics.sort(key=lambda x: x['count'], reverse=True)
    
    # Return top N unique topics
    trending = []
    seen = set()
    for topic_data in all_topics:
        topic = topic_data['topic']
        topic_lower = topic.lower()
        
        # Check for duplicates or substrings
        is_duplicate = False
        for seen_topic in seen:
            if topic_lower in seen_topic or seen_topic in topic_lower:
                is_duplicate = True
                break
        
        if not is_duplicate:
            trending.append({
                'topic': topic,
                'count': topic_data['count'] // 2 if topic_data['type'] == 'phrase' else topic_data['count'],
                'articles': []  # Will be populated with relevant articles
            })
            seen.add(topic_lower)
        
        if len(trending) >= top_n:
            break
    
    # Find articles for each trending topic
    for topic_data in trending:
        topic_lower = topic_data['topic'].lower()
        topic_articles = []
        
        for article in recent_articles:
            text = f"{article['title']} {article['summary']}".lower()
            if topic_lower in text:
                topic_articles.append({
                    'title': article['title'],
                    'link': article['link'],
                    'site': article['site'],
                    'category': article['category']
                })
                
                if len(topic_articles) >= 3:  # Max 3 articles per topic
                    break
        
        topic_data['articles'] = topic_articles
    
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
    return render_template('login.html')

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
    return render_template('register.html')

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
        'feed_count': active_feeds
    })

@app.route('/api/trending')
@login_required
def get_trending_topics():
    """API endpoint to get trending topics from last 24 hours"""
    logging.info("Trending topics API called")
    articles = fetch_articles()
    logging.info(f"Found {len(articles)} articles for trending analysis")
    trending = extract_trending_topics(articles, top_n=10)
    logging.info(f"Extracted {len(trending)} trending topics")
    
    return jsonify({
        'trending': trending,
        'count': len(trending),
        'period': '24 hours'
    })

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
