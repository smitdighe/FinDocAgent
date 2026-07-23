"""RFC 7807 problem+json exception handling for the whole API."""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


def problem_response(
    *,
    status: int,
    title: str,
    detail: str | None = None,
    instance: str | None = None,
    type_: str = "about:blank",
    headers: Mapping[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"type": type_, "title": title, "status": status}
    if detail:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    if extra:
        body.update(extra)
    return JSONResponse(
        body, status_code=status, media_type=PROBLEM_CONTENT_TYPE, headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        try:
            title = HTTPStatus(exc.status_code).phrase
        except ValueError:  # pragma: no cover - non-standard code
            title = "Error"
        return problem_response(
            status=exc.status_code,
            title=title,
            detail=str(exc.detail) if exc.detail else None,
            instance=request.url.path,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            status=422,
            title="Unprocessable Entity",
            detail="request validation failed",
            instance=request.url.path,
            extra={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return problem_response(
            status=500,
            title="Internal Server Error",
            detail="an unexpected error occurred",
            instance=request.url.path,
        )
