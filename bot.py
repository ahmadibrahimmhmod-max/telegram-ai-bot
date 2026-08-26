import os
import sys
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import AsyncGroq
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not GROQ_API_KEY or not TELEGRAM_TOKEN:
    print ("Error:missing API keys. please set GROQ API KEY and TELEGRAM_TOKEN in environment variables.")
    sys.exit()
client = AsyncGroq(api_key=GROQ_API_KEY)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(f"Welcome {user_name}")
async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_received = update.message.text
    try:
        chat_completion = await client.chat.completions.create(
            messages=[{"role": "system", "content":"""انت بوت ذكي ومساعد شخصي  ahmed_test_bot للمبرمج احمد ابراهيم محمود   وتعرف احمد ابراهيم هو من قام من طورك بفضل الله"""},{"role": "user", "content":text_received}],
            model="openai/gpt-oss-120b",
        )
        await update.message.reply_text(chat_completion.choices[0].message.content)
    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text("Sorry, I encountered an error.")


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT &~filters.COMMAND, ai_reply))

    app.run_polling()
