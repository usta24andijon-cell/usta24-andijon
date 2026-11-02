
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# -------------------- SOZLAMALAR --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}
DB_PATH = os.getenv("DB_PATH", "usta24.db")
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_HOLDER = os.getenv("CARD_HOLDER", "USTA 24 ANDIJON").strip()

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. .env fayliga BOT_TOKEN=... қаторини киритинг."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("usta24")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

CATEGORIES = [
    "⚡ Электрик",
    "🚿 Сантехник",
    "❄️ Кондиционер устаси",
    "🧱 Қурилиш ва таъмирлаш",
    "🪑 Мебель устаси",
    "🧺 Маиший техника таъмири",
    "🎨 Бўёқчи ва пардозчи",
    "🔐 Қулф ва эшик устаси",
    "🚗 Автоэлектрик",
    "🔧 Бошқа хизматлар",
]


# -------------------- FSM ҲОЛАТЛАРИ --------------------
class Registration(StatesGroup):
    name = State()
    phone = State()
    district = State()
    role = State()


class MasterApplication(StatesGroup):
    category = State()
    experience = State()
    about = State()


class OrderForm(StatesGroup):
    category = State()
    description = State()
    address = State()
    phone = State()
    photo = State()
    payment = State()
    receipt = State()


class SupportForm(StatesGroup):
    message = State()


class ReviewForm(StatesGroup):
    comment = State()


class BroadcastForm(StatesGroup):
    message = State()


# -------------------- КЛАВИАТУРАЛАР --------------------
def main_menu(role: str = "client", is_admin: bool = False):
    rows = [
        [KeyboardButton(text="🔍 Уста топиш"), KeyboardButton(text="📝 Буюртма бериш")],
        [KeyboardButton(text="👨‍🔧 Уста бўлиш"), KeyboardButton(text="📋 Буюртмаларим")],
        [KeyboardButton(text="👤 Шахсий кабинет"), KeyboardButton(text="⭐ Баҳолар")],
        [KeyboardButton(text="❤️ Севимли усталар"), KeyboardButton(text="☎️ Ёрдам")],
    ]
    if role == "master":
        rows.insert(1, [KeyboardButton(text="📥 Усталар учун буюртмалар")])
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Админ панели")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def categories_markup(prefix: str):
    builder = InlineKeyboardBuilder()
    for index, category in enumerate(CATEGORIES):
        builder.button(text=category, callback_data=f"{prefix}:{index}")
    builder.adjust(2)
    return builder.as_markup()


def admin_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👨‍🔧 Усталарни тасдиқлаш", callback_data="admin:masters")],
        [InlineKeyboardButton(text="💳 Тўловларни текшириш", callback_data="admin:payments")],
        [InlineKeyboardButton(text="📋 Барча буюртмалар", callback_data="admin:orders")],
        [InlineKeyboardButton(text="📢 Хабар юбориш", callback_data="admin:broadcast")],
    ])


def payment_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Нақд пул", callback_data="pay:cash")],
        [InlineKeyboardButton(text="💳 Карта орқали", callback_data="pay:card")],
    ])


# -------------------- БАЗА --------------------
async def db_execute(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(query, params)
        await db.commit()


async def db_fetchone(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        return await cursor.fetchone()


async def db_fetchall(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        return await cursor.fetchall()


async def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                district TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'client',
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS masters (
                tg_id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                experience TEXT NOT NULL,
                about TEXT NOT NULL,
                district TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                rating REAL NOT NULL DEFAULT 0,
                reviews INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                address TEXT NOT NULL,
                phone TEXT NOT NULL,
                photo_id TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                master_id INTEGER,
                payment_method TEXT NOT NULL DEFAULT 'cash',
                payment_status TEXT NOT NULL DEFAULT 'unpaid',
                receipt_file_id TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                client_id INTEGER NOT NULL,
                master_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                client_id INTEGER NOT NULL,
                master_id INTEGER NOT NULL,
                UNIQUE(client_id, master_id)
            )
        """)
        # Аввалги версиялардан қолган база учун миграция.
        cursor = await db.execute("PRAGMA table_info(orders)")
        columns = {row[1] for row in await cursor.fetchall()}
        migrations = {
            "payment_method": "TEXT NOT NULL DEFAULT 'cash'",
            "payment_status": "TEXT NOT NULL DEFAULT 'unpaid'",
            "receipt_file_id": "TEXT",
            "created_at": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in columns:
                await db.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
        await db.commit()


async def get_user(user_id: int):
    return await db_fetchone("SELECT * FROM users WHERE tg_id=?", (user_id,))


async def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def send_admins(text: str, markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=markup)
        except Exception:
            logger.exception("Администраторга хабар юборилмади: %s", admin_id)


async def user_menu(message: Message, user_id: int):
    user = await get_user(user_id)
    if not user:
        return
    await message.answer(
        f"Ассалому алайкум, {user['name']}!\nUSTA 24 ANDIJON хизматига хуш келибсиз.",
        reply_markup=main_menu(user["role"], await is_admin(user_id))
    )


async def send_order_to_masters(order_id: int):
    order = await db_fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
    if not order:
        return
    masters = await db_fetchall(
        """SELECT m.tg_id, u.name, u.phone
           FROM masters m JOIN users u ON u.tg_id=m.tg_id
           WHERE m.approved=1 AND m.category=?""",
        (order["category"],)
    )
    text = (
        f"🆕 <b>Янги буюртма №{order_id}</b>\n"
        f"Хизмат: {order['category']}\n"
        f"Тавсиф: {order['description']}\n"
        f"Манзил: {order['address']}\n"
        f"Телефон: {order['phone']}"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Буюртмани қабул қилиш", callback_data=f"take:{order_id}")
    ]])
    for master in masters:
        try:
            await bot.send_message(master["tg_id"], text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            logger.exception("Устага буюртма юборилмади: %s", master["tg_id"])


# -------------------- РЎЙХАТДАН ЎТИШ --------------------
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    if user:
        await user_menu(message, message.from_user.id)
        return
    await message.answer(
        "🔧 <b>USTA 24 ANDIJON</b>\n\nРўйхатдан ўтиш учун исм-фамилиянгизни ёзинг.",
        parse_mode="HTML"
    )
    await state.set_state(Registration.name)


@dp.message(Registration.name)
async def registration_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Исмни камида 2 та ҳарф билан киритинг.")
        return
    await state.update_data(name=name)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Телефон рақамни юбориш", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Телефон рақамингизни юборинг ёки қўлда ёзинг.", reply_markup=keyboard)
    await state.set_state(Registration.phone)


@dp.message(Registration.phone)
async def registration_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else (message.text or "").strip()
    if len(phone) < 7:
        await message.answer("Телефон рақам нотўғри. Қайта киритинг.")
        return
    await state.update_data(phone=phone)
    await message.answer("Қайси туман ёки шаҳарда яшайсиз?")
    await state.set_state(Registration.district)


@dp.message(Registration.district)
async def registration_district(message: Message, state: FSMContext):
    district = (message.text or "").strip()
    if len(district) < 2:
        await message.answer("Туман ёки шаҳар номини киритинг.")
        return
    await state.update_data(district=district)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Мижозман", callback_data="role:client")],
        [InlineKeyboardButton(text="👨‍🔧 Устаман", callback_data="role:master")],
    ])
    await message.answer("Сиз кимсиз?", reply_markup=markup)
    await state.set_state(Registration.role)


@dp.callback_query(Registration.role, F.data.startswith("role:"))
async def registration_role(call: CallbackQuery, state: FSMContext):
    role = call.data.split(":", 1)[1]
    if role not in {"client", "master"}:
        await call.answer("Нотўғри танлов.", show_alert=True)
        return
    data = await state.get_data()
    now = datetime.now().isoformat(timespec="seconds")
    await db_execute(
        """INSERT INTO users(tg_id,name,phone,district,role,created_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(tg_id) DO UPDATE SET
           name=excluded.name, phone=excluded.phone,
           district=excluded.district, role=excluded.role""",
        (call.from_user.id, data["name"], data["phone"], data["district"], role, now)
    )
    await state.clear()
    await call.message.answer(
        "✅ Рўйхатдан ўтиш якунланди.",
        reply_markup=main_menu(role, await is_admin(call.from_user.id))
    )
    if role == "master":
        await call.message.answer("Уста профилини тўлдириш учун «👨‍🔧 Уста бўлиш» тугмасини босинг.")
    await call.answer()


# -------------------- УСТА БЎЛИШ ВА ҚИДИРИШ --------------------
@dp.message(F.text == "👨‍🔧 Уста бўлиш")
async def master_apply(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Аввал /start орқали рўйхатдан ўтинг.")
        return
    await message.answer("Қайси хизмат тури бўйича ишлайсиз?", reply_markup=categories_markup("apply"))
    await state.set_state(MasterApplication.category)


@dp.callback_query(MasterApplication.category, F.data.startswith("apply:"))
async def master_category(call: CallbackQuery, state: FSMContext):
    try:
        index = int(call.data.split(":")[1])
        category = CATEGORIES[index]
    except (ValueError, IndexError):
        await call.answer("Хизмат тури нотўғри.", show_alert=True)
        return
    await state.update_data(category=category)
    await call.message.answer("Иш тажрибангиз қанча? Масалан: 3 йил.")
    await state.set_state(MasterApplication.experience)
    await call.answer()


@dp.message(MasterApplication.experience)
async def master_experience(message: Message, state: FSMContext):
    experience = (message.text or "").strip()
    if not experience:
        await message.answer("Иш тажрибангизни ёзинг.")
        return
    await state.update_data(experience=experience)
    await message.answer("Ўзингиз ва хизматингиз ҳақида қисқача маълумот ёзинг.")
    await state.set_state(MasterApplication.about)


@dp.message(MasterApplication.about)
async def master_about(message: Message, state: FSMContext):
    about = (message.text or "").strip()
    if len(about) < 5:
        await message.answer("Камида 5 та белги билан маълумот ёзинг.")
        return
    data = await state.get_data()
    user = await get_user(message.from_user.id)
    await db_execute(
        """INSERT INTO masters(tg_id,category,experience,about,district,approved)
           VALUES(?,?,?,?,?,0)
           ON CONFLICT(tg_id) DO UPDATE SET
           category=excluded.category, experience=excluded.experience,
           about=excluded.about, district=excluded.district, approved=0""",
        (message.from_user.id, data["category"], data["experience"], about, user["district"])
    )
    await state.clear()
    await message.answer("✅ Аризангиз администраторга юборилди. Тасдиқлангач хабар берамиз.",
                         reply_markup=main_menu("master", await is_admin(message.from_user.id)))
    await send_admins(
        f"👨‍🔧 <b>Янги уста аризаси</b>\n"
        f"Исм: {user['name']}\nТелефон: {user['phone']}\n"
        f"Йўналиш: {data['category']}\nТажриба: {data['experience']}\n"
        f"Ҳудуд: {user['district']}\nМаълумот: {about}",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Тасдиқлаш", callback_data=f"approve_master:{message.from_user.id}"),
            InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"reject_master:{message.from_user.id}")
        ]])
    )


@dp.message(F.text == "🔍 Уста топиш")
async def find_master(message: Message):
    await message.answer("Қайси хизмат керак?", reply_markup=categories_markup("find"))


@dp.callback_query(F.data.startswith("find:"))
async def show_masters(call: CallbackQuery):
    try:
        category = CATEGORIES[int(call.data.split(":")[1])]
    except (ValueError, IndexError):
        await call.answer("Нотўғри хизмат тури.", show_alert=True)
        return
    masters = await db_fetchall(
        """SELECT m.*, u.name, u.phone, u.district FROM masters m
           JOIN users u ON u.tg_id=m.tg_id
           WHERE m.approved=1 AND m.category=? ORDER BY m.rating DESC""",
        (category,)
    )
    if not masters:
        await call.message.answer("Ҳозирча бу йўналишда тасдиқланган уста топилмади.")
    for master in masters:
        text = (
            f"👨‍🔧 <b>{master['name']}</b>\n"
            f"Йўналиш: {master['category']}\nТажриба: {master['experience']}\n"
            f"Ҳудуд: {master['district']}\nРейтинг: {master['rating']:.1f} "
            f"({master['reviews']} та баҳо)\n"
            f"Маълумот: {master['about']}\nТелефон: {master['phone']}"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❤️ Севимлига қўшиш", callback_data=f"fav_add:{master['tg_id']}")
        ]])
        await call.message.answer(text, parse_mode="HTML", reply_markup=markup)
    await call.answer()


@dp.callback_query(F.data.startswith("fav_add:"))
async def favorite_add(call: CallbackQuery):
    try:
        master_id = int(call.data.split(":")[1])
    except ValueError:
        await call.answer("Хато маълумот.", show_alert=True)
        return
    await db_execute(
        "INSERT OR IGNORE INTO favorites(client_id,master_id) VALUES(?,?)",
        (call.from_user.id, master_id)
    )
    await call.answer("Севимли усталарга қўшилди.")


@dp.message(F.text == "❤️ Севимли усталар")
async def favorites_list(message: Message):
    rows = await db_fetchall(
        """SELECT m.*,u.name,u.phone,u.district FROM favorites f
           JOIN masters m ON m.tg_id=f.master_id
           JOIN users u ON u.tg_id=m.tg_id WHERE f.client_id=?""",
        (message.from_user.id,)
    )
    if not rows:
        await message.answer("Севимли усталар рўйхати ҳозирча бўш.")
        return
    for row in rows:
        await message.answer(
            f"👨‍🔧 {row['name']}\n{row['category']}\nТелефон: {row['phone']}\n"
            f"Рейтинг: {row['rating']:.1f}"
        )


# -------------------- БУЮРТМА БЕРИШ --------------------
@dp.message(F.text == "📝 Буюртма бериш")
async def order_start(message: Message, state: FSMContext):
    if not await get_user(message.from_user.id):
        await message.answer("Аввал /start орқали рўйхатдан ўтинг.")
        return
    await message.answer("Қандай хизмат керак?", reply_markup=categories_markup("order"))
    await state.set_state(OrderForm.category)


@dp.callback_query(OrderForm.category, F.data.startswith("order:"))
async def order_category(call: CallbackQuery, state: FSMContext):
    try:
        category = CATEGORIES[int(call.data.split(":")[1])]
    except (ValueError, IndexError):
        await call.answer("Хизмат тури нотўғри.", show_alert=True)
        return
    await state.update_data(category=category)
    await call.message.answer("Муаммони батафсил ёзинг.")
    await state.set_state(OrderForm.description)
    await call.answer()


@dp.message(OrderForm.description)
async def order_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    if len(description) < 5:
        await message.answer("Илтимос, муаммони батафсилроқ ёзинг.")
        return
    await state.update_data(description=description)
    await message.answer("Манзилингизни ёзинг (туман, кўча, уй).")
    await state.set_state(OrderForm.address)


@dp.message(OrderForm.address)
async def order_address(message: Message, state: FSMContext):
    address = (message.text or "").strip()
    if len(address) < 3:
        await message.answer("Манзилни тўлиқроқ ёзинг.")
        return
    await state.update_data(address=address)
    user = await get_user(message.from_user.id)
    await message.answer(f"Алоқа телефонингиз: {user['phone']}\nЎзгартириш керак бўлса, янги рақамни ёзинг. Ўзгармаса, «Йўқ» деб ёзинг.")
    await state.set_state(OrderForm.phone)


@dp.message(OrderForm.phone)
async def order_phone(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    user = await get_user(message.from_user.id)
    phone = user["phone"] if text.lower() in {"йўқ", "йук", "yo'q", "yoq"} else text
    if len(phone) < 7:
        await message.answer("Телефон рақам нотўғри. Қайта киритинг ёки «Йўқ» деб ёзинг.")
        return
    await state.update_data(phone=phone)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Расм юбориш", callback_data="photo:yes")],
        [InlineKeyboardButton(text="Ўтказиб юбориш", callback_data="photo:no")]
    ])
    await message.answer("Муаммо расмини юборишни хоҳлайсизми?", reply_markup=markup)
    await state.set_state(OrderForm.photo)


@dp.callback_query(OrderForm.photo, F.data.startswith("photo:"))
async def order_photo_choice(call: CallbackQuery, state: FSMContext):
    choice = call.data.split(":")[1]
    if choice == "yes":
        await call.message.answer("Илтимос, муаммо расмини юборинг.")
        await state.update_data(photo_id=None)
        await state.set_state(OrderForm.receipt)  # vaqtincha rasm qabul qilish uchun
        await state.update_data(waiting_order_photo=True)
    else:
        await state.update_data(photo_id=None)
        await call.message.answer("Тўлов турини танланг:", reply_markup=payment_markup())
        await state.set_state(OrderForm.payment)
    await call.answer()


@dp.message(OrderForm.receipt, F.photo)
async def receive_order_or_receipt_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("waiting_order_photo"):
        await state.update_data(photo_id=message.photo[-1].file_id, waiting_order_photo=False)
        await message.answer("Тўлов турини танланг:", reply_markup=payment_markup())
        await state.set_state(OrderForm.payment)
        return
    # Карта тўлови чеки: администратор тасдиқлагунча буюртма усталарга кўринмайди.
    receipt_id = message.photo[-1].file_id
    await create_order(message, state, "card", "pending", receipt_id)


@dp.message(OrderForm.receipt)
async def order_photo_invalid(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("waiting_order_photo"):
        await message.answer("Илтимос, расм юборинг ёки /cancel билан бекор қилинг.")
    else:
        await message.answer("Карта тўлови чекини расм шаклида юборинг.")


async def create_order(message: Message, state: FSMContext, payment_method: str,
                       payment_status: str, receipt_id: str = None):
    data = await state.get_data()
    user = await get_user(message.from_user.id)
    status = "new" if payment_method == "cash" else "awaiting_payment"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO orders(
                client_id,category,description,address,phone,photo_id,status,
                payment_method,payment_status,receipt_file_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                message.from_user.id, data["category"], data["description"],
                data["address"], data["phone"], data.get("photo_id"),
                status, payment_method, payment_status, receipt_id,
                datetime.now().isoformat(timespec="seconds")
            )
        )
        order_id = cursor.lastrowid
        await db.commit()
    await state.clear()
    await message.answer(
        f"✅ Буюртмангиз қабул қилинди. Рақами: #{order_id}",
        reply_markup=main_menu(user["role"], await is_admin(message.from_user.id))
    )
    if payment_method == "cash":
        await send_order_to_masters(order_id)
    else:
        await send_admins(
            f"💳 <b>Карта тўлови чеки келди</b>\nБуюртма: #{order_id}\n"
            f"Мижоз: {user['name']}\nСумма: келишув асосида",
            InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Тўловни тасдиқлаш", callback_data=f"payment_ok:{order_id}"),
                InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"payment_no:{order_id}")
            ]])
        )


@dp.callback_query(OrderForm.payment, F.data == "pay:cash")
async def order_cash(call: CallbackQuery, state: FSMContext):
    # Create using callback message context without a proxy object.
    data = await state.get_data()
    user = await get_user(call.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO orders(client_id,category,description,address,phone,photo_id,
               status,payment_method,payment_status,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (call.from_user.id, data["category"], data["description"], data["address"],
             data["phone"], data.get("photo_id"), "new", "cash", "unpaid",
             datetime.now().isoformat(timespec="seconds"))
        )
        order_id = cursor.lastrowid
        await db.commit()
    await state.clear()
    await call.message.answer(
        f"✅ Буюртмангиз қабул қилинди. №{order_id}\nТўловни иш тугагач устага нақд берасиз.",
        reply_markup=main_menu(user["role"], await is_admin(call.from_user.id))
    )
    await send_order_to_masters(order_id)
    await call.answer()


@dp.callback_query(OrderForm.payment, F.data == "pay:card")
async def order_card(call: CallbackQuery, state: FSMContext):
    if not CARD_NUMBER:
        await call.answer("Карта маълумоти ҳали созланмаган. Нақд тўловни танланг.", show_alert=True)
        return
    await call.message.answer(
        f"💳 Карта рақами: <code>{CARD_NUMBER}</code>\n"
        f"Карта эгаси: {CARD_HOLDER}\n\n"
        "Тўловни амалга ошириб, чек расмини юборинг.",
        parse_mode="HTML"
    )
    await state.update_data(waiting_order_photo=False)
    await state.set_state(OrderForm.receipt)
    await call.answer()


# -------------------- УСТА БУЮРТМАЛАРИ --------------------
@dp.message(F.text == "📥 Усталар учун буюртмалар")
async def master_orders(message: Message):
    master = await db_fetchone("SELECT * FROM masters WHERE tg_id=?", (message.from_user.id,))
    if not master or not master["approved"]:
        await message.answer("Уста профилингиз ҳали администратор томонидан тасдиқланмаган.")
        return
    orders = await db_fetchall(
        """SELECT * FROM orders WHERE category=? AND status='new'
           AND (payment_method='cash' OR payment_status='paid')
           ORDER BY id DESC LIMIT 20""",
        (master["category"],)
    )
    if not orders:
        await message.answer("Ҳозирча сизга мос янги буюртмалар йўқ.")
        return
    for order in orders:
        text = (
            f"🆕 <b>Буюртма №{order['id']}</b>\n"
            f"{order['category']}\n{order['description']}\n"
            f"Манзил: {order['address']}\nТелефон: {order['phone']}"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Қабул қилиш", callback_data=f"take:{order['id']}")
        ]])
        await message.answer(text, parse_mode="HTML", reply_markup=markup)


@dp.callback_query(F.data.startswith("take:"))
async def take_order(call: CallbackQuery):
    try:
        order_id = int(call.data.split(":")[1])
    except ValueError:
        await call.answer("Буюртма рақами нотўғри.", show_alert=True)
        return
    master = await db_fetchone("SELECT * FROM masters WHERE tg_id=?", (call.from_user.id,))
    if not master or not master["approved"]:
        await call.answer("Фақат тасдиқланган усталар буюртмани қабул қила олади.", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM orders WHERE id=? AND status='new'
               AND (payment_method='cash' OR payment_status='paid')""",
            (order_id,)
        )
        order = await cursor.fetchone()
        if not order:
            await call.answer("Буюртма олинган ёки мавжуд эмас.", show_alert=True)
            return
        if order["category"] != master["category"]:
            await call.answer("Бу буюртма сизнинг йўналишингизга мос эмас.", show_alert=True)
            return
        cursor = await db.execute(
            "UPDATE orders SET status='accepted', master_id=? WHERE id=? AND status='new'",
            (call.from_user.id, order_id)
        )
        await db.commit()
        if cursor.rowcount != 1:
            await call.answer("Буюртмани бошқа уста қабул қилди.", show_alert=True)
            return
    client = await get_user(order["client_id"])
    master_user = await get_user(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"Сиз #{order_id} буюртмани қабул қилдингиз.")
    await bot.send_message(
        call.from_user.id,
        "Иш тугагач, қуйидаги тугмани босинг.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🏁 Ишни якунлаш", callback_data=f"done:{order_id}")
        ]])
    )
    await bot.send_message(
        order["client_id"],
        f"👨‍🔧 Буюртмангиз қабул қилинди!\nУста: {master_user['name']}\nТелефон: {master_user['phone']}"
    )
    await call.answer("Буюртма сизга бириктирилди.")


@dp.callback_query(F.data.startswith("done:"))
async def complete_order(call: CallbackQuery):
    try:
        order_id = int(call.data.split(":")[1])
    except ValueError:
        await call.answer("Буюртма рақами нотўғри.", show_alert=True)
        return
    order = await db_fetchone(
        "SELECT * FROM orders WHERE id=? AND master_id=? AND status='accepted'",
        (order_id, call.from_user.id)
    )
    if not order:
        await call.answer("Бу буюртма сизга бириктирилмаган ёки якунланган.", show_alert=True)
        return
    await db_execute("UPDATE orders SET status='completed' WHERE id=?", (order_id,))
    await call.message.edit_reply_markup(reply_markup=None)
    await bot.send_message(
        order["client_id"],
        f"✅ #{order_id} буюртма якунланди. Устага 1 дан 5 гача баҳо беринг.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"{n} ⭐", callback_data=f"rate:{order_id}:{n}") for n in range(1, 6)]
        ])
    )
    await call.answer("Буюртма якунланди.")


# -------------------- МИЖОЗ БУЮРТМАЛАРИ ВА БАҲОЛАР --------------------
@dp.message(F.text == "📋 Буюртмаларим")
async def my_orders(message: Message):
    orders = await db_fetchall(
        "SELECT * FROM orders WHERE client_id=? ORDER BY id DESC LIMIT 20",
        (message.from_user.id,)
    )
    if not orders:
        await message.answer("Сизда ҳозирча буюртмалар йўқ.")
        return
    for order in orders:
        payment = "Нақд" if order["payment_method"] == "cash" else "Карта"
        await message.answer(
            f"Буюртма №{order['id']}\nХизмат: {order['category']}\n"
            f"Ҳолати: {order['status']}\nТўлов: {payment} ({order['payment_status']})"
        )


@dp.callback_query(F.data.startswith("rate:"))
async def rate_order(call: CallbackQuery, state: FSMContext):
    try:
        _, order_id_text, rating_text = call.data.split(":")
        order_id, rating = int(order_id_text), int(rating_text)
    except ValueError:
        await call.answer("Баҳо маълумоти нотўғри.", show_alert=True)
        return
    if rating < 1 or rating > 5:
        await call.answer("Баҳо 1 дан 5 гача бўлиши керак.", show_alert=True)
        return
    order = await db_fetchone(
        "SELECT * FROM orders WHERE id=? AND client_id=? AND status='completed'",
        (order_id, call.from_user.id)
    )
    if not order or not order["master_id"]:
        await call.answer("Баҳолаш мумкин эмас.", show_alert=True)
        return
    exists = await db_fetchone("SELECT id FROM reviews WHERE order_id=?", (order_id,))
    if exists:
        await call.answer("Бу буюртма баҳоланган.", show_alert=True)
        return
    await db_execute(
        """INSERT INTO reviews(order_id,client_id,master_id,rating,created_at)
           VALUES(?,?,?,?,?)""",
        (order_id, call.from_user.id, order["master_id"], rating,
         datetime.now().isoformat(timespec="seconds"))
    )
    stats = await db_fetchone(
        "SELECT AVG(rating) AS avg_rating, COUNT(*) AS total FROM reviews WHERE master_id=?",
        (order["master_id"],)
    )
    await db_execute(
        "UPDATE masters SET rating=?, reviews=? WHERE tg_id=?",
        (stats["avg_rating"] or 0, stats["total"], order["master_id"])
    )
    await call.message.answer("⭐ Раҳмат! Баҳонгиз сақланди.")
    await call.answer()


@dp.message(F.text == "⭐ Баҳолар")
async def reviews_list(message: Message):
    rows = await db_fetchall(
        """SELECT r.rating,r.comment,u.name,m.category
           FROM reviews r JOIN users u ON u.tg_id=r.client_id
           JOIN masters m ON m.tg_id=r.master_id
           ORDER BY r.id DESC LIMIT 10"""
    )
    if not rows:
        await message.answer("Ҳозирча баҳолар йўқ.")
        return
    for row in rows:
        await message.answer(
            f"⭐ {row['rating']}/5 — {row['category']}\nМижоз: {row['name']}\n{row['comment'] or ''}"
        )


# -------------------- ЁРДАМ ВА КАБИНЕТ --------------------
@dp.message(F.text == "👤 Шахсий кабинет")
async def profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Аввал /start орқали рўйхатдан ўтинг.")
        return
    master = await db_fetchone("SELECT * FROM masters WHERE tg_id=?", (message.from_user.id,))
    text = (
        f"👤 {user['name']}\nТелефон: {user['phone']}\nҲудуд: {user['district']}\n"
        f"Роль: {user['role']}"
    )
    if master:
        text += f"\nУста йўналиши: {master['category']}\nТасдиқланган: {'Ҳа' if master['approved'] else 'Йўқ'}"
    await message.answer(text)


@dp.message(F.text == "☎️ Ёрдам")
async def support_start(message: Message, state: FSMContext):
    await message.answer("Администраторга хабарингизни ёзинг.")
    await state.set_state(SupportForm.message)


@dp.message(SupportForm.message)
async def support_send(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text:
        await message.answer("Матнли хабар юборинг.")
        return
    user = await get_user(message.from_user.id)
    await send_admins(
        f"☎️ <b>Ёрдам сўрови</b>\nФойдаланувчи: {user['name'] if user else 'номаълум'} "
        f"(ID: {message.from_user.id})\n\n{text}"
    )
    await state.clear()
    await message.answer("Хабарингиз администраторга юборилди.")


@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    role = user["role"] if user else "client"
    await message.answer("Жорий амал бекор қилинди.",
                         reply_markup=main_menu(role, await is_admin(message.from_user.id)))


# -------------------- АДМИН ПАНЕЛИ --------------------
@dp.message(F.text == "⚙️ Админ панели")
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Бу бўлим фақат администратор учун.")
        return
    await message.answer("⚙️ Администратор панели", reply_markup=admin_markup())


@dp.callback_query(F.data.startswith("admin:"))
async def admin_actions(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True)
        return
    action = call.data.split(":")[1]
    if action == "stats":
        users = await db_fetchone("SELECT COUNT(*) AS n FROM users")
        masters = await db_fetchone("SELECT COUNT(*) AS n FROM masters")
        orders = await db_fetchone("SELECT COUNT(*) AS n FROM orders")
        await call.message.answer(
            f"📊 Статистика\nФойдаланувчилар: {users['n']}\n"
            f"Усталар: {masters['n']}\nБуюртмалар: {orders['n']}"
        )
    elif action == "masters":
        masters = await db_fetchall(
            """SELECT m.*,u.name,u.phone FROM masters m JOIN users u ON u.tg_id=m.tg_id
               WHERE m.approved=0 ORDER BY m.tg_id DESC LIMIT 20"""
        )
        if not masters:
            await call.message.answer("Кутилayotgan уста аризалари йўқ.")
        for master in masters:
            await call.message.answer(
                f"Уста: {master['name']}\nТелефон: {master['phone']}\n"
                f"Йўналиш: {master['category']}\nТажриба: {master['experience']}\n"
                f"Маълумот: {master['about']}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Тасдиқлаш", callback_data=f"approve_master:{master['tg_id']}"),
                    InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"reject_master:{master['tg_id']}")
                ]])
            )
    elif action == "payments":
        rows = await db_fetchall(
            "SELECT * FROM orders WHERE payment_method='card' AND payment_status='pending' ORDER BY id"
        )
        if not rows:
            await call.message.answer("Текшириш учун карта тўлови йўқ.")
        for order in rows:
            await call.message.answer(
                f"💳 Буюртма №{order['id']}\nМижоз ID: {order['client_id']}\n"
                f"Йўналиш: {order['category']}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Тасдиқлаш", callback_data=f"payment_ok:{order['id']}"),
                    InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"payment_no:{order['id']}")
                ]])
            )
            if order["receipt_file_id"]:
                await bot.send_photo(call.from_user.id, order["receipt_file_id"])
    elif action == "orders":
        rows = await db_fetchall("SELECT * FROM orders ORDER BY id DESC LIMIT 20")
        if not rows:
            await call.message.answer("Буюртмалар йўқ.")
        for order in rows:
            await call.message.answer(
                f"№{order['id']} | {order['category']}\nҲолати: {order['status']}\n"
                f"Тўлов: {order['payment_method']} / {order['payment_status']}"
            )
    elif action == "broadcast":
        await call.message.answer("Барча фойдаланувчиларга юбориладиган хабарни ёзинг.")
        await state.set_state(BroadcastForm.message)
    await call.answer()


@dp.callback_query(F.data.startswith("approve_master:"))
async def approve_master(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True)
        return
    master_id = int(call.data.split(":")[1])
    await db_execute("UPDATE masters SET approved=1 WHERE tg_id=?", (master_id,))
    await db_execute("UPDATE users SET role='master' WHERE tg_id=?", (master_id,))
    try:
        await bot.send_message(master_id, "✅ Уста профилингиз тасдиқланди. Энди буюртмаларни қабул қилишингиз мумкин.")
    except Exception:
        logger.exception("Устага тасдиқ хабари юборилмади")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Уста тасдиқланди.")


@dp.callback_query(F.data.startswith("reject_master:"))
async def reject_master(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True)
        return
    master_id = int(call.data.split(":")[1])
    await db_execute("DELETE FROM masters WHERE tg_id=? AND approved=0", (master_id,))
    try:
        await bot.send_message(master_id, "❌ Уста аризангиз рад этилди. Қўшимча маълумот учун администраторга ёзинг.")
    except Exception:
        logger.exception("Устага рад жавоби юборилмади")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Ариза рад этилди.")


@dp.callback_query(F.data.startswith("payment_ok:"))
async def payment_approve(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    order = await db_fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
    if not order or order["payment_status"] != "pending":
        await call.answer("Тўлов топилмади ёки аллақачон кўрилган.", show_alert=True)
        return
    await db_execute(
        "UPDATE orders SET payment_status='paid', status='new' WHERE id=?",
        (order_id,)
    )
    await bot.send_message(order["client_id"], f"✅ #{order_id} карта тўлови тасдиқланди. Буюртмангиз усталарга юборилди.")
    await send_order_to_masters(order_id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Тўлов тасдиқланди.")


@dp.callback_query(F.data.startswith("payment_no:"))
async def payment_reject(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    order = await db_fetchone("SELECT * FROM orders WHERE id=?", (order_id,))
    if not order or order["payment_status"] != "pending":
        await call.answer("Тўлов топилмади ёки аллақачон кўрилган.", show_alert=True)
        return
    await db_execute(
        "UPDATE orders SET payment_status='rejected', status='payment_rejected' WHERE id=?",
        (order_id,)
    )
    await bot.send_message(order["client_id"], f"❌ #{order_id} карта тўлови тасдиқланмади. Ёрдам учун администраторга мурожаат қилинг.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Тўлов рад этилди.")


@dp.message(BroadcastForm.message)
async def broadcast_send(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Матнли хабар юборинг.")
        return
    users = await db_fetchall("SELECT tg_id FROM users")
    success = 0
    for user in users:
        try:
            await bot.send_message(user["tg_id"], text)
            success += 1
        except Exception:
            logger.warning("Broadcast failed for %s", user["tg_id"])
    await state.clear()
    await message.answer(f"📢 Хабар {success} та фойдаланувчига юборилди.")


# -------------------- ИШГА ТУШИРИШ --------------------
async def main():
    await init_db()
    logger.info("USTA 24 ANDIJON боти ишга тушмоқда...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
