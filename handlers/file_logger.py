"""
Временный обработчик для получения file_id входящих файлов.
Для использования: отправьте любой файл/видео боту, и он вернет file_id.
"""

from aiogram import Router, F, types
from loguru import logger

router = Router(name="file_logger_router")


@router.message(F.video)
async def handle_video(message: types.Message):
    """Обработка видео - вывод file_id."""
    video = message.video
    file_id = video.file_id
    file_unique_id = video.file_unique_id
    
    response_text = (
        f"📹 <b>Видео получено!</b>\n\n"
        f"<code>{file_id}</code>\n\n"
        f"🆔 Unique ID: <code>{file_unique_id}</code>\n"
        f"📁 Имя файла: {video.file_name or 'Без названия'}\n"
        f"📏 Размер: {video.file_size} байт\n"
        f"⏱ Длительность: {video.duration} сек\n\n"
        f"✅ Скопируйте <b>file_id</b> выше и используйте в коде"
    )
    
    await message.answer(text=response_text, parse_mode="HTML")
    logger.info(f"Получено видео: file_id={file_id}, user_id={message.from_user.id}")


@router.message(F.document)
async def handle_document(message: types.Message):
    """Обработка документов - вывод file_id."""
    document = message.document
    file_id = document.file_id
    file_unique_id = document.file_unique_id
    
    response_text = (
        f"📄 <b>Документ получен!</b>\n\n"
        f"<code>{file_id}</code>\n\n"
        f"🆔 Unique ID: <code>{file_unique_id}</code>\n"
        f"📁 Имя файла: {document.file_name or 'Без названия'}\n"
        f"📏 Размер: {document.file_size} байт\n"
        f"📌 MIME тип: {document.mime_type or 'Неизвестно'}\n\n"
        f"✅ Скопируйте <b>file_id</b> выше и используйте в коде"
    )
    
    await message.answer(text=response_text, parse_mode="HTML")
    logger.info(f"Получен документ: file_id={file_id}, user_id={message.from_user.id}")


@router.message(F.photo)
async def handle_photo(message: types.Message):
    """Обработка фото - вывод file_id."""
    photo = message.photo[-1]  # Берем самое большое фото
    file_id = photo.file_id
    file_unique_id = photo.file_unique_id
    
    response_text = (
        f"📷 <b>Фото получено!</b>\n\n"
        f"<code>{file_id}</code>\n\n"
        f"🆔 Unique ID: <code>{file_unique_id}</code>\n"
        f"📏 Размер: {photo.file_size} байт\n"
        f"📐 Разрешение: {photo.width}x{photo.height}\n\n"
        f"✅ Скопируйте <b>file_id</b> выше и используйте в коде"
    )
    
    await message.answer(text=response_text, parse_mode="HTML")
    logger.info(f"Получено фото: file_id={file_id}, user_id={message.from_user.id}")
