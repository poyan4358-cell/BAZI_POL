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

# =========================================================
# SETTINGS
# =========================================================

TOKEN = "توکن_ربات_اینجا"
OWNER_ID = 123456789

DB_FILE = "moltaf_kid.db"
OWNER_MONEY = 10**100


# =========================================================
# DATABASE
# =========================================================

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


# =========================================================
# USER / MONEY
# =========================================================

def ensure_user(user_id):
    if user_id == OWNER_ID:
        return

    cur = db.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, money, bank) VALUES (?, 0, 0)",
        (user_id,)
    )
    db.commit()


def get_money(user_id):
    if user_id == OWNER_ID:
        return OWNER_MONEY

    ensure_user(user_id)

    cur = db.cursor()
    cur.execute("SELECT money FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    return row["money"] if row else 0


def get_bank(user_id):
    ensure_user(user_id)

    cur = db.cursor()
    cur.execute("SELECT bank FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    return row["bank"] if row else 0


def add_money(user_id, amount):
    if user_id == OWNER_ID:
        return

    ensure_user(user_id)

    cur = db.cursor()
    cur.execute(
        "UPDATE users SET money = money + ? WHERE user_id = ?",
        (amount, user_id)
    )
    db.commit()


def remove_money(user_id, amount):
    if user_id == OWNER_ID:
        return True

    ensure_user(user_id)

    current = get_money(user_id)

    if current < amount:
        return False

    cur = db.cursor()
    cur.execute(
        "UPDATE users SET money = money - ? WHERE user_id = ?",
        (amount, user_id)
    )
    db.commit()

    return True


def add_bank(user_id, amount):
    ensure_user(user_id)

    cur = db.cursor()
    cur.execute(
        "UPDATE users SET bank = bank + ? WHERE user_id = ?",
        (amount, user_id)
    )
    db.commit()


def remove_bank(user_id, amount):
    ensure_user(user_id)

    current = get_bank(user_id)

    if current < amount:
        return False

    cur = db.cursor()
    cur.execute(
        "UPDATE users SET bank = bank - ? WHERE user_id = ?",
        (amount, user_id)
    )
    db.commit()

    return True


# =========================================================
# NUMBER PARSER
# =========================================================

def parse_amount(text, user_id):
    text = text.strip().lower()

    money = get_money(user_id)

    if text in ["کل", "همه", "همش"]:
        return money

    if text == "نصف":
        return money // 2

    if text == "خمس":
        return money // 5

    if text == "ثلث":
        return money // 3

    multipliers = {
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

    parts = text.replace(",", "").split()

    if len(parts) == 1:
        try:
            return int(parts[0])
        except:
            return None

    try:
        number = int(parts[0])
        unit = parts[1]

        if unit in multipliers:
            return number * multipliers[unit]

    except:
        pass

    return None


# =========================================================
# GROUP ACTIVATION
# =========================================================

def group_is_active(chat_id):
    cur = db.cursor()
    cur.execute(
        "SELECT active FROM groups_active WHERE chat_id = ?",
        (chat_id,)
    )
    row = cur.fetchone()

    return bool(row["active"]) if row else False


def activate_group(chat_id):
    cur = db.cursor()

    cur.execute("""
        INSERT INTO groups_active (chat_id, active)
        VALUES (?, 1)
        ON CONFLICT(chat_id)
        DO UPDATE SET active = 1
    """, (chat_id,))

    db.commit()


# =========================================================
# FORMAT MONEY
# =========================================================

def format_money(amount):
    if amount >= 10**18:
        return f"{amount / 10**18:.2f} کواد سکه"

    if amount >= 10**15:
        return f"{amount / 10**15:.2f} کیل سکه"

    if amount >= 10**12:
        return f"{amount / 10**12:.2f} تیل سکه"

    if amount >= 10**9:
        return f"{amount / 10**9:.2f} بیل سکه"

    if amount >= 10**6:
        return f"{amount / 10**6:.2f} میل سکه"

    if amount >= 10**3:
        return f"{amount / 10**3:.2f} کا سکه"

    return f"{amount:,} سکه"


# =========================================================
# MINERS
# =========================================================

def get_miner_data(user_id):
    cur = db.cursor()

    cur.execute(
        "SELECT * FROM miners WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()

    if not row:
        cur.execute("""
            INSERT INTO miners
            (user_id, count, level, last_claim)
            VALUES (?, 0, 1, ?)
        """, (user_id, time.time()))

        db.commit()

        return {
            "count": 0,
            "level": 1,
            "last_claim": time.time()
        }

    return {
        "count": row["count"],
        "level": row["level"],
        "last_claim": row["last_claim"]
    }


def buy_miners(user_id, count, level):
    price_each = 1_000_000 * (2 ** (level - 1))
    total = price_each * count

    if user_id != OWNER_ID:
        if not remove_money(user_id, total):
            return False, total

    cur = db.cursor()

    cur.execute(
        "SELECT count FROM miners WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()

    if row:
        cur.execute("""
            UPDATE miners
            SET count = count + ?, level = ?
            WHERE user_id = ?
        """, (count, level, user_id))
    else:
        cur.execute("""
            INSERT INTO miners
            (user_id, count, level, last_claim)
            VALUES (?, ?, ?, ?)
        """, (user_id, count, level, time.time()))

    db.commit()

    return True, total


def claim_miners(user_id):
    data = get_miner_data(user_id)

    count = data["count"]
    level = data["level"]
    last_claim = data["last_claim"]

    if count <= 0:
        return 0

    now = time.time()

    elapsed = int(now - last_claim)

    if elapsed <= 0:
        return 0

    rate = 1000 * level
    reward = elapsed * count * rate

    cur = db.cursor()

    cur.execute("""
        UPDATE miners
        SET last_claim = ?
        WHERE user_id = ?
    """, (now, user_id))

    db.commit()

    add_money(user_id, reward)

    return reward


# =========================================================
# GAMES
# =========================================================

async def gamble(update, user_id, amount, win, tie=False):
    if amount is None or amount <= 0:
        await update.message.reply_text("❌ مقدار سکه درست نیست.")
        return

    if user_id != OWNER_ID and get_money(user_id) < amount:
        await update.message.reply_text("❌ سکه کافی نداری.")
        return

    if user_id != OWNER_ID:
        remove_money(user_id, amount)

    if tie:
        if user_id != OWNER_ID:
            add_money(user_id, amount)

        await update.message.reply_text(
            f"🤝 مساوی شد!\n\n"
            f"💰 {format_money(amount)} برگشت داده شد."
        )
        return

    if win:
        reward = amount * 2

        if user_id != OWNER_ID:
            add_money(user_id, reward)

        await update.message.reply_text(
            f"🎉 بردی!\n\n"
            f"💰 جایزه: {format_money(reward)}"
        )

    else:
        await update.message.reply_text(
            f"💀 باختی!\n\n"
            f"💸 از دست دادی: {format_money(amount)}"
        )


# =========================================================
# HELP
# =========================================================

HELP_TEXT = """
╭━━━━━━━ ✦ ملتفت کید ✦ ━━━━━━━╮

💰 اقتصاد:

موجودی
بالانس
سکه

بانک
موجودی بانک
شارژ بانک 10 میل
برداشت بانک 5 میل

💸 انتقال:

روی پیام شخص ریپلای کن:
انتقال 5 میل

🎟 سریال:

ساخت سریال 10 میل
سریال ABC123

⛏ ماینر:

خرید 5 ماینر
خرید 5 ماینر سطح 2
برداشت ماینر

🎮 بازی:

سنگ 5 میل
کاغذ 5 میل
قیچی 5 میل

شیر 5 میل
خط 5 میل

راست 5 میل
چپ 5 میل

زوج 5 میل
فرد 5 میل

⚙️ مدیریت:

فعال

━━━━━━━━━━━━━━━━━━━━

💰 واحد اصلی اقتصاد: سکه

╰━━━━━━━ ✦ ملتفت کید ✦ ━━━━━━━╯
"""


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    text = update.message.text.strip()
    user = update.effective_user
    user_id = user.id
    chat = update.effective_chat

    ensure_user(user_id)

    # -----------------------------------------------------
    # ACTIVATE GROUP
    # -----------------------------------------------------

    if text == "فعال":

        if user_id != OWNER_ID:
            return

        if chat.type in ["group", "supergroup"]:
            activate_group(chat.id)

        await update.message.reply_text(
            "ربات فعال شد ✅\n"
            "ملتفت کید هستم، سر گرمتون میکنم 🗿"
        )

        return

    # -----------------------------------------------------
    # GROUP CHECK
    # -----------------------------------------------------

    if chat.type in ["group", "supergroup"]:

        if not group_is_active(chat.id):
            return

    # -----------------------------------------------------
    # HELP
    # -----------------------------------------------------

    if text in ["راهنما", "کمک", "/help"]:

        await update.message.reply_text(HELP_TEXT)
        return

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    if text in ["موجودی", "بالانس", "سکه"]:

        money = get_money(user_id)

        await update.message.reply_text(
            f"💰 موجودی کیف پول:\n\n"
            f"{format_money(money)}"
        )

        return

    # -----------------------------------------------------
    # BANK
    # -----------------------------------------------------

    if text in [
        "بانک",
        "موجودی بانک",
        "موجودی حساب بانکی",
        "موجودی کارت"
    ]:

        bank = get_bank(user_id)

        await update.message.reply_text(
            f"🏦 موجودی بانک:\n\n"
            f"{format_money(bank)}"
        )

        return

    # -----------------------------------------------------
    # BANK DEPOSIT
    # -----------------------------------------------------

    if text.startswith("شارژ بانک "):

        amount_text = text[len("شارژ بانک "):].strip()

        amount = parse_amount(amount_text, user_id)

        if amount is None or amount <= 0:
            await update.message.reply_text(
                "❌ مقدار درست وارد کن."
            )
            return

        if user_id != OWNER_ID:

            if get_money(user_id) < amount:
                await update.message.reply_text(
                    "❌ سکه کافی نداری."
                )
                return

            remove_money(user_id, amount)

        add_bank(user_id, amount)

        await update.message.reply_text(
            f"🏦 مبلغ {format_money(amount)} "
            f"به بانک منتقل شد."
        )

        return

    # -----------------------------------------------------
    # BANK WITHDRAW
    # -----------------------------------------------------

    if text.startswith("برداشت بانک "):

        amount_text = text[len("برداشت بانک "):].strip()

        amount = parse_amount(amount_text, user_id)

        if amount is None or amount <= 0:
            await update.message.reply_text(
                "❌ مقدار درست وارد کن."
            )
            return

        if not remove_bank(user_id, amount):
            await update.message.reply_text(
                "❌ موجودی بانک کافی نیست."
            )
            return

        add_money(user_id, amount)

        await update.message.reply_text(
            f"💳 مبلغ {format_money(amount)} "
            f"به کیف پول منتقل شد."
        )

        return

    # -----------------------------------------------------
    # TRANSFER
    # -----------------------------------------------------

    if text.startswith("انتقال "):

        if not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ باید روی پیام شخص موردنظر ریپلای کنی."
            )
            return

        target = update.message.reply_to_message.from_user

        if target.id == user_id:
            await update.message.reply_text(
                "😂 به خودت که نمیشه انتقال داد."
            )
            return

        amount_text = text[len("انتقال "):].strip()

        amount = parse_amount(amount_text, user_id)

        if amount is None or amount <= 0:
            await update.message.reply_text(
                "❌ مقدار انتقال درست نیست."
            )
            return

        if user_id != OWNER_ID:

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

        return

    # -----------------------------------------------------
    # CREATE SERIAL
    # -----------------------------------------------------

    if text.startswith("ساخت سریال "):

        amount_text = text[len("ساخت سریال "):].strip()

        amount = parse_amount(amount_text, user_id)

        if amount is None or amount <= 0:
            await update.message.reply_text(
                "❌ مبلغ سریال درست نیست."
            )
            return

        if user_id != OWNER_ID:

            if not remove_money(user_id, amount):
                await update.message.reply_text(
                    "❌ سکه کافی نداری."
                )
                return

        code = "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=20
            )
        )

        cur = db.cursor()

        cur.execute("""
            INSERT INTO serials
            (code, amount, used)
            VALUES (?, ?, 0)
        """, (code, amount))

        db.commit()

        await update.message.reply_text(
            f"🎟 سریال ساخته شد!\n\n"
            f"`{code}`\n\n"
            f"💰 ارزش: {format_money(amount)}",
            parse_mode="Markdown"
        )

        return

    # -----------------------------------------------------
    # USE SERIAL
    # -----------------------------------------------------

    if text.startswith("سریال "):

        code = text[len("سریال "):].strip().upper()

        cur = db.cursor()

        cur.execute(
            "SELECT * FROM serials WHERE code = ?",
            (code,)
        )

        row = cur.fetchone()

        if not row:
            await update.message.reply_text(
                "❌ این سریال وجود ندارد."
            )
            return

        if row["used"]:
            await update.message.reply_text(
                "❌ این سریال قبلاً استفاده شده."
            )
            return

        amount = row["amount"]

        cur.execute(
            "UPDATE serials SET used = 1 WHERE code = ?",
            (code,)
        )

        db.commit()

        add_money(user_id, amount)

        await update.message.reply_text(
            f"🎉 سریال با موفقیت فعال شد!\n\n"
            f"💰 دریافت کردی: {format_money(amount)}"
        )

        return

    # -----------------------------------------------------
    # BUY MINER
    # -----------------------------------------------------

    if text.startswith("خرید ") and "ماینر" in text:

        parts = text.split()

        try:
            count = int(parts[1])
        except:
            await update.message.reply_text(
                "❌ تعداد ماینر درست نیست."
            )
            return

        level = 1

        if "سطح" in parts:

            try:
                index = parts.index("سطح")
                level = int(parts[index + 1])
            except:
                level = 1

        if count <= 0 or count > 100000:
            await update.message.reply_text(
                "❌ تعداد ماینر نامعتبر است."
            )
            return

        if level < 1 or level > 100:
            await update.message.reply_text(
                "❌ سطح ماینر باید بین 1 تا 100 باشد."
            )
            return

        success, total = buy_miners(
            user_id,
            count,
            level
        )

        if not success:
            await update.message.reply_text(
                f"❌ سکه کافی نداری.\n\n"
                f"💰 قیمت: {format_money(total)}"
            )
            return

        await update.message.reply_text(
            f"⛏ خرید ماینر انجام شد!\n\n"
            f"🔢 تعداد: {count}\n"
            f"⭐ سطح: {level}\n"
            f"💰 هزینه: {format_money(total)}"
        )

        return

    # -----------------------------------------------------
    # CLAIM MINER
    # -----------------------------------------------------

    if text == "برداشت ماینر":

        reward = claim_miners(user_id)

        if reward <= 0:

            data = get_miner_data(user_id)

            if data["count"] <= 0:
                await update.message.reply_text(
                    "⛏ هنوز ماینری نداری."
                )
            else:
                await update.message.reply_text(
                    "⏳ هنوز چیزی برای برداشت جمع نشده."
                )

            return

        await update.message.reply_text(
            f"⛏ برداشت انجام شد!\n\n"
            f"💰 دریافت کردی: {format_money(reward)}"
        )

        return

    # -----------------------------------------------------
    # ROCK PAPER SCISSORS
    # -----------------------------------------------------

    for command in ["سنگ", "کاغذ", "قیچی"]:

        if text.startswith(command + " "):

            amount_text = text[len(command) + 1:].strip()

            amount = parse_amount(
                amount_text,
                user_id
            )

            if amount is None or amount <= 0:
                await update.message.reply_text(
                    "❌ مقدار شرط درست نیست."
                )
                return

            bot_choice = random.choice(
                ["سنگ", "کاغذ", "قیچی"]
            )

            user_choice = command

            if user_choice == bot_choice:

             
