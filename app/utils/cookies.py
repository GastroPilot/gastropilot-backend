"""
Cookie utilities for secure token handling.
"""

from fastapi import Response

from app.settings import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    COOKIE_DOMAIN,
    COOKIE_PATH,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    REFRESH_TOKEN_EXPIRE_DAYS,
)


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    """
    Set HttpOnly cookies for access and refresh tokens.

    Args:
        response: FastAPI Response object
        access_token: JWT access token
        refresh_token: JWT refresh token
    """
    # Access token cookie - shorter expiry
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path=COOKIE_PATH,
        domain=COOKIE_DOMAIN,
        secure=COOKIE_SECURE,
        httponly=True,
        samesite=COOKIE_SAMESITE,
    )

    # Refresh token cookie - longer expiry
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        expires=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=COOKIE_PATH,
        domain=COOKIE_DOMAIN,
        secure=COOKIE_SECURE,
        httponly=True,
        samesite=COOKIE_SAMESITE,
    )

    # Also set a non-httponly cookie to indicate auth state to JavaScript
    # This doesn't contain the actual token, just indicates logged-in status
    response.set_cookie(
        key="is_authenticated",
        value="true",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path=COOKIE_PATH,
        domain=COOKIE_DOMAIN,
        secure=COOKIE_SECURE,
        httponly=False,
        samesite=COOKIE_SAMESITE,
    )


def clear_auth_cookies(response: Response) -> None:
    """
    Clear all authentication cookies.

    Args:
        response: FastAPI Response object
    """
    response.delete_cookie(
        key="access_token",
        path=COOKIE_PATH,
        domain=COOKIE_DOMAIN,
    )
    response.delete_cookie(
        key="refresh_token",
        path=COOKIE_PATH,
        domain=COOKIE_DOMAIN,
    )
    response.delete_cookie(
        key="is_authenticated",
        path=COOKIE_PATH,
        domain=COOKIE_DOMAIN,
    )


def get_token_from_cookie_or_header(
    cookie_token: str | None,
    header_token: str | None,
) -> str | None:
    """
    Get token from cookie or Authorization header.
    Cookies take precedence over headers when USE_HTTPONLY_COOKIES is enabled.

    Args:
        cookie_token: Token from cookie
        header_token: Token from Authorization header

    Returns:
        The token to use, or None if neither is available
    """
    from app.settings import USE_HTTPONLY_COOKIES

    if USE_HTTPONLY_COOKIES and cookie_token:
        return cookie_token

    if header_token:
        # Remove "Bearer " prefix if present
        if header_token.startswith("Bearer "):
            return header_token[7:]
        return header_token

    return cookie_token
