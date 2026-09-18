import sqlite3

DB_NAME = "realtor_tracker.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_objects (
            server_id TEXT NOT NULL,
            server_name TEXT NOT NULL,
            season TEXT,
            obj_type TEXT NOT NULL,
            slot INTEGER NOT NULL,
            payday INTEGER NOT NULL,
            insurance_status TEXT,
            exact_fall_time TEXT,
            last_updated TEXT NOT NULL,
            is_frozen INTEGER DEFAULT 0,
            is_h2 INTEGER DEFAULT 0,
            is_estate INTEGER DEFAULT 0,
            PRIMARY KEY (server_id, slot, obj_type)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id TEXT NOT NULL,
            slot INTEGER NOT NULL,
            obj_type TEXT NOT NULL,
            payday INTEGER NOT NULL,
            recorded_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            expires_at TEXT NOT NULL,
            added_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_keys (
            key TEXT PRIMARY KEY,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by INTEGER,
            used INTEGER DEFAULT 0,
            used_by INTEGER
        )
    """)

    # Небольшая миграция для базы, созданной старой версией.
    # SQLite не добавляет новые поля через CREATE TABLE IF NOT EXISTS.
    cursor.execute("PRAGMA table_info(server_objects)")
    columns = {row[1] for row in cursor.fetchall()}
    for column, definition in {
        "is_frozen": "INTEGER DEFAULT 0",
        "is_h2": "INTEGER DEFAULT 0",
        "is_estate": "INTEGER DEFAULT 0",
    }.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE server_objects ADD COLUMN {column} {definition}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("[DB] База данных инициализирована")
