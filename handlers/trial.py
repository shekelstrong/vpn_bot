"""
Обработчик пробной подписки (триала).
Выдача доступа на 24 часа с лимитом 1GB.
"""
import io
import qrcode
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from database.models import User
from keyboards.inline import get_main_menu_keyboard
from services.marzban_api import marzban_service
from config import settings, get_db_setting

router = Router()


def generate_qr(data: str) -> BufferedInputFile:
    """Генерация QR-кода в памяти и возврат в виде файла для Telegram."""
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="qr.png")


async def send_trial_info(message: types.Message | types.CallbackQuery, subscription_url: str):
    """Отправить Умную ссылку для пробной подписки."""
    if isinstance(message, types.CallbackQuery):
        message = message.message

    qr_file = generate_qr(subscription_url)

    success_text = (
        f"✅ <b>Ваш пробный период активен!</b>\n\n"
        "🔗 <b>Ваша ссылка на подписку:</b>\n"
        f"<code>{subscription_url}</code>\n"
        "<i>(Нажмите на ссылку, чтобы скопировать)</i>\n\n"
        "📱 <b>Инструкция по подключению (V2Box):</b>\n"
        "1. Установите <b>V2Box</b> (<a href='https://apps.apple.com/us/app/v2box-v2ray-client/id6446814690'>iOS</a> / <a href='https://play.google.com/store/apps/details?id=dev.hexasoftware.v2box'>Android</a>)\n"
        "2. В приложении перейдите во вкладку <b>Configs</b>.\n"
        "3. Нажмите <b>«+»</b> → <b>«Import V2ray URL from Clipboard»</b>.\n"
        "4. На главной (Home) нажмите <b>«Slide to Connect»</b>.\n\n"
        "📷 <b>Альтернативный способ (QR-код):</b>\n"
        "Вы можете отсканировать QR-код из этого сообщения через приложение V2Box на вашем устройстве.\n\n"
        "⏰ <b>Ваш триал действует 24 часа!</b>\n\n"
        "⚠️ Не передавайте ссылку третьим лицам!\n\n"
        "Если возникнут проблемы с подключением, напишите в поддержку по кнопке «Помощь 🆘» из главного меню."
    )

    await message.answer_photo(
        photo=qr_file,
        caption=success_text,
        reply_markup=get_main_menu_keyboard(show_trial=False)
    )


@router.callback_query(F.data == "trial")
@router.message(Command("trial"))
@router.message(F.text.startswith("Пробная подписка"))
async def show_trial(callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession):
    """Показать информацию о пробной подписке (триале)."""

    if isinstance(callback_or_message, types.CallbackQuery):
        callback = callback_or_message
        message = callback.message
        user_id = callback.from_user.id
        await callback.answer()
    else:
        message = callback_or_message
        callback = None
        user_id = message.from_user.id

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        await message.answer("❌ Пользователь не найден. Нажмите /start")
        return

    # Проверяем, есть ли активная подписка
    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()

    if has_subscription and user.is_trial_used:
        # У пользователя уже активирован триал - показываем ключ
        if not user.marzban_username:
            await message.answer(
                "❌ Ошибка: у вас нет VPN-аккаунта.\n\n"
                "Обратитесь в поддержку.",
                reply_markup=get_main_menu_keyboard(show_trial=False)
            )
            return

        try:
            marzban_data = await marzban_service.get_user(user.marzban_username)
            if not marzban_data:
                # Аккаунт удалён в Marzban - создаём заново с параметрами триала
                trial_hours = await get_db_setting(session, "trial_hours", "24")
                trial_limit = await get_db_setting(session, "trial_data_limit", "1")

                marzban_data = await marzban_service.create_user(
                    tg_id=user_id,
                    username=user.username,
                    expire_hours=int(trial_hours),
                    data_limit_gb=int(trial_limit)
                )
                user.marzban_username = marzban_data.get("username")
                await session.commit()
                logger.info(f"Пересоздан аккаунт Marzban для пользователя {user_id} с триалом")

            subscription_url = marzban_data.get("subscription_url", "")
            if subscription_url and subscription_url.startswith("/"):
                base_url = settings.MARZBAN_URL.rstrip("/")
                subscription_url = f"{base_url}{subscription_url}"

            if subscription_url:
                await send_trial_info(message, subscription_url)
            else:
                await message.answer(
                    "❌ Не удалось получить ссылку на подписку.\n\n"
                    "Пожалуйста, обратитесь в поддержку.",
                    reply_markup=get_main_menu_keyboard(show_trial=False)
                )
        except Exception as e:
            logger.error(f"Ошибка получения ссылки для {user_id}: {e}")
            await message.answer(
                "❌ Произошла ошибка при получении ссылки.\n\n"
                "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                reply_markup=get_main_menu_keyboard(show_trial=False)
            )

    elif has_subscription and not user.is_trial_used:
        # У пользователя платная подписка, но триал ещё не использован
        trial_hours = await get_db_setting(session, "trial_hours", "24")
        trial_limit = await get_db_setting(session, "trial_data_limit", "1")
        text = (
            f"🎁 <b>Бесплатный триал Nemo VPN</b>\n\n"
            f"Попробуйте наш VPN-сервис бесплатно в течение {trial_hours} часов!\n\n"
            "✨ <b>Что вы получите:</b>\n"
            f"▫️ {trial_hours} часов доступа\n"
            f"▫️ {trial_limit} GB трафика\n"
            "▫️ Доступ ко всем серверам\n"
            "▫️ Протокол VLESS Reality\n\n"
            "⚠️ Триал доступен только один раз!\n\n"
            "Готовы попробовать? Нажмите «Активировать триал»"
        )
        await message.answer(
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Активировать триал", callback_data="activate_trial")],
                [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
            ])
        )

    elif user.is_trial_used:
        # Триал уже использован, подписки нет
        price = await get_db_setting(session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB))
        text = (
            "📦 <b>Пробная подписка</b>\n\n"
            "❌ Вы уже использовали пробный период.\n\n"
            "Вы можете оформить платную подписку\n"
            "и продолжить пользоваться Nemo VPN без ограничений.\n\n"
            f"💳 <b>Стоимость:</b> {price}₽/месяц"
        )
        await message.answer(
            text=text,
            reply_markup=get_main_menu_keyboard(show_trial=False)
        )

    else:
        # Триал ещё не использован, подписки нет - предлагаем активировать
        trial_hours = await get_db_setting(session, "trial_hours", "24")
        trial_limit = await get_db_setting(session, "trial_data_limit", "1")
        text = (
            f"🎁 <b>Бесплатный триал Nemo VPN</b>\n\n"
            f"Попробуйте наш VPN-сервис бесплатно в течение {trial_hours} часов!\n\n"
            "✨ <b>Что вы получите:</b>\n"
            f"▫️ {trial_hours} часов доступа\n"
            f"▫️ {trial_limit} GB трафика\n"
            "▫️ Доступ ко всем серверам\n"
            "▫️ Протокол VLESS Reality\n\n"
            "⚠️ Триал доступен только один раз!\n\n"
            "Готовы попробовать? Нажмите «Активировать триал»"
        )
        await message.answer(
            text=text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Активировать триал", callback_data="activate_trial")],
                [InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_main")]
            ])
        )


@router.callback_query(F.data == "activate_trial")
async def activate_trial(callback: types.CallbackQuery, session: AsyncSession):
    """Активировать бесплатный триал для пользователя."""
    user_id = callback.from_user.id
    await callback.answer("⏳ Активация триала...")

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        await callback.message.answer("❌ Пользователь не найден")
        return

    if user.is_trial_used:
        await callback.message.answer(
            "❌ Вы уже использовали пробный период.\n\n"
            "Оформите подписку для продолжения работы с VPN."
        )
        return

    if user.expire_date and user.expire_date > datetime.utcnow():
        await callback.message.answer(
            "❌ У вас уже есть активная подписка.\n\n"
            "Сначала дождитесь её окончания."
        )
        return

    try:
        trial_hours = await get_db_setting(session, "trial_hours", "24")
        trial_limit = await get_db_setting(session, "trial_data_limit", "1")

        marzban_data = await marzban_service.create_user(
            tg_id=user_id,
            username=user.username,
            expire_hours=int(trial_hours),
            data_limit_gb=int(trial_limit)
        )

        user.marzban_username = marzban_data.get("username")
        user.is_trial_used = True
        user.expire_date = datetime.utcnow() + timedelta(hours=int(trial_hours))
        await session.commit()

        subscription_url = marzban_data.get("subscription_url", "")
        if subscription_url and subscription_url.startswith("/"):
            base_url = settings.MARZBAN_URL.rstrip("/")
            subscription_url = f"{base_url}{subscription_url}"

        if not subscription_url:
            await callback.message.answer("❌ Ошибка генерации ссылки сервером.")
            return

        await send_trial_info(callback.message, subscription_url)

        logger.info(f"Активирован триал для пользователя {user_id}")

    except Exception as e:
        logger.error(f"Ошибка активации триала для {user_id}: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при активации триала.\n\n"
            "Пожалуйста, попробуйте позже или обратитесь в поддержку."
        )