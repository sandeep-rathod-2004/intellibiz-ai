"""Add user-scoped duplicate upload detection."""

from alembic import op
import sqlalchemy as sa

revision = "0002_dataset_content_hash"
down_revision = "0001_preserve_existing_schema"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_dataset_owner_content_hash"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("datasets")}
    if "content_hash" not in columns:
        op.add_column("datasets", sa.Column("content_hash", sa.String(length=64), nullable=True))

    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("datasets")
    indexes = inspector.get_indexes("datasets")
    has_constraint = any(
        constraint.get("column_names") == ["owner_id", "content_hash"]
        for constraint in unique_constraints
    )
    has_index = any(
        index.get("unique")
        and index.get("column_names") == ["owner_id", "content_hash"]
        for index in indexes
    )
    if not has_constraint and not has_index:
        op.create_index(
            INDEX_NAME,
            "datasets",
            ["owner_id", "content_hash"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("datasets")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="datasets")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("datasets")}
    if "content_hash" in columns:
        with op.batch_alter_table("datasets") as batch_op:
            batch_op.drop_column("content_hash")
