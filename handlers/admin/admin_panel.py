"""
Обработчик админ-панели.
Управление пользователями, статистика, рассылки.
"""

import asyncio
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from loguru import logger

from database.models import User, Transaction, PaymentInvoice
from database.engine import get_session_factory
from keyboards.inline import (
    get_admin_keyboard,
    get_admin_user_search_keyboard,
    get_yes_no_keyboard,
    get_main_menu_keyboard,
    get_back_keyboard,
)
from utils.states import AdminPanel
from config import settings

router = Router()


def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором."""
    return user_id in settings.admin_ids_list


@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Открыть админ-панель."""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        logger.warning(f"Попытка доступа к админке от неавторизованного пользователя {user_id}")
        await message.answer("❌ У вас нет доступа к админ-панели.")
        return
    
    await message.answer(
        text="🔧 <b>Админ-панель Nemo VPN</b>\n\n"
             "Выберите действие:",
        reply_markup=get_admin_keyboard(),
    )
    
    logger.info(f"Админ {user_id} открыл админ-панель")


@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    """Показать админ-панель."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="🔧 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
    )
    
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery, session: AsyncSession):
    """Показать статистику."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    try:
        # Общая статистика пользователей
        res_total = await session.execute(select(func.count(User.user_id)))
        total_users = res_total.scalar()
        
        # Активные пользователи (с подпиской)
        now = datetime.utcnow()
        res_active = await session.execute(
            select(func.count(User.user_id)).where(User.expire_date > now)
        )
        active_users = res_active.scalar()
        
        # Пользователи с триалом
        res_trial = await session.execute(
            select(func.count(User.user_id)).where(User.is_trial_used == True)
        )
        trial_users = res_trial.scalar()
        
        # Общая выручка
        res_revenue = await session.execute(
            select(func.sum(Transaction.amount)).where(Transaction.status == "paid")
        )
        total_revenue = res_revenue.scalar() or 0
        
        # Активные счета
        res_invoices = await session.execute(
            select(func.count(PaymentInvoice.id)).where(
                PaymentInvoice.status == "pending"
            )
        )
        pending_invoices = res_invoices.scalar()
        
        # Рефералы
        res_refs = await session.execute(
            select(func.count(User.user_id)).where(User.referrer_id.isnot(None))
        )
        users_with_referrals = res_refs.scalar()
        
        stats_text = (
            "📊 <b>Статистика Nemo VPN</b>\n\n"
            
            f"👥 <b>Пользователи:</b>\n"
            f"• Всего: {total_users}\n"
            f"• Активные: {active_users}\n"
            f"• С триалом: {trial_users}\n"
            f"• С рефералами: {users_with_referrals}\n\n"
            
            f"💰 <b>Финансы:</b>\n"
            f"• Общая выручка: {total_revenue:.2f}₽\n"
            f"• Активных счетов: {pending_invoices}\n\n"
            
            f"📈 <b>Конверсия:</b>\n"
            f"• Активные/Всего: {(active_users/total_users*100) if total_users else 0:.1f}%\n"
        )
        
        await callback.message.edit_text(
            text=stats_text,
            reply_markup=get_admin_keyboard(),
        )
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await callback.answer("❌ Ошибка при получении статистики", show_alert=True)
    
    await callback.answer()


@router.callback_query(F.data == "admin_users")
async def admin_users(callback: types.CallbackQuery):
    """Меню управления пользователями."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="👥 <b>Управление пользователями</b>\n\n"
             "Найдите пользователя для управления:",
        reply_markup=get_admin_user_search_keyboard(),
    )
    
    await callback.answer()


@router.callback_query(F.data == "admin_find_by_id")
async def admin_find_by_id(callback: types.CallbackQuery, state: FSMContext):
    """Поиск пользователя по ID."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminPanel.waiting_for_user_search)
    await state.update_data(search_type="id")
    
    await callback.message.answer(
        "🔍 Введите Telegram ID пользователя:\n\n"
        "Или нажмите /cancel для отмены."
    )
    
    await callback.answer()


@router.callback_query(F.data == "admin_find_by_vk_id")
async def admin_find_by_vk_id(callback: types.CallbackQuery, state: FSMContext):
    """Поиск пользователя по VK ID."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminPanel.waiting_for_user_search)
    await state.update_data(search_type="vk_id")
    
    await callback.message.answer(
        "🔍 Введите VK ID пользователя (число):\n\n"
        "Или нажмите /cancel для отмены."
    )
    
    await callback.answer()


@router.callback_query(F.data == "admin_find_by_username")
async def admin_find_by_username(callback: types.CallbackQuery, state: FSMContext):
    """Поиск пользователя по username."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminPanel.waiting_for_user_search)
    await state.update_data(search_type="username")
    
    await callback.message.answer(
        "🔍 Введите username пользователя (без @):\n\n"
        "Или нажмите /cancel для отмены."
    )
    
    await callback.answer()




@router.callback_query(F.data == "admin_find_by_vk_link")
async def admin_find_by_vk_link(callback: types.CallbackQuery, state: FSMContext):
    """Поиск пользователя по VK ссылке (screen name)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminPanel.waiting_for_user_search)
    await state.update_data(search_type="vk_link")
    
    await callback.message.answer(
        "🔍 Введите ссылку на VK пользователя:\n\n"
        "Примеры:\n"
        "• vk.com/vasily_nedopekin\n"
        "• vasily_nedopekin\n"
        "• 731577540 (VK ID)\n\n"
        "Или нажмите /cancel для отмены."
    )
    
    await callback.answer()

@router.message(AdminPanel.waiting_for_user_search)
async def process_user_search(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка поиска пользователя."""
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    search_type = data.get("search_type", "id")
    search_value = message.text.strip()
    
    try:
        if search_type == "id":
            user_id = int(search_value)
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
        elif search_type == "vk_id":
            vk_id = int(search_value)
            result = await session.execute(
                select(User).where(User.vk_id == vk_id)
            )
        elif search_type == "vk_link":
            # Parse VK link: vk.com/username, @username, or just username
            import httpx
            import re
            
            # Extract screen name from URL
            vk_pattern = r"(?:vk\.com/|@)?([a-zA-Z0-9_.]+)"
            match = re.search(vk_pattern, search_value)
            
            if match:
                screen_name = match.group(1)
                # Try as numeric VK ID first
                try:
                    vk_id_int = int(screen_name)
                    result = await session.execute(
                        select(User).where(User.vk_id == vk_id_int)
                    )
                    user = result.scalar_one_or_none()
                    if not user:
                        await message.answer(f"❌ Пользователь с VK ID {vk_id_int} не найден.\n\nПопробуйте ещё раз или нажмите /cancel.")
                        return
                except ValueError:
                    # Resolve screen name via VK API
                    vk_token = settings.VK_TOKEN
                    if not vk_token:
                        await message.answer("❌ VK_TOKEN не настроен. Невозможно разрешить ссылку.")
                        await state.clear()
                        return
                    
                    try:
                        async with httpx.AsyncClient(timeout=10) as client:
                            resp = await client.get(
                                "https://api.vk.com/method/utils.resolveScreenName",
                                params={"screen_name": screen_name, "access_token": vk_token, "v": "5.199"}
                            )
                            data = resp.json()
                            if "response" in data and data["response"]:
                                vk_id_int = data["response"]["object_id"]
                                result = await session.execute(
                                    select(User).where(User.vk_id == vk_id_int)
                                )
                            else:
                                await message.answer(f"❌ VK пользователь \"{screen_name}\" не найден.\n\nПопробуйте ещё раз или нажмите /cancel.")
                                return
                    except Exception as e:
                        logger.error(f"VK resolve error: {e}")
                        await message.answer(f"❌ Ошибка при поиске VK пользователя.\n\nПопробуйте ещё раз или нажмите /cancel.")
                        return
            else:
                await message.answer("❌ Неверный формат VK ссылки.\n\nВведите vk.com/username или числовой VK ID.")
                return
        else:
            username = search_value.lstrip("@")
            result = await session.execute(
                select(User).where(User.username == username)
            )
        
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer(
                f"❌ Пользователь не найден.\n\n"
                f"Попробуйте ещё раз или нажмите /cancel."
            )
            return
        
        # Получаем информацию о пользователе
        user_info = (
            f"👤 <b>Информация о пользователе</b>\n\n"
            f"<b>ID:</b> <code>{user.user_id}</code>\n"
            f"<b>Username:</b> @{user.username if user.username else 'N/A'}\n"
            f"<b>Marzban (TG):</b> <code>{user.marzban_username or 'N/A'}</code>\n"
            f"<b>Marzban (VK):</b> <code>{user.marzban_username_vk or 'N/A'}</code>\n"
            f"<b>VK ID:</b> <code>{user.vk_id or 'N/A'}</code>\n"
            f"<b>Platform:</b> {user.platform or 'tg'}\n\n"
            f"<b>Баланс:</b> {user.balance:.2f}₽\n"
            f"<b>Реф. баланс:</b> {user.referral_balance:.2f}₽\n"
            f"<b>Триал:</b> {'Использован' if user.is_trial_used else 'Не использован'}\n\n"
        )
        
        if user.expire_date:
            days_left = (user.expire_date - datetime.utcnow()).days
            if days_left > 0:
                user_info += f"<b>Подписка:</b> Активна ({days_left} дн.)\n"
                user_info += f"<b>Истекает:</b> {user.expire_date.strftime('%d.%m.%Y %H:%M')}\n"
            else:
                user_info += f"<b>Подписка:</b> Истекла\n"
                user_info += f"<b>Дата:</b> {user.expire_date.strftime('%d.%m.%Y %H:%M')}\n"
        else:
            user_info += "<b>Подписка:</b> Отсутствует\n"
        
        if user.referrer_id:
            user_info += f"<b>Реферер:</b> <code>{user.referrer_id}</code>\n"
        
        referrals_res = await session.execute(
            select(func.count(User.user_id)).where(User.referrer_id == user.user_id)
        )
        referral_count = referrals_res.scalar()
        user_info += f"<b>Рефералов:</b> {referral_count}\n"
        
        await message.answer(
            text=user_info,
            reply_markup=get_yes_no_keyboard(
                yes_callback=f"admin_gift_sub:{user.user_id}",
                no_callback="admin_users",
                question="Выдать подписку?"
            ),
        )
        
        await state.clear()
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID.\n\n"
            "Введите числовое значение или нажмите /cancel."
        )
    except Exception as e:
        logger.error(f"Ошибка поиска пользователя: {e}")
        await message.answer("❌ Произошла ошибка при поиске.")
        await state.clear()


@router.callback_query(F.data.startswith("admin_gift_sub:"))
async def admin_gift_sub_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало процесса выдачи подарочной подписки."""
    if not is_admin(callback.from_user.id):
        return
    
    user_id = callback.data.split(":")[1]
    await state.update_data(gift_user_id=user_id)
    await state.set_state(AdminPanel.waiting_for_gift_days)
    
    await callback.message.answer(
        "🎁 Введите количество дней подписки:\n\n"
        "Или нажмите /cancel для отмены."
    )
    
    await callback.answer()


@router.message(AdminPanel.waiting_for_gift_days)
async def process_gift_days(message: types.Message, state: FSMContext, session: AsyncSession):
    """Обработка выдачи подарочной подписки."""
    if not is_admin(message.from_user.id):
        return
    
    try:
        days = int(message.text.strip())
        
        if days <= 0 or days > 365:
            await message.answer(
                "❌ Количество дней должно быть от 1 до 365.\n\n"
                "Введите значение ещё раз."
            )
            return
        
        data = await state.get_data()
        gift_user_id = int(data.get("gift_user_id"))
        
        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.user_id == gift_user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return
        
        # Продлеваем подписку
        if user.expire_date and user.expire_date > datetime.utcnow():
            new_expire = user.expire_date + timedelta(days=days)
        else:
            new_expire = datetime.utcnow() + timedelta(days=days)
        
        user.expire_date = new_expire
        
        # Если есть Marzban пользователь, продлеваем там
        if user.marzban_username:
            from services.marzban_api import marzban_service
            try:
                await marzban_service.update_user_expiry(
                    user.marzban_username,
                    days
                )
            except Exception as e:
                logger.error(f"Ошибка продления в Marzban: {e}")
        
        await session.commit()
        
        await message.answer(
            f"✅ Подписка продлена!\n\n"
            f"Пользователь: <code>{gift_user_id}</code>\n"
            f"Дней: {days}\n"
            f"Новая дата истечения: {new_expire.strftime('%d.%m.%Y %H:%M')}"
        )
        
        # Уведомляем пользователя
        try:
            await message.bot.send_message(
                chat_id=gift_user_id,
                text=(
                    f"🎁 <b>Вам подарена подписка!</b>\n\n"
                    f"Администратор добавил {days} дней к вашей подписке.\n\n"
                    f"Новая дата истечения: {new_expire.strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"Спасибо за использование Nemo VPN! 💙"
                ),
            )
        except Exception:
            pass
        
        await state.clear()
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат.\n\n"
            "Введите число дней или нажмите /cancel."
        )
    except Exception as e:
        logger.error(f"Ошибка выдачи подарочной подписки: {e}")
        await message.answer("❌ Произошла ошибка.")
        await state.clear()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(AdminPanel.waiting_for_broadcast_message)
    
    await callback.message.answer(
        "📢 <b>Рассылка сообщений</b>\n\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям.\n\n"
        "Поддерживаются: текст, фото, видео, документы.",
        reply_markup=get_back_keyboard("admin_panel")
    )
    
    await callback.answer()


@router.message(AdminPanel.waiting_for_broadcast_message)
async def process_broadcast(message: types.Message, state: FSMContext):
    """Обработка рассылки - сохранение сообщения и показ предпросмотра."""
    if not is_admin(message.from_user.id):
        return
    
    # Сохраняем информацию о сообщении
    message_type = "text"
    photo_file_id = None
    video_file_id = None
    document_file_id = None
    
    if message.photo:
        message_type = "photo"
        photo_file_id = message.photo[-1].file_id
    elif message.video:
        message_type = "video"
        video_file_id = message.video.file_id
    elif message.document:
        message_type = "document"
        document_file_id = message.document.file_id
    
    await state.update_data(
        message_type=message_type,
        text=message.text or message.caption or "",
        photo_file_id=photo_file_id,
        video_file_id=video_file_id,
        document_file_id=document_file_id,
        reply_markup=None
    )

    # Показываем предпросмотр
    preview_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить всем", callback_data="broadcast_confirm_send")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="broadcast_cancel")]
    ])

    # Отправляем копию сообщения как предпросмотр
    try:
        if message_type == "photo":
            await message.copy_to(chat_id=message.chat.id, reply_markup=preview_keyboard)
        elif message_type == "video":
            await message.copy_to(chat_id=message.chat.id, reply_markup=preview_keyboard)
        elif message_type == "document":
            await message.copy_to(chat_id=message.chat.id, reply_markup=preview_keyboard)
        else:
            await message.answer(
                text=message.text or "Текстовое сообщение",
                reply_markup=preview_keyboard
            )
    except Exception as e:
        logger.error(f"Ошибка при создании предпросмотра: {e}")
        await message.answer(
            text="⚠️ Не удалось создать предпросмотр, но сообщение будет отправлено.",
            reply_markup=preview_keyboard
        )

    await state.set_state(AdminPanel.waiting_for_broadcast_confirm)


@router.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Отмена рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.clear()
    await callback.message.edit_text(
        "❌ Рассылка отменена.",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "broadcast_confirm_send")
async def broadcast_confirm_send(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    """Подтверждение и отправка рассылки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.answer("⏳ Начинаю рассылку...")

    # Получаем данные из состояния
    data = await state.get_data()
    message_type = data.get("message_type", "text")
    text = data.get("text", "")
    photo_file_id = data.get("photo_file_id")
    video_file_id = data.get("video_file_id")
    document_file_id = data.get("document_file_id")

    # Получаем всех пользователей
    result = await session.execute(select(User.user_id))
    user_ids = [row[0] for row in result.all()]

    success_count = 0
    fail_count = 0

    try:
        # Отправляем сообщение каждому пользователю
        for user_id in user_ids:
            try:
                if message_type == "photo" and photo_file_id:
                    await callback.message.bot.send_photo(
                        chat_id=user_id,
                        photo=photo_file_id,
                        caption=text,
                        parse_mode="HTML"
                    )
                elif message_type == "video" and video_file_id:
                    await callback.message.bot.send_video(
                        chat_id=user_id,
                        video=video_file_id,
                        caption=text,
                        parse_mode="HTML"
                    )
                elif message_type == "document" and document_file_id:
                    await callback.message.bot.send_document(
                        chat_id=user_id,
                        document=document_file_id,
                        caption=text,
                        parse_mode="HTML"
                    )
                else:
                    await callback.message.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode="HTML"
                    )
                success_count += 1
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
                fail_count += 1

            # Небольшая задержка для избежания лимитов
            await asyncio.sleep(0.05)

        await callback.message.edit_text(
            f"✅ Рассылка завершена!\n\n"
            f"Всего пользователей: {len(user_ids)}\n"
            f"Успешно: {success_count}\n"
            f"Не удалось: {fail_count}",
            reply_markup=get_admin_keyboard()
        )

        logger.info(f"Админ {callback.from_user.id} провел рассылку: {success_count} успешно, {fail_count} неудачно")

    except Exception as e:
        logger.error(f"Ошибка рассылки: {e}")
        await callback.message.edit_text(
            "❌ Произошла ошибка при рассылке.",
            reply_markup=get_admin_keyboard()
        )

    await state.clear()





@router.callback_query(F.data == "admin_close")
async def admin_close(callback: types.CallbackQuery):
    """Закрыть админ-панель."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        text="🔒 Админ-панель закрыта.",
        reply_markup=get_main_menu_keyboard(),
    )
    
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Отмена текущего действия."""
    await state.clear()
    await message.answer(
        "❌ Отменено.\n\nВыберите действие:",
        reply_markup=get_admin_keyboard() if is_admin(message.from_user.id) else get_main_menu_keyboard(),
    )


@router.message(Command("webhook_check"))
async def cmd_webhook_check(message: types.Message):
    """Проверить текущий вебхук CryptoBot."""
    from services.payment_crypto import crypto_bot_service
    
    await message.answer("⏳ Проверка вебхука CryptoBot...")
    
    try:
        webhook_info = await crypto_bot_service.get_webhook_info()
        
        if webhook_info:
            webhook_url = webhook_info.get("url", "Не установлен")
            text = (
                f"🪙 <b>Информация о вебхуке CryptoBot</b>\n\n"
                f"🔗 URL: <code>{webhook_url}</code>\n\n"
                f"<i>Если URL пустой или неправильный, используйте /webhook_set</i>"
            )
        else:
            text = "❌ Не удалось получить информацию о вебхуке."
        
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка проверки вебхука: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("webhook_set"))
async def cmd_webhook_set(message: types.Message):
    """Установить вебхук CryptoBot."""
    from services.payment_crypto import crypto_bot_service
    
    webhook_url = f"https://{settings.BASE_URL}/cryptopay"
    
    await message.answer(f"⏳ Установка вебхука на URL: {webhook_url}...")
    
    try:
        result = await crypto_bot_service.set_webhook(webhook_url)
        
        if result.get("ok"):
            text = (
                f"✅ <b>Вебхук успешно установлен!</b>\n\n"
                f"🔗 URL: <code>{webhook_url}</code>\n\n"
                f"<i>Теперь CryptoBot будет отправлять уведомления об оплатах на этот URL.</i>"
            )
        else:
            text = f"❌ Ошибка: {result}"
        
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка установки вебхука: {e}")
        await message.answer(f"❌ Ошибка: {e}")
