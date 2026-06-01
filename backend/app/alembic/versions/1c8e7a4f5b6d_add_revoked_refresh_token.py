"""add revoked_refresh_token

Revision ID: 1c8e7a4f5b6d
Revises: 03f84ced3788
Create Date: 2026-05-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '1c8e7a4f5b6d'
down_revision = '03f84ced3788'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'revoked_refresh_token',
        sa.Column('jti', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('jti'),
    )
    # Index expires_at so the periodic prune (DELETE WHERE expires_at < NOW())
    # is cheap as the table grows.
    op.create_index(
        op.f('ix_revoked_refresh_token_expires_at'),
        'revoked_refresh_token',
        ['expires_at'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f('ix_revoked_refresh_token_expires_at'),
        table_name='revoked_refresh_token',
    )
    op.drop_table('revoked_refresh_token')
