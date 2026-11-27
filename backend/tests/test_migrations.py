import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import settings
from app.core.database import Base
from app.core.security import hash_password


def test_migrations_preserve_existing_users_and_additive_schema(tmp_path, monkeypatch):
    database_path = tmp_path / "existing.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            full_name VARCHAR(120) NOT NULL,
            hashed_password VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL
        );
        CREATE INDEX ix_users_email ON users (email);
        CREATE TABLE datasets (
            id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            name VARCHAR(255) NOT NULL,
            stored_name VARCHAR(255) NOT NULL UNIQUE,
            row_count INTEGER NOT NULL,
            column_count INTEGER NOT NULL,
            file_size INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
        );
        CREATE INDEX ix_datasets_owner_id ON datasets (owner_id);
        """
    )
    connection.execute(
        "INSERT INTO users (email, full_name, hashed_password, created_at) VALUES (?, ?, ?, ?)",
        ("existing@example.com", "Existing User", hash_password("ExistingPass123!"), "2026-01-01"),
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database_path.as_posix()}")
    backend_dir = Path(__file__).resolve().parents[1]
    migration_config = Config(str(backend_dir / "alembic.ini"))
    migration_config.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(migration_config, "head")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as migrated:
        user = migrated.execute(
            text("SELECT email, full_name FROM users WHERE email = :email"),
            {"email": "existing@example.com"},
        ).one()
        assert user.email == "existing@example.com"
        assert user.full_name == "Existing User"
        assert "content_hash" in {
            column["name"] for column in inspect(migrated).get_columns("datasets")
        }
        assert "revoked_tokens" in inspect(migrated).get_table_names()
        assert {
            "copilot_conversations",
            "copilot_messages",
        }.issubset(set(inspect(migrated).get_table_names()))
        assert migrated.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0004_copilot_context_mode"
        assert "context_mode" in {
            column["name"] for column in inspect(migrated).get_columns("copilot_conversations")
        }
    engine.dispose()


def test_migration_is_safe_when_create_all_already_added_copilot_tables(tmp_path, monkeypatch):
    database_path = tmp_path / "create-all-first.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database_path.as_posix()}")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (email, full_name, hashed_password, created_at) "
                "VALUES ('kept@example.com', 'Kept User', 'safe-hash', CURRENT_TIMESTAMP)"
            )
        )
        owner_id = connection.execute(
            text("SELECT id FROM users WHERE email = 'kept@example.com'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO copilot_conversations "
                "(owner_id, dataset_id, title, created_at, updated_at) "
                "VALUES (:owner_id, NULL, 'Keep this conversation', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"owner_id": owner_id},
        )
        conversation_id = connection.execute(
            text("SELECT id FROM copilot_conversations WHERE title = 'Keep this conversation'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO copilot_messages (conversation_id, role, content, created_at) "
                "VALUES (:conversation_id, 'user', 'Preserve this message', CURRENT_TIMESTAMP)"
            ),
            {"conversation_id": conversation_id},
        )
    engine.dispose()

    backend_dir = Path(__file__).resolve().parents[1]
    migration_config = Config(str(backend_dir / "alembic.ini"))
    migration_config.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(migration_config, "head")

    with sqlite3.connect(database_path) as migrated:
        assert migrated.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert migrated.execute("SELECT COUNT(*) FROM copilot_conversations").fetchone()[0] == 1
        assert migrated.execute("SELECT COUNT(*) FROM copilot_messages").fetchone()[0] == 1
        assert migrated.execute("SELECT context_mode FROM copilot_conversations").fetchone()[0] == "dataset"
