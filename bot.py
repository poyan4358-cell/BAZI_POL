# -*- coding: utf-8 -*-

import asyncio
import random
import re
import secrets
import sqlite3
import string
import time

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# تنظیمات
# ============================================================

TOKEN = "توکن_بات_را_اینجا_بگذار"

# آیدی عددی مالک بات
OWNER_ID = 123456789

DB_NAME = "moltaf_kid.db"

# درآمد ماینر سطح 1 در هر ثانیه
MINER_BASE_PER_SECOND = 1000

# ============================================================
# دیتابیس
# ============================================================

db = sqlite3.connect(DB_NAME, check_same_thread=False)
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
    created_at INTEGER NOT NULL
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
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER DEFAULT 0
)
""")

db.commit()


# ============================================================
# ابزارهای عمومی
# ============================================================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def ensure_user(user):
    db.execute("""
        INSERT INTO users(user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
    ))
    db.commit()


def get_user(user_id: int):
    return db.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()


def wallet(user_id: int) -> int:
    if is_owner(user_id):
        return 10 ** 30

    row = get_user(user_id)
    return row["wallet"] if row else 0


def bank(user_id: int) -> int:
    if is_owner(user_id):
        return 10 ** 30

    row = get_user(user_id)
    return row["bank"] if row else 0


def add_wallet(user_id: int, amount: int):
    if is_owner(user_id):
        return

    db.execute(
        "UPDATE users SET wallet=wallet+? WHERE user_id=?",
        (amount, user_id)
    )
    db.commit()
    update_record(user_id)


def add_bank(user_id: int, amount: int):
    if is_owner(user_id):
        return

    db.execute(
        "UPDATE users SET bank=bank+? WHERE user_id=?",
        (amount, user_id)
    )
    db.commit()


def update_record(user_id: int):
    if is_owner(user_id):
        return

    db.execute("""
        UPDATE users
        SET record=wallet
        WHERE user_id=? AND wallet>record
    """, (user_id,))
    db.commit()


def get_rank(user_id: int) -> int:
    if is_owner(user_id):
        return 1

    current = wallet(user_id)

    row = db.execute("""
        SELECT COUNT(*) AS c
        FROM users
        WHERE wallet > ?
    """, (current,)).fetchone()

    return row["c"] + 1


def fmt(number: int) -> str:
    return f"{int(number):,}"


# ============================================================
# تبدیل مبلغ
# ============================================================

UNITS = {
    "کا": 10 ** 3,
    "میل": 10 ** 6,
    "بیل": 10 ** 9,
    "تیل": 10 ** 12,
    "کیل": 10 ** 15,
}


def normalize_text(text: str) -> str:
    text = text.lower().strip()

    replacements = {
        "،": "",
        ",": "",
        "_": "",
        "سکه": "",
        "تومان": "",
    }

    for a, b in replacements.items():
        text = text.replace(a, b)

    # فاصله‌های اضافی
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def parse_amount(text: str) -> int:
    """
    نمونه‌های قابل قبول:

    5000
    5 کا
    10 میل
    4 بیل
    4000 میل
    1 تیل
    100 کیل
    """

    text = normalize_text(text)

    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)\s*(کا|میل|بیل|تیل|کیل)?",
        text
    )

    if not match:
        raise ValueError("مبلغ نامعتبر")

    number = float(match.group(1))
    unit = match.group(2)

    if unit:
        number *= UNITS[unit]

    if number <= 0:
        raise ValueError("مبلغ باید بیشتر از صفر باشد")

    if number != int(number):
        raise ValueError("مبلغ باید عدد صحیح باشد")

    return int(number)


def parse_bet(text: str, current_wallet: int) -> int:
    text = normalize_text(text)

    if text in ("کل", "همه", "تمام"):
        amount = current_wallet

    elif text == "نصف":
        amount = current_wallet // 2

    elif text == "ثلث":
        amount = current_wallet // 3

    elif text == "خمس":
        amount = current_wallet // 5

    else:
        amount = parse_amount(text)

    if amount <= 0:
        raise ValueError("شرط صفر است")

    return amount


# ============================================================
# فعال / وضعیت بات
# ============================================================

def is_active(chat_id: int) -> bool:
    row = db.execute(
        "SELECT active FROM settings WHERE chat_id=?",
        (chat_id,)
    ).fetchone()

    return bool(row["active"]) if row else False


def set_active(chat_id: int, value: bool):
    db.execute("""
        INSERT INTO settings(chat_id, active)
        VALUES (?, ?)
        ON CONFLICT(chat_id)
        DO UPDATE SET active=excluded.active
    """, (chat_id, int(value)))

    db.commit()


async def activate(update: Update):
    user = update.effective_user
    chat = update.effective_chat

    if not is_owner(user.id):
        return

    if chat.type not in ("group", "supergroup"):
        return

    set_active(chat.id, True)

    await update.message.reply_text(
        "ربات فعال شد ✅ ملتفت کید هستم سر گرمتون میکنم 🗿"
    )


# ============================================================
# موجودی
# ============================================================

async def show_balance(update: Update):
    user = update.effective_user
    ensure_user(user)

    row = get_user(user.id)

    if is_owner(user.id):
        current = 10 ** 30
        record = 10 ** 30
    else:
        current = row["wallet"]
        record = row["record"]

    rank = get_rank(user.id)

    await update.message.reply_text(
        f"موجودی اکانت شما = {fmt(current)} 💰\n\n"
        f"رکورد بیشترین موجودی شما = {fmt(record)} 💰\n\n"
        f"رتبه شما = {rank:,} 🎖"
    )


# ============================================================
# بانک
# ============================================================

async def show_bank(update: Update):
    user = update.effective_user
    ensure_user(user)

    await update.message.reply_text(
        f"موجودی حساب بانکی شما = {fmt(bank(user.id))} 💰"
    )


async def bank_deposit(update: Update, amount_text: str):
    user = update.effective_user
    ensure_user(user)

    if is_owner(user.id):
        await update.message.reply_text(
            "حساب مالک نامحدود است 🗿"
        )
        return

    try:
        amount = parse_amount(amount_text)
    except ValueError:
        await update.message.reply_text(
            "مبلغ واردشده معتبر نیست ❌"
        )
        return

    current = wallet(user.id)

    if current < amount:
        await update.message.reply_text(
            "موجودی کیف پول شما کافی نیست ❌"
        )
        return

    add_wallet(user.id, -amount)
    add_bank(user.id, amount)

    await update.message.reply_text(
        "مبلغ با موفقیت به حساب بانکی منتقل شد ✅"
    )


async def bank_withdraw(update: Update, amount_text: str):
    user = update.effective_user
    ensure_user(user)

    if is_owner(user.id):
        await update.message.reply_text(
            "حساب مالک نامحدود است 🗿"
        )
        return

    try:
        amount = parse_amount(amount_text)
    except ValueError:
        await update.message.reply_text(
            "مبلغ واردشده معتبر نیست ❌"
        )
        return

    current = bank(user.id)

    if current < amount:
        await update.message.reply_text(
            "موجودی حساب بانکی شما کافی نیست ❌"
        )
        return

    add_bank(user.id, -amount)
    add_wallet(user.id, amount)

    await update.message.reply_text(
        "مبلغ با موفقیت از بانک برداشت شد ✅"
    )


# ============================================================
# انتقال
# ============================================================

async def transfer(update: Update, amount_text: str):
    user = update.effective_user
    ensure_user(user)

    reply = update.message.reply_to_message

    if not reply:
        await update.message.reply_text(
            "برای انتقال باید روی پیام طرف مقابل ریپلای کنی.\n\n"
            "مثال:\n"
            "انتقال 5 بیل"
        )
        return

    target = reply.from_user

    if target.id == user.id:
        await update.message.reply_text(
            "نمی‌تونی به خودت انتقال بدی ❌"
        )
        return

    ensure_user(target)

    try:
        amount = parse_amount(amount_text)
    except ValueError:
        await update.message.reply_text(
            "مبلغ واردشده معتبر نیست ❌"
        )
        return

    sender_before = wallet(user.id)

    if sender_before < amount:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    if not is_owner(user.id):
        add_wallet(user.id, -amount)

    add_wallet(target.id, amount)

    sender_after = wallet(user.id)
    target_after = wallet(target.id)

    await update.message.reply_text(
        "انتقال بمب کوین با موفقیت انجام شد ✅\n\n"
        f"مقدار انتقال = {fmt(amount)} 💰\n\n"
        f"موجودی فعلی شما = {fmt(sender_after)} 💰\n\n"
        f"موجودی طرف مقابل = {fmt(target_after)} 💰"
    )


# ============================================================
# سریال
# ============================================================

def make_serial(length=20):
    chars = string.ascii_letters + string.digits
    return "".join(
        secrets.choice(chars)
        for _ in range(length)
    )


async def create_serial(update: Update, amount_text: str):
    user = update.effective_user
    ensure_user(user)

    try:
        amount = parse_amount(amount_text)
    except ValueError:
        await update.message.reply_text(
            "مبلغ سریال معتبر نیست ❌"
        )
        return

    if not is_owner(user.id) and wallet(user.id) < amount:
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    if not is_owner(user.id):
        add_wallet(user.id, -amount)

    code = make_serial()

    db.execute("""
        INSERT INTO serials(
            code,
            amount,
            creator_id,
            used,
            created_at
        )
        VALUES (?, ?, ?, 0, ?)
    """, (
        code,
        amount,
        user.id,
        int(time.time())
    ))

    db.commit()

    try:
        await update.get_bot().send_message(
            chat_id=user.id,
            text=(
                "سریال با موفقیت ساخته شد ✅\n\n"
                f"مبلغ = {fmt(amount)} 💰\n\n"
                f"کد سریال:\n{code}"
            )
        )

        await update.message.reply_text(
            "کد سریال در پیوی شما ارسال شد ✅"
        )

    except Exception:
        db.execute(
            "DELETE FROM serials WHERE code=?",
            (code,)
        )
        db.commit()

        if not is_owner(user.id):
            add_wallet(user.id, amount)

        await update.message.reply_text(
            "نتونستم به پیوی شما پیام بدم ❌\n"
            "اول به بات خصوصی پیام بده و دوباره امتحان کن."
        )


async def use_serial(update: Update, code: str):
    user = update.effective_user
    ensure_user(user)

    code = code.strip()

    if len(code) != 20:
        await update.message.reply_text(
            "سریال نامعتبر است ❌"
        )
        return

    row = db.execute("""
        SELECT *
        FROM serials
        WHERE code=?
    """, (code,)).fetchone()

    if not row:
        await update.message.reply_text(
            "سریال نامعتبر است ❌"
        )
        return

    if row["used"]:
        await update.message.reply_text(
            "این سریال قبلاً استفاده شده ❌"
        )
        return

    amount = row["amount"]

    db.execute("""
        UPDATE serials
        SET used=1
        WHERE code=?
    """, (code,))

    db.commit()

    add_wallet(user.id, amount)

    await update.message.reply_text(
        "سریال با موفقیت فعال شد ✅\n\n"
        f"مبلغ دریافت‌شده = {fmt(amount)} 💰\n\n"
        f"موجودی فعلی شما = {fmt(wallet(user.id))} 💰"
    )


# ============================================================
# ماینر
# ============================================================

def miner_rate(level: int) -> int:
    return MINER_BASE_PER_SECOND * (2 ** (level - 1))


def miner_price(level: int) -> int:
    # قیمت پایه: سطح 1 = یک میلیون
    return 1_000_000 * (2 ** (level - 1))


def miner_pending(user_id: int) -> int:
    rows = db.execute("""
        SELECT *
        FROM miners
        WHERE user_id=?
    """, (user_id,)).fetchall()

    current = int(time.time())
    total = 0

    for row in rows:
        elapsed = max(0, current - row["last_claim"])
        total += elapsed * miner_rate(row["level"])

    return total


async def buy_miner(update: Update, level_text: str, count_text: str):
    user = update.effective_user
    ensure_user(user)

    try:
        level = int(level_text)
        count = int(count_text)
    except ValueError:
        await update.message.reply_text(
            "سطح یا تعداد ماینر نامعتبر است ❌"
        )
        return

    if level < 1 or count < 1:
        await update.message.reply_text(
            "سطح و تعداد باید بیشتر از صفر باشد ❌"
        )
        return

    # برای جلوگیری از خرید غیرمنطقی ناشی از اشتباه تایپی
    if level > 100:
        await update.message.reply_text(
            "حداکثر سطح ماینر در این نسخه 100 است ❌"
        )
        return

    price_each = miner_price(level)
    total_price = price_each * count

    if wallet(user.id) < total_price:
        await update.message.reply_text(
            "موجودی شما برای خرید این ماینرها کافی نیست ❌"
        )
        return

    if not is_owner(user.id):
        add_wallet(user.id, -total_price)

    current = int(time.time())

    for _ in range(count):
        db.execute("""
            INSERT INTO miners(
                user_id,
                level,
                last_claim
            )
            VALUES (?, ?, ?)
        """, (
            user.id,
            level,
            current
        ))

    db.commit()

    await update.message.reply_text(
        "ماینر با موفقیت خریداری شد ✅\n\n"
        f"سطح ماینر = {level}\n"
        f"تعداد = {fmt(count)}\n"
        f"قیمت هر ماینر = {fmt(price_each)} 💰\n"
        f"هزینه کل = {fmt(total_price)} 💰\n\n"
        f"موجودی فعلی شما = {fmt(wallet(user.id))} 💰"
    )


async def claim_miners(update: Update):
    user = update.effective_user
    ensure_user(user)

    rows = db.execute("""
        SELECT *
        FROM miners
        WHERE user_id=?
    """, (user.id,)).fetchall()

    if not rows:
        await update.message.reply_text(
            "شما هیچ ماینری ندارید ❌"
        )
        return

    current = int(time.time())
    total = 0

    for row in rows:
        elapsed = max(0, current - row["last_claim"])
        total += elapsed * miner_rate(row["level"])

    db.execute(
        "DELETE FROM miners WHERE user_id=?",
        (user.id,)
    )
    db.commit()

    add_wallet(user.id, total)

    await update.message.reply_text(
        "برداشت ماینر با موفقیت انجام شد ✅\n\n"
        f"درآمد ماینرها = {fmt(total)} 💰\n\n"
        f"موجودی فعلی شما = {fmt(wallet(user.id))} 💰"
    )


# ============================================================
# سیستم شرط
# ============================================================

async def take_bet(user_id: int, amount: int):
    current = wallet(user_id)

    if current < amount:
        return False

    if not is_owner(user_id):
        add_wallet(user_id, -amount)

    return True


def win_bet(user_id: int, amount: int):
    # در این مدل، اصل شرط هنگام شروع کم شده
    # و در صورت برد 2 برابر شرط برمی‌گردد.
    add_wallet(user_id, amount * 2)


# ============================================================
# سنگ کاغذ قیچی
#
# استفاده:
# سنگ کل
# سنگ نصف
# سنگ 5 میل
# کاغذ 10 کا
# قیچی 1 بیل
# ============================================================

async def rps_game(update: Update, choice: str, bet_text: str):
    user = update.effective_user
    ensure_user(user)

    choice = choice.lower()

    choices = {
        "سنگ": "سنگ 🪨",
        "کاغذ": "کاغذ 📜",
        "قیچی": "قیچی ✂️",
    }

    if choice not in choices:
        return

    try:
        amount = parse_bet(
            bet_text,
            wallet(user.id)
        )
    except ValueError:
        await update.message.reply_text(
            "مقدار شرط نامعتبر است ❌"
        )
        return

    before = wallet(user.id)

    if not await take_bet(user.id, amount):
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    bot_choice = random.choice(
        list(choices.keys())
    )

    if choice == bot_choice:
        # مساوی: اصل شرط برمی‌گردد
        add_wallet(user.id, amount)

        await update.message.reply_text(
            "مساوی شدید 🤝\n\n"
            f"شما: {choices[choice]}\n"
            f"ربات: {choices[bot_choice]}\n\n"
            f"مقدار شرط = {fmt(amount)} 💰\n"
            f"موجودی فعلی شما = {fmt(wallet(user.id))} 💰"
        )
        return

    wins = (
        (choice == "سنگ" and bot_choice == "قیچی")
        or
        (choice == "کاغذ" and bot_choice == "سنگ")
        or
        (choice == "قیچی" and bot_choice == "کاغذ")
    )

    if wins:
        win_bet(user.id, amount)

        await update.message.reply_text(
            "شما برنده شدید ✅🥳\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"مقدار شرط پول : {fmt(amount)} 💰\n\n"
            f"موجودی قبلی شما : {fmt(before)} 💰\n\n"
            f"موجودی فعلی شما : {fmt(wallet(user.id))} 💰"
        )

    else:
        await update.message.reply_text(
            "شما باختید ❌\n\n"
            f"شما : {choices[choice]}\n"
            f"ربات : {choices[bot_choice]}\n\n"
            f"مقدار شرط پول : {fmt(amount)} 💰\n\n"
            f"موجودی قبلی شما : {fmt(before)} 💰\n\n"
            f"موجودی فعلی شما : {fmt(wallet(user.id))} 💰"
        )


# ============================================================
# شیر یا خط
#
# شیر کل
# خط نصف
# شیر 5 میل
# ============================================================

async def coin_game(update: Update, choice: str, bet_text: str):
    user = update.effective_user
    ensure_user(user)

    if choice not in ("شیر", "خط"):
        return

    try:
        amount = parse_bet(
            bet_text,
            wallet(user.id)
        )
    except ValueError:
        await update.message.reply_text(
            "مقدار شرط نامعتبر است ❌"
        )
        return

    before = wallet(user.id)

    if not await take_bet(user.id, amount):
        await update.message.reply_text(
            "موجودی شما کافی نیست ❌"
        )
        return

    result = random.choice(["شیر", "خط"])

    if choice == result:
        win_bet(user.id, amount)

        await update.message.reply_text(
            "🥳✅ خوشبختانه بردی 🥳✅\n\n"
            f"حدس تو = {choice} ?
