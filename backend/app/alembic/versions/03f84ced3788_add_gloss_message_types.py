"""add gloss message types

Revision ID: 03f84ced3788
Revises: a6ec6de6be1e
Create Date: 2026-05-01 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '03f84ced3788'
down_revision = 'a6ec6de6be1e'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE messagetype ADD VALUE IF NOT EXISTS 'gloss_translation'")
    op.execute("ALTER TYPE messagetype ADD VALUE IF NOT EXISTS 'gloss_input'")


def downgrade():
    # PostgreSQL does not support removing enum values; this is intentionally a no-op.
    pass
