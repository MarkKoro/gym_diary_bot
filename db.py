import aiosqlite, asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from settings import DB_PATH, TRIAL_DAYS, DB_POOL_SIZE

# Ограничиваем число одновременных операций с базой
_db_semaphore = asyncio.BoundedSemaphore(DB_POOL_SIZE)

@asynccontextmanager
async def connect_db():
    async with _db_semaphore:
        async with aiosqlite.connect(DB_PATH) as db:
            yield db

async def init_db():
    async with connect_db() as db:
        await db.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            username TEXT,
            tz TEXT DEFAULT 'Asia/Jerusalem',
            created_at TEXT,
            trial_until TEXT,
            plan TEXT DEFAULT 'trial'
        );

        CREATE TABLE IF NOT EXISTS exercises(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            muscle_group TEXT
        );

        CREATE TABLE IF NOT EXISTS user_exercises(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            exercise_id INTEGER,
            day_index INTEGER,            -- 1..7 (гибко, не привязано к календарю)
            UNIQUE(user_id, exercise_id, day_index)
        );

        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,                    -- 'YYYY-MM-DD' (локально для юзера)
            day_index INTEGER,
            UNIQUE(user_id, date)
        );

        CREATE TABLE IF NOT EXISTS sets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            user_exercise_id INTEGER,
            set_no INTEGER,
            reps INTEGER DEFAULT 0,
            weight_kg REAL DEFAULT 0
        );

        -- задел под биллинг (появится в Блоке 4)
        CREATE TABLE IF NOT EXISTS subscriptions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan TEXT,                    -- month / halfyear / year
            started_at TEXT,
            expires_at TEXT,
            status TEXT                   -- active/expired/cancelled
        );

        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            provider TEXT,                -- yookassa/telegram/...
            amount INTEGER,
            currency TEXT,
            created_at TEXT,
            status TEXT,
            payload_json TEXT
        );
        """)
        await db.commit()

async def get_or_create_user(tg_id: int, username: str|None):
    async with connect_db() as db:
        cur = await db.execute("SELECT id, trial_until FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        if row:
            return row[0]
        trial_until = (datetime.utcnow() + timedelta(days=TRIAL_DAYS)).isoformat()
        await db.execute(
            "INSERT INTO users(tg_id, username, created_at, trial_until) VALUES(?,?,?,?)",
            (tg_id, username, datetime.utcnow().isoformat(), trial_until)
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        return row[0]

async def ensure_default_plan(user_id: int):
    """Демо: создаём базовый День 1 с 3 упражнениями, если у юзера ничего нет."""
    default = [("Жим лёжа", "chest"), ("Присед", "legs"), ("Тяга в наклоне", "back")]
    async with connect_db() as db:
        # вставим упражнения в каталог (если их нет)
        for name, mg in default:
            try:
                await db.execute("INSERT INTO exercises(name, muscle_group) VALUES(?,?)", (name, mg))
            except Exception:
                pass
        await db.commit()

        # привяжем к пользователю на day_index=1
        for name, _ in default:
            cur = await db.execute("SELECT id FROM exercises WHERE name=?", (name,))
            ex = await cur.fetchone()
            ex_id = ex[0]
            try:
                await db.execute(
                    "INSERT INTO user_exercises(user_id, exercise_id, day_index) VALUES(?,?,1)",
                    (user_id, ex_id)
                )
            except Exception:
                pass
        await db.commit()

async def get_or_create_today_session(user_id: int, date_str: str, day_index: int = 1):
    async with connect_db() as db:
        cur = await db.execute("SELECT id FROM sessions WHERE user_id=? AND date=?", (user_id, date_str))
        row = await cur.fetchone()
        if row: return row[0]
        await db.execute("INSERT INTO sessions(user_id, date, day_index) VALUES(?,?,?)", (user_id, date_str, day_index))
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        return (await cur.fetchone())[0]

async def fetch_day_exercises(user_id: int, day_index: int = 1):
    async with connect_db() as db:
        cur = await db.execute("""
        SELECT ue.id, e.name
        FROM user_exercises ue
        JOIN exercises e ON e.id = ue.exercise_id
        WHERE ue.user_id=? AND ue.day_index=?
        ORDER BY e.name
        """, (user_id, day_index))
        return await cur.fetchall()

async def fetch_sets_table(session_id: int):
    async with connect_db() as db:
        cur = await db.execute("""
        SELECT sets.id, sets.user_exercise_id, sets.set_no, sets.reps, sets.weight_kg, e.name
        FROM sets
        JOIN user_exercises ue ON ue.id = sets.user_exercise_id
        JOIN exercises e ON e.id = ue.exercise_id
        WHERE sets.session_id=?
        ORDER BY e.name, sets.set_no
        """, (session_id,))
        rows = await cur.fetchall()
        return rows

async def add_set(session_id: int, user_ex_id: int):
    async with connect_db() as db:
        cur = await db.execute("SELECT COALESCE(MAX(set_no),0)+1 FROM sets WHERE session_id=? AND user_exercise_id=?", (session_id, user_ex_id))
        next_no = (await cur.fetchone())[0]
        await db.execute("INSERT INTO sets(session_id, user_exercise_id, set_no, reps, weight_kg) VALUES(?,?,?,?,?)",
                         (session_id, user_ex_id, next_no, 0, 0.0))
        await db.commit()

async def inc_last_set(user_ex_id: int, session_id: int, field: str, delta: float):
    assert field in ("reps", "weight_kg")
    async with connect_db() as db:
        cur = await db.execute("""
            SELECT id, reps, weight_kg FROM sets
            WHERE session_id=? AND user_exercise_id=?
            ORDER BY set_no DESC LIMIT 1
        """, (session_id, user_ex_id))
        row = await cur.fetchone()
        if not row:
            # если сетов нет — создаём первый
            await db.execute("INSERT INTO sets(session_id, user_exercise_id, set_no, reps, weight_kg) VALUES(?,?,?,?,?)",
                             (session_id, user_ex_id, 1, 0, 0.0))
            await db.commit()
            return await inc_last_set(user_ex_id, session_id, field, delta)
        set_id, reps, weight = row
        if field == "reps":
            reps = int(reps + delta)
            await db.execute("UPDATE sets SET reps=? WHERE id=?", (max(reps, 0), set_id))
        else:
            weight = float(weight + delta)
            await db.execute("UPDATE sets SET weight_kg=? WHERE id=?", (max(weight, 0.0), set_id))
        await db.commit()
