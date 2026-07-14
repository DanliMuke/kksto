import logging
import os
import tempfile

from groq import Groq
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Настройки ──────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")
MAX_DURATION = 300

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Отправь голосовое сообщение — я переведу его в текст.\n"
        "Работаю с русским и казахским языком."
    )


async def cmd_chatid(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает ID текущего Telegram-чата."""
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


async def send_to_target_chat(
    ctx: ContextTypes.DEFAULT_TYPE,
    msg,
    text: str,
    file_obj=None,
    message_kind: str = "текстовое сообщение",
) -> None:
    """Отправляет сообщение и данные пользователя в TARGET_CHAT_ID."""
    if not TARGET_CHAT_ID:
        log.warning(
            "TARGET_CHAT_ID не задан. Отправка в отдельный чат пропущена."
        )
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
            for chunk in split_text(full_text):
                await ctx.bot.send_message(
                    chat_id=TARGET_CHAT_ID,
                    text=chunk,
                )
            log.info(
                "Текстовое сообщение отправлено в TARGET_CHAT_ID=%s",
                TARGET_CHAT_ID,
            )
            return

        caption_limit = 1024
        available = max(caption_limit - len(header), 0)
        caption_text = text[:available]
        leftover = text[available:]
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

        log.info(
            "Голосовое сообщение отправлено в TARGET_CHAT_ID=%s",
            TARGET_CHAT_ID,
        )

        for chunk in split_text(leftover):
            await ctx.bot.send_message(
                chat_id=TARGET_CHAT_ID,
                text=chunk,
            )

    except Exception:
        log.exception("Ошибка при отправке сообщения в TARGET_CHAT_ID")


def split_text(text: str, limit: int = 4000) -> list[str]:
    """Разбивает длинный текст на части, допустимые Telegram."""
    if not text:
        return []
    return [text[i : i + limit] for i in range(0, len(text), limit)]


async def handle_voice(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    msg = update.message
    file_obj = msg.voice or msg.audio

    if not file_obj:
        return

    duration = getattr(file_obj, "duration", 0) or 0
    if duration > MAX_DURATION:
        await msg.reply_text(
            f"⚠️ Слишком длинное сообщение "
            f"(>{MAX_DURATION // 60} мин). Разбей на части."
        )
        return

    status = await msg.reply_text("⏳ Распознаю...")

    try:
        tg_file = await ctx.bot.get_file(file_obj.file_id)

        with tempfile.TemporaryDirectory() as tmp:
            extension = ".ogg" if msg.voice else ".mp3"
            audio_path = os.path.join(tmp, f"audio{extension}")
            await tg_file.download_to_drive(audio_path)

            with open(audio_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_path), audio_file),
                    model="whisper-large-v3",
                    language="ru",
                    response_format="text",
                )

        await status.delete()

        if isinstance(transcription, str):
            text = transcription.strip()
        else:
            text = (transcription.text or "").strip()

        if not text:
            await msg.reply_text(
                "🤔 Не удалось распознать речь. Попробуй говорить чётче."
            )
            return

        await send_to_target_chat(
            ctx,
            msg,
            text,
            file_obj=file_obj,
            message_kind="голосовое сообщение",
        )

        for chunk in split_text(text):
            await msg.reply_text(f"📝 {chunk}")

        log.info(
            "User %s | %s символов",
            msg.from_user.id,
            len(text),
        )

    except Exception:
        try:
            await status.delete()
        except Exception:
            pass

        await msg.reply_text(
            "❌ Ошибка при распознавании. Попробуй ещё раз."
        )
        log.exception("Ошибка транскрипции")


async def handle_text(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    msg = update.message
    text = (msg.text or "").strip()

    if not text:
        return

    await send_to_target_chat(
        ctx,
        msg,
        text,
        message_kind="текстовое сообщение",
    )
    await msg.reply_text("✅ Текстовое сообщение отправлено.")

    log.info(
        "User %s | текстовое сообщение | %s символов",
        msg.from_user.id,
        len(text),
    )


def validate_environment() -> None:
    """Проверяет обязательные переменные Railway."""
    missing = []

    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")

    if missing:
        raise RuntimeError(
            "Не заданы обязательные переменные окружения: "
            + ", ".join(missing)
        )


def main() -> None:
    validate_environment()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("chatid", cmd_chatid))

    private_audio_filter = filters.ChatType.PRIVATE & (
        filters.VOICE | filters.AUDIO
    )
    private_text_filter = (
        filters.ChatType.PRIVATE
        & filters.TEXT
        & ~filters.COMMAND
    )

    app.add_handler(
        MessageHandler(private_audio_filter, handle_voice)
    )
    app.add_handler(
        MessageHandler(private_text_filter, handle_text)
    )

    log.info("Бот запущен.")
    app.run_polling()


if __name__ == "__main__":
    main()
