"""enforce ready version storage key

Revision ID: 4c2a23ad91fa
Revises: 3e8decfb45b9
Create Date: 2026-11-14 09:13:09.981671

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c2a23ad91fa'
down_revision: Union[str, Sequence[str], None] = '3e8decfb45b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_document_versions_ready_storage_key",
        "document_versions",
        """
        status <> 'READY'
        OR (
            storage_key IS NOT NULL
            AND length(trim(storage_key)) > 0
        )
        """,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_versions_ready_storage_key",
        "document_versions",
        type_="check",
    )
