import os
import random
import sqlite3
import time
import string

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده است")

DB = "bazi_pol.db"


# =========================
# DATABASE
# =========================

def db():
    return sqlite3.connect(DB)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            balance INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            active INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS miners (
            user_id INTEGER PRIMARY KEY,
            level INTEGER DEFAULT 0,
            last_collect INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS serials (
            code TEXT PRIMARY KEY,
            amount INTEGER,
            used INTEGER DEFAULT 0
        )
    """)

    con.commit()
    con.close()


def get_user(user_id, name=""):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT user_id, name, balance FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    if row is None:
        cur.execute(
            "INSERT INTO users (user_id, name, balance) VALUES (?, ?, 0)",
            (user_id, name)
        )
        con.commit()
        balance = 0
    else:
        balance = row[2]

    con.close()
    return balance


def change_balance(user_id, amount, name=""):
    get_user(user_id, name)

    con = db()
    cur = con.cursor()

    cur.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id=?",
        (amount, user_id)
    )

    con.commit()
    con.close()


def get_balance(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT balance FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()
    con.close()

    return row[0] if row else 0


# =========================
# GROUP ACTIVE
# =========================

def is_group(update):
    return update.effective_chat.type in ["group", "supergroup"]


def group_active(chat_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT active FROM groups WHERE chat_id=?",
        (chat_id,)
    )

    row = cur.fetchone()
    con.close()

    return bool(row and row[0] == 1)


def set_group(chat_id, active):
    con = db()
    cur = con.cursor()

    cur.execute(
        "INSERT OR REPLACE INTO groups (chat_id, active) VALUES (?, ?)",
        (chat_id, int(active))
    )

    con.commit()
    con.close()


async def ensure_active(update):
    if not is_group(update):
        return True

    if not group_active(update.effective_chat.id):
        await update.message.reply_text(
            "🔴 بات هنوز فعال نشده.\n"
            "ادمین گروه باید بنویسه: فعال"
        )
        return False

    return True


# =========================
# ADMIN
# =========================

async def is_admin(update):
    if not is_group(update):
        return False

    member = await update.effective_chat.get_member(
        update.effective_user.id
    )

    return member.status in ["administrator", "creator"]


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user(
        update.effective_user.id,
        update.effective_user.first_name
    )

    await update.message.reply_text(
        "💰 به بات پولمون خوش اومدی!\n\n"
        "بات رو به گروه اضافه کن و ادمین گروه بنویسه:\n"
        "فعال\n\n"
        "بعدش با «راهنما» همه دستورات رو ببین."
    )


# =========================
# فعال / غیرفعال
# =========================

async def activate(update, context):

    if not is_group(update):
        await update.message.reply_text(
            "این دستور باید داخل گروه استفاده بشه."
        )
        return

    if not await is_admin(update):
        await update.message.reply_text(
            "❌ فقط ادمین گروه می‌تونه بات رو فعال کنه."
        )
        return

    set_group(update.effective_chat.id, True)

    await update.message.reply_text(
        "🟢 بات پولمون فعال شد!\n\n"
        "💰 بازی شروع شد."
    )


async def deactivate(update, context):

    if not is_group(update):
        return

    if not await is_admin(update):
        await update.message.reply_text(
            "❌ فقط ادمین می‌تونه بات رو غیرفعال کنه."
        )
        return

    set_group(update.effective_chat.id, False)

    await update.message.reply_text(
        "🔴 بات پولمون غیرفعال شد."
    )


# =========================
# راهنما
# =========================

async def help_command(update, context):

    if not await ensure_active(update):
        return

    await update.message.reply_text(
        "📖 راهنمای بات پولمون\n\n"

        "🟢 فعال\n"
        "🔴 غیرفعال\n\n"

        "💰 موجودی\n"
        "💵 واریز 1000\n"
        "💸 برداشت 1000\n"
        "🔄 انتقال 1000 ← با ریپلای\n\n"

        "🎮 بازی‌ها:\n"
        "✊ سنگ\n"
        "📄 کاغذ\n"
        "✂️ قیچی\n"
        "🪙 شیر\n"
        "🪙 خط\n"
        "➡️ راست\n"
        "⬅️ چپ\n\n"

        "🏆 ثروتمندان\n"
        "🎬 ساخت سریال\n"
        "⛏️ ماینر"
    )


# =========================
# موجودی
# =========================

async def balance(update, context):

    if not await ensure_active(update):
        return

    user = update.effective_user

    money = get_user(
        user.id,
        user.first_name
    )

    await update.message.reply_text(
        f"💰 موجودی {user.first_name}:\n"
        f"{money:,} پولمون"
    )


# =========================
# واریز
# =========================

async def deposit(update, context):

    if not await ensure_active(update):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\nواریز 10000"
        )
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ مبلغ نامعتبره."
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ باید بیشتر از صفر باشه."
        )
        return

    change_balance(
        update.effective_user.id,
        amount,
        update.effective_user.first_name
    )

    await update.message.reply_text(
        f"💵 {amount:,} پولمون به حسابت اضافه شد."
    )


# =========================
# برداشت
# =========================

async def withdraw(update, context):

    if not await ensure_active(update):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\nبرداشت 10000"
        )
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ مبلغ نامعتبره."
        )
        return

    money = get_balance(update.effective_user.id)

    if amount <= 0:
        return

    if money < amount:
        await update.message.reply_text(
            "❌ موجودیت کافی نیست."
        )
        return

    change_balance(
        update.effective_user.id,
        -amount
    )

    await update.message.reply_text(
        f"💸 {amount:,} پولمون برداشت شد."
    )


# =========================
# انتقال با ریپلای
# =========================

async def transfer(update, context):

    if not await ensure_active(update):
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ روی پیام شخص موردنظر ریپلای کن.\n"
            "مثال: انتقال 10000"
        )
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\nانتقال 10000"
        )
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ مبلغ نامعتبره."
        )
        return

    if amount <= 0:
        return

    sender = update.effective_user
    receiver = update.message.reply_to_message.from_user

    if sender.id == receiver.id:
        await update.message.reply_text(
            "😂 نمی‌تونی به خودت پول انتقال بدی."
        )
        return

    if get_balance(sender.id) < amount:
        await update.message.reply_text(
            "❌ موجودیت کافی نیست."
        )
        return

    get_user(
        receiver.id,
        receiver.first_name
    )

    change_balance(sender.id, -amount)
    change_balance(receiver.id, amount)

    await update.message.reply_text(
        f"🔄 انتقال انجام شد!\n\n"
        f"👤 فرستنده: {sender.first_name}\n"
        f"👤 گیرنده: {receiver.first_name}\n"
        f"💰 مبلغ: {amount:,}"
    )


# =========================
# سنگ کاغذ قیچی
# =========================

async def rps(update, choice):

    if not await ensure_active(update):
        return

    user = update.effective_user

    if get_balance(user.id) < 100:
        await update.message.reply_text(
            "❌ برای بازی حداقل 100 پولمون لازم داری."
        )
        return

    choices = ["سنگ", "کاغذ", "قیچی"]
    bot = random.choice(choices)

    change_balance(user.id, -100)

    if choice == bot:
        result = "🤝 مساوی شد!"
        prize = 100

    elif (
        (choice == "سنگ" and bot == "قیچی")
        or
        (choice == "کاغذ" and bot == "سنگ")
        or
        (choice == "قیچی" and bot == "کاغذ")
    ):
        result = "🎉 بردی!"
        prize = 200
        change_balance(user.id, prize)

    else:
        result = "💀 باختی!"
        prize = 0

    await update.message.reply_text(
        f"🎮 سنگ کاغذ قیچی\n\n"
        f"👤 تو: {choice}\n"
        f"🤖 بات: {bot}\n\n"
        f"{result}\n"
        f"💰 جایزه: {prize:,}"
    )


# =========================
# شیر خط
# =========================

async def coin(update, choice):

    if not await ensure_active(update):
        return

    user = update.effective_user

    if get_balance(user.id) < 100:
        await update.message.reply_text(
            "❌ حداقل 100 پولمون لازم داری."
        )
        return

    result = random.choice(["شیر", "خط"])

    change_balance(user.id, -100)

    if result == choice:
        change_balance(user.id, 200)
        text = "🎉 بردی!"
    else:
        text = "💀 باختی!"

    await update.message.reply_text(
        f"🪙 نتیجه: {result}\n\n{text}"
    )


# =========================
# راست / چپ
# =========================

async def right_left(update, choice):

    if not await ensure_active(update):
        return

    user = update.effective_user

    if get_balance(user.id) < 100:
        await update.message.reply_text(
            "❌ حداقل 100 پولمون لازم داری."
        )
        return

    result = random.choice(["راست", "چپ"])

    change_balance(user.id, -100)

    if result == choice:
        change_balance(user.id, 200)
        text = "🎉 بردی!"
    else:
        text = "💀 باختی!"

    await update.message.reply_text(
        f"🎲 نتیجه: {result}\n\n{text}"
    )


# =========================
# ثروتمندان
# =========================

async def rich(update, context):

    if not await ensure_active(update):
        return

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT name, balance
        FROM users
        ORDER BY balance DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text(
            "هنوز کسی پولی نداره 😂"
        )
        return

    text = "🏆 ثروتمندان پولمون\n\n"

    for i, row in enumerate(rows, 1):
        name = row[0] or "بدون نام"
        money = row[1]

        text += f"{i}. {name} — {money:,} 💰\n"

    await update.message.reply_text(text)


# =========================
# ساخت سریال
# =========================

async def serial(update, context):

    if not await ensure_active(update):
        return

    user = update.effective_user

    cost = 500

    if get_balance(user.id) < cost:
        await update.message.reply_text(
            "❌ برای ساخت سریال 500 پولمون لازم داری."
        )
        return

    change_balance(user.id, -cost)

    code = "".join(
        random.choices(
            string.ascii_uppercase + string.digits,
            k=8
        )
    )

    amount = random.randint(300, 1500)

    con = db()
    cur = con.cursor()

    cur.execute(
        "INSERT INTO serials (code, amount) VALUES (?, ?)",
        (code, amount)
    )

    con.commit()
    con.close()

    await update.message.reply_text(
        f"🎬 سریالت ساخته شد!\n\n"
        f"🎫 کد سریال:\n"
        f"`{code}`\n\n"
        f"💰 ارزش: {amount:,} پولمون\n\n"
        f"فعلاً 500 پولمون هزینه ساخت شد."
    )


# =========================
# ماینر
# =========================

async def miner(update, context):

    if not await ensure_active(update):
        return

    user = update.effective_user

    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT level, last_collect FROM miners WHERE user_id=?",
        (user.id,)
    )

    row = cur.fetchone()

    if row is None:
        cur.execute(
            "INSERT INTO miners (user_id, level, last_collect) VALUES (?, ?, ?)",
            (user.id, 1, int(time.time()))
        )

        con.commit()
        con.close()

        await update.message.reply_text(
            "⛏️ ماینر سطح 1 برات ساخته شد!\n"
            "دوباره «ماینر» بزن تا درآمدت رو جمع کنی."
        )
        return

    level, last_collect = row

    now = int(time.time())
    elapsed = now - last_collect

    income = int(elapsed / 60) * level

    if income <= 0:
        con.close()

        await update.message.reply_text(
            "⛏️ هنوز چیزی استخراج نشده.\n"
            "چند دقیقه دیگه دوباره بزن."
        )
        return

    cur.execute(
        "UPDATE miners SET last_collect=? WHERE user_id=?",
        (now, user.id)
    )

    con.commit()
    con.close()

    change_balance(user.id, income)

    await update.message.reply_text(
        f"⛏️ ماینر درآمدش رو استخراج کرد!\n\n"
        f"💰 درآمد: {income:,} پولمون\n"
        f"📈 سطح ماینر: {level}"
    )


# =========================
# TEXT HANDLER
# =========================

async def text_handler(update, context):

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # فعال
    if text == "فعال":
        await activate(update, context)
        return

    # غیرفعال
    if text == "غیرفعال":
        await deactivate(update, context)
        return

    # بقیه فقط وقتی فعال هستند
    if text == "راهنما":
        await help_command(update, context)
        return

    if text == "موجودی":
        await balance(update, context)
        return

    # واریز
    if text.startswith("واریز "):
        context.args = text.split()[1:]
        await deposit(update, context)
        return

    # برداشت
    if text.startswith("برداشت "):
        context.args = text.split()[1:]
        await withdraw(update, context)
        return

    # انتقال
    if text.startswith("انتقال "):
        context.args = text.split()[1:]
        await transfer(update, context)
        return

    # بازی سنگ کاغذ قیچی
    if text in ["سنگ", "کاغذ", "قیچی"]:
        await rps(update, text)
        return

    # شیر خط
    if text in ["شیر", "خط"]:
        await coin(update, text)
        return

    # راست چپ
    if text in ["راست", "چپ"]:
        await right_left(update, text)
        return

    # ثروتمندان
    if text == "ثروتمندان":
        await rich(update, context)
        return

    # ساخت سریال
    if text == "ساخت سریال":
        await serial(update, context)
        return

    # ماینر
    if text == "ماینر":
        await miner(update, context)
        return


# =========================
# MAIN
# =========================

def main():

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    print("💰 BAZI POL IS RUNNING...")

    # اجرای دائم تا زمانی که محیط اجرا فعال باشد
    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
