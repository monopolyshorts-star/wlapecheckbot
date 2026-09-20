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
# БЛИЖАЙШИЕ / ВСЕ СЛЁТЫ (ФИНАЛЬНЫЕ ТОЧНЫЕ ПРАВКИ)
# -------------------------------------------------------------
def format_falls(rows, header_title):
    known_rows = [r for r in rows if r[7] and r[7] != "Неизвестно"]

    if not known_rows:
        return f"{header_title}\n\n⚠️ Точно известных слётов не обнаружено."

    conn = db()
    manual_dict = dict(conn.execute("SELECT server_id, season FROM manual_seasons").fetchall())
    conn.close()

    grouped = {}
    total_houses = 0
    total_biz = 0

    for row in known_rows:
        (
            server_name,
            server_id,
            season,
            obj_type,
            slot,
            house_id,
            payday,
            status,
            fall_time,
            frozen,
            is_h2,
            is_estate,
        ) = row

        if not fall_time:
            continue

        try:
            dt = datetime.fromisoformat(fall_time)
        except (ValueError, TypeError):
            continue

        if obj_type == "Дом":
            total_houses += 1
        elif obj_type == "Бизнес":
            total_biz += 1

        active_season = manual_dict.get(str(server_id)) or season or "Неизвестно"
        hour_key = dt.strftime("%H:00")
        
        hour_dict = grouped.setdefault(hour_key, {})
        srv_dict = hour_dict.setdefault((server_id, server_name, active_season), {"Дом": [], "Бизнес": []})
        srv_dict[obj_type].append(row)

    if not grouped:
        return f"{header_title}\n\n⚠️ Точно известных слётов с рассчитанным временем не обнаружено."

    top_header = f"{header_title}\n🏠×{total_houses} 🏢×{total_biz}"
    body_lines = []

    for hour in sorted(grouped.keys()):
        body_lines.append(f"└─⚡️ Слёты в {hour}:")
        srv_list = sorted(grouped[hour].items(), key=lambda x: x[0][1])

        several_servers = len(srv_list) > 1

        for s_idx, ((server_id, server_name, season), cat_groups) in enumerate(srv_list):
            is_last_server = (s_idx == len(srv_list) - 1)
            
            # Сервер остается на месте (7 пробелов)
            server_branch = "       └─" if is_last_server else "       ├─"
            server_bar   = "       │  " if several_servers and not is_last_server else "          "

            icon_emoji = get_season_icon(season)
            body_lines.append(f"{server_branch}🌐 Сервер {server_name.upper()} {icon_emoji}")

            categories = []
            if cat_groups["Дом"]:
                categories.append(("Дом", "📍 Дома:", cat_groups["Дом"]))
            if cat_groups["Бизнес"]:
                categories.append(("Бизнес", "⭐ Бизнесы ⭐:", cat_groups["Бизнес"]))

            for c_idx, (kind, cat_title, items) in enumerate(categories):
                is_last_cat = (c_idx == len(categories) - 1)
                
                # Дома/Бизнесы сдвинуты на 4 пробела влево (было 9, стало 5)
                cat_branch = "     └─" if is_last_cat else "     ├─"
                cat_bar   = "     │  " if not is_last_cat else "        "

                body_lines.append(f"{server_bar}{cat_branch}{cat_title}")

                sorted_items = sorted(items, key=lambda x: x[4])
                for i_idx, r in enumerate(sorted_items):
                    slot, house_id, payday, status = r[4], r[5], r[6], r[7]
                    info = status_name(status)
                    is_last_item = (i_idx == len(sorted_items) - 1)
                    
                    # Позиции (pos) сдвинуты еще на 7 влево (было 8, стало 1)
                    item_branch = " └─" if is_last_item else " ├─"

                    item_label = f"id {house_id}" if house_id else f"pos {slot}"
                    body_lines.append(f"{server_bar}{cat_bar}{item_branch}{item_label} (PayDay: {payday}) - {info}")

        body_lines.append("")

    quote_content = "\n".join(body_lines).strip()
    return f"{top_header}\n<blockquote>{quote_content}</blockquote>"


# -------------------------------------------------------------
# ПО СЕРВЕРУ (ПОЛНЫЙ СПИСОК В ЦИТАТЕ)
# -------------------------------------------------------------
def format_server_compact(rows, server_id, server_name):
    conn = db()
    m_row = conn.execute("SELECT season FROM manual_seasons WHERE server_id = ?", (str(server_id),)).fetchone()
    conn.close()

    season = "Неизвестно"
    if m_row and m_row[0]:
        season = m_row[0]
    elif rows and rows[0][2]:
        season = rows[0][2]

    season_icon = get_season_icon(season)

    if not rows:
        return f"🌐 <b>Сервер {server_name.upper()}[{server_id}]</b>\n<blockquote>└─ Сезон 🌐 \"<b>{season.upper()}</b>\" {season_icon}\n\n⚠️ Активных объектов не обнаружено.</blockquote>"

    result = [
        f"└─ Сезон 🌐 \"{season.upper()}\" {season_icon}",
    ]

    houses = [r for r in rows if r[3] == "Дом"]
    businesses = [r for r in rows if r[3] == "Бизнес"]

    if houses:
        result.append("└─ 🏠 Дома:")
        for r in sorted(houses, key=lambda x: x[4]):
            _, _, _, _, slot, house_id, payday, status, fall_time, _, _, is_estate = r
            info = status_name(status)
            if is_estate:
                info += " (🔒 С поместьем)"
            time_str = ""
            if fall_time:
                try:
                    dt = datetime.fromisoformat(fall_time)
                    time_str = f" | ⏰ {dt.strftime('%H:%M')}"
                except:
                    pass
            
            prefix = f"id {house_id}" if house_id else f"pos {slot}"
            result.append(f"   {prefix} (PayDay: {payday}) - {info}{time_str}")

    if businesses:
        result.append("└─ ✨ Бизнесы:")
        for r in sorted(businesses, key=lambda x: x[4]):
            _, _, _, _, slot, house_id, payday, status, fall_time, _, _, is_estate = r
            info = status_name(status)
            time_str = ""
            if fall_time:
                try:
                    dt = datetime.fromisoformat(fall_time)
                    time_str = f" | ⏰ {dt.strftime('%H:%M')}"
                except:
                    pass
            prefix = f"id {house_id}" if house_id else f"pos {slot}"
            result.append(f"   {prefix} (PayDay: {payday}) - {info}{time_str}")

    header = f"🌐 <b>Сервер {server_name.upper()}[{server_id}]</b>"
    quote_body = "\n".join(result)
    return f"{header}\n<blockquote>{quote_body}</blockquote>"


@dp.message(Command("start"))
async def start(message: types.Message):
    if not has_access(message.from_user.id):
        await message.answer("🔒 У вас нет доступа к боту.")
        return
    await message.answer(
        "👋 <b>Arizona Tracker</b>",
        reply_markup=keyboard(message.from_user.id),
        parse_mode="HTML",
    )


@dp.message(F.text.in_({"⚠️ Ближайшие слёты", "Ближайшие слёты"}))
async def nearest(message: types.Message):
    if not has_access(message.from_user.id):
        return
    now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
    limit = now + timedelta(hours=3)
    rows = fetch_rows(
        "is_frozen = 0 AND exact_fall_time BETWEEN ? AND ?",
        (now.isoformat(), limit.isoformat()),
    )
    await message.answer(format_falls(rows, "⚠️ <b>Слёты в ближайшие 3 часа</b>"), parse_mode="HTML")


@dp.message(F.text.in_({"📋 Все слёты", "Все слёты"}))
async def all_falls(message: types.Message):
    if not has_access(message.from_user.id):
        return
    now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
    rows = fetch_rows(
        "is_frozen = 0 AND exact_fall_time BETWEEN ? AND ?",
        (now.isoformat(), (now + timedelta(hours=24)).isoformat()),
    )
    await message.answer(format_falls(rows, "📋 <b>Все слёты за 24 часа</b>"), parse_mode="HTML")


@dp.message(F.text.in_({"🌐 По серверу", "По серверу"}))
async def servers_menu(message: types.Message):
    if not has_access(message.from_user.id):
        return
    buttons = []
    for s_id, s_name in SERVERS_LIST:
        buttons.append(InlineKeyboardButton(text=f"{s_name} [{s_id}]", callback_data=f"srv:{s_id}"))
    keyboard_inline = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    await message.answer("🌐 Выберите сервер из списка:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_inline))


@dp.callback_query(F.data.startswith("srv:"))
async def server_result(callback: types.CallbackQuery):
    if not has_access(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    server_id = callback.data.split(":", 1)[1]
    server_name = server_id
    for s_id, s_name in SERVERS_LIST:
        if s_id == server_id:
            server_name = s_name
            break

    rows = fetch_rows("server_id = ? AND is_frozen = 0", (server_id,))
    text_result = format_server_compact(rows, server_id, server_name)
    await callback.message.answer(text_result, parse_mode="HTML")
    await callback.answer()


@dp.message(F.text.in_({"🏆 Сезоны", "Сезоны"}))
async def seasons_overview(message: types.Message):
    if not has_access(message.from_user.id):
        return
    conn = db()
    lines = ["🏆 <b>Текущие сезоны по серверам:</b>", ""]
    for s_id, s_name in SERVERS_LIST:
        m_row = conn.execute("SELECT season FROM manual_seasons WHERE server_id = ?", (str(s_id),)).fetchone()
        season = "Неизвестно"
        if m_row and m_row[0]:
            season = m_row[0]
        else:
            r = conn.execute("SELECT season FROM server_objects WHERE server_id = ? ORDER BY last_updated DESC LIMIT 1", (str(s_id),)).fetchone()
            if r and r[0]:
                season = r[0]

        icon = get_season_icon(season)
        has_data = conn.execute("SELECT 1 FROM server_objects WHERE server_id = ? LIMIT 1", (str(s_id),)).fetchone()
        status_box = "🟩" if has_data else "🟥"
        lines.append(f"<code>[{s_id}] {s_name:<11}</code> {icon} {season:<14} {status_box}")
    conn.close()
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text.in_({"⚙️ Консоль разработчика", "Консоль разработчика"}))
async def dev_console(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    buttons = []
    for s_id, s_name in SERVERS_LIST:
        buttons.append(InlineKeyboardButton(text=f"[{s_id}] {s_name}", callback_data=devsrv:{s_id}))
    keyboard_inline = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    await message.answer("⚙️ <b>Консоль разработчика</b>\nВыберите сервер для установки сезона:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_inline), parse_mode="HTML")


@dp.callback_query(F.data.startswith("devsrv:"))
async def dev_select_server(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    server_id = callback.data.split(":", 1)[1]
    server_name = server_id
    for s_id, s_name in SERVERS_LIST:
        if s_id == server_id:
            server_name = s_name
            break

    buttons = [
        [InlineKeyboardButton(text=season, callback_data=f"devset:{server_id}:{season}")]
        for season in SEASONS_LIST
    ]
    await callback.message.answer(f"⚙️ Выберите сезон для <b>{server_name} [{server_id}]</b>:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("devset:"))
async def dev_set_season(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    _, server_id, season = callback.data.split(":", 2)
    conn = db()
    conn.execute("INSERT OR REPLACE INTO manual_seasons (server_id, season) VALUES (?, ?)", (server_id, season))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Для сервера [{server_id}] установлен сезон: <b>{season}</b>", parse_mode="HTML")
    await callback.answer()


@dp.message(F.text.in_({"📍 Статус", "Статус"}))
async def status(message: types.Message):
    if not has_access(message.from_user.id):
        return
    conn = db()
    rows = conn.execute("SELECT server_name, MAX(last_updated) FROM server_objects GROUP BY server_id").fetchall()
    conn.close()
    rows.sort(key=lambda row: row[1] or "", reverse=True)
    if not rows:
        await message.answer("📍 Данных о сканировании пока нет.")
        return
    lines = ["📍 <b>Последние сейвы по серверам:</b>", ""]
    for name, value in rows:
        lines.append(f"<code>{name:<14} | {value}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text.in_({"😴 Стоит проснуться", "Стоит проснуться"}))
async def wakeup(message: types.Message):
    if not has_access(message.from_user.id):
        return
    rows = fetch_rows("is_frozen = 0")
    known = [r for r in rows if r[7] and r[7] != "Неизвестно"]
    grouped = {}
    for row in known:
        grouped.setdefault((row[8], row[1]), []).append(row)
    selected = []
    for values in grouped.values():
        if any(row[3] == "Бизнес" for row in values) or sum(row[3] == "Дом" for row in values) > 5:
            selected.extend(values)
    await message.answer(format_falls(selected, "😴 <b>Стоит проснуться</b>"), parse_mode="HTML")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
