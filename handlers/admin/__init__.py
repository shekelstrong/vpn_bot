from aiogram import Router
from . import admin_panel
from . import settings

# Создаем общий роутер для всей админки
router = Router(name="admin_main_router")

# Подключаем в него роутеры из соседних файлов
router.include_router(admin_panel.router)
router.include_router(settings.router)