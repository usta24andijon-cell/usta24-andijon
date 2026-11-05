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
    Message, CallbackQuery, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
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

# LOGOTIP RASM UCHUN LINK (O'zingizning rasm havolangizni qo'yishingiz mumkin)
LOGOS_URL = "https://images.unsplash.com/photo-1621905251189-08b45d6a269e?w=800"

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


class BroadcastForm(StatesGroup):
    message = State()


class AdminAddMaster(StatesGroup):
    tg_id = State()
    name = State()
    phone = State()
    district = State()
    category = State()
    experience = State()
    about = State()


# -------------------- КЛАВИАТУРАЛАР --------------------
def main_menu(role: str = "client", is_admin: bool = False):
    rows = [
        [KeyboardButton(text="🔎 Xizmat tanlash / Buyurtma berish")],
        [KeyboardButton(text="📍 Joylashuv yuborish"), KeyboardButton(text="🚚 Usta joylashuvini kuzatish")],
        [KeyboardButton(text="📋 Buyurtmalarim"), KeyboardButton(text="💳 Toʻlovlarim")],
        [KeyboardButton(text="❤️ Sevimli ustalar"), KeyboardButton(text="⭐ Baholar")],
        [KeyboardButton(text="👨‍🔧 Usta kabineti"), KeyboardButton(text="👤 Shaxsiy kabinet")],
        [KeyboardButton(text="💬 Yordam"), KeyboardButton(text="ℹ️ Qoʻllanma")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ ADMIN PANELI")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def master_cabinet_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📥 Yangi buyurtmalar"), KeyboardButton(text="📌 Qabul qilgan buyurtmalar")],
            [KeyboardButton(text="🔄 Jarayondagi ishlarim"), KeyboardButton(text="✅ Tugallangan ishlarim")],
            [KeyboardButton(text="📍 Joylashuvimni yuborish"), KeyboardButton(text="📈 Usta statistikasi")],
            [KeyboardButton(text="⭐ Mening reytingim"), KeyboardButton(text="💰 Daromadlarim")],
            [KeyboardButton(text="✏️ Usta profilim"), KeyboardButton(text="⬅️ Asosiy menyu")],
        ],
        resize_keyboard=True
    )


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
        [InlineKeyboardButton(text="➕ Уста қўшиш", callback_data="admin:add_master")],
        [InlineKeyboardButton(text="🗑 Устани ўчириш", callback_data="admin:delete_masters_list")],
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
                created_at TEXT NOT NULL,
                latitude REAL,
                longitude REAL
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS master_locations (
                master_id INTEGER PRIMARY KEY,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS client_locations (
                client_id INTEGER PRIMARY KEY,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.commit()


async def get_user(user_id: int):
    return await db_fetchone("SELECT * FROM users WHERE tg_id=?", (user_id,))


async def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def send_admins(text: str, markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            logger.exception("Администраторга хабар юборилмади: %s", admin_id)


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


# -------------------- START (LOGOTIP BILAN) --------------------
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    
    if await is_admin(message.from_user.id):
        try:
            await message.answer_photo(
                photo=LOGOS_URL,
                caption="<b>🔧 USTA 24 ANDIJON</b>\n<b>АДМИНИСТРАТОР ПАНЕЛИГА ХУШ КЕЛИБСИЗ!</b>",
                parse_mode="HTML"
            )
        except Exception:
            await message.answer("<b>🔧 USTA 24 ANDIJON - АДМИН ПАНЕЛ</b>", parse_mode="HTML")
        
        await message.answer("⚙️ Администратор панели бошқаруви:", reply_markup=admin_markup())
        return

    user = await get_user(message.from_user.id)
    if user:
        try:
            await message.answer_photo(
                photo=LOGOS_URL,
                caption=f"<b>🔧 USTA 24 ANDIJON</b>\n\nАссалому алайкум, {user['name']}!\nХизматларимиздан фойдаланишингиз мумкин.",
                parse_mode="HTML",
                reply_markup=main_menu(user["role"], await is_admin(message.from_user.id))
            )
        except Exception:
            await message.answer(
                f"Ассалому алайкум, {user['name']}! USTA 24 ANDIJON хизматига хуш келибсиз.",
                reply_markup=main_menu(user["role"], await is_admin(message.from_user.id))
            )
        return

    try:
        await message.answer_photo(
            photo=LOGOS_URL,
            caption="<b>🔧 USTA 24 ANDIJON</b>\n\nХизматларимизга хуш келибсиз!\nИлтимос, исм-шарифingizni kiriting:",
            parse_mode="HTML"
        )
    except Exception:
        await message.answer("<b>🔧 USTA 24 ANDIJON</b>\nИлтимос, исм-шарифingizni kiriting:", parse_mode="HTML")
        
    await state.set_state(Registration.name)


@dp.message(Registration.name)
async def registration_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Исмни тўлиқроқ киритинг.")
        return
    await state.update_data(name=name)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Телефон рақамни юбориш", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Телефон рақамингизни юборинг ёки ёзинг.", reply_markup=keyboard)
    await state.set_state(Registration.phone)


@dp.message(Registration.phone)
async def registration_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else (message.text or "").strip()
    if len(phone) < 7:
        await message.answer("Телефон рақам нотўғри.")
        return
    await state.update_data(phone=phone)
    await message.answer("Қайси туман ёки шаҳарда яшайсиз?", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Registration.district)


@dp.message(Registration.district)
async def registration_district(message: Message, state: FSMContext):
    district = (message.text or "").strip()
    await state.update_data(district=district)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Мижозман", callback_data="role:client")],
        [InlineKeyboardButton(text="👨‍🔧 Устаман", callback_data="role:master")],
    ])
    await message.answer("Сиз ким сифатида рўйхатдан ўтяпсиз?", reply_markup=markup)
    await state.set_state(Registration.role)


@dp.callback_query(Registration.role, F.data.startswith("role:"))
async def registration_role(call: CallbackQuery, state: FSMContext):
    role = call.data.split(":", 1)[1]
    data = await state.get_data()
    now = datetime.now().isoformat(timespec="seconds")
    await db_execute(
        """INSERT INTO users(tg_id,name,phone,district,role,created_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(tg_id) DO UPDATE SET
           name=excluded.name, phone=excluded.phone, district=excluded.district, role=excluded.role""",
        (call.from_user.id, data["name"], data["phone"], data["district"], role, now)
    )
    await state.clear()
    if role == "master":
        await call.message.answer("👨‍🔧 Уста сифатида йўналишингизни танланг:", reply_markup=categories_markup("apply"))
        await state.set_state(MasterApplication.category)
    else:
        await call.message.answer("✅ Рўйхатдан ўтиш якунланди.", reply_markup=main_menu(role, await is_admin(call.from_user.id)))
    await call.answer()


@dp.callback_query(MasterApplication.category, F.data.startswith("apply:"))
async def master_category(call: CallbackQuery, state: FSMContext):
    try:
        index = int(call.data.split(":")[1])
        category = CATEGORIES[index]
    except (ValueError, IndexError):
        await call.answer("Хатолик.", show_alert=True)
        return
    await state.update_data(category=category)
    await call.message.answer("Иш тажрибангиз қанча? (Масалан: 3 йил)")
    await state.set_state(MasterApplication.experience)
    await call.answer()


@dp.message(MasterApplication.experience)
async def master_experience(message: Message, state: FSMContext):
    await state.update_data(experience=message.text.strip())
    await message.answer("Ўзингиз ҳақида қисқача маълумот ёзинг:")
    await state.set_state(MasterApplication.about)


@dp.message(MasterApplication.about)
async def master_about(message: Message, state: FSMContext):
    about = message.text.strip()
    data = await state.get_data()
    user = await get_user(message.from_user.id)
    await db_execute(
        """INSERT INTO masters(tg_id,category,experience,about,district,approved)
           VALUES(?,?,?,?,?,0)
           ON CONFLICT(tg_id) DO UPDATE SET
           category=excluded.category, experience=excluded.experience, about=excluded.about, approved=0""",
        (message.from_user.id, data["category"], data["experience"], about, user["district"])
    )
    await state.clear()
    await message.answer("✅ Аризангиз админга юборилди.", reply_markup=main_menu("master", await is_admin(message.from_user.id)))
    await send_admins(
        f"👨‍🔧 <b>Янги уста аризаси</b>\nИсм: {user['name']}\nЙўналиш: {data['category']}",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Тасдиқлаш", callback_data=f"approve_master:{message.from_user.id}"),
            InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"reject_master:{message.from_user.id}")
        ]])
    )


# -------------------- BUYURTMA BERISH --------------------
@dp.message(F.text.in_({"🔎 Xizmat tanlash / Buyurtma berish", "📝 Buyurtma berish", "🔍 Usta topish"}))
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
        await call.answer("Хатолик.", show_alert=True)
        return
    await state.update_data(category=category)
    await call.message.answer("Муаммони батафсил ёзинг:")
    await state.set_state(OrderForm.description)
    await call.answer()


@dp.message(OrderForm.description)
async def order_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("Манзилингизни киритинг:")
    await state.set_state(OrderForm.address)


@dp.message(OrderForm.address)
async def order_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    user = await get_user(message.from_user.id)
    await message.answer(f"Телефон рақамингиз: {user['phone']}\nЎзгартириш учун янги рақамни ёзинг ёки «Йўқ» денг.")
    await state.set_state(OrderForm.phone)


@dp.message(OrderForm.phone)
async def order_phone(message: Message, state: FSMContext):
    text = message.text.strip()
    user = await get_user(message.from_user.id)
    phone = user["phone"] if text.lower() in {"йўқ", "йук", "yo'q", "yoq"} else text
    await state.update_data(phone=phone)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Расм юбориш", callback_data="photo:yes")],
        [InlineKeyboardButton(text="⏩ Ўтказиб юбориш", callback_data="photo:no")]
    ])
    await message.answer("Муаммо расмини юбориш керакми?", reply_markup=markup)
    await state.set_state(OrderForm.photo)


@dp.callback_query(OrderForm.photo, F.data.startswith("photo:"))
async def order_photo_choice(call: CallbackQuery, state: FSMContext):
    if call.data.split(":")[1] == "yes":
        await call.message.answer("Расмни юборинг:")
        await state.update_data(waiting_order_photo=True)
        await state.set_state(OrderForm.receipt)
    else:
        await state.update_data(photo_id=None)
        await call.message.answer("Тўлов турини танланг:", reply_markup=payment_markup())
        await state.set_state(OrderForm.payment)
    await call.answer()


@dp.message(OrderForm.receipt, F.photo)
async def receive_order_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("waiting_order_photo"):
        await state.update_data(photo_id=message.photo[-1].file_id, waiting_order_photo=False)
        await message.answer("Тўлов турини танланг:", reply_markup=payment_markup())
        await state.set_state(OrderForm.payment)
        return
    receipt_id = message.photo[-1].file_id
    await create_order(message, state, "card", "pending", receipt_id)


async def create_order(message: Message, state: FSMContext, payment_method: str, payment_status: str, receipt_id: str = None):
    data = await state.get_data()
    user = await get_user(message.from_user.id)
    status = "new" if payment_method == "cash" else "awaiting_payment"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO orders(client_id,category,description,address,phone,photo_id,status,payment_method,payment_status,receipt_file_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (message.from_user.id, data["category"], data["description"], data["address"], data["phone"], data.get("photo_id"), status, payment_method, payment_status, receipt_id, datetime.now().isoformat(timespec="seconds"))
        )
        order_id = cursor.lastrowid
        await db.commit()
    await state.clear()
    await message.answer(f"✅ Буюртмангиз қабул қилинди! Рақами: #{order_id}", reply_markup=main_menu(user["role"], await is_admin(message.from_user.id)))
    if payment_method == "cash":
        await send_order_to_masters(order_id)
    else:
        await send_admins(
            f"💳 <b>Карта тўлови чеки келди</b>\nБуюртма: #{order_id}",
            InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Тасдиқлаш", callback_data=f"payment_ok:{order_id}"),
                InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"payment_no:{order_id}")
            ]])
        )


@dp.callback_query(OrderForm.payment, F.data == "pay:cash")
async def order_cash(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = await get_user(call.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO orders(client_id,category,description,address,phone,photo_id,status,payment_method,payment_status,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (call.from_user.id, data["category"], data["description"], data["address"], data["phone"], data.get("photo_id"), "new", "cash", "unpaid", datetime.now().isoformat(timespec="seconds"))
        )
        order_id = cursor.lastrowid
        await db.commit()
    await state.clear()
    await call.message.answer(f"✅ Буюртма қабул қилинди: #{order_id}", reply_markup=main_menu(user["role"], await is_admin(call.from_user.id)))
    await send_order_to_masters(order_id)
    await call.answer()


@dp.callback_query(OrderForm.payment, F.data == "pay:card")
async def order_card(call: CallbackQuery, state: FSMContext):
    if not CARD_NUMBER:
        await call.answer("Карта созланмаган.", show_alert=True)
        return
    await call.message.answer(f"💳 Карта: <code>{CARD_NUMBER}</code>\nЧекни юборинг:", parse_mode="HTML")
    await state.update_data(waiting_order_photo=False)
    await state.set_state(OrderForm.receipt)
    await call.answer()


# -------------------- USTA KABINETI --------------------
@dp.message(F.text == "👨‍🔧 Usta kabineti")
async def master_cabinet_home(
