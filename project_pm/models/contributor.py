from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from project_pm.models.base import Base


class Contributor(Base):
    __tablename__ = "contributors"

    github_username: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    auth_token: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    telegram_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    telegram_display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telegram_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
