# ============================================================
# 1. الاستيرادات والإعدادات الأساسية
# ============================================================
import os
import sys
import html
import json
import logging
import traceback
from datetime import date

import aiosqlite
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    ContextTypes, filters,
)
from groq import AsyncGroq

load_dotenv()
import os
print(">>> مجلد العمل:", os.getcwd())
print(">>> هل .env موجود:", os.path.exists(".env"))
print(">>> محتوى GROQ_API_KEY:", os.getenv("GROQ_API_KEY"))
print(">>> محتوى TELEGRAM_TOKEN:", os.getenv("TELEGRAM_TOKEN"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8443))
URL_PATH = os.getenv("URL_PATH", "webhook")
CERT_PATH = os.getenv("CERT_PATH")
KEY_PATH = os.getenv("KEY_PATH")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
DEVELOPER_CHAT_ID = int(os.getenv("DEVELOPER_CHAT_ID", 0))

if not GROQ_API_KEY or not TELEGRAM_TOKEN:
    print("Error: missing API keys.")
    sys.exit()

client = AsyncGroq(api_key=GROQ_API_KEY)

# ============================================================
# 2. إعداد نظام المراقبة (Logging)
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# 3. قاعدة البيانات (SQLite غير متزامنة)
# ============================================================
DB_PATH = "bot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                subject TEXT DEFAULT NULL,
                level TEXT DEFAULT NULL,
                daily_count INTEGER DEFAULT 0,
                last_reset TEXT DEFAULT NULL,
                is_premium INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                currency TEXT,
                charge_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def create_user(user_id: int, first_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)",
            (user_id, first_name),
        )
        await db.commit()

async def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
    values = list(kwargs.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
        await db.commit()

async def increment_daily_count(user_id: int) -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE users
            SET daily_count = CASE
                WHEN last_reset IS NULL OR last_reset < ? THEN 1
                ELSE daily_count + 1
            END,
            last_reset = ?
            WHERE user_id = ?
        """, (today, today, user_id))
        await db.commit()
        async with db.execute("SELECT daily_count FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def save_payment(user_id: int, amount: int, currency: str, charge_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (user_id, amount, currency, charge_id) VALUES (?, ?, ?, ?)",
            (user_id, amount, currency, charge_id),
        )
        await db.commit()

# ============================================================
# 4. دوال البوت
# ============================================================
FREE_DAILY_LIMIT = 10
PREMIUM_PRICE_STARS = 50

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await create_user(user.id, user.first_name)
    await update.message.reply_text(
        f"أهلاً {user.first_name}! 👋\n"
        "أنا مساعدك الدراسي الذكي.\n\n"
        "أرسل لي أي سؤال في أي مادة، وسأشرحه لك خطوة بخطوة.\n\n"
        f"🎁 لديك {FREE_DAILY_LIMIT} رسائل مجانية يومياً.\n"
        "للاشتراك المميز: /subscribe"
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton(
            f"⭐ اشترك الآن - {PREMIUM_PRICE_STARS} نجمة",
            callback_data="buy_premium"
        )
    ]]
    await update.message.reply_text(
        "🌟 **الاشتراك المميز**\n\n"
        "✅ رسائل غير محدودة\n"
        "✅ حل الصور والتمارين\n"
        "✅ أولوية في الردود\n"
        "✅ حفظ سياق المحادثة\n\n"
        f"السعر: {PREMIUM_PRICE_STARS} نجمة (لمرة واحدة)",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )

async def buy_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title="الاشتراك المميز",
        description="رسائل غير محدودة + ميزات متقدمة",
        payload="premium_subscription",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice("الاشتراك المميز", PREMIUM_PRICE_STARS)],
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payment = update.message.successful_payment
    user_id = update.effective_user.id
    await update_user(user_id, is_premium=1)
    await save_payment(
        user_id,
        payment.total_amount,
        payment.currency,
        payment.telegram_payment_charge_id,
    )
    await update.message.reply_text(
        "🎉 تم تفعيل اشتراكك المميز!\n"
        "استمتع الآن برسائل غير محدودة."
    )

async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text_received = update.message.text

    await create_user(user.id, user.first_name)
    user_data = await get_user(user.id)
    if not user_data:
        return

    # فحص الحد اليومي
    if not user_data["is_premium"]:
        count = await increment_daily_count(user.id)
        if count > FREE_DAILY_LIMIT:
            await update.message.reply_text(
                "⚠️ وصلت للحد اليومي المجاني.\n"
                "اشترك للحصول على رسائل غير محدودة: /subscribe"
            )
            return
    else:
        await increment_daily_count(user.id)

    subject = user_data["subject"]
    if not subject:
        await update_user(user.id, subject=text_received)
        await update.message.reply_text(
            f"ممتاز! سجلت مادتك: {text_received}\n"
            "أرسل لي سؤالك الآن."
        )
        return

    system_instruction = (
        f"You are a patient, friendly tutor for students worldwide. "
        f"The student is studying: {subject}. "
        "Always reply in the SAME language the user writes in. "
        "Explain clearly, encourage the student, and show reasoning step by step."
    )

    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": text_received},
            ],
            model="openai/gpt-oss-120b",
        )
        await update.message.reply_text(chat_completion.choices[0].message.content)
    except Exception as e:
        logger.error(f"Groq API error: {e}", exc_info=True)
        await update.message.reply_text("حدث خطأ مؤقت، حاول مجدداً.")

# ============================================================
# 5. معالج الأخطاء (نظام المراقبة)
# ============================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

    if not DEVELOPER_CHAT_ID:
        return

    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        "⚠️ **خطأ في البوت**\n\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    try:
        await context.bot.send_message(
            chat_id=DEVELOPER_CHAT_ID,
            text=message[:4000],
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"Failed to send error to developer: {e}")

# ============================================================
# 6. التشغيل (Webhook)
# ============================================================
async def post_init(application):
    await init_db()
    logger.info("Database initialized.")

if __name__ == "__main__":
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CallbackQueryHandler(buy_premium, pattern="^buy_premium$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply))

    app.add_error_handler(error_handler)

    logger.info("✅ البوت يعمل عبر Webhook...")

    app.run_webhook(
        listen="0.0.0.0",
        port=4843,
        url_path="webhook",
        webhook_url="https://yourdomain.com/webhook",
        drop_pending_updates=True,
    )