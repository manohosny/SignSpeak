"""add message flag columns

User-feedback capture: participants can flag a persisted message as a wrong
translation (POST /meetings/{id}/messages/{message_id}/flag). Additive only.

Revision ID: c4d8e2f1a7b3
Revises: b2f7c1a9d4e0
Create Date: 2026-06-12 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c4d8e2f1a7b3'
down_revision = 'b2f7c1a9d4e0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'meeting_message',
        sa.Column('flagged_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'meeting_message',
        sa.Column('flag_reason', sa.String(length=500), nullable=True),
    )


def downgrade():
    op.drop_column('meeting_message', 'flag_reason')
    op.drop_column('meeting_message', 'flagged_at')
