"""
Обработчик раздела помощи.
Инструкции по настройке V2Box и FAQ.
"""

from aiogram import Router, F, types
from aiogram.filters import Command
from loguru import logger

from keyboards.inline import (
    get_help_keyboard,
    get_v2box_instruction_keyboard,
    get_main_menu_keyboard,
)

router = Router()


@router.callback_query(F.data == "help")
@router.message(Command("help"))
@router.message(F.text == "Помощь 🆘")
async def show_help(callback_or_message: types.CallbackQuery | types.Message):
    """Показать меню помощи."""
    if isinstance(callback_or_message, types.CallbackQuery):
        callback = callback_or_message
        message = callback.message
        await callback.answer()
    else:
        message = callback_or_message
    
    help_text = (
        "🆘 <b>Центр помощи Nemo VPN</b>\n\n"
        "Выберите тему, которая вас интересует:\n\n"
        "📱 <b>Как настроить V2Box</b>\n"
        "Пошаговая инструкция по настройке приложения\n\n"
        "❓ <b>Частые вопросы</b>\n"
        "Ответы на популярные вопросы\n\n"
        "💬 <b>Техподдержка</b>\n"
        "Связаться с оператором"
    )
    
    await message.answer(
        text=help_text,
        reply_markup=get_help_keyboard(),
    )


@router.callback_query(F.data == "help_v2box")
async def help_v2box(callback: types.CallbackQuery):
    """Инструкция по настройке V2Box."""
    instruction_text = (
        "📱 <b>Настройка V2Box для Nemo VPN</b>\n\n"
        "<b>Шаг 1: Скачайте приложение</b>\n"
        "• iOS / macOS: App Store\n"
        "• Android: Google Play Store\n\n"
        "<b>Шаг 2: Получите ссылку</b>\n"
        "В разделе «Мой профиль» нажмите «Получить ссылку 🔗» и скопируйте её.\n\n"
        "<b>Шаг 3: Добавьте профиль VPN</b>\n"
        "1. Откройте приложение V2Box\n"
        "2. Перейдите в раздел <b>Configs</b> (внизу)\n"
        "3. Нажмите «+» в правом верхнем углу\n"
        "4. Выберите <b>Import V2ray URL from Clipboard</b>\n\n"
        "<b>Шаг 4: Подключитесь</b>\n"
        "1. Перейдите в раздел <b>Home</b>\n"
        "2. Проведите вправо ползунок <b>Slide to Connect</b>\n"
        "3. Готово! VPN активен 🎉\n\n"
        "🌟 <b>Для пользователей тарифа VIP (Обход списков):</b>\n"
        "Крупный бизнес и РКН всё чаще детектят устройства с включенным VPN. "
        "Поэтому мы <b>специально не встраиваем маршрутизацию в основной ключ</b>. "
        "Для VIP-тарифа мы выдаем второй ключ (и видео-инструкцию), который настраивает ваше окружение вручную: "
        "российские сервисы и Госуслуги работают напрямую от вашего провайдера, а заблокированные сайты (Instagram, X) — через VPN. "
        "Это гарантирует, что РКН не увидит подмены, а VPN будет работать даже при тотальных блокировках!"
    )
    
    await callback.message.answer(
        text=instruction_text,
        reply_markup=get_v2box_instruction_keyboard(),
    )
    
    await callback.answer()


@router.callback_query(F.data == "help_faq")
async def help_faq(callback: types.CallbackQuery):
    """Частые вопросы."""
    faq_text = (
        "❓ <b>Частые вопросы (FAQ)</b>\n\n"
        
        "<b>🔹 Как работает триал?</b>\n"
        "Триал даёт 24 часа доступа с лимитом 1GB трафика.\n"
        "Доступен один раз для каждого пользователя.\n\n"
        
        "<b>🔹 Как продлить подписку?</b>\n"
        "Перейдите в «Купить подписку» и выберите тариф.\n"
        "Новая подписка автоматически продлит текущую.\n\n"
        
        "<b>🔹 Чем отличается VIP-тариф?</b>\n"
        "В VIP-тарифе мы используем умную маршрутизацию (сплит-туннелинг). "
        "Российские сайты открываются с вашего реального IP, а заблокированные — через VPN. "
        "Это защищает соединение от РКН и ускоряет работу банков.\n\n"
        
        "<b>🔹 Как работает реферальная программа?</b>\n"
        "Приглашайте друзей и получайте проценты с их покупок:\n"
        "• 1 уровень — 15%\n"
        "• 2 уровень — 10%\n"
        "• 3 уровень — 5%\n\n"
        
        "<b>🔹 Какие способы оплаты доступны?</b>\n"
        "• CryptoBot (USDT, TON, Bitcoin)\n"
        "• Банковские карты РФ (через Platega)\n\n"
        
        "<b>🔹 Что такое VLESS Reality?</b>\n"
        "Новейший протокол маскировки трафика. Провайдер видит ваше соединение как "
        "обычный заход на разрешенный сайт (например, Microsoft), что исключает блокировку.\n\n"
        
        "<b>🔹 Как связаться с поддержкой?</b>\n"
        "Нажмите «Техподдержка» в меню помощи."
    )
    
    await callback.message.answer(
        text=faq_text,
        reply_markup=get_main_menu_keyboard(),
    )
    
    await callback.answer()


@router.callback_query(F.data == "help_support")
async def help_support(callback: types.CallbackQuery):
    """Техподдержка."""
    support_text = (
        "💬 <b>Техподдержка Nemo VPN</b>\n\n"
        "Наша команда готова помочь вам!\n\n"
        "📧 <b>Способы связи:</b>\n"
        "• Напишите нам: @nedopekin\n\n"
        "⏰ <b>Время работы:</b>\n"
        "Круглосуточно\n\n"
        "📝 <b>Перед обращением укажите:</b>\n"
        "1. Описание проблемы\n"
        "2. Скриншот ошибки (если есть)\n\n"
        "Обычно мы отвечаем в течение 15 минут!"
    )

    # Клавиатура с кнопкой на личку
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Написать в поддержку", url="https://t.me/nedopekin")
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    builder.adjust(1)

    await callback.message.answer(
        text=support_text,
        reply_markup=builder.as_markup(),
    )

    await callback.answer()