"""Security module — context propagation, permissions, RBAC, JWT validation."""

from cxo_ai_companion.security.context import (
    ContextType,
    Permission,
    SecurityContext,
    create_anonymous_context,
    create_security_context,
    create_system_context,
)
from cxo_ai_companion.security.jwt_validator import JWTValidator, TokenClaims
from cxo_ai_companion.security.auth_dependency import (
    get_current_user,
    get_optional_user,
)

__all__ = [
    "ContextType",
    "Permission",
    "SecurityContext",
    "create_anonymous_context",
    "create_security_context",
    "create_system_context",
    "JWTValidator",
    "TokenClaims",
    "get_current_user",
    "get_optional_user",
]
