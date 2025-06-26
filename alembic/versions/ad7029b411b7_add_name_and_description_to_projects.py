"""add_name_and_description_to_projects

Revision ID: ad7029b411b7
Revises: fad2e5b46554
Create Date: 2025-06-26 04:10:20.988324

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ad7029b411b7"
down_revision: Union[str, None] = "fad2e5b46554"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_mundiai_projects", sa.Column("name", sa.String(), nullable=True)
    )
    op.add_column(
        "user_mundiai_projects", sa.Column("description", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("user_mundiai_projects", "description")
    op.drop_column("user_mundiai_projects", "name")
