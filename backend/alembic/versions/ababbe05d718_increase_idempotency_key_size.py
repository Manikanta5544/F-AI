"""increase idempotency key size

Revision ID: ababbe05d718
Revises: 71c631e4891b
Create Date: 2026-04-02 06:11:26.108943+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ababbe05d718'
down_revision: Union[str, None] = '71c631e4891b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    
    pass


def downgrade() -> None:
    pass
