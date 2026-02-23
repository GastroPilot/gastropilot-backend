"""Tenant middleware adapter for Core Service."""
import sys
from pathlib import Path

_shared_path = Path(__file__).parent.parent.parent.parent.parent / "packages"
if str(_shared_path) not in sys.path:
    sys.path.insert(0, str(_shared_path))

from shared.tenant import TenantMiddleware, get_db_user, set_tenant_context  # noqa: F401
