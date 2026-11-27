import json
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import jwt
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.config import settings
from app.core.security import (
    ALGORITHM,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.main import app
from app.models.entities import (
    CopilotConversation,
    CopilotMessage,
    Dataset,
    RevokedToken,
    User,
)
from app.api import routes as api_routes
from app.api.rate_limit import _lock, _requests
from app.services.copilot import CopilotProviderError


@pytest.fixture
def auth_client():
    with _lock:
        _requests.clear()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(autoflush=False, autocommit=False, bind=engine)

    def override_get_db():
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, test_session
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def register(client: TestClient, email: str = "person@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Test Person",
            "password": "SecurePass123!",
            "password_confirmation": "SecurePass123!",
        },
    )


def login(client: TestClient, email: str = "person@example.com"):
    return client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "SecurePass123!"},
    )


def test_registration_login_and_jwt_protected_route(auth_client):
    client, test_session = auth_client
    response = register(client)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "person@example.com"
    assert "hashed_password" not in data["user"]
    assert "hashed_password" not in data
    assert "password" not in data
    assert "access_token" not in data
    assert "message" in data

    with test_session() as db:
        user = db.query(User).filter(User.email == "person@example.com").one()
        assert user.hashed_password != "SecurePass123!"
        assert verify_password("SecurePass123!", user.hashed_password)

    login_response = login(client, "PERSON@example.com")
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    profile = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile.status_code == 200
    assert profile.json() == data["user"]
    headers = {"Authorization": f"Bearer {token}"}
    logout_response = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_response.status_code == 200
    assert logout_response.json() == {"logged_out": True}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    ).status_code == 401


def test_jwt_validation_rejects_expired_tokens_and_invalid_signatures(monkeypatch):
    monkeypatch.setattr(
        settings,
        "secret_key",
        "test-signing-key-with-at-least-thirty-two-bytes",
    )
    expired_token = jwt.encode(
        {"sub": "user-1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    invalid_signature = jwt.encode(
        {"sub": "user-1", "exp": datetime.now(timezone.utc) + timedelta(minutes=1)},
        "incorrect-signing-key-with-at-least-thirty-two-bytes",
        algorithm=ALGORITHM,
    )

    assert decode_token(create_access_token("user-1"))["sub"] == "user-1"
    assert decode_token(expired_token) is None
    assert decode_token(invalid_signature) is None


def test_login_rejects_incorrect_password(auth_client):
    client, _ = auth_client
    assert register(client).status_code == 200

    response = client.post(
        "/api/v1/auth/login",
        data={"username": "person@example.com", "password": "IncorrectPass123!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"
    unknown_user = client.post(
        "/api/v1/auth/login",
        data={"username": "not-registered@example.com", "password": "SecurePass123!"},
    )
    assert unknown_user.status_code == 401


def test_login_keeps_existing_short_password_accounts_compatible(auth_client):
    client, test_session = auth_client
    with test_session() as db:
        db.add(
            User(
                email="legacy@example.com",
                full_name="Legacy User",
                hashed_password=hash_password("legacy8!"),
            )
        )
        db.commit()

    response = client.post(
        "/api/v1/auth/login",
        data={"username": "legacy@example.com", "password": "legacy8!"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "legacy@example.com"


def test_registration_rejects_duplicate_email_case_insensitively(auth_client):
    client, _ = auth_client
    assert register(client).status_code == 200

    response = register(client, "PERSON@EXAMPLE.COM")
    assert response.status_code == 409
    assert response.json()["detail"] == "An account with this email already exists"


def test_registration_reports_invalid_schema_and_password(auth_client):
    client, _ = auth_client
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "not-an-email",
            "name": "Test Person",
            "password": "short",
        },
    )

    assert response.status_code == 422
    locations = [issue["loc"] for issue in response.json()["detail"]]
    assert ["body", "email"] in locations
    assert ["body", "full_name"] in locations
    assert ["body", "name"] in locations
    assert ["body", "password"] in locations


def test_registration_rejects_password_beyond_bcrypt_byte_limit(auth_client):
    client, _ = auth_client
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "long-password@example.com",
            "full_name": "Test Person",
            "password": "a" * 73,
            "password_confirmation": "a" * 73,
        },
    )

    assert response.status_code == 422
    issue = next(item for item in response.json()["detail"] if item["loc"][-1] == "password")
    assert "72 UTF-8 bytes" in issue["msg"]


def test_registration_rejects_mismatched_password_confirmation(auth_client):
    client, _ = auth_client
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "mismatch@example.com",
            "full_name": "Test Person",
            "password": "SecurePass123!",
            "password_confirmation": "DifferentPass123!",
        },
    )

    assert response.status_code == 422
    assert any("Passwords do not match" in item["msg"] for item in response.json()["detail"])


def test_dataset_access_is_scoped_to_authenticated_user(auth_client):
    client, test_session = auth_client
    first_registration = register(client, "first@example.com")
    assert register(client, "second@example.com").status_code == 200
    first_token = login(client, "first@example.com").json()["access_token"]
    second_token = login(client, "second@example.com").json()["access_token"]
    first_user_id = first_registration.json()["user"]["id"]

    with test_session() as db:
        db.add(
            Dataset(
                owner_id=first_user_id,
                name="private.csv",
                stored_name="opaque-private-file.csv",
                row_count=1,
                column_count=1,
                file_size=8,
            )
        )
        db.commit()
        dataset_id = db.query(Dataset).one().id

    first_datasets = client.get(
        "/api/v1/datasets",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    second_datasets = client.get(
        "/api/v1/datasets",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    cross_user_delete = client.delete(
        f"/api/v1/datasets/{dataset_id}",
        headers={"Authorization": f"Bearer {second_token}"},
    )

    assert first_datasets.status_code == 200
    assert [item["id"] for item in first_datasets.json()] == [dataset_id]
    assert second_datasets.status_code == 200
    assert second_datasets.json() == []
    assert cross_user_delete.status_code == 404


def test_dataset_preview_filters_sorts_and_paginates(auth_client, tmp_path, monkeypatch):
    client, test_session = auth_client
    registration = register(client, "preview@example.com")
    token = login(client, "preview@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    sample_path = Path(tmp_path) / "preview.csv"
    sample_path.write_text(
        "region,revenue\nNorth,10\nSouth,40\nNorth,30\nWest,20\n",
        encoding="utf-8",
    )
    with test_session() as db:
        dataset = Dataset(
            owner_id=user_id,
            name="preview.csv",
            stored_name=sample_path.name,
            row_count=4,
            column_count=2,
            file_size=sample_path.stat().st_size,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

    headers = {"Authorization": f"Bearer {token}"}
    page = client.get(
        f"/api/v1/datasets/{dataset_id}/preview",
        params={"limit": 2, "offset": 1, "sort_by": "revenue", "descending": True},
        headers=headers,
    )
    filtered = client.get(
        f"/api/v1/datasets/{dataset_id}/preview",
        params={"search": "north"},
        headers=headers,
    )
    multi_filtered = client.get(
        f"/api/v1/datasets/{dataset_id}/preview",
        params={"filters": json.dumps({"region": "North", "revenue": "30"})},
        headers=headers,
    )

    assert page.status_code == 200
    assert [row["revenue"] for row in page.json()["rows"]] == [30, 20]
    assert page.json()["total"] == 4
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 2
    assert all(row["region"] == "North" for row in filtered.json()["rows"])
    assert multi_filtered.status_code == 200
    assert multi_filtered.json()["total"] == 1
    assert multi_filtered.json()["rows"][0]["revenue"] == 30


def test_dataset_upload_rejects_duplicate_content_for_same_user(auth_client, tmp_path, monkeypatch):
    client, test_session = auth_client
    registration = register(client, "upload@example.com")
    token = login(client, "upload@example.com").json()["access_token"]
    monkeypatch.setattr(settings, "data_storage_backend", "local")
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    headers = {"Authorization": f"Bearer {token}"}
    content = b"region,revenue\nNorth,100\n"

    first = client.post(
        "/api/v1/datasets/upload",
        headers=headers,
        files={"file": ("sales.csv", content, "text/csv")},
    )
    duplicate = client.post(
        "/api/v1/datasets/upload",
        headers=headers,
        files={"file": ("renamed-sales.csv", content, "text/csv")},
    )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    with test_session() as db:
        rows = db.query(Dataset).filter(Dataset.owner_id == registration.json()["user"]["id"]).all()
        assert len(rows) == 1
    assert len(list(tmp_path.iterdir())) == 1


def test_independent_csv_and_excel_uploads_keep_dynamic_schemas_and_rows(
    auth_client,
    tmp_path,
    monkeypatch,
):
    client, test_session = auth_client
    registration = register(client, "dynamic-schema@example.com")
    user_id = registration.json()["user"]["id"]
    token = login(client, "dynamic-schema@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(settings, "data_storage_backend", "local")
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)

    csv_content = b"Region / Area,Revenue ($),Revenue ($),Store Open\nNorth,125.5,500,true\nSouth,,800,false\n"
    excel_buffer = BytesIO()
    pd.DataFrame({
        "Ticket #": ["T-100", "T-101"],
        "Minutes elapsed": [12, 28],
        "Resolution?": ["yes", "no"],
    }).to_excel(excel_buffer, index=False)
    excel_content = excel_buffer.getvalue()

    csv_upload = client.post(
        "/api/v1/datasets/upload",
        headers=headers,
        files={"file": ("quarter.csv", csv_content, "text/csv")},
    )
    xlsx_upload = client.post(
        "/api/v1/datasets/upload",
        headers=headers,
        files={
            "file": (
                "support.xlsx",
                excel_content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert csv_upload.status_code == 200
    assert xlsx_upload.status_code == 200
    csv_id = csv_upload.json()["id"]
    xlsx_id = xlsx_upload.json()["id"]
    assert csv_id != xlsx_id
    csv_preview = client.get(f"/api/v1/datasets/{csv_id}/preview", headers=headers)
    xlsx_preview = client.get(f"/api/v1/datasets/{xlsx_id}/preview", headers=headers)
    assert csv_preview.status_code == xlsx_preview.status_code == 200
    assert csv_preview.json()["columns"] == [
        "Region / Area", "Revenue ($)", "Revenue ($).1", "Store Open",
    ]
    assert csv_preview.json()["rows"] == [
        {"Region / Area": "North", "Revenue ($)": 125.5, "Revenue ($).1": 500, "Store Open": True},
        {"Region / Area": "South", "Revenue ($)": None, "Revenue ($).1": 800, "Store Open": False},
    ]
    assert xlsx_preview.json()["columns"] == ["Ticket #", "Minutes elapsed", "Resolution?"]
    assert xlsx_preview.json()["rows"][0] == {
        "Ticket #": "T-100", "Minutes elapsed": 12, "Resolution?": "yes",
    }
    assert len(list(tmp_path.iterdir())) == 2
    with test_session() as db:
        stored = db.query(Dataset).filter(Dataset.owner_id == user_id).all()
        assert len(stored) == 2
        assert len({dataset.stored_name for dataset in stored}) == 2


def test_dataset_upload_flushes_database_row_before_storage_write(
    auth_client,
    tmp_path,
    monkeypatch,
):
    client, test_session = auth_client
    register(client, "flush-upload@example.com")
    token = login(client, "flush-upload@example.com").json()["access_token"]
    monkeypatch.setattr(settings, "data_storage_backend", "local")
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    inserts = []

    def observe_sql(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("insert into datasets"):
            inserts.append(statement)

    def save_after_flush(stored_name, content, local_path):
        assert inserts, "Dataset INSERT must be flushed before storage write"
        Path(local_path).write_bytes(content)

    monkeypatch.setattr(api_routes, "save_stored_dataset", save_after_flush)
    engine = test_session.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe_sql)
    try:
        response = client.post(
            "/api/v1/datasets/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("sales.csv", b"region,revenue\nNorth,100\n", "text/csv")},
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)

    assert response.status_code == 200
    assert len(inserts) == 1


def test_dataset_key_collision_retries_before_storage_write(
    auth_client,
    tmp_path,
    monkeypatch,
):
    client, test_session = auth_client
    registration = register(client, "key-collision@example.com")
    token = login(client, "key-collision@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(settings, "data_storage_backend", "local")
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    with test_session() as db:
        db.add(
            Dataset(
                owner_id=user_id,
                name="existing.csv",
                stored_name="collision.csv",
                content_hash=None,
                row_count=1,
                column_count=1,
                file_size=0,
            )
        )
        db.commit()

    keys = iter(("collision", "fresh-key"))
    monkeypatch.setattr(
        api_routes,
        "uuid4",
        lambda: SimpleNamespace(hex=next(keys)),
    )
    uploaded_keys = []

    def record_upload(stored_name, content, local_path):
        uploaded_keys.append(stored_name)
        Path(local_path).write_bytes(content)

    monkeypatch.setattr(api_routes, "save_stored_dataset", record_upload)
    response = client.post(
        "/api/v1/datasets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sales.csv", b"region,revenue\nNorth,100\n", "text/csv")},
    )

    assert response.status_code == 200
    assert uploaded_keys == ["fresh-key.csv"]
    with test_session() as db:
        assert db.query(Dataset).filter_by(stored_name="collision.csv").count() == 1
        assert db.query(Dataset).filter_by(stored_name="fresh-key.csv").count() == 1


def test_dataset_upload_failure_rolls_back_without_cloud_cleanup(
    auth_client,
    tmp_path,
    monkeypatch,
):
    client, test_session = auth_client
    registration = register(client, "failed-upload@example.com")
    token = login(client, "failed-upload@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(settings, "data_storage_backend", "local")
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    cleanup_calls = []

    def fail_upload(*_args):
        raise api_routes.DatasetStorageError("simulated upload failure")

    monkeypatch.setattr(api_routes, "save_stored_dataset", fail_upload)
    monkeypatch.setattr(
        api_routes,
        "remove_stored_dataset",
        lambda *args: cleanup_calls.append(args),
    )
    response = client.post(
        "/api/v1/datasets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("sales.csv", b"region,revenue\nNorth,100\n", "text/csv")},
    )

    assert response.status_code == 503
    assert cleanup_calls == []
    with test_session() as db:
        assert db.query(Dataset).filter(Dataset.owner_id == user_id).count() == 0


def test_dataset_upload_sanitizes_parser_errors(auth_client, tmp_path, monkeypatch):
    client, _ = auth_client
    register(client, "invalid-upload@example.com")
    token = login(client, "invalid-upload@example.com").json()["access_token"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)

    response = client.post(
        "/api/v1/datasets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("invalid.csv", b"private-marker,value\n\xff,1\n", "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The CSV file could not be parsed."
    assert "private-marker" not in response.text


def test_dataset_upload_enforces_configured_cell_limit(auth_client, tmp_path, monkeypatch):
    client, test_session = auth_client
    registration = register(client, "large-upload@example.com")
    token = login(client, "large-upload@example.com").json()["access_token"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "max_dataset_cells", 3)

    response = client.post(
        "/api/v1/datasets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("large.csv", b"region,revenue\nNorth,10\nSouth,20\n", "text/csv")},
    )

    assert response.status_code == 413
    with test_session() as db:
        assert db.query(Dataset).filter(
            Dataset.owner_id == registration.json()["user"]["id"]
        ).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_dataset_upload_detects_legacy_duplicate_without_saved_hash(auth_client, tmp_path, monkeypatch):
    client, test_session = auth_client
    registration = register(client, "legacy-upload@example.com")
    token = login(client, "legacy-upload@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    content = b"region,revenue\nNorth,100\n"
    (tmp_path / "legacy.csv").write_bytes(content)
    with test_session() as db:
        db.add(
            Dataset(
                owner_id=user_id,
                name="legacy.csv",
                stored_name="legacy.csv",
                content_hash=None,
                row_count=1,
                column_count=2,
                file_size=len(content),
            )
        )
        db.commit()

    response = client.post(
        "/api/v1/datasets/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("re-upload.csv", content, "text/csv")},
    )

    assert response.status_code == 409
    assert "legacy.csv" in response.json()["detail"]


def test_dataset_delete_reports_storage_cleanup_failure_after_record_commit(
    auth_client,
    monkeypatch,
):
    client, test_session = auth_client
    registration = register(client, "storage-delete@example.com")
    token = login(client, "storage-delete@example.com").json()["access_token"]
    dataset = Dataset(
        owner_id=registration.json()["user"]["id"],
        name="sales.csv",
        stored_name="opaque-name.csv",
        row_count=1,
        column_count=1,
        file_size=8,
    )
    with test_session() as db:
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

    def fail_delete(*_args):
        with test_session() as db:
            assert db.query(Dataset).filter(Dataset.id == dataset_id).one_or_none() is None
        raise api_routes.DatasetStorageError("provider detail must not escape")

    monkeypatch.setattr(api_routes, "remove_stored_dataset", fail_delete)
    response = client.delete(
        f"/api/v1/datasets/{dataset_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Dataset record was deleted, but storage cleanup failed. Please contact support."
    )
    with test_session() as db:
        assert db.query(Dataset).filter(Dataset.id == dataset_id).one_or_none() is None


def test_dataset_delete_commit_failure_does_not_remove_storage(
    auth_client,
    monkeypatch,
):
    client, test_session = auth_client
    registration = register(client, "delete-commit-failure@example.com")
    token = login(client, "delete-commit-failure@example.com").json()["access_token"]
    dataset = Dataset(
        owner_id=registration.json()["user"]["id"],
        name="sales.csv",
        stored_name="opaque-name.csv",
        row_count=1,
        column_count=1,
        file_size=8,
    )
    with test_session() as db:
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

    original_commit = api_routes.Session.commit
    cleanup_calls = []

    def fail_delete_commit(session):
        if any(
            isinstance(item, Dataset) and item.id == dataset_id
            for item in session.deleted
        ):
            raise SQLAlchemyError("simulated commit failure")
        return original_commit(session)

    monkeypatch.setattr(api_routes.Session, "commit", fail_delete_commit)
    monkeypatch.setattr(
        api_routes,
        "remove_stored_dataset",
        lambda *args: cleanup_calls.append(args),
    )
    response = client.delete(
        f"/api/v1/datasets/{dataset_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Dataset could not be deleted. Please retry later."
    assert cleanup_calls == []
    with test_session() as db:
        assert db.query(Dataset).filter(Dataset.id == dataset_id).one_or_none() is not None


def test_filtered_csv_export_neutralizes_spreadsheet_formulas(auth_client, tmp_path, monkeypatch):
    client, test_session = auth_client
    registration = register(client, "export@example.com")
    token = login(client, "export@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    source = tmp_path / "unsafe.csv"
    source.write_text("label,value\n=1+1,2\nNormal,3\n", encoding="utf-8")
    with test_session() as db:
        dataset = Dataset(
            owner_id=user_id,
            name="unsafe.csv",
            stored_name=source.name,
            content_hash="a" * 64,
            row_count=2,
            column_count=2,
            file_size=source.stat().st_size,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

    response = client.get(
        f"/api/v1/datasets/{dataset_id}/export",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert b"'=1+1" in response.content


def test_anomaly_sensitivity_and_report_use_owned_dataset(auth_client, tmp_path, monkeypatch):
    client, test_session = auth_client
    registration = register(client, "anomaly@example.com")
    token = login(client, "anomaly@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    source = tmp_path / "measurements.csv"
    source.write_text(
        "region,revenue\n" + "".join(f"region-{index},{index * 10}\n" for index in range(12)),
        encoding="utf-8",
    )
    with test_session() as db:
        dataset = Dataset(
            owner_id=user_id,
            name="measurements.csv",
            stored_name=source.name,
            row_count=12,
            column_count=2,
            file_size=source.stat().st_size,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

    headers = {"Authorization": f"Bearer {token}"}
    result = client.get(
        f"/api/v1/datasets/{dataset_id}/anomalies",
        params={"contamination": 0.1},
        headers=headers,
    )
    report = client.get(
        f"/api/v1/datasets/{dataset_id}/anomalies/export",
        params={"contamination": 0.1},
        headers=headers,
    )

    assert result.status_code == 200
    assert result.json()["contamination"] == 0.1
    assert report.status_code == 200
    assert b"anomaly_score,explanation" in report.content


def test_analysis_and_pdf_routes_handle_overflowing_unrelated_numeric_summary(
    auth_client, tmp_path, monkeypatch
):
    client, test_session = auth_client
    registration = register(client, "overflow-analysis@example.com")
    token = login(client, "overflow-analysis@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    source = tmp_path / "overflow.csv"
    source.write_text("score\n1.7e308\n1.7e308\n", encoding="utf-8")
    with test_session() as db:
        dataset = Dataset(
            owner_id=user_id,
            name="overflow.csv",
            stored_name=source.name,
            row_count=2,
            column_count=1,
            file_size=source.stat().st_size,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

    headers = {"Authorization": f"Bearer {token}"}
    analysis = client.get(f"/api/v1/datasets/{dataset_id}/analysis", headers=headers)
    report = client.get(f"/api/v1/datasets/{dataset_id}/report", headers=headers)

    assert analysis.status_code == 200
    payload = json.loads(
        analysis.content,
        parse_constant=lambda token: pytest.fail(f"Non-finite JSON constant leaked: {token}"),
    )
    score = next(item for item in payload["profile"]["numeric_summary"] if item["name"] == "score")
    assert score["sum"] is None
    assert score["mean"] is None
    assert any(item.get("title") == "score: summary unavailable" for item in payload["insights"])
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("application/pdf")
    assert report.content.startswith(b"%PDF-")


def test_public_sample_download_is_available():
    response = TestClient(app).get("/api/v1/samples/retail-sales")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert response.content.startswith(b"date,")


def test_copilot_reports_missing_provider_configuration(auth_client, tmp_path, monkeypatch):
    client, test_session = auth_client
    registration = register(client, "copilot@example.com")
    token = login(client, "copilot@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    sample_path = Path(tmp_path) / "copilot.csv"
    sample_path.write_text("date,revenue\n2024-01-01,10\n", encoding="utf-8")
    with test_session() as db:
        dataset = Dataset(
            owner_id=user_id,
            name="copilot.csv",
            stored_name=sample_path.name,
            row_count=1,
            column_count=2,
            file_size=sample_path.stat().st_size,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id

    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    readiness = client.get(
        "/api/v1/copilot/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/copilot",
        json={"question": "Explain the causal reason for this change."},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]
    assert len(response.headers["x-request-id"]) == 32
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "configuration_required"


def test_create_all_preserves_existing_database_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    Base.metadata.create_all(bind=engine)
    existing_session = sessionmaker(bind=engine)
    with existing_session() as db:
        db.add(
            User(
                email="existing@example.com",
                full_name="Existing User",
                hashed_password=hash_password("SecurePass123!"),
            )
        )
        db.commit()
        user_id = db.query(User).filter(User.email == "existing@example.com").one().id

    Base.metadata.create_all(bind=engine)
    with existing_session() as db:
        user = db.query(User).filter(User.id == user_id).one()
        assert user.email == "existing@example.com"
        assert verify_password("SecurePass123!", user.hashed_password)
    engine.dispose()


def test_copilot_persists_failed_user_message_and_retries_without_duplication(
    auth_client,
    tmp_path,
    monkeypatch,
):
    client, test_session = auth_client
    registration = register(client, "history@example.com")
    token = login(client, "history@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    dataset_path = tmp_path / "history.csv"
    dataset_path.write_text("month,revenue\nJan,10\nFeb,15\n", encoding="utf-8")
    with test_session() as db:
        dataset = Dataset(
            owner_id=user_id,
            name="history.csv",
            stored_name=dataset_path.name,
            row_count=2,
            column_count=2,
            file_size=dataset_path.stat().st_size,
        )
        db.add(dataset)
        db.commit()
        dataset_id = dataset.id
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/v1/copilot/conversations",
        json={"dataset_id": dataset_id},
        headers=headers,
    )
    conversation_id = created.json()["id"]
    appended = client.post(
        f"/api/v1/copilot/conversations/{conversation_id}/messages",
        json={"content": "Summarize the revenue trend"},
        headers=headers,
    )
    message_id = appended.json()["id"]

    async def failed_answer(*args, **kwargs):
        raise CopilotProviderError(503, "Provider is temporarily unavailable.")

    monkeypatch.setattr(api_routes, "ask_copilot", failed_answer)
    failed = client.post(
        f"/api/v1/copilot/conversations/{conversation_id}/messages/{message_id}/answer",
        headers=headers,
    )
    history_after_failure = client.get(
        f"/api/v1/copilot/conversations/{conversation_id}/messages",
        headers=headers,
    )

    assert created.status_code == 201
    assert appended.status_code == 201
    assert failed.status_code == 503
    assert failed.json()["detail"]["message_id"] == message_id
    assert [item["role"] for item in history_after_failure.json()["items"]] == ["user"]

    observed_history = {}

    async def successful_answer(question, facts, request_id="", conversation_history=None):
        observed_history["question"] = question
        observed_history["history"] = conversation_history
        return {"answer": "Revenue increased by 5.", "provider": "openai"}

    monkeypatch.setattr(api_routes, "ask_copilot", successful_answer)
    retried = client.post(
        f"/api/v1/copilot/conversations/{conversation_id}/messages/{message_id}/answer",
        headers=headers,
    )
    after_retry = client.get(
        f"/api/v1/copilot/conversations/{conversation_id}/messages",
        headers=headers,
    )

    assert retried.status_code == 200
    assert retried.json()["role"] == "assistant"
    assert observed_history == {"question": "Summarize the revenue trend", "history": []}
    assert [item["role"] for item in after_retry.json()["items"]] == ["user", "assistant"]


def test_general_copilot_conversations_are_independent_persisted_and_contextual(
    auth_client,
    monkeypatch,
):
    client, _ = auth_client
    register(client, "general-chat@example.com")
    token = login(client, "general-chat@example.com").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post(
        "/api/v1/copilot/conversations",
        json={"context_mode": "general", "dataset_id": None},
        headers=headers,
    )
    second = client.post(
        "/api/v1/copilot/conversations",
        json={"context_mode": "general"},
        headers=headers,
    )
    calls = []

    async def general_answer(question, facts, request_id="", conversation_history=None):
        calls.append((question, facts, conversation_history))
        return {"answer": "A persisted general answer.", "provider": "test_provider"}

    monkeypatch.setattr(api_routes, "ask_copilot", general_answer)
    first_id = first.json()["id"]
    first_user = client.post(
        f"/api/v1/copilot/conversations/{first_id}/messages",
        json={"content": "Explain recursion."},
        headers=headers,
    ).json()
    first_answer = client.post(
        f"/api/v1/copilot/conversations/{first_id}/messages/{first_user['id']}/answer",
        headers=headers,
    )
    followup = client.post(
        f"/api/v1/copilot/conversations/{first_id}/messages",
        json={"content": "Can you show a short example?"},
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/copilot/conversations/{first_id}/messages/{followup['id']}/answer",
        headers=headers,
    )

    assert first.status_code == second.status_code == 201
    assert first_id != second.json()["id"]
    assert first.json()["context_mode"] == "general"
    assert first.json()["dataset_available"] is False
    assert first_answer.status_code == 200
    assert calls[0][1] == {"context_mode": "general"}
    assert calls[1][2] == [
        {"role": "user", "content": "Explain recursion."},
        {"role": "assistant", "content": "A persisted general answer."},
    ]
    restored = client.get(
        f"/api/v1/copilot/conversations/{first_id}/messages",
        headers=headers,
    )
    assert [message["role"] for message in restored.json()["items"]] == [
        "user", "assistant", "user", "assistant",
    ]
    assert client.post(
        "/api/v1/copilot/conversations",
        json={"context_mode": "dataset"},
        headers=headers,
    ).status_code == 422


def test_missing_context_mode_column_returns_cors_readable_copilot_errors(auth_client):
    client, test_session = auth_client
    register(client, "missing-context-mode@example.com")
    token = login(client, "missing-context-mode@example.com").json()["access_token"]
    with test_session.kw["bind"].begin() as connection:
        connection.execute(text("ALTER TABLE copilot_conversations DROP COLUMN context_mode"))

    diagnostic_client = TestClient(app, raise_server_exceptions=False)
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "http://localhost:5173",
    }
    history = diagnostic_client.get("/api/v1/copilot/conversations", headers=headers)
    created = diagnostic_client.post(
        "/api/v1/copilot/conversations",
        json={"context_mode": "general", "dataset_id": None},
        headers=headers,
    )

    for response in (history, created):
        assert response.status_code == 500
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert response.headers.get("x-request-id")
        assert response.json()["detail"] == "An unexpected server error occurred"


def test_copilot_history_is_user_scoped_and_deletion_preserves_other_domains(auth_client):
    client, test_session = auth_client
    user_a = register(client, "history-a@example.com").json()["user"]["id"]
    token_a = login(client, "history-a@example.com").json()["access_token"]
    user_b = register(client, "history-b@example.com").json()["user"]["id"]
    token_b = login(client, "history-b@example.com").json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    first_a = client.post("/api/v1/copilot/conversations", json={}, headers=headers_a).json()["id"]
    second_a = client.post("/api/v1/copilot/conversations", json={}, headers=headers_a).json()["id"]
    only_b = client.post("/api/v1/copilot/conversations", json={}, headers=headers_b).json()["id"]

    assert client.get(
        f"/api/v1/copilot/conversations/{only_b}",
        headers=headers_a,
    ).status_code == 404
    assert client.patch(
        f"/api/v1/copilot/conversations/{only_b}",
        json={"title": "not allowed"},
        headers=headers_a,
    ).status_code == 404
    assert client.delete(
        f"/api/v1/copilot/conversations/{only_b}",
        headers=headers_a,
    ).status_code == 404

    deleted = client.delete(
        f"/api/v1/copilot/conversations/{first_a}",
        headers=headers_a,
    )
    listed_a = client.get("/api/v1/copilot/conversations", headers=headers_a).json()
    listed_b = client.get("/api/v1/copilot/conversations", headers=headers_b).json()

    assert deleted.status_code == 200
    assert [item["id"] for item in listed_a["items"]] == [second_a]
    assert [item["id"] for item in listed_b["items"]] == [only_b]

    with test_session() as db:
        db.add_all(
            [
                Dataset(
                    owner_id=user_a,
                    name="a.csv",
                    stored_name="a.csv",
                    row_count=1,
                    column_count=1,
                    file_size=10,
                ),
                RevokedToken(
                    token_id="history-security-record",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                ),
            ]
        )
        db.commit()
    assert client.request(
        "DELETE",
        "/api/v1/copilot/conversations",
        json={},
        headers=headers_a,
    ).status_code == 422
    cleared = client.request(
        "DELETE",
        "/api/v1/copilot/conversations",
        json={"confirmation": "CLEAR"},
        headers=headers_a,
    )

    assert cleared.status_code == 200
    assert cleared.json()["deleted"] == 1
    with test_session() as db:
        assert db.query(CopilotConversation).filter_by(owner_id=user_a).count() == 0
        assert db.query(CopilotConversation).filter_by(owner_id=user_b).count() == 1
        assert db.query(CopilotMessage).count() == 0
        assert db.query(Dataset).filter_by(owner_id=user_a).count() == 1
        assert db.query(User).count() == 2
        assert db.query(RevokedToken).filter_by(token_id="history-security-record").count() == 1


def test_dataset_deletion_preserves_copilot_history_and_security_records(
    auth_client,
    tmp_path,
    monkeypatch,
):
    client, test_session = auth_client
    registration = register(client, "dataset-history@example.com")
    token = login(client, "dataset-history@example.com").json()["access_token"]
    user_id = registration.json()["user"]["id"]
    monkeypatch.setattr(api_routes, "DATA_DIR", tmp_path)
    dataset_file = tmp_path / "linked.csv"
    dataset_file.write_text("value\n12\n", encoding="utf-8")
    with test_session() as db:
        dataset = Dataset(
            owner_id=user_id,
            name="linked.csv",
            stored_name=dataset_file.name,
            row_count=1,
            column_count=1,
            file_size=dataset_file.stat().st_size,
        )
        db.add(dataset)
        db.flush()
        dataset_id = dataset.id
        conversation = CopilotConversation(owner_id=user_id, dataset_id=dataset_id)
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id
        db.add(CopilotMessage(
            conversation_id=conversation_id,
            role="user",
            content="Keep this history",
        ))
        db.add(RevokedToken(
            token_id="dataset-security-record",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        db.commit()

    response = client.delete(
        f"/api/v1/datasets/{dataset_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    with test_session() as db:
        kept_conversation = db.query(CopilotConversation).filter_by(id=conversation_id).one()
        assert kept_conversation.dataset_id is None
        assert db.query(CopilotMessage).filter_by(conversation_id=conversation_id).count() == 1
        assert db.query(Dataset).filter_by(id=dataset_id).count() == 0
        assert db.query(User).filter_by(id=user_id).count() == 1
        assert db.query(RevokedToken).filter_by(token_id="dataset-security-record").count() == 1
