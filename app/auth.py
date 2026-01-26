from jose import jwt
import bcrypt
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from app.settings import (
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_ISSUER,
    JWT_AUDIENCE,
    JWT_LEEWAY_SECONDS,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    BCRYPT_ROUNDS,
    REFRESH_TOKEN_PEPPER,
)

logger = logging.getLogger(__name__)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifiziert ein Klartext-Passwort gegen einen bcrypt Hash.
    Das Frontend sendet das Passwort als Klartext, das Backend hasht es.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def hash_password(plain_password: str) -> str:
    """
    Hasht ein Klartext-Passwort mit bcrypt.
    Wird verwendet, wenn ein neues Passwort gesetzt wird.
    """
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(plain_password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def create_access_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Erstellt ein JWT Access Token.
    """
    now = datetime.now(timezone.utc)
    to_encode = data.copy()
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    to_encode.update({
        "exp": expire,
        "iat": now,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "type": "access"
    })

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(user_id: int) -> str:
    """
    Erstellt ein JWT Refresh Token.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "user_id": user_id,
        "exp": expire,
        "iat": now,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "type": "refresh"
    }

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str, token_type: str = "access") -> Optional[Dict]:
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
            options={"leeway": JWT_LEEWAY_SECONDS},
        )

        if payload.get("type") != token_type:
            logger.warning(f"Token type mismatch: expected {token_type}, got {payload.get('type')}")
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
    """
    Erstellt einen SHA256 Hash eines Refresh Tokens für die Speicherung in der DB.
    """
    return hashlib.sha256((token + REFRESH_TOKEN_PEPPER).encode('utf-8')).hexdigest()
