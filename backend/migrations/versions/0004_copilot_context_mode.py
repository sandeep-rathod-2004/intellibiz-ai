"""Persist whether each Copilot conversation is general or dataset-focused."""

from alembic import op
import sqlalchemy as sa

revision = "0004_copilot_context_mode"
down_revision = "0003_copilot_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("copilot_conversations")}
    if "context_mode" not in columns:
        op.add_column(
            "copilot_conversations",
            sa.Column("context_mode", sa.String(length=16), nullable=False, server_default="dataset"),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("copilot_conversations")}
    if "context_mode" in columns:
        op.drop_column("copilot_conversations", "context_mode")
