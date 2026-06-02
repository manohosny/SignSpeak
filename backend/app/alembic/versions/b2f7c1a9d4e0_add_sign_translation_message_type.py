"""add sign_translation message type

Adds the gloss-free Direction B recognition path (Uni-Sign signs -> English) as a
distinct MessageType value. Mirrors 03f84ced3788_add_gloss_message_types.

Revision ID: b2f7c1a9d4e0
Revises: 1c8e7a4f5b6d
Create Date: 2026-06-01 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b2f7c1a9d4e0'
down_revision = '1c8e7a4f5b6d'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE messagetype ADD VALUE IF NOT EXISTS 'sign_translation'")


def downgrade():
    # PostgreSQL does not support removing enum values; this is intentionally a no-op.
    pass
