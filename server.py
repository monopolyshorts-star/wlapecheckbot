import sqlite3
import re
from datetime import datetime, timedelta
from typing import List, Optional, Any
from fastapi import FastAPI
from pydantic import BaseModel
from database import DB_NAME, init_db

app = FastAPI(title="Arizona Tracker API")
init_db()

SERVER_RULES = {
    "phoenix":     {"house": (2, 2, 3), "biz": (2, 2, 3)},
    "tucson":      {"house": (2, 2, 3), "biz": (2, 1, 2)},
    "scottdale":   {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "chandler":    {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "brainburg":   {"house": (2, 2, 3), "biz": (2, 1, 2)},
    "saintrose":   {"house": (2, 2, 3), "biz": (2, 2, 3)},
    "mesa":        {"house": (2, 2, 3), "biz": (2, 1, 2)},
    "redrock":     {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "yuma":        {"house": (2, 2, 3), "biz": (2, 2, 3)},
    "surprise":    {"house": (2, 2, 3), "biz": (2, 1, 2)},
    "prescott":    {"house": (2, 2, 3), "biz": (2, 1, 2)},
    "glendale":    {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "kingman":     {"house": (2, 2, 3), "biz": (2, 2, 3)},
    "winslow":     {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "payson":      {"house": (1, 1, 2), "biz": (1, 1, 2)},
    "gilbert":     {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "showlow":     {"house": (1, 1, 2), "biz": (1, 1, 2)},
    "casagrande":  {"house": (2, 2, 3), "biz": (2, 2, 3)},
    "page":        {"house": (2, 2, 3), "biz": (2, 1, 2)},
    "suncity":     {"house": (1, 1, 2), "biz": (1, 1, 2)},
    "queencreek":  {"house": (2, 2, 3), "biz": (2, 1, 2)},
    "sedona":      {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "holiday":     {"house": (2, 2, 3), "biz": (2, 1, 2)},
    "wednesday":   {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "yava":        {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "faraway":     {"house": (1, 1, 2), "biz": (2, 2, 3)},
    "bumblebee":   {"house": (1, 1, 2), "biz": (1, 1, 2)},
    "christmas":   {"house": (2, 2, 3), "biz": (2, 2, 3)},
    "mirage":      {"house": (2, 2, 3), "biz": (2, 2, 3)},
    "love":        {"house": (1, 1, 2), "biz": (2, 2, 3)},
    "drake":       {"house": (2, 2, 3), "biz": (1, 1, 2)},
    "space":       {"house": (1, 1, 2), "biz": (2, 1, 2)},
    "home":        {"house": (1, 1, 2), "biz": (2, 1, 2)}
}

class RealtorItem(BaseModel):
    slot: int
    payday: int
    type: str
    state: Optional[str] = None

class RealtorPayload(BaseModel):
    server_id: Any
    server_name: str
    season: Optional[str] = "Неизвестно"
    items: List[RealtorItem]

def get_clean_key(name: str) -> str:
    return re.sub(r'[^a-z]', '', name.lower())

def calculate_fall_time(server_name: str, obj_type: str, payday_val: int, insurance_status: str, update_time: datetime, is_h2: bool = False):
    try:
        next_payday = (update_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        is_biz = (obj_type == "Бизнес")
        
        if is_biz and payday_val == 4:
            hours_to_add = 0
        else:
            hours_to_add = payday_val - 1
            if "Нестрах" in str(insurance_status):
                hours_to_add = (payday_val // 2) - 1 if payday_val > 1 else 0
                
        if is_h2:
            hours_to_add = hours_to_add * 2
            
        fall_time = next_payday + timedelta(hours=max(0, hours_to_add))
        return fall_time.isoformat()
    except Exception:
        return None

@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%d.%m.%Y %H:%M:%S")

    for item in payload.items:
        cursor.execute("""
            SELECT payday, recorded_at FROM scan_history
            WHERE server_id = ? AND slot = ? AND obj_type = ?
            ORDER BY id DESC LIMIT 1
        """, (payload.server_id, item.slot, item.type))
        old_rec = cursor.fetchone()

        is_frozen = 0
        is_h2 = 0
        is_estate = 0
        insurance = item.state

        if old_rec:
            old_pd, old_time_str = old_rec
            try:
                old_time = datetime.strptime(old_time_str, "%d.%m.%Y %H:%M:%S")
                hours_diff = int((now - old_time).total_seconds() / 3600)
                if hours_diff > 0:
                    pd_diff = old_pd - item.payday
                    if pd_diff == 0 and hours_diff >= 2:
                        is_frozen = 1
                    elif pd_diff == 1 and hours_diff >= 2:
                        is_h2 = 1
            except:
                pass

        if not insurance and old_rec:
            old_pd = old_rec[0]
            if old_pd - item.payday >= 2 and item.payday == 1:
                is_estate = 1
                insurance = "Страх"

        fall_time = calculate_fall_time(payload.server_name, item.type, item.payday, insurance, now, is_h2=bool(is_h2))

        cursor.execute("""
            INSERT INTO server_objects (server_id, server_name, season, obj_type, slot, payday, insurance_status, exact_fall_time, last_updated, is_frozen, is_h2, is_estate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id, slot, obj_type) DO UPDATE SET
                payday = excluded.payday,
                insurance_status = COALESCE(excluded.insurance_status, server_objects.insurance_status),
                season = excluded.season,
                exact_fall_time = COALESCE(excluded.exact_fall_time, server_objects.exact_fall_time),
                last_updated = excluded.last_updated,
                is_frozen = excluded.is_frozen,
                is_h2 = excluded.is_h2,
                is_estate = excluded.is_estate
        """, (payload.server_id, payload.server_name, payload.season, item.type, item.slot, item.payday, insurance, fall_time, now_str, is_frozen, is_h2, is_estate))

        cursor.execute("""
            INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at)
            VALUES (?, ?, ?, ?, ?)
        """, (payload.server_id, item.slot, item.type, item.payday, now_str))

    conn.commit()
    conn.close()
    return {"status": "success", "count": len(payload.items)}
