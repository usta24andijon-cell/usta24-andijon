
    import asyncio
import logging
import os
import re
import sqlite3
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
]
DB_PATH = os.getenv("DB_PATH", "usta24.db")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
BASE_DIR = Path(__file__).resolve().parent
INDEX_PATH = BASE_DIR / "index.html"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("usta24")

router = Router()

SERVICES = {
    "🔧 Сантехника хизмати": 0,
    "⚡ Электр хизмати": 0,
    "🪑 Мебел хизмати": 0,
    "🔩 Пайвандлаш ишлари": 0,
    "❄️ Кондиционер хизмати": 0,
    "🧺 Маиший техника таъмири": 0,
    "🧹 Уй тозалаш хизмати": 0,
    "🚚 Юк ташиш хизмати": 0,
    "🛠 Бошқа хизмат": 0,
}

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛠 Хизмат танлаш")],
        [KeyboardButton(text="📋 Буюртмаларим")],
        [KeyboardButton(text="ℹ️ Ёрдам")],
    ],
    resize_keyboard=True,
)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mijoz_id INTEGER,
                mijoz_ismi TEXT NOT NULL,
                telefon TEXT NOT NULL,
                service TEXT NOT NULL,
                address TEXT NOT NULL,
                description TEXT NOT NULL,
                price INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Янги',
                created_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'telegram'
            )
        """)
        table_info = list(conn.execute("PRAGMA table_info(orders)"))
        columns = {row[1] for row in table_info}
        mijoz_id_not_null = any(
            row[1] == "mijoz_id" and row[3] == 1
            for row in table_info
        )

        if mijoz_id_not_null:
            conn.execute("ALTER TABLE orders RENAME TO orders_old_migration")
            conn.execute("""
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mijoz_id INTEGER,
                    mijoz_ismi TEXT NOT NULL,
                    telefon TEXT NOT NULL,
                    service TEXT NOT NULL,
                    address TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'Янги',
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'telegram'
                )
            """)
            old_columns = {
                row[1] for row in
                conn.execute("PRAGMA table_info(orders_old_migration)")
            }
            source_expr = "source" if "source" in old_columns else "'telegram'"
            conn.execute(f"""
                INSERT INTO orders
                (id, mijoz_id, mijoz_ismi, telefon, service, address,
                 description, price, status, created_at, source)
                SELECT id, mijoz_id, mijoz_ismi, telefon, service, address,
                       description, price, status, created_at, {source_expr}
                FROM orders_old_migration
            """)
            conn.execute("DROP TABLE orders_old_migration")
        elif "source" not in columns:
            conn.execute(
                "ALTER TABLE orders ADD COLUMN source TEXT NOT NULL DEFAULT 'telegram'"
            )
        conn.commit()

def create_order(
    mijoz_id: Optional[int], mijoz_ismi: str, telefon: str, service: str,
    address: str, description: str, source: str = "telegram", price: int = 0
) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("""
            INSERT INTO orders
            (mijoz_id, mijoz_ismi, telefon, service, address,
             description, price, status, created_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Янги', ?, ?)
        """, (
            mijoz_id, mijoz_ismi, telefon, service, address,
            description, price,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source
        ))
        conn.commit()
        return int(cur.lastrowid)

def get_user_orders(user_id: int, limit: int = 10):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT id, service, status, price, created_at, address
            FROM orders WHERE mijoz_id = ?
            ORDER BY id DESC LIMIT ?
        """, (user_id, limit)).fetchall()

def get_order(order_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("""
            SELECT id, mijoz_id, mijoz_ismi, telefon, service, address,
                   description, price, status, created_at, source
            FROM orders WHERE id = ?
        """, (order_id,)).fetchone()

def update_order_status(order_id: int, status: str):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT mijoz_id FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE orders SET status = ? WHERE id = ?", (status, order_id)
        )
        conn.commit()
        return row[0]def status_keyboard(order_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏳ Jarayonda", callback_data=f"status:{order_id}:Jarayonda"),
            InlineKeyboardButton(text="✅ Бажарилди", callback_data=f"status:{order_id}:Бажарилди"),
        ],
        [InlineKeyboardButton(text="❌ Рад этилди", callback_data=f"status:{order_id}:Рад этилди")],
    ])


async def notify_admins(bot: Bot, order_id: int):
    order = get_order(order_id)
    if not order:
        return
    oid, customer_id, customer_name, phone, service, address, description, price, status, created_at, source = order
    price_text = f"{price:,}".replace(",", " ") + " сўм" if price else "Уста билан келишилади"
    text = (
        f"🆕 <b>Янги буюртма #{oid}</b>\n\n"
        f"📥 Манба: {escape(source)}\n"
        f"👤 Мижоз: {escape(customer_name)}\n"
        f"🆔 Telegram ID: {customer_id if customer_id else 'Веб-сайт орқали'}\n"
        f"📞 Телефон: {escape(phone)}\n"
        f"🛠 Хизмат: {escape(service)}\n"
        f"📍 Манзил: {escape(address)}\n"
        f"📝 Тавсиф: {escape(description)}\n"
        f"💰 Нарx: {price_text}\n"
        f"🕒 Вақт: {escape(created_at)}"
    )
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS sozlanmagan. Buyurtma bazaga saqlandi, lekin adminlarga yuborilmadi.")
        return
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=status_keyboard(oid))
        except Exception:
            logger.exception("Admin %s ga xabar yuborilmadi", admin_id)


class OrderForm(StatesGroup):
    service = State()
    phone = State()
    address = State()
    description = State()


def service_keyboard():
    names = list(SERVICES)
    rows = [[KeyboardButton(text=n) for n in names[i:i + 2]] for i in range(0, len(names), 2)]
    rows.append([KeyboardButton(text="⬅️ Бош меню")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Бекор қилиш")]],
    resize_keyboard=True,
)


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    name = escape(message.from_user.first_name or "мижоз")
    await message.answer(
        f"Ассалому алайкум, <b>{name}</b>!\n\n"
        "👋 <b>USTA 24 АНДИЖОН</b> ботига хуш келибсиз.\n"
        "Хизмат танлаб буюртма қолдиришингиз ёки сайт орқали буюртма беришингиз мумкин.",
        reply_markup=MAIN_KEYBOARD,
    )


@router.message(Command("cancel"))
@router.message(F.text == "❌ Бекор қилиш")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Буюртма бериш бекор қилинди.", reply_markup=MAIN_KEYBOARD)


@router.message(F.text == "⬅️ Бош меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Бош меню", reply_markup=MAIN_KEYBOARD)


@router.message(F.text == "🛠 Хизмат танлаш")
async def choose_service(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Қайси хизмат керак?", reply_markup=service_keyboard())


@router.message(F.text.in_(list(SERVICES.keys())))
async def service_selected(message: Message, state: FSMContext):
    await state.update_data(service=message.text)
    await state.set_state(OrderForm.phone)
    await message.answer("📞 Телефон рақамингизни киритинг:", reply_markup=CANCEL_KEYBOARD)


@router.message(OrderForm.phone, F.text)
async def get_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(phone) < 7 or len(phone) > 25:
        await message.answer("Телефон рақами нотўғри кўринади. Қайта киритинг:")
        return
    await state.update_data(phone=phone)
    await state.set_state(OrderForm.address)
    await message.answer("📍 Манзилингизни киритинг:")


@router.message(OrderForm.address, F.text)
async def get_address(message: Message, state: FSMContext):
    address = message.text.strip()
    if len(address) < 3:
        await message.answer("Манзилни батафсилроқ киритинг:")
        return
    await state.update_data(address=address)
    await state.set_state(OrderForm.description)
    await message.answer("📝 Қандай иш кераклигини қисқача ёзинг:")


@router.message(OrderForm.description, F.text)
async def get_description(message: Message, state: FSMContext, bot: Bot):
    description = message.text.strip()
    if len(description) < 3:
        await message.answer("Иш ҳақида батафсилроқ ёзинг:")
        return
    data = await state.get_data()
    user = message.from_user
    order_id = create_order(
        mijoz_id=user.id,
        mijoz_ismi=user.full_name or user.first_name or "Мижоз",
        telefon=data["phone"],
        service=data["service"],
        address=data["address"],
        description=description,
        source="telegram",
    )
    await state.clear()
    await message.answer(
        f"✅ Буюртмангиз қабул қилинди!\n"
        f"🆔 Рақам: <b>#{order_id}</b>\n"
        "Администратор тез орада сиз билан боғланади.",
        reply_markup=MAIN_KEYBOARD,
    )
    await notify_admins(bot, order_id)


@router.message(F.text == "📋 Буюртмаларим")
async def my_orders(message: Message):
    orders = get_user_orders(message.from_user.id)
    if not orders:
        await message.answer("📭 Сизда ҳали буюртмалар йўқ.", reply_markup=MAIN_KEYBOARD)
        return
    lines = ["📋 <b>Сизнинг охирги буюртмаларингиз:</b>\n"]
    for oid, service, status, price, created_at, address in orders:
        price_text = f"{price:,}".replace(",", " ") + " сўм" if price else "Келишилади"
        lines.append(
            f"🆔 <b>#{oid}</b> — {escape(service)}\n"
            f"Ҳолат: <i>{escape(status)}</i>\n"
            f"💰 {price_text}\n📍 {escape(address)}\n🕒 {escape(created_at)}"
        )
    await message.answer("\n\n".join(lines), reply_markup=MAIN_KEYBOARD)


@router.message(F.text == "ℹ️ Ёрдам")
async def help_handler(message: Message):
    await message.answer(
        "ℹ️ <b>Ёрдам</b>\n"
        "1. «🛠 Хизмат танлаш»ни босинг.\n"
        "2. Хизмат, телефон, манзил ва иш тавсифини юборинг.\n"
        "3. «📋 Буюртмаларим» бўлимида буюртмаларингизни кўринг.",
        reply_markup=MAIN_KEYBOARD,
    )


@router.callback_query(F.data.startswith("status:"))
async def admin_change_status(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Бу амал фақат администратор учун.", show_alert=True)
        return
    try:
        _, order_id_text, new_status = callback.data.split(":", 2)
        order_id = int(order_id_text)
    except (ValueError, AttributeError):
        await callback.answer("Буюртма маълумоти нотўғри.", show_alert=True)
        return
    if new_status not in {"Jarayonda", "Бажарилди", "Рад этилди"}:
        await callback.answer("Номаълум ҳолат.", show_alert=True)
        return
    customer_id = update_order_status(order_id, new_status)
    if customer_id is None:
        await callback.answer("Буюртма топилмади.", show_alert=True)
        return
    await callback.answer("Ҳолат янгиланди.")
    if customer_id:
        try:
            await bot.send_message(
                customer_id,
                f"📣 <b>#{order_id}</b> буюртмангиз ҳолати: <i>{escape(new_status)}</i>",
            )
        except Exception:
            logger.exception("Mijozga status xabari yuborilmadi")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"✅ #{order_id} ҳолати: <b>{escape(new_status)}</b>")


@router.message()
async def fallback(message: Message):
    await message.answer(
        "🤖 Тушунмадим. Илтимос, менюдан фойдаланинг.\n/start",
        reply_markup=MAIN_KEYBOARD,
    )# =========================================================
# SAYT BACKENDI
# =========================================================

def clean_field(value, max_len=1000):
    return str(value or "").strip()[:max_len]


async def homepage(request: web.Request):
    if not INDEX_PATH.exists():
        return web.Response(text="index.html topilmadi", status=404)
    return web.FileResponse(INDEX_PATH)


async def create_web_order(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "message": "Ma'lumot formati noto'g'ri."},
            status=400,
        )

    name = clean_field(data.get("name"), 100)
    phone = clean_field(data.get("phone"), 30)
    service = clean_field(data.get("service"), 150)
    address = clean_field(data.get("address"), 250)
    description = clean_field(data.get("description"), 1500)

    if not all([name, phone, service, address, description]):
        return web.json_response(
            {"ok": False, "message": "Barcha maydonlarni to'ldiring."},
            status=400,
        )

    if len(name) < 2 or len(phone) < 7 or not re.search(r"\d{7,}", phone):
        return web.json_response(
            {"ok": False, "message": "Ism yoki telefon raqamini tekshiring."},
            status=400,
        )

    if service not in SERVICES:
        return web.json_response(
            {"ok": False, "message": "Xizmat ro'yxatda topilmadi."},
            status=400,
        )

    order_id = create_order(
        mijoz_id=None,
        mijoz_ismi=name,
        telefon=phone,
        service=service,
        address=address,
        description=description,
        source="website",
    )

    bot: Bot = request.app["bot"]

    try:
        await notify_admins(bot, order_id)
    except Exception:
        logger.exception("Web order adminlarga yuborishda xatolik")

    return web.json_response({
        "ok": True,
        "order_id": order_id,
        "message": f"Buyurtmangiz qabul qilindi! Raqam: #{order_id}",
    })


async def health(request: web.Request):
    return web.json_response({"ok": True, "service": "USTA 24"})


async def start_web_server(bot: Bot):
    app = web.Application(client_max_size=64 * 1024)
    app["bot"] = bot
    app.router.add_get("/", homepage)
    app.router.add_post("/api/order", create_web_order)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, HOST, PORT)
    await site.start()

    logger.info("Sayt: http://%s:%s", HOST, PORT)
    return runner


async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN sozlanmagan. Render Environment'га BOT_TOKEN киритинг."
        )

    if not ADMIN_IDS:
        logger.warning(
            "ADMIN_IDS sozlanmagan. Buyurtmalar bazaga saqlanadi, "
            "ammo adminlarga Telegram xabari yuborilmaydi."
        )

    init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    runner = None

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        runner = await start_web_server(bot)

        logger.info("USTA 24 ANDIJON bot ishga tushdi.")

        await dp.start_polling(bot)

    finally:
        if runner:
            await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi.")
