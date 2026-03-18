"""
Обработчик раздела помощи.
Инструкции по настройке Hiddify и FAQ.
"""

from aiogram import Router, F, types
from aiogram.filters import Command
from loguru import logger

from keyboards.inline import (
    get_help_keyboard,
    get_hiddify_instruction_keyboard,
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
        "📱 <b>Как настроить Hiddify</b>\n"
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


@router.callback_query(F.data == "help_hiddify")
async def help_hiddify(callback: types.CallbackQuery):
    """Инструкция по настройке Hiddify."""
    instruction_text = (
        "📱 <b>Настройка Hiddify для Nemo VPN</b>\n\n"
        "<b>Шаг 1: Скачайте приложение</b>\n"
        "Hiddify доступен для всех платформ:\n"
        "• Android: Google Play Store\n"
        "• iOS: App Store\n"
        "• Windows: GitHub Releases\n"
        "• macOS: App Store / GitHub\n\n"
        "<b>Шаг 2: Получите ссылку</b>\n"
        "В разделе «Мой профиль» нажмите «Получить ссылку 🔗»\n"
        "Скопируйте ссылку на подписку.\n\n"
        "<b>Шаг 3: Добавьте профиль</b>\n"
        "1. Откройте Hiddify\n"
        "2. Нажмите «+» или «Add Profile»\n"
        "3. Выберите «Import from Clipboard»\n"
        "4. Подтвердите добавление\n\n"
        "<b>Шаг 4: Подключитесь</b>\n"
        "1. Выберите сервер из списка\n"
        "2. Нажмите кнопку подключения\n"
        "3. Готово! VPN активен 🎉\n\n"
        "⚠️ <b>Важно:</b>\n"
        "• Не передавайте ссылку третьим лицам\n"
        "• При проблемах попробуйте обновить профиль\n"
        "• Для смены сервера выберите другой в списке"
    )
    
    await callback.message.answer(
        text=instruction_text,
        reply_markup=get_hiddify_instruction_keyboard(),
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
        
        "<b>🔹 Что будет, когда подписка истечет?</b>\n"
        "Доступ к VPN прекратится. Для возобновления\n"
        "нужно оформить новую подписку.\n\n"
        
        "<b>🔹 Как работает реферальная программа?</b>\n"
        "Приглашайте друзей и получайте проценты с их покупок:\n"
        "• 1 уровень — 15%\n"
        "• 2 уровень — 10%\n"
        "• 3 уровень — 5%\n\n"
        
        "<b>🔹 Какие способы оплаты доступны?</b>\n"
        "• CryptoBot (USDT, TON, Bitcoin)\n"
        "• Банковские карты РФ (через Platega)\n\n"
        
        "<b>🔹 Что такое VLESS Reality?</b>\n"
        "Современный протокол, маскирующий трафик\n"
        "под обычный HTTPS. Обходит любые блокировки.\n\n"
        
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
