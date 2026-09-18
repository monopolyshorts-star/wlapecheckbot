import sqlite3
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel
from database import DB_NAME, init_db

app = FastAPI(title="Arizona Tracker API")
init_db()

# Правила падения по ТЗ (для каждого сервера и типа объектов)
# Для каждого сервера задаются два набора правил:
# house: insured_target, uninsured_min, uninsured_max
# biz:   insured_target, uninsured_min, uninsured_max
SERVER_RULES: Dict[str, Dict[str, Dict[str, int]]] = {
    # Phoenix (01) — пример: дома 2 страховка, 2/3 нестраховые; бизнесы 2 insured, 2/3 uninsured
    "01": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 2, "uninsured_min": 2, "uninsured_max": 3}},
    "02": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 2, "uninsured_min": 1, "uninsured_max": 2}},
    "03": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 1, "uninsured_min": 1, "uninsured_max": 2}},
    "04": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 1, "uninsured_min": 1, "uninsured_max": 2}},
    "05": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 2, "uninsured_min": 1, "uninsured_max": 2}},
    "06": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 2, "uninsured_min": 2, "uninsured_max": 3}},
    "07": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 2, "uninsured_min": 1, "uninsured_max": 2}},
    "08": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 1, "uninsured_min": 1, "uninsured_max": 2}},
    "09": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {"insured": 2, "uninsured_min": 2, "uninsured_max": 3}},
    "10": {"house": {"insured": 2, "uninsured_min": 2, "uninsured_max": 3},
           "biz":   {" insured": 2, "uninsured_min": 1, "uninsured_max": 2}},
    # ... продолжай заполнять по ТЗ
}
# Примерно так: для полноты мы оставим пустую секцию по умолчанию (если сервера нет в словаре, будет fallback)

class RealtorItem(BaseModel):
    slot: int
    payday: int
    type: str  # "Дом" или "Бизнес"
    state: Optional[str] = None

class RealtorPayload(BaseModel):
    server_id: Any
    server_name: str
    season: Optional[str] = "Неизвестно"
    scan_ts: Optional[float] = None  # UNIX-время в секундах, пришедшее из Lua
    items: List[RealtorItem]

def _to_dt(ts: Optional[float]) -> datetime:
    if ts is None:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return datetime.now(tz=timezone.utc)

def _nearest_payday_boundary(dt: datetime) -> datetime:
    # Ближайший часовой границы: если dt на границе часа - возвращаем dt
    if dt.minute == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt
    base = dt.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(hours=1)

def _get_target_pds(server_id: str, obj_type: str, insured: bool) -> List[int]:
    # возвращает список целевых PD для uninsured/insured
    rules = SERVER_RULES.get(server_id, None)
    if not rules:
        # дефолт: 2 insured, 2 uninsured_min и 3 uninsured_max
        if obj_type == "Дом":
            return [2, 2, 3] if not insured else [2]
        else:
            return [2, 1, 2] if not insured else [2]
    if obj_type == "Дом":
        t = rules.get("house", {"insured":2, "uninsured_min":2, "uninsured_max":3})
    else:
        t = rules.get("biz", {"insured":2, "uninsured_min":1, "uninsured_max":2})
    insured_pd = t.get("insured", 2)
    uninsured_min = t.get("uninsured_min", 2)
    uninsured_max = t.get("uninsured_max", uninsured_min)
    if insured:
        return [insured_pd]
    else:
        return [uninsured_min, uninsured_max]

def calculate_fall_time(server_id: str, server_name: str, obj_type: str, payday_val: int, insurance_status: str, update_time: datetime, is_h2: bool = False):
    try:
        # ближайшая граница Payday
        next_payday = _nearest_payday_boundary(update_time)

        insured = False
        if insurance_status and "Страх" in insurance_status:
            insured = True

        targets = _get_target_pds(server_id, obj_type, insured)
        if not targets:
            targets = [2]  # дефолт

        # hours_to_add для страховки: минимальное между целевыми PD
        hours_candidates = []
        for t in targets:
            hours_candidates.append(max(0, payday_val - t))
        hours_to_add = min(hours_candidates) if hours_candidates else 0

        if is_h2:
            hours_to_add = hours_to_add * 2

        fall_time = next_payday + timedelta(hours=hours_to_add)
        return fall_time.isoformat()
    except Exception as e:
        print("[Server Calc Error]", e)
        return None

@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    # используем scan_ts, чтобы учитывать часовой пояс и момент скана
    update_time = _to_dt(payload.scan_ts)
    now_str = update_time.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    server_id = payload.server_id
    server_name = payload.server_name
    season = payload.season

    for item in payload.items:
        cursor.execute("SELECT payday, recorded_at FROM scan_history WHERE server_id = ? AND slot = ? AND obj_type = ? ORDER BY id DESC LIMIT 1",
                       (server_id, item.slot, item.type))
        old = cursor.fetchone()

        insurance = item.state
        if not insurance and old:
            old_pd, old_time = old
            # простой расчёт по разнице PD между старым и текущим PD
            paydays = max(0, item.payday - old_pd)
            # если нужно, можно учесть строгие правила; здесь оставим как мощную базовую логику

        if not insurance:
            cursor.execute("SELECT insurance_status FROM server_objects WHERE server_id = ? AND slot = ? AND obj_type = ?",
                           (server_id, item.slot, item.type))
            row = cursor.fetchone()
            if row:
                insurance = row[0]

        fall_time = calculate_fall_time(server_id, server_name, item.type, item.payday, insurance, update_time)

        cursor.execute("""
            INSERT INTO server_objects (server_id, server_name, season, obj_type, slot, payday, insurance_status, exact_fall_time, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id, slot, obj_type) DO UPDATE SET
                payday = excluded.payday,
                insurance_status = COALESCE(excluded.insurance_status, server_objects.insurance_status),
                season = excluded.season,
                exact_fall_time = COALESCE(excluded.exact_fall_time, server_objects.exact_fall_time),
                last_updated = excluded.last_updated
        """, (server_id, server_name, season, item.type, item.slot, item.payday, insurance, fall_time, now_str))

        cursor.execute("""
            INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at)
            VALUES (?, ?, ?, ?, ?)
        """, (server_id, item.slot, item.type, item.payday, now_str))

    conn.commit()
    conn.close()
    return {"status": "success", "count": len(payload.items)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)
