"""
Обработчик раздела помощи.

ИЗМЕНЕНИЯ:
1. Все упоминания V2Box заменены на Happ
2. Кнопка «Как настроить V2Box» → «Как настроить Happ»
3. Ссылки на скачивание Happ для всех платформ
4. Убран ключ маршрутизации V2Box, оставлен только Happ
"""

from aiogram import Router, F, types
from aiogram.filters import Command
from loguru import logger

from keyboards.inline import (
    get_help_keyboard,
    get_happ_instruction_keyboard,
    get_main_menu_keyboard,
)
from config import settings

router = Router()


@router.callback_query(F.data == "help")
@router.message(Command("help"))
@router.message(F.text == "Помощь 🆘")
async def show_help(callback_or_message: types.CallbackQuery | types.Message):
    if isinstance(callback_or_message, types.CallbackQuery):
        callback = callback_or_message
        message = callback.message
        await callback.answer()
    else:
        message = callback_or_message
    
    help_text = (
        "🆘 <b>Центр помощи Nemo VPN</b>\n\n"
        "Выберите тему, которая вас интересует:\n\n"
        "📱 <b>Как настроить Happ</b>\n"
        "Пошаговая инструкция по настройке приложения\n\n"
        "❓ <b>Частые вопросы</b>\n"
        "Ответы на популярные вопросы\n\n"
        "💬 <b>Техподдержка</b>\n"
        "Связаться с оператором\n\n"
        "📜 <b>Юридические документы</b>\n"
        "Пользовательское соглашение и политика конфиденциальности"
    )
    
    await message.answer(
        text=help_text,
        reply_markup=get_help_keyboard(),
    )


@router.callback_query(F.data == "help_happ")
async def help_happ(callback: types.CallbackQuery):
    """Инструкция по настройке Happ (заменяет V2Box)."""
    instruction_text = (
        "📱 <b>Настройка Happ для Nemo VPN</b>\n\n"
        "<b>Шаг 1: Скачайте приложение</b>\n"
        "Нажмите кнопку ниже для вашей платформы.\n\n"
        "<b>Шаг 2: Получите ссылку</b>\n"
        "В разделе «Мой профиль» нажмите «Получить ссылку 🔗» и скопируйте её.\n\n"
        "<b>Шаг 3: Добавьте профиль VPN</b>\n"
        "1. Откройте приложение Happ\n"
        "2. Нажмите <b>«+»</b> для добавления нового профиля\n"
        "3. Выберите <b>«Import from Clipboard»</b>\n"
        "4. Ссылка автоматически добавится\n\n"
        "<b>Шаг 4: Подключитесь</b>\n"
        "1. Выберите добавленный профиль\n"
        "2. Нажмите кнопку подключения\n"
        "3. Готово! VPN активен 🎉\n\n"
        "🌟 <b>Для пользователей тарифа VIP (Обход списков):</b>\n"
        "После покупки VIP-тарифа вам также придёт ключ маршрутизации.\n"
        "Он настраивает умную маршрутизацию: российские сервисы "
        "(Сбер, Госуслуги, Wildberries) работают напрямую от вашего провайдера, "
        "а заблокированные (Instagram, X, ChatGPT) — через VPN.\n\n"
        "Это делает ваш серфинг невидимым для РКН! 🔒"
    )
    
    await callback.message.answer(
        text=instruction_text,
        reply_markup=get_happ_instruction_keyboard(),
    )
    
    await callback.answer()


@router.callback_query(F.data == "help_faq")
async def help_faq(callback: types.CallbackQuery):
    faq_text = (
        "❓ <b>Частые вопросы (FAQ)</b>\n\n"
        
        "<b>🔹 Как работает триал?</b>\n"
        "Триал даёт 24 часа доступа с лимитом 1GB трафика. "
        "Вы получаете оба конфига (стандартный + обход БС). "
        "Доступен один раз для каждого пользователя.\n\n"
        
        "<b>🔹 Что входит в подписку?</b>\n"
        "Одна подписка = оба конфига:\n"
        "• 🛡 Стандартный — безлимитный трафик, прямое подключение\n"
        "• 🚀 Обход БС — лимит ГБ, умная маршрутизация (РФ сайты напрямую)\n\n"
        
        "<b>🔹 Как продлить подписку?</b>\n"
        "Перейдите в «Купить подписку» и выберите тариф. "
        "Новая подписка автоматически продлит текущую.\n\n"
        
        "<b>🔹 Что такое «обход белых списков»?</b>\n"
        "Умная маршрутизация: российские сайты открываются с вашего реального IP, "
        "а заблокированные — через VPN. Это нужно, если ваш провайдер блокирует VPN "
        "и разрешает только «белые» сайты.\n\n"
        
        "<b>🔹 Как докупить ГБ?</b>\n"
        "Если вам не хватает трафика на БС-конфиге — купите доп. ГБ "
        "в разделе «Купить подписку → Докупить трафик».\n\n"
        
        "<b>🔹 Как работает реферальная программа?</b>\n"
        "Приглашайте друзей и получайте проценты с их покупок:\n"
        "• 1 уровень — 15%\n"
        "• 2 уровень — 10%\n"
        "• 3 уровень — 5%\n\n"
        
        "<b>🔹 Какие способы оплаты доступны?</b>\n"
        "• CryptoBot (USDT, TON, BTC)\n"
        "• Банковские карты РФ / СБП (через Platega)\n"
        "• Реферальный баланс\n\n"
        
        "<b>🔹 Бонус за подписку на канал?</b>\n"
        f"Подпишитесь на {settings.CHANNEL_USERNAME} — после первой покупки "
        "получите +3 дня к подписке бесплатно!\n\n"
        
        "<b>🔹 Что такое VLESS Reality?</b>\n"
        "Новейший протокол маскировки трафика. Провайдер видит ваше "
        "соединение как обычный заход на разрешённый сайт.\n\n"
        
        "<b>🔹 Какое приложение использовать?</b>\n"
        "Рекомендуем <b>Happ</b> — автоматически загружает оба конфига "
        "и настраивает маршрутизацию. Скачайте: iOS / Android / Windows.\n\n"
        
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
