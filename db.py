import aiosqlite, asyncio
from datetime import datetime, timedelta, UTC
from contextlib import asynccontextmanager
from typing import Sequence
from settings import DB_PATH, TRIAL_DAYS, DB_POOL_SIZE
from kb_catalog import KB_EXERCISE_NAMES


DEFAULT_EXERCISES: Sequence[tuple[str, str]] = [
    ("Жим лёжа", "chest"),
    ("Жим гантелей", "chest"),
    ("Жим штанги на наклонной скамье", "chest"),
    ("Отжимания", "chest"),
    ("Разводка гантелей", "chest"),
    ("Пуловер", "chest"),
    ("Отжимания на брусьях", "chest"),
    ("Жим в тренажёре", "chest"),
    ("Сведение рук в тренажёре", "chest"),
    ("Тяга в наклоне", "back"),
    ("Подтягивания", "back"),
    ("Тяга штанги к поясу", "back"),
    ("Становая тяга", "back"),
    ("Тяга верхнего блока", "back"),
    ("Тяга нижнего блока", "back"),
    ("Гиперэкстензия", "back"),
    ("Тяга гантели в наклоне", "back"),
    ("Тяга Т-грифа", "back"),
    ("Присед", "legs"),
    ("Выпады", "legs"),
    ("Болгарские выпады", "legs"),
    ("Румынская тяга", "legs"),
    ("Жим ногами", "legs"),
    ("Сгибание ног", "legs"),
    ("Разгибание ног", "legs"),
    ("Подъём на носки", "legs"),
    ("Гакк-присед", "legs"),
    ("Приседания с собственным весом", "legs"),
    ("Жим над головой", "shoulders"),
    ("Подъём гантелей в стороны", "shoulders"),
    ("Подъём гантелей перед собой", "shoulders"),
    ("Жим Арнольда", "shoulders"),
    ("Жим над головой сидя", "shoulders"),
    ("Тяга к подбородку", "shoulders"),
    ("Махи гантелями в наклоне", "shoulders"),
    ("Подъём на бицепс", "biceps"),
    ("Молотки", "biceps"),
    ("Подъём EZ-штанги", "biceps"),
    ("Концентрированный подъём", "biceps"),
    ("Сгибание в блоке", "biceps"),
    ("Подъём штанги на бицепс", "biceps"),
    ("Подъём гантелей сидя на бицепс", "biceps"),
    ("Жим узким хватом", "triceps"),
    ("Разгибание на блоке", "triceps"),
    ("Французский жим", "triceps"),
    ("Отжимания на брусьях узким хватом", "triceps"),
    ("Разгибание гантели из-за головы", "triceps"),
    ("Отжимания на скамье", "triceps"),
    ("Разгибание рук в наклоне", "triceps"),
    ("Скручивания", "core"),
    ("Подъём ног лёжа", "core"),
    ("Подъём колен в висе", "core"),
    ("Русский твист", "core"),
    ("Касания пяток", "core"),
    ("Скручивания на скамье", "core"),
]

KB_EXERCISES: Sequence[tuple[str, str]] = tuple((name, "kb") for name in KB_EXERCISE_NAMES)

METCON_EXERCISES: Sequence[tuple[str, str]] = [
    ("Меткон — AMRAP (кастом)", "metcon"),
    ("Меткон — For Time (кастом)", "metcon"),
    ("Бёрпи", "metcon"),
    ("Трастеры (штанга)", "metcon"),
    ("Подтягивания (кроссфит)", "metcon"),
    ("Подъёмы носков к перекладине", "metcon"),
    ("Отжимания (кроссфит)", "metcon"),
    ("Приседания с собственным весом (кроссфит)", "metcon"),
    ("Прыжки на тумбу", "metcon"),
    ("Двойные прыжки на скакалке", "metcon"),
    ("Гребля (ккал)", "metcon"),
    ("Велотренажёр (ккал)", "metcon"),
    ("Бег (метры)", "metcon"),
    ("Лыжный эргометр (ккал)", "metcon"),
]

WORKOUT_EXERCISES: Sequence[tuple[str, str]] = [
    ("Подтягивания (воркаут, прямой хват)", "workout"),
    ("Подтягивания (воркаут, обратный хват)", "workout"),
    ("Подтягивания (воркаут, широкий хват)", "workout"),
    ("Австралийские подтягивания (воркаут)", "workout"),
    ("Выход силой на турник (воркаут)", "workout"),
    ("Отжимания на брусьях (воркаут)", "workout"),
    ("Отжимания от пола (воркаут)", "workout"),
    ("Отжимания узким хватом (воркаут)", "workout"),
    ("Пистолетик (левая) (воркаут)", "workout"),
    ("Пистолетик (правая) (воркаут)", "workout"),
    ("Удержание L-sit на брусьях (сек) (воркаут)", "workout"),
    ("Удержание уголка в висе (сек) (воркаут)", "workout"),
    ("Стойка на руках у стены (сек) (воркаут)", "workout"),
]

METCON_EXERCISE_NAMES = {name for name, _ in METCON_EXERCISES}
DEFAULT_EXERCISE_NAMES = {name for name, _ in DEFAULT_EXERCISES}
METCON_SHARED_NAMES = METCON_EXERCISE_NAMES & DEFAULT_EXERCISE_NAMES

SCHEME_SENTINEL = -1


async def _seed_exercises(db, exercises: Sequence[tuple[str, str]], update_group: bool = True):
    for name, mg in exercises:
        cur = await db.execute(
            "SELECT muscle_group FROM exercises WHERE name=?",
            (name,),
        )
        row = await cur.fetchone()
        if not row:
            await db.execute(
                "INSERT INTO exercises(name, muscle_group) VALUES(?,?)",
                (name, mg),
            )
        elif row[0] != mg and update_group:
            await db.execute(
                "UPDATE exercises SET muscle_group=? WHERE name=?",
                (mg, name),
            )

# Ограничиваем число одновременных операций с базой
_db_semaphore = asyncio.BoundedSemaphore(DB_POOL_SIZE)

@asynccontextmanager
async def connect_db():
    async with _db_semaphore:
        async with aiosqlite.connect(DB_PATH) as db:
            yield db


async def _column_exists(db, table: str, column: str) -> bool:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return any(row[1] == column for row in rows)

async def init_db():
    async with connect_db() as db:
        await db.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            username TEXT,
            tz TEXT DEFAULT 'UTC',
            created_at TEXT,
            trial_until TEXT,
            plan TEXT DEFAULT 'trial',
            system TEXT,
            workouts_per_week INTEGER
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
            is_archived INTEGER DEFAULT 0,
            UNIQUE(user_id, exercise_id, day_index)
        );

        CREATE TABLE IF NOT EXISTS user_days(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            day_index INTEGER,
            label TEXT,
            is_active INTEGER,
            UNIQUE(user_id, day_index)
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
            weight_kg REAL DEFAULT 0,
            is_warmup INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS day_completions(
            user_id INTEGER,
            day_index INTEGER,
            completed_at TEXT,
            PRIMARY KEY(user_id, day_index)
        );

        CREATE TABLE IF NOT EXISTS session_exercises(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            user_exercise_id INTEGER,
            is_done INTEGER DEFAULT 0,
            is_microcycle INTEGER DEFAULT 0,
            done_at TEXT,
            last_reps INTEGER,
            last_weight REAL,
            UNIQUE(session_id, user_exercise_id)
        );

        CREATE TABLE IF NOT EXISTS exercise_baseline(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            day_index INTEGER,
            exercise_id INTEGER,
            sets INTEGER,
            reps INTEGER,
            weight_kg REAL,
            UNIQUE(user_id, day_index, exercise_id)
        );

        CREATE TABLE IF NOT EXISTS user_reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            dow INTEGER,
            hour INTEGER,
            minute INTEGER
        );

        CREATE TABLE IF NOT EXISTS user_prefs(
            user_id INTEGER PRIMARY KEY,
            weight_step REAL DEFAULT 0.5,
            recording_mode TEXT DEFAULT 'flex',
            day_view_mode TEXT DEFAULT 'detailed',
            ui_mode TEXT CHECK(ui_mode IN ('compact','detailed')) DEFAULT 'detailed',
            ui_emoji_enabled INTEGER CHECK(ui_emoji_enabled IN (0,1)) DEFAULT 1,
            ui_verbose_level INTEGER CHECK(ui_verbose_level IN (0,1)) DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_measurements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            metric TEXT,
            value REAL,
            extra TEXT,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_measurements_user_metric
            ON user_measurements(user_id, metric, created_at);

        CREATE TABLE IF NOT EXISTS user_muscle_groups(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            UNIQUE(user_id, name)
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
        try:
            await db.execute("ALTER TABLE users ADD COLUMN system TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN workouts_per_week INTEGER")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE sets ADD COLUMN is_warmup INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE user_prefs ADD COLUMN recording_mode TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE user_prefs ADD COLUMN day_view_mode TEXT")
        except Exception:
            pass
        if not await _column_exists(db, "user_prefs", "ui_mode"):
            await db.execute(
                "ALTER TABLE user_prefs ADD COLUMN ui_mode TEXT CHECK(ui_mode IN ('compact','detailed')) DEFAULT 'detailed'"
            )
        if not await _column_exists(db, "user_prefs", "ui_emoji_enabled"):
            await db.execute(
                "ALTER TABLE user_prefs ADD COLUMN ui_emoji_enabled INTEGER CHECK(ui_emoji_enabled IN (0,1)) DEFAULT 1"
            )
        if not await _column_exists(db, "user_prefs", "ui_verbose_level"):
            await db.execute(
                "ALTER TABLE user_prefs ADD COLUMN ui_verbose_level INTEGER CHECK(ui_verbose_level IN (0,1)) DEFAULT 0"
            )
        await db.execute(
            "UPDATE user_prefs SET ui_mode = CASE WHEN ui_mode IN ('compact','detailed') THEN ui_mode ELSE COALESCE(day_view_mode, 'detailed') END"
        )
        await db.execute(
            "UPDATE user_prefs SET ui_emoji_enabled = CASE WHEN ui_emoji_enabled IN (0,1) THEN ui_emoji_enabled ELSE 1 END"
        )
        await db.execute(
            "UPDATE user_prefs SET ui_verbose_level = CASE WHEN ui_verbose_level IN (0,1) THEN ui_verbose_level ELSE 0 END"
        )
        try:
            await db.execute("ALTER TABLE user_exercises ADD COLUMN is_archived INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE session_exercises ADD COLUMN last_reps INTEGER")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE session_exercises ADD COLUMN last_weight REAL")
        except Exception:
            pass
        await db.commit()

        await _seed_exercises(db, DEFAULT_EXERCISES)
        await _seed_exercises(db, KB_EXERCISES)
        await _seed_exercises(db, METCON_EXERCISES, update_group=False)
        await _seed_exercises(db, WORKOUT_EXERCISES, update_group=False)
        await db.commit()

async def get_or_create_user(tg_id: int, username: str|None):
    async with connect_db() as db:
        cur = await db.execute("SELECT id, trial_until FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        if row:
            return row[0]
        trial_until = (datetime.now(UTC) + timedelta(days=TRIAL_DAYS)).isoformat()
        await db.execute(
            "INSERT INTO users(tg_id, username, created_at, trial_until) VALUES(?,?,?,?)",
            (tg_id, username, datetime.now(UTC).isoformat(), trial_until)
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

async def get_session_for_day(user_id: int, date_str: str, day_index: int) -> int | None:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id FROM sessions WHERE user_id=? AND date=? AND day_index=?",
            (user_id, date_str, day_index),
        )
        row = await cur.fetchone()
        return row[0] if row else None

async def fetch_day_exercises(user_id: int, day_index: int = 1, date_str: str | None = None):
    date_str = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
    async with connect_db() as db:
        cur = await db.execute(
            """
        SELECT ue.id, e.name, e.muscle_group, IFNULL(se.is_done,0), ue.exercise_id
        FROM user_exercises ue
        JOIN exercises e ON e.id = ue.exercise_id
        LEFT JOIN sessions s ON s.user_id=ue.user_id AND s.date=? AND s.day_index=ue.day_index
        LEFT JOIN session_exercises se ON se.session_id=s.id AND se.user_exercise_id=ue.id
        WHERE ue.user_id=? AND ue.day_index=? AND ue.is_archived=0
        ORDER BY ue.id
        """,
            (date_str, user_id, day_index),
        )
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


async def _upsert_session_defaults(db, session_id: int, user_ex_id: int, reps: int | float, weight: float):
    await db.execute(
        """
        INSERT INTO session_exercises(session_id, user_exercise_id, is_done, is_microcycle, done_at, last_reps, last_weight)
        VALUES(?,?,0,0,NULL,?,?)
        ON CONFLICT(session_id, user_exercise_id)
        DO UPDATE SET last_reps=excluded.last_reps, last_weight=excluded.last_weight
        """,
        (session_id, user_ex_id, int(reps), float(weight)),
    )


async def _refresh_session_defaults(db, session_id: int, user_ex_id: int):
    cur = await db.execute(
        """
        SELECT reps, weight_kg
        FROM sets
        WHERE session_id=? AND user_exercise_id=? AND is_warmup=0
        ORDER BY set_no DESC
        LIMIT 1
        """,
        (session_id, user_ex_id),
    )
    row = await cur.fetchone()
    if not row:
        cur = await db.execute(
            """
            SELECT reps, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=?
            ORDER BY set_no DESC
            LIMIT 1
            """,
            (session_id, user_ex_id),
        )
        row = await cur.fetchone()
    if row:
        await _upsert_session_defaults(db, session_id, user_ex_id, row[0], row[1])


async def get_session_last_values(session_id: int, user_ex_id: int) -> tuple[int, float] | None:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT last_reps, last_weight FROM session_exercises WHERE session_id=? AND user_exercise_id=?",
            (session_id, user_ex_id),
        )
        row = await cur.fetchone()
        if not row or row[0] is None or row[1] is None:
            return None
        return int(row[0]), float(row[1])

async def inc_last_set(user_ex_id: int, session_id: int, field: str, delta: float):
    assert field in ("reps", "weight_kg")
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, reps, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=?
            ORDER BY set_no DESC
            """,
            (session_id, user_ex_id),
        )
        rows = await cur.fetchall()
        if not rows:
            await db.execute(
                "INSERT INTO sets(session_id, user_exercise_id, set_no, reps, weight_kg) VALUES(?,?,?,?,?)",
                (session_id, user_ex_id, 1, 0, 0.0),
            )
            await db.commit()
            return await inc_last_set(user_ex_id, session_id, field, delta)
        current = rows[0][1] if field == "reps" else rows[0][2]
        if field == "reps":
            new_val = max(int(current + delta), 0)
        else:
            new_val = max(float(current + delta), 0.0)
        await db.executemany(
            f"UPDATE sets SET {field}=? WHERE id=?",
            [(new_val, r[0]) for r in rows],
        )
        reps_val = new_val if field == "reps" else rows[0][1]
        weight_val = new_val if field == "weight_kg" else rows[0][2]
        await _upsert_session_defaults(db, session_id, user_ex_id, reps_val, weight_val)
        await db.commit()

async def apply_sets_template(
    session_id: int,
    user_ex_id: int,
    template: Sequence[tuple[int | float | None, int | float | None]],
):
    async with connect_db() as db:
        await db.execute(
            "DELETE FROM sets WHERE session_id=? AND user_exercise_id=?",
            (session_id, user_ex_id),
        )
        rows = []
        for idx, (reps, weight) in enumerate(template, start=1):
            reps_val = int(reps) if reps is not None else 0
            weight_val = float(weight) if weight is not None else 0.0
            rows.append(
                (
                    session_id,
                    user_ex_id,
                    idx,
                    max(reps_val, 0),
                    max(weight_val, 0.0),
                )
            )
        if rows:
            await db.executemany(
                "INSERT INTO sets(session_id, user_exercise_id, set_no, reps, weight_kg, is_warmup) VALUES(?,?,?,?,?,0)",
                rows,
            )
            last = rows[-1]
            await _upsert_session_defaults(db, session_id, user_ex_id, last[3], last[4])
        else:
            await _refresh_session_defaults(db, session_id, user_ex_id)
        await db.commit()

async def inc_specific_set(user_ex_id: int, session_id: int, set_no: int, field: str, delta: float):
    assert field in ("reps", "weight_kg")
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, reps, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=? AND set_no=?
            LIMIT 1
            """,
            (session_id, user_ex_id, set_no),
        )
        row = await cur.fetchone()
        if not row:
            return
        set_id, reps, weight = row
        if field == "reps":
            new_val = max(int(reps + delta), 0)
            await db.execute("UPDATE sets SET reps=? WHERE id=?", (new_val, set_id))
        else:
            new_val = max(float(weight + delta), 0.0)
            await db.execute("UPDATE sets SET weight_kg=? WHERE id=?", (new_val, set_id))
        await _refresh_session_defaults(db, session_id, user_ex_id)
        await db.commit()

async def fetch_user_settings(user_id: int):
    async with connect_db() as db:
        cur = await db.execute("SELECT system, workouts_per_week FROM users WHERE id=?", (user_id,))
        return await cur.fetchone()

async def update_user_system(user_id: int, system: str):
    async with connect_db() as db:
        await db.execute("UPDATE users SET system=? WHERE id=?", (system, user_id))
        await db.commit()

async def set_workouts_per_week(user_id: int, n: int):
    async with connect_db() as db:
        await db.execute("UPDATE users SET workouts_per_week=? WHERE id=?", (n, user_id))
        for i in range(1, 8):
            label = f"День {i}"
            is_active = 1 if i <= n else 0
            await db.execute(
                """
                INSERT INTO user_days(user_id, day_index, label, is_active) VALUES(?,?,?,?)
                ON CONFLICT(user_id, day_index) DO UPDATE SET label=excluded.label, is_active=excluded.is_active
                """,
                (user_id, i, label, is_active),
            )
        await db.commit()

async def list_exercises_by_group(group: str):
    async with connect_db() as db:
        if group == "metcon" and METCON_SHARED_NAMES:
            placeholders = ",".join("?" for _ in METCON_SHARED_NAMES)
            query = (
                "SELECT id, name FROM exercises "
                "WHERE muscle_group=? OR name IN (" + placeholders + ") "
                "ORDER BY name"
            )
            params: tuple = (group, *METCON_SHARED_NAMES)
            cur = await db.execute(query, params)
        else:
            cur = await db.execute(
                "SELECT id, name FROM exercises WHERE muscle_group=? ORDER BY name",
                (group,),
            )
        return await cur.fetchall()

async def get_exercise_details(exercise_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT name, muscle_group FROM exercises WHERE id=?",
            (exercise_id,),
        )
        return await cur.fetchone()

async def list_user_exercise_ids(user_id: int, day_index: int, group: str):
    async with connect_db() as db:
        if group == "metcon" and METCON_SHARED_NAMES:
            placeholders = ",".join("?" for _ in METCON_SHARED_NAMES)
            query = (
                """
                SELECT e.id
                FROM user_exercises ue
                JOIN exercises e ON e.id = ue.exercise_id
                WHERE ue.user_id=? AND ue.day_index=? AND ue.is_archived=0
                  AND (e.muscle_group=? OR e.name IN ("""
                + placeholders
                + "))"
            )
            params: tuple = (user_id, day_index, group, *METCON_SHARED_NAMES)
            cur = await db.execute(query, params)
        else:
            cur = await db.execute(
                """
                SELECT e.id
                FROM user_exercises ue
                JOIN exercises e ON e.id = ue.exercise_id
                WHERE ue.user_id=? AND ue.day_index=? AND e.muscle_group=? AND ue.is_archived=0
                """,
                (user_id, day_index, group),
            )
        rows = await cur.fetchall()
        return [r[0] for r in rows]

async def add_user_muscle_group(user_id: int, name: str) -> str:
    async with connect_db() as db:
        cur = await db.execute(
            "INSERT INTO user_muscle_groups(user_id, name) VALUES(?,?)",
            (user_id, name),
        )
        await db.commit()
        return f"u{cur.lastrowid}"

async def list_user_muscle_groups(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, name FROM user_muscle_groups WHERE user_id=? ORDER BY name",
            (user_id,),
        )
        rows = await cur.fetchall()
        return [(f"u{r[0]}", r[1]) for r in rows]


async def remove_user_muscle_group(user_id: int, code: str) -> bool:
    if not code.startswith("u"):
        return False
    try:
        group_id = int(code[1:])
    except ValueError:
        return False
    async with connect_db() as db:
        cur = await db.execute(
            "DELETE FROM user_muscle_groups WHERE id=? AND user_id=?",
            (group_id, user_id),
        )
        removed = cur.rowcount > 0
        if removed:
            await db.execute(
                """
                UPDATE user_exercises
                SET is_archived=1
                WHERE user_id=?
                  AND exercise_id IN (
                      SELECT id FROM exercises WHERE muscle_group=?
                  )
                """,
                (user_id, code),
            )
        await db.commit()
        return removed

async def add_user_exercise(user_id: int, day_index: int, exercise_id: int):
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_exercises(user_id, exercise_id, day_index, is_archived)
            VALUES(?,?,?,0)
            ON CONFLICT(user_id, exercise_id, day_index)
            DO UPDATE SET is_archived=0
            """,
            (user_id, exercise_id, day_index),
        )
        if day_index != 0:
            await db.execute(
                """
                INSERT INTO user_exercises(user_id, exercise_id, day_index, is_archived)
                VALUES(?,?,0,0)
                ON CONFLICT(user_id, exercise_id, day_index)
                DO UPDATE SET is_archived=0
                """,
                (user_id, exercise_id),
            )
        await db.commit()

async def toggle_user_exercise(user_id: int, day_index: int, exercise_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, is_archived FROM user_exercises WHERE user_id=? AND day_index=? AND exercise_id=?",
            (user_id, day_index, exercise_id),
        )
        row = await cur.fetchone()
        if row and row[1] == 0:
            await db.execute("UPDATE user_exercises SET is_archived=1 WHERE id=?", (row[0],))
            await db.commit()
            return False
        await db.execute(
            """
            INSERT INTO user_exercises(user_id, exercise_id, day_index, is_archived)
            VALUES(?,?,?,0)
            ON CONFLICT(user_id, exercise_id, day_index)
            DO UPDATE SET is_archived=0
            """,
            (user_id, exercise_id, day_index),
        )
        if day_index != 0:
            await db.execute(
                """
                INSERT INTO user_exercises(user_id, exercise_id, day_index, is_archived)
                VALUES(?,?,0,0)
                ON CONFLICT(user_id, exercise_id, day_index)
                DO UPDATE SET is_archived=0
                """,
                (user_id, exercise_id),
            )
        await db.commit()
        return True


async def copy_day_plan_to_other_days(user_id: int, src_day: int, days: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT exercise_id FROM user_exercises WHERE user_id=? AND day_index=? AND is_archived=0",
            (user_id, src_day),
        )
        ex_ids = [r[0] for r in await cur.fetchall()]
        for d in range(1, days + 1):
            if d == src_day:
                continue
            for ex_id in ex_ids:
                await db.execute(
                    """
                    INSERT INTO user_exercises(user_id, exercise_id, day_index, is_archived)
                    VALUES(?,?,?,0)
                    ON CONFLICT(user_id, exercise_id, day_index)
                    DO UPDATE SET is_archived=0
                    """,
                    (user_id, ex_id, d),
                )
        cur = await db.execute(
            "SELECT exercise_id, sets, reps, weight_kg FROM exercise_baseline WHERE user_id=? AND day_index=?",
            (user_id, src_day),
        )
        rows = await cur.fetchall()
        for d in range(1, days + 1):
            if d == src_day:
                continue
            for ex_id, sets, reps, weight in rows:
                await db.execute(
                    """
                    INSERT INTO exercise_baseline(user_id, day_index, exercise_id, sets, reps, weight_kg)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(user_id, day_index, exercise_id)
                    DO UPDATE SET sets=excluded.sets, reps=excluded.reps, weight_kg=excluded.weight_kg
                    """,
                    (user_id, d, ex_id, sets, reps, weight),
                )
        await db.commit()


async def ensure_library_history(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT DISTINCT exercise_id
            FROM (
                SELECT ue.exercise_id AS exercise_id
                FROM sessions s
                JOIN session_exercises se ON se.session_id=s.id
                JOIN user_exercises ue ON ue.id=se.user_exercise_id
                WHERE s.user_id=?
                UNION
                SELECT ue.exercise_id
                FROM sessions s
                JOIN sets st ON st.session_id=s.id
                JOIN user_exercises ue ON ue.id=st.user_exercise_id
                WHERE s.user_id=?
                UNION
                SELECT exercise_id
                FROM exercise_baseline
                WHERE user_id=?
                UNION
                SELECT exercise_id
                FROM user_exercises
                WHERE user_id=? AND day_index>0
            )
            """,
            (user_id, user_id, user_id, user_id),
        )
        rows = await cur.fetchall()
        if not rows:
            return
        ex_ids = [r[0] for r in rows if r and r[0] is not None]
        if not ex_ids:
            return
        missing: list[int] = []
        for ex_id in ex_ids:
            cur = await db.execute(
                """
                SELECT 1
                FROM user_exercises
                WHERE user_id=? AND exercise_id=? AND day_index=0
                LIMIT 1
                """,
                (user_id, ex_id),
            )
            if await cur.fetchone() is None:
                missing.append(ex_id)
        if not missing:
            return
        await db.executemany(
            """
            INSERT INTO user_exercises(user_id, exercise_id, day_index, is_archived)
            VALUES(?,?,0,0)
            ON CONFLICT(user_id, exercise_id, day_index)
            DO UPDATE SET is_archived=0
            """,
            [(user_id, ex_id) for ex_id in missing],
        )
        await db.commit()


async def list_library_groups(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT e.muscle_group, e.name
            FROM user_exercises ue
            JOIN exercises e ON e.id=ue.exercise_id
            WHERE ue.user_id=? AND ue.day_index=0 AND ue.is_archived=0
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    counters: dict[str, int] = {}
    for group, name in rows:
        resolved = "metcon" if name in METCON_EXERCISE_NAMES else group
        counters[resolved] = counters.get(resolved, 0) + 1
    return sorted(counters.items())


async def list_library_exercises(user_id: int, group: str):
    async with connect_db() as db:
        if group == "metcon" and METCON_SHARED_NAMES:
            placeholders = ",".join("?" for _ in METCON_SHARED_NAMES)
            query = (
                """
                SELECT ue.id, e.name
                FROM user_exercises ue
                JOIN exercises e ON e.id=ue.exercise_id
                WHERE ue.user_id=? AND ue.day_index=0 AND ue.is_archived=0
                  AND (e.muscle_group=? OR e.name IN ("""
                + placeholders
                + "))"
                " ORDER BY e.name"
            )
            params: tuple = (user_id, group, *METCON_SHARED_NAMES)
            cur = await db.execute(query, params)
        else:
            cur = await db.execute(
                """
                SELECT ue.id, e.name
                FROM user_exercises ue
                JOIN exercises e ON e.id=ue.exercise_id
                WHERE ue.user_id=? AND ue.day_index=0 AND e.muscle_group=? AND ue.is_archived=0
                ORDER BY e.name
                """,
                (user_id, group),
            )
        return await cur.fetchall()


async def list_exercise_day_links(user_id: int, exercise_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT ue.day_index, COALESCE(ud.label, '')
            FROM user_exercises ue
            LEFT JOIN user_days ud ON ud.user_id=ue.user_id AND ud.day_index=ue.day_index
            WHERE ue.user_id=? AND ue.exercise_id=? AND ue.day_index>0 AND ue.is_archived=0
            ORDER BY ue.day_index
            """,
            (user_id, exercise_id),
        )
        rows = await cur.fetchall()
        return [(day_idx, label or "") for day_idx, label in rows]

async def get_or_create_exercise(name: str, muscle_group: str):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id FROM exercises WHERE LOWER(name)=LOWER(?)",
            (name,),
        )
        row = await cur.fetchone()
        if row:
            return row[0]
        await db.execute(
            "INSERT INTO exercises(name, muscle_group) VALUES(?,?)",
            (name, muscle_group),
        )
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        return (await cur.fetchone())[0]


async def user_has_library_exercise(user_id: int, name: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT 1
            FROM user_exercises ue
            JOIN exercises e ON e.id = ue.exercise_id
            WHERE ue.user_id=? AND ue.day_index=0 AND ue.is_archived=0 AND e.name=?
            LIMIT 1
            """,
            (user_id, name),
        )
        return await cur.fetchone() is not None

async def list_day_exercises(user_id: int, day_index: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT e.id, e.name, e.muscle_group
            FROM user_exercises ue
            JOIN exercises e ON e.id = ue.exercise_id
            WHERE ue.user_id=? AND ue.day_index=? AND ue.is_archived=0
            ORDER BY e.name
            """,
            (user_id, day_index),
        )
        return await cur.fetchall()


async def detach_user_exercise(user_id: int, day_index: int, exercise_id: int):
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE user_exercises
            SET is_archived=1
            WHERE user_id=? AND day_index=? AND exercise_id=?
            """,
            (user_id, day_index, exercise_id),
        )
        await db.commit()

async def set_baseline(user_id: int, day_index: int, exercise_id: int, sets: int, reps: int, weight: float):
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO exercise_baseline(user_id, day_index, exercise_id, sets, reps, weight_kg)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id, day_index, exercise_id)
            DO UPDATE SET sets=excluded.sets, reps=excluded.reps, weight_kg=excluded.weight_kg
            """,
            (user_id, day_index, exercise_id, sets, reps, weight),
        )
        await db.commit()

async def set_user_timezone(user_id: int, tz: str):
    async with connect_db() as db:
        await db.execute("UPDATE users SET tz=? WHERE id=?", (tz, user_id))
        await db.commit()


async def get_user_timezone(user_id: int):
    async with connect_db() as db:
        cur = await db.execute("SELECT tz FROM users WHERE id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else "UTC"

async def add_user_reminder(user_id: int, dow: int, hour: int, minute: int):
    async with connect_db() as db:
        await db.execute(
            "INSERT INTO user_reminders(user_id, dow, hour, minute) VALUES(?,?,?,?)",
            (user_id, dow, hour, minute),
        )
        await db.commit()


async def list_user_reminders(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT dow, hour, minute FROM user_reminders WHERE user_id=? ORDER BY id",
            (user_id,),
        )
        return await cur.fetchall()


async def clear_user_reminders(user_id: int):
    async with connect_db() as db:
        await db.execute("DELETE FROM user_reminders WHERE user_id=?", (user_id,))
        await db.commit()


async def list_users_with_reminders():
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT r.user_id, u.tg_id, r.dow, r.hour, r.minute FROM user_reminders r "
            "JOIN users u ON u.id = r.user_id"
        )
        return await cur.fetchall()


async def list_all_user_tg_ids():
    async with connect_db() as db:
        cur = await db.execute("SELECT tg_id FROM users WHERE tg_id IS NOT NULL")
        rows = await cur.fetchall()
        return [row[0] for row in rows]


async def list_active_days(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT day_index, label FROM user_days WHERE user_id=? AND is_active=1 ORDER BY day_index",
            (user_id,),
        )
        return await cur.fetchall()


async def list_day_completions(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT day_index, completed_at FROM day_completions WHERE user_id=?",
            (user_id,),
        )
        return await cur.fetchall()


async def mark_day_completed(user_id: int, day_index: int, completed_at: str):
    async with connect_db() as db:
        await db.execute(
            "REPLACE INTO day_completions(user_id, day_index, completed_at) VALUES(?,?,?)",
            (user_id, day_index, completed_at),
        )
        await db.commit()


async def clear_day_completions(user_id: int):
    async with connect_db() as db:
        await db.execute("DELETE FROM day_completions WHERE user_id=?", (user_id,))
        await db.commit()


async def get_day_label(user_id: int, day_index: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT label FROM user_days WHERE user_id=? AND day_index=?",
            (user_id, day_index),
        )
        row = await cur.fetchone()
        return row[0] if row else f"День {day_index}"

async def rename_day(user_id: int, day_index: int, label: str):
    async with connect_db() as db:
        await db.execute(
            "UPDATE user_days SET label=? WHERE user_id=? AND day_index=?",
            (label, user_id, day_index),
        )
        await db.commit()

async def remove_user_exercise(user_id: int, day_index: int, ue_id: int):
    async with connect_db() as db:
        await db.execute(
            "UPDATE user_exercises SET is_archived=1 WHERE id=? AND user_id=? AND day_index=?",
            (ue_id, user_id, day_index),
        )
        await db.commit()


async def clear_day_plan(user_id: int, day_index: int):
    async with connect_db() as db:
        await db.execute(
            "UPDATE user_exercises SET is_archived=1 WHERE user_id=? AND day_index=? AND is_archived=0",
            (user_id, day_index),
        )
        await db.execute(
            "DELETE FROM exercise_baseline WHERE user_id=? AND day_index=?",
            (user_id, day_index),
        )
        await db.commit()


async def get_exercise_info(ue_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT ue.exercise_id, e.name, e.muscle_group
            FROM user_exercises ue
            JOIN exercises e ON e.id = ue.exercise_id
            WHERE ue.id=?
            """,
            (ue_id,),
        )
        return await cur.fetchone()

async def get_baseline(user_id: int, day_index: int, exercise_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT sets, reps, weight_kg FROM exercise_baseline "
            "WHERE user_id=? AND day_index=? AND exercise_id=? AND sets>=0",
            (user_id, day_index, exercise_id),
        )
        row = await cur.fetchone()
        if row:
            return row
        cur = await db.execute(
            "SELECT sets, reps, weight_kg FROM exercise_baseline "
            "WHERE user_id=? AND exercise_id=? AND sets>=0 ORDER BY day_index LIMIT 1",
            (user_id, exercise_id),
        )
        return await cur.fetchone()

async def get_exercise_scheme(user_id: int, day_index: int, exercise_id: int) -> str | None:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT weight_kg FROM exercise_baseline "
            "WHERE user_id=? AND day_index=? AND exercise_id=? AND sets=?",
            (user_id, day_index, exercise_id, SCHEME_SENTINEL),
        )
        row = await cur.fetchone()
        if row and row[0]:
            return str(row[0])
        cur = await db.execute(
            "SELECT weight_kg FROM exercise_baseline "
            "WHERE user_id=? AND exercise_id=? AND sets=? ORDER BY day_index LIMIT 1",
            (user_id, exercise_id, SCHEME_SENTINEL),
        )
        row = await cur.fetchone()
        if row and row[0]:
            return str(row[0])
        return None

async def set_exercise_scheme(user_id: int, day_index: int, exercise_id: int, text: str | None):
    async with connect_db() as db:
        cleaned = text.strip() if text else ""
        if cleaned:
            await db.execute(
                """
                INSERT INTO exercise_baseline(user_id, day_index, exercise_id, sets, reps, weight_kg)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id, day_index, exercise_id)
                DO UPDATE SET sets=excluded.sets, reps=excluded.reps, weight_kg=excluded.weight_kg
                """,
                (user_id, day_index, exercise_id, SCHEME_SENTINEL, 0, cleaned),
            )
        else:
            await db.execute(
                "DELETE FROM exercise_baseline WHERE user_id=? AND day_index=? AND exercise_id=? AND sets=?",
                (user_id, day_index, exercise_id, SCHEME_SENTINEL),
            )
        await db.commit()

async def get_last_session_summary(user_id: int, day_index: int, ue_id: int, today: str):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id FROM sessions WHERE user_id=? AND day_index=? AND date<? ORDER BY date DESC LIMIT 1",
            (user_id, day_index, today),
        )
        row = await cur.fetchone()
        if not row:
            return None
        session_id = row[0]
        cur = await db.execute(
            "SELECT reps, weight_kg FROM sets WHERE session_id=? AND user_exercise_id=? AND is_warmup=0 ORDER BY set_no DESC LIMIT 1",
            (session_id, ue_id),
        )
        last = await cur.fetchone()
        if not last:
            return None
        reps, weight = last
        cur = await db.execute(
            "SELECT COUNT(*) FROM sets WHERE session_id=? AND user_exercise_id=? AND is_warmup=0",
            (session_id, ue_id),
        )
        count = (await cur.fetchone())[0]
        return count, reps, weight

async def fetch_last_session_sets(user_id: int, day_index: int, ue_id: int, today: str):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT exercise_id FROM user_exercises WHERE id=?",
            (ue_id,),
        )
        row = await cur.fetchone()
        if not row:
            return []
        exercise_id = row[0]
        cur = await db.execute(
            """
            SELECT s.id, st.user_exercise_id
            FROM sessions s
            JOIN sets st ON st.session_id=s.id AND st.is_warmup=0
            JOIN user_exercises ue ON ue.id=st.user_exercise_id
            WHERE s.user_id=? AND ue.exercise_id=? AND s.date<?
            ORDER BY s.date DESC, st.set_no DESC
            LIMIT 1
            """,
            (user_id, exercise_id, today),
        )
        row = await cur.fetchone()
        if not row:
            return []
        session_id, prev_ue_id = row
        cur = await db.execute(
            """
            SELECT set_no, reps, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=? AND is_warmup=0
            ORDER BY set_no
            """,
            (session_id, prev_ue_id),
        )
        return await cur.fetchall()

async def fetch_exercise_sets(session_id: int, ue_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT set_no, reps, weight_kg, is_warmup FROM sets WHERE session_id=? AND user_exercise_id=? ORDER BY set_no",
            (session_id, ue_id),
        )
        return await cur.fetchall()

async def add_set(session_id: int, user_ex_id: int, reps: int = 0, weight: float = 0.0):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COALESCE(MAX(set_no),0)+1 FROM sets WHERE session_id=? AND user_exercise_id=?",
            (session_id, user_ex_id),
        )
        next_no = (await cur.fetchone())[0]
        await db.execute(
            "INSERT INTO sets(session_id, user_exercise_id, set_no, reps, weight_kg, is_warmup) VALUES(?,?,?,?,?,0)",
            (session_id, user_ex_id, next_no, reps, weight),
        )
        await _upsert_session_defaults(db, session_id, user_ex_id, reps, weight)
        await db.commit()

async def remove_last_set(user_ex_id: int, session_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, reps, weight_kg FROM sets WHERE session_id=? AND user_exercise_id=? ORDER BY set_no DESC LIMIT 1",
            (session_id, user_ex_id),
        )
        row = await cur.fetchone()
        if row:
            set_id, reps, weight = row
            await db.execute("DELETE FROM sets WHERE id=?", (set_id,))
            await _refresh_session_defaults(db, session_id, user_ex_id)
            cur = await db.execute(
                "SELECT COUNT(*) FROM sets WHERE session_id=? AND user_exercise_id=? AND is_warmup=0",
                (session_id, user_ex_id),
            )
            remaining = (await cur.fetchone())[0]
            if remaining == 0:
                await _upsert_session_defaults(db, session_id, user_ex_id, reps, weight)
            await db.commit()

async def toggle_last_set_warmup(user_ex_id: int, session_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, is_warmup FROM sets WHERE session_id=? AND user_exercise_id=? ORDER BY set_no DESC LIMIT 1",
            (session_id, user_ex_id),
        )
        row = await cur.fetchone()
        if not row:
            return
        set_id, is_warmup = row
        new_val = 0 if is_warmup else 1
        await db.execute("UPDATE sets SET is_warmup=? WHERE id=?", (new_val, set_id))
        await _refresh_session_defaults(db, session_id, user_ex_id)
        await db.commit()

async def mark_exercise_done(session_id: int, ue_id: int):
    async with connect_db() as db:
        await _refresh_session_defaults(db, session_id, ue_id)
        cur = await db.execute(
            "SELECT last_reps, last_weight FROM session_exercises WHERE session_id=? AND user_exercise_id=?",
            (session_id, ue_id),
        )
        row = await cur.fetchone()
        last_reps = row[0] if row and row[0] is not None else None
        last_weight = row[1] if row and row[1] is not None else None
        await db.execute(
            """
            INSERT INTO session_exercises(session_id, user_exercise_id, is_done, is_microcycle, done_at, last_reps, last_weight)
            VALUES(?,?,1,0,?,?,?)
            ON CONFLICT(session_id, user_exercise_id)
            DO UPDATE SET
                is_done=1,
                done_at=excluded.done_at,
                last_reps=COALESCE(excluded.last_reps, session_exercises.last_reps),
                last_weight=COALESCE(excluded.last_weight, session_exercises.last_weight)
            """,
            (
                session_id,
                ue_id,
                datetime.now(UTC).isoformat(),
                last_reps,
                last_weight,
            ),
        )
        await db.commit()

async def list_recent_progress(user_id: int, day_index: int, ue_id: int, limit: int = 4, offset: int = 0):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT exercise_id FROM user_exercises WHERE id=?",
            (ue_id,),
        )
        row = await cur.fetchone()
        if not row:
            return []
        exercise_id = row[0]
        cur = await db.execute(
            """
            SELECT s.date,
                   COUNT(st.id) as sets,
                   MAX(st.reps) as reps,
                   MAX(st.weight_kg) as weight
            FROM sessions s
            JOIN session_exercises se ON se.session_id=s.id
            JOIN user_exercises ue ON ue.id=se.user_exercise_id
            LEFT JOIN sets st ON st.session_id=s.id AND st.user_exercise_id=se.user_exercise_id AND st.is_warmup=0
            WHERE s.user_id=? AND ue.exercise_id=? AND se.is_done=1
            GROUP BY s.id
            ORDER BY s.date DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, exercise_id, limit, offset),
        )
        return await cur.fetchall()

async def count_exercise_progress_entries(user_id: int, day_index: int, ue_id: int) -> int:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT exercise_id FROM user_exercises WHERE id=?",
            (ue_id,),
        )
        row = await cur.fetchone()
        if not row:
            return 0
        exercise_id = row[0]
        cur = await db.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT s.id
                FROM sessions s
                JOIN session_exercises se ON se.session_id=s.id AND se.is_done=1
                JOIN user_exercises ue ON ue.id=se.user_exercise_id
                WHERE s.user_id=? AND ue.exercise_id=?
                GROUP BY s.id
            )
            """,
            (user_id, exercise_id),
        )
        total = await cur.fetchone()
        return total[0] if total and total[0] is not None else 0

async def list_last_done_dates(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT ue.exercise_id, MAX(s.date)
            FROM sessions s
            JOIN session_exercises se ON se.session_id=s.id AND se.is_done=1
            JOIN user_exercises ue ON ue.id=se.user_exercise_id
            WHERE s.user_id=?
            GROUP BY ue.exercise_id
            """,
            (user_id,),
        )
        return await cur.fetchall()

async def get_recording_mode(user_id: int) -> str:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT recording_mode FROM user_prefs WHERE user_id=?",
            (user_id,),
        )
        row = await cur.fetchone()
        if row and row[0] == "flex":
            return "flex"
    await set_recording_mode(user_id, "flex")
    return "flex"


async def set_recording_mode(user_id: int, mode: str):
    if mode != "flex":
        mode = "flex"
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_prefs(user_id, recording_mode) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET recording_mode=excluded.recording_mode
            """,
            (user_id, mode),
        )
        await db.commit()


async def get_ui_preferences(user_id: int) -> tuple[str, int, int]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT ui_mode, ui_emoji_enabled, ui_verbose_level, day_view_mode
            FROM user_prefs WHERE user_id=?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    mode = "detailed"
    emoji = 1
    verbose = 0
    if row:
        stored_mode, stored_emoji, stored_verbose, legacy_mode = row
        if stored_mode in ("compact", "detailed"):
            mode = stored_mode
        elif legacy_mode in ("compact", "detailed"):
            mode = legacy_mode
        if stored_emoji in (0, 1):
            emoji = int(stored_emoji)
        if stored_verbose in (0, 1):
            verbose = int(stored_verbose)
    return mode, emoji, verbose


async def set_ui_mode(user_id: int, mode: str):
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_prefs(user_id, ui_mode, day_view_mode) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET ui_mode=excluded.ui_mode, day_view_mode=excluded.day_view_mode
            """,
            (user_id, mode, mode),
        )
        await db.commit()


async def set_ui_emoji_enabled(user_id: int, enabled: bool):
    value = 1 if enabled else 0
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_prefs(user_id, ui_emoji_enabled) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET ui_emoji_enabled=excluded.ui_emoji_enabled
            """,
            (user_id, value),
        )
        await db.commit()


async def set_ui_verbose_level(user_id: int, level: int):
    safe_level = 1 if level else 0
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_prefs(user_id, ui_verbose_level) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET ui_verbose_level=excluded.ui_verbose_level
            """,
            (user_id, safe_level),
        )
        await db.commit()


async def get_day_view_mode(user_id: int) -> str:
    mode, _, _ = await get_ui_preferences(user_id)
    return mode


async def set_day_view_mode(user_id: int, mode: str):
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_prefs(user_id, ui_mode, day_view_mode) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET ui_mode=excluded.ui_mode, day_view_mode=excluded.day_view_mode
            """,
            (user_id, mode, mode),
        )
        await db.commit()


async def add_measurement_entry(user_id: int, metric: str, value: float, extra: str | None = None):
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_measurements(user_id, metric, value, extra, created_at)
            VALUES(?,?,?,?,?)
            """,
            (user_id, metric, value, extra, datetime.now(UTC).isoformat()),
        )
        await db.commit()


async def update_last_measurement(
    user_id: int,
    metric: str,
    value: float,
    extra: str | None = None,
) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id FROM user_measurements WHERE user_id=? AND metric=? ORDER BY created_at DESC LIMIT 1",
            (user_id, metric),
        )
        row = await cur.fetchone()
        if not row:
            return False
        await db.execute(
            "UPDATE user_measurements SET value=?, extra=?, created_at=? WHERE id=?",
            (value, extra, datetime.now(UTC).isoformat(), row[0]),
        )
        await db.commit()
        return True


async def delete_last_measurement(user_id: int, metric: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id FROM user_measurements WHERE user_id=? AND metric=? ORDER BY created_at DESC LIMIT 1",
            (user_id, metric),
        )
        row = await cur.fetchone()
        if not row:
            return False
        await db.execute("DELETE FROM user_measurements WHERE id=?", (row[0],))
        await db.commit()
        return True


async def list_measurement_metrics(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT metric, MAX(created_at)
            FROM user_measurements
            WHERE user_id=?
            GROUP BY metric
            ORDER BY MAX(created_at) DESC
            """,
            (user_id,),
        )
        return await cur.fetchall()


async def fetch_measurement_history(user_id: int, metric: str, limit: int = 2):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT value, extra, created_at
            FROM user_measurements
            WHERE user_id=? AND metric=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, metric, limit),
        )
        return await cur.fetchall()


async def get_measurements_last_update(user_id: int) -> str | None:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT MAX(created_at) FROM user_measurements WHERE user_id=?",
            (user_id,),
        )
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
