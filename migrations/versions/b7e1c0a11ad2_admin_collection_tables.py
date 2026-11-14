"""Collection tables and video sync columns for the private admin library.

Revision ID: b7e1c0a11ad2
Revises: 078c7c5dd96c
Create Date: 2026-11-14

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e1c0a11ad2'
down_revision = '078c7c5dd96c'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if 'video' in tables:
        columns = {column['name'] for column in inspector.get_columns('video')}
        with op.batch_alter_table('video') as batch:
            if 'duration_seconds' not in columns:
                batch.add_column(sa.Column('duration_seconds', sa.Integer(), nullable=True))
            if 'comments_disabled' not in columns:
                batch.add_column(sa.Column('comments_disabled', sa.Boolean(), nullable=False, server_default=sa.false()))
            if 'comments_synced_at' not in columns:
                batch.add_column(sa.Column('comments_synced_at', sa.DateTime(), nullable=True))

    if 'admin_session' not in tables:
        op.create_table(
            'admin_session',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('token_hash', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_admin_session_token_hash', 'admin_session', ['token_hash'], unique=True)
        op.create_index('ix_admin_session_expires_at', 'admin_session', ['expires_at'])

    if 'login_attempt' not in tables:
        op.create_table(
            'login_attempt',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('ip_hash', sa.String(length=64), nullable=False),
            sa.Column('success', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_login_attempt_ip_hash', 'login_attempt', ['ip_hash'])
        op.create_index('ix_login_attempt_created_at', 'login_attempt', ['created_at'])

    if 'collection_job' not in tables:
        op.create_table(
            'collection_job',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('channel_ref', sa.String(length=500), nullable=False),
            sa.Column('channel_id', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(length=32), nullable=False),
            sa.Column('phase', sa.String(length=32), nullable=False),
            sa.Column('page_token', sa.String(length=255), nullable=True),
            sa.Column('saved_next_thread_token', sa.String(length=255), nullable=True),
            sa.Column('current_video_yt_id', sa.String(length=64), nullable=True),
            sa.Column('reply_parent_id', sa.String(length=128), nullable=True),
            sa.Column('reply_page_token', sa.String(length=255), nullable=True),
            sa.Column('pending_reply_ids', sa.JSON(), nullable=True),
            sa.Column('api_steps', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('lease_owner', sa.String(length=64), nullable=True),
            sa.Column('lease_until', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['channel_id'], ['channel.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_collection_job_channel_id', 'collection_job', ['channel_id'])
        op.create_index('ix_collection_job_status', 'collection_job', ['status'])

    if 'collected_comment' not in tables:
        op.create_table(
            'collected_comment',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('yt_comment_id', sa.String(length=128), nullable=False),
            sa.Column('video_id', sa.Integer(), nullable=False),
            sa.Column('parent_yt_comment_id', sa.String(length=128), nullable=True),
            sa.Column('text', sa.Text(), nullable=False),
            sa.Column('author_display', sa.String(length=255), nullable=True),
            sa.Column('like_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('published_at', sa.DateTime(), nullable=True),
            sa.Column('reply_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('replies_complete', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['video_id'], ['video.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_collected_comment_yt_comment_id', 'collected_comment', ['yt_comment_id'], unique=True)
        op.create_index('ix_collected_comment_video_id', 'collected_comment', ['video_id'])
        op.create_index('ix_collected_comment_parent', 'collected_comment', ['parent_yt_comment_id'])
        op.create_index('ix_collected_comment_published_at', 'collected_comment', ['published_at'])

    if 'comment_tag' not in tables:
        op.create_table(
            'comment_tag',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('comment_id', sa.Integer(), nullable=False),
            sa.Column('tag', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['comment_id'], ['collected_comment.id']),
            sa.UniqueConstraint('comment_id', 'tag', name='uq_comment_tag'),
        )
        op.create_index('ix_comment_tag_comment_id', 'comment_tag', ['comment_id'])

    if 'topic' not in tables:
        op.create_table(
            'topic',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('channel_id', sa.Integer(), nullable=False),
            sa.Column('label', sa.String(length=255), nullable=False),
            sa.Column('keywords', sa.String(length=500), nullable=True),
            sa.Column('method', sa.String(length=32), nullable=False),
            sa.Column('comment_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['channel_id'], ['channel.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_topic_channel_id', 'topic', ['channel_id'])

    if 'comment_topic' not in tables:
        op.create_table(
            'comment_topic',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('comment_id', sa.Integer(), nullable=False),
            sa.Column('topic_id', sa.Integer(), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
            sa.ForeignKeyConstraint(['comment_id'], ['collected_comment.id']),
            sa.ForeignKeyConstraint(['topic_id'], ['topic.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('comment_id'),
        )
        op.create_index('ix_comment_topic_topic_id', 'comment_topic', ['topic_id'])


def downgrade():
    for table in ('comment_topic', 'topic', 'comment_tag', 'collected_comment', 'collection_job', 'login_attempt', 'admin_session'):
        op.drop_table(table)
    with op.batch_alter_table('video') as batch:
        batch.drop_column('comments_synced_at')
        batch.drop_column('comments_disabled')
        batch.drop_column('duration_seconds')
