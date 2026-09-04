"""Deterministic, explainable story clustering for recent persisted articles."""

import re
from collections import defaultdict
from datetime import datetime, timedelta


STOPWORDS = {
    # Grammar and common RSS boilerplate must not join unrelated stories.
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of',
    'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these',
    'those', 'it', 'its', 'their', 'there', 'here', 'his', 'her', 'she', 'he',
    'they', 'we', 'you', 'your', 'our', 'who', 'what', 'which', 'where', 'when',
    'why', 'how', 'about', 'after', 'again', 'also', 'because', 'before',
    'between', 'during', 'following', 'including', 'into', 'just', 'more',
    'most', 'only', 'other', 'over', 'same', 'some', 'than', 'then', 'through',
    'under', 'until', 'very', 'while', 'without',
    # News and generic nouns are not story identity.
    'said', 'says', 'say', 'told', 'report', 'reports', 'reported', 'reporting',
    'news', 'story', 'stories', 'article', 'articles', 'update', 'updates',
    'latest', 'breaking', 'live', 'new', 'major', 'general', 'public',
    'official', 'world', 'country', 'city', 'government', 'company',
    'companies', 'business', 'group', 'groups', 'team', 'people', 'person',
    'market', 'markets', 'data', 'case', 'cases', 'plan', 'plans', 'role',
    'claim', 'claims', 'rule', 'rules', 'risk', 'risks', 'rate', 'rates',
    'cost', 'costs', 'issue', 'issues', 'price', 'prices', 'sale', 'sales',
    'loss', 'losses', 'gain', 'gains', 'growth', 'fund', 'funds', 'source',
    'sources', 'impact', 'effect', 'result', 'results', 'number', 'numbers',
    # Time and URL noise.
    'today', 'yesterday', 'week', 'month', 'year', 'day', 'time', 'years',
    'days', 'hours', 'minutes', 'soon', 'recently', 'https', 'http', 'www',
    'com', 'net', 'org', 'html', 'pdf',
}


def _tokens(article):
    words = re.findall(r'[a-z0-9]{3,}', f'{article.title} {article.summary or ""}'.lower())
    return {word for word in words if word not in STOPWORDS}


def _similar(left, right):
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return overlap / len(left | right)


def recluster_recent(hours=36):
    """Rebuild clusters for a bounded recent window using token overlap."""
    from main import Article, StoryCluster, db

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    articles = Article.query.filter(Article.published_at >= cutoff).order_by(Article.published_at.asc()).all()
    if not articles:
        return 0
    token_sets = {article.id: _tokens(article) for article in articles}
    parent = {article.id: article.id for article in articles}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left, right):
        lroot, rroot = find(left), find(right)
        if lroot != rroot:
            parent[rroot] = lroot

    inverted = defaultdict(set)
    for article_id, tokens in token_sets.items():
        for token in tokens:
            inverted[token].add(article_id)
    for article in articles:
        candidates = set()
        for token in token_sets[article.id]:
            candidates.update(inverted[token])
        for other_id in candidates:
            if other_id >= article.id:
                continue
            # Two shared tokens or a strong Jaccard match are enough for a
            # story family, but source/category differences are not ignored.
            overlap = len(token_sets[article.id] & token_sets[other_id])
            if overlap >= 2 or _similar(token_sets[article.id], token_sets[other_id]) >= 0.42:
                union(article.id, other_id)

    groups = defaultdict(list)
    for article in articles:
        groups[find(article.id)].append(article)
    touched = set()
    for members in groups.values():
        existing_cluster = next((member.cluster for member in members if member.cluster), None)
        cluster = existing_cluster or StoryCluster(label=members[0].title[:512])
        cluster.updated_at = datetime.utcnow()
        if not existing_cluster:
            db.session.add(cluster)
            db.session.flush()
        for member in members:
            member.cluster_id = cluster.id
        touched.add(cluster.id)
    db.session.commit()
    return len(touched)
