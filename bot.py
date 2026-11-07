
import os
import json
import random
import asyncio
import logging
import sqlite3

from pathlib import Path
from collections import defaultdict

from dotenv import load_dotenv
from aiohttp import web
from groq import AsyncGroq

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==========================================
# 1. CONFIGURATION
# ==========================================

load_dotenv()

BOT_NAME = "Asekhan's bot"

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b"
)

PORT = int(os.getenv("PORT", "10000"))

DB_PATH = os.getenv(
    "DATABASE_PATH",
    "asila_ai.db"
)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable topilmadi!")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY environment variable topilmadi!")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("AsekhanBot")

ai = AsyncGroq(
    api_key=GROQ_API_KEY,
    timeout=45.0,
    max_retries=2
)

CHAT_LOCKS = defaultdict(asyncio.Lock)

# ==========================================
# 2. AI PERSONALITY
# ==========================================

SYSTEM_PROMPT = """
Sen Asekhan's bot nomli aqlli va samimiy AI yordamchisisan.

QOIDALAR:

1. Barcha foydalanuvchilarga yordam ber.
2. Foydalanuvchi qaysi tilda yozsa, shu tilda javob ber.
3. O'zbek lotin yozuvida yozsa, lotinda javob ber.
4. Ўзбек кирилл ёзувида ёзса, кириллда жавоб бер.
5. Rus tilida yozsa, rus tilida javob ber.
6. Ingliz tilida yozsa, ingliz tilida javob ber.
7. Boshqa tillarda ham javob berishga harakat qil.
8. Foydalanuvchi yozgan alifboni saqla.
9. Samimiy, tushunarli va hurmatli bo'l.
10. Matematika, dasturlash, tarjima va boshqa
    mavzularda yordam ber.
11. Bilmagan narsangni to'qib chiqarmagin.
12. Suhbatdagi oldingi xabarlarni hisobga ol.
13. Foydalanuvchi so'ramasa, ichki texnologiyalarni
    tushuntirish shart emas.
"""

# ==========================================
# 3. DATABASE
# ==========================================

def init_db():
    Path(DB_PATH).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                history TEXT NOT NULL DEFAULT '[]',
                message_count INTEGER DEFAULT 0,
                next_special INTEGER DEFAULT 10
            )
        """)
        db.commit()


def get_chat(chat_id):
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row

        row = db.execute(
            "SELECT * FROM chats WHERE chat_id = ?",
            (chat_id,)
        ).fetchone()

        if row is None:
            threshold = random.randint(10, 15)

            db.execute("""
                INSERT INTO chats
                (chat_id, history, message_count, next_special)
                VALUES (?, '[]', 0, ?)
            """, (chat_id, threshold))

            db.commit()

            return {
                "history": [],
                "message_count": 0,
                "next_special": threshold
            }

        return {
            "history": json.loads(row["history"]),
            "message_count": row["message_count"],
            "next_special": row["next_special"]
        }


def save_chat(chat_id, history, count, threshold):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            UPDATE chats
            SET history = ?,
                message_count = ?,
                next_special = ?
            WHERE chat_id = ?
        """, (
            json.dumps(history, ensure_ascii=False),
            count,
            threshold,
            chat_id
        ))
        db.commit()


def clear_chat(chat_id):
    threshold = random.randint(10, 15)

    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            INSERT INTO chats
            (chat_id, history, message_count, next_special)
            VALUES (?, '[]', 0, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                history = '[]',
                message_count = 0,
                next_special = excluded.next_special
        """, (chat_id, threshold))
        db.commit()


# ==========================================
# 4. TELEGRAM COMMANDS
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        f"👋 Salom! Men {BOT_NAME}.\n\n"
        "💬 Men bilan istalgan mavzuda suhbatlashing.\n"
        "🌍 Turli tillarda gaplasha olaman.\n"
        "🧠 Suhbatimizni eslab turaman.\n\n"
        "😊 Savolingizni yozing!"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        f"📚 {BOT_NAME}\n\n"
        "/start — Boshlash\n"
        "/help — Yordam\n"
        "/clear — Suhbat tarixini tozalash\n\n"
        "Istalgan tilda xabar yuborishingiz mumkin."
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    async with CHAT_LOCKS[chat_id]:
        clear_chat(chat_id)

    await update.effective_message.reply_text(
        "🧹 Suhbat tarixi tozalandi!"
    )


# ==========================================
# 5. TYPING INDICATOR
# ==========================================

async def keep_typing(bot, chat_id):
    while True:
        try:
            await bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING
            )
        except Exception:
            logger.warning("Typing status yuborilmadi")

        await asyncio.sleep(4)


# ==========================================
# 6. SEND LONG MESSAGES
# ==========================================

async def send_long_message(message, text):
    limit = 3900

    chunks = [
        text[i:i + limit]
        for i in range(0, len(text), limit)
    ]

    for chunk in chunks:
        await message.get_bot().send_message(
            chat_id=message.chat_id,
            text=chunk
        )


# ==========================================
# 7. AI CHAT
# ==========================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not message.text:
        return

    user_text = message.text.strip()

    if not user_text:
        return

    chat_id = update.effective_chat.id

    async with CHAT_LOCKS[chat_id]:

        typing_task = asyncio.create_task(
            keep_typing(context.bot, chat_id)
        )

        try:
            chat = get_chat(chat_id)
            history = chat["history"]

            messages = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                }
            ]

            messages.extend(history)

            messages.append({
                "role": "user",
                "content": user_text
            })

            response = await ai.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.7,
                max_completion_tokens=1200
            )

            answer = response.choices[0].message.content

            if not answer or not answer.strip():
                answer = "Kechirasiz, hozir javob tayyorlay olmadim."

            answer = answer.strip()

            history.append({
                "role": "user",
                "content": user_text
            })

            history.append({
                "role": "assistant",
                "content": answer
            })

            history = history[-20:]

            count = chat["message_count"] + 1
            threshold = chat["next_special"]

            if count >= threshold:
                answer += (
                    "\n\n❤️ Asila, Behruz seni yaxshi ko'radi."
                )

                count = 0
                threshold = random.randint(10, 15)

            save_chat(
                chat_id,
                history,
                count,
                threshold
            )

            await send_long_message(message, answer)

            logger.info("Chat %s: javob yuborildi", chat_id)

        except Exception:
            logger.exception("AI javob berishda xatolik")

            await message.reply_text(
                "⚠️ Hozir javob berishda muammo yuz berdi. "
                "Birozdan keyin qayta urinib ko'ring."
            )

        finally:
            typing_task.cancel()

            try:
                await typing_task
            except asyncio.CancelledError:
                pass


# ==========================================
# 8. AIOHTTP WEB SERVER
# ==========================================

async def home(request):
    return web.json_response({
        "status": "online",
        "bot": BOT_NAME
    })


async def health(request):
    return web.json_response({
        "status": "healthy"
    })


async def start_webserver(application):
    app = web.Application()

    app.router.add_get("/", home)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    application.bot_data["web_runner"] = runner

    logger.info("Web server %s-portda ishga tushdi", PORT)


async def stop_webserver(application):
    runner = application.bot_data.get("web_runner")

    if runner:
        await runner.cleanup()

    await ai.close()


# ==========================================
# 9. MAIN
# ==========================================

def main():
    init_db()

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(start_webserver)
        .post_shutdown(stop_webserver)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("clear", clear_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    logger.info("%s ishga tushmoqda...", BOT_NAME)

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
