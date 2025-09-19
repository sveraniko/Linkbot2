# app/handlers/__init__.py — sane order & safe imports (drop-in)

from aiogram import Router

from .base import router as base_router
from .menu import router as menu_router
from .keyboard import router as kb_router
from .status import router as status_router
from .ask import router as ask_router
from .answer_actions import router as ans_router
from .import_file import router as import_router
from .config_handler import router as config_router

# Optional modules — fail safe if missing
try:
    from .memory_panel import router as memory_router  # may be absent
except Exception:
    memory_router = None

try:
    from .chat_fixed import router as chat_fixed_router  # likely absent
except Exception:
    chat_fixed_router = None

try:
    from .chat import router as chat_router
except Exception:
    chat_router = None

from .zip_handlers import router as zip_router
from .export import router as export_router
from .repo import router as repo_router
from .cleanup import router as cleanup_router
from .batch_ops import router as batch_ops_router

router = Router(name="root")

# !!! ORDER MATTERS !!!
# 1) Keyboard FIRST — it must capture bottom-row buttons (Actions / Chat ON/OFF / ASK-WIZARD)
router.include_router(base_router)
router.include_router(menu_router)
router.include_router(kb_router)

# 2) Then all the rest
router.include_router(status_router)
router.include_router(config_router)
router.include_router(import_router)
if memory_router:
    router.include_router(memory_router)

# ASK AFTER keyboard — it has a broad message handler
router.include_router(ask_router)
router.include_router(ans_router)

router.include_router(zip_router)
router.include_router(export_router)
router.include_router(repo_router)
router.include_router(cleanup_router)
router.include_router(batch_ops_router)

# Chat router(s) last
if chat_fixed_router:
    router.include_router(chat_fixed_router)
elif chat_router:
    router.include_router(chat_router)
