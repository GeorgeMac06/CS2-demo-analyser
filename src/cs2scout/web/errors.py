"""The API error envelope ``{code, message}`` (design §5.6)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from cs2scout.core.errors import ErrorCode


class ApiError(Exception):
    def __init__(self, status: int, code: ErrorCode | str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, str(code), message


def not_found(what: str) -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND, f"{what} not found")


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()))
        return JSONResponse(
            {
                "code": ErrorCode.INVALID_REQUEST,
                "message": f"{where}: {first.get('msg', 'invalid')}",
            },
            status_code=422,
        )
