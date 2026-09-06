import os
import sqlite3
import random
import string
import time

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

# آیدی عددی مالک ربات
OWNER_ID = 8981018900

DB_FILE = "moltaf_kid.db"

# پول نامحدود مالک
OWNER_MONEY = 10**100


# =========================
# DATABASE
# =========================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row


def init_db():
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            money INTEGER DEFAULT 0,
            bank INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS serials (
            code TEXT PRIMARY KEY,
            amount INTEGER NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS miners (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_claim REAL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups_active (
            chat_id INTEGER PRIMARY KEY,
            active INTEGER DEFAULT 0
        )
    """)

    db.commit()


def ensure_user(user_id):
    if user_id == OWNER_ID:
        return

    db.execute(
        "INSERT OR IGNORE INTO users (user_id, money, bank) VALUES (?, 0, 0)",
        (user_id,)
    )

    db.commit()


# =========================
# MONEY
# =========================

def get_money(user_id):
    if user_id == OWNER_ID:
        return OWNER_MONEY

    ensure_user(user_id)

    row = db.execute(
        "SELECT money FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    return row["money"] if row else 0


def get_bank(user_id):
    if user_id == OWNER_ID:
        return OWNER_MONEY

    ensure_user(user_id)

    row = db.execute(
        "SELECT bank FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    return row["bank"] if row else 0


def add_money(user_id, amount):
    if user_id == OWNER_ID:
        return

    ensure_user(user_id)

    db.execute(
        "UPDATE users SET money = money + ? WHERE user_id=?",
        (amount, user_id)
    )

    db.commit()


def remove_money(user_id, amount):
    if amount < 0:
        return False

    if user_id == OWNER_ID:
        return True

    ensure_user(user_id)

    if get_money(user_id) < amount:
        return False

    db.execute(
        "UPDATE users SET money = money - ? WHERE user_id=?",
        (amount, user_id)
    )

    db.commit()

    return True


def add_bank(user_id, amount):
    if user_id == OWNER_ID:
        return

    ensure_user(user_id)

    db.execute(
        "UPDATE users SET bank = bank + ? WHERE user_id=?",
        (amount, user_id)
    )

    db.commit()


def remove_bank(user_id, amount):
    if amount < 0:
        return False

    if user_id == OWNER_ID:
        return True

    ensure_user(user_id)

    if get_bank(user_id) < amount:
        return False

    db.execute(
        "UPDATE users SET bank = bank - ? WHERE user_id=?",
        (amount, user_id)
    )

    db.commit()

    return True


# =========================
# MONEY UNITS
# =========================

MULTIPLIERS = {
    "کا": 10**3,
    "هزار": 10**3,

    "میل": 10**6,
    "میلیون": 10**6,

    "بیل": 10**9,
    "میلیارد": 10**9,

    "تیل": 10**12,
    "تریلیون": 10**12,

    "کیل": 10**15,

    "کواد": 10**18,
}


def parse_amount(text, user_id):
    text = text.strip().lower().replace(",", "")

    money = get_money(user_id)

    if text in ("کل", "همه", "همش"):
        return money

    if text == "نصف":
        return money // 2

    if text == "خمس":
        return money // 5

    if text == "ثلث":
        return money // 3

    parts = text.split()

    try:

        if len(parts) == 1:
            return int(parts[0])

        if len(parts) == 2 and parts[1] in MULTIPLIERS:
            return int(parts[0]) * MULTIPLIERS[parts[1]]

    except ValueError:
        return None

    return None


def format_money(amount):

    if amount >= OWNER_MONEY:
        return "بی‌نهایت سکه"

    units = [
        (10**18, "کواد"),
        (10**15, "کیل"),
        (10**12, "تیل"),
        (10**9, "بیل"),
        (10**6, "میل"),
        (10**3, "کا"),
    ]

    for value, name in units:

        if amount >= value:
            return f"{amount // value} {name} سکه"

    return f"{amount:,} سکه"


# =========================
# GROUP
# =========================

def group_is_active(chat_id):

    row = db.execute(
        "SELECT active FROM groups_active WHERE chat_id=?",
        (chat_id,)
    ).fetchone()

    return bool(row["active"]) if row else False


def activate_group(chat_id):

    db.execute("""
        INSERT INTO groups_active(chat_id, active)
        VALUES (?, 1)

        ON CONFLICT(chat_id)
        DO UPDATE SET active=1
    """, (chat_id,))

    db.commit()


# =========================
# BANK
# =========================

async def bank_deposit(update, user_id, amount):

    if amount is None or amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if not remove_money(user_id, amount):
        await update.message.reply_text(
            "❌ سکه کافی نداری."
        )
        return

    add_bank(user_id, amount)

    await update.message.reply_text(
        f"🏦 {format_money(amount)} به بانک منتقل شد."
    )


async def bank_withdraw(update, user_id, amount):

    if amount is None or amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if not remove_bank(user_id, amount):
        await update.message.reply_text(
            "❌ موجودی بانک کافی نیست."
        )
        return

    add_money(user_id, amount)

    await update.message.reply_text(
        f"💳 {format_money(amount)} از بانک برداشت شد."
    )


# =========================
# TRANSFER
# =========================

async def transfer(update, user_id, amount):

    reply = update.message.reply_to_message

    if not reply:
        await update.message.reply_text(
            "❌ باید روی پیام شخص ریپلای کنی."
        )
        return

    target = reply.from_user

    if target.id == user_id:
        await update.message.reply_text(
            "😂 به خودت نمیشه انتقال داد."
        )
        return

    if amount is None or amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if not remove_money(user_id, amount):
        await update.message.reply_text(
            "❌ سکه کافی نداری."
        )
        return

    add_money(target.id, amount)

    await update.message.reply_text(
        f"💸 انتقال انجام شد!\n\n"
        f"👤 گیرنده: {target.first_name}\n"
        f"💰 مبلغ: {format_money(amount)}"
    )


# =========================
# SERIAL
# =========================

async def create_serial(update, user_id, amount):

    if amount is None or amount <= 0:
        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )
        return

    if not remove_money(user_id, amount):
        await update.message.reply_text(
            "❌ سکه کافی نداری."
        )
        return

    while True:

        code = "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=20
            )
        )

        exists = db.execute(
            "SELECT 1 FROM serials WHERE code=?",
            (code,)
        ).fetchone()

        if not exists:
            break

    db.execute(
        "INSERT INTO serials(code, amount, used) VALUES (?, ?, 0)",
        (code, amount)
    )

    db.commit()

    await update.message.reply_text(
        f"🎟 سریال ساخته شد!\n\n"
        f"`{code}`\n\n"
        f"💰 ارزش: {format_money(amount)}",
        parse_mode="Markdown"
    )


async def use_serial(update, user_id, code):

    code = code.strip().upper()

    row = db.execute(
        "SELECT * FROM serials WHERE code=?",
        (code,)
    ).fetchone()

    if not row:
        await update.message.reply_text(
            "❌ سریال پیدا نشد."
        )
        return

    if row["used"]:
        await update.message.reply_text(
            "❌ این سریال قبلاً استفاده شده."
        )
        return

    db.execute(
        "UPDATE serials SET used=1 WHERE code=?",
        (code,)
    )

    db.commit()

    add_money(user_id, row["amount"])

    await update.message.reply_text(
        f"🎉 سریال فعال شد!\n"
        f"💰 دریافت کردی: {format_money(row['amount'])}"
    )


# =========================
# MINER
# =========================

async def buy_miner(update, user_id, count, level):

    if count <= 0 or level <= 0:
        await update.message.reply_text(
            "❌ تعداد یا سطح درست نیست."
        )
        return

    total = count * 1_000_000 * level

    if not remove_money(user_id, total):

        await update.message.reply_text(
            f"❌ سکه کافی نداری.\n"
            f"💰 قیمت: {format_money(total)}"
        )

        return

    row = db.execute(
        "SELECT * FROM miners WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if row:

        db.execute("""
            UPDATE miners
            SET count=count+?,
                level=?
            WHERE user_id=?
        """, (
            count,
            max(row["level"], level),
            user_id
        ))

    else:

        db.execute("""
            INSERT INTO miners
            (user_id, count, level, last_claim)
            VALUES (?, ?, ?, 0)
        """, (
            user_id,
            count,
            level
        ))

    db.commit()

    await update.message.reply_text(
        f"⛏ {count} ماینر سطح {level} خریدی!\n"
        f"💰 هزینه: {format_money(total)}"
    )


async def claim_miner(update, user_id):

    row = db.execute(
        "SELECT * FROM miners WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not row or row["count"] <= 0:

        await update.message.reply_text(
            "❌ هنوز ماینری نداری."
        )

        return

    remaining = 3600 - (
        time.time() - row["last_claim"]
    )

    if row["last_claim"] and remaining > 0:

        await update.message.reply_text(
            f"⏳ هنوز وقت برداشت نرسیده.\n"
            f"🕐 {int(remaining)//60} دقیقه "
            f"و {int(remaining)%60} ثانیه باقی مانده."
        )

        return

    reward = (
        row["count"]
        * 500_000
        * row["level"]
    )

    db.execute(
        "UPDATE miners SET last_claim=? WHERE user_id=?",
        (time.time(), user_id)
    )

    db.commit()

    add_money(user_id, reward)

    await update.message.reply_text(
        f"⛏ برداشت ماینر انجام شد!\n\n"
        f"⛏ تعداد: {row['count']}\n"
        f"⭐ سطح: {row['level']}\n"
        f"💰 دریافتی: {format_money(reward)}"
    )


# =========================
# GAMES
# =========================

async def game(update, user_id, kind, choice, amount):

    if amount is None or amount <= 0:

        await update.message.reply_text(
            "❌ مبلغ درست نیست."
        )

        return

    if not remove_money(user_id, amount):

        await update.message.reply_text(
            "❌ سکه کافی نداری."
        )

        return

    if kind == "rps":

        bot_choice = random.choice(
            ["سنگ", "کاغذ", "قیچی"]
        )

        win = (
            (choice == "سنگ" and bot_choice == "قیچی")
            or
            (choice == "کاغذ" and bot_choice == "سنگ")
            or
            (choice == "قیچی" and bot_choice == "کاغذ")
        )

        draw = choice == bot_choice

        result = (
            f"🤖 انتخاب من: {bot_choice}\n"
        )

    elif kind == "coin":

        bot_choice = random.choice(
            ["شیر", "خط"]
        )

        win = choice == bot_choice
        draw = False

        result = (
            f"🪙 نتیجه: {bot_choice}\n"
        )

    elif kind == "direction":

        bot_choice = random.choice(
            ["راست", "چپ"]
        )

        win = choice == bot_choice
        draw = False

        result = (
            f"🤖 انتخاب من: {bot_choice}\n"
        )

    else:

        number = random.randint(1, 100)

        bot_choice = (
            "زوج"
            if number % 2 == 0
            else "فرد"
        )

        win = choice == bot_choice
        draw = False

        result = (
            f"🎲 عدد: {number}\n"
            f"📌 نتیجه: {bot_choice}\n"
        )

    if draw:

        add_money(user_id, amount)

        await update.message.reply_text(
            result +
            "🤝 مساوی شد! سکه‌ات برگشت."
        )

    elif win:

        reward = amount * 2

        add_money(user_id, reward)

        await update.message.reply_text(
            result +
            f"🎉 بردی!\n"
            f"💰 دریافتی: {format_money(reward)}"
        )

    else:

        await update.message.reply_text(
            result +
            f"💀 باختی!\n"
            f"💸 از دست دادی: {format_money(amount)}"
        )


# =========================
# HELP
# =========================

HELP_TEXT = """🤖 راهنمای ملتفت کید

💰 اقتصاد:
موجودی
پول
سکه

🏦 بانک:
بانک
شارژ بانک 10 میل
برداشت بانک 5 میل

💸 انتقال:
روی پیام شخص ریپلای کن و بنویس:
انتقال 5 میل

🎟 سریال:
ساخت سریال 10 میل
سریال CODE

⛏ ماینر:
خرید 5 ماینر
خرید 5 ماینر سطح 2
برداشت ماینر

🎮 بازی‌ها:

سنگ 5 میل
کاغذ 5 میل
قیچی 5 میل

شیر 5 میل
خط 5 میل

راست 5 میل
چپ 5 میل

زوج 5 میل
فرد 5 میل

👑 فعال‌سازی گروه:
فعال
"""


# =========================
# MESSAGE HANDLER
# =========================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    text = update.message.text.strip()

    lower = text.lower()

    user_id = update.message.from_user.id

    ensure_user(user_id)

    # -------------------------
    # فعال کردن گروه
    # -------------------------

    if lower == "فعال":

        if user_id != OWNER_ID:

            await update.message.reply_text(
                "❌ فقط مالک ربات می‌تونه گروه رو فعال کنه."
            )

            return

        if update.effective_chat.type == "private":

            await update.message.reply_text(
                "❌ این دستور برای گروه ساخته شده."
            )

            return

        activate_group(
            update.effective_chat.id
        )

        await update.message.reply_text(
            "✅ گروه فعال شد!\n"
            "🤖 ملتفت کید آماده‌ست."
        )

        return

    # -------------------------
    # گروه فعال نشده
    # -------------------------

    if (
        update.effective_chat.type != "private"
        and
        not group_is_active(
            update.effective_chat.id
        )
    ):

        return

    # -------------------------
    # موجودی
    # -------------------------

    if lower in (
        "موجودی",
        "پول",
        "سکه"
    ):

        await update.message.reply_text(
            f"💰 موجودی تو:\n"
            f"{format_money(get_money(user_id))}"
        )

        return

    # -------------------------
    # بانک
    # -------------------------

    if lower == "بانک":

        await update.message.reply_text(
            f"🏦 موجودی بانک:\n"
            f"{format_money(get_bank(user_id))}"
        )

        return

    if lower.startswith("شارژ بانک "):

        amount = parse_amount(
            text[len("شارژ بانک "):],
            user_id
        )

        await bank_deposit(
            update,
            user_id,
            amount
        )

        return

    if lower.startswith("برداشت بانک "):

        amount_text = (
            text[len("برداشت بانک "):]
            .strip()
            .lower()
        )

        if amount_text in (
            "کل",
            "همه",
            "همش"
        ):

            amount = get_bank(user_id)

        else:

            amount = parse_amount(
                amount_text,
                user_id
            )

        await bank_withdraw(
            update,
            user_id,
            amount
        )

        return

    # -------------------------
    # انتقال
    # -------------------------

    if lower.startswith("انتقال "):

        amount = parse_amount(
            text[len("انتقال "):],
            user_id
        )

        await transfer(
            update,
            user_id,
            amount
        )

        return

    # -------------------------
    # سریال
    # -------------------------

    if lower.startswith("ساخت سریال "):

        amount = parse_amount(
            text[len("ساخت سریال "):],
            user_id
        )

        await create_serial(
            update,
            user_id,
            amount
        )

        return

    if lower.startswith("سریال "):

        code = text[len("سریال "):]

        await use_serial(
            update,
            user_id,
            code
        )

        return

    # -------------------------
    # ماینر
    # -------------------------

    if lower.startswith("خرید ") and "ماینر" in lower:

        parts = text.split()

        try:

            count = int(parts[1])

            level = 1

            if "سطح" in parts:

                index = parts.index("سطح")

                level = int(parts[index + 1])

        except (
            ValueError,
            IndexError
        ):

            await update.message.reply_text(
                "❌ تعداد یا سطح ماینر درست نیست."
            )

            return

        await buy_miner(
            update,
            user_id,
            count,
            level
        )

        return

    if lower == "برداشت ماینر":

        await claim_miner(
            update,
            user_id
        )

        return

    # -------------------------
    # سنگ کاغذ قیچی
    # -------------------------

    for choice in (
        "سنگ",
        "کاغذ",
        "قیچی"
    ):

        if lower.startswith(
            choice + " "
        ):

            amount = parse_amount(
                text[len(choice):],
                user_id
            )

            await game(
                update,
                user_id,
                "rps",
                choice,
                amount
            )

            return

    # -------------------------
    # شیر خط
    # -------------------------

    for choice in (
        "شیر",
        "خط"
    ):

        if lower.startswith(
            choice + " "
        ):

            amount = parse_amount(
                text[len(choice):],
                user_id
            )

            await game(
                update,
                user_id,
                "coin",
                choice,
                amount
            )

            return

    # -------------------------
    # راست چپ
    # -------------------------

    for choice in (
        "راست",
        "چپ"
    ):

        if lower.startswith(
            choice + " "
        ):

            amount = parse_amount(
                text[len(choice):],
                user_id
            )

            await game(
                update,
                user_id,
                "direction",
                choice,
                amount
            )

            return

    # -------------------------
    # زوج فرد
    # -------------------------

    for choice in (
        "زوج",
        "فرد"
    ):

        if lower.startswith(
            choice + " "
        ):

            amount = parse_amount(
                text[len(choice):],
                user_id
            )

            await game(
                update,
                user_id,
                "evenodd",
                choice,
                amount
            )

            return

    # -------------------------
    # راهنما
    # -------------------------

    if lower in (
        "کمک",
        "راهنما",
        "help"
    ):

        await update.message.reply_text(
            HELP_TEXT
        )


# =========================
# ERROR
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        "ERROR:",
        context.error
    )


# =========================
# MAIN
# =========================

def main():

    init_db()

    print(
        "TOKEN FOUND:",
        bool(TOKEN)
    )

    if not TOKEN:

        print(
            "❌ BOT_TOKEN پیدا نشد."
        )

        return

    print(
        "BOT STARTING..."
    )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "🤖 ملتفت کید آنلاین شد!"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
