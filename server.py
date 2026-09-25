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


class RealtorItem(BaseModel):
    slot: int
    house_id: Optional[int] = None
    payday: int
    type: str
    state: Optional[str] = None


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


def calculate_fall_time(server_id: str, obj_type: str, payday: int, insurance: str, now: datetime):
    rules = SERVER_RULES.get(str(server_id).zfill(2), SERVER_RULES["01"])
    if obj_type == "Бизнес":
        if insurance == "Не страх, Без занят":
            rate, target = 4, rules["b_un"]
        elif insurance == "Страх, Без занят":
            rate, target = 2, rules["b_un"]
        elif insurance == "Страх, Занят":
            rate, target = 1, rules["b_ins"]
        else:
            rate, target = 2, rules["b_un"]
    else:
        if insurance == "Не страх":
            rate, target = 2, rules["h_un"]
        else:
            rate, target = 1, rules["h_ins"]

    hours_left = 1 if payday <= target else math.ceil((payday - target) / rate) + 1
    next_payday = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_payday + timedelta(hours=hours_left - 1)).isoformat()


def classify_status(obj_type: str, old_pd: Optional[int], new_pd: int, hours: int) -> str:
    if old_pd is None or hours < 1:
        return "Неизвестно"
    speed = (old_pd - new_pd) / hours
    if speed <= 0:
        return "Неизвестно"
    if obj_type == "Дом":
        return "Не страх" if speed >= 1.5 else "Страх"
    if speed >= 3.0:
        return "Не страх, Без занят"
    if speed >= 1.5:
        return "Страх, Без занят"
    return "Страх, Занят"


def normalize_items(raw):
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [x for x in raw.values() if isinstance(x, dict)]
    return []


@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    conn = None
    try:
        items = normalize_items(payload.items)
        server_id = str(payload.server_id)
        if payload.scan_ts:
            now = (datetime.fromtimestamp(payload.scan_ts, tz=timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        else:
            now = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)
        now_str = now.strftime("%d.%m.%Y %H:%M:%S")
        print(f"[API] {payload.server_name} [{server_id}], scan_type={payload.scan_type}, items={len(items)}", flush=True)

        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        manual = cur.execute("SELECT season FROM manual_seasons WHERE server_id=?", (server_id,)).fetchone()
        season = manual[0] if manual and manual[0] else payload.season

        # Пустой раздел очищает только явно указанный тип, не весь сервер.
        if not items:
            target_type = payload.scan_type if payload.scan_type in ("Дом", "Бизнес") else None
            if target_type is None:
                conn.close()
                return JSONResponse(status_code=400, content={"status": "error", "message": "Для пустого списка требуется scan_type Дом/Бизнес"})
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
            # Для текущего объекта ищем последний снимок не моложе 50 минут.
            # Так несколько чеков в одном PayDay не создают ложную заморозку.
            for item in type_items:
                slot = int(item["slot"])
                new_pd = int(item["payday"])
                hid = item.get("house_id")

                prior_rows = cur.execute("""
                    SELECT payday, recorded_at
                    FROM scan_history
                    WHERE server_id=? AND slot=? AND obj_type=?
                    ORDER BY id DESC LIMIT 30
                """, (server_id, slot, obj_type)).fetchall()

                prior_pd = None
                prior_dt = None
                for hist_pd, hist_time in prior_rows:
                    hist_dt = parse_scan_time(hist_time)
                    if hist_dt and (now - hist_dt).total_seconds() >= 50 * 60:
                        prior_pd, prior_dt = hist_pd, hist_dt
                        break

                hours = 0
                if prior_dt:
                    hours = int(round((now.replace(minute=0, second=0, microsecond=0) - prior_dt.replace(minute=0, second=0, microsecond=0)).total_seconds() / 3600))
                    if hours < 1 or hours > 24:
                        hours = 0

                # Если история по позиции не нашлась, пытаемся сопоставить по house_id.
                if prior_pd is None and hid is not None:
                    hid_rows = cur.execute("""
                        SELECT sh.payday, sh.recorded_at
                        FROM scan_history sh
                        JOIN server_objects so ON so.server_id=sh.server_id AND so.slot=sh.slot AND so.obj_type=sh.obj_type
                        WHERE sh.server_id=? AND sh.obj_type=? AND so.house_id=?
                        ORDER BY sh.id DESC LIMIT 30
                    """, (server_id, obj_type, hid)).fetchall()
                    for hist_pd, hist_time in hid_rows:
                        hist_dt = parse_scan_time(hist_time)
                        if hist_dt and (now - hist_dt).total_seconds() >= 50 * 60:
                            prior_pd, prior_dt = hist_pd, hist_dt
                            hours = int(round((now.replace(minute=0, second=0, microsecond=0) - hist_dt.replace(minute=0, second=0, microsecond=0)).total_seconds() / 3600))
                            if hours < 1 or hours > 24:
                                hours = 0
                            break

                # Предыдущее состояние из основной таблицы нужно для повторного скана в тот же час.
                current_db = cur.execute("""
                    SELECT payday, insurance_status, is_frozen, last_updated
                    FROM server_objects WHERE server_id=? AND slot=? AND obj_type=?
                """, (server_id, slot, obj_type)).fetchone()

                status = classify_status(obj_type, prior_pd, new_pd, hours)
                if status == "Неизвестно" and current_db and current_db[1] and current_db[1] != "Неизвестно":
                    status = current_db[1]

                frozen = 0
                if prior_pd is not None and hours >= 1:
                    frozen = int(new_pd == prior_pd)
                elif current_db:
                    # Повторный просмотр в том же PayDay сохраняет флаг; не создает новый.
                    frozen = int(current_db[2] or 0) if new_pd == current_db[0] else 0

                fall_time = calculate_fall_time(server_id, obj_type, new_pd, status, now)
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
                """, (server_id,payload.server_name,season,obj_type,slot,hid,new_pd,status,fall_time,now_str,frozen))
                cur.execute("INSERT INTO scan_history (server_id,slot,obj_type,payday,recorded_at) VALUES (?,?,?,?,?)",
                            (server_id,slot,obj_type,new_pd,now_str))

            # Очистка исчезнувших позиций только при полном скане; быстрые страницы склеиваем.
            cur.execute("SELECT MAX(last_updated) FROM server_objects WHERE server_id=? AND obj_type=?", (server_id,obj_type))
            last_updated = cur.fetchone()[0]
            is_paged = False
            if last_updated:
                dt = parse_scan_time(last_updated)
                is_paged = bool(dt and (now - dt).total_seconds() < 60)
            if not is_paged:
                slots = sorted({int(x["slot"]) for x in type_items})
                marks = ",".join("?" for _ in slots)
                cur.execute(f"DELETE FROM server_objects WHERE server_id=? AND obj_type=? AND slot NOT IN ({marks})", [server_id,obj_type,*slots])

        conn.commit()
        conn.close()
        return {"status": "success", "count": len(items)}
    except Exception as exc:
        if conn:
            conn.rollback()
            conn.close()
        print(f"[API ERROR] {exc}", flush=True)
        return JSONResponse(status_code=500, content={"status":"error","message":str(exc)})
