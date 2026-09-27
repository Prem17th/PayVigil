"""Compatibility entrypoint for deployments using ``python -m app.payment_worker``."""

from app.payments.worker import (
    WorkerSettings,
    main,
    reconcile_or_submit,
    run,
    run_once,
    verified_readback,
)

__all__ = ["WorkerSettings", "main", "reconcile_or_submit", "run", "run_once", "verified_readback"]


if __name__ == "__main__":
    main()
