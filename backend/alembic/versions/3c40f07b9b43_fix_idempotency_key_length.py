"""fix idempotency key length

Revision ID: 3c40f07b9b43
Revises: ababbe05d718
Create Date: 2026-04-02 06:24:42.046325+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c40f07b9b43'
down_revision: Union[str, None] = 'ababbe05d718'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "jobs",
        "idempotency_key",
        type_=sa.Text(),
    )


def downgrade() -> None:
    pass
