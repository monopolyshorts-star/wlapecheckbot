import asyncio
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from database import DB_NAME, init_db

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {1321937398}

init_db()
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# Точное соответствие названий сезонов из игры со значками из ТЗ
SEASON_ICONS = {
    "Мотогонки": "🏍",
    "Ловля по инфе": "📱",
    "По инфе": "📱",
    "По новому": "✈️",
    "Автогонки": "🚗",
    "Скорострелы": "⌨️",
}

SEASONS = [
    "Скорострелы",
    "Ловля по инфе",
    "Автогонки",
    "По новому",
    "Мотогонки",
]

SELECT_COLUMNS = (
    "server_name, server_id, season, obj_type, slot, payday, "
    "insurance_status, exact_fall_time, is_frozen, is_h2, is_estate"
)


def db():
    return sqlite3.connect(DB_NAME)


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
    except ValueError:
        return False


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⚠️ Ближайшие слёты"),
                KeyboardButton(text="📋 Все слёты"),
            ],
            [
                KeyboardButton(text="🌐 По серверу"),
                KeyboardButton(text="🏆 Поиск по сезону"),
            ],
            [
                KeyboardButton(text="📍 Статус"),
                KeyboardButton(text="😴 Стоит проснуться"),
            ],
        ],
        resize_keyboard=True,
    )


def status_name(value):
    return {
        "Страх": "Застраховано",
        "Нестрах": "Не застраховано",
        "Страх, Занят": "Застраховано, есть занятость",
        "Страх, Незанят": "Застраховано, нет занятости",
        "Нестрах, Незанят": "Не застраховано, нет занятости",
    }.get(value or "", "Застраховано")


def get_season_icon(season_name):
    if not season_name:
        return "🌐"
    # Ищем соответствие без учета регистра и возможных пробелов
    s_clean = season_name.strip()
    for key, icon in SEASON_ICONS.items():
        if key.lower() in s_clean.lower():
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

    grouped = {}
    for row in rows:
        (
            server_name,
            server_id,
            season,
            obj_type,
            slot,
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
        except ValueError:
            continue

        key = (dt, server_id, server_name, season)
        grouped.setdefault(key, {"Дом": [], "Бизнес": []})[obj_type].append(row)

    if not grouped:
        return f"{title}\n\n⚠️ Слётов с рассчитанным временем не обнаружено."

    result = [title, ""]
    shown_hour = None

    for (dt, server_id, server_name, season), groups in sorted(grouped.items()):
        hour = dt.strftime("%H:00")
        if hour != shown_hour:
            result.append(f"🕰️ <b>Слёты в {hour}:</b> 🕰️")
            shown_hour = hour

        icon_emoji = get_season_icon(season)
        result.append(
            f"   └─🌐 <b>Сервер {server_name.upper()} {icon_emoji}</b>"
        )

        for obj_type, objects in groups.items():
            if not objects:
                continue

            icon = "🏠" if obj_type == "Дом" else "✨"
            title_type = "Дома" if obj_type == "Дом" else "Бизнесы"
            result.append(f"      └─{icon} <b>{title_type}:</b>")

            for row in objects:
                (
                    _,
                    _,
                    _,
                    _,
                    slot,
                    payday,
                    status,
                    _,
                    _,
                    is_h2,
                    is_estate,
                ) = row

                info = status_name(status)
                if is_estate:
                    info += " (🔒 С поместьем)"
                if is_h2:
                    info += " (🔒 Х2 ДОМ!!!)"

                result.append(
                    f"         └─pos {slot} "
                    f"(PayDay: {payday}) - {info}"
                )

        result.append("")

    return "\n".join(result)


@dp.message(Command("start"))
async def start(message: types.Message):
    if not has_access(message.from_user.id):
        await message.answer("🔒 У вас нет доступа к боту.")
        return

    await message.answer(
        "👋 <b>Arizona Tracker</b>",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


@dp.message(Command("genkey"))
async def genkey(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit() or int(args[1]) <= 0:
        await message.answer("Использование: /genkey КОЛИЧЕСТВО_ДНЕЙ")
        return

    days = int(args[1])
    key = secrets.token_hex(4).upper()
    expires = datetime.now() + timedelta(days=days)

    conn = db()
    conn.execute(
        "INSERT INTO access_keys "
        "(key, expires_at, created_at, created_by) VALUES (?, ?, ?, ?)",
        (key, expires.isoformat(), datetime.now().isoformat(), message.from_user.id),
    )
    conn.commit()
    conn.close()

    await message.answer(
        f"🔑 Ключ на <b>{days} дн.</b>:\n"
        f"<code>{key}</code>\n\n"
        f"Активация: <code>/key {key}</code>",
        parse_mode="HTML",
    )


@dp.message(Command("key"))
async def activate_key(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /key КЛЮЧ")
        return

    key = args[1].strip().upper()
    conn = db()
    row = conn.execute(
        "SELECT expires_at, used FROM access_keys WHERE key = ?",
        (key,),
    ).fetchone()

    if not row:
        conn.close()
        await message.answer("❌ Ключ не найден.")
        return

    expires_at, used = row
    if used:
        conn.close()
        await message.answer("❌ Этот ключ уже использован.")
        return

    if datetime.fromisoformat(expires_at) <= datetime.now():
        conn.close()
        await message.answer("❌ Срок действия ключа истёк.")
        return

    conn.execute(
        "UPDATE access_keys SET used = 1, used_by = ? WHERE key = ?",
        (message.from_user.id, key),
    )
    conn.execute(
        "INSERT OR REPLACE INTO allowed_users "
        "(user_id, username, expires_at, added_at) VALUES (?, ?, ?, ?)",
        (
            message.from_user.id,
            message.from_user.username or "",
            expires_at,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    await message.answer(
        "✅ Подписка активирована.",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("grant"))
async def grant(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /grant USER_ID ДНИ")
        return

    try:
        user_id = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("USER_ID и ДНИ должны быть числами.")
        return

    expires = datetime.now() + timedelta(days=days)
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO allowed_users "
        "(user_id, username, expires_at, added_at) VALUES (?, ?, ?, ?)",
        (user_id, "", expires.isoformat(), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    await message.answer(f"✅ Доступ выдан до {expires:%d.%m.%Y %H:%M}.")


@dp.message(Command("revoke"))
async def revoke(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        await message.answer("Использование: /revoke USER_ID")
        return

    conn = db()
    conn.execute("DELETE FROM allowed_users WHERE user_id = ?", (int(args[1]),))
    conn.commit()
    conn.close()

    await message.answer("✅ Подписка отозвана.")


@dp.message(F.text == "⚠️ Ближайшие слёты")
async def nearest(message: types.Message):
    if not has_access(message.from_user.id):
        return

    now = datetime.now()
    rows = fetch_rows(
        "is_frozen = 0 AND exact_fall_time BETWEEN ? AND ?",
        (now.isoformat(), (now + timedelta(hours=3)).isoformat()),
    )
    await message.answer(
        format_falls(rows, "⚠️ <b>Ближайшие слёты (3 ПД)</b>"),
        parse_mode="HTML",
    )


@dp.message(F.text == "📋 Все слёты")
async def all_falls(message: types.Message):
    if not has_access(message.from_user.id):
        return

    now = datetime.now()
    rows = fetch_rows(
        "is_frozen = 0 AND exact_fall_time BETWEEN ? AND ?",
        (now.isoformat(), (now + timedelta(hours=24)).isoformat()),
    )
    await message.answer(
        format_falls(rows, "📋 <b>Все слёты за 24 часа</b>"),
        parse_mode="HTML",
    )


@dp.message(F.text == "🌐 По серверу")
async def servers_menu(message: types.Message):
    if not has_access(message.from_user.id):
        return

    conn = db()
    servers = conn.execute(
        "SELECT DISTINCT server_id, server_name "
        "FROM server_objects ORDER BY server_name"
    ).fetchall()
    conn.close()

    if not servers:
        await message.answer("⚠️ В базе пока нет данных по серверам.")
        return

    buttons = [
        [
            InlineKeyboardButton(
                text=f"{name} [{server_id}]",
                callback_data=f"srv:{server_id}",
            )
        ]
        for server_id, name in servers
    ]
    await message.answer(
        "🌐 Выберите сервер:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("srv:"))
async def server_result(callback: types.CallbackQuery):
    if not has_access(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    server_id = callback.data.split(":", 1)[1]
    rows = fetch_rows(
        "server_id = ? AND is_frozen = 0",
        (server_id,),
    )

    if not rows:
        await callback.message.answer("⚠️ На этом сервере нет активных слётов.")
    else:
        await callback.message.answer(
            format_falls(rows, f"🌐 <b>Слёты сервера {rows[0][0].upper()}</b>"),
            parse_mode="HTML",
        )

    await callback.answer()


@dp.message(F.text == "📍 Статус")
async def status(message: types.Message):
    if not has_access(message.from_user.id):
        return

    conn = db()
    # Сортировка по убыванию: свежие сканы (по реальной дате/времени) сверху, старые — снизу
    rows = conn.execute(
        "SELECT server_name, MAX(last_updated) "
        "FROM server_objects GROUP BY server_id "
        "ORDER BY MAX(datetime(substr(last_updated,7,4)||'-'||substr(last_updated,4,2)||'-'||substr(last_updated,1,2)||' '||substr(last_updated,12))) DESC"
    ).fetchall()
    conn.close()

    if not rows:
        await message.answer("📍 Данных о сканировании пока нет.")
        return

    lines = ["📍 <b>Последние сейвы по серверам:</b>", ""]
    for name, value in rows:
        lines.append(f"<code>{name:<14} | {value}</code>")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text == "😴 Стоит проснуться")
async def wakeup(message: types.Message):
    if not has_access(message.from_user.id):
        return

    rows = fetch_rows("is_frozen = 0")
    grouped = {}
    for row in rows:
        grouped.setdefault((row[7], row[1]), []).append(row)

    selected = []
    for values in grouped.values():
        business_exists = any(row[3] == "Бизнес" for row in values)
        houses_count = sum(row[3] == "Дом" for row in values)
        if business_exists or houses_count > 5:
            selected.extend(values)

    await message.answer(
        format_falls(selected, "😴 <b>Стоит проснуться</b>"),
        parse_mode="HTML",
    )


@dp.message(F.text == "🏆 Поиск по сезону")
async def season_menu(message: types.Message):
    if not has_access(message.from_user.id):
        return

    buttons = [
        [InlineKeyboardButton(text=season, callback_data=f"season:{season}")]
        for season in SEASONS
    ]
    await message.answer(
        "🏆 Выберите сезон:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("season:"))
async def season_result(callback: types.CallbackQuery):
    if not has_access(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    season = callback.data.split(":", 1)[1]
    rows = fetch_rows(
        "season = ? AND is_frozen = 0",
        (season,),
    )
    await message.answer(
        format_falls(rows, f"🏆 <b>Сезон: {season}</b>"),
        parse_mode="HTML",
    )
    await callback.answer()


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
