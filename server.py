import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database import DB_NAME, init_db

app = FastAPI(title="Arizona Tracker API")
init_db()

SERVER_RULES = {
    "01": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "02": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "03": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "04": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "05": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "06": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "07": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "08": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "09": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "10": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "11": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "12": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "13": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "14": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "15": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2},
    "16": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "17": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2},
    "18": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "19": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "20": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2},
    "21": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "22": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "23": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 2},
    "24": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "25": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "26": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 3},
    "27": {"h_ins": 1, "h_un": 2, "b_ins": 1, "b_un": 2},
    "28": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "29": {"h_ins": 2, "h_un": 3, "b_ins": 2, "b_un": 3},
    "30": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 3},
    "31": {"h_ins": 2, "h_un": 3, "b_ins": 1, "b_un": 2},
    "32": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 2},
    "33": {"h_ins": 1, "h_un": 2, "b_ins": 2, "b_un": 2},
}


def ensure_schema():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS manual_seasons (
        server_id TEXT PRIMARY KEY, season TEXT NOT NULL
    )""")
    columns = {r[1] for r in cur.execute("PRAGMA table_info(server_objects)")}
    if "house_id" not in columns:
        cur.execute("ALTER TABLE server_objects ADD COLUMN house_id INTEGER")
    if "is_frozen" not in columns:
        cur.execute("ALTER TABLE server_objects ADD COLUMN is_frozen INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


ensure_schema()


@app.get("/")
def read_root():
    return {"status": "online", "service": "Arizona Tracker API is running"}


class RealtorPayload(BaseModel):
    server_id: Any
    server_name: str
    season: Optional[str] = "Неизвестно"
    scan_ts: Optional[float] = None
    scan_type: Optional[str] = None
    items: Any = []


def parse_scan_time(value):
    try:
        return datetime.strptime(value, "%d.%m.%Y %H:%M:%S")
    except (TypeError, ValueError):
        return None


def calculate_fall_time(server_id: str, obj_type: str, payday: int, insurance: str, now: datetime, is_frozen: int):
    if is_frozen == 1:
        return None

    sid = str(server_id).zfill(2)
    rules = SERVER_RULES.get(sid, SERVER_RULES["01"])
    next_payday = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    if payday <= 1:
        return next_payday.isoformat()

    if insurance == "Неизвестно":
        if obj_type == "Дом":
            min_target = min(rules["h_ins"], rules["h_un"])
            if payday <= min_target:
                return next_payday.isoformat()
        else:
            min_target = min(rules["b_ins"], rules["b_un"])
            if payday <= min_target:
                return next_payday.isoformat()
        return None

    if obj_type == "Бизнес":
        if insurance == "Не страх, Без занят":
            rate, target = 4, rules["b_un"]
        elif insurance == "Страх, Без занят":
            rate, target = 2, rules["b_un"]
        elif insurance == "Страх, Занят":
            rate, target = 1, rules["b_ins"]
        else:
            return None
    else:
        if insurance == "Не страх":
            rate, target = 2, rules["h_un"]
        elif insurance == "Страх":
            rate, target = 1, rules["h_ins"]
        else:
            return None

    hours_left = 1 if payday <= target else math.ceil((payday - target) / rate) + 1
    return (next_payday + timedelta(hours=hours_left - 1)).isoformat()


@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    conn = None
    try:
        raw_items = payload.items
        items = []
        if isinstance(raw_items, list):
            items = [x for x in raw_items if isinstance(x, dict)]
        elif isinstance(raw_items, dict):
            items = [x for x in raw_items.values() if isinstance(x, dict)]

        server_id = str(payload.server_id)
        if payload.scan_ts:
            now = (datetime.fromtimestamp(payload.scan_ts, tz=timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        else:
            now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        now_str = now.strftime("%d.%m.%Y %H:%M:%S")

        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        manual = cur.execute("SELECT season FROM manual_seasons WHERE server_id=?", (server_id,)).fetchone()
        season = manual[0] if manual and manual[0] else payload.season

        if not items:
            target_type = payload.scan_type if payload.scan_type in ("Дом", "Бизнес") else None
            if target_type is None:
                conn.close()
                return JSONResponse(status_code=400, content={"status": "error", "message": "Требуется scan_type"})
            cur.execute("DELETE FROM server_objects WHERE server_id=? AND obj_type=?", (server_id, target_type))
            cur.execute("INSERT INTO scan_history (server_id,slot,obj_type,payday,recorded_at) VALUES (?,0,?,0,?)",
                        (server_id, f"Пусто_{target_type}", now_str))
            conn.commit()
            conn.close()
            return {"status": "success", "count": 0}

        grouped = {}
        for item in items:
            typ = item.get("type")
            if typ in ("Дом", "Бизнес") and item.get("slot") is not None and item.get("payday") is not None:
                grouped.setdefault(typ, []).append(item)

        for obj_type, type_items in grouped.items():
            for item in type_items:
                slot = int(item["slot"])
                new_pd = int(item["payday"])
                hid = item.get("house_id")

                # Ищем предыдущую запись строго в диапазоне 50 - 90 минут назад
                prior_pd = None
                prior_dt = None

                # Сначала пробуем по house_id
                if hid is not None:
                    hid_rows = cur.execute("""
                        SELECT sh.payday, sh.recorded_at
                        FROM scan_history sh
                        JOIN server_objects so ON so.server_id=sh.server_id AND so.slot=sh.slot AND so.obj_type=sh.obj_type
                        WHERE sh.server_id=? AND sh.obj_type=? AND so.house_id=?
                        ORDER BY sh.id DESC LIMIT 10
                    """, (server_id, obj_type, hid)).fetchall()
                    for hist_pd, hist_time in hid_rows:
                        hist_dt = parse_scan_time(hist_time)
                        if hist_dt:
                            diff = (now - hist_dt).total_seconds()
                            if 50 * 60 <= diff <= 90 * 60:
                                prior_pd = hist_pd
                                prior_dt = hist_dt
                                break

                # Если не нашли по id, ищем по слоту в предыдущем часе
                if prior_pd is None:
                    slot_rows = cur.execute("""
                        SELECT payday, recorded_at
                        FROM scan_history
                        WHERE server_id=? AND slot=? AND obj_type=?
                        ORDER BY id DESC LIMIT 10
                    """, (server_id, slot, obj_type)).fetchall()
                    for hist_pd, hist_time in slot_rows:
                        hist_dt = parse_scan_time(hist_time)
                        if hist_dt:
                            diff = (now - hist_dt).total_seconds()
                            if 50 * 60 <= diff <= 90 * 60:
                                prior_pd = hist_pd
                                prior_dt = hist_dt
                                break

                # Достаем текущую запись из базы для проверки заморозки
                current_db = cur.execute("""
                    SELECT payday, insurance_status, is_frozen, last_updated, house_id
                    FROM server_objects WHERE server_id=? AND slot=? AND obj_type=?
                """, (server_id, slot, obj_type)).fetchone()

                # Проверяем заморозку (PayDay не изменился за прошлый час)
                frozen = 0
                if prior_pd is not None and new_pd == prior_pd:
                    frozen = 1
                elif current_db:
                    db_dt = parse_scan_time(current_db[3])
                    if db_dt and (now - db_dt).total_seconds() < 50 * 60 and new_pd == current_db[0]:
                        frozen = int(current_db[2] or 0)

                # Вычисляем статус
                status = "Неизвестно"
                if frozen == 1:
                    # Если объект заморожен, статус берем старый (если был) или Неизвестно
                    status = current_db[1] if current_db and current_db[1] and current_db[1] != "Неизвестно" else "Неизвестно"
                elif prior_pd is not None:
                    drop = prior_pd - new_pd
                    if drop == 1:
                        status = "Страх" if obj_type == "Дом" else "Страх, Занят"
                    elif drop == 2:
                        status = "Не страх" if obj_type == "Дом" else "Страх, Без занят"
                    elif drop >= 4 and obj_type == "Бизнес":
                        status = "Не страх, Без занят"
                    elif drop <= 0:
                        frozen = 1 # Стоит на месте = заморожен
                        status = current_db[1] if current_db else "Неизвестно"

                # Если это самый первый скан и истории нет — статус строго Неизвестно
                if prior_pd is None and current_db is None:
                    status = "Неизвестно"
                elif status == "Неизвестно" and current_db and current_db[1] and current_db[1] != "Неизвестно":
                    # Сохраняем ранее подтвержденный статус, если объект тот же
                    if hid is not None and current_db[4] == hid:
                        status = current_db[1]

                # При бизнес 1 PD с гарантией
                if obj_type == "Бизнес" and new_pd == 1 and status == "Неизвестно":
                    status = "Страх, Занят"

                fall_time = calculate_fall_time(server_id, obj_type, new_pd, status, now, frozen)

                cur.execute("""
                    INSERT INTO server_objects
                    (server_id,server_name,season,obj_type,slot,house_id,payday,insurance_status,
                     exact_fall_time,last_updated,is_frozen,is_h2,is_estate)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,0,0)
                    ON CONFLICT(server_id,slot,obj_type) DO UPDATE SET
                        server_name=excluded.server_name,
                        season=excluded.season,
                        house_id=excluded.house_id,
                        payday=excluded.payday,
                        insurance_status=excluded.insurance_status,
                        exact_fall_time=excluded.exact_fall_time,
                        last_updated=excluded.last_updated,
                        is_frozen=excluded.is_frozen
                """, (server_id, payload.server_name, season, obj_type, slot, hid, new_pd, status, fall_time, now_str, frozen))
                cur.execute("INSERT INTO scan_history (server_id,slot,obj_type,payday,recorded_at) VALUES (?,?,?,?,?)",
                            (server_id, slot, obj_type, new_pd, now_str))

            # Удаление исчезнувших при полном скане
            cur.execute("SELECT MAX(last_updated) FROM server_objects WHERE server_id=? AND obj_type=?", (server_id, obj_type))
            last_updated = cur.fetchone()[0]
            is_paged = False
            if last_updated:
                dt = parse_scan_time(last_updated)
                is_paged = bool(dt and (now - dt).total_seconds() < 60)
            if not is_paged:
                slots = sorted({int(x["slot"]) for x in type_items})
                marks = ",".join("?" for _ in slots)
                cur.execute(f"DELETE FROM server_objects WHERE server_id=? AND obj_type=? AND slot NOT IN ({marks})", [server_id, obj_type, *slots])

        conn.commit()
        conn.close()
        return {"status": "success", "count": len(items)}
    except Exception as exc:
        if conn:
            conn.rollback()
            conn.close()
        print(f"[API ERROR] {exc}", flush=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(exc)})
