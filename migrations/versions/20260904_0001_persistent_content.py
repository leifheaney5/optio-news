"""Add durable content, subscriptions, reading state, and digest tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '20260904_0001'
down_revision = None
branch_labels = None
depends_on = None


def _create(bind, name, columns, constraints=()):
    if not inspect(bind).has_table(name):
        op.create_table(name, *columns, *constraints)


def upgrade():
    bind = op.get_bind()
    _create(bind, 'users', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.UniqueConstraint('email', name='uq_users_email'),
    ])
    _create(bind, 'user_feeds', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('is_hidden', sa.Boolean()), sa.Column('is_added', sa.Boolean()),
        sa.Column('created_at', sa.DateTime()),
    ])
    _create(bind, 'bookmarks', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('description', sa.Text()), sa.Column('image_url', sa.String(length=2048)),
        sa.Column('tags', sa.JSON()), sa.Column('created_at', sa.DateTime()),
    ])
    _create(bind, 'topic_stats', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('topic', sa.String(length=128), nullable=False),
        sa.Column('day', sa.Date(), nullable=False), sa.Column('count', sa.Integer()),
        sa.UniqueConstraint('topic', 'day', name='uq_topic_day'),
    ])
    _create(bind, 'feeds', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('etag', sa.String(length=512)), sa.Column('last_modified', sa.String(length=512)),
        sa.Column('last_fetched_at', sa.DateTime()), sa.Column('last_success_at', sa.DateTime()),
        sa.Column('last_error', sa.Text()), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('url', name='uq_feeds_url'),
    ])
    _create(bind, 'story_clusters', [
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('label', sa.String(length=512)),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
    ])
    _create(bind, 'subscriptions', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('feed_id', sa.Integer(), sa.ForeignKey('feeds.id'), nullable=False),
        sa.Column('is_hidden', sa.Boolean(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'feed_id', name='uq_subscription_user_feed'),
    ])
    _create(bind, 'articles', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('feed_id', sa.Integer(), sa.ForeignKey('feeds.id'), nullable=False),
        sa.Column('canonical_url', sa.String(length=2048), nullable=False),
        sa.Column('title', sa.String(length=1024), nullable=False), sa.Column('author', sa.String(length=512)),
        sa.Column('summary', sa.Text()), sa.Column('image_url', sa.String(length=2048)),
        sa.Column('published_at', sa.DateTime(), nullable=False), sa.Column('content_hash', sa.String(length=64)),
        sa.Column('guid', sa.String(length=2048)), sa.Column('cluster_id', sa.Integer(), sa.ForeignKey('story_clusters.id')),
        sa.Column('fetched_at', sa.DateTime(), nullable=False), sa.Column('search_document', sa.Text()),
        sa.UniqueConstraint('canonical_url', name='uq_articles_canonical_url'),
    ])
    _create(bind, 'user_article_states', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('article_id', sa.Integer(), sa.ForeignKey('articles.id'), nullable=False),
        sa.Column('first_seen_at', sa.DateTime()), sa.Column('last_impression_at', sa.DateTime()),
        sa.Column('read_at', sa.DateTime()), sa.Column('dismissed_at', sa.DateTime()),
        sa.UniqueConstraint('user_id', 'article_id', name='uq_article_state_user_article'),
    ])
    _create(bind, 'digest_preferences', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('cadence', sa.String(length=32), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', name='uq_digest_preferences_user'),
    ])
    _create(bind, 'saved_searches', [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('query', sa.String(length=256), nullable=False), sa.Column('category', sa.String(length=64)),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'query', 'category', name='uq_saved_search_user_query_category'),
    ])
    for table, columns in {
        'feeds': ['category'], 'articles': ['feed_id', 'published_at', 'cluster_id', 'content_hash'],
        'subscriptions': ['user_id', 'feed_id'], 'user_article_states': ['user_id', 'article_id'],
    }.items():
        existing = {index['name'] for index in inspect(bind).get_indexes(table)}
        for column in columns:
            name = f'ix_{table}_{column}'
            if name not in existing:
                op.create_index(name, table, [column])
    if bind.dialect.name == 'postgresql':
        op.execute("CREATE INDEX IF NOT EXISTS ix_articles_search_document_fts ON articles USING gin (to_tsvector('english', coalesce(search_document, '')))")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute('DROP INDEX IF EXISTS ix_articles_search_document_fts')
    for table in ['saved_searches', 'digest_preferences', 'user_article_states', 'articles', 'subscriptions', 'story_clusters', 'feeds']:
        if inspect(bind).has_table(table):
            op.drop_table(table)
