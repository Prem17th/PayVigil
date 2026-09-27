import asyncio
import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID, insert
from sqlalchemy.ext.asyncio import AsyncEngine


metadata = MetaData(schema="sandbox_ledger")
transfers = Table(
    "transfers",
    metadata,
    Column("idempotency_key", PGUUID(as_uuid=True), primary_key=True),
    Column("transfer_id", PGUUID(as_uuid=True), unique=True, nullable=False),
    Column("request_payload", JSONB, nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("visible_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    CheckConstraint("status IN ('SUCCEEDED', 'FAILED')", name="transfer_status"),
)
debits = Table(
    "debits",
    metadata,
    Column(
        "idempotency_key",
        PGUUID(as_uuid=True),
        ForeignKey("sandbox_ledger.transfers.idempotency_key"),
        primary_key=True,
    ),
    Column("amount_minor", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    CheckConstraint("amount_minor > 0", name="positive_debit"),
    CheckConstraint("currency = 'INR'", name="synthetic_currency"),
)


class IdempotencyConflict(Exception):
    pass


async def assert_runtime_role(connection) -> None:
    row = (
        (
            await connection.execute(
                text("""
        SELECT r.rolsuper, r.rolbypassrls, r.rolcreatedb, r.rolcreaterole, r.rolreplication,
          EXISTS (SELECT 1 FROM pg_roles g WHERE g.rolname = 'beforetransfer_sandbox_api'
            AND pg_has_role(current_user, g.oid, 'member')) AS allowed,
          EXISTS (SELECT 1 FROM pg_roles g WHERE
            (g.rolsuper OR g.rolbypassrls OR g.rolcreatedb OR g.rolcreaterole OR g.rolreplication)
            AND pg_has_role(current_user, g.oid, 'member')) AS inherits_privilege,
          EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'sandbox_ledger'
              AND pg_has_role(current_user, c.relowner, 'member')) AS owns_tables
        FROM pg_roles r WHERE r.rolname = current_user
    """)
            )
        )
        .mappings()
        .one()
    )
    if not row["allowed"] or any(
        row[k]
        for k in (
            "rolsuper",
            "rolbypassrls",
            "rolcreatedb",
            "rolcreaterole",
            "rolreplication",
            "inherits_privilege",
            "owns_tables",
        )
    ):
        raise PermissionError("A restricted sandbox runtime role is required.")


def result(row) -> dict:
    return {
        **row["request_payload"],
        "idempotency_key": str(row["idempotency_key"]),
        "transfer_id": str(row["transfer_id"]),
        "status": row["status"],
    }


async def create_transfer(
    engine: AsyncEngine, key: UUID, payload: dict, visibility_delay: float
) -> dict:
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    async with asyncio.timeout(8), engine.begin() as connection:
        await assert_runtime_role(connection)
        now = (await connection.execute(select(func.now()))).scalar_one()
        visible_at = (
            now + timedelta(seconds=visibility_delay)
            if payload["simulation"] == "lost_response"
            else now
        )
        statement = (
            insert(transfers)
            .values(
                idempotency_key=key,
                transfer_id=uuid4(),
                request_payload=payload,
                fingerprint=fingerprint,
                status="FAILED" if payload["simulation"] == "decline" else "SUCCEEDED",
                visible_at=visible_at,
            )
            .on_conflict_do_nothing(index_elements=[transfers.c.idempotency_key])
            .returning(transfers)
        )
        row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            # READ COMMITTED sees the competing INSERT after its commit. No second debit.
            row = (
                (
                    await connection.execute(
                        select(transfers).where(transfers.c.idempotency_key == key)
                    )
                )
                .mappings()
                .one()
            )
            if row["fingerprint"] != fingerprint or row["request_payload"] != payload:
                raise IdempotencyConflict()
        elif row["status"] == "SUCCEEDED":
            await connection.execute(
                insert(debits).values(
                    idempotency_key=key,
                    amount_minor=payload["amount_minor"],
                    currency=payload["currency"],
                )
            )
        answer = result(row)
    # Commit finishes before the simulated lost response is delayed by the HTTP layer.
    return answer


async def read_transfer(engine: AsyncEngine, key: UUID) -> dict | None:
    async with asyncio.timeout(8), engine.begin() as connection:
        await assert_runtime_role(connection)
        row = (
            (
                await connection.execute(
                    select(transfers).where(
                        transfers.c.idempotency_key == key,
                        transfers.c.visible_at <= func.now(),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return result(row) if row else None


async def check_ready(engine: AsyncEngine) -> None:
    async with asyncio.timeout(8), engine.begin() as connection:
        await assert_runtime_role(connection)
        await connection.execute(select(transfers.c.idempotency_key).limit(1))
        await connection.execute(select(debits.c.idempotency_key).limit(1))
