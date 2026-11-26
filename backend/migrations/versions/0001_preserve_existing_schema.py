"""Create only missing baseline tables without replacing existing user data."""

from alembic import op
import sqlalchemy as sa

revision = "0001_preserve_existing_schema"
down_revision = None
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _create_index_if_missing(bind, table_name: str, index_name: str, columns: list[str]) -> None:
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    existing = _table_names(bind)
    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=120), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("email"),
        )
    if "datasets" not in existing:
        op.create_table(
            "datasets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("stored_name", sa.String(length=255), nullable=False),
            sa.Column("row_count", sa.Integer(), nullable=False),
            sa.Column("column_count", sa.Integer(), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("stored_name"),
        )
    if "revoked_tokens" not in existing:
        op.create_table(
            "revoked_tokens",
            sa.Column("token_id", sa.String(length=64), primary_key=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )

    bind = op.get_bind()
    _create_index_if_missing(bind, "users", "ix_users_email", ["email"])
    _create_index_if_missing(bind, "datasets", "ix_datasets_owner_id", ["owner_id"])
    _create_index_if_missing(bind, "revoked_tokens", "ix_revoked_tokens_expires_at", ["expires_at"])


def downgrade() -> None:
    pass
