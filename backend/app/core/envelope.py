"""Consistent response envelope. [OPUS] — this is the contract, do not bypass it.

Every route returns ok(...) or raises an ApiError (see exceptions.py). Nothing
returns a bare dict.
"""
from typing import Any, Optional
from math import ceil


def ok(data: Any = None, meta: Optional[dict] = None) -> dict:
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def err(code: str, message: str, details: Optional[dict] = None) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
    }


def paginated(items: list, total: int, page: int, page_size: int) -> dict:
    return ok(
        data=items,
        meta={
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": ceil(total / page_size) if page_size else 0,
        },
    )


def clamp_pagination(page: int, page_size: int, max_size: int = 100) -> tuple[int, int]:
    page = max(1, page)
    page_size = min(max(1, page_size), max_size)  # never allow unbounded queries
    return page, page_size
