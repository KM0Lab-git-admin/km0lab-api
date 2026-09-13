"""Shared HTTP helpers for public binary media (rewards / shops / towns)."""

from fastapi.responses import Response

JSON_404 = b'{"detail":"Media not found"}'

_CORP = "cross-origin"


def media_headers(*, cache: str, byte_size: int | None = None) -> dict[str, str]:
    headers = {
        "Cache-Control": cache,
        "Cross-Origin-Resource-Policy": _CORP,
        "X-Content-Type-Options": "nosniff",
        "Vary": "Origin",
    }
    if byte_size is not None:
        headers["Content-Length"] = str(byte_size)
    return headers


def media_bytes_response(
    data: bytes,
    content_type: str,
    *,
    cache: str,
    byte_size: int | None = None,
) -> Response:
    return Response(
        content=data,
        media_type=content_type,
        headers=media_headers(
            cache=cache,
            byte_size=byte_size if byte_size is not None else len(data),
        ),
    )


def media_not_found_response() -> Response:
    return Response(
        status_code=404,
        content=JSON_404,
        media_type="application/json",
        headers=media_headers(cache="no-store", byte_size=len(JSON_404)),
    )
