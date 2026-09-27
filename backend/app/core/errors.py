from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """An intentionally safe, public error; never attach provider responses."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


async def app_error_handler(_: Request, error: AppError) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if error.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=error.status,
        content={"error": {"code": error.code, "message": error.message}},
        headers=headers,
    )
