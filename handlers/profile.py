"""
Обработчик профиля пользователя.

ИЗМЕНЕНИЯ:
1. Все упоминания V2Box убраны, заменены на Happ
2. Добавлены ссылки на Happ для всех платформ (iOS, Android, Windows, macOS, Linux)
3. Убран отдельный ключ маршрутизации — маршрутизация подключается автоматически через подписку (Happ >= 1.63.1)
4. Добавлена кнопка перегенерации ключа (regenerate_key)
5. Перегенерация: старая ссылка перестаёт работать, срок и ГБ сохраняются
"""

import io
import qrcode
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from loguru import logger
from database.models import User
from keyboards.inline import get_profile_keyboard, get_main_menu_keyboard
from services.xui_api import xui_service as marzban_service
from config import settings, get_db_setting
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Маршрутизация Happ — динамические ссылки через sub-service
ROUTE_HAPP_STANDARD = "https://sub.nemovpn.online/happ/standard"
ROUTE_HAPP_PREMIUM = "https://sub.nemovpn.online/happ/premium"
ROUTE_HAPP = ROUTE_HAPP_STANDARD

router = Router()


def format_bytes(bytes_value: int) -> str:
    if bytes_value is None:
        return "Безлимитно"
    if bytes_value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    value = float(bytes_value)
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1
    return f"{value:.2f} {units[unit_index]}"


def generate_qr(data: str) -> BufferedInputFile:
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return BufferedInputFile(bio.read(), filename="qr.png")


async def send_subscription_info(
    message: types.Message | types.CallbackQuery,
    subscription_url: str,
    vless_link: str = "",
    user=None,
):
    """Отправить ссылку для платной подписки."""
    if isinstance(message, types.CallbackQuery):
        message = message.message

    qr_file = generate_qr(subscription_url or vless_link)

    success_text = (
        f"✅ <b>Ваша подписка активна!</b>\n\n"
        f"🔗 <b>Ваша ссылка на подписку:</b>\n"
        f"<code>{subscription_url}</code>\n"
        f"<i>(Нажмите на ссылку, чтобы скопировать)</i>\n\n"
        f"📱 <b>Инструкция по подключению:</b>\n"
        f"1. Установите приложение <b>Happ</b> для вашего устройства:\n"
        f"• <b>iOS / macOS:</b> <a href='https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'>App Store</a>\n"
        f"• <b>Android:</b> <a href='https://play.google.com/store/apps/details?id=com.happproxy'>Google Play</a>\n"
        f"• <b>Windows:</b> <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe'>Скачать</a>\n"
        f"• <b>Linux:</b> <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest'>GitHub Releases</a>\n"
        f"2. Скопируйте ссылку на подписку (выше).\n"
        f"3. Откройте Happ, нажмите <b>«+»</b> и выберите <b>«Import from Clipboard»</b>.\n"
        f"4. Нажмите кнопку подключения на главном экране.\n\n"
    )

    # Маршрутизация: для всех — автопримечание, для premium — кнопка
    is_premium = False
    if user and hasattr(user, "tier") and user.tier == "premium":
        is_premium = True
    if user and hasattr(user, "expire_premium") and user.expire_premium:
        from datetime import datetime as _dt
        if user.expire_premium > _dt.utcnow():
            is_premium = True

    if is_premium:
        success_text += "Для корректной работы российских сервисов напрямую, нажмите кнопку:\n\n"
        success_text += "⚠️ Не передавайте ссылку третьим лицам!"

        route_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Настроить маршрутизацию Happ", url=ROUTE_HAPP_PREMIUM)]
        ])
        await message.answer(
            text=success_text,
            disable_web_page_preview=True,
            reply_markup=route_keyboard,
            parse_mode="HTML",
        )
    else:
        success_text += "🔄 <b>Маршрутизация российской трафика подключается автоматически</b> при добавлении подписки в Happ.\n\n"
        success_text += "⚠️ Не передавайте ссылку третьим лицам! Если возникнут проблемы с подключением, напишите в поддержку."

        await message.answer(
            text=success_text,
            disable_web_page_preview=True,
            reply_markup=get_main_menu_keyboard(show_trial=False),
            parse_mode="HTML",
        )

    await message.answer_photo(photo=qr_file, caption="Ваш QR-код для подключения 👆")


@router.callback_query(F.data == "profile")
@router.message(Command("profile"))
@router.message(F.text.startswith("Мой профиль"))
async def show_profile(
    callback_or_message: types.CallbackQuery | types.Message, session: AsyncSession
):
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
        await message.answer("Пользователь не найден. Нажмите /start")
        return

    marzban_data = None
    if user.marzban_username:
        try:
            marzban_data = await marzban_service.get_user(user.marzban_username)
        except Exception as e:
            logger.error(f"Ошибка получения данных из Marzban: {e}")

    profile_text = f"👤 <b>Профиль пользователя</b>\n\n"
    profile_text += f"<b>ID:</b> <code>{user.user_id}</code>\n"
    if user.username:
        profile_text += f"<b>Username:</b> @{user.username}\n"
    profile_text += f"🎁 <b>Реферальный баланс:</b> {user.referral_balance:.2f} ₽\n"

    # Показываем раздельные сроки
    now = datetime.utcnow()
    if user.expire_standard and user.expire_standard > now:
        days_std = (user.expire_standard - now).days
        profile_text += f"\n🛡 <b>Стандартный VPN:</b> активен ({days_std} дн., до {user.expire_standard.strftime('%d.%m.%Y')})\n"
    elif user.expire_standard:
        profile_text += f"\n🛡 <b>Стандартный VPN:</b> истёк\n"

    if user.expire_premium and user.expire_premium > now:
        days_vip = (user.expire_premium - now).days
        profile_text += f"🚀 <b>VIP (обход списков):</b> активен ({days_vip} дн., до {user.expire_premium.strftime('%d.%m.%Y')})\n"
    elif user.expire_premium:
        profile_text += f"🚀 <b>VIP (обход списков):</b> истёк\n"

    if not user.expire_standard and not user.expire_premium:
        if user.expire_date and user.expire_date > now:
            days_left = (user.expire_date - now).days
            profile_text += f"\n✅ <b>Подписка активна</b> ({days_left} дн.)\n"
        else:
            profile_text += "\n❌ <b>Нет активной подписки</b>\n"

    if marzban_data:
        used_traffic = marzban_data.get("used_traffic", 0)
        data_limit = marzban_data.get("data_limit", 0)
        profile_text += "\n📊 <b>Трафик:</b>\n"
        profile_text += f"Использовано: {format_bytes(used_traffic)}\n"
        if data_limit and data_limit > 0:
            remaining = data_limit - used_traffic
            profile_text += f"Осталось: {format_bytes(max(0, remaining))}\n"
            profile_text += f"Лимит: {format_bytes(data_limit)}\n"
        else:
            profile_text += "Безлимитный трафик\n"

    result = await session.execute(select(User).where(User.referrer_id == user.user_id))
    referrals = result.scalars().all()
    if referrals:
        profile_text += f"\n👥 <b>Рефералы:</b> {len(referrals)}\n"

    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()
    show_link = (
        has_subscription and user.marzban_username and (marzban_data is not None)
    )

    await message.answer(
        text=profile_text,
        reply_markup=get_profile_keyboard(
            has_subscription=bool(has_subscription), show_link=bool(show_link)
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "confirm_regenerate")
async def confirm_regenerate(callback: types.CallbackQuery, session: AsyncSession):
    """Подтверждение перегенерации ключа."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, перегенерировать", callback_data="regenerate_key")
    builder.button(text="❌ Отмена", callback_data="profile")
    builder.adjust(1)
    await callback.message.edit_text(
        "⚠️ <b>Перегенерация ключа</b>\n\n"
        "Старая ссылка перестанет работать.\n"
        "Вам придётся обновить подписку в Happ.\n\n"
        "Срок подписки и ГБ сохраняются.\n\n"
        "<b>Вы уверены?</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "regenerate_key")
async def regenerate_key(callback: types.CallbackQuery, session: AsyncSession):
    """Перегенерировать VPN ключ. Старая ссылка перестаёт работать, срок и ГБ сохраняются."""
    user_id = callback.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.marzban_username:
        await callback.answer("У вас нет активной подписки", show_alert=True)
        return

    try:
        # Сохраняем текущие данные аккаунта
        marzban_data = await marzban_service.get_user(user.marzban_username)
        if not marzban_data:
            await callback.answer(
                "Аккаунт не найден. Оформите новую подписку.", show_alert=True
            )
            return

        current_expire = marzban_data.get("expire") or 0
        current_data_limit = marzban_data.get("data_limit")
        current_ip_limit = marzban_data.get("ip_limit", 1) or 1
        current_inbounds = marzban_data.get("inbounds", {}).get(
            "vless", ["vless-reality-standard"]
        )
        current_used = marzban_data.get("used_traffic", 0) or 0

        # Вычисляем оставшиеся дни
        now = datetime.utcnow()
        current_ts = int(now.timestamp())
        if current_expire > current_ts:
            days_left = (current_expire - current_ts) // 86400 + 1
        else:
            days_left = 0

        if days_left <= 0:
            await callback.answer("Подписка истекла. Оформите новую.", show_alert=True)
            return

        # Удаляем старый аккаунт
        await marzban_service.delete_user(user.marzban_username)
        logger.info(f"Удалён аккаунт {user.marzban_username} для перегенерации")

        # Создаём новый аккаунт с теми же настройками
        new_gb = 0
        if current_data_limit and current_data_limit > 0:
            new_gb = max(0, (current_data_limit - current_used) / (1024**3))

        tier = user.tier or "standard"
        new_acc = await marzban_service.create_user(
            tg_id=user_id,
            username=user.username,
            expire_days=days_left,
            data_limit_gb=new_gb,
            tier=tier,
            device_count=current_ip_limit,
            inbounds=current_inbounds,
        )
        user.marzban_username = new_acc.get("username")
        await session.commit()

        new_sub_url = await marzban_service.get_user_subscription(new_acc.get("username", ""))
        if not new_sub_url:
            new_sub_url = new_acc.get("subscription_url", "")
            if new_sub_url and new_sub_url.startswith("/"):
                new_sub_url = f"{settings.MARZBAN_URL.rstrip('/')}{new_sub_url}"

        await callback.message.edit_text(
            f"🔄 <b>Ключ перегенерирован!</b>\n\n"
            f"Старая ссылка больше не работает.\n\n"
            f"🔗 <b>Новый ключ подписки:</b>\n"
            f"<code>{new_sub_url}</code>\n\n"
            f"Обновите подписку в Happ — старый ключ исчезнет автоматически.\n"
            f"Срок подписки и лимит ГБ сохранены.",
            parse_mode="HTML",
        )
        logger.info(f"Пользователь {user_id} перегенерировал ключ (delete+create)")

    except Exception as e:
        logger.error(f"Ошибка перегенерации ключа для {user_id}: {e}")
        await callback.answer("❌ Ошибка. Попробуйте позже.", show_alert=True)


@router.callback_query(F.data == "get_vless_link")
async def get_vless_link(callback: types.CallbackQuery, session: AsyncSession):
    user_id = callback.from_user.id
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.marzban_username:
        await callback.answer("У вас нет активной подписки", show_alert=True)
        return

    try:
        marzban_data = await marzban_service.get_user(user.marzban_username)
        if not marzban_data:
            await callback.answer(
                "Аккаунт заархивирован. Оформите новую подписку.", show_alert=True
            )
            return

        subscription_url = await marzban_service.get_user_subscription(user.marzban_username)
        if not subscription_url:
            subscription_url = marzban_data.get("subscription_url", "")
            if subscription_url and subscription_url.startswith("/"):
                base_url = settings.MARZBAN_URL.rstrip("/")
                subscription_url = f"{base_url}{subscription_url}"

        vless_link = await marzban_service.get_user_vless_link(user.marzban_username)

        if subscription_url or vless_link:
            link_text = (
                f"🔗 <b>Ваша ссылка на подписку:</b>\n"
                f"<code>{subscription_url}</code>\n\n"
                f"📱 <b>Инструкция по подключению:</b>\n"
                f"1. Установите <b>Happ</b>:\n"
                f"• <a href='https://apps.apple.com/us/app/happ-proxy-utility/id6504287215'>iOS / macOS</a>\n"
                f"• <a href='https://play.google.com/store/apps/details?id=com.happproxy'>Android</a>\n"
                f"• <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe'>Windows</a>\n"
                f"• <a href='https://github.com/Happ-proxy/happ-desktop/releases/latest'>Linux</a>\n"
                f"2. Скопируйте ссылку выше.\n"
                f"3. Откройте Happ → «+» → <b>Import from Clipboard</b>.\n"
                f"4. Выберите сервер и подключитесь!\n\n"
            )
            # Проверяем, является ли пользователь premium
            is_premium_user = False
            if user and hasattr(user, "tier") and user.tier == "premium":
                is_premium_user = True
            if user and hasattr(user, "expire_premium") and user.expire_premium:
                from datetime import datetime as _dt
                if user.expire_premium > _dt.utcnow():
                    is_premium_user = True

            if is_premium_user:
                link_text += "\nДля корректной работы российских сервисов напрямую, нажмите кнопку:"
                link_text += "\n\n⚠️ Не передавайте ссылку третьим лицам!"

                route_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔑 Настроить маршрутизацию Happ", url=ROUTE_HAPP_PREMIUM)]
                ])
                await callback.message.answer(
                    text=link_text, disable_web_page_preview=True, parse_mode="HTML",
                    reply_markup=route_keyboard,
                )
            else:
                link_text += "\n💡 Маршрутизация российской трафика подключается автоматически при добавлении подписки в Happ."
                link_text += "\n\n⚠️ Не передавайте ссылку третьим лицам!"

                await callback.message.answer(
                    text=link_text, disable_web_page_preview=True, parse_mode="HTML"
                )

            # QR
            qr_file = generate_qr(subscription_url or vless_link)
            await callback.message.answer_photo(
                photo=qr_file, caption="QR-код для быстрого подключения 👆"
            )
        else:
            await callback.message.answer(
                "❌ Не удалось получить ссылку. Обратитесь в поддержку."
            )
    except Exception as e:
        logger.error(f"Ошибка получения ссылки для {user_id}: {e}")
        await callback.message.answer("❌ Ошибка. Попробуйте позже.")

    await callback.answer()


@router.callback_query(F.data == "subscription")
async def show_subscription_callback(
    callback: types.CallbackQuery, session: AsyncSession
):
    await show_subscription(callback, session)


async def show_subscription(callback_or_message, session: AsyncSession):
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
        await message.answer("Пользователь не найден. Нажмите /start")
        return

    has_subscription = user.expire_date and user.expire_date > datetime.utcnow()

    if has_subscription:
        # Убедимся что у пользователя есть email в 3x-ui
        if not user.marzban_username:
            user.marzban_username = f"tg_{user_id}"
            await session.commit()

        try:
            # Получаем данные из 3x-ui
            marzban_data = await marzban_service.get_user(user.marzban_username)

            if not marzban_data:
                # Клиента нет в 3x-ui — создаём только если реально не найден
                now = datetime.utcnow()
                days_left = max(1, (user.expire_date - now).days) if user.expire_date else 30
                gb_limit = (user.gb_limit or 0)

                try:
                    marzban_data = await marzban_service.create_user(
                        tg_id=user_id,
                        username=user.username,
                        expire_days=days_left,
                        data_limit_gb=gb_limit,
                    )
                    user.marzban_username = marzban_data.get("username", f"tg_{user_id}")
                    await session.commit()
                except Exception as create_err:
                    logger.warning(f"create_user failed for {user_id} (may already exist): {create_err}")
                    # Повторный запрос — клиент может уже существовать
                    marzban_data = await marzban_service.get_user(user.marzban_username)
                    if not marzban_data:
                        raise create_err

            # Получаем ссылку на подписку через sub-service
            subscription_url = await marzban_service.get_user_subscription(user.marzban_username)

            # Fallback: прямая VLESS-ссылка
            if not subscription_url:
                subscription_url = await marzban_service.get_user_vless_link(user.marzban_username)

            if subscription_url:
                vless_link = await marzban_service.get_user_vless_link(user.marzban_username)
                await send_subscription_info(
                    message, subscription_url, vless_link, user
                )
            else:
                await message.answer(
                    "❌ Не удалось получить ссылку. Обратитесь в поддержку."
                )
        except Exception as e:
            logger.error(f"Ошибка получения ссылки для {user_id}: {e}", exc_info=True)
            await message.answer("❌ Ошибка. Попробуйте позже.")
    else:
        price = await get_db_setting(
            session, "subscription_price", str(settings.SUBSCRIPTION_PRICE_RUB)
        )
        text = (
            "📦 <b>Подписка</b>\n\n"
            "❌ У вас нет активной подписки.\n\n"
            f"💰 <b>Стоимость:</b> от {price} ₽/месяц"
        )
        from keyboards.inline import get_back_keyboard

        await message.answer(
            text=text,
            reply_markup=get_back_keyboard(callback_data="buy"),
            parse_mode="HTML",
        )
