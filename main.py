import os
import time
import logging
import feedparser
import schedule
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
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

# User's hidden feeds (persisted)
hidden_feeds = set()

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

def load_hidden_feeds():
    """Load hidden feeds from file"""
    global hidden_feeds
    try:
        if os.path.exists('hidden_feeds.txt'):
            with open('hidden_feeds.txt', 'r') as f:
                hidden_feeds = set(line.strip() for line in f if line.strip())
    except Exception as e:
        logging.error(f"Error loading hidden feeds: {e}")

def save_hidden_feeds():
    """Save hidden feeds to file"""
    try:
        with open('hidden_feeds.txt', 'w') as f:
            for feed in hidden_feeds:
                f.write(f"{feed}\n")
    except Exception as e:
        logging.error(f"Error saving hidden feeds: {e}")

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
            # Skip hidden feeds
            if url in hidden_feeds:
                logging.info(f"Skipping hidden feed: {url}")
                continue
                
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

# Flask Routes
@app.route('/')
def index():
    """Main page route"""
    return render_template('index.html', categories=list(rss_feeds.keys()))

@app.route('/feeds')
def feeds_page():
    """Feed management page"""
    return render_template('feeds.html')

@app.route('/api/articles')
def get_articles_api():
    """API endpoint to fetch articles with filtering"""
    category = request.args.get('category', 'all')
    search = request.args.get('search', '').lower()
    
    articles = fetch_articles()
    
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
    active_feeds = total_feeds - len(hidden_feeds)
    
    return jsonify({
        'articles': articles,
        'count': len(articles),
        'cached': cache_timestamp.isoformat() if cache_timestamp else None,
        'feed_count': active_feeds
    })

@app.route('/api/trending')
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
def refresh_articles():
    """Force refresh articles"""
    articles = fetch_articles(force_refresh=True)
    return jsonify({
        'success': True,
        'count': len(articles),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/feeds')
def get_feeds():
    """Get all RSS feeds with their status"""
    feeds_list = []
    for category, urls in rss_feeds.items():
        for url in urls:
            # Extract feed name from URL
            domain = url.split('/')[2] if len(url.split('/')) > 2 else url
            feeds_list.append({
                'url': url,
                'category': category,
                'name': domain,
                'hidden': url in hidden_feeds
            })
    return jsonify({
        'feeds': feeds_list,
        'total': len(feeds_list),
        'hidden_count': len(hidden_feeds)
    })

@app.route('/api/feeds/hide', methods=['POST'])
def hide_feed():
    """Hide a specific feed"""
    data = request.json
    feed_url = data.get('url')
    
    if not feed_url:
        return jsonify({'error': 'URL required'}), 400
    
    hidden_feeds.add(feed_url)
    save_hidden_feeds()
    
    # Force refresh articles
    fetch_articles(force_refresh=True)
    
    return jsonify({
        'success': True,
        'message': f'Feed hidden: {feed_url}',
        'hidden_count': len(hidden_feeds)
    })

@app.route('/api/feeds/unhide', methods=['POST'])
def unhide_feed():
    """Unhide a specific feed"""
    data = request.json
    feed_url = data.get('url')
    
    if not feed_url:
        return jsonify({'error': 'URL required'}), 400
    
    if feed_url in hidden_feeds:
        hidden_feeds.remove(feed_url)
        save_hidden_feeds()
        
        # Force refresh articles
        fetch_articles(force_refresh=True)
    
    return jsonify({
        'success': True,
        'message': f'Feed unhidden: {feed_url}',
        'hidden_count': len(hidden_feeds)
    })

@app.route('/api/feeds/available')
def get_available_feeds():
    """Get list of available feeds that can be added"""
    return jsonify({
        'feeds': available_feeds,
        'total': sum(len(feeds) for feeds in available_feeds.values())
    })

@app.route('/api/feeds/add', methods=['POST'])
def add_feed():
    """Add a new feed to the active feeds"""
    data = request.json
    feed_url = data.get('url')
    category = data.get('category')
    
    if not feed_url or not category:
        return jsonify({'error': 'URL and category required'}), 400
    
    if category not in rss_feeds:
        return jsonify({'error': 'Invalid category'}), 400
    
    # Add feed to the category if not already present
    if feed_url not in rss_feeds[category]:
        rss_feeds[category].append(feed_url)
        
        # Remove from hidden feeds if it was hidden
        if feed_url in hidden_feeds:
            hidden_feeds.remove(feed_url)
            save_hidden_feeds()
        
        # Force refresh articles
        fetch_articles(force_refresh=True)
        
        return jsonify({
            'success': True,
            'message': f'Feed added to {category}',
            'url': feed_url
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Feed already exists'
        }), 400

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

if __name__ == "__main__":
    # Load hidden feeds
    load_hidden_feeds()
    logging.info(f"Loaded {len(hidden_feeds)} hidden feeds")
    
    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Start Flask web server (articles will be fetched on first request)
    logging.info("Starting web server at http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
