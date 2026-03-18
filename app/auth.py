import hashlib
import logging
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.settings import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    BCRYPT_ROUNDS,
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER,
    JWT_LEEWAY_SECONDS,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRE_DAYS,
    REFRESH_TOKEN_PEPPER,
)

logger = logging.getLogger(__name__)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifiziert ein Klartext-Passwort gegen einen bcrypt Hash.
    Das Frontend sendet das Passwort als Klartext, das Backend hasht es.
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def hash_password(plain_password: str) -> str:
    """
    Hasht ein Klartext-Passwort mit bcrypt.
    Wird verwendet, wenn ein neues Passwort gesetzt wird.
    """
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Erstellt ein JWT Access Token.
    """
    now = datetime.now(UTC)
    to_encode = data.copy()
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    to_encode.update(
        {"exp": expire, "iat": now, "iss": JWT_ISSUER, "aud": JWT_AUDIENCE, "type": "access"}
    )

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(user_id: int) -> str:
    """
    Erstellt ein JWT Refresh Token.
    """
    import uuid

    now = datetime.now(UTC)
    expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "user_id": user_id,
        "exp": expire,
        "iat": now,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "type": "refresh",
        "jti": str(uuid.uuid4()),  # Unique token ID to ensure uniqueness
    }

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str, token_type: str = "access") -> dict | None:
    """
    Verifiziert ein JWT Token und gibt die Payload zurück.
    """
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            leeway=timedelta(seconds=JWT_LEEWAY_SECONDS),
        )

        if payload.get("type") != token_type:
            logger.warning(f"Token type mismatch: expected {token_type}, got {payload.get('type')}")
            return None

        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except (jwt.InvalidIssuerError, jwt.InvalidAudienceError) as e:
        logger.warning(f"Invalid token claims: {e}")
        return None
    except jwt.PyJWTError as e:
        logger.warning(f"Invalid token: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error verifying token: {e}", exc_info=True)
        return None


def hash_refresh_token(token: str) -> str:
    """
    Erstellt einen SHA256 Hash eines Refresh Tokens für die Speicherung in der DB.
    """
    return hashlib.sha256((token + REFRESH_TOKEN_PEPPER).encode("utf-8")).hexdigest()
