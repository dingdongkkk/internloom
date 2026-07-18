"""add listing target fields

Revision ID: 9b1d0e2a7c41
Revises: 4ce49e93a3bb
Create Date: 2026-07-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9b1d0e2a7c41"
down_revision: Union[str, None] = "4ce49e93a3bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("target_branch", sa.String(length=100), nullable=True))
    op.add_column("listings", sa.Column("target_graduation_year", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_listings_target_branch"), "listings", ["target_branch"], unique=False)
    op.create_index(
        op.f("ix_listings_target_graduation_year"),
        "listings",
        ["target_graduation_year"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_listings_target_graduation_year"), table_name="listings")
    op.drop_index(op.f("ix_listings_target_branch"), table_name="listings")
    op.drop_column("listings", "target_graduation_year")
    op.drop_column("listings", "target_branch")
