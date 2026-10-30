import asyncio
import logging
import os
from datetime import datetime

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

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB_PATH = os.getenv("DB_PATH", "usta24.db")
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_HOLDER = os.getenv("CARD_HOLDER", "USTA 24 ANDIJON").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. .env yoki Render Environment Variables ni tekshiring.")

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

CATEGORIES = [
    "⚡ Электрик", "🚿 Сантехник", "❄️ Кондиционер устаси",
    "🧱 Қурилиш ва таъмирлаш", "🪑 Мебель устаси",
    "🧺 Маиший техника таъмири", "🎨 Бўёқчи ва пардозчи",
    "🔐 Қулф ва эшик устаси", "🚗 Автоэлектрик", "🔧 Бошқа хизматлар"
]

class Register(StatesGroup):
    name = State()
    phone = State()
    district = State()
    role = State()

class MasterApply(StatesGroup):
    category = State()
    experience = State()
    about = State()
    district = State()

class NewOrder(StatesGroup):
    category = State()
    description = State()
    address = State()
    phone = State()
    photo = State()
    payment = State()
    receipt = State()

class Broadcast(StatesGroup):
    text = State()

class HelpMessage(StatesGroup):
    text = State()

def main_menu(role="client", is_admin=False):
    rows = [
        [KeyboardButton(text="🔍 Уста топиш"), KeyboardButton(text="📝 Буюртма бериш")],
        [KeyboardButton(text="👨‍🔧 Уста бўлиш"), KeyboardButton(text="📋 Буюртмаларим")],
        [KeyboardButton(text="👤 Шахсий кабинет"), KeyboardButton(text="⭐ Баҳолар ва фикрлар")],
        [KeyboardButton(text="❤️ Севимли усталар"), KeyboardButton(text="☎️ Ёрдам маркази")]
    ]
    if role == "master":
        rows.insert(1, [KeyboardButton(text="📥 Усталар учун буюртмалар")])
    if is_admin:
        rows.append([KeyboardButton(text="⚙️ Админ панели")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def category_keyboard(prefix="cat"):
    b = InlineKeyboardBuilder()
    for i, name in enumerate(CATEGORIES):
        b.button(text=name, callback_data=f"{prefix}:{i}")
    b.adjust(2)
    return b.as_markup()

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="👨‍🔧 Усталарни тасдиқлаш", callback_data="adm:masters")],
        [InlineKeyboardButton(text="📋 Очиқ буюртмалар", callback_data="adm:orders")],
        [InlineKeyboardButton(text="📢 Оммавий хабар", callback_data="adm:broadcast")],
    ])

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
            tg_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, district TEXT,
            role TEXT DEFAULT 'client', created_at TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS masters(
            tg_id INTEGER PRIMARY KEY, category TEXT, experience TEXT, about TEXT,
            district TEXT, approved INTEGER DEFAULT 0, rating REAL DEFAULT 0,
            reviews INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, category TEXT,
            description TEXT, address TEXT, phone TEXT, photo_id TEXT,
            status TEXT DEFAULT 'new', master_id INTEGER, created_at TEXT,
            payment_method TEXT DEFAULT 'cash',
            payment_status TEXT DEFAULT 'unpaid',
            receipt_file_id TEXT)""")
        # Eski bazalar uchun xavfsiz migratsiya: yangi ustunlar bo'lmasa qo'shiladi.
        cur = await db.execute("PRAGMA table_info(orders)")
        existing_columns = {row[1] for row in await cur.fetchall()}
        for column, definition in [
            ("payment_method", "TEXT DEFAULT 'cash'"),
            ("payment_status", "TEXT DEFAULT 'unpaid'"),
            ("receipt_file_id", "TEXT"),
        ]:
            if column not in existing_columns:
                await db.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
        await db.execute("""CREATE TABLE IF NOT EXISTS reviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, client_id INTEGER,
            master_id INTEGER, rating INTEGER, comment TEXT, created_at TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS favorites(
            client_id INTEGER, master_id INTEGER, UNIQUE(client_id, master_id))""")
        await db.commit()

async def get_user(tg_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,))
        return await cur.fetchone()

async def save_user(tg_id, name, phone, district, role):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO users(tg_id,name,phone,district,role,created_at)
        VALUES(?,?,?,?,?,?) ON CONFLICT(tg_id) DO UPDATE SET
        name=excluded.name, phone=excluded.phone, district=excluded.district,
        role=excluded.role""",
        (tg_id, name, phone, district, role, datetime.now().isoformat(timespec="seconds")))
        await db.commit()

async def user_is_admin(tg_id):
    return tg_id in ADMIN_IDS

async def notify_admins(text, reply_markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:
            logging.exception("Admin notification failed: %s", admin_id)

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(
            "🔧 <b>USTA 24 ANDIJON</b>\n\nХуш келибсиз! Рўйхатдан ўтиш учун исм-фамилиянгизни ёзинг.",
            parse_mode="HTML"
        )
        await state.set_state(Register.name)
        return
    await message.answer(
        f"Ассалому алайкум, {user['name']}!\nUSTA 24 ANDIJON хизматларига хуш келибсиз.",
        reply_markup=main_menu(user["role"], await user_is_admin(message.from_user.id))
    )

@dp.message(Register.name)
async def reg_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Илтимос, исмингизни тўғри киритинг.")
        return
    await state.update_data(name=name)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Телефон рақамни юбориш", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Телефон рақамингизни юборинг ёки +998901234567 шаклида ёзинг.", reply_markup=kb)
    await state.set_state(Register.phone)

@dp.message(Register.phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else (message.text or "").strip()
    if len(phone) < 7:
        await message.answer("Телефон рақам нотўғри. Қайта киритинг.")
        return
    await state.update_data(phone=phone)
    await message.answer("Қайси туман/шаҳарда яшайсиз? Масалан: Андижон шаҳри.")
    await state.set_state(Register.district)

@dp.message(Register.district)
async def reg_district(message: Message, state: FSMContext):
    await state.update_data(district=(message.text or "").strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Мижозман", callback_data="role:client")],
        [InlineKeyboardButton(text="👨‍🔧 Устаман", callback_data="role:master")]
    ])
    await message.answer("Сиз кимсиз?", reply_markup=kb)
    await state.set_state(Register.role)

@dp.callback_query(Register.role, F.data.startswith("role:"))
async def reg_role(call: CallbackQuery, state: FSMContext):
    role = call.data.split(":")[1]
    data = await state.get_data()
    await save_user(call.from_user.id, data["name"], data["phone"], data["district"], role)
    await state.clear()
    await call.message.answer("✅ Рўйхатдан ўтиш якунланди!",
        reply_markup=main_menu(role, await user_is_admin(call.from_user.id)))
    await call.answer()
    if role == "master":
        await call.message.answer("Уста профилингизни тўлдириш учун «👨‍🔧 Уста бўлиш» тугмасини босинг.")

@dp.message(F.text == "👨‍🔧 Уста бўлиш")
async def master_apply_start(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Аввал /start орқали рўйхатдан ўтинг.")
        return
    await message.answer("Қайси хизмат тури бўйича ишлайсиз?", reply_markup=category_keyboard("apply"))
    await state.set_state(MasterApply.category)

@dp.callback_query(MasterApply.category, F.data.startswith("apply:"))
async def master_category(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split(":")[1])
    if not 0 <= idx < len(CATEGORIES):
        await call.answer("Нотўғри хизмат тури.", show_alert=True)
        return
    await state.update_data(category=CATEGORIES[idx])
    await call.message.answer("Иш тажрибангиз қанча? Масалан: 3 йил.")
    await state.set_state(MasterApply.experience)
    await call.answer()

@dp.message(MasterApply.experience)
async def master_experience(message: Message, state: FSMContext):
    await state.update_data(experience=(message.text or "").strip())
    await message.answer("Ўзингиз ва хизматингиз ҳақида қисқача маълумот ёзинг.")
    await state.set_state(MasterApply.about)

@dp.message(MasterApply.about)
async def master_about(message: Message, state: FSMContext):
    await state.update_data(about=(message.text or "").strip())
    await message.answer("Қайси туманларда хизмат кўрсатасиз?")
    await state.set_state(MasterApply.district)

@dp.message(MasterApply.district)
async def master_district(message: Message, state: FSMContext):
    data = await state.get_data()
    district = (message.text or "").strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO masters(tg_id,category,experience,about,district,approved)
        VALUES(?,?,?,?,?,0) ON CONFLICT(tg_id) DO UPDATE SET
        category=excluded.category, experience=excluded.experience,
        about=excluded.about, district=excluded.district, approved=0""",
        (message.from_user.id, data["category"], data["experience"], data["about"], district))
        await db.execute("UPDATE users SET role='master' WHERE tg_id=?", (message.from_user.id,))
        await db.commit()
    await state.clear()
    await message.answer("✅ Аризангиз администраторга юборилди. Текширувдан кейин хабар берамиз.",
        reply_markup=main_menu("master", await user_is_admin(message.from_user.id)))
    await notify_admins(
        f"🆕 <b>Янги уста аризаси</b>\nID: <code>{message.from_user.id}</code>\n"
        f"Йўналиш: {data['category']}\nТажриба: {data['experience']}\n"
        f"Маълумот: {data['about']}\nҲудуд: {district}",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Тасдиқлаш", callback_data=f"approve:{message.from_user.id}"),
            InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"reject:{message.from_user.id}")
        ]])
    )

@dp.callback_query(F.data.startswith("approve:"))
async def approve_master(call: CallbackQuery):
    if not await user_is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True); return
    mid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE masters SET approved=1 WHERE tg_id=?", (mid,))
        await db.commit()
    await bot.send_message(mid, "🎉 Уста профилингиз тасдиқланди! Энди янги буюртмаларни кўришингиз мумкин.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Уста тасдиқланди.")

@dp.callback_query(F.data.startswith("reject:"))
async def reject_master(call: CallbackQuery):
    if not await user_is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True); return
    mid = int(call.data.split(":")[1])
    await bot.send_message(mid, "Аризангиз ҳозирча тасдиқланмади. Маълумотни тўлдириб қайта мурожаат қилинг.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Ариза рад этилди.")

@dp.message(F.text == "📝 Буюртма бериш")
async def order_start(message: Message, state: FSMContext):
    if not await get_user(message.from_user.id):
        await message.answer("Аввал /start орқали рўйхатдан ўтинг."); return
    await message.answer("Қандай хизмат керак?", reply_markup=category_keyboard("order"))
    await state.set_state(NewOrder.category)

@dp.callback_query(NewOrder.category, F.data.startswith("order:"))
async def order_category(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split(":")[1])
    if not 0 <= idx < len(CATEGORIES):
        await call.answer("Нотўғри хизмат тури.", show_alert=True)
        return
    await state.update_data(category=CATEGORIES[idx])
    await call.message.answer("Муаммо ёки керакли ишни батафсил ёзинг.")
    await state.set_state(NewOrder.description)
    await call.answer()

@dp.message(NewOrder.description)
async def order_description(message: Message, state: FSMContext):
    await state.update_data(description=(message.text or "").strip())
    await message.answer("Хизмат кўрсатиладиган аниқ манзилни ёзинг.")
    await state.set_state(NewOrder.address)

@dp.message(NewOrder.address)
async def order_address(message: Message, state: FSMContext):
    await state.update_data(address=(message.text or "").strip())
    user = await get_user(message.from_user.id)
    await message.answer(f"Телефон рақамингизни юборинг ёки ёзинг.\nРўйхатдаги рақам: {user['phone']}")
    await state.set_state(NewOrder.phone)

@dp.message(NewOrder.phone)
async def order_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else (message.text or "").strip()
    if len(phone) < 7:
        await message.answer("Телефон рақам нотўғри. Қайта киритинг.")
        return
    await state.update_data(phone=phone)
    await message.answer("Муаммо расмини юборинг. Агар расм бўлмаса, «Расм йўқ» деб ёзинг.")
    await state.set_state(NewOrder.photo)

@dp.message(NewOrder.photo)
async def order_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    if not photo_id and (message.text or "").strip().lower() not in ("расм йўқ", "rasm yo'q", "йўқ"):
        await message.answer("Расм юборинг ёки «Расм йўқ» деб ёзинг.")
        return
    await state.update_data(photo_id=photo_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Нақд пул", callback_data="pay:cash")],
        [InlineKeyboardButton(text="💳 Карта орқали", callback_data="pay:card")],
    ])
    await message.answer("Тўлов турини танланг:", reply_markup=kb)
    await state.set_state(NewOrder.payment)

async def create_order_from_state(message: Message, state: FSMContext, payment_method: str,
                                  payment_status: str, receipt_file_id: str | None = None):
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""INSERT INTO orders(
            client_id,category,description,address,phone,photo_id,created_at,
            payment_method,payment_status,receipt_file_id,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (message.from_user.id, data["category"], data["description"], data["address"],
             data["phone"], data.get("photo_id"), datetime.now().isoformat(timespec="seconds"),
             payment_method, payment_status, receipt_file_id,
             "new" if payment_method == "cash" else "awaiting_payment"))
        order_id = cur.lastrowid
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""SELECT m.tg_id FROM masters m
            WHERE m.approved=1 AND m.category=?""", (data["category"],))
        masters = await cur.fetchall()

    method_label = "Нақд пул" if payment_method == "cash" else "Карта орқали"
    if payment_method == "cash":
        await message.answer(
            f"✅ Буюртмангиз қабул қилинди!\nБуюртма рақами: #{order_id}\n"
            f"Тўлов: {method_label} (иш тугагач устага тўланади).",
            reply_markup=main_menu("client", await user_is_admin(message.from_user.id)))
        send_to_masters = True
    else:
        await message.answer(
            f"🧾 Чек администраторга текшириш учун юборилди.\nБуюртма рақами: #{order_id}\n"
            "Тўлов тасдиқлангач, буюртма усталарга юборилади.",
            reply_markup=main_menu("client", await user_is_admin(message.from_user.id)))
        send_to_masters = False

    text = (f"🆕 <b>Буюртма #{order_id}</b>\nЙўналиш: {data['category']}\n"
            f"Тавсиф: {data['description']}\nМанзил: {data['address']}\n"
            f"Телефон: {data['phone']}\nТўлов: {method_label}\n"
            f"Тўлов ҳолати: {payment_status}")
    if payment_method == "card":
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Тўловни тасдиқлаш", callback_data=f"payok:{order_id}"),
            InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"payno:{order_id}")
        ]])
        for admin_id in ADMIN_IDS:
            try:
                if receipt_file_id:
                    await bot.send_photo(admin_id, receipt_file_id, caption=text,
                                         reply_markup=admin_kb, parse_mode="HTML")
                else:
                    await bot.send_message(admin_id, text, reply_markup=admin_kb, parse_mode="HTML")
            except Exception:
                logging.exception("Payment receipt notify failed")
    else:
        await notify_admins(text)

    if send_to_masters:
        await notify_matching_masters(order_id, data, message.from_user.id)

    await state.clear()

async def notify_matching_masters(order_id: int, data: dict, client_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT tg_id FROM masters WHERE approved=1 AND category=?",
                               (data["category"],))
        masters = await cur.fetchall()
    text = (f"🆕 <b>Янги буюртма #{order_id}</b>\nЙўналиш: {data['category']}\n"
            f"Тавсиф: {data['description']}\nМанзил: {data['address']}\nТелефон: {data['phone']}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Қабул қилиш", callback_data=f"take:{order_id}")
    ]])
    for master in masters:
        try:
            photo_id = data.get("photo_id")
            if photo_id:
                await bot.send_photo(master["tg_id"], photo_id, caption=text,
                                     reply_markup=kb, parse_mode="HTML")
            else:
                await bot.send_message(master["tg_id"], text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            logging.exception("Master notification failed")

@dp.callback_query(NewOrder.payment, F.data.startswith("pay:"))
async def choose_payment(call: CallbackQuery, state: FSMContext):
    method = call.data.split(":")[1]
    if method == "cash":
        data = await state.get_data()
        await call.message.answer("💵 Нақд тўлов танланди. Иш тугагач, ҳақни бевосита устага тўлайсиз.")
        # Callback has no Message sender context; use bot message as user-facing response and persist.
        class MessageProxy:
            from_user = call.from_user
            async def answer(self, text, **kwargs):
                await call.message.answer(text, **kwargs)
        proxy = MessageProxy()
        await create_order_from_state(proxy, state, "cash", "cash_on_delivery")
        await call.answer("Нақд тўлов танланди.")
        return

    if method == "card":
        if not CARD_NUMBER:
            await call.answer("Карта реквизитлари ҳали администратор томонидан созланмаган.", show_alert=True)
            return
        await state.update_data(payment_method="card")
        await call.message.answer(
            f"💳 <b>Карта орқали тўлов</b>\nКарта рақами: <code>{CARD_NUMBER}</code>\n"
            f"Қабул қилувчи: {CARD_HOLDER}\n\n"
            "Керакли суммани ўтказинг ва тўлов чекининг расмини юборинг. "
            "Администратор текшириб тасдиқлайди. Чек тасдиқланмагунча буюртма усталарга берилмайди.",
            parse_mode="HTML")
        await state.set_state(NewOrder.receipt)
        await call.answer()
        return
    await call.answer("Нотўғри тўлов тури.", show_alert=True)

@dp.message(NewOrder.receipt)
async def receive_payment_receipt(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Илтимос, тўлов чекининг расмини юборинг. Бекор қилиш: /cancel")
        return
    data = await state.get_data()
    class MessageProxy:
        from_user = message.from_user
        async def answer(self, text, **kwargs):
            await message.answer(text, **kwargs)
    proxy = MessageProxy()
    await create_order_from_state(proxy, state, "card", "receipt_sent", message.photo[-1].file_id)

@dp.callback_query(F.data.startswith("payok:"))
async def confirm_card_payment(call: CallbackQuery):
    if not await user_is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True)
        return
    oid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=? AND payment_method='card' AND payment_status='receipt_sent'",
                               (oid,))
        order = await cur.fetchone()
        if not order:
            await call.answer("Чек топилмади ёки аллақачон кўриб чиқилган.", show_alert=True)
            return
        await db.execute("UPDATE orders SET payment_status='paid', status='new' WHERE id=?", (oid,))
        await db.commit()
        cur = await db.execute("SELECT name FROM users WHERE tg_id=?", (order["client_id"],))
        client = await cur.fetchone()
    data = {"category": order["category"], "description": order["description"],
            "address": order["address"], "phone": order["phone"], "photo_id": order["photo_id"]}
    await notify_matching_masters(oid, data, order["client_id"])
    await bot.send_message(order["client_id"], f"✅ #{oid} буюртмангиз учун карта тўлови тасдиқланди. Усталарга юборилди.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Тўлов тасдиқланди.")

@dp.callback_query(F.data.startswith("payno:"))
async def reject_card_payment(call: CallbackQuery):
    if not await user_is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True)
        return
    oid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT client_id FROM orders WHERE id=? AND payment_method='card' AND payment_status='receipt_sent'",
                               (oid,))
        order = await cur.fetchone()
        if not order:
            await call.answer("Буюртма топилмади ёки аввал кўрилган.", show_alert=True)
            return
        await db.execute("UPDATE orders SET payment_status='rejected', status='payment_rejected' WHERE id=?", (oid,))
        await db.commit()
    await bot.send_message(order["client_id"], f"❌ #{oid} буюртмангиз бўйича тўлов чеки тасдиқланмади. Илтимос, администратор билан боғланинг.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Тўлов рад этилди.")

@dp.callback_query(F.data.startswith("take:"))
async def take_order(call: CallbackQuery):
    oid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM masters WHERE tg_id=? AND approved=1", (call.from_user.id,))
        master = await cur.fetchone()
        if not master:
            await call.answer("Фақат тасдиқланган усталар қабул қила олади.", show_alert=True); return
        cur = await db.execute("SELECT * FROM orders WHERE id=? AND status='new'", (oid,))
        order = await cur.fetchone()
        if not order:
            await call.answer("Бу буюртма аллақачон олинган ёки ёпилган.", show_alert=True); return
        if order["category"] != master["category"]:
            await call.answer("Бу буюртма сизнинг йўналишингизга мос эмас.", show_alert=True)
            return
        cur = await db.execute("UPDATE orders SET status='accepted', master_id=? WHERE id=? AND status='new'",
                               (call.from_user.id, oid))
        await db.commit()
        if cur.rowcount != 1:
            await call.answer("Буюртмани бошқа уста олиб бўлди.", show_alert=True)
            return
    await call.message.edit_reply_markup(reply_markup=None)
    await bot.send_message(call.from_user.id,
        f"✅ Сиз #{oid} буюртмани қабул қилдингиз. Иш тугагач, қуйидаги тугмани босинг.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🏁 Ишни якунлаш", callback_data=f"done:{oid}")
        ]]))
    await bot.send_message(order["client_id"],
        f"👨‍🔧 Буюртмангиз қабул қилинди!\nУста: {master['category']}\nУста ID: {call.from_user.id}\n"
        "Уста сиз билан боғланиши учун бироз кутинг.")
    await call.answer("Буюртма сизга бириктирилди!")

@dp.message(F.text == "🔍 Уста топиш")
async def find_masters(message: Message):
    await message.answer("Қайси йўналиш бўйича уста қидирасиз?", reply_markup=category_keyboard("find"))

@dp.callback_query(F.data.startswith("find:"))
async def find_masters_by_category(call: CallbackQuery):
    idx = int(call.data.split(":")[1])
    if not 0 <= idx < len(CATEGORIES):
        await call.answer("Нотўғри хизмат тури.", show_alert=True)
        return
    category = CATEGORIES[idx]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""SELECT m.*,u.name,u.phone FROM masters m
            JOIN users u ON u.tg_id=m.tg_id WHERE m.approved=1 AND m.category=?
            ORDER BY m.rating DESC""", (category,))
        rows = await cur.fetchall()
    if not rows:
        await call.message.answer(f"Ҳозирча «{category}» бўйича тасдиқланган уста топилмади.")
    for m in rows[:20]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❤️ Севимлиларга қўшиш", callback_data=f"fav:{m['tg_id']}")
        ]])
        await call.message.answer(
            f"👨‍🔧 <b>{m['name']}</b>\nЙўналиш: {m['category']}\nТажриба: {m['experience']}\n"
            f"Ҳудуд: {m['district']}\nРейтинг: {m['rating']:.1f} ⭐ ({m['reviews']} та)\n"
            f"Телефон: {m['phone']}", parse_mode="HTML", reply_markup=kb
        )
    await call.answer()

@dp.callback_query(F.data.startswith("fav:"))
async def favorite_master(call: CallbackQuery):
    mid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO favorites(client_id,master_id) VALUES(?,?)",
                         (call.from_user.id, mid))
        await db.commit()
    await call.answer("❤️ Севимли усталарга қўшилди!", show_alert=True)

@dp.message(F.text == "📋 Буюртмаларим")
async def my_orders(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE client_id=? ORDER BY id DESC LIMIT 10",
                               (message.from_user.id,))
        rows = await cur.fetchall()
    if not rows:
        await message.answer("Сизда ҳозирча буюртмалар йўқ."); return
    for o in rows:
        text = f"#{o['id']} — {o['category']}\n{o['description']}\nҲолати: {o['status']}"
        markup = None
        if o["status"] == "completed":
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT id FROM reviews WHERE order_id=?", (o["id"],))
                reviewed = await cur.fetchone()
            if not reviewed:
                markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="⭐ Баҳолаш", callback_data=f"rate:{o['id']}")
                ]])
        await message.answer(text, reply_markup=markup)

@dp.callback_query(F.data.startswith("done:"))
async def complete_order(call: CallbackQuery):
    oid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=? AND master_id=? AND status='accepted'",
                               (oid, call.from_user.id))
        order = await cur.fetchone()
        if not order:
            await call.answer("Буюртма топилмади ёки сизга тегишли эмас.", show_alert=True)
            return
        await db.execute("UPDATE orders SET status='completed' WHERE id=?", (oid,))
        await db.commit()
    await bot.send_message(order["client_id"], f"🏁 Буюртма #{oid} якунланди. «Буюртмаларим» бўлимидан устага баҳо беринг.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Буюртма якунланди.")

@dp.callback_query(F.data.startswith("rate:"))
async def rate_order(call: CallbackQuery):
    oid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=? AND client_id=? AND status='completed'",
                               (oid, call.from_user.id))
        order = await cur.fetchone()
        cur = await db.execute("SELECT id FROM reviews WHERE order_id=?", (oid,))
        already = await cur.fetchone()
    if not order or already:
        await call.answer("Баҳолаш мумкин эмас ёки аввал баҳоланган.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{n} ⭐", callback_data=f"rating:{oid}:{n}") for n in range(1, 6)
    ]])
    await call.message.answer(f"Буюртма #{oid} учун баҳо танланг:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("rating:"))
async def save_rating(call: CallbackQuery):
    _, oid_s, rating_s = call.data.split(":")
    oid, rating = int(oid_s), int(rating_s)
    if rating < 1 or rating > 5:
        await call.answer("Баҳо 1 дан 5 гача бўлиши керак.", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=? AND client_id=? AND status='completed'",
                               (oid, call.from_user.id))
        order = await cur.fetchone()
        if not order:
            await call.answer("Буюртма топилмади.", show_alert=True)
            return
        cur = await db.execute("SELECT id FROM reviews WHERE order_id=?", (oid,))
        if await cur.fetchone():
            await call.answer("Бу буюртма аллақачон баҳоланган.", show_alert=True)
            return
        await db.execute("""INSERT INTO reviews(order_id,client_id,master_id,rating,comment,created_at)
            VALUES(?,?,?,?,?,?)""",
            (oid, call.from_user.id, order["master_id"], rating, "", datetime.now().isoformat(timespec="seconds")))
        cur = await db.execute("SELECT AVG(rating),COUNT(*) FROM reviews WHERE master_id=?", (order["master_id"],))
        avg, count = await cur.fetchone()
        await db.execute("UPDATE masters SET rating=?,reviews=? WHERE tg_id=?",
                         (avg or 0, count or 0, order["master_id"]))
        await db.commit()
    await call.message.answer(f"Раҳмат! {rating} юлдузли баҳо сақланди.")
    await call.answer("Баҳо сақланди.")

@dp.message(F.text == "📥 Усталар учун буюртмалар")
async def master_orders(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""SELECT o.* FROM orders o JOIN masters m ON m.tg_id=?
            WHERE m.approved=1 AND o.status='new' AND (o.payment_method='cash' OR o.payment_status='paid')
            AND o.category=m.category ORDER BY o.id DESC LIMIT 10""",
            (message.from_user.id,))
        rows = await cur.fetchall()
    if not rows:
        await message.answer("Ҳозирча янги буюртмалар йўқ."); return
    for o in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Қабул қилиш", callback_data=f"take:{o['id']}")
        ]])
        await message.answer(f"Буюртма #{o['id']}\n{o['category']}\n{o['description']}\nМанзил: {o['address']}", reply_markup=kb)

@dp.message(F.text == "👤 Шахсий кабинет")
async def profile(message: Message):
    u = await get_user(message.from_user.id)
    if not u:
        await message.answer("Аввал /start орқали рўйхатдан ўтинг."); return
    await message.answer(f"👤 {u['name']}\n📞 {u['phone']}\n📍 {u['district']}\nРоль: {u['role']}")

@dp.message(F.text == "⭐ Баҳолар ва фикрлар")
async def reviews_info(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""SELECT r.rating,r.comment,u.name FROM reviews r
            LEFT JOIN users u ON u.tg_id=r.client_id ORDER BY r.id DESC LIMIT 10""")
        rows = await cur.fetchall()
    if not rows:
        await message.answer("⭐ Ҳозирча баҳолар йўқ. Бажарилган буюртмадан кейин баҳо беришингиз мумкин.")
        return
    for r in rows:
        await message.answer(f"⭐ {r['rating']}/5 — {r['name'] or 'Мижоз'}\n{r['comment'] or 'Изоҳ йўқ'}")

@dp.message(F.text == "❤️ Севимли усталар")
async def favorites_info(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""SELECT u.name,u.phone,m.category,m.district,m.rating,m.tg_id
            FROM favorites f JOIN users u ON u.tg_id=f.master_id
            JOIN masters m ON m.tg_id=f.master_id WHERE f.client_id=?""", (message.from_user.id,))
        rows = await cur.fetchall()
    if not rows:
        await message.answer("❤️ Севимлилар рўйхати бўш. «Уста топиш» бўлимидан усталарни сақланг.")
        return
    for m in rows:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Рўйхатдан ўчириш", callback_data=f"unfav:{m['tg_id']}")
        ]])
        await message.answer(f"❤️ {m['name']}\n{m['category']} | {m['district']}\nРейтинг: {m['rating']:.1f} ⭐\nТелефон: {m['phone']}", reply_markup=kb)

@dp.callback_query(F.data.startswith("unfav:"))
async def unfavorite_master(call: CallbackQuery):
    mid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM favorites WHERE client_id=? AND master_id=?", (call.from_user.id, mid))
        await db.commit()
    await call.message.edit_text("Севимли усталар рўйхатидан ўчирилди.")
    await call.answer("Ўчирилди")

@dp.message(F.text == "☎️ Ёрдам маркази")
async def help_center(message: Message, state: FSMContext):
    await message.answer("Савол ёки муаммоингизни ёзинг. Администраторга етказамиз. Бекор қилиш: /cancel")
    await state.set_state(HelpMessage.text)

@dp.message(HelpMessage.text)
async def help_message_send(message: Message, state: FSMContext):
    body = (message.text or "").strip()
    if len(body) < 3:
        await message.answer("Илтимос, мурожаатингизни батафсилроқ ёзинг.")
        return
    user = await get_user(message.from_user.id)
    name = user["name"] if user else message.from_user.full_name
    await notify_admins(f"☎️ <b>ЁРДАМ СЎРОВИ</b>\n{name} | ID: <code>{message.from_user.id}</code>\n{body}")
    await state.clear()
    await message.answer("✅ Мурожаатингиз администраторга юборилди.",
        reply_markup=main_menu(user["role"] if user else "client", await user_is_admin(message.from_user.id)))

@dp.message(F.text == "⚙️ Админ панели")
async def admin_panel(message: Message):
    if not await user_is_admin(message.from_user.id):
        await message.answer("⛔ Сизда администратор рухсати йўқ."); return
    await message.answer("⚙️ <b>АДМИН ПАНЕЛИ</b>", reply_markup=admin_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("adm:"))
async def admin_actions(call: CallbackQuery, state: FSMContext):
    if not await user_is_admin(call.from_user.id):
        await call.answer("Рухсат йўқ.", show_alert=True); return
    action = call.data.split(":")[1]
    if action == "stats":
        async with aiosqlite.connect(DB_PATH) as db:
            async def count(sql):
                cur = await db.execute(sql); return (await cur.fetchone())[0]
            users = await count("SELECT COUNT(*) FROM users")
            masters = await count("SELECT COUNT(*) FROM masters")
            approved = await count("SELECT COUNT(*) FROM masters WHERE approved=1")
            orders = await count("SELECT COUNT(*) FROM orders")
            new = await count("SELECT COUNT(*) FROM orders WHERE status='new'")
        await call.message.answer(f"📊 <b>Статистика</b>\nФойдаланувчилар: {users}\nУсталар: {masters}\nТасдиқланган усталар: {approved}\nБуюртмалар: {orders}\nЯнги буюртмалар: {new}", parse_mode="HTML")
    elif action == "masters":
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""SELECT m.*,u.name FROM masters m JOIN users u ON u.tg_id=m.tg_id
                WHERE m.approved=0 ORDER BY m.tg_id DESC LIMIT 20""")
            rows = await cur.fetchall()
        if not rows:
            await call.message.answer("Кутилayotgan тасдиқлаш аризалари йўқ.")
        for m in rows:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Тасдиқлаш", callback_data=f"approve:{m['tg_id']}"),
                InlineKeyboardButton(text="❌ Рад этиш", callback_data=f"reject:{m['tg_id']}")
            ]])
            await call.message.answer(f"{m['name']} | ID: {m['tg_id']}\n{m['category']}\n{m['experience']}\n{m['district']}", reply_markup=kb)
    elif action == "orders":
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM orders WHERE status='new' ORDER BY id DESC LIMIT 20")
            rows = await cur.fetchall()
        if not rows:
            await call.message.answer("Очиқ буюртмалар йўқ.")
        for o in rows:
            await call.message.answer(f"#{o['id']} | {o['category']}\n{o['description']}\nМижоз ID: {o['client_id']}")
    elif action == "broadcast":
        await call.message.answer("Барча фойдаланувчиларга юбориладиган хабар матнини ёзинг.")
        await state.set_state(Broadcast.text)
    await call.answer()

@dp.message(Broadcast.text)
async def broadcast_send(message: Message, state: FSMContext):
    if not await user_is_admin(message.from_user.id):
        await state.clear(); return
    text = (message.text or "").strip()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT tg_id FROM users")
        ids = [r[0] for r in await cur.fetchall()]
    sent = 0
    for uid in ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass
    await state.clear()
    await message.answer(f"📢 Хабар {sent} та фойдаланувчига юборилди.",
                         reply_markup=main_menu("client", True))

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    user = await get_user(message.from_user.id)
    await message.answer("Жорий амал бекор қилинди.",
        reply_markup=main_menu(user["role"] if user else "client", await user_is_admin(message.from_user.id)))

@dp.message()
async def fallback(message: Message):
    await message.answer("Менюдан керакли бўлимни танланг ёки /start буйруғини юборинг.")

async def main():
    await init_db()
    logging.info("USTA 24 ANDIJON bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
