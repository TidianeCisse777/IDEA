"""merge agent_type attachments mcp branches

Revision ID: 94878e03adeb
Revises: 4a6f9e0bb0f4, a3f8c2e19b54, e3a1b2c4d5e6
Create Date: 2026-06-03 14:45:10.645665

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '94878e03adeb'
down_revision = ('4a6f9e0bb0f4', 'a3f8c2e19b54', 'e3a1b2c4d5e6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass