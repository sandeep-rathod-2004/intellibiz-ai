from hashlib import sha256
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
def hash_password(password: str) -> str: return pwd_context.hash(password)
def verify_password(password: str, hashed: str) -> bool: return pwd_context.verify(password, hashed)
def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": subject, "exp": expire, "jti": uuid4().hex}, settings.secret_key, algorithm=ALGORITHM)
def decode_token(token: str):
    try: return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError: return None

def get_token_id(token: str, payload: dict) -> str | None:
    token_id = payload.get("jti")
    if isinstance(token_id, str) and token_id:
        return token_id
    if "jti" not in payload:
        return sha256(token.encode("utf-8")).hexdigest()
    return None
