# filename: tg_file_shortbot.py
import logging
import sqlite3
import time
from datetime import datetime
from urllib.parse import quote_plus
import requests

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# -------- CONFIG ----------
BOT_TOKEN = "8222645012:AAEQMNK31oa5hDo_9OEStfNL7FMBdZMkUFM"
CHANNEL_ID = -1003292247930  # replace with your private channel ID
BOT_USERNAME = "Cornsehub"  # without @
ADMINS = {7681308594}  # replace with your Telegram numeric id(s)
ADRINO_API_KEY = "5b33540e7eaa148b24b8cca0d9a5e1b9beb3e634"  # optional: your adrinolinks.in API key
# --------------------------

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ---------- DATABASE ----------
conn = sqlite3.connect("botdata.db", check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS verified_users (
    user_id INTEGER PRIMARY KEY,
    valid_until INTEGER
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS files (
    chart_id TEXT PRIMARY KEY,
    channel_id INTEGER,
    channel_msg_id INTEGER,
    file_unique_id TEXT,
    created_at INTEGER
)
""")
conn.commit()

# ---------- FUNCTIONS ----------
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

def make_chart_id(channel_id: int, msg_id: int) -> str:
    return f"file_{abs(channel_id)}_{msg_id}"

def verify_user_db_set(user_id: int, days: int = 1):
    valid_until = int(time.time() + 86400 * days)
    c.execute("REPLACE INTO verified_users(user_id, valid_until) VALUES(?,?)", (user_id, valid_until))
    conn.commit()
    return valid_until

def verify_user_db_check(user_id: int) -> bool:
    c.execute("SELECT valid_until FROM verified_users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        return False
    return int(time.time()) <= row[0]

def store_file_record(chart_id, channel_id, channel_msg_id, file_unique_id):
    created_at = int(time.time())
    c.execute(
        "INSERT OR REPLACE INTO files(chart_id, channel_id, channel_msg_id, file_unique_id, created_at) VALUES(?,?,?,?,?)",
        (chart_id, channel_id, channel_msg_id, file_unique_id, created_at))
    conn.commit()

def get_file_record(chart_id):
    c.execute("SELECT channel_id, channel_msg_id FROM files WHERE chart_id=?", (chart_id,))
    return c.fetchone()

# ---------- LINK SHORTEN ----------
def shorten_with_adrino(long_url: str) -> str:
    if not ADRINO_API_KEY:
        return None
    try:
        res = requests.post(
            "https://adrinolinks.in/api",
            data={"api": ADRINO_API_KEY, "url": long_url},
            timeout=10
        )
        j = res.json()
        if "shortenedUrl" in j:
            return j["shortenedUrl"]
    except Exception as e:
        log.warning("Adrino shorten failed: %s", e)
    return None

def shorten_with_tinyurl(long_url: str) -> str:
    try:
        r = requests.get("http://tinyurl.com/api-create.php?url=" + quote_plus(long_url), timeout=10)
        if r.status_code == 200:
            return r.text.strip()
    except Exception as e:
        log.warning("TinyURL shorten failed: %s", e)
    return long_url

def make_short_link(long_url: str) -> str:
    s = shorten_with_adrino(long_url)
    if s:
        return s
    return shorten_with_tinyurl(long_url)

# ---------- HANDLERS ----------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("👋 Hello! Use /verify to get 1-day access.\n(Admins can upload files.)")
        return

    param = " ".join(args)
    if param.startswith("file_"):
        chart_id = param
        user_id = update.effective_user.id
        if not verify_user_db_check(user_id):
            await update.effective_message.reply_text(
                "𝗬𝗼𝘂𝗿 𝗔𝗱𝘀 𝗧𝗼𝗸𝗲𝗻 𝗵𝗮𝘀 𝗲𝘅𝗽𝗶𝗿𝗲𝗱!\n"
                "𝗣𝗹𝗲𝗮𝘀𝗲 𝗿𝗲𝗳𝗿𝗲𝘀𝗵 𝘆𝗼𝘂𝗿 𝘁𝗼𝗸𝗲𝗻 𝘁𝗼 𝘂𝘀𝗲 𝗺𝗲.\n\n"
                "🕒 Token Timeout: 1 day\n\n"
                "Use /verify to verify and get 1-day access."
            )
            return

        rec = get_file_record(chart_id)
        if not rec:
            await update.effective_message.reply_text("❌ File not found or expired.")
            return

        channel_id, channel_msg_id = rec
        try:
            await context.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=channel_id,
                message_id=channel_msg_id
            )
        except Exception as e:
            log.exception("File send error")
            await update.effective_message.reply_text("⚠️ Error sending file. Contact admin.")
    else:
        await update.effective_message.reply_text("❌ Unknown parameter.")

async def verify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    valid_until = verify_user_db_set(user_id, days=1)
    dt = datetime.utcfromtimestamp(valid_until).strftime("%Y-%m-%d %H:%M:%S UTC")
    await update.message.reply_text(f"✅ Verified! Access valid until {dt} (1 day).")

async def admin_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return  # ignore non-admin messages silently

    msg = update.message
    try:
        sent = await context.bot.forward_message(
            chat_id=CHANNEL_ID,
            from_chat_id=msg.chat_id,
            message_id=msg.message_id
        )
    except Exception as e:
        log.exception("Channel forward failed")
        await update.message.reply_text("⚠️ Error forwarding file. Bot ko channel admin banaya?")
        return

    chart_id = make_chart_id(CHANNEL_ID, sent.message_id)
    file_unique_id = ""
    if msg.document:
        file_unique_id = msg.document.file_unique_id
    elif msg.photo:
        file_unique_id = msg.photo[-1].file_unique_id
    elif msg.video:
        file_unique_id = msg.video.file_unique_id

    store_file_record(chart_id, CHANNEL_ID, sent.message_id, file_unique_id)
    deep_link = f"https://t.me/{BOT_USERNAME}?start={chart_id}"
    short = make_short_link(deep_link)

    await update.message.reply_text(
        f"✅ File saved & short link ready:\n{short}\n\n"
        f"⚠️ Users must /verify once before accessing the file."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Admins: Send file → bot gives short link.\nUsers: /verify to access files.")

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("verify", verify_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, admin_file_handler))

    print("✅ Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
