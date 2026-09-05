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

# ============================================================
# تنظیمات
# ============================================================

TOKEN = "توکن_ربات_اینجا"
OWNER_ID = 123456789

DB_FILE = "moltaf_kid.db"
OWNER_MONEY = 10**100


# ============================================================
# دیتابیس
# ============================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
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


# ============================================================
# کاربران و سکه
# ============================================================

def ensure_user(user_id):
    if user_id == OWNER_ID:
        return

    cur.execute(
        "INSERT OR IGNORE INTO users(user_id, money, bank) VALUES(?, ?, ?)",
        (user_id, 0, 0)
    )
    db.commit()


def get_money(user_id):
    if user_id == OWNER_ID:
        return OWNER_MONEY

    ensure_user(user_id)

    cur.execute(
        "SELECT money FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    if row:
        return row[0]

    return 0


def set_money(user_id, amount):
    if user_id == OWNER_ID:
        return

    ensure_user(user_id)

    cur.execute(
        "UPDATE users SET money=? WHERE user_id=?",
        (max(0, int(amount)), user_id)
    )

    db.commit()


def add_money(user_id, amount):
    if user_id == OWNER_ID:
        return

    set_money(
        user_id,
        get_money(user_id) + int(amount)
    )


def get_bank(user_id):
    ensure_user(user_id)

    cur.execute(
        "SELECT bank FROM users WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    if row:
        return row[0]

    return 0


def set_bank(user_id, amount):
    ensure_user(user_id)

    cur.execute(
        "UPDATE users SET bank=? WHERE user_id=?",
        (max(0, int(amount)), user_id)
    )

    db.commit()


def fmt_money(amount):
    return f"{int(amount):,}"


# ============================================================
# تبدیل مبلغ
# ============================================================

UNITS = {
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


def parse_money(text):
    text = text.strip().lower()
    text = text.replace(",", "")
    text = text.replace("٬", "")

    if text in ("کل", "همه", "همش"):
        return "ALL"

    if text == "نصف":
        return "HALF"

    if text == "خمس":
        return "FIFTH"

    if text == "ثلث":
        return "THIRD"

    parts = text.split()

    if not parts:
        return None

    try:
        if len(parts) == 1:
            return int(parts[0])

        if len(parts) >= 2:
            number = float(parts[0])
            unit = parts[1]

            if unit in UNITS:
                return int(number * UNITS[unit])

    except (ValueError, TypeError):
        return None

    return None


def resolve_amount(user_id, text):
    value = parse_money(text)
    money = get_money(user_id)

    if value == "ALL":
        return money

    if value == "HALF":
        return money // 2

    if value == "FIFTH":
        return money // 5

    if value == "THIRD":
        return money // 3

    if isinstance(value, int):
        return value

    return None


# ============================================================
# فعال کردن گروه
# ============================================================

def is_group_active(chat_id):
    cur.execute(
        "SELECT active FROM groups_active WHERE chat_id=?",
        (chat_id,)
    )

    row = cur.fetchone()

    return bool(row and row[0])


def activate_group(chat_id):
    cur.execute(
        "INSERT OR REPLACE INTO groups_active(chat_id, active) VALUES(?, 1)",
        (chat_id,)
    )

    db.commit()


# ============================================================
# سریال
# ============================================================

def make_serial():
    chars = string.ascii_uppercase + string.digits

    return "".join(
        random.choice(chars)
        for _ in range(20)
    )


def create_serial(amount):
    while True:
        code = make_serial()

        cur.execute(
            "SELECT code FROM serials WHERE code=?",
            (code,)
        )

        if cur.fetchone() is None:
            break

    cur.execute(
        "INSERT INTO serials(code, amount, used) VALUES(?, ?, 0)",
        (code, amount)
    )

    db.commit()

    return code


def use_serial(user_id, code):
    code = code.strip().upper()

    cur.execute(
        "SELECT amount, used FROM serials WHERE code=?",
        (code,)
    )

    row = cur.fetchone()

    if not row:
        return None

    amount, used = row

    if used:
        return 0

    cur.execute(
        "UPDATE serials SET used=1 WHERE code=?",
        (code,)
    )

    db.commit()

    add_money(user_id, amount)

    return amount


# ============================================================
# ماینر
# ============================================================

def miner_price(level):
    return 1_000_000 * (2 ** (level - 1))


def miner_rate(level):
    return 1_000 * (2 ** (level - 1))


def get_miner(user_id):
    cur.execute(
        "SELECT count, level, last_claim FROM miners WHERE user_id=?",
        (user_id,)
    )

    row = cur.fetchone()

    if not row:
        return 0, 1, time.time()

    return row


def save_miner(user_id, count, level, last_claim):
    cur.execute("""
        INSERT OR REPLACE INTO miners(
            user_id,
            count,
            level,
            last_claim
        )
        VALUES(?, ?, ?, ?)
    """, (
        user_id,
        count,
        level,
        last_claim
    ))

    db.commit()


# ============================================================
# سیستم بازی
# ============================================================

def gamble(user_id, amount, win):
    if amount is None:
        return "❌ مبلغ رو درست وارد کن."

    if amount <= 0:
        return "❌ مبلغ باید بیشتر از صفر باشه."

    money = get_money(user_id)

    if money < amount:
        return "❌ سکه کافی نداری."

    set_money(
        user_id,
        money - amount
    )

    if win:
        add_money(
            user_id,
            amount * 2
        )

        return (
            "🎉 بردی!\n"
            f"💰 جایزه: {fmt_money(amount * 2)} سکه"
        )

    return (
        "💀 باختی!\n"
        f"💸 {fmt_money(amount)} سکه از دست رفت."
    )


# ============================================================
# سنگ کاغذ قیچی
# ============================================================

def rps_game(user_id, choice, amount):
    choices = [
        "سنگ",
        "کاغذ",
        "قیچی"
    ]

    bot = random.choice(choices)

    if choice == bot:
        if amount is not None and amount > 0:
            add_money(user_id, amount)

        return (
            "🤝 مساوی شد!\n"
            f"🤖 انتخاب ربات: {bot}\n"
            "💰 سکه‌ات برگشت."
        )

    win = (
        (choice == "سنگ" and bot == "قیچی")
        or
        (choice == "کاغذ" and bot == "سنگ")
        or
        (choice == "قیچی" and bot == "کاغذ")
    )

    result = gamble(
        user_id,
        amount,
        win
    )

    return (
        f"🎮 انتخاب تو: {choice}\n"
        f"🤖 انتخاب ربات: {bot}\n\n"
        f"{result}"
    )


# ============================================================
# شیر خط
# ============================================================

def coin_game(user_id, choice, amount):
    result = random.choice([
        "شیر",
        "خط"
    ])

    win = choice == result

    result_text = gamble(
        user_id,
        amount,
        win
    )

    return (
        f"🪙 نتیجه: {result}\n\n"
        f"{result_text}"
    )


# ============================================================
# راست چپ
# ============================================================

def right_left_game(user_id, choice, amount):
    result = random.choice([
        "راست",
        "چپ"
    ])

    win = choice == result

    result_text = gamble(
        user_id,
        amount,
        win
    )

    return (
        f"🎯 نتیجه: {result}\n\n"
        f"{result_text}"
    )


# ============================================================
# زوج فرد
# ============================================================

def odd_even_game(user_id, choice, amount):
    number = random.randint(1, 100)

    actual = (
        "زوج"
        if number % 2 == 0
        else "فرد"
    )

    win = choice == actual

    result_text = gamble(
        user_id,
        amount,
        win
    )

    return (
        f"🎲 عدد: {number}\n"
        f"📊 نتیجه: {actual}\n\n"
        f"{result_text}"
    )


# ============================================================
# راهنما
# ============================================================

HELP_TEXT = """
🗿 ملتفت کید

💰 اقتصاد:

موجودی
بالانس
سکه

🏦 بانک:

بانک
شارژ بانک 5 بیل
برداشت بانک 5 بیل

🎫 سریال:

ساخت سریال 20 بیل
سریال CODE

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

💸 انتقال:

روی پیام شخص ریپلای کن:

انتقال 5 بیل

👑 فعال کردن گروه:

فعال
"""


# ============================================================
# پردازش پیام
# ============================================================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    user = update.effective_user
    chat = update.effective_chat

    user_id = user.id
    text = update.message.text.strip()
    low = text.lower()

    ensure_user(user_id)

    # --------------------------------------------------------
    # گروه
    # --------------------------------------------------------

    if chat.type in (
        "group",
        "supergroup"
    ):

        if low == "فعال":

            if user_id == OWNER_ID:

                activate_group(chat.id)

                await update.message.reply_text(
                    "ربات فعال شد ✅ ملتفت کید هستم "
                    "سر گرمتون میکنم 🗿"
                )

            return

        if not is_group_active(chat.id):
            return

    # --------------------------------------------------------
    # راهنما
    # --------------------------------------------------------

    if low in (
        "راهنما",
        "کمک",
        "/help"
    ):

        await update.message.reply_text(
            HELP_TEXT
        )

        return

    # --------------------------------------------------------
    # موجودی
    # --------------------------------------------------------

    if low in (
        "موجودی",
        "بالانس",
        "سکه"
    ):

        money = get_money(user_id)
        bank = get_bank(user_id)

        await update.message.reply_text(
            f"💰 کیف پول: {fmt_money(money)} سکه\n"
            f"🏦 بانک: {fmt_money(bank)} سکه"
        )

        return

    # --------------------------------------------------------
    # بانک
    # --------------------------------------------------------

    if low in (
        "بانک",
        "موجودی بانک",
        "موجودی حساب بانکی",
        "موجودی کارت"
    ):

        await update.message.reply_text(
            f"🏦 موجودی بانک: "
            f"{fmt_money(get_bank(user_id))} سکه"
        )

        return

    # --------------------------------------------------------
    # واریز بانک
    # --------------------------------------------------------

    if low.startswith("شارژ بانک "):

        amount_text = text.split(
            " ",
            2
        )[2]

        amount = resolve_amount(
            user_id,
            amount_text
        )

        if amount is None or amount <= 0:

            await update.message.reply_text(
                "❌ مبلغ نامعتبره."
            )

            return

        if get_money(user_id) < amount:

            await update.message.reply_text(
                "❌ سکه کافی نداری."
            )

            return

        set_money(
            user_id,
            get_money(user_id) - amount
        )

        set_bank(
            user_id,
            get_bank(user_id) + amount
        )

        await update.message.reply_text(
            f"🏦 {fmt_money(amount)} سکه "
            "به بانک واریز شد."
        )

        return

    # --------------------------------------------------------
    # برداشت بانک
    # --------------------------------------------------------

    if low.startswith("برداشت بانک "):

        amount_text = text.split(
            " ",
            2
        )[2]

        amount = resolve_amount(
            user_id,
            amount_text
        )

        if amount is None or amount <= 0:

            await update.message.reply_text(
                "❌ مبلغ نامعتبره."
            )

            return

        if get_bank(user_id) < amount:

            await update.message.reply_text(
                "❌ موجودی بانک کافی نیست."
            )

            return

        set_bank(
            user_id,
            get_bank(user_id) - amount
        )

        add_money(
            user_id,
            amount
        )

        await update.message.reply_text(
            f"🏦 {fmt_money(amount)} سکه "
            "برداشت شد."
        )

        return

    # --------------------------------------------------------
    # انتقال
    # --------------------------------------------------------

    if low.startswith("انتقال "):

        reply = update.message.reply_to_message

        if not reply:

            await update.message.reply_text(
                "❌ روی پیام شخص ریپلای کن."
            )

            return

        target = reply.from_user

        if target.is_bot:

            await update.message.reply_text(
                "❌ به ربات نمی‌تونی سکه بدی."
            )

            return

        amount_text = text.split(
            " ",
            1
        )[1]

        amount = resolve_amount(
            user_id,
            amount_text
        )

        if amount is None or amount <= 0:

            await update.message.reply_text(
                "❌ مبلغ نامعتبره."
            )

            return

        if get_money(user_id) < amount:

            await update.message.reply_text(
                "❌ سکه کافی نداری."
            )

            return

        ensure_user(target.id)

        set_money(
            user_id,
            get_money(user_id) - amount
        )

        add_money(
            target.id,
            amount
        )

        await update.message.reply_text(
            "💸 انتقال انجام شد.\n"
            f"👤 {target.first_name}\n"
            f"💰 {fmt_money(amount)} سکه"
        )

        return

    # --------------------------------------------------------
    # ساخت سریال
    # --------------------------------------------------------

    if low.startswith("ساخت سریال "):

        amount_text = text.split(
            " ",
            2
        )[2]

        amount = resolve_amount(
            user_id,
            amount_text
        )

        if amount is None or amount <= 0:

            await update.message.reply_text(
                "❌ مبلغ نامعتبره."
            )

            return

        if user_id != OWNER_ID:

            if get_money(user_id) < amount:

                await update.message.reply_text(
                    "❌ سکه کافی نداری."
                )

                return

            set_money(
                user_id,
                get_money(user_id) - amount
            )

        code = create_serial(
            amount
        )

        await update.message.reply_text(
            "🎫 سریال ساخته شد:\n\n"
            f"{code}\n\n"
            f"💰 ارزش: {fmt_money(amount)} سکه"
        )

        return

    # --------------------------------------------------------
    # فعال کردن سریال
    # --------------------------------------------------------

    if low.startswith("سریال "):

        code = text.split(
            " ",
            1
        )[1].strip()

        amount = use_serial(
            user_id,
            code
        )

        if amount is None:

            await update.message.reply_text(
                "❌ سریال پیدا نشد."
            )

            return

        if amount == 0:

            await update.message.reply_text(
                "❌ این سریال قبلاً استفاده شده."
            )

            return

        await update.message.reply_text(
            "🎫 سریال فعال شد.\n"
            f"💰 +{fmt_money(amount)} سکه"
        )

        return

    # --------------------------------------------------------
    # ماینر
    # --------------------------------------------------------

    if low.startswith("خرید ") and "ماینر" in low:

        parts = low.split()

        try:
            count = int(parts[1])
        except (ValueError, IndexError):

            await update.message.reply_text(
                "❌ تعداد ماینر نامعتبره."
            )

            return

        if count <= 0:

            await update.message.reply_text(
                "❌ تعداد باید بیشتر از صفر باشه."
            )

            return

        level = 1

        if "سطح" in parts:

            try:
                index = parts.index("سطح")
                level = int(parts[index + 1])

            except (ValueError, IndexError):

                await update.message.reply_text(
                    "❌ سطح ماینر نامعتبره."
                )

                return

        if level < 1:

            await update.message.reply_text(
                "❌ سطح نامعتبره."
            )

            return

        price = (
            miner_price(level)
            * count
        )

        if get_money(user_id) < price:

            await update.message.reply_text(
                "❌ سکه کافی نداری.\n"
                f"💰 قیمت: {fmt_money(price)} سکه"
            )

            return

        old_count, old_level, last_claim = get_miner(
            user_id
        )

        if old_count > 0 and old_level != level:

            await update.message.reply_text(
                "❌ ماینرهای قبلی‌ات سطح دیگری دارن."
            )

            return

        set_money(
            user_id,
            get_money(user_id) - price
        )

        save_miner(
            user_id,
            old_count + count,
            level,
            last_claim
        )

        await update.message.reply_text(
            f"⛏ {count} ماینر سطح {level} خریدی.\n"
            f"💸 هزینه: {fmt_money(price)} سکه"
        )

        return

    # --------------------------------------------------------
    # برداشت ماینر
    # --------------------------------------------------------

    if low == "برداشت ماینر":

        count, level, last_claim = get_miner(
            user_id
        )

        if count <= 0:

            await update.message.reply_text(
                "❌ هنوز ماینر نداری."
            )

            return

        now = time.time()

        se
