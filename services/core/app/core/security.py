"""Security utilities – imports and re-exports from shared package."""
import sys
from pathlib import Path

_shared_path = Path(__file__).parent.parent.parent.parent.parent / "packages"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

from shared.auth import (  # noqa: F401
    configure,
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_pin,
    hash_refresh_token,
    verify_password,
    verify_pin,
    verify_token,
)

from .config import settings

configure(
    jwt_secret=settings.JWT_SECRET,
    jwt_algorithm=settings.JWT_ALGORITHM,
    jwt_issuer=settings.JWT_ISSUER,
    jwt_audience=settings.JWT_AUDIENCE,
    jwt_leeway_seconds=settings.JWT_LEEWAY_SECONDS,
    access_token_expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    refresh_token_expire_days=settings.REFRESH_TOKEN_EXPIRE_DAYS,
    bcrypt_rounds=settings.BCRYPT_ROUNDS,
    refresh_token_pepper=settings.REFRESH_TOKEN_PEPPER,
)
