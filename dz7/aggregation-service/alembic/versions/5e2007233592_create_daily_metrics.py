"""create daily_metrics

Revision ID: 5e2007233592
Revises: 
Create Date: 2026-04-21 22:56:52.266047

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5e2007233592'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_metrics",
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("dimension_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("dimension_value", sa.Text(), nullable=False, server_default=""),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("metric_date", "metric_name", "dimension_key", "dimension_value"),
    )
    op.create_index(
        "idx_daily_metrics_lookup",
        "daily_metrics",
        ["metric_date", "metric_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_daily_metrics_lookup", table_name="daily_metrics")
    op.drop_table("daily_metrics")
