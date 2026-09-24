import asyncio
import logging
import os
import sqlite3
import math
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from database import DB_NAME, init_db

TOKEN = os.getenv("BOT_TOKEN", "8480773029:AAGO1I2nYPGc8agez0UJziFm1qx0YBEUGAo")
ADMIN_IDS = {1321937398}

init_db()
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

SEASONS_LIST = [
    "Автогонки",
    "Мотогонки",
    "По инфе",
    "По новому",
    "Скорострелы"
]

SEASON_ICONS = {
    "Мотогонки": "🏍",
    "Ловля по инфе": "📱",
    "По инфе": "📱",
    "По новому": "✈️",
    "Автогонки": "🚗",
    "Скорострелы": "⌨️",
}

SELECT_COLUMNS = (
    "server_name, server_id, season, obj_type, slot, house_id, payday, "
    "insurance_status, exact_fall_time, is_frozen, is_h2, is_estate"
)

SERVERS_LIST = [
    ("01", "Phoenix"), ("02", "Tucson"), ("03", "Scottdale"), ("04", "Chandler"),
    ("05", "Brainburg"), ("06", "Saint-Rose"), ("07", "Mesa"), ("08", "Red-Rock"),
    ("09", "Yuma"), ("10", "Surprise"), ("11", "Prescott"), ("12", "Glendale"),
    ("13", "Kingman"), ("14", "Winslow"), ("15", "Payson"), ("16", "Gilbert"),
    ("17", "Show-Low"), ("18", "Casa-Grande"), ("19", "Page"), ("20", "Sun-City"),
    ("21", "Queen-Creek"), ("22", "Sedona"), ("23", "Holiday"), ("24", "Wednesday"),
    ("25", "Yava"), ("26", "Faraway"), ("27", "Bumble Bee"), ("28", "Christmas"),
    ("29", "Mirage"), ("30", "Love"), ("31", "Drake"), ("32", "Space"), ("33", "Home")
]


def db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manual_seasons (
            server_id TEXT PRIMARY KEY,
            season TEXT NOT NULL
        )
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(server_objects)").fetchall()}
    if "house_id" not in columns:
        conn.execute("ALTER TABLE server_objects ADD COLUMN house_id INTEGER;")
    if "is_frozen" not in columns:
        conn.execute("ALTER TABLE server_objects ADD COLUMN is_frozen INTEGER DEFAULT 0;")
    conn.commit()
    return conn


def has_access(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    conn = db()
    row = conn.execute(
        "SELECT expires_at FROM allowed_users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return False
    try:
        return datetime.fromisoformat(row[0]) > datetime.now()
    except (ValueError, TypeError):
        return False


def keyboard(user_id: int):
    rows = [
        [
            KeyboardButton(text="⚠️ Ближайшие слёты"),
            KeyboardButton(text="📋 Все слёты"),
        ],
        [
            KeyboardButton(text="🌐 По серверу"),
            KeyboardButton(text="🏆 Сезоны"),
        ],
        [
            KeyboardButton(text="📍 Статус"),
            KeyboardButton(text="😴 Стоит проснуться"),
        ],
    ]
    if user_id in ADMIN_IDS:
        rows.append([KeyboardButton(text="⚙️ Консоль разработчика")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def status_name(value):
    mapping = {
        "Страх": "Страх",
        "Застраховано": "Страх",
        "Нестрах": "Не страх",
        "Не застраховано": "Не страх",
        "Страх, Занят": "Страх, Занят",
        "Застраховано, есть занятость": "Страх, Занят",
        "Страх, Незанят": "Страх, Без занят",
        "Застраховано, нет занятости": "Страх, Без занят",
        "Нестрах, Без занятости": "Не страх, Без занят",
        "Не застраховано, без занятости": "Не страх, Без занят",
        "Неизвестно": "Неизвестно",
    }
    return mapping.get(value or "Неизвестно", "Неизвестно")


def get_season_icon(season_name):
    if not season_name:
        return "🌐"
    s = season_name.strip().lower()
    if "мото" in s or "moto" in s:
        return "🏍"
    if "инф" in s or "info" in s:
        return "📱"
    if "нов" in s or "new" in s:
        return "✈️"
    if "авто" in s or "гонк" in s:
        return "🚗"
    if "скорост" in s:
        return "⌨️"
    for key, icon in SEASON_ICONS.items():
        if key.lower() in s:
            return icon
    return "🌐"


def fetch_rows(where="", params=()):
    conn = db()
    query = f"SELECT {SELECT_COLUMNS} FROM server_objects"
    if where:
        query += " WHERE " + where
    query += " ORDER BY exact_fall_time ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


# -------------------------------------------------------------
# БЛИЖАЙШИЕ СЛЁТЫ
# -------------------------------------------------------------
def format_falls(rows, header_title):
    known_rows = [r for r in rows if r[8] and r[9] != 1]

    if not known_rows:
        return f"{header_title}\n\n⚠️ Точно известных активных слётов не обнаружено."

    conn = db()
    manual_dict = dict(conn.execute("SELECT server_id, season FROM manual_seasons").fetchall())
    conn.close()

    grouped = {}
    total_houses = 0
    total_biz = 0

    for row in known_rows:
        (
            server_name, server_id, season, obj_type, slot, house_id, payday, 
            status, fall_time, frozen, is_h2, is_estate
        ) = row

        if not fall_time: continue
        try:
            dt = datetime.fromisoformat(fall_time)
        except: continue

        if obj_type == "Дом": total_houses += 1
        elif obj_type == "Бизнес": total_biz += 1

        active_season = manual_dict.get(str(server_id)) or season or "Неизвестно"
        hour_key = dt.strftime("%H:00")
        
        hour_dict = grouped.setdefault(hour_key, {})
        srv_dict = hour_dict.setdefault((server_id, server_name, active_season), {"Дом": [], "Бизнес": []})
        srv_dict[obj_type].append(row)

    if not grouped:
        return f"{header_title}\n\n⚠️ Активных слётов не обнаружено."

    top_header = f"{header_title}\n🏠×{total_houses} 🏢×{total_biz}"
    body_lines = []

    for hour in sorted(grouped.keys()):
        body_lines.append(f"└─⚡ Слёты в {hour}:")
        srv_list = sorted(grouped[hour].items(), key=lambda x: x[0][1])

        several_servers = len(srv_list) > 1

        for s_idx, ((server_id, server_name, season), cat_groups) in enumerate(srv_list):
            is_last_server = (s_idx == len(srv_list) - 1)
            
            s_branch = "       └─" if is_last_server else "       ├─"
            s_bar = "       │  " if several_servers and not is_last_server else "          "

            icon_emoji = get_season_icon(season)
            body_lines.append(f"{s_branch}🌐 Сервер {server_name.upper()} {icon_emoji}")

            categories = []
            if cat_groups["Дом"]: categories.append(("📍 Дома:", cat_groups["Дом"]))
            if cat_groups["Бизнес"]: categories.append(("⭐ Бизнесы ⭐:", cat_groups["Бизнес"]))

            for c_idx, (cat_title, items) in enumerate(categories):
                is_last_cat = (c_idx == len(categories) - 1)
                
                c_branch = "               └─" if is_last_cat else "               ├─"
                body_lines.append(f"{c_branch}{cat_title}")

                sorted_items = sorted(items, key=lambda x: x[4])
                for i_idx, r in enumerate(sorted_items):
                    slot, house_id, payday, status = r[4], r[5], r[6], r[7]
                    info = status_name(status)
                    is_last_item = (i_idx == len(sorted_items) - 1)
                    
                    i_branch = "                       └─" if is_last_item else "                       ├─"
                    label = f"id {house_id}" if house_id else f"pos {slot}"
                    body_lines.append(f"{i_branch}{label} (PayDay: {payday}) - {info}")

        body_lines.append("")

    quote_content = "\n".join(body_lines).strip()
    return f"{top_header}\n<blockquote>{quote_content}</blockquote>"


# -------------------------------------------------------------
# ВСЕ СЛЁТЫ С ПАГИНАЦИЕЙ (ПО 3 ЧАСА НА СТРАНИЦУ)
# -------------------------------------------------------------
def get_all_falls_markup(page: int, total_pages: int):
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"all_page:{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"Стр. {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"all_page:{page+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[nav_row])


def format_all_falls_paged(page: int = 1):
    now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
    limit = now + timedelta(hours=24)
    rows = fetch_rows("is_frozen = 0 AND exact_fall_time BETWEEN ? AND ?", (now.isoformat(), limit.isoformat()))
    
    known_rows = [r for r in rows if r[8] and r[9] != 1]

    if not known_rows:
        return "📋 <b>Все слёты за 24 часа</b>\n\n⚠️ Точно известных активных слётов не обнаружено.", None

    conn = db()
    manual_dict = dict(conn.execute("SELECT server_id, season FROM manual_seasons").fetchall())
    conn.close()

    grouped = {}
    total_houses = 0
    total_biz = 0

    for row in known_rows:
        (
            server_name, server_id, season, obj_type, slot, house_id, payday, 
            status, fall_time, frozen, is_h2, is_estate
        ) = row

        if not fall_time: continue
        try:
            dt = datetime.fromisoformat(fall_time)
        except: continue

        if obj_type == "Дом": total_houses += 1
        elif obj_type == "Бизнес": total_biz += 1

        active_season = manual_dict.get(str(server_id)) or season or "Неизвестно"
        hour_key = dt.strftime("%H:00")
        
        hour_dict = grouped.setdefault(hour_key, {})
        srv_dict = hour_dict.setdefault((server_id, server_name, active_season), {"Дом": [], "Бизнес": []})
        srv_dict[obj_type].append(row)

    sorted_hours = sorted(grouped.keys())
    if not sorted_hours:
        return "📋 <b>Все слёты за 24 часа</b>\n\n⚠️ Активных слётов не обнаружено.", None

    hours_per_page = 3
    total_pages = math.ceil(len(sorted_hours) / hours_per_page)
    
    if page < 1: page = 1
    if page > total_pages: page = total_pages

    page_hours = sorted_hours[(page-1)*hours_per_page : page*hours_per_page]

    top_header = f"📋 <b>Все слёты за 24 часа</b> (Стр. {page}/{total_pages})\n🏠×{total_houses} 🏢×{total_biz}"
    body_lines = []

    for hour in page_hours:
        body_lines.append(f"└─⚡ Слёты в {hour}:")
        srv_list = sorted(grouped[hour].items(), key=lambda x: x[0][1])

        several_servers = len(srv_list) > 1

        for s_idx, ((server_id, server_name, season), cat_groups) in enumerate(srv_list):
            is_last_server = (s_idx == len(srv_list) - 1)
            
            s_branch = "       └─" if is_last_server else "       ├─"
            s_bar = "       │  " if several_servers and not is_last_server else "          "

            icon_emoji = get_season_icon(season)
            body_lines.append(f"{s_branch}🌐 Сервер {server_name.upper()} {icon_emoji}")

            categories = []
            if cat_groups["Дом"]: categories.append(("📍 Дома:", cat_groups["Дом"]))
            if cat_groups["Бизнес"]: categories.append(("⭐ Бизнесы ⭐:", cat_groups["Бизнес"]))

            for c_idx, (cat_title, items) in enumerate(categories):
                is_last_cat = (c_idx == len(categories) - 1)
                
                c_branch = "               └─" if is_last_cat else "               ├─"
                body_lines.append(f"{c_branch}{cat_title}")

                sorted_items = sorted(items, key=lambda x: x[4])
                for i_idx, r in enumerate(sorted_items):
                    slot, house_id, payday, status = r[4], r[5], r[6], r[7]
                    info = status_name(status)
                    is_last_item = (i_idx == len(sorted_items) - 1)
                    
                    i_branch = "                       └─" if is_last_item else "                       ├─"
                    label = f"id {house_id}" if house_id else f"pos {slot}"
                    body_lines.append(f"{i_branch}{label} (PayDay: {payday}) - {info}")

        body_lines.append("")

    quote_content = "\n".join(body_lines).strip()
    text = f"{top_header}\n<blockquote>{quote_content}</blockquote>"
    markup = get_all_falls_markup(page, total_pages) if total_pages > 1 else None
    return text, markup


# -------------------------------------------------------------
# ПО СЕРВЕРУ
# -------------------------------------------------------------
def format_server_compact(rows, server_id, server_name):
    conn = db()
    m_row = conn.execute("SELECT season FROM manual_seasons WHERE server_id = ?", (str(server_id),)).fetchone()
    conn.close()

    season = m_row[0] if m_row and m_row[0] else (rows[0][2] if rows else "Неизвестно")
    icon = get_season_icon(season)

    now_msk = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)

    active_rows = []
    for r in rows:
        fall_time = r[8]
        if fall_time:
            try:
                f_dt = datetime.fromisoformat(fall_time)
                if f_dt <= now_msk:
                    continue
            except:
                pass
        active_rows.append(r)

    if not active_rows:
        return f"🌐 <b>Сервер {server_name.upper()}[{server_id}]</b>\n<blockquote>└─ Сезон 🌐 \"<b>{season.upper()}</b>\" {icon}\n\n⚠️ Активных объектов не обнаружено.</blockquote>"

    result = [f"└─ Сезон 🌐 \"{season.upper()}\" {icon}"]
    houses = [r for r in active_rows if r[3] == "Дом"]
    businesses = [r for r in active_rows if r[3] == "Бизнес"]

    def make_entry(r):
        slot, house_id, payday, status, fall_time, is_frozen = r[4], r[5], r[6], r[7], r[8], r[9]
        label = f"id {house_id}" if house_id else f"pos {slot}"
        info = status_name(status)
        
        time_part = ""
        if fall_time:
            try:
                f_dt = datetime.fromisoformat(fall_time)
                time_part = f" | {f_dt.strftime('%H:00')}"
            except:
                pass
                
        frozen_mark = " (🔒 Заморожен)" if is_frozen == 1 else ""
        return f"   {label} (PayDay: {payday}) - {info}{time_part}{frozen_mark}"

    if houses:
        result.append("└─ 🏠 Дома:")
        for r in sorted(houses, key=lambda x: x[4]):
            result.append(make_entry(r))

    if businesses:
        result.append("└─ ✨ Бизнесы:")
        for r in sorted(businesses, key=lambda x: x[4]):
            result.append(make_entry(r))

    return f"🌐 <b>Сервер {server_name.upper()}</b>\n<blockquote>" + "\n".join(result) + "</blockquote>"


@dp.message(Command("start"))
async def start(message: types.Message):
    if not has_access(message.from_user.id):
        await message.answer("🔒 У вас нет доступа.")
        return
    await message.answer("👋 <b>Arizona Tracker</b>", reply_markup=keyboard(message.from_user.id), parse_mode="HTML")


# -------------------------------------------------------------
# КОМАНДЫ АДМИНИСТРАТОРА (УПРАВЛЕНИЕ КЛЮЧАМИ)
# -------------------------------------------------------------
@dp.message(Command("users"))
async def list_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    conn = db()
    rows = conn.execute("SELECT user_id, expires_at FROM allowed_users").fetchall()
    conn.close()
    
    if not rows:
        await message.answer("👥 Список разрешенных пользователей пуст.")
        return
        
    lines = ["👥 <b>Список пользователей с доступом:</b>\n"]
    for uid, expires in rows:
        try:
            dt = datetime.fromisoformat(expires)
            formatted = dt.strftime("%d.%m.%Y %H:%M")
        except:
            formatted = expires
        lines.append(f"• <code>{uid}</code> — до <i>{formatted}</i>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("grant"))
async def grant_user(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("⚠️ Использование: <code>/grant [ID] [дни]</code>\nПример: <code>/grant 123456789 30</code>", parse_mode="HTML")
        return
        
    try:
        target_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("⚠️ ID и количество дней должны быть числами!")
        return
        
    expires_dt = datetime.now() + timedelta(days=days)
    expires_str = expires_dt.isoformat()
    
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO allowed_users (user_id, expires_at) VALUES (?, ?)",
        (target_id, expires_str)
    )
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Доступ для <code>{target_id}</code> успешно выдан на <b>{days}</b> дней (до {expires_dt.strftime('%d.%m.%Y %H:%M')}).", parse_mode="HTML")


@dp.message(Command("revoke"))
async def revoke_user(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Использование: <code>/revoke [ID]</code>\nПример: <code>/revoke 123456789</code>", parse_mode="HTML")
        return
        
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("⚠️ ID должен быть числом!")
        return
        
    conn = db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM allowed_users WHERE user_id = ?", (target_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    if deleted > 0:
        await message.answer(f"⛔️ Доступ для <code>{target_id}</code> успешно аннулирован.", parse_mode="HTML")
    else:
        await message.answer(f"❓ Пользователь <code>{target_id}</code> не найден в списке доступов.", parse_mode="HTML")


# -------------------------------------------------------------
# ДРУГИЕ КОМАНДЫ БОТА
# -------------------------------------------------------------
@dp.message(F.text.in_({"⚠️ Ближайшие слёты", "Ближайшие слёты"}))
async def nearest(message: types.Message):
    if not has_access(message.from_user.id): return
    now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
    limit = now + timedelta(hours=3)
    rows = fetch_rows("is_frozen = 0 AND exact_fall_time BETWEEN ? AND ?", (now.isoformat(), limit.isoformat()))
    await message.answer(format_falls(rows, "⚠️ <b>Слёты в ближайшие 3 часа</b>"), parse_mode="HTML")


@dp.message(F.text.in_({"📋 Все слёты", "Все слёты"}))
async def all_falls(message: types.Message):
    if not has_access(message.from_user.id): return
    text, markup = format_all_falls_paged(1)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.callback_query(F.data.startswith("all_page:"))
async def all_falls_page_callback(callback: types.CallbackQuery):
    if not has_access(callback.from_user.id): return
    page = int(callback.data.split(":")[1])
    text, markup = format_all_falls_paged(page)
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data == "noop")
async def noop_callback(callback: types.CallbackQuery):
    await callback.answer()


@dp.message(F.text.in_({"🌐 По серверу", "По серверу"}))
async def servers_menu(message: types.Message):
    if not has_access(message.from_user.id): return
    buttons = [[InlineKeyboardButton(text=f"{n} [{i}]", callback_data=f"srv:{i}") for i, n in SERVERS_LIST[j:j+2]] for j in range(0, len(SERVERS_LIST), 2)]
    await message.answer("🌐 Выберите сервер:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("srv:"))
async def server_result(callback: types.CallbackQuery):
    if not has_access(callback.from_user.id): return
    sid = callback.data.split(":")[1]
    sname = next((n for i, n in SERVERS_LIST if i == sid), sid)
    rows = fetch_rows("server_id = ?", (sid,))
    await callback.message.answer(format_server_compact(rows, sid, sname), parse_mode="HTML")
    await callback.answer()


@dp.message(F.text.in_({"🏆 Сезоны", "Сезоны"}))
async def seasons_overview(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    lines = ["🏆 <b>Текущие сезоны:</b>", ""]
    for sid, sname in SERVERS_LIST:
        m = conn.execute("SELECT season FROM manual_seasons WHERE server_id = ?", (sid,)).fetchone()
        season = m[0] if m else "Неизвестно"
        lines.append(f"<code>[{sid}] {sname:<11}</code> {get_season_icon(season)} {season}")
    conn.close()
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text.in_({"⚙️ Консоль разработчика", "Консоль разработчика"}))
async def dev_console(message: types.Message):
    if message.from_user.id not in ADMIN_IDS: return
    buttons = [[InlineKeyboardButton(text=f"[{i}] {n}", callback_data=f"devsrv:{i}") for i, n in SERVERS_LIST[j:j+2]] for j in range(0, len(SERVERS_LIST), 2)]
    await message.answer("⚙️ <b>Консоль разработчика</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@dp.callback_query(F.data.startswith("devsrv:"))
async def dev_select_server(callback: types.CallbackQuery):
    sid = callback.data.split(":")[1]
    buttons = [[InlineKeyboardButton(text=s, callback_data=f"devset:{sid}:{s}")] for s in SEASONS_LIST]
    await callback.message.answer(f"⚙️ Выберите сезон для [{sid}]:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("devset:"))
async def dev_set_season(callback: types.CallbackQuery):
    _, sid, season = callback.data.split(":")
    conn = db()
    conn.execute("INSERT OR REPLACE INTO manual_seasons (server_id, season) VALUES (?, ?)", (sid, season))
    conn.commit()
    conn.close()
    await callback.message.answer(f"✅ Для [{sid}] установлен сезон: <b>{season}</b>", parse_mode="HTML")
    await callback.answer()


@dp.message(F.text.in_({"📍 Статус", "Статус"}))
async def status_msg(message: types.Message):
    if not has_access(message.from_user.id): return
    conn = db()
    
    server_status = []
    for s_id, s_name in SERVERS_LIST:
        row = conn.execute(
            "SELECT recorded_at FROM scan_history WHERE server_id = ? ORDER BY id DESC LIMIT 1",
            (str(s_id),)
        ).fetchone()
        val = row[0] if row else None
        
        if not val:
            row_obj = conn.execute(
                "SELECT MAX(last_updated) FROM server_objects WHERE server_id = ?",
                (str(s_id),)
            ).fetchone()
            val = row_obj[0] if row_obj else None
            
        if val:
            server_status.append((s_name, val))
            
    conn.close()
    
    def parse_dt(val_str):
        try:
            return datetime.strptime(val_str, "%d.%m.%Y %H:%M:%S")
        except:
            return datetime.min
            
    server_status.sort(key=lambda x: parse_dt(x[1]), reverse=True)
    
    if not server_status:
        await message.answer("📍 Данных о сканировании пока нет.")
        return
        
    lines = ["📍 <b>Последние сейвы по серверам:</b>", ""]
    for name, value in server_status:
        lines.append(f"<code>{name:<14} | {value}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text.in_({"😴 Стоит проснуться", "Стоит проснуться"}))
async def wakeup(message: types.Message):
    if not has_access(message.from_user.id): return
    rows = fetch_rows("is_frozen = 0")
    known = [r for r in rows if r[8]]
    grouped = {}
    for row in known: grouped.setdefault((row[8], row[1]), []).append(row)
    selected = []
    for values in grouped.values():
        if any(row[3] == "Бизнес" for row in values) or sum(row[3] == "Дом" for row in values) > 5: selected.extend(values)
    await message.answer(format_falls(selected, "😴 <b>Стоит проснуться</b>"), parse_mode="HTML")


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
