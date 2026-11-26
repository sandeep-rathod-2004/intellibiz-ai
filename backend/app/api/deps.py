from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_token, get_token_id
from app.models.entities import RevokedToken, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    subject = payload.get("sub") if payload else None
    token_id = get_token_id(token, payload) if payload else None
    if not isinstance(subject, str) or not subject.isdecimal() or not token_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    if db.query(RevokedToken).filter(RevokedToken.token_id == token_id).first():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    user = db.query(User).filter(User.id == int(subject)).first()
    if not user: raise HTTPException(status_code=401, detail="User no longer exists")
    return user
