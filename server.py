import sqlite3
import re
from datetime import datetime, timedelta
from typing import List, Optional, Any
from fastapi import FastAPI
from pydantic import BaseModel
from database import DB_NAME, init_db

app = FastAPI(title="Arizona Tracker API")
init_db()

# Правила слётов из ТЗ: (Целевой PayDay для страховки, нестраховки)
SERVER_RULES = {
    "phoenix":     {"house": (2, 2), "biz": (2, 2)},
    "tucson":      {"house": (2, 2), "biz": (2, 1)},
    "scottdale":   {"house": (2, 2), "biz": (1, 1)},
    "chandler":    {"house": (2, 2), "biz": (1, 1)},
    "brainburg":   {"house": (2, 2), "biz": (2, 1)},
    "saintrose":   {"house": (2, 2), "biz": (2, 2)},
    "mesa":        {"house": (2, 2), "biz": (2, 1)},
    "redrock":     {"house": (2, 2), "biz": (1, 1)},
    "yuma":        {"house": (2, 2), "biz": (2, 2)},
    "surprise":    {"house": (2, 2), "biz": (2, 1)},
    "prescott":    {"house": (2, 2), "biz": (2, 1)},
    "glendale":    {"house": (2, 2), "biz": (1, 1)},
    "kingman":     {"house": (2, 2), "biz": (2, 2)},
    "winslow":     {"house": (2, 2), "biz": (1, 1)},
    "payson":      {"house": (1, 1), "biz": (1, 1)},
    "gilbert":     {"house": (2, 2), "biz": (1, 1)},
    "showlow":     {"house": (1, 1), "biz": (1, 1)},
    "casagrande":  {"house": (2, 2), "biz": (2, 2)},
    "page":        {"house": (2, 2), "biz": (2, 1)},
    "suncity":     {"house": (1, 1), "biz": (1, 1)},
    "queencreek":  {"house": (2, 2), "biz": (2, 1)},
    "sedona":      {"house": (2, 2), "biz": (1, 1)},
    "holiday":     {"house": (2, 2), "biz": (2, 1)},
    "wednesday":   {"house": (2, 2), "biz": (1, 1)},
    "yava":        {"house": (2, 2), "biz": (1, 1)},
    "faraway":     {"house": (1, 1), "biz": (2, 2)},
    "bumblebee":   {"house": (1, 1), "biz": (1, 1)},
    "christmas":   {"house": (2, 2), "biz": (2, 2)},
    "mirage":      {"house": (2, 2), "biz": (2, 2)},
    "love":        {"house": (1, 1), "biz": (2, 2)},
    "drake":       {"house": (2, 2), "biz": (1, 1)},
    "space":       {"house": (1, 1), "biz": (2, 1)},
    "home":        {"house": (1, 1), "biz": (2, 1)}
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
    scan_ts: Optional[float] = None
    items: List[RealtorItem]

def get_clean_key(name: str) -> str:
    return re.sub(r'[^a-z]', '', name.lower())

def calculate_fall_time(server_name: str, obj_type: str, payday_val: int, insurance_status: str, update_time: datetime):
    try:
        # Умножаем на 1 час каждый Payday. 
        # Если дом застрахованный (-1 пд/час), если нестрахованный (-2 пд/час).
        is_biz = (obj_type == "Бизнес")
        s_key = get_clean_key(server_name)
        rules = SERVER_RULES.get(s_key, {"house": (2, 2), "biz": (2, 1)})
        
        is_insured = True
        if insurance_status and "Нестрах" in insurance_status:
            is_insured = False

        # По ТЗ: если страхованный — уменьшается по 1 PD каждый час. Если нестрахованный — по 2 PD каждый час.
        drop_per_hour = 1 if is_insured else 2
        
        # Целевой порог слёта (куда должен упасть PD, чтобы слететь)
        rule_set = rules["biz"] if is_biz else rules["house"]
        target_pd = rule_set[0] if is_insured else rule_set[1]

        # Сколько PayDay осталось пройти до целевого порога
        paydays_left = max(0, payday_val - target_pd)
        
        # Сколько часов нужно добавить (с учетом скорости падения: 1 час на 1 PD для страха, 1 час на 2 PD для нестраха)
        hours_to_add = paydays_left / drop_per_hour

        # Ближайший PayDay — следующий ровный час по МСК
        next_payday = (update_time + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        
        fall_time = next_payday + timedelta(hours=hours_to_add)
        return fall_time.isoformat()
    except Exception as e:
        print(f"[Calc Error] {e}")
        return None

@app.post("/api/update")
async def update_objects(payload: RealtorPayload):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # ПРИВЯЗКА К МОСКОВСКОМУ ВРЕМЕНИ (UTC+3)
    if payload.scan_ts:
        # Переводим локальное время пользователя (+7) в Московское время (UTC+3)
        # Разница между +7 и МСК (+3) составляет -4 часа.
        local_time = datetime.fromtimestamp(payload.scan_ts)
        now = local_time - timedelta(hours=4)
    else:
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
            except:
                pass

        # Определение страховки по скорости уменьшения (если дельта 1 за час — страх, если 2 — нестрах)
        if not insurance and old_rec:
            old_pd = old_rec[0]
            old_time = datetime.strptime(old_rec[1], "%d.%m.%Y %H:%M:%S")
            h_diff = max(1, int((now - old_time).total_seconds() / 3600))
            drop_speed = (old_pd - item.payday) / h_diff
            
            if drop_speed >= 1.5:
                insurance = "Нестрах"
            else:
                insurance = "Страх"
                
            old_pd_val = old_rec[0]
            if old_pd_val - item.payday >= 2 and item.payday == 1:
                is_estate = 1
                insurance = "Страх"

        # Если статус всё еще неизвестен, по умолчанию считаем застрахованным (-1 PD в час)
        if not insurance:
            insurance = "Страх"

        fall_time = calculate_fall_time(payload.server_name, item.type, item.payday, insurance, now)

        cursor.execute("""
            INSERT INTO server_objects (server_id, server_name, season, obj_type, slot, payday, insurance_status, exact_fall_time, last_updated, is_frozen, is_h2, is_estate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(server_id, slot, obj_type) DO UPDATE SET
                payday = excluded.payday,
                insurance_status = COALESCE(excluded.insurance_status, server_objects.insurance_status),
                season = excluded.season,
                exact_fall_time = COALESCE(excluded.exact_fall_time, server_objects.exact_fall_time),
                last_updated = excluded.last_updated,
                is_frozen = excluded.is_frozen,
                is_estate = excluded.is_estate
        """, (payload.server_id, payload.server_name, payload.season, item.type, item.slot, item.payday, insurance, fall_time, now_str, is_estate))

        cursor.execute("""
            INSERT INTO scan_history (server_id, slot, obj_type, payday, recorded_at)
            VALUES (?, ?, ?, ?, ?)
        """, (payload.server_id, item.slot, item.type, item.payday, now_str))

    conn.commit()
    conn.close()
    return {"status": "success", "count": len(payload.items)}
