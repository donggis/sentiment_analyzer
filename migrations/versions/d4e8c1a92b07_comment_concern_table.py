"""Add comment_concern without changing existing rows.

Revision ID: d4e8c1a92b07
Revises: b7e1c0a11ad2
Create Date: 2026-11-14

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e8c1a92b07'
down_revision = 'b7e1c0a11ad2'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'comment_concern' in inspector.get_table_names():
        return
    op.create_table(
        'comment_concern',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('comment_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('theme', sa.String(length=80), nullable=False),
        sa.Column('cues', sa.String(length=120), nullable=False, server_default=''),
        sa.Column('summary', sa.String(length=200), nullable=True),
        sa.Column('score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('method', sa.String(length=16), nullable=False, server_default='local'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['comment_id'], ['collected_comment.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('comment_id', name='uq_comment_concern_comment'),
    )
    op.create_index('ix_comment_concern_kind', 'comment_concern', ['kind'])
    op.create_index('ix_comment_concern_theme', 'comment_concern', ['theme'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'comment_concern' not in inspector.get_table_names():
        return
    op.drop_table('comment_concern')
