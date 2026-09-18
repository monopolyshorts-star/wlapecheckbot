import sqlite3

DB_NAME = "realtor_tracker.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Таблица объектов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_objects (
            server_id TEXT,
            server_name TEXT,
            season TEXT,
            obj_type TEXT, -- "Дом" или "Бизнес"
            slot INTEGER,
            payday INTEGER,
            insurance_status TEXT, -- "Страх", "Нестрах", "Страх, Занят", "Страх, Незанят", "Нестрах, Незанят"
            exact_fall_time TEXT,  -- ISO формат времени слета
            last_updated TEXT,
            PRIMARY KEY (server_id, slot, obj_type)
        )
    """)
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("[DB] Новая база данных трекера инициализирована!")
