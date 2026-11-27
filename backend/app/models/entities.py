from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

def utcnow(): return datetime.now(timezone.utc)
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    datasets = relationship("Dataset", back_populates="owner", cascade="all, delete-orphan")

class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    token_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("owner_id", "content_hash", name="uq_dataset_owner_content_hash"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    file_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    owner = relationship("User", back_populates="datasets")


class CopilotConversation(Base):
    __tablename__ = "copilot_conversations"
    __table_args__ = (
        Index("ix_copilot_conversations_owner_updated", "owner_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    dataset_id: Mapped[int | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Existing conversations were created only for selected datasets. Keep that
    # meaning if a linked dataset is later deleted (dataset_id becomes NULL).
    context_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="dataset", server_default="dataset")
    title: Mapped[str] = mapped_column(String(160), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    messages = relationship(
        "CopilotMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="CopilotMessage.id",
        passive_deletes=True,
    )


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"
    __table_args__ = (
        Index("ix_copilot_messages_conversation_id_id", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("copilot_conversations.id", ondelete="CASCADE"),
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    conversation = relationship("CopilotConversation", back_populates="messages")
