# Handlers package
from handlers.start import router as start_router
from handlers.profile import router as profile_router
from handlers.trial import router as trial_router
from handlers.buy import router as buy_router
from handlers.help import router as help_router
from handlers.admin import router as admin_router

__all__ = [
    "start_router",
    "profile_router",
    "trial_router",
    "buy_router",
    "help_router",
    "admin_router",
]