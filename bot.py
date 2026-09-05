import random
import re
import secrets
import sqlite3
import string
import time

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters


# =========================================================
# تنظیمات
# =========================================================

TOKEN = "YOUR_BOT_TOKEN"
OWNER_ID = 123456789

DB_FILE = "moltaf_kid.db"

# موجودی بسیار بزرگ برای صاحب ربات
OWNER_MONEY = 10**100


# =========================================================
# دیتابیس
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    wallet INTEGER DEFAULT 0,
    bank INTEGER DEFAULT 0,
    record INTEGER DEFAULT 0
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS serials (
    code TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    creator_id INTEGER NOT NULL,
    used INTEGER DEFAULT 0,
    created_at INTEGER
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS miners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    last_claim INTEGER NOT NULL
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS groups_active (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER DEFAULT 0
)
""")

db.commit()


# =========================================================
# ابزارهای کاربر
# =========================================================

def ensure_user(user):
    db.execute("""
        INSERT INTO users
        (user_id, username, first_name, wallet, bank, record)
        VALUES (?, ?, ?, 0, 0, 0)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (
        user.id,
        user.username or "",
        user.first_name or ""
    ))

    db.commit()


def get_wallet(user_id):
    if user_id == OWNER_ID:
        return OWNER_MONEY

    row = db.execute(
        "SELECT wallet FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    return row["wallet"] if row else 0


def set_wallet(user_id, amount):
    if user_id == OWNER_ID:
        return

    db.execute(
        "UPDATE users SET wallet=? WHERE user_id=?",
        (max(0, int(amount)), user_id)
    )

    db.commit()


def add_wallet(user_id, amount):
    if user_id == OWNER_ID:
        return

    current = get_wallet(user_id)

    db.execute(
        "UPDATE users SET wallet=? WHERE user_id=?",
        (current + int(amount), user_id)
    )

    db.commit()


def get_bank(user_id):
    row = db.execute(
        "SELECT bank FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    return row["bank"] if row else 0


def add_bank(user_id, amount):
    db.execute(
        "UPDATE users SET bank=bank+? WHERE user_id=?",
        (int(amount), user_id)
    )

    db.commit()


def update_record(user_id):
    if user_id == OWNER_ID:
        return

    wallet = get_wallet(user_id)

    db.execute("""
        UPDATE users
        SET record = CASE
            WHEN record < ? THEN ?
            ELSE record
        END
        WHERE user_id=?
    """, (wallet, wallet, user_id))

    db.commit()


def format_money(amount):
    return f"{int(amount):,}"


# =========================================================
# رتبه
# =========================================================

def get_rank(user_id):
    if user_id == OWNER_ID:
        return 1

    wallet = get_wallet(user_id)

    count = db.execute("""
        SELECT COUNT(*) AS c
        FROM users
        WHERE wallet > ?
        AND user_id != ?
    """, (wallet, OWNER_ID)).fetchone()["c"]

    return count + 2


# =========================================================
# فعال بودن گروه
# =========================================================

def is_active(chat_id):
    row = db.execute(
        "SELECT active FROM groups_active WHERE chat_id=?",
        (chat_id,)
    ).fetchone()

    return bool(row and row["active"])


def activate_group(chat_id):
    db.execute("""
        INSERT INTO groups_active(chat_id, active)
        VALUES (?, 1)
        ON CONFLICT(chat_id) DO UPDATE SET active=1
    """, (chat_id,))

    db.commit()


# =========================================================
# تبدیل مقدار سکه
# =========================================================

UNITS = {
    "کا": 10**3,
    "میل": 10**6,
    "بیل": 10**9,
    "تیل": 10**12,
    "کیل": 10**15
}


def parse_money(text):
    text = text.strip().lower()
    text = text.replace(",", "")
    text = text.replace("٬", "")

    if text in ("کل", "همه"):
        return "ALL"

    if text == "نصف":
        return "HALF"

    if text == "خمس":
        return "FIFTH"

    if text == "ثلث":
        return "THIRD"

    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(کا|میل|بیل|تیل|کیل)?", text)

    if not m:
        return None

    number = float(m.group(1))
    unit = m.group(2)

    if unit:
        return int(number * UNITS[unit])

    return int(number)


def resolve_bet(text, balance):
    parsed = parse_money(text)

    if parsed == "ALL":
        return balance

    if parsed == "HALF":
        return balance // 2

    if parsed == "FIFTH":
        return balance // 5

    if parsed == "THIRD":
        return balance // 3

    if isinstance(parsed, int):
        return parsed

    return None


# =========================================================
# شرط
# =========================================================

def take_bet(user_id, amount):
    balance = get_wallet(user_id)

    if amount <= 0:
        return False, balance

    if user_id != OWNER_ID and balance < amount:
        return False, balance

    if user_id != OWNER_ID:
        set_wallet(user_id, balance - amount)

    return True, balance


def win_bet(user_id, amount):
    if user_id != OWNER_ID:
        add_wallet(user_id, amount * 2)

    return get_wallet(user_id)


def lose_bet(user_id):
    return get_wallet(user_id)


# =========================================================
# موجودی
# =========================================================

async def balance_command(update):
    user = update.effective_user
    ensure_user(user)

    wallet = get_wallet(user.id)

    if user.id == OWNER_ID:
        record = "نامحدود"
        rank = 1
    else:
        row = db.execute(
            "SELECT record FROM users WHERE user_id=?",
            (user.id,)
        ).fetchone()

        record = row["record"] if row else 0
        rank = get_rank(user.id)

    await update.message.reply_text(
        f"موجودی اکانت شما = {format_money(wallet)} 💰\n\n"
        f"رکورد بیشترین موجودی شما = "
        f"{record if record == 'نامحدود' else format_money(record)} 💰\n\n"
        f"رتبه شما = {format_money(rank)} 🎖"
    )


# =========================================================
# بانک
# =========================================================

async def bank_command(update):
    user = update.effective_user
    ensure_user(user)

    bank = get_bank(user.id)

    await update.message.reply_text(
        f"موجودی حساب بانکی شما = {format_money(bank)} 💰"
    )


async def bank_deposit(update, amount_text):
    user = update.effective_user
    ensure_user(user)

    wallet = get_wallet(user.id)
    amount = resolve_bet(amount_text, wallet)

    if amount is None or amount <= 0:
        return

    if user.id != OWNER_ID and wallet < amount:
        await update.message.reply_text("موجودی شما کافی نیست ❌")
        return

    if user.id != OWNER_ID:
        set_wallet(user.id, wallet - amount)

    add_bank(user.id, amount)

    await update.message.reply_text(
        f"واریز به بانک با موفقیت انجام شد ✅\n\n"
        f"مقدار واریز = {format_money(amount)} 💰\n\n"
        f"موجودی فعلی بانک = {format_money(get_bank(user.id))} 💰"
    )


async def bank_withdraw(update, amount_text):
    user = update.effective_user
    ensure_user(user)

    bank = get_bank(user.id)
    amount = resolve_bet(amount_text, bank)

    if amount is None or amount <= 0:
        return

    if bank < amount:
        await update.message.reply_text("موجودی حساب بانکی شما کافی نیست ❌")
        return

    add_bank(user.id, -amount)

    if user.id != OWNER_ID:
        add_wallet(user.id, amount)

    await update.message.reply_text(
        f"برداشت از بانک با موفقیت انجام شد ✅\n\n"
        f"مقدار برداشت = {format_money(amount)} 💰\n\n"
        f"موجودی فعلی بانک = {format_money(get_bank(user.id))} 💰"
    )


# =========================================================
# انتقال سکه
# =========================================================

async def transfer_command(update, amount_text):
    user = update.effective_user
    ensure_user(user)

    message = update.message

    if not message.reply_to_message:
        await message.reply_text(
            "برای انتقال سکه باید روی پیام طرف ریپلای کنی ❌"
        )
        return

    target = message.reply_to_message.from_user

    if not target:
        return

    if target.id == user.id:
        await message.reply_text("نمیشه به خودت سکه انتقال بدی 😂")
        return

    ensure_user(target)

    balance = get_wallet(user.id)
    amount = resolve_bet(amount_text, balance)

    if amount is None or amount <= 0:
        await message.reply_text("مقدار سکه اشتباهه ❌")
        return

    if user.id != OWNER_ID and balance < amount:
        await message.reply_text("موجودی شما کافی نیست ❌")
        return

    if user.id != OWNER_ID:
        set_wallet(user.id, balance - amount)

    add_wallet(target.id, amount)

    update_record(user.id)
    update_record(target.id)

    await message.reply_text(
        f"انتقال سکه با موفقیت انجام شد ✅\n\n"
        f"مقدار انتقال = {format_money(amount)} 💰\n\n"
        f"موجودی فعلی شما = {format_money(get_wallet(user.id))} 💰\n\n"
        f"موجودی طرف مقابل = {format_money(get_wallet(target.id))} 💰"
    )


# =========================================================
# ساخت سریال
# =========================================================

def create_code():
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(20))


async def create_serial(update, amount_text):
    user = update.effective_user
    ensure_user(user)

    balance = get_wallet(user.id)
    amount = resolve_bet(amount_text, balance)

    if amount is None or amount <= 0:
        await update.message.reply_text("مقدار سریال اشتباهه ❌")
        return

    if user.id != OWNER_ID and balance < amount:
        await update.message.reply_text("موجودی شما کافی نیست ❌")
        return

    code = create_code()

    if user.id != OWNER_ID:
        set_wallet(user.id, balance - amount)

    db.execute("""
        INSERT INTO serials(code, amount, creator_id, used, created_at)
        VALUES (?, ?, ?, 0, ?)
    """, (
        code,
        amount,
        user.id,
        int(time.time())
    ))

    db.commit()

    try:
        await update.effective_chat.send_message(
            f"سریال ساخته شد ✅\n\n"
            f"مقدار سریال = {format_money(amount)} 💰\n\n"
            f"کد سریال:\n"
            f"`{code}`",
            parse_mode="Markdown"
        )

    except Exception:
        db.execute(
            "DELETE FROM serials WHERE code=?",
            (code,)
        )
        db.commit()

        if user.id != OWNER_ID:
            add_wallet(user.id, amount)

        await update.message.reply_text(
            "نتونستم سریال رو ارسال کنم ❌"
        )


async def use_serial(update, code):
    user = update.effective_user
    ensure_user(user)

    code = code.strip()

    row = db.execute(
        "SELECT * FROM serials WHERE code=? AND used=0",
        (code,)
    ).fetchone()

    if not row:
        await update.message.reply_text(
            "این سریال نامعتبره یا قبلاً استفاده شده ❌"
        )
        return

    amount = row["amount"]

    db.execute(
        "UPDATE serials SET used=1 WHERE code=?",
        (code,)
    )

    db.commit()

    add_wallet(user.id, amount)
    update_record(user.id)

    await update.message.reply_text(
        f"سریال با موفقیت فعال شد ✅\n\n"
        f"سکه دریافت‌شده = {format_money(amount)} 💰\n\n"
        f"موجودی فعلی شما = {format_money(get_wallet(user.id))} 💰"
    )


# =========================================================
# ماینر
# =========================================================

def miner_price(level):
    return 1_000_000 * (2 ** (level - 1))


def miner_rate(level):
    return 1_000 * (2 ** (level - 1))


def miner_stats(user_id):
    rows = db.execute(
        "SELECT * FROM miners WHERE user_id=?",
        (user_id,)
    ).fetchall()

    total = 0

    for row in rows:
        elapsed = max(0, int(time.time()) - row["last_claim"])
        total += elapsed * miner_rate(row["level"])

    return rows, total


async def buy_miner(update, count, level):
    user = update.effective_user
    ensure_user(user)

    if count <= 0 or level <= 0:
        return

    price_each = miner_price(level)
    total_price = price_each * count

    balance = get_wallet(user.id)

    if user.id != OWNER_ID and balance < total_price:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    if user.id != OWNER_ID:
        set_wallet(user.id, balance - total_price)

    now = int(time.time())

    for _ in range(count):
        db.execute("""
            INSERT INTO miners(user_id, level, last_claim)
            VALUES (?, ?, ?)
        """, (
            user.id,
            level,
            now
        ))

    db.commit()

    await update.message.reply_text(
        f"خرید ماینر با موفقیت انجام شد ✅\n\n"
        f"تعداد = {format_money(count)} ماینر\n"
        f"سطح = {level}\n\n"
        f"قیمت هر ماینر = {format_money(price_each)} 💰\n"
        f"مبلغ پرداختی = {format_money(total_price)} 💰\n\n"
        f"تولید هر ماینر = "
        f"{format_money(miner_rate(level))} سکه در ثانیه 💰"
    )


async def claim_miner(update):
    user = update.effective_user
    ensure_user(user)

    rows, earned = miner_stats(user.id)

    if not rows:
        await update.message.reply_text(
            "شما هیچ ماینری ندارید ❌"
        )
        return

    count = len(rows)

    db.execute(
        "DELETE FROM miners WHERE user_id=?",
        (user.id,)
    )

    db.commit()

    if user.id != OWNER_ID:
        add_wallet(user.id, earned)

    update_record(user.id)

    await update.message.reply_text(
        f"برداشت ماینر با موفقیت انجام شد ✅\n\n"
        f"تعداد ماینر = {format_money(count)}\n\n"
        f"سکه تولیدشده = {format_money(earned)} 💰\n\n"
        f"موجودی فعلی شما = "
        f"{format_money(get_wallet(user.id))} 💰"
    )


# =========================================================
# سنگ کاغذ قیچی
# =========================================================

async def rps_game(update, choice, bet_text):
    user = update.effective_user
    ensure_user(user)

    choices = {
        "سنگ": "سنگ 🪨",
        "کاغذ": "کاغذ 📜",
        "قیچی": "قیچی ✂️"
    }

    if choice not in choices:
        return

    balance = get_wallet(user.id)
    bet = resolve_bet(bet_text, balance)

    if bet is None or bet <= 0:
        await update.message.reply_text("مقدار شرط اشتباهه ❌")
        return

    ok, old_balance = take_bet(user.id, bet)

    if not ok:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    bot_choice = random.choice(list(choices.keys()))

    wins = {
        ("سنگ", "قیچی"),
        ("کاغذ", "سنگ"),
        ("قیچی", "کاغذ")
    }

    if choice == bot_choice:
        result = "tie"
    elif (choice, bot_choice) in wins:
        result = "win"
    else:
        result = "lose"

    if result == "win":
        current = win_bet(user.id, bet)

        text = (
            f"شما برنده شدید ✅🥳\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"مقدار شرط پول : {format_money(bet)} 💰\n\n"
            f"موجودی قبلی شما : {format_money(old_balance)} 💰\n\n"
            f"موجودی فعلی شما : {format_money(current)} 💰"
        )

    elif result == "lose":
        current = lose_bet(user.id)

        text = (
            f"شما باختید ❌\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"مقدار شرط پول : {format_money(bet)} 💰\n\n"
            f"موجودی قبلی شما : {format_money(old_balance)} 💰\n\n"
            f"موجودی فعلی شما : {format_money(current)} 💰"
        )

    else:
        if user.id != OWNER_ID:
            add_wallet(user.id, bet)

        current = get_wallet(user.id)

        text = (
            f"مساوی شدید 😐\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"مقدار شرط پول : {format_money(bet)} 💰\n\n"
            f"موجودی قبلی شما : {format_money(old_balance)} 💰\n\n"
            f"موجودی فعلی شما : {format_money(current)} 💰"
        )

    update_record(user.id)

    await update.message.reply_text(text)


# =========================================================
# شیر یا خط
# =========================================================

async def coin_game(update, guess, bet_text):
    user = update.effective_user
    ensure_user(user)

    balance = get_wallet(user.id)
    bet = resolve_bet(bet_text, balance)

    if bet is None or bet <= 0:
        await update.message.reply_text("مقدار شرط اشتباهه ❌")
        return

    ok, old_balance = take_bet(user.id, bet)

    if not ok:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    result = random.choice(["شیر", "خط"])

    if guess == result:
        current = win_bet(user.id, bet)

        text = (
            f"🥳✅ خوشبختانه بردی 🥳✅\n\n"
            f"حدس تو = {guess} 💡\n"
            f"سمت رو شده = {result} 🪙\n\n"
            f"مقدار سکه شرط = {format_money(bet)} 💰\n\n"
            f"موجودی قبلی شما = {format_money(old_balance)} 💰\n\n"
            f"موجودی فعلی شما = {format_money(current)} 💰"
        )

    else:
        current = lose_bet(user.id)

        text = (
            f"🙁❌ متاسفانه باختی ❌🙁\n\n"
            f"حدس تو = {guess} 💡\n"
            f"سمت رو شده = {result} 🪙\n\n"
            f"مقدار سکه شرط = {format_money(bet)} 💰\n\n"
            f"موجودی قبلی شما = {format_money(old_balance)} 💰\n\n"
            f"موجودی فعلی شما = {format_money(current)} 💰"
        )

    update_record(user.id)

    await update.message.reply_text(text)


# =========================================================
# راست یا چپ
# =========================================================

async def right_left_game(update, guess, bet_text):
    user = update.effective_user
    ensure_user(user)

    balance = get_wallet(user.id)
    bet = resolve_bet(bet_text, balance)

    if bet is None or bet <= 0:
        await update.message.reply_text("مقدار شرط اشتباهه ❌")
        return

    ok, old_balance = take_bet(user.id, bet)

    if not ok:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    result = random.choice(["راست", "چپ"])

    if guess == result:
        current = win_bet(user.id, bet)

        text = (
            f"🥳✅ خوشبختانه برنده شدی 🥳✅\n\n"
            f"╭✦───✧◈✧───✦╮\n"
            f"     ✋️          🪸\n"
            f"╰✦───✧◈✧───✦╯\n\n"
            f"حدس شما : دست {guess} ✨\n\n"
            f"مقدار شرط سکه = {format_money(bet)} 💰\n\n"
            f"موجودی قبلی شما = {format_money(old_balance)} 💰\n\n"
            f"موجودی فعلی شما = {format_money(current)} 💰"
        )

    else:
        current = lose_bet(user.id)

        text = (
            f"😔❌ متاسفانه باختی ❌😔\n\n"
            f"╭✦───✧◈✧───✦╮\n"
            f"     ✋️          🪻\n"
    
