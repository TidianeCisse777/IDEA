"""add_attachments_to_message

Revision ID: e3a1b2c4d5e6
Revises: d9b987de9ed3
Create Date: 2026-06-02 18:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3a1b2c4d5e6'
down_revision = 'd9b987de9ed3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'message',
        sa.Column('attachments', sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('message', 'attachments')
