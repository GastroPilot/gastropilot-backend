import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import jwt

logger = logging.getLogger(__name__)

_JWT_SECRET: str | None = None
_JWT_ALGORITHM: str = "HS256"
_JWT_ISSUER: str = "gastropilot"
_JWT_AUDIENCE: str = "gastropilot-api"
_JWT_LEEWAY_SECONDS: int = 10
_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
_BCRYPT_ROUNDS: int = 12
_REFRESH_TOKEN_PEPPER: str = ""


def configure(
    jwt_secret: str,
    jwt_algorithm: str = "HS256",
    jwt_issuer: str = "gastropilot",
    jwt_audience: str = "gastropilot-api",
    jwt_leeway_seconds: int = 10,
    access_token_expire_minutes: int = 60,
    refresh_token_expire_days: int = 30,
    bcrypt_rounds: int = 12,
    refresh_token_pepper: str = "",
) -> None:
    global _JWT_SECRET, _JWT_ALGORITHM, _JWT_ISSUER, _JWT_AUDIENCE
    global _JWT_LEEWAY_SECONDS, _ACCESS_TOKEN_EXPIRE_MINUTES
    global _REFRESH_TOKEN_EXPIRE_DAYS, _BCRYPT_ROUNDS, _REFRESH_TOKEN_PEPPER

    _JWT_SECRET = jwt_secret
    _JWT_ALGORITHM = jwt_algorithm
    _JWT_ISSUER = jwt_issuer
    _JWT_AUDIENCE = jwt_audience
    _JWT_LEEWAY_SECONDS = jwt_leeway_seconds
    _ACCESS_TOKEN_EXPIRE_MINUTES = access_token_expire_minutes
    _REFRESH_TOKEN_EXPIRE_DAYS = refresh_token_expire_days
    _BCRYPT_ROUNDS = bcrypt_rounds
    _REFRESH_TOKEN_PEPPER = refresh_token_pepper


def _get_secret() -> str:
    if not _JWT_SECRET:
        raise RuntimeError("JWT secret not configured. Call configure() first.")
    return _JWT_SECRET


# ---------------------------------------------------------------------------
# Password utilities (Email/Password auth)
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


# ---------------------------------------------------------------------------
# PIN utilities (Staff PIN auth)
# ---------------------------------------------------------------------------

def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_pin.encode("utf-8"),
            hashed_pin.encode("utf-8"),
        )
    except Exception:
        return False


def hash_pin(plain_pin: str) -> str:
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(plain_pin.encode("utf-8"), salt)
    return hashed.decode("utf-8")


# ---------------------------------------------------------------------------
# Token utilities
# ---------------------------------------------------------------------------

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """
    Creates a JWT access token.

    JWT payload for restaurant staff:
        { "sub": "uuid", "role": "manager", "tenant_id": "uuid", "type": "access" }

    JWT payload for platform admins:
        { "sub": "uuid", "role": "platform_admin", "tenant_id": null, "type": "access" }

    JWT payload for impersonation:
        { "sub": "uuid", "role": "platform_admin", "tenant_id": null,
          "impersonating_tenant_id": "uuid", "type": "access" }
    """
    now = datetime.now(UTC)
    to_encode = data.copy()
    expire = now + (expires_delta or timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES))

    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "iss": _JWT_ISSUER,
            "aud": _JWT_AUDIENCE,
            "type": "access",
        }
    )

    return jwt.encode(to_encode, _get_secret(), algorithm=_JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(days=_REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "user_id": user_id,
        "exp": expire,
        "iat": now,
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(to_encode, _get_secret(), algorithm=_JWT_ALGORITHM)


def verify_token(token: str, token_type: str = "access") -> dict | None:
    try:
        payload = jwt.decode(
            token,
            _get_secret(),
            algorithms=[_JWT_ALGORITHM],
            audience=_JWT_AUDIENCE,
            issuer=_JWT_ISSUER,
            options={"leeway": _JWT_LEEWAY_SECONDS},
        )

        if payload.get("type") != token_type:
            logger.warning(
                f"Token type mismatch: expected {token_type}, got {payload.get('type')}"
            )
            return None

        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.JWTClaimsError as e:
        logger.warning(f"Invalid token claims: {e}")
        return None
    except jwt.JWTError as e:
        logger.warning(f"Invalid token: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error verifying token: {e}", exc_info=True)
        return None


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256((token + _REFRESH_TOKEN_PEPPER).encode("utf-8")).hexdigest()
