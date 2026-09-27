from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


APP_SCHEMA = "beforetransfer"


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = {"schema": APP_SCHEMA}

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('finance_admin', 'finance_reviewer', 'supplier')",
            name="membership_role_allowed",
        ),
        {"schema": APP_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # Phase 2 intentionally permits exactly one business membership per user.
    # No dependency on auth.users: identity is validated through Supabase Auth.
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, unique=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey(f"{APP_SCHEMA}.tenants.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
