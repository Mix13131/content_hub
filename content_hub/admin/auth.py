from __future__ import annotations

from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from content_hub.settings import Settings, get_settings


def verify_admin_token(
    settings: Annotated[Settings, Depends(get_settings)],
    admin_token: Annotated[
        str | None,
        Header(alias="X-Content-Hub-Admin-Token"),
    ] = None,
) -> None:
    if not settings.admin_api_token:
        return
    if admin_token and compare_digest(settings.admin_api_token, admin_token):
        return
    raise HTTPException(status_code=403, detail="Invalid admin token")
