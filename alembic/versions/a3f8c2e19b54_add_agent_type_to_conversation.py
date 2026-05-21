"""Add agent_type to conversation

Revision ID: a3f8c2e19b54
Revises: d9b987de9ed3
Create Date: 2026-05-21

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a3f8c2e19b54'
down_revision = 'd9b987de9ed3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'conversation',
        sa.Column('agent_type', sa.String(length=64), nullable=False, server_default='generic')
    )


def downgrade() -> None:
    op.drop_column('conversation', 'agent_type')
