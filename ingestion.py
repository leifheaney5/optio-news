"""Worker-only RSS ingestion for Optio.

The web process imports this module only for explicit maintenance commands;
normal page and API requests never call the network.
"""

import calendar
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
from bs4 import BeautifulSoup


TRACKING_KEYS = {'fbclid', 'gclid', 'ref', 'ref_src'}


def canonicalize_url(url):
    """Normalize a feed link so tracking parameters do not create duplicates."""
    url = (url or '').strip()
    if not url:
        return ''
    try:
        parts = urlsplit(url)
        if parts.scheme not in {'http', 'https'} or not parts.netloc:
            return url
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if not key.lower().startswith('utm_') and key.lower() not in TRACKING_KEYS]
        path = parts.path.rstrip('/') or '/'
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                           urlencode(query, doseq=True), ''))
    except ValueError:
        return url


def _published_at(entry):
    for attr in ('published_parsed', 'updated_parsed'):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime.utcfromtimestamp(calendar.timegm(parsed[:6]))
            except (TypeError, ValueError, OverflowError):
                pass
    return datetime.utcnow()


def _image_from_entry(entry):
    for attr in ('media_thumbnail', 'media_content', 'enclosures'):
        for candidate in (getattr(entry, attr, None) or []):
            image = candidate.get('url') or candidate.get('href') or ''
            if image and (attr != 'enclosures' or candidate.get('type', '').startswith('image/')):
                return image
    for blob in [getattr(entry, 'summary', '')] + [item.get('value', '') for item in (getattr(entry, 'content', None) or [])]:
        match = re.search(r'<img[^>]+src=["\']([^"\']+)', blob or '')
        if match:
            return match.group(1)
    return ''


def _snapshot(feed_data):
    """Fetch one feed with conditional headers and return serializable data."""
    feed_id, url, etag, last_modified = feed_data
    headers = {'User-Agent': 'OptioNewsBot/1.0 (+https://optio.news)'}
    if etag:
        headers['If-None-Match'] = etag
    if last_modified:
        headers['If-Modified-Since'] = last_modified
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 304:
            return {'feed_id': feed_id, 'status': 304, 'records': [], 'etag': etag,
                    'last_modified': last_modified}
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        records = []
        for entry in parsed.entries[:30]:
            link = canonicalize_url(getattr(entry, 'link', ''))
            title = (getattr(entry, 'title', '') or '').strip()
            if not link or not title:
                continue
            summary = getattr(entry, 'summary', '') or ''
            records.append({
                'canonical_url': link,
                'title': title[:1024],
                'author': (getattr(entry, 'author', '') or '')[:512],
                'summary': summary,
                'image_url': _image_from_entry(entry),
                'published_at': _published_at(entry),
                'guid': (getattr(entry, 'id', '') or link)[:2048],
            })
        return {'feed_id': feed_id, 'status': response.status_code, 'records': records,
                'etag': response.headers.get('ETag'),
                'last_modified': response.headers.get('Last-Modified'), 'error': None}
    except Exception as exc:
        logging.warning('Feed fetch failed for %s: %s', url, exc)
        return {'feed_id': feed_id, 'status': 0, 'records': [], 'error': str(exc)[:1000]}


def _enrich_records(records, max_lookups=160):
    """Perform optional page image lookups in the worker, never in a request."""

    def extract_og_image(url):
        try:
            response = requests.get(url, timeout=6, headers={'User-Agent': 'OptioNewsBot/1.0'})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            tag = (soup.find('meta', property='og:image')
                   or soup.find('meta', attrs={'name': 'twitter:image'}))
            image = tag.get('content', '').strip() if tag else ''
            return image if image.startswith(('http://', 'https://')) else ''
        except Exception:
            return ''

    missing = [record for record in records if not record.get('image_url')][:max_lookups]
    if not missing:
        return
    with ThreadPoolExecutor(max_workers=16) as pool:
        for record, image in zip(missing, pool.map(lambda item: extract_og_image(item['canonical_url']), missing)):
            if image:
                record['image_url'] = image


def ingest_once():
    """Fetch active feeds, upsert articles, and rebuild recent story groups."""
    from main import Article, Feed, app, db, get_or_create_feed, rss_feeds

    # This function is invoked under an app context by scheduled_job/worker.
    if not Feed.query.count():
        for category, urls in rss_feeds.items():
            for url in urls:
                get_or_create_feed(url, category)
        db.session.commit()

    feeds = Feed.query.filter_by(active=True).all()
    payloads = [(feed.id, feed.url, feed.etag, feed.last_modified) for feed in feeds]
    snapshots = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for snapshot in pool.map(_snapshot, payloads):
            snapshots.append(snapshot)

    all_records = [record for snapshot in snapshots for record in snapshot['records']]
    _enrich_records(all_records)
    now = datetime.utcnow()
    inserted = 0
    updated = 0
    for snapshot in snapshots:
        feed = db.session.get(Feed, snapshot['feed_id'])
        if not feed:
            continue
        feed.last_fetched_at = now
        if snapshot.get('etag'):
            feed.etag = snapshot['etag']
        if snapshot.get('last_modified'):
            feed.last_modified = snapshot['last_modified']
        if snapshot.get('status') in range(200, 400):
            feed.last_success_at = now
            feed.last_error = None
        elif snapshot.get('error'):
            feed.last_error = snapshot['error']
        for record in snapshot['records']:
            record['canonical_url'] = canonicalize_url(record.get('canonical_url', ''))
            if not record['canonical_url']:
                continue
            existing = Article.query.filter_by(canonical_url=record['canonical_url']).first()
            digest = __import__('hashlib').sha256(
                f"{record['title']}|{record['summary']}".encode('utf-8', 'ignore')
            ).hexdigest()
            if existing:
                existing.title = record['title']
                existing.author = record['author']
                existing.summary = record['summary']
                existing.image_url = existing.image_url or record['image_url']
                existing.published_at = record['published_at']
                existing.guid = record['guid']
                existing.content_hash = digest
                existing.search_document = f"{record['title']} {record['summary']}"
                existing.feed_id = feed.id
                existing.fetched_at = now
                updated += 1
            else:
                db.session.add(Article(
                    feed_id=feed.id,
                    canonical_url=record['canonical_url'],
                    title=record['title'],
                    author=record['author'],
                    summary=record['summary'],
                    image_url=record['image_url'],
                    published_at=record['published_at'],
                    guid=record['guid'],
                    content_hash=digest,
                    search_document=f"{record['title']} {record['summary']}",
                    fetched_at=now,
                ))
                inserted += 1
    db.session.commit()

    from clustering import recluster_recent
    clustered = recluster_recent()
    logging.info('Ingestion complete: %d inserted, %d updated, %d recent clusters', inserted, updated, clustered)
    return {'feeds': len(feeds), 'inserted': inserted, 'updated': updated, 'clusters': clustered}
