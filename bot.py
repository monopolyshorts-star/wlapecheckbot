import asyncio
import logging
import os
import secrets
import sqlite3
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
    return {
        "Страх": "Застраховано",
        "Нестрах": "Не застраховано",
        "Страх, Занят": "Застраховано, есть занятость",
        "Страх, Незанят": "Застраховано, нет занятости",
        "Нестрах, Без занятости": "Не застраховано, без занятости",
        "Неизвестно": "Неизвестно",
    }.get(value or "Неизвестно", "Неизвестно")


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


def format_falls(rows, title):
    if not rows:
        return f"{title}\n\n⚠️ Слётов не обнаружено."

    conn = db()
    manual_dict = dict(conn.execute("SELECT server_id, season FROM manual_seasons").fetchall())
    conn.close()

    grouped = {}
    for row in rows:
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

        # Приоритет сезона: ручной из админки -> из таблицы объектов
        active_season = manual_dict.get(str(server_id)) or season or "Неизвестно"
        key = (dt.strftime("%H:00"), server_id, server_name, active_season)
        grouped.setdefault(key, {"Дом": [], "Бизнес": []})[obj_type].append(row)

    if not grouped:
        return f"{title}\n\n⚠️ Слётов с рассчитанным временем не обнаружено."

    result = [title, ""]
    current_hour = None

    for (hour, server_id, server_name, season), groups in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][2])):
        if hour != current_hour:
            result.append(f"🕰️ <b>Слёты в {hour}:</b> 🕰️")
            current_hour = hour

        icon_emoji = get_season_icon(season)
        result.append(f"   └─🌐 <b>Сервер {server_name.upper()} {icon_emoji}</b>")

        for obj_type in ("Дом", "Бизнес"):
            objects = groups[obj_type]
            if not objects:
                continue

            icon = "🏠" if obj_type == "Дом" else "✨"
            title_type = "Дома" if obj_type == "Дом" else "Бизнесы"
            result.append(f"      └─{icon} <b>{title_type}:</b>")

            for row in sorted(objects, key=lambda r: r[4]):
                _, _, _, _, slot, house_id, payday, status, _, _, _, is_estate = row
                info = status_name(status)
                if is_estate:
                    info += " (🔒 С поместьем)"

                # Если есть house_id (для Скорострелов), всегда его выводим
                id_part = f" [ID: {house_id}]" if house_id else ""
                result.append(f"         └─pos {slot}{id_part} (PayDay: {payday}) - {info}")

        result.append("")

    return "\n".join(result).strip()


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
        return f"🌐 <b>Сервер {server_name.upper()}[{server_id}]</b>\n   └─ Сезон 🌐 \"<b>{season.upper()}</b>\" {season_icon}\n\n⚠️ Активных слётов не обнаружено."

    result = [
        f"🌐 <b>Сервер {server_name.upper()}[{server_id}]</b>",
        f"   └─ Сезон 🌐 \"<b>{season.upper()}</b>\" {season_icon}",
    ]

    houses = [r for r in rows if r[3] == "Дом"]
    businesses = [r for r in rows if r[3] == "Бизнес"]

    if houses:
        result.append("   └─ 🏠 <b>Дома:</b>")
        for r in sorted(houses, key=lambda x: x[4]):
            _, _, _, _, slot, house_id, payday, status, fall_time, _, _, is_estate = r
            info = status_name(status)
            if is_estate:
                info += ", с поместьем"
            time_str = ""
            if fall_time:
                try:
                    dt = datetime.fromisoformat(fall_time)
                    time_str = f" | ⏰ {dt.strftime('%H:%M')}"
                except:
                    pass
            id_part = f" [ID: {house_id}]" if house_id else ""
            result.append(f"      pos {slot}{id_part} (PayDay: {payday}) - {info}{time_str}")

    if businesses:
        result.append("   └─ ✨ <b>Бизнесы:</b>")
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
            id_part = f" [ID: {house_id}]" if house_id else ""
            result.append(f"      pos {slot}{id_part} (PayDay: {payday}) - {info}{time_str}")

    return "\n".join(result)


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
    await message.answer(format_falls(rows, "⚠️ <b>Ближайшие слёты (3 ПД)</b>"), parse_mode="HTML")


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
        buttons.append(InlineKeyboardButton(text=f"[{s_id}] {s_name}", callback_data=f"devsrv:{s_id}"))
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
    await callback.message.answer(f"✅ Для сервера [{server_id}] установлен сезон: <b>{season}</b>", parse_mode="HTML")
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
    grouped = {}
    for row in rows:
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
