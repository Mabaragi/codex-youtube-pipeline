from __future__ import annotations

from typing import Annotated
from urllib.parse import unquote

from fastapi import Depends, Header, HTTPException, status


def get_operator_reason(
    value: Annotated[
        str,
        Header(alias="X-Operator-Reason", min_length=3, max_length=1500),
    ],
) -> str:
    reason = unquote(value).strip()
    if not 3 <= len(reason) <= 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="X-Operator-Reason must be between 3 and 500 characters.",
        )
    return reason


OperatorReason = Annotated[str, Depends(get_operator_reason)]
