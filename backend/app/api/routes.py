import asyncio
import csv
import io
import ipaddress
import json
import logging
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token, decode_token, get_token_id
from app.core.config import openai_configuration_metadata, settings
from app.models.entities import (
    CopilotConversation,
    CopilotMessage,
    Dataset,
    RevokedToken,
    User,
    utcnow,
)
from app.api.deps import get_current_user, oauth2_scheme
from app.api.rate_limit import rate_limit
from app.services.analytics import DatasetReadError, read_dataset, profile, insights
from app.services.copilot import (
    CopilotConfigurationError,
    CopilotProviderError,
    ask_copilot,
    diagnose_openai_authentication,
    provider_readiness,
)
from app.services.reports import build_report
from app.services.storage import (
    DatasetStorageError,
    delete_dataset as remove_stored_dataset,
    read_dataset as read_stored_dataset,
    save_dataset as save_stored_dataset,
)
from app.ml.engine import detect_anomalies, forecast_series, json_safe

logger = logging.getLogger(__name__)
router=APIRouter()
DATA_DIR=Path(__file__).resolve().parents[2] / "uploads"
DATA_DIR.mkdir(exist_ok=True)
class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10)
    password_confirmation: str = Field(min_length=10)

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_full_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("password", "password_confirmation")
    @classmethod
    def password_fits_bcrypt_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def passwords_match(self) -> "RegisterIn":
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        return self

class AuthUser(BaseModel):
    id: int
    email: EmailStr
    full_name: str

class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    user: AuthUser

class RegistrationResponse(BaseModel):
    message: str
    user: AuthUser

class DatasetPreview(BaseModel):
    rows: list[dict[str, Any]]
    total: int
    offset: int
    limit: int
    columns: list[str]

class ChatIn(BaseModel):
    question: str


class ConversationCreateIn(BaseModel):
    dataset_id: int | None = Field(default=None, gt=0)


class ConversationRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = " ".join(value.split())
        if not title:
            raise ValueError("Conversation title cannot be empty")
        return title


class ConversationMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=1200)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Message cannot be empty")
        return content


class ClearConversationsIn(BaseModel):
    confirmation: Literal["CLEAR"]


class ForecastIn(BaseModel):
    date_column: str
    target_column: str
    horizon: int = 6


def filter_dataset_rows(df, search: str | None, column_filters: str | None):
    if search:
        term = search.strip()
        if term:
            mask = df.astype("string").apply(
                lambda column: column.str.contains(term, case=False, regex=False, na=False)
            ).any(axis=1)
            df = df[mask]

    if not column_filters:
        return df
    if len(column_filters) > 4096:
        raise HTTPException(400, "Column filter payload is too large")
    try:
        filters = json.loads(column_filters)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Column filters must be valid JSON") from exc
    if not isinstance(filters, dict) or len(filters) > 20:
        raise HTTPException(400, "Provide at most 20 column filters")

    columns = {str(column): column for column in df.columns}
    for name, value in filters.items():
        if name not in columns:
            raise HTTPException(400, f"Filter column does not exist: {name}")
        if not isinstance(value, str) or len(value) > 200:
            raise HTTPException(400, "Column filter values must be strings of 200 characters or fewer")
        term = value.strip()
        if term:
            df = df[
                df[columns[name]].astype("string").str.contains(
                    term,
                    case=False,
                    regex=False,
                    na=False,
                )
            ]
    return df


def _spreadsheet_safe(value):
    value = json_safe(value)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


@router.post(
    '/auth/register',
    response_model=RegistrationResponse,
    dependencies=[Depends(rate_limit("registration", settings.registration_requests_per_hour, 3600))],
)
def register(payload:RegisterIn, db:Session=Depends(get_db)):
    email = str(payload.email).lower()
    if db.query(User).filter(User.email==email).first(): raise HTTPException(409,"An account with this email already exists")
    user=User(email=email,full_name=payload.full_name,hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.query(User).filter(User.email==email).first():
            raise HTTPException(409,"An account with this email already exists") from exc
        raise
    db.refresh(user)
    return {
        "message": "Registration successful. Sign in with your credentials.",
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name},
    }
@router.post(
    '/auth/login',
    response_model=AuthResponse,
    dependencies=[Depends(rate_limit("login", settings.login_requests_per_minute, 60))],
)
def login(form:OAuth2PasswordRequestForm=Depends(),db:Session=Depends(get_db)):
    user=db.query(User).filter(User.email==form.username.lower()).first()
    if not user or not verify_password(form.password,user.hashed_password): raise HTTPException(401,"Incorrect email or password")
    return {"access_token":create_access_token(str(user.id)),"token_type":"bearer","user":{"id":user.id,"email":user.email,"full_name":user.full_name}}
@router.post('/auth/logout')
def logout(
    token: str = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = decode_token(token)
    token_id = get_token_id(token, payload) if payload else None
    expiration = payload.get("exp") if payload else None
    if not isinstance(token_id, str) or not isinstance(expiration, (int, float)):
        raise HTTPException(401, "Invalid or expired session")
    db.add(RevokedToken(
        token_id=token_id,
        expires_at=datetime.fromtimestamp(expiration, timezone.utc),
    ))
    db.commit()
    return {"logged_out": True}
@router.get('/auth/me', response_model=AuthUser)
def me(user:User=Depends(get_current_user)): return {"id":user.id,"email":user.email,"full_name":user.full_name}

def owned_dataset(dataset_id:int,user:User,db:Session):
    ds=db.query(Dataset).filter(Dataset.id==dataset_id,Dataset.owner_id==user.id).first()
    if not ds: raise HTTPException(404,"Dataset not found")
    return ds


def owned_conversation(conversation_id: int, user: User, db: Session) -> CopilotConversation:
    conversation = db.query(CopilotConversation).filter(
        CopilotConversation.id == conversation_id,
        CopilotConversation.owner_id == user.id,
    ).first()
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return conversation


def conversation_payload(conversation: CopilotConversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "dataset_id": conversation.dataset_id,
        "dataset_available": conversation.dataset_id is not None,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def message_payload(message: CopilotMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "provider": message.provider,
        "created_at": message.created_at.isoformat(),
    }


def load(ds):
    path = DATA_DIR / ds.stored_name
    try:
        content = read_stored_dataset(ds.stored_name, path)
    except FileNotFoundError as exc:
        raise HTTPException(410, "Dataset file is no longer available") from exc
    except DatasetStorageError as exc:
        raise HTTPException(503, "Dataset storage is unavailable. Please retry later.") from exc
    return read_dataset(io.BytesIO(content), Path(ds.name or ds.stored_name).suffix)


@router.post('/datasets/upload')
async def upload_dataset(file:UploadFile=File(...),user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in {'.csv','.xlsx'}: raise HTTPException(415,"Upload a CSV or XLSX file")
    content=await file.read(settings.max_upload_mb*1024*1024+1)
    if len(content)>settings.max_upload_mb*1024*1024: raise HTTPException(413,f"File exceeds {settings.max_upload_mb} MB limit")
    content_hash = sha256(content).hexdigest()
    existing_dataset = db.query(Dataset).filter(
        Dataset.owner_id == user.id,
        Dataset.content_hash == content_hash,
    ).first()
    if existing_dataset:
        raise HTTPException(409, f"This file is already uploaded as {existing_dataset.name}")

    legacy_datasets = db.query(Dataset).filter(
        Dataset.owner_id == user.id,
        Dataset.content_hash.is_(None),
        Dataset.file_size == len(content),
    ).all()
    for existing in legacy_datasets:
        data_root = DATA_DIR.resolve()
        existing_path = (DATA_DIR / existing.stored_name).resolve()
        try:
            existing_path.relative_to(data_root)
        except ValueError:
            continue
        if Path(existing.stored_name).name != existing.stored_name:
            continue
        try:
            existing_content = await asyncio.to_thread(
                read_stored_dataset,
                existing.stored_name,
                existing_path,
            )
        except FileNotFoundError:
            continue
        except DatasetStorageError as exc:
            raise HTTPException(503, "Dataset storage is unavailable. Please retry later.") from exc
        if sha256(existing_content).hexdigest() == content_hash:
            raise HTTPException(409, f"This file is already uploaded as {existing.name}")

    try:
        df = await asyncio.to_thread(read_dataset, io.BytesIO(content), suffix)
    except DatasetReadError as exc:
        logger.warning(
            "Dataset parsing rejected extension=%s exception=%s",
            suffix,
            type(exc).__name__,
        )
        raise HTTPException(400, str(exc)) from exc
    if df.empty or len(df) > settings.max_rows or len(df.columns) > 100:
        raise HTTPException(
            400,
            f"Dataset must contain 1–{settings.max_rows} rows and at most 100 columns.",
        )
    if len(df.columns) == 0:
        raise HTTPException(400, "No columns were found in the uploaded dataset.")
    if len(df) * len(df.columns) > settings.max_dataset_cells:
        raise HTTPException(
            413,
            f"Dataset exceeds the {settings.max_dataset_cells:,}-cell processing limit.",
        )

    ds = None
    stored = ""
    for attempt in range(3):
        stored = f"{uuid4().hex}{suffix}"
        ds = Dataset(
            owner_id=user.id,
            name=(file.filename or "dataset")[:255],
            stored_name=stored,
            content_hash=content_hash,
            row_count=len(df),
            column_count=len(df.columns),
            file_size=len(content),
        )
        db.add(ds)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            if db.query(Dataset).filter(
                Dataset.owner_id == user.id,
                Dataset.content_hash == content_hash,
            ).first():
                raise HTTPException(
                    409,
                    "This file has already been uploaded",
                ) from exc
            if (
                db.query(Dataset)
                .filter(Dataset.stored_name == stored)
                .first()
                and attempt < 2
            ):
                continue
            raise
        break
    else:
        raise HTTPException(503, "Could not reserve a unique dataset storage key.")

    if ds is None:
        raise HTTPException(503, "Could not reserve a unique dataset storage key.")

    path = DATA_DIR / stored
    try:
        await asyncio.to_thread(save_stored_dataset, stored, content, path)
    except DatasetStorageError as exc:
        db.rollback()
        raise HTTPException(503, "Dataset storage is unavailable. Please retry later.") from exc
    except OSError:
        db.rollback()
        raise

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.query(Dataset).filter(
            Dataset.owner_id == user.id,
            Dataset.content_hash == content_hash,
        ).first():
            raise HTTPException(409, "This file has already been uploaded") from exc
        raise
    except SQLAlchemyError:
        db.rollback()
        raise
    db.refresh(ds)
    return {"id":ds.id,"name":ds.name,"rows":ds.row_count,"columns":ds.column_count,"size":ds.file_size}
@router.get('/datasets')
def list_datasets(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return [{"id":d.id,"name":d.name,"rows":d.row_count,"columns":d.column_count,"size":d.file_size,"created_at":d.created_at.isoformat()} for d in db.query(Dataset).filter(Dataset.owner_id==user.id).order_by(Dataset.created_at.desc()).all()]
@router.get('/datasets/{dataset_id}/preview', response_model=DatasetPreview)
def dataset_preview(
    dataset_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    filters: str | None = None,
    sort_by: str | None = None,
    descending: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    df = load(owned_dataset(dataset_id, user, db))
    if sort_by and sort_by not in df.columns:
        raise HTTPException(400, "Sort column does not exist")
    df = filter_dataset_rows(df, search, filters)
    total = len(df)
    if sort_by:
        df = df.sort_values(
            by=sort_by,
            ascending=not descending,
            na_position="last",
            kind="mergesort",
        )
    rows = [
        {str(column): json_safe(value) for column, value in row.items()}
        for row in df.iloc[offset:offset + limit].to_dict(orient="records")
    ]
    return {
        "rows": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "columns": [str(column) for column in df.columns],
    }


@router.get('/datasets/{dataset_id}/export')
def export_dataset(
    dataset_id: int,
    search: str | None = Query(None, max_length=200),
    filters: str | None = None,
    sort_by: str | None = None,
    descending: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    df = load(owned_dataset(dataset_id, user, db))
    if sort_by and sort_by not in df.columns:
        raise HTTPException(400, "Sort column does not exist")
    df = filter_dataset_rows(df, search, filters)
    if sort_by:
        df = df.sort_values(
            by=sort_by,
            ascending=not descending,
            na_position="last",
            kind="mergesort",
        )

    def rows():
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([_spreadsheet_safe(column) for column in df.columns])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for values in df.itertuples(index=False, name=None):
            writer.writerow([_spreadsheet_safe(value) for value in values])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="dataset-{dataset_id}-filtered.csv"'},
    )

@router.get('/samples/retail-sales')
def download_retail_sample():
    sample_path = Path(__file__).resolve().parents[3] / "sample-data" / "retail_sales.csv"
    if not sample_path.is_file():
        raise HTTPException(404, "The retail sales sample is unavailable")
    return FileResponse(sample_path, media_type="text/csv", filename="retail_sales.csv")

@router.delete('/datasets/{dataset_id}')
def delete_dataset(dataset_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    ds=owned_dataset(dataset_id,user,db)
    stored_name = ds.stored_name
    stored_path = DATA_DIR / stored_name
    deleted_dataset_id = ds.id
    db.query(CopilotConversation).filter(
        CopilotConversation.dataset_id == ds.id,
    ).update(
        {CopilotConversation.dataset_id: None},
        synchronize_session=False,
    )
    db.delete(ds)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "Dataset deletion transaction failed dataset_id=%s exception=%s",
            deleted_dataset_id,
            type(exc).__name__,
        )
        raise HTTPException(
            503,
            "Dataset could not be deleted. Please retry later.",
        ) from exc
    try:
        remove_stored_dataset(stored_name, stored_path)
    except (DatasetStorageError, OSError) as exc:
        logger.error(
            "Dataset record deleted but storage cleanup failed dataset_id=%s exception=%s",
            deleted_dataset_id,
            type(exc).__name__,
        )
        raise HTTPException(
            503,
            "Dataset record was deleted, but storage cleanup failed. Please contact support.",
        ) from exc
    return {"deleted":True}
@router.get('/datasets/{dataset_id}/analysis')
def get_analysis(dataset_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    ds=owned_dataset(dataset_id,user,db)
    df=load(ds)
    dataset_profile=profile(df)
    return {
        "dataset":{"id":ds.id,"name":ds.name},
        "profile":dataset_profile,
        "insights":insights(df,dataset_profile),
    }
@router.get('/datasets/{dataset_id}/anomalies')
def anomalies(
    dataset_id: int,
    contamination: float = Query(0.05, ge=0.01, le=0.2),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return detect_anomalies(load(owned_dataset(dataset_id,user,db)), contamination)


@router.get('/datasets/{dataset_id}/anomalies/export')
def export_anomalies(
    dataset_id: int,
    contamination: float = Query(0.05, ge=0.01, le=0.2),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    df = load(owned_dataset(dataset_id,user,db))
    result = detect_anomalies(df, contamination)
    if not result["available"]:
        raise HTTPException(422, result["reason"])
    columns = ["record", "anomaly_score", "explanation"] + [str(column) for column in df.columns]

    def rows():
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([_spreadsheet_safe(column) for column in columns])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for anomaly in result["rows"]:
            values = anomaly["values"]
            writer.writerow(
                [
                    anomaly["row"] + 1,
                    anomaly["score"],
                    "; ".join(anomaly["reasons"]),
                    *[_spreadsheet_safe(values.get(str(column))) for column in df.columns],
                ]
            )
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="dataset-{dataset_id}-anomalies.csv"'},
    )


@router.post('/datasets/{dataset_id}/forecast')
def forecast(dataset_id:int,payload:ForecastIn,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    df=load(owned_dataset(dataset_id,user,db))
    if payload.date_column not in df.columns or payload.target_column not in df.columns: raise HTTPException(400,"Selected columns do not exist")
    if not 1<=payload.horizon<=24: raise HTTPException(400,"Horizon must be between 1 and 24")
    return forecast_series(df,payload.date_column,payload.target_column,payload.horizon)
@router.post(
    '/datasets/{dataset_id}/copilot',
    dependencies=[Depends(rate_limit("copilot", settings.copilot_requests_per_minute, 60))],
)
async def copilot(dataset_id:int,payload:ChatIn,request:Request,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    if not payload.question.strip() or len(payload.question)>1200: raise HTTPException(400,"Question must be between 1 and 1200 characters")
    ds=owned_dataset(dataset_id,user,db)
    df=await asyncio.to_thread(load, ds)
    dataset_profile = profile(df, include_all_summaries=True)
    dataset_profile.pop("preview", None)
    facts={"dataset":ds.name,"profile":dataset_profile,"insights":insights(df,dataset_profile)}
    try:
        return await ask_copilot(payload.question,facts,request.state.request_id)
    except CopilotConfigurationError as exc:
        raise HTTPException(503,str(exc)) from exc
    except CopilotProviderError as exc:
        raise HTTPException(
            exc.status_code,
            detail={
                "message": str(exc),
                "retryable": exc.retryable,
                "retry_after_seconds": exc.retry_after_seconds,
                "provider_status": exc.provider_status,
            },
        ) from exc


@router.get("/copilot/status")
def copilot_status(user: User = Depends(get_current_user)):
    return provider_readiness()


@router.post("/copilot/diagnostics/openai", include_in_schema=False)
async def local_openai_diagnostic(request: Request):
    client = request.client
    try:
        is_loopback = bool(client and ipaddress.ip_address(client.host).is_loopback)
    except ValueError:
        is_loopback = False
    if settings.environment.lower() not in {"development", "dev", "local"} or not is_loopback:
        raise HTTPException(404, "Not found")

    configuration = openai_configuration_metadata()
    try:
        result = await diagnose_openai_authentication()
    except CopilotConfigurationError as exc:
        raise HTTPException(
            503,
            detail={"message": str(exc), "configuration": configuration},
        ) from exc
    except CopilotProviderError as exc:
        raise HTTPException(
            exc.status_code,
            detail={
                "message": str(exc),
                "status": exc.provider_status,
                "upstream_status_code": exc.upstream_status_code,
                "provider_error_code": exc.provider_error_code,
                "provider_error_type": exc.provider_error_type,
                "retry_after_seconds": exc.retry_after_seconds,
                "configuration": configuration,
            },
        ) from exc
    return {**result, "configuration": configuration}


@router.get("/copilot/conversations")
def list_copilot_conversations(
    search: str | None = Query(None, max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(CopilotConversation).filter(CopilotConversation.owner_id == user.id)
    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        matching_messages = db.query(CopilotMessage.conversation_id).filter(
            CopilotMessage.content.ilike(search_pattern),
        )
        query = query.filter(or_(
            CopilotConversation.title.ilike(search_pattern),
            CopilotConversation.id.in_(matching_messages),
        ))
    total = query.count()
    conversations = query.order_by(
        CopilotConversation.updated_at.desc(),
        CopilotConversation.id.desc(),
    ).offset(offset).limit(limit).all()
    return {
        "items": [conversation_payload(conversation) for conversation in conversations],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.post("/copilot/conversations", status_code=201)
def create_copilot_conversation(
    payload: ConversationCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.dataset_id is not None:
        owned_dataset(payload.dataset_id, user, db)
    conversation = CopilotConversation(
        owner_id=user.id,
        dataset_id=payload.dataset_id,
        title="New conversation",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation_payload(conversation)


@router.get("/copilot/conversations/{conversation_id}")
def get_copilot_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return conversation_payload(owned_conversation(conversation_id, user, db))


@router.patch("/copilot/conversations/{conversation_id}")
def rename_copilot_conversation(
    conversation_id: int,
    payload: ConversationRenameIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = owned_conversation(conversation_id, user, db)
    conversation.title = payload.title
    conversation.updated_at = utcnow()
    db.commit()
    db.refresh(conversation)
    return conversation_payload(conversation)


@router.get("/copilot/conversations/{conversation_id}/messages")
def list_copilot_messages(
    conversation_id: int,
    limit: int = Query(50, ge=1, le=100),
    before_id: int | None = Query(None, ge=1),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owned_conversation(conversation_id, user, db)
    query = db.query(CopilotMessage).filter(
        CopilotMessage.conversation_id == conversation_id,
    )
    total = query.count()
    page_query = query
    if before_id is not None:
        page_query = page_query.filter(CopilotMessage.id < before_id)
    messages = page_query.order_by(CopilotMessage.id.desc()).limit(limit).all()
    messages.reverse()
    has_more = bool(
        messages
        and query.filter(CopilotMessage.id < messages[0].id).first()
    )
    return {
        "items": [message_payload(message) for message in messages],
        "total": total,
        "limit": limit,
        "has_more": has_more,
    }


@router.post("/copilot/conversations/{conversation_id}/messages", status_code=201)
def append_copilot_message(
    conversation_id: int,
    payload: ConversationMessageIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = owned_conversation(conversation_id, user, db)
    last_message = db.query(CopilotMessage).filter(
        CopilotMessage.conversation_id == conversation_id,
    ).order_by(CopilotMessage.id.desc()).first()
    if last_message and last_message.role == "user":
        raise HTTPException(409, "Retry or finish the previous Copilot response before sending another message.")

    content = payload.content
    message = CopilotMessage(
        conversation_id=conversation.id,
        role="user",
        content=content,
    )
    db.add(message)
    if conversation.title == "New conversation":
        conversation.title = content[:157].rstrip() + ("..." if len(content) > 160 else "")
    conversation.updated_at = utcnow()
    db.commit()
    db.refresh(message)
    return message_payload(message)


@router.post(
    "/copilot/conversations/{conversation_id}/messages/{message_id}/answer",
    dependencies=[Depends(rate_limit("copilot", settings.copilot_requests_per_minute, 60))],
)
async def answer_copilot_message(
    conversation_id: int,
    message_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = owned_conversation(conversation_id, user, db)
    message = db.query(CopilotMessage).filter(
        CopilotMessage.id == message_id,
        CopilotMessage.conversation_id == conversation_id,
        CopilotMessage.role == "user",
    ).first()
    if not message:
        raise HTTPException(404, "User message not found")

    next_message = db.query(CopilotMessage).filter(
        CopilotMessage.conversation_id == conversation_id,
        CopilotMessage.id > message_id,
    ).order_by(CopilotMessage.id.asc()).first()
    if next_message:
        if next_message.role == "assistant":
            return message_payload(next_message)
        raise HTTPException(409, "Only the latest unanswered Copilot message can be retried.")

    if conversation.dataset_id is None:
        raise HTTPException(409, "This conversation's dataset is unavailable. Its history has been preserved.")
    dataset = owned_dataset(conversation.dataset_id, user, db)
    frame = await asyncio.to_thread(load, dataset)
    dataset_profile = profile(frame, include_all_summaries=True)
    dataset_profile.pop("preview", None)
    facts = {
        "dataset": dataset.name,
        "profile": dataset_profile,
        "insights": insights(frame, dataset_profile),
    }
    question = message.content
    history_rows = db.query(CopilotMessage).filter(
        CopilotMessage.conversation_id == conversation_id,
        CopilotMessage.id < message_id,
    ).order_by(CopilotMessage.id.desc()).limit(12).all()
    history = [
        {"role": item.role, "content": item.content}
        for item in reversed(history_rows)
        if item.role in {"user", "assistant"}
    ]
    db.rollback()

    try:
        answer = await ask_copilot(
            question,
            facts,
            request.state.request_id,
            conversation_history=history,
        )
    except CopilotConfigurationError as exc:
        raise HTTPException(
            503,
            detail={"message": str(exc), "retryable": False, "message_id": message_id},
        ) from exc
    except CopilotProviderError as exc:
        raise HTTPException(
            exc.status_code,
            detail={
                "message": str(exc),
                "retryable": exc.retryable,
                "retry_after_seconds": exc.retry_after_seconds,
                "provider_status": exc.provider_status,
                "provider_error_code": exc.provider_error_code,
                "provider_error_type": exc.provider_error_type,
                "message_id": message_id,
            },
        ) from exc

    saved_answer = CopilotMessage(
        conversation_id=conversation_id,
        role="assistant",
        content=answer["answer"],
        provider=answer["provider"],
    )
    updated_conversation = owned_conversation(conversation_id, user, db)
    updated_conversation.updated_at = utcnow()
    db.add(saved_answer)
    db.commit()
    db.refresh(saved_answer)
    return message_payload(saved_answer)


@router.delete("/copilot/conversations/{conversation_id}")
def delete_copilot_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = owned_conversation(conversation_id, user, db)
    db.query(CopilotMessage).filter(
        CopilotMessage.conversation_id == conversation_id,
    ).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
    return {"deleted": True}


@router.delete("/copilot/conversations")
def clear_copilot_conversations(
    payload: ClearConversationsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owned_ids = db.query(CopilotConversation.id).filter(
        CopilotConversation.owner_id == user.id,
    )
    deleted_count = owned_ids.count()
    if deleted_count:
        db.query(CopilotMessage).filter(
            CopilotMessage.conversation_id.in_(owned_ids),
        ).delete(synchronize_session=False)
        db.query(CopilotConversation).filter(
            CopilotConversation.owner_id == user.id,
        ).delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted_count}


@router.get('/datasets/{dataset_id}/report')
def report(dataset_id:int,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    ds=owned_dataset(dataset_id,user,db); df=load(ds); pdf=build_report(ds.name,profile(df),insights(df))
    return StreamingResponse(pdf,media_type='application/pdf',headers={"Content-Disposition":f'attachment; filename="intellibiz-report-{ds.id}.pdf"'})
