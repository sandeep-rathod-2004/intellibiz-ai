"""Add persistent Copilot conversations and messages."""

from alembic import op
import sqlalchemy as sa

revision = "0003_copilot_conversations"
down_revision = "0002_dataset_content_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "copilot_conversations" not in tables:
        op.create_table(
            "copilot_conversations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("dataset_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="SET NULL"),
        )
    conversation_indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("copilot_conversations")
    }
    if "ix_copilot_conversations_owner_updated" not in conversation_indexes:
        op.create_index(
            "ix_copilot_conversations_owner_updated",
            "copilot_conversations",
            ["owner_id", "updated_at"],
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "copilot_messages" not in tables:
        op.create_table(
            "copilot_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("conversation_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["conversation_id"],
                ["copilot_conversations.id"],
                ondelete="CASCADE",
            ),
        )
    message_indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("copilot_messages")
    }
    if "ix_copilot_messages_conversation_id_id" not in message_indexes:
        op.create_index(
            "ix_copilot_messages_conversation_id_id",
            "copilot_messages",
            ["conversation_id", "id"],
        )


def downgrade() -> None:
    pass
