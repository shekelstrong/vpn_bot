"""
DPI-чекер: проверка доступности сайтов через VPN.
Позволяет пользователю проверить, заблокирован ли сайт провайдером.
"""
import httpx
from aiogram import Router, F, types
from aiogram.filters import Command
from loguru import logger

from keyboards.inline import get_back_keyboard

router = Router()

# Популярные заблокированные/условно-доступные сайты для быстрой проверки
CHECK_SITES = [
    {"name": "YouTube", "url": "https://www.youtube.com"},
    {"name": "Instagram", "url": "https://www.instagram.com"},
    {"name": "Facebook", "url": "https://www.facebook.com"},
    {"name": "Twitter/X", "url": "https://x.com"},
    {"name": "LinkedIn", "url": "https://www.linkedin.com"},
    {"name": "Dzen", "url": "https://dzen.ru"},
    {"name": "TikTok", "url": "https://www.tiktok.com"},
]


async def check_site(url: str, timeout: float = 8.0) -> dict:
    """Проверить доступность сайта. Возвращает статус и время ответа."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            import time
            start = time.monotonic()
            resp = await client.get(url)
            elapsed = time.monotonic() - start
            return {
                "accessible": resp.status_code < 400,
                "status": resp.status_code,
                "time_ms": int(elapsed * 1000),
                "error": None,
            }
    except httpx.ConnectTimeout:
        return {"accessible": False, "status": 0, "time_ms": 0, "error": "timeout"}
    except httpx.ConnectError:
        return {"accessible": False, "status": 0, "time_ms": 0, "error": "connection_refused"}
    except Exception as e:
        return {"accessible": False, "status": 0, "time_ms": 0, "error": str(e)[:50]}


@router.callback_query(F.data == "dpi_check")
@router.message(Command("dpi"))
async def dpi_check_start(callback_or_message: types.CallbackQuery | types.Message):
    """Показать меню DPI-проверки."""
    if isinstance(callback_or_message, types.CallbackQuery):
        message = callback_or_message.message
        await callback_or_message.answer()
    else:
        message = callback_or_message

    text = (
        "🔍 <b>DPI-чекер NEMO VPN</b>\n\n"
        "Проверьте, блокирует ли ваш провайдер популярные сайты.\n\n"
        "Нажмите «Быстрая проверка» для теста 7 популярных сайтов,\n"
        "или введите адрес сайта вручную.\n\n"
        "💡 <i>Для точного результата запускайте проверку БЕЗ включённого VPN</i>"
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Быстрая проверка", callback_data="dpi_quick")],
        [InlineKeyboardButton(text="✏️ Ввести адрес сайта", callback_data="dpi_custom")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="help")],
    ])

    try:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "dpi_quick")
async def dpi_quick_check(callback: types.CallbackQuery):
    """Быстрая проверка популярных сайтов."""
    await callback.answer("⏳ Проверяю сайты...")
    message = callback.message

    await message.edit_text("🔍 <b>Проверяю доступность сайтов...</b>", parse_mode="HTML")

    results = []
    for site in CHECK_SITES:
        result = await check_site(site["url"])
        results.append((site["name"], result))

    # Формируем отчёт
    lines = ["🔍 <b>Результаты DPI-проверки:</b>\n"]
    blocked_count = 0
    for name, result in results:
        if result["accessible"]:
            lines.append(f"✅ <b>{name}</b> — доступен ({result['time_ms']}мс)")
        else:
            blocked_count += 1
            err = result.get("error", f"HTTP {result['status']}")
            lines.append(f"❌ <b>{name}</b> — заблокирован ({err})")

    if blocked_count > 0:
        lines.append(
            f"\n🚫 <b>{blocked_count} из {len(results)} сайтов заблокировано!</b>\n"
            "Подключите NEMO VPN для доступа ко всем сайтам."
        )
    else:
        lines.append("\n✅ <b>Все сайты доступны!</b> Блокировок не обнаружено.")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Проверить снова", callback_data="dpi_quick")],
        [InlineKeyboardButton(text="✏️ Ввести адрес сайта", callback_data="dpi_custom")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="help")],
    ])

    await message.edit_text("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "dpi_custom")
async def dpi_custom_prompt(callback: types.CallbackQuery, state):
    """Запросить адрес сайта у пользователя."""
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>Введите адрес сайта для проверки</b>\n\n"
        "Пример: <code>youtube.com</code> или <code>https://instagram.com</code>\n\n"
        "<i>Отправьте сообщение с адресом сайта.</i>",
        parse_mode="HTML",
    )
    await state.set_state("dpi_custom_url")


@router.message(F.text, lambda m: not m.text.startswith("/"))
async def dpi_custom_check(message: types.Message, state):
    """Проверить кастомный URL."""
    url = message.text.strip()
    if not url.startswith("http"):
        url = f"https://{url}"

    await message.answer("⏳ Проверяю доступность...", parse_mode="HTML")

    result = await check_site(url)

    if result["accessible"]:
        text = (
            f"✅ <b>Сайт доступен!</b>\n\n"
            f"🔗 {url}\n"
            f"📊 HTTP {result['status']} — {result['time_ms']}мс\n\n"
            "<i>Сайт открывается без VPN.</i>"
        )
    else:
        err = result.get("error", f"HTTP {result['status']}")
        text = (
            f"❌ <b>Сайт недоступен!</b>\n\n"
            f"🔗 {url}\n"
            f"📊 Ошибка: {err}\n\n"
            "Подключите NEMO VPN для доступа к этому сайту."
        )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Проверить другой сайт", callback_data="dpi_custom")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="dpi_check")],
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.clear()