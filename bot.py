import os
import logging
import tempfile
from groq import Groq
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

# ── Настройки ──────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# ID чата, куда будет отправляться голосовое сообщение и текст
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")
MAX_DURATION = 300

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)


async def cmd_chatid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Команда для получения ID текущего чата. Полезно, чтобы узнать
    TARGET_CHAT_ID для пересылки заявок в группу.
    """
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def send_to_target_chat(
    ctx: ContextTypes.DEFAULT_TYPE,
    msg,
    text: str,
    file_obj=None,
    message_kind: str = "текстовое сообщение",
):
    """
    Отправляет сообщение пользователя в отдельный Telegram-чат, если указан TARGET_CHAT_ID.
    Для голосовых/аудио сообщений прикладывает оригинальное медиа с транскриптом в caption.
    Для обычного текста отправляет текстовое сообщение с данными отправителя.
    """
    if not TARGET_CHAT_ID:
        log.warning("TARGET_CHAT_ID не задан. Отправка в отдельный чат пропущена.")
        return

    try:
        user = msg.from_user
        username = f"@{user.username}" if user.username else "нет username"
        is_voice_message = file_obj is not None

        header = (
            f"📝 Новое {message_kind}\n\n"
            "Отправитель:\n"
            f"Имя: {user.full_name}\n"
            f"Username: {username}\n"
            f"Telegram ID: {user.id}\n\n"
            "Текст:\n"
        )

        if not is_voice_message:
            full_text = header + text
            for chunk in [full_text[i:i + 4000] for i in range(0, len(full_text), 4000)]:
                await ctx.bot.send_message(chat_id=TARGET_CHAT_ID, text=chunk)
            log.info(f"Текстовое сообщение отправлено в TARGET_CHAT_ID={TARGET_CHAT_ID}")
            return

        # Telegram ограничивает длину подписи к медиа примерно 1024 символами.
        caption_limit = 1024
        available = max(caption_limit - len(header), 0)
        caption_text = text[:available] if len(text) > available else text
        leftover = text[available:] if len(text) > available else ""
        caption = header + caption_text

        if msg.voice:
            await ctx.bot.send_voice(
                chat_id=TARGET_CHAT_ID,
                voice=file_obj.file_id,
                caption=caption,
            )
        else:
            await ctx.bot.send_audio(
                chat_id=TARGET_CHAT_ID,
                audio=file_obj.file_id,
                caption=caption,
            )
        log.info(f"Голосовое сообщение отправлено в TARGET_CHAT_ID={TARGET_CHAT_ID}")

        if leftover:
            for chunk in [leftover[i:i + 4000] for i in range(0, len(leftover), 4000)]:
                await ctx.bot.send_message(chat_id=TARGET_CHAT_ID, text=chunk)

    except Exception:
        log.exception("Ошибка при отправке сообщения в TARGET_CHAT_ID")

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Отправь голосовое сообщение — я переведу его в текст.\n"
        "Работаю с русским и казахским языком."
    )


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = msg.voice or msg.audio
    if not file_obj:
        return

    duration = getattr(file_obj, "duration", 0)
    if duration > MAX_DURATION:
        await msg.reply_text(f"⚠️ Слишком длинное сообщение (>{MAX_DURATION // 60} мин). Разбей на части.")
        return

    status = await msg.reply_text("⏳ Распознаю...")

    try:
        tg_file = await ctx.bot.get_file(file_obj.file_id)

        with tempfile.TemporaryDirectory() as tmp:
            audio_path = os.path.join(tmp, "voice.ogg")
            await tg_file.download_to_drive(audio_path)

            with open(audio_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=("voice.ogg", f),
                    model="whisper-large-v3",
                    language="ru",
                    response_format="text"
                )

        await status.delete()

        text = transcription.strip() if isinstance(transcription, str) else transcription.text.strip()

        if not text:
            await msg.reply_text("🤔 Не удалось распознать речь. Попробуй говорить чётче.")
            return

        # Отправляем текст и оригинальное голосовое сообщение в специальный чат
        await send_to_target_chat(ctx, msg, text, file_obj=file_obj, message_kind="голосовое сообщение")

        # После отправки в группу отвечаем пользователю распознанным текстом
        for chunk in [text[i:i + 4000] for i in range(0, len(text), 4000)]:
            await msg.reply_text(f"📝 {chunk}")

        log.info(f"User {msg.from_user.id} | {len(text)} символов")

    except Exception:
        await status.delete()
        await msg.reply_text("❌ Ошибка при распознавании. Попробуй ещё раз.")
        log.exception("Ошибка транскрипции")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = (msg.text or "").strip()
    if not text:
        return

    await send_to_target_chat(ctx, msg, text, message_kind="текстовое сообщение")
    await msg.reply_text("✅ Текстовое сообщение отправлено.")
    log.info(f"User {msg.from_user.id} | текстовое сообщение | {len(text)} символов")

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("Переменная BOT_TOKEN не задана!")
    if not GROQ_API_KEY:
        raise RuntimeError("Переменная GROQ_API_KEY не задана!")
    if not TARGET_CHAT_ID:
        raise RuntimeError("Переменная TARGET_CHAT_ID не задана!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Регистрация команд
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("chatid", cmd_chatid))

    # Обработчик голосовых и аудио сообщений
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.VOICE | filters.AUDIO), handle_voice))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Бот запущен.")
    app.run_polling()


