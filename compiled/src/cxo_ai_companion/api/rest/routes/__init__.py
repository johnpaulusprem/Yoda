"""Route re-exports."""
from cxo_ai_companion.api.rest.routes.health import router as health_router
from cxo_ai_companion.api.rest.routes.meetings import router as meetings_router
from cxo_ai_companion.api.rest.routes.action_items import router as action_items_router
from cxo_ai_companion.api.rest.routes.dashboard import router as dashboard_router
from cxo_ai_companion.api.rest.routes.chat import router as chat_router
from cxo_ai_companion.api.rest.routes.documents import router as documents_router
from cxo_ai_companion.api.rest.routes.insights import router as insights_router
from cxo_ai_companion.api.rest.routes.webhooks import router as webhooks_router
from cxo_ai_companion.api.rest.routes.acs_callbacks import router as acs_callbacks_router
from cxo_ai_companion.api.rest.routes.notifications import router as notifications_router
from cxo_ai_companion.api.rest.routes.search import router as search_router
from cxo_ai_companion.api.rest.routes.projects import router as projects_router

__all__ = [
    "health_router",
    "meetings_router",
    "action_items_router",
    "dashboard_router",
    "chat_router",
    "documents_router",
    "insights_router",
    "webhooks_router",
    "acs_callbacks_router",
    "notifications_router",
    "search_router",
    "projects_router",
]
