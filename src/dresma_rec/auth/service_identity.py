"""Service-to-service authentication via Cloud Run IAM identity tokens."""

from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from dresma_rec.config.settings import Settings, get_settings

security = HTTPBearer()


async def verify_service_account(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Validate a Google-signed OIDC bearer token from a calling service account."""
    if settings.environment == "development":
        return {"email": "dev-bypass"}

    try:
        return id_token.verify_oauth2_token(credentials.credentials, Request())
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
        ) from None
