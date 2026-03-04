import aiosqlite, asyncio
import json
from datetime import datetime, timedelta, timezone, UTC
import secrets
from contextlib import asynccontextmanager
from typing import Optional, Sequence
from settings import DB_PATH, DB_POOL_SIZE
from kb_catalog import KB_CATEGORY_DEFINITION, KB_EXERCISE_NAMES


DEFAULT_EXERCISES: Sequence[tuple[str, str]] = [
    ("Жим лёжа", "chest"),
    ("Жим гантелей", "chest"),
    ("Жим штанги на наклонной скамье", "chest"),
    ("Отжимания", "chest"),
    ("Разводка гантелей", "chest"),
    ("Жим гантелей на наклонной скамье", "chest"),
    ("Пуловер", "chest"),
    ("Отжимания на брусьях", "chest"),
    ("Жим в тренажёре", "chest"),
    ("Сведение рук в тренажёре", "chest"),
    ("Сведение в кроссовере", "chest"),
    ("Тяга в наклоне", "back"),
    ("Подтягивания", "back"),
    ("Тяга штанги к поясу", "back"),
    ("Становая тяга", "back"),
    ("Тяга верхнего блока", "back"),
    ("Тяга нижнего блока", "back"),
    ("Подтягивания широким хватом", "back"),
    ("Тяга горизонтального блока", "back"),
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
    ("Сумо-присед", "legs"),
    ("Ягодичный мост", "legs"),
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
    ("Разведения в тренажёре (задняя дельта)", "shoulders"),
    ("Армейский жим", "shoulders"),
    ("Подъём на бицепс", "biceps"),
    ("Молотки", "biceps"),
    ("Подъём EZ-штанги", "biceps"),
    ("Концентрированный подъём", "biceps"),
    ("Сгибание в блоке", "biceps"),
    ("Подъём штанги на бицепс", "biceps"),
    ("Подъём гантелей сидя на бицепс", "biceps"),
    ("Сгибания на скамье Скотта", "biceps"),
    ("Сгибания с гантелями на наклонной скамье", "biceps"),
    ("Жим узким хватом", "triceps"),
    ("Разгибание на блоке", "triceps"),
    ("Французский жим", "triceps"),
    ("Отжимания на брусьях узким хватом", "triceps"),
    ("Разгибание гантели из-за головы", "triceps"),
    ("Отжимания на скамье", "triceps"),
    ("Разгибание рук в наклоне", "triceps"),
    ("Разгибание рук на блоке с канатом", "triceps"),
    ("Разгибание одной рукой на блоке", "triceps"),
    ("Скручивания", "core"),
    ("Подъём ног лёжа", "core"),
    ("Подъём колен в висе", "core"),
    ("Русский твист", "core"),
    ("Касания пяток", "core"),
    ("Скручивания на скамье", "core"),
    ("Планка", "core"),
    ("Велосипед", "core"),
    ("Подъём корпуса", "core"),
    ("Бег", "run"),
]

KB_EXERCISES: Sequence[tuple[str, str]] = tuple((name, "kb") for name in KB_EXERCISE_NAMES)

MUSCLE_CODES = ["chest", "back", "legs", "shoulders", "biceps", "triceps", "core", "cardio"]

ANATOMICAL_GROUPS = {"chest", "back", "legs", "shoulders", "core", "biceps", "triceps"}

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


def normalize_dow(dow: int | str) -> int:
    """Normalize a day-of-week value to the range 0..6."""

    d = int(dow)
    # Values already in the 0-6 range are treated as normalized (Monday=0).
    if 0 <= d <= 6:
        return d
    if 1 <= d <= 7:
        return (d - 1) % 7
    return d % 7

SCHEME_SENTINEL = -1

DURATION_NAME_PATTERNS: tuple[str, ...] = (
    "(сек",
    "удержание",
    "стойка",
    "планк",
)
DURATION_NAME_SQL = " OR ".join("LOWER(e.name) LIKE ?" for _ in DURATION_NAME_PATTERNS)


def _duration_name_params() -> tuple[str, ...]:
    return tuple(f"%{pattern}%" for pattern in DURATION_NAME_PATTERNS)


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


async def _ensure_muscle_map_schema(db):
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS exercise_muscles(
            exercise_id INTEGER NOT NULL,
            muscle_code TEXT NOT NULL,
            weight_pct REAL NOT NULL,
            PRIMARY KEY(exercise_id, muscle_code),
            FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_exercise_muscles(
            user_id INTEGER NOT NULL,
            exercise_id INTEGER NOT NULL,
            muscle_code TEXT NOT NULL,
            weight_pct REAL NOT NULL,
            PRIMARY KEY(user_id, exercise_id, muscle_code),
            FOREIGN KEY(exercise_id) REFERENCES exercises(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_exercise_muscles_exercise_id
            ON exercise_muscles(exercise_id);
        """
    )


async def _ensure_achievements_schema(db):
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_achievements(
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            PRIMARY KEY(user_id, code)
        );

        CREATE INDEX IF NOT EXISTS idx_user_achievements_user_unlocked
            ON user_achievements(user_id, unlocked_at DESC);

        CREATE TABLE IF NOT EXISTS training_system_copy_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_user_id INTEGER NOT NULL,
            source_system_id INTEGER NOT NULL,
            target_user_id INTEGER NOT NULL,
            target_system_id INTEGER NOT NULL,
            copied_at TEXT NOT NULL,
            first_trained_at TEXT,
            last_trained_at TEXT,
            UNIQUE(source_user_id, source_system_id, target_user_id, target_system_id)
        );

        CREATE INDEX IF NOT EXISTS idx_copy_events_source_trained
            ON training_system_copy_events(source_user_id, first_trained_at);

        CREATE INDEX IF NOT EXISTS idx_copy_events_target_system
            ON training_system_copy_events(target_user_id, target_system_id);

        CREATE TABLE IF NOT EXISTS user_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_user_events_user_type_created
            ON user_events(user_id, event_type, created_at DESC);
        """
    )

    if not await _column_exists(db, "user_prefs", "title_frame_code"):
        await db.execute("ALTER TABLE user_prefs ADD COLUMN title_frame_code TEXT DEFAULT NULL")
    if not await _column_exists(db, "user_prefs", "badge_code"):
        await db.execute("ALTER TABLE user_prefs ADD COLUMN badge_code TEXT DEFAULT NULL")
    if not await _column_exists(db, "user_prefs", "badge_hidden"):
        await db.execute(
            "ALTER TABLE user_prefs ADD COLUMN badge_hidden INTEGER CHECK(badge_hidden IN (0,1)) DEFAULT 0"
        )
    await db.execute(
        "UPDATE user_prefs SET badge_hidden = 0 WHERE badge_hidden IS NULL OR badge_hidden NOT IN (0,1)"
    )


async def search_catalog_exercises(query: str | None, limit: int = 50):
    pattern = f"%{(query or '').strip().lower()}%"
    async with connect_db() as db:
        base_query = (
            """
            SELECT e.id, e.name, e.muscle_group, COALESCE(u.cnt, 0) AS usage_count
            FROM exercises e
            LEFT JOIN (
                SELECT exercise_id, COUNT(*) AS cnt
                FROM user_exercises
                GROUP BY exercise_id
            ) u ON u.exercise_id = e.id
            {where_clause}
            ORDER BY usage_count DESC, e.name ASC
            LIMIT ?
            """
        )
        if query and query.strip():
            cur = await db.execute(base_query.format(where_clause="WHERE LOWER(e.name) LIKE ?"), (pattern, limit))
        else:
            cur = await db.execute(base_query.format(where_clause=""), (limit,))
        rows = await cur.fetchall()
        return [(int(r[0]), r[1], r[2]) for r in rows if r]


async def create_catalog_exercise(name: str, muscle_group: str | None = None) -> int:
    normalized_mg = muscle_group.strip().lower() if muscle_group else None
    async with connect_db() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO exercises(name, muscle_group) VALUES(?, ?)",
            (name, normalized_mg),
        )
        if cur.rowcount == 0:
            cur = await db.execute("SELECT id FROM exercises WHERE name=?", (name,))
            row = await cur.fetchone()
        else:
            row = (cur.lastrowid,)
        await db.commit()
        if not row:
            raise ValueError("Не удалось создать упражнение")
        return int(row[0])


async def _seed_exercise_muscles_defaults(db):
    mapping: dict[str, dict[str, int]] = {}

    anatomical_groups = {"chest", "back", "legs", "shoulders", "biceps", "triceps", "core"}
    for name, group in DEFAULT_EXERCISES:
        if group in anatomical_groups:
            mapping[name] = {group: 100}

    category_defaults: dict[str, dict[str, int]] = {
        "kb_cat_ballistics": {"legs": 35, "back": 20, "shoulders": 15, "core": 20, "cardio": 10},
        "kb_cat_grinds": {"shoulders": 30, "back": 20, "legs": 20, "core": 20, "biceps": 5, "triceps": 5},
        "kb_cat_squats": {"legs": 60, "core": 20, "back": 20},
        "kb_cat_carries": {"core": 35, "legs": 25, "shoulders": 20, "back": 20},
        "kb_cat_core": {"core": 80, "legs": 20},
        "kb_cat_complexes": {"legs": 30, "back": 20, "shoulders": 20, "core": 20, "biceps": 5, "triceps": 5},
    }

    for cat_code, exercise_names in KB_CATEGORY_DEFINITION:
        distribution = category_defaults.get(cat_code.lower())
        if not distribution:
            continue
        for name in exercise_names:
            mapping[name] = distribution

    for name, _ in METCON_EXERCISES:
        mapping[name] = {"cardio": 70, "legs": 15, "core": 15}

    for name, _ in WORKOUT_EXERCISES:
        mapping[name] = {"back": 35, "biceps": 20, "triceps": 15, "shoulders": 10, "core": 10, "legs": 10}

    rows_to_insert: list[tuple[int, str, int]] = []
    for name, muscles in mapping.items():
        cur = await db.execute("SELECT id FROM exercises WHERE name=?", (name,))
        row = await cur.fetchone()
        if not row:
            continue
        exercise_id = row[0]
        cur = await db.execute(
            "SELECT 1 FROM exercise_muscles WHERE exercise_id=? LIMIT 1", (exercise_id,)
        )
        if await cur.fetchone():
            continue
        rows_to_insert.extend(
            (exercise_id, muscle_code, weight_pct) for muscle_code, weight_pct in muscles.items()
        )

    if rows_to_insert:
        await db.executemany(
            "INSERT INTO exercise_muscles(exercise_id, muscle_code, weight_pct) VALUES (?,?,?)",
            rows_to_insert,
        )

# Ограничиваем число одновременных операций с базой
_db_semaphore = asyncio.BoundedSemaphore(DB_POOL_SIZE)

@asynccontextmanager
async def connect_db():
    async with _db_semaphore:
        async with aiosqlite.connect(DB_PATH) as db:
            yield db


class _DBPoolWrapper:
    @asynccontextmanager
    async def acquire(self):
        async with connect_db() as db:
            yield db


_pool = _DBPoolWrapper()


async def set_app_meta(key: str, value: str) -> None:
    async with _pool.acquire() as db:
        await db.execute(
            "INSERT INTO app_meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


async def get_app_meta(key: str) -> Optional[str]:
    async with _pool.acquire() as db:
        cur = await db.execute("SELECT value FROM app_meta WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None


# Специализации для вступительного видео
INTRO_VIDEO_KEY = "intro_video_file_id"
ONBOARDING_VIDEO_CHAT_ID_KEY = "onboarding_video_chat_id"
ONBOARDING_VIDEO_MESSAGE_ID_KEY = "onboarding_video_message_id"
ONBOARDING_INTRO_CHAT_ID_KEY = "onboarding_intro_chat_id"
ONBOARDING_INTRO_MESSAGE_ID_KEY = "onboarding_intro_message_id"

AI_COACH_DAILY_LIMIT = 3
AI_COACH_WEEKLY_LIMIT = 7
AI_COACH_MONTHLY_LIMIT = 15


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _generate_team_join_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    length = secrets.choice((6, 7, 8))
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _fetch_ai_coach_quota_state(db, user_id: int, now_utc: datetime) -> dict:
    day_cutoff = now_utc - timedelta(days=1)
    week_cutoff = now_utc - timedelta(days=7)
    month_cutoff = now_utc - timedelta(days=30)

    day_cutoff_iso = _iso_utc(day_cutoff)
    week_cutoff_iso = _iso_utc(week_cutoff)
    month_cutoff_iso = _iso_utc(month_cutoff)

    cur = await db.execute(
        """
        SELECT
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS day_count,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS week_count,
            SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS month_count
        FROM ai_coach_requests
        WHERE user_id = ?
        """,
        (day_cutoff_iso, week_cutoff_iso, month_cutoff_iso, user_id),
    )
    row = await cur.fetchone()
    day_count = int((row[0] if row and row[0] is not None else 0) or 0)
    week_count = int((row[1] if row and row[1] is not None else 0) or 0)
    month_count = int((row[2] if row and row[2] is not None else 0) or 0)

    week_reset_at: datetime | None = None
    if week_count >= AI_COACH_WEEKLY_LIMIT:
        cur = await db.execute(
            """
            SELECT created_at
            FROM ai_coach_requests
            WHERE user_id = ? AND created_at >= ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, week_cutoff_iso),
        )
        row = await cur.fetchone()
        if row and row[0]:
            first = datetime.fromisoformat(str(row[0]))
            week_reset_at = (first if first.tzinfo else first.replace(tzinfo=UTC)) + timedelta(days=7)

    month_reset_at: datetime | None = None
    if month_count >= AI_COACH_MONTHLY_LIMIT:
        cur = await db.execute(
            """
            SELECT created_at
            FROM ai_coach_requests
            WHERE user_id = ? AND created_at >= ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id, month_cutoff_iso),
        )
        row = await cur.fetchone()
        if row and row[0]:
            first = datetime.fromisoformat(str(row[0]))
            month_reset_at = (first if first.tzinfo else first.replace(tzinfo=UTC)) + timedelta(days=30)

    return {
        "limits": {
            "day": AI_COACH_DAILY_LIMIT,
            "week": AI_COACH_WEEKLY_LIMIT,
            "month": AI_COACH_MONTHLY_LIMIT,
        },
        "usage": {
            "day": day_count,
            "week": week_count,
            "month": month_count,
        },
        "remaining": {
            "day": max(0, AI_COACH_DAILY_LIMIT - day_count),
            "week": max(0, AI_COACH_WEEKLY_LIMIT - week_count),
            "month": max(0, AI_COACH_MONTHLY_LIMIT - month_count),
        },
        "weekly_reset_at": _iso_utc(week_reset_at) if week_reset_at else None,
        "monthly_reset_at": _iso_utc(month_reset_at) if month_reset_at else None,
    }


async def get_ai_coach_quota(user_id: int, now: datetime | None = None) -> dict:
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    async with _pool.acquire() as db:
        return await _fetch_ai_coach_quota_state(db, user_id, now_utc)


async def consume_ai_coach_quota(user_id: int, mode: str, now: datetime | None = None) -> dict:
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    async with _pool.acquire() as db:
        await db.execute("BEGIN IMMEDIATE")
        state = await _fetch_ai_coach_quota_state(db, user_id, now_utc)
        usage = state.get("usage") or {}

        blocked_scope: str | None = None
        reset_at: str | None = None
        if int(usage.get("month", 0)) >= AI_COACH_MONTHLY_LIMIT:
            blocked_scope = "month"
            reset_at = state.get("monthly_reset_at")
        elif int(usage.get("week", 0)) >= AI_COACH_WEEKLY_LIMIT:
            blocked_scope = "week"
            reset_at = state.get("weekly_reset_at")
        elif int(usage.get("day", 0)) >= AI_COACH_DAILY_LIMIT:
            blocked_scope = "day"

        if blocked_scope:
            await db.rollback()
            return {
                "ok": False,
                "blocked_scope": blocked_scope,
                "reset_at": reset_at,
                **state,
            }

        await db.execute(
            "INSERT INTO ai_coach_requests(user_id, mode, created_at) VALUES(?,?,?)",
            (user_id, str(mode or "unknown"), _iso_utc(now_utc)),
        )
        await db.commit()
        updated_state = await _fetch_ai_coach_quota_state(db, user_id, now_utc)
        return {
            "ok": True,
            **updated_state,
        }


async def reset_ai_coach_quota(user_id: int) -> int:
    async with _pool.acquire() as db:
        cur = await db.execute("DELETE FROM ai_coach_requests WHERE user_id=?", (user_id,))
        await db.commit()
        return int(cur.rowcount or 0)


async def set_intro_video(file_id: str) -> None:
    await set_app_meta(INTRO_VIDEO_KEY, file_id)


async def get_intro_video() -> Optional[str]:
    return await get_app_meta(INTRO_VIDEO_KEY)


async def set_onboarding_video_message(user_id: int, chat_id: int, message_id: int) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE users
            SET onboarding_video_chat_id = ?, onboarding_video_message_id = ?
            WHERE id = ?
            """,
            (chat_id, message_id, user_id),
        )
        await db.commit()


async def get_onboarding_video_message(user_id: int) -> tuple[Optional[int], Optional[int]]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT onboarding_video_chat_id, onboarding_video_message_id
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None, None
    return (row[0], row[1])


async def clear_onboarding_video_message(user_id: int) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE users
            SET onboarding_video_chat_id = NULL, onboarding_video_message_id = NULL
            WHERE id = ?
            """,
            (user_id,),
        )
        await db.commit()


async def set_onboarding_intro_message(user_id: int, chat_id: int, message_id: int) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE users
            SET onboarding_intro_chat_id = ?, onboarding_intro_message_id = ?
            WHERE id = ?
            """,
            (chat_id, message_id, user_id),
        )
        await db.commit()


async def get_onboarding_intro_message(user_id: int) -> tuple[Optional[int], Optional[int]]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT onboarding_intro_chat_id, onboarding_intro_message_id
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None, None
    return row[0], row[1]


async def clear_onboarding_intro_message(user_id: int) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE users
            SET onboarding_intro_chat_id = NULL, onboarding_intro_message_id = NULL
            WHERE id = ?
            """,
            (user_id,),
        )
        await db.commit()


async def set_onboarding_completed(user_id: int, completed: bool) -> None:
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE users
            SET onboarding_completed = ?
            WHERE id = ?
            """,
            (1 if completed else 0, user_id),
        )
        await db.commit()


async def is_onboarding_completed(user_id: int) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT onboarding_completed
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return False
    return bool(row[0])


# Глобальная статистика для /stats — всё из текущих таблиц.
async def fetch_global_stats(now_iso: str | None = None) -> dict:
    now = datetime.now(timezone.utc) if now_iso is None else datetime.fromisoformat(now_iso)
    day30 = (now - timedelta(days=30)).isoformat()
    day365 = (now - timedelta(days=365)).isoformat()

    async with connect_db() as db:
        stats: dict[str, object] = {}

        # Пользователи
        cur = await db.execute("SELECT COUNT(*) FROM users")
        stats["users_total"] = int((await cur.fetchone())[0])
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (day30,))
        stats["users_last_30d"] = int((await cur.fetchone())[0])
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (day365,))
        stats["users_last_365d"] = int((await cur.fetchone())[0])
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE COALESCE(notifications_enabled,1)=1")
        stats["users_notifications_on"] = int((await cur.fetchone())[0])

        # Подписки
        cur = await db.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active' AND expires_at >= ?", (now.isoformat(),))
        stats["subs_active"] = int((await cur.fetchone())[0])
        cur = await db.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active'")
        stats["subs_total_records_active_flag"] = int((await cur.fetchone())[0])

        # Тренировки/сеты
        cur = await db.execute("SELECT COUNT(*) FROM sessions")
        sessions_total = int((await cur.fetchone())[0])
        stats["sessions_total"] = sessions_total
        cur = await db.execute("SELECT COUNT(DISTINCT date) FROM sessions")
        days_total = int((await cur.fetchone())[0]) or 1
        stats["avg_sessions_per_day_global"] = round(sessions_total / days_total, 3)
        cur = await db.execute("SELECT COUNT(*) FROM sets")
        sets_total = int((await cur.fetchone())[0])
        stats["sets_total"] = sets_total
        cur = await db.execute("SELECT COUNT(DISTINCT session_id) FROM sets")
        set_sessions = int((await cur.fetchone())[0]) or 1
        stats["avg_sets_per_session"] = round(sets_total / set_sessions, 3)

        # Топ-упражнений по количеству сетов
        cur = await db.execute(
            """
            SELECT e.name, COUNT(*) AS c
            FROM sets s
            JOIN user_exercises ue ON ue.id = s.user_exercise_id
            JOIN exercises e ON e.id = ue.exercise_id
            GROUP BY e.name
            ORDER BY c DESC
            LIMIT 10
        """
        )
        stats["top_exercises_by_sets"] = [{"name": r[0], "sets": int(r[1])} for r in await cur.fetchall()]

        # Тренер/подопечный
        cur = await db.execute("SELECT COUNT(*) FROM trainer_links WHERE status='accepted'")
        accepted = int((await cur.fetchone())[0])
        cur = await db.execute("SELECT COUNT(*) FROM trainer_links")
        links_all = int((await cur.fetchone())[0])
        stats["trainer_links_total"] = links_all
        stats["trainer_links_accepted"] = accepted

    return stats


async def _column_exists(db, table: str, column: str) -> bool:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return any(row[1] == column for row in rows)


async def _table_exists(db, table: str) -> bool:
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    row = await cur.fetchone()
    return bool(row)


async def _has_unique_index(
    db, table: str, columns: tuple[str, ...]
) -> bool:
    cur = await db.execute(f"PRAGMA index_list({table})")
    indexes = await cur.fetchall()
    for _seq, name, unique, *_ in indexes:
        if not unique:
            continue
        cur_info = await db.execute(f"PRAGMA index_info({name})")
        info_rows = await cur_info.fetchall()
        index_columns = tuple(row[2] for row in info_rows)
        if index_columns == columns:
            return True
    return False



async def _ensure_day_completions_system_scope(db) -> None:
    cur = await db.execute("PRAGMA table_info(day_completions)")
    cols = await cur.fetchall()
    col_names = {str(row[1]) for row in cols}
    if "system_id" in col_names:
        await db.execute("UPDATE day_completions SET system_id=0 WHERE system_id IS NULL")
        return
    await db.execute("ALTER TABLE day_completions RENAME TO day_completions_old")
    await db.execute(
        """
        CREATE TABLE day_completions(
            user_id INTEGER,
            system_id INTEGER NOT NULL DEFAULT 0,
            day_index INTEGER,
            completed_at TEXT,
            PRIMARY KEY(user_id, system_id, day_index)
        )
        """
    )
    await db.execute(
        """
        INSERT INTO day_completions(user_id, system_id, day_index, completed_at)
        SELECT user_id, 0, day_index, completed_at
        FROM day_completions_old
        """
    )
    await db.execute("DROP TABLE day_completions_old")

async def _ensure_sessions_unique_by_day_and_system(db) -> None:
    desired = ("user_id", "date", "day_index", "system_id")
    if await _has_unique_index(db, "sessions", desired):
        return
    await db.execute("PRAGMA foreign_keys=OFF")
    await db.execute("BEGIN")
    try:
        await db.execute("ALTER TABLE sessions RENAME TO sessions_old")
        await db.execute(
            """
            CREATE TABLE sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                day_index INTEGER,
                system_id INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, date, day_index, system_id)
            )
            """
        )
        await db.execute(
            """
            INSERT INTO sessions(id, user_id, date, day_index, system_id)
            SELECT id, user_id, date, day_index, COALESCE(system_id, 0) FROM sessions_old
            """
        )
        await db.execute("DROP TABLE sessions_old")
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")


async def _migrate_duration_metrics(db) -> None:
    params = _duration_name_params()
    await db.execute(
        f"""
        UPDATE sets
        SET seconds = reps, reps = 0
        WHERE seconds = 0
          AND COALESCE(reps, 0) != 0
          AND user_exercise_id IN (
              SELECT ue.id
              FROM user_exercises ue
              JOIN exercises e ON e.id = ue.exercise_id
              WHERE {DURATION_NAME_SQL}
          )
        """,
        params,
    )
    await db.execute(
        f"""
        UPDATE session_exercises
        SET last_seconds = last_reps, last_reps = 0
        WHERE COALESCE(last_seconds, 0) = 0
          AND COALESCE(last_reps, 0) != 0
          AND user_exercise_id IN (
              SELECT ue.id
              FROM user_exercises ue
              JOIN exercises e ON e.id = ue.exercise_id
              WHERE {DURATION_NAME_SQL}
          )
        """,
        params,
    )
    await db.execute(
        f"""
        UPDATE exercise_baseline
        SET seconds = reps, reps = 0
        WHERE COALESCE(seconds, 0) = 0
          AND COALESCE(reps, 0) != 0
          AND exercise_id IN (
              SELECT e.id
              FROM exercises e
              WHERE {DURATION_NAME_SQL}
          )
        """,
        params,
    )


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
            workouts_per_week INTEGER,
            day_finish_total INTEGER DEFAULT 0,
            subscription_prompt_total INTEGER DEFAULT 0,
            notifications_enabled INTEGER NOT NULL DEFAULT 1,
            leaderboard_visible INTEGER NOT NULL DEFAULT 1,
            trainer_accepts_requests INTEGER NOT NULL DEFAULT 1,
            onboarding_video_chat_id INTEGER,
            onboarding_video_message_id INTEGER,
            onboarding_intro_chat_id INTEGER,
            onboarding_intro_message_id INTEGER,
            onboarding_completed INTEGER NOT NULL DEFAULT 0,
            systems_limit_prompted_at TEXT
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
            system_id INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, date, day_index, system_id)
        );

        CREATE TABLE IF NOT EXISTS sets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            user_exercise_id INTEGER,
            set_no INTEGER,
            reps INTEGER DEFAULT 0,
            seconds INTEGER DEFAULT 0,
            weight_kg REAL DEFAULT 0,
            is_warmup INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS day_completions(
            user_id INTEGER,
            system_id INTEGER NOT NULL DEFAULT 0,
            day_index INTEGER,
            completed_at TEXT,
            PRIMARY KEY(user_id, system_id, day_index)
        );

        CREATE TABLE IF NOT EXISTS day_completion_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            system_id INTEGER NOT NULL DEFAULT 0,
            day_index INTEGER NOT NULL,
            completed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS session_exercises(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            user_exercise_id INTEGER,
            is_done INTEGER DEFAULT 0,
            is_microcycle INTEGER DEFAULT 0,
            done_at TEXT,
            last_reps INTEGER,
            last_seconds INTEGER,
            last_weight REAL,
            note TEXT,
            UNIQUE(session_id, user_exercise_id)
        );

        CREATE TABLE IF NOT EXISTS exercise_baseline(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            day_index INTEGER,
            exercise_id INTEGER,
            sets INTEGER,
            reps INTEGER,
            seconds INTEGER,
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
            ui_verbose_level INTEGER CHECK(ui_verbose_level IN (0,1)) DEFAULT 0,
            suppress_webapp_prompt INTEGER CHECK(suppress_webapp_prompt IN (0,1)) DEFAULT 0,
            title_frame_code TEXT DEFAULT NULL,
            badge_code TEXT DEFAULT NULL,
            badge_hidden INTEGER CHECK(badge_hidden IN (0,1)) DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS training_system_cosmetics(
            user_id INTEGER NOT NULL,
            system_id INTEGER NOT NULL,
            title_frame_code TEXT DEFAULT NULL,
            badge_code TEXT DEFAULT NULL,
            badge_hidden INTEGER CHECK(badge_hidden IN (0,1)) DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, system_id)
        );

        CREATE TABLE IF NOT EXISTS user_measurements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            metric TEXT,
            value REAL,
            extra TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS running_entries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_exercise_id INTEGER,
            exercise_id INTEGER,
            session_id INTEGER,
            day_index INTEGER,
            distance_km REAL DEFAULT 0,
            duration_sec INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            calories INTEGER DEFAULT 0,
            heart_rate INTEGER DEFAULT 0,
            is_draft INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_measurement_custom(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT UNIQUE,
            name TEXT,
            category_code TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_measurement_categories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT UNIQUE,
            letter TEXT,
            name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_measurements_user_metric
            ON user_measurements(user_id, metric, created_at);
        CREATE INDEX IF NOT EXISTS idx_running_entries_session
            ON running_entries(session_id, user_exercise_id);
        CREATE INDEX IF NOT EXISTS idx_running_entries_user
            ON running_entries(user_id, user_exercise_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_user_measurement_custom_user
            ON user_measurement_custom(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_user_measurement_categories_user
            ON user_measurement_categories(user_id, created_at DESC);

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
            payload_json TEXT,
            external_id TEXT
        );

        CREATE TABLE IF NOT EXISTS trainer_links(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trainer_user_id INTEGER NOT NULL,
            trainee_user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            can_edit_plan INTEGER NOT NULL DEFAULT 0,
            trainer_label TEXT,
            trainee_label TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS ai_coach_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ai_coach_requests_user_created
            ON ai_coach_requests(user_id, created_at);

        CREATE TABLE IF NOT EXISTS training_systems(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            color TEXT DEFAULT '#2ea6ff',
            created_at TEXT,
            UNIQUE(user_id, name)
        );

        CREATE TABLE IF NOT EXISTS training_system_days(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            label TEXT,
            is_active INTEGER DEFAULT 1,
            UNIQUE(system_id, day_index)
        );

        CREATE TABLE IF NOT EXISTS training_systems_archive(
            system_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            color TEXT,
            deleted_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS training_system_days_archive(
            system_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            label TEXT,
            deleted_at TEXT NOT NULL,
            PRIMARY KEY(system_id, day_index)
        );

        CREATE TABLE IF NOT EXISTS training_system_exercises(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            exercise_id INTEGER NOT NULL,
            UNIQUE(system_id, day_index, exercise_id)
        );

        CREATE TABLE IF NOT EXISTS training_system_reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            day_no INTEGER NOT NULL,
            dow INTEGER NOT NULL,
            hour INTEGER NOT NULL,
            minute INTEGER NOT NULL,
            UNIQUE(system_id, day_no)
        );

        CREATE TABLE IF NOT EXISTS training_system_exercise_sources(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            day_index INTEGER NOT NULL,
            exercise_id INTEGER NOT NULL,
            source_payload TEXT NOT NULL,
            UNIQUE(system_id, day_index, exercise_id)
        );

        CREATE TABLE IF NOT EXISTS teams(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            join_code TEXT NOT NULL UNIQUE,
            is_open INTEGER NOT NULL DEFAULT 0,
            frame_code TEXT,
            bg_code TEXT,
            emblem_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS team_members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            left_at TEXT
        );

        CREATE TABLE IF NOT EXISTS team_join_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS team_achievements(
            team_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            PRIMARY KEY(team_id, code)
        );

        CREATE TABLE IF NOT EXISTS team_daily_scores(
            team_id INTEGER NOT NULL,
            day_utc TEXT NOT NULL,
            score INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            members INTEGER NOT NULL,
            sessions_7 INTEGER NOT NULL,
            sessions_28 INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(team_id, day_utc)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_team_members_active_user
            ON team_members(user_id)
            WHERE left_at IS NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_team_members_captain
            ON team_members(team_id)
            WHERE role='captain' AND left_at IS NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_team_requests_pending
            ON team_join_requests(team_id, user_id)
            WHERE status='pending';

        CREATE INDEX IF NOT EXISTS idx_team_members_team_active
            ON team_members(team_id, left_at);

        CREATE INDEX IF NOT EXISTS idx_team_requests_team_status
            ON team_join_requests(team_id, status, created_at);
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
            await db.execute("ALTER TABLE users ADD COLUMN day_finish_total INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN subscription_prompt_total INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE sets ADD COLUMN is_warmup INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE sets ADD COLUMN seconds INTEGER DEFAULT 0")
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
        if not await _column_exists(db, "user_prefs", "suppress_webapp_prompt"):
            await db.execute(
                "ALTER TABLE user_prefs ADD COLUMN suppress_webapp_prompt INTEGER CHECK(suppress_webapp_prompt IN (0,1)) DEFAULT 0"
            )
        if not await _column_exists(db, "payments", "external_id"):
            await db.execute("ALTER TABLE payments ADD COLUMN external_id TEXT")
        if not await _column_exists(db, "running_entries", "heart_rate"):
            await db.execute("ALTER TABLE running_entries ADD COLUMN heart_rate INTEGER DEFAULT 0")
        if not await _column_exists(db, "running_entries", "duration_ms"):
            await db.execute("ALTER TABLE running_entries ADD COLUMN duration_ms INTEGER DEFAULT 0")
        if not await _column_exists(db, "running_entries", "exercise_id"):
            await db.execute("ALTER TABLE running_entries ADD COLUMN exercise_id INTEGER")
            await db.execute(
                """
                UPDATE running_entries
                SET exercise_id=(
                    SELECT ue.exercise_id
                    FROM user_exercises ue
                    WHERE ue.id=running_entries.user_exercise_id
                    LIMIT 1
                )
                WHERE exercise_id IS NULL
                """
            )
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_trainer INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN trainer_code TEXT")
        except Exception:
            pass
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN notifications_enabled INTEGER NOT NULL DEFAULT 1"
            )
        except Exception:
            pass
        if not await _column_exists(db, "users", "leaderboard_visible"):
            await db.execute(
                "ALTER TABLE users ADD COLUMN leaderboard_visible INTEGER NOT NULL DEFAULT 1"
            )
        if not await _column_exists(db, "users", "trainer_accepts_requests"):
            await db.execute(
                "ALTER TABLE users ADD COLUMN trainer_accepts_requests INTEGER NOT NULL DEFAULT 1"
            )
        try:
            await db.execute(
                "UPDATE users SET trainer_accepts_requests = 1 WHERE trainer_accepts_requests IS NULL"
            )
        except Exception:
            pass
        if not await _column_exists(db, "users", "onboarding_video_chat_id"):
            await db.execute("ALTER TABLE users ADD COLUMN onboarding_video_chat_id INTEGER")
        if not await _column_exists(db, "users", "onboarding_video_message_id"):
            await db.execute("ALTER TABLE users ADD COLUMN onboarding_video_message_id INTEGER")
        if not await _column_exists(db, "users", "onboarding_intro_chat_id"):
            await db.execute("ALTER TABLE users ADD COLUMN onboarding_intro_chat_id INTEGER")
        if not await _column_exists(db, "users", "onboarding_intro_message_id"):
            await db.execute("ALTER TABLE users ADD COLUMN onboarding_intro_message_id INTEGER")
        if not await _column_exists(db, "users", "onboarding_completed"):
            await db.execute(
                "ALTER TABLE users ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0"
            )
        if not await _column_exists(db, "users", "active_system_id"):
            await db.execute("ALTER TABLE users ADD COLUMN active_system_id INTEGER")
        if not await _column_exists(db, "users", "systems_limit_prompted_at"):
            await db.execute("ALTER TABLE users ADD COLUMN systems_limit_prompted_at TEXT")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS ai_coach_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, mode TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_coach_requests_user_created ON ai_coach_requests(user_id, created_at)"
        )
        if not await _column_exists(db, "sessions", "system_id"):
            await db.execute("ALTER TABLE sessions ADD COLUMN system_id INTEGER")
        await db.execute("UPDATE sessions SET system_id=0 WHERE system_id IS NULL")
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
        try:
            await db.execute("ALTER TABLE session_exercises ADD COLUMN note TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE session_exercises ADD COLUMN last_seconds INTEGER")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE exercise_baseline ADD COLUMN seconds INTEGER")
        except Exception:
            pass
        if not await _column_exists(db, "user_measurement_custom", "category_code"):
            await db.execute(
                "ALTER TABLE user_measurement_custom ADD COLUMN category_code TEXT"
            )
        if not await _table_exists(db, "user_measurement_categories"):
            await db.execute(
                """
                CREATE TABLE user_measurement_categories(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    code TEXT UNIQUE,
                    letter TEXT,
                    name TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                "CREATE INDEX idx_user_measurement_categories_user ON user_measurement_categories(user_id, created_at DESC)"
            )
        if not await _column_exists(db, "user_reminders", "day_no"):
            await db.execute("ALTER TABLE user_reminders ADD COLUMN day_no INTEGER")
            cur = await db.execute(
                "SELECT id, user_id FROM user_reminders WHERE day_no IS NULL ORDER BY user_id, id"
            )
            rows = await cur.fetchall()
            last_user: int | None = None
            position = 0
            for row_id, user_id in rows:
                if user_id != last_user:
                    last_user = user_id
                    position = 0
                position += 1
                await db.execute(
                    "UPDATE user_reminders SET day_no=? WHERE id=?",
                    (position, row_id),
                )
            await db.commit()
        await db.commit()
        await _ensure_sessions_unique_by_day_and_system(db)
        await _ensure_day_completions_system_scope(db)
        await _migrate_duration_metrics(db)
        await _ensure_achievements_schema(db)
        await db.commit()

        await _seed_exercises(db, DEFAULT_EXERCISES)
        await _seed_exercises(db, KB_EXERCISES)
        await _seed_exercises(db, METCON_EXERCISES, update_group=False)
        await _seed_exercises(db, WORKOUT_EXERCISES, update_group=False)
        await _ensure_muscle_map_schema(db)
        await _seed_exercise_muscles_defaults(db)
        await db.commit()

def _generate_trainer_code_value() -> str:
    return "TR-" + secrets.token_hex(3).upper()


async def _generate_unique_trainer_code(db) -> str:
    while True:
        candidate = _generate_trainer_code_value()
        cur = await db.execute(
            "SELECT 1 FROM users WHERE trainer_code = ?", (candidate,)
        )
        exists = await cur.fetchone()
        if not exists:
            return candidate


async def _ensure_user_trainer_code(db, user_id: int) -> str:
    cur = await db.execute(
        "SELECT trainer_code FROM users WHERE id=?",
        (user_id,),
    )
    row = await cur.fetchone()
    if row and row[0]:
        return row[0]
    code = await _generate_unique_trainer_code(db)
    await db.execute(
        "UPDATE users SET trainer_code = ? WHERE id=?",
        (code, user_id),
    )
    await db.commit()
    return code


async def get_or_create_user(tg_id: int, username: str|None):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, trainer_code FROM users WHERE tg_id=?",
            (tg_id,),
        )
        row = await cur.fetchone()
        if row:
            user_id = row[0]
            if not row[1]:
                await _ensure_user_trainer_code(db, user_id)
            return user_id
        await db.execute(
            "INSERT INTO users(tg_id, username, created_at) VALUES(?,?,?)",
            (tg_id, username, datetime.now(UTC).isoformat())
        )
        await db.commit()
        cur = await db.execute("SELECT id FROM users WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        if not row:
            raise RuntimeError("Failed to create user")
        user_id = row[0]
        await _ensure_user_trainer_code(db, user_id)
        return user_id

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



async def ensure_training_system_defaults(user_id: int) -> int:
    now = datetime.now(UTC).isoformat()
    created_new = False
    needs_sync = False
    async with connect_db() as db:
        cur = await db.execute("SELECT id, active_system_id FROM users WHERE id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            raise RuntimeError('User not found')
        active_id = row[1]
        if active_id:
            return int(active_id)
        cur = await db.execute(
            "SELECT id FROM training_systems WHERE user_id=? ORDER BY id LIMIT 1",
            (user_id,),
        )
        existing = await cur.fetchone()
        if existing:
            system_id = int(existing[0])
            cur = await db.execute("SELECT 1 FROM training_system_days WHERE system_id=? LIMIT 1", (system_id,))
            if not await cur.fetchone():
                needs_sync = True
        else:
            cur = await db.execute(
                "INSERT INTO training_systems(user_id, name, color, created_at) VALUES(?,?,?,?)",
                (user_id, 'Своя система', '#2ea6ff', now),
            )
            system_id = int(cur.lastrowid)
            created_new = True
            needs_sync = True
        await db.execute("UPDATE users SET active_system_id=? WHERE id=?", (system_id, user_id))
        await db.commit()
    if needs_sync:
        await sync_current_plan_to_system(user_id, system_id)
        await sync_reminders_to_system(user_id, system_id)
    if created_new:
        return int(system_id)
    return int(system_id)


async def get_active_training_system_id(user_id: int) -> int:
    system_id = await ensure_training_system_defaults(user_id)
    return int(system_id)


async def list_training_systems(user_id: int):
    active_id = await get_active_training_system_id(user_id)
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, name, color FROM training_systems WHERE user_id=? ORDER BY id",
            (user_id,),
        )
        rows = await cur.fetchall()
    return [
        {
            'id': int(r[0]),
            'name': r[1],
            'color': r[2] or '#2ea6ff',
            'is_active': int(r[0]) == int(active_id),
        }
        for r in rows
    ]


async def fetch_training_system_exercise_sources(system_id: int, day_index: int) -> dict[int, dict]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT exercise_id, source_payload
            FROM training_system_exercise_sources
            WHERE system_id=? AND day_index=?
            """,
            (int(system_id), int(day_index)),
        )
        rows = await cur.fetchall()
    result: dict[int, dict] = {}
    for exercise_id, payload in rows:
        try:
            result[int(exercise_id)] = json.loads(payload or '{}')
        except Exception:
            result[int(exercise_id)] = {}
    return result


async def upsert_training_system_exercise_source(system_id: int, day_index: int, exercise_id: int, source_payload: dict):
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO training_system_exercise_sources(system_id, day_index, exercise_id, source_payload)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(system_id, day_index, exercise_id)
            DO UPDATE SET source_payload=excluded.source_payload
            """,
            (system_id, day_index, exercise_id, json.dumps(source_payload, ensure_ascii=False)),
        )
        await db.commit()


async def sync_current_plan_to_system(user_id: int, system_id: int):
    async with connect_db() as db:
        await db.execute("DELETE FROM training_system_days WHERE system_id=?", (system_id,))
        await db.execute("DELETE FROM training_system_exercises WHERE system_id=?", (system_id,))
        cur = await db.execute(
            "SELECT day_index, label, is_active FROM user_days WHERE user_id=?",
            (user_id,),
        )
        for day_index, label, is_active in await cur.fetchall():
            await db.execute(
                "INSERT INTO training_system_days(system_id, day_index, label, is_active) VALUES(?,?,?,?)",
                (system_id, int(day_index), label, int(is_active or 0)),
            )
        cur = await db.execute(
            "SELECT day_index, exercise_id FROM user_exercises WHERE user_id=? AND is_archived=0",
            (user_id,),
        )
        for day_index, exercise_id in await cur.fetchall():
            await db.execute(
                "INSERT OR IGNORE INTO training_system_exercises(system_id, day_index, exercise_id) VALUES(?,?,?)",
                (system_id, int(day_index), int(exercise_id)),
            )
        await db.commit()


async def sync_reminders_to_system(user_id: int, system_id: int):
    async with connect_db() as db:
        await db.execute("DELETE FROM training_system_reminders WHERE system_id=?", (system_id,))
        cur = await db.execute(
            "SELECT day_no, dow, hour, minute FROM user_reminders WHERE user_id=?",
            (user_id,),
        )
        for day_no, dow, hour, minute in await cur.fetchall():
            await db.execute(
                "INSERT OR REPLACE INTO training_system_reminders(system_id, day_no, dow, hour, minute) VALUES(?,?,?,?,?)",
                (system_id, int(day_no), int(dow), int(hour), int(minute)),
            )
        await db.commit()


async def apply_system_to_current_plan(user_id: int, system_id: int):
    async with connect_db() as db:
        await db.execute("UPDATE users SET active_system_id=? WHERE id=?", (system_id, user_id))
        await db.execute("DELETE FROM user_days WHERE user_id=?", (user_id,))
        await db.execute("UPDATE user_exercises SET is_archived=1 WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM user_reminders WHERE user_id=?", (user_id,))
        cur = await db.execute(
            "SELECT day_index, label, is_active FROM training_system_days WHERE system_id=? ORDER BY day_index",
            (system_id,),
        )
        days = await cur.fetchall()
        active_days_count = 0
        if days:
            for day_index, label, is_active in days:
                active_flag = int(is_active or 0)
                active_days_count += 1 if active_flag else 0
                await db.execute(
                    "INSERT INTO user_days(user_id, day_index, label, is_active) VALUES(?,?,?,?)",
                    (user_id, int(day_index), label, active_flag),
                )
        if active_days_count > 0:
            await db.execute("UPDATE users SET workouts_per_week=? WHERE id=?", (active_days_count, user_id))
        cur = await db.execute(
            "SELECT day_index, exercise_id FROM training_system_exercises WHERE system_id=?",
            (system_id,),
        )
        for day_index, exercise_id in await cur.fetchall():
            await db.execute(
                "INSERT OR IGNORE INTO user_exercises(user_id, exercise_id, day_index, is_archived) VALUES(?,?,?,0)",
                (user_id, int(exercise_id), int(day_index)),
            )
            await db.execute(
                "UPDATE user_exercises SET is_archived=0 WHERE user_id=? AND exercise_id=? AND day_index=?",
                (user_id, int(exercise_id), int(day_index)),
            )
        cur = await db.execute(
            "SELECT day_no, dow, hour, minute FROM training_system_reminders WHERE system_id=?",
            (system_id,),
        )
        for day_no, dow, hour, minute in await cur.fetchall():
            await db.execute(
                "INSERT INTO user_reminders(user_id, dow, hour, minute, day_no) VALUES(?,?,?,?,?)",
                (user_id, int(dow), int(hour), int(minute), int(day_no)),
            )
        await db.commit()


async def create_training_system(
    user_id: int,
    name: str,
    color: str = '#2ea6ff',
    workouts_per_week: int | None = None,
):
    system_name = (name or '').strip() or 'Новая система'
    now = datetime.now(UTC).isoformat()
    default_days = max(1, min(7, int(workouts_per_week or 0) or 3))
    async with connect_db() as db:
        cur = await db.execute(
            "INSERT INTO training_systems(user_id, name, color, created_at) VALUES(?,?,?,?)",
            (user_id, system_name, color, now),
        )
        system_id = int(cur.lastrowid)
        for day_index in range(1, 8):
            await db.execute(
                "INSERT INTO training_system_days(system_id, day_index, label, is_active) VALUES(?,?,?,?)",
                (system_id, day_index, f"День {day_index}", 1 if day_index <= default_days else 0),
            )
        await db.commit()
    return system_id


async def rename_training_system(user_id: int, system_id: int, name: str):
    async with connect_db() as db:
        await db.execute(
            "UPDATE training_systems SET name=? WHERE id=? AND user_id=?",
            ((name or '').strip() or 'Система', system_id, user_id),
        )
        await db.commit()


async def set_training_system_color(user_id: int, system_id: int, color: str):
    async with connect_db() as db:
        await db.execute(
            "UPDATE training_systems SET color=? WHERE id=? AND user_id=?",
            ((color or '#2ea6ff').strip(), system_id, user_id),
        )
        await db.commit()


async def delete_training_system(user_id: int, system_id: int):
    active_id = await get_active_training_system_id(user_id)
    deleted_at = datetime.now(UTC).isoformat()
    async with connect_db() as db:
        cur = await db.execute("SELECT COUNT(*) FROM training_systems WHERE user_id=?", (user_id,))
        total = int((await cur.fetchone())[0] or 0)
        if total <= 1:
            return False
        await db.execute(
            """
            INSERT INTO training_systems_archive(system_id, user_id, name, color, deleted_at)
            SELECT id, user_id, name, color, ?
            FROM training_systems
            WHERE id=? AND user_id=?
            ON CONFLICT(system_id) DO UPDATE SET
                user_id=excluded.user_id,
                name=excluded.name,
                color=excluded.color,
                deleted_at=excluded.deleted_at
            """,
            (deleted_at, system_id, user_id),
        )
        await db.execute(
            """
            INSERT INTO training_system_days_archive(system_id, day_index, label, deleted_at)
            SELECT d.system_id, d.day_index, d.label, ?
            FROM training_system_days d
            JOIN training_systems s ON s.id=d.system_id
            WHERE d.system_id=? AND s.user_id=?
            ON CONFLICT(system_id, day_index) DO UPDATE SET
                label=excluded.label,
                deleted_at=excluded.deleted_at
            """,
            (deleted_at, system_id, user_id),
        )
        await db.execute("DELETE FROM training_system_reminders WHERE system_id=?", (system_id,))
        await db.execute("DELETE FROM training_system_exercises WHERE system_id=?", (system_id,))
        await db.execute("DELETE FROM training_system_days WHERE system_id=?", (system_id,))
        await db.execute("DELETE FROM training_systems WHERE id=? AND user_id=?", (system_id, user_id))
        if int(active_id) == int(system_id):
            cur = await db.execute("SELECT id FROM training_systems WHERE user_id=? ORDER BY id LIMIT 1", (user_id,))
            row = await cur.fetchone()
            if row:
                await db.execute("UPDATE users SET active_system_id=? WHERE id=?", (int(row[0]), user_id))
        await db.commit()
    return True



async def count_user_training_systems(user_id: int) -> int:
    async with connect_db() as db:
        cur = await db.execute("SELECT COUNT(*) FROM training_systems WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return int(row[0] or 0) if row else 0


async def list_user_training_system_ids(user_id: int) -> list[int]:
    async with connect_db() as db:
        cur = await db.execute("SELECT id FROM training_systems WHERE user_id=? ORDER BY id", (user_id,))
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]


async def prune_user_training_systems(user_id: int, keep_system_id: int) -> None:
    keep_system_id = int(keep_system_id)
    async with connect_db() as db:
        cur = await db.execute("SELECT id FROM training_systems WHERE user_id=? AND id<>?", (user_id, keep_system_id))
        rows = await cur.fetchall()
        remove_ids = [int(r[0]) for r in rows]
        if not remove_ids:
            await db.execute("UPDATE users SET active_system_id=?, systems_limit_prompted_at=NULL WHERE id=?", (keep_system_id, user_id))
            await db.commit()
            return
        placeholders = ','.join('?' for _ in remove_ids)
        params = tuple(remove_ids)
        await db.execute(f"DELETE FROM training_system_reminders WHERE system_id IN ({placeholders})", params)
        await db.execute(f"DELETE FROM training_system_exercises WHERE system_id IN ({placeholders})", params)
        await db.execute(f"DELETE FROM training_system_days WHERE system_id IN ({placeholders})", params)
        await db.execute(f"DELETE FROM training_systems WHERE id IN ({placeholders})", params)
        await db.execute("UPDATE users SET active_system_id=?, systems_limit_prompted_at=NULL WHERE id=?", (keep_system_id, user_id))
        await db.commit()


async def get_systems_limit_prompted_at(user_id: int) -> datetime | None:
    async with connect_db() as db:
        cur = await db.execute("SELECT systems_limit_prompted_at FROM users WHERE id=?", (user_id,))
        row = await cur.fetchone()
        if not row or not row[0]:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except Exception:
            return None


async def set_systems_limit_prompted_at(user_id: int, dt: datetime | None) -> None:
    value = dt.isoformat() if dt else None
    async with connect_db() as db:
        await db.execute("UPDATE users SET systems_limit_prompted_at=? WHERE id=?", (value, user_id))
        await db.commit()

async def get_or_create_today_session(
    user_id: int, date_str: str, day_index: int = 1, system_id: int | None = None
):
    async with connect_db() as db:
        resolved_system_id = int(system_id) if system_id is not None else 0
        cur = await db.execute(
            "SELECT id FROM sessions WHERE user_id=? AND date=? AND day_index=? AND system_id=?",
            (user_id, date_str, day_index, resolved_system_id),
        )
        row = await cur.fetchone()
        if row:
            return row[0]
        await db.execute(
            "INSERT INTO sessions(user_id, date, day_index, system_id) VALUES(?,?,?,?)",
            (user_id, date_str, day_index, resolved_system_id),
        )
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        return (await cur.fetchone())[0]

async def get_session_for_day(
    user_id: int, date_str: str, day_index: int, system_id: int | None = None
) -> int | None:
    resolved_system_id = int(system_id) if system_id is not None else 0
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id FROM sessions WHERE user_id=? AND date=? AND day_index=? AND system_id=?",
            (user_id, date_str, day_index, resolved_system_id),
        )
        row = await cur.fetchone()
        return row[0] if row else None

async def fetch_day_exercises(
    user_id: int,
    day_index: int = 1,
    date_str: str | None = None,
    system_id: int | None = 0,
):
    date_str = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
    resolved_system_id = 0 if system_id is None else int(system_id)
    async with connect_db() as db:
        cur = await db.execute(
            """
        SELECT ue.id, e.name, e.muscle_group, IFNULL(se.is_done,0), ue.exercise_id
        FROM user_exercises ue
        JOIN exercises e ON e.id = ue.exercise_id
        LEFT JOIN sessions s
          ON s.user_id=ue.user_id
         AND s.date=?
         AND s.day_index=ue.day_index
         AND s.system_id=?
        LEFT JOIN session_exercises se ON se.session_id=s.id AND se.user_exercise_id=ue.id
        WHERE ue.user_id=? AND ue.day_index=? AND ue.is_archived=0
        ORDER BY ue.id
        """,
            (date_str, resolved_system_id, user_id, day_index),
        )
        return await cur.fetchall()


async def get_latest_set_values_for_exercise(
    user_id: int,
    user_exercise_id: int,
    exclude_session_id: int | None = None,
):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT exercise_id FROM user_exercises WHERE id=? AND user_id=?",
            (user_exercise_id, user_id),
        )
        ex_row = await cur.fetchone()
        if not ex_row:
            return None
        exercise_id = int(ex_row[0])
        params: tuple[object, ...] = (user_id, exercise_id)
        exclude_clause = ""
        if exclude_session_id is not None:
            exclude_clause = " AND s.id<>?"
            params = (user_id, exercise_id, int(exclude_session_id))
        cur = await db.execute(
            f"""
            SELECT st.reps, st.seconds, st.weight_kg
            FROM sessions s
            JOIN sets st ON st.session_id=s.id
            JOIN user_exercises ue ON ue.id=st.user_exercise_id
            WHERE s.user_id=? AND ue.exercise_id=? {exclude_clause}
            ORDER BY s.date DESC, s.id DESC, st.set_no DESC
            LIMIT 1
            """,
            params,
        )
        row = await cur.fetchone()
        if not row:
            return None
        return int(row[0] or 0), int(row[1] or 0), float(row[2] or 0.0)

async def fetch_sets_table(session_id: int):
    async with connect_db() as db:
        cur = await db.execute("""
        SELECT sets.id, sets.user_exercise_id, sets.set_no, sets.reps, sets.seconds, sets.weight_kg, e.name
        FROM sets
        JOIN user_exercises ue ON ue.id = sets.user_exercise_id
        JOIN exercises e ON e.id = ue.exercise_id
        WHERE sets.session_id=?
        ORDER BY e.name, sets.set_no
        """, (session_id,))
        rows = await cur.fetchall()
        return rows


async def _upsert_session_defaults(
    db, session_id: int, user_ex_id: int, reps: int | float, seconds: int | float, weight: float
):
    await db.execute(
        """
        INSERT INTO session_exercises(
            session_id, user_exercise_id, is_done, is_microcycle, done_at, last_reps, last_seconds, last_weight
        )
        VALUES(?,?,0,0,NULL,?,?,?)
        ON CONFLICT(session_id, user_exercise_id)
        DO UPDATE SET
            last_reps=excluded.last_reps,
            last_seconds=excluded.last_seconds,
            last_weight=excluded.last_weight
        """,
        (session_id, user_ex_id, int(reps), int(seconds), float(weight)),
    )


async def _refresh_session_defaults(db, session_id: int, user_ex_id: int):
    cur = await db.execute(
        """
        SELECT reps, seconds, weight_kg
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
            SELECT reps, seconds, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=?
            ORDER BY set_no DESC
            LIMIT 1
            """,
            (session_id, user_ex_id),
        )
        row = await cur.fetchone()
    if row:
        await _upsert_session_defaults(db, session_id, user_ex_id, row[0], row[1], row[2])


async def get_session_last_values(
    session_id: int, user_ex_id: int
) -> tuple[int, int, float] | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT last_reps, last_seconds, last_weight
            FROM session_exercises
            WHERE session_id=? AND user_exercise_id=?
            """,
            (session_id, user_ex_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        reps_val = int(row[0]) if row[0] is not None else 0
        seconds_val = int(row[1]) if row[1] is not None else 0
        weight_val = float(row[2]) if row[2] is not None else 0.0
        if row[0] is None and row[1] is None and row[2] is None:
            return None
        return reps_val, seconds_val, weight_val

async def inc_last_set(user_ex_id: int, session_id: int, field: str, delta: float):
    assert field in ("reps", "seconds", "weight_kg")
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, reps, seconds, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=?
            ORDER BY set_no DESC
            """,
            (session_id, user_ex_id),
        )
        rows = await cur.fetchall()
        if not rows:
            await db.execute(
                """
                INSERT INTO sets(session_id, user_exercise_id, set_no, reps, seconds, weight_kg, is_warmup)
                VALUES(?,?,?,?,?,?,0)
                """,
                (session_id, user_ex_id, 1, 0, 0, 0.0),
            )
            await db.commit()
            return await inc_last_set(user_ex_id, session_id, field, delta)
        if field == "reps":
            current = rows[0][1]
            new_val = max(int(current + delta), 0)
        elif field == "seconds":
            current = rows[0][2]
            new_val = max(int(current + delta), 0)
        else:
            current = rows[0][3]
            new_val = max(float(current + delta), 0.0)
        await db.executemany(
            f"UPDATE sets SET {field}=? WHERE id=?",
            [(new_val, r[0]) for r in rows],
        )
        reps_val = new_val if field == "reps" else rows[0][1]
        seconds_val = new_val if field == "seconds" else rows[0][2]
        weight_val = new_val if field == "weight_kg" else rows[0][3]
        await _upsert_session_defaults(db, session_id, user_ex_id, reps_val, seconds_val, weight_val)
        await db.commit()

async def apply_sets_template(
    session_id: int,
    user_ex_id: int,
    template: Sequence[tuple[int | float | None, int | float | None, int | float | None]],
):
    async with connect_db() as db:
        await db.execute(
            "DELETE FROM sets WHERE session_id=? AND user_exercise_id=?",
            (session_id, user_ex_id),
        )
        rows = []
        for idx, (reps, seconds, weight) in enumerate(template, start=1):
            reps_val = int(reps) if reps is not None else 0
            seconds_val = int(seconds) if seconds is not None else 0
            weight_val = float(weight) if weight is not None else 0.0
            rows.append(
                (
                    session_id,
                    user_ex_id,
                    idx,
                    max(reps_val, 0),
                    max(seconds_val, 0),
                    max(weight_val, 0.0),
                )
            )
        if rows:
            await db.executemany(
                """
                INSERT INTO sets(session_id, user_exercise_id, set_no, reps, seconds, weight_kg, is_warmup)
                VALUES(?,?,?,?,?,?,0)
                """,
                rows,
            )
            last = rows[-1]
            await _upsert_session_defaults(db, session_id, user_ex_id, last[3], last[4], last[5])
        else:
            await _refresh_session_defaults(db, session_id, user_ex_id)
        await db.commit()

async def inc_specific_set(user_ex_id: int, session_id: int, set_no: int, field: str, delta: float):
    assert field in ("reps", "seconds", "weight_kg")
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, reps, seconds, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=? AND set_no=?
            LIMIT 1
            """,
            (session_id, user_ex_id, set_no),
        )
        row = await cur.fetchone()
        if not row:
            return
        set_id, reps, seconds, weight = row
        if field == "reps":
            new_val = max(int(reps + delta), 0)
            await db.execute("UPDATE sets SET reps=? WHERE id=?", (new_val, set_id))
        elif field == "seconds":
            new_val = max(int(seconds + delta), 0)
            await db.execute("UPDATE sets SET seconds=? WHERE id=?", (new_val, set_id))
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

async def set_workouts_per_week(user_id: int, n: int) -> list[tuple[int, int, int, int]]:
    """Update workouts per week and deactivate surplus days.

    Returns:
        A list of reminders that were removed because their day number is now
        inactive. Each entry contains ``(day_no, dow, hour, minute)``.
    """

    async with connect_db() as db:
        await db.execute("UPDATE users SET workouts_per_week=? WHERE id=?", (n, user_id))
        removed_days: list[int] = []
        for i in range(1, 8):
            label = f"День {i}"
            is_active = 1 if i <= n else 0
            if not is_active:
                removed_days.append(i)
            await db.execute(
                """
                INSERT INTO user_days(user_id, day_index, label, is_active) VALUES(?,?,?,?)
                ON CONFLICT(user_id, day_index) DO UPDATE SET is_active=excluded.is_active
                """,
                (user_id, i, label, is_active),
            )

        removed_ue_ids: list[int] = []
        if removed_days:
            placeholders = ",".join("?" for _ in removed_days)
            day_params: tuple = tuple(removed_days)
            cur = await db.execute(
                f"SELECT id FROM user_exercises WHERE user_id=? AND day_index IN ({placeholders}) AND is_archived=0",
                (user_id, *day_params),
            )
            removed_ue_ids = [int(r[0]) for r in await cur.fetchall() if r and r[0] is not None]
            await db.execute(
                f"UPDATE user_exercises SET is_archived=1 WHERE user_id=? AND day_index IN ({placeholders}) AND is_archived=0",
                (user_id, *day_params),
            )
            await db.execute(
                f"DELETE FROM exercise_baseline WHERE user_id=? AND day_index IN ({placeholders})",
                (user_id, *day_params),
            )
            # Историю (sets/running_entries/sessions/day_completion_history) не удаляем,
            # сохраняем статистику навсегда.
        if removed_ue_ids:
            ue_placeholders = ",".join("?" for _ in removed_ue_ids)
            await db.execute(
                f"DELETE FROM session_exercises WHERE user_exercise_id IN ({ue_placeholders})",
                tuple(removed_ue_ids),
            )
        await db.commit()

        removed: list[tuple[int, int, int, int]] = []
        cur = await db.execute(
            """
            SELECT id, day_no, dow, hour, minute
            FROM user_reminders
            WHERE user_id=?
            ORDER BY COALESCE(day_no, id)
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        next_fallback = 1
        to_delete: list[int] = []
        for row_id, day_no, dow, hour, minute in rows:
            actual_day = int(day_no) if day_no is not None else next_fallback
            if actual_day > n:
                to_delete.append(int(row_id))
                norm_dow = int(dow) if dow is not None else -1
                if dow is not None and not 0 <= norm_dow <= 6:
                    norm_dow = normalize_dow(dow)
                removed.append((actual_day, norm_dow, int(hour), int(minute)))
            next_fallback = max(next_fallback, actual_day + 1)
        if to_delete:
            await db.executemany(
                "DELETE FROM user_reminders WHERE id=?",
                ((row_id,) for row_id in to_delete),
            )
            await db.commit()
        return removed

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
            "SELECT 1 FROM user_muscle_groups WHERE id=? AND user_id=?",
            (group_id, user_id),
        )
        if not await cur.fetchone():
            return False
        cur = await db.execute(
            "SELECT id FROM exercises WHERE muscle_group=?",
            (code,),
        )
        exercise_ids = [int(r[0]) for r in await cur.fetchall() if r and r[0] is not None]
        if exercise_ids:
            placeholders = ",".join("?" for _ in exercise_ids)
            cur = await db.execute(
                f"SELECT id FROM user_exercises WHERE exercise_id IN ({placeholders})",
                tuple(exercise_ids),
            )
            ue_ids = [int(r[0]) for r in await cur.fetchall() if r and r[0] is not None]
            if ue_ids:
                ue_placeholders = ",".join("?" for _ in ue_ids)
                await db.execute(
                    f"DELETE FROM running_entries WHERE user_exercise_id IN ({ue_placeholders})",
                    tuple(ue_ids),
                )
                await db.execute(
                    f"DELETE FROM sets WHERE user_exercise_id IN ({ue_placeholders})",
                    tuple(ue_ids),
                )
                await db.execute(
                    f"DELETE FROM session_exercises WHERE user_exercise_id IN ({ue_placeholders})",
                    tuple(ue_ids),
                )
            await db.execute(
                f"DELETE FROM exercise_baseline WHERE exercise_id IN ({placeholders})",
                tuple(exercise_ids),
            )
            await db.execute(
                f"DELETE FROM user_exercise_muscles WHERE exercise_id IN ({placeholders})",
                tuple(exercise_ids),
            )
            await db.execute(
                f"DELETE FROM exercise_muscles WHERE exercise_id IN ({placeholders})",
                tuple(exercise_ids),
            )
            await db.execute(
                f"DELETE FROM user_exercises WHERE exercise_id IN ({placeholders})",
                tuple(exercise_ids),
            )
            await db.execute(
                f"DELETE FROM exercises WHERE id IN ({placeholders})",
                tuple(exercise_ids),
            )
        cur = await db.execute(
            "DELETE FROM user_muscle_groups WHERE id=? AND user_id=?",
            (group_id, user_id),
        )
        removed = cur.rowcount > 0
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
            """
            SELECT exercise_id, sets, reps, seconds, weight_kg
            FROM exercise_baseline
            WHERE user_id=? AND day_index=?
            """,
            (user_id, src_day),
        )
        rows = await cur.fetchall()
        for d in range(1, days + 1):
            if d == src_day:
                continue
            for ex_id, sets, reps, seconds, weight in rows:
                await db.execute(
                    """
                    INSERT INTO exercise_baseline(user_id, day_index, exercise_id, sets, reps, seconds, weight_kg)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(user_id, day_index, exercise_id)
                    DO UPDATE SET
                        sets=excluded.sets,
                        reps=excluded.reps,
                        seconds=excluded.seconds,
                        weight_kg=excluded.weight_kg
                    """,
                    (user_id, d, ex_id, sets, reps, seconds, weight),
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


async def list_user_library_groups(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT DISTINCT e.id, e.muscle_group, e.name
            FROM user_exercises ue
            JOIN exercises e ON e.id=ue.exercise_id
            WHERE ue.user_id=?
              AND (
                EXISTS(
                  SELECT 1
                  FROM sets st
                  JOIN sessions s ON s.id=st.session_id
                  JOIN user_exercises ue_hist ON ue_hist.id=st.user_exercise_id
                  WHERE s.user_id=? AND ue_hist.exercise_id=e.id AND st.is_warmup=0
                )
                OR EXISTS(
                  SELECT 1
                  FROM running_entries re
                  WHERE re.user_id=? AND re.exercise_id=e.id AND re.is_draft=0
                )
              )
            """,
            (user_id, user_id, user_id),
        )
        rows = await cur.fetchall()

    counters: dict[str, int] = {}
    for _ex_id, group, name in rows:
        code = (group or "").strip().lower()
        resolved = "metcon" if name in METCON_EXERCISE_NAMES else (code or "none")
        counters[resolved] = counters.get(resolved, 0) + 1
    return counters


async def list_user_group_exercises(user_id: int, group_code: str, query: str | None = None):
    conditions = ["ue.user_id=?"]
    params: list = [user_id]
    if group_code == "none":
        conditions.append("(e.muscle_group IS NULL OR TRIM(e.muscle_group)='')")
    elif group_code == "metcon" and METCON_SHARED_NAMES:
        placeholders = ",".join("?" for _ in METCON_SHARED_NAMES)
        conditions.append("(e.muscle_group=? OR e.name IN (" + placeholders + "))")
        params.append(group_code)
        params.extend(METCON_SHARED_NAMES)
    else:
        conditions.append("e.muscle_group=?")
        params.append(group_code)

    if query:
        conditions.append("LOWER(e.name) LIKE ?")
        params.append(f"%{query.lower()}%")

    conditions.append(
        """
        (
            EXISTS(
                SELECT 1
                FROM sets st
                JOIN sessions s ON s.id=st.session_id
                JOIN user_exercises ue_hist ON ue_hist.id=st.user_exercise_id
                WHERE s.user_id=ue.user_id AND ue_hist.exercise_id=e.id AND st.is_warmup=0
            )
            OR EXISTS(
                SELECT 1
                FROM running_entries re
                WHERE re.user_id=ue.user_id AND re.exercise_id=e.id AND re.is_draft=0
            )
        )
        """.strip()
    )

    where_clause = " AND ".join(conditions)
    async with connect_db() as db:
        cur = await db.execute(
            f"""
            SELECT DISTINCT e.id, e.name, e.muscle_group,
                   EXISTS(SELECT 1 FROM user_exercise_muscles uem WHERE uem.user_id=ue.user_id AND uem.exercise_id=e.id) AS has_override
            FROM user_exercises ue
            JOIN exercises e ON e.id=ue.exercise_id
            WHERE {where_clause}
            ORDER BY e.name
            """,
            tuple(params),
        )
        return await cur.fetchall()


async def fetch_exercise_history_points(user_id: int, exercise_id: int, start_date: str | None, end_date: str):
    params: list = [user_id, exercise_id, end_date]
    date_clause = ""
    if start_date:
        date_clause = "AND s.date>=?"
        params.append(start_date)

    async with connect_db() as db:
        cur = await db.execute(
            f"""
            SELECT
                s.id AS session_id,
                s.date,
                s.system_id,
                COALESCE(ts.name, tsa.name) AS system_name,
                COALESCE(ts.color, tsa.color) AS system_color,
                s.day_index,
                COALESCE(tsd.label, tsda.label) AS day_label,
                st.set_no,
                st.reps,
                st.seconds,
                st.weight_kg
            FROM sets st
            JOIN sessions s ON s.id = st.session_id
            JOIN user_exercises ue ON ue.id = st.user_exercise_id
            LEFT JOIN training_systems ts ON ts.id = s.system_id AND ts.user_id = s.user_id
            LEFT JOIN training_systems_archive tsa ON tsa.system_id = s.system_id AND tsa.user_id = s.user_id
            LEFT JOIN training_system_days tsd ON tsd.system_id = s.system_id AND tsd.day_index = s.day_index
            LEFT JOIN training_system_days_archive tsda ON tsda.system_id = s.system_id AND tsda.day_index = s.day_index
            WHERE s.user_id=? AND ue.exercise_id=? AND st.is_warmup=0 AND s.date<=? {date_clause}
            ORDER BY s.date, session_id, st.set_no
            """,
            tuple(params),
        )
        return await cur.fetchall()


async def fetch_last_exercise_session(user_id: int, exercise_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT s.id
            FROM sessions s
            JOIN sets st ON st.session_id=s.id AND st.is_warmup=0
            JOIN user_exercises ue ON ue.id=st.user_exercise_id
            WHERE s.user_id=? AND ue.exercise_id=?
            ORDER BY s.date DESC, s.id DESC
            LIMIT 1
            """,
            (user_id, exercise_id),
        )
        row = await cur.fetchone()
        if not row:
            return None, None, None, None, None, None, None, []
        session_id = int(row[0])
        cur = await db.execute(
            """
            SELECT
                s.date,
                s.system_id,
                COALESCE(ts.name, tsa.name) AS system_name,
                COALESCE(ts.color, tsa.color) AS system_color,
                s.day_index,
                COALESCE(tsd.label, tsda.label) AS day_label
            FROM sessions s
            LEFT JOIN training_systems ts ON ts.id = s.system_id AND ts.user_id = s.user_id
            LEFT JOIN training_systems_archive tsa ON tsa.system_id = s.system_id AND tsa.user_id = s.user_id
            LEFT JOIN training_system_days tsd ON tsd.system_id = s.system_id AND tsd.day_index = s.day_index
            LEFT JOIN training_system_days_archive tsda ON tsda.system_id = s.system_id AND tsda.day_index = s.day_index
            WHERE s.id=? AND s.user_id=?
            LIMIT 1
            """,
            (session_id, user_id),
        )
        context = await cur.fetchone()
        if context:
            session_date, system_id, system_name, system_color, day_index, day_label = context
        else:
            session_date, system_id, system_name, system_color, day_index, day_label = (None, None, None, None, None, None)
        cur = await db.execute(
            """
            SELECT set_no, reps, seconds, weight_kg
            FROM sets
            WHERE session_id=? AND is_warmup=0 AND user_exercise_id IN (
                SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=?
            )
            ORDER BY set_no
            """,
            (session_id, user_id, exercise_id),
        )
        sets = await cur.fetchall()
        return session_id, session_date, system_id, system_name, system_color, day_index, day_label, sets


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

async def set_baseline(
    user_id: int, day_index: int, exercise_id: int, sets: int, reps: int, seconds: int, weight: float
):
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO exercise_baseline(user_id, day_index, exercise_id, sets, reps, seconds, weight_kg)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(user_id, day_index, exercise_id)
            DO UPDATE SET
                sets=excluded.sets,
                reps=excluded.reps,
                seconds=excluded.seconds,
                weight_kg=excluded.weight_kg
            """,
            (user_id, day_index, exercise_id, sets, reps, seconds, weight),
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


async def get_user_notifications_enabled(user_id: int) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COALESCE(notifications_enabled, 1) FROM users WHERE id=?",
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return True
        try:
            return bool(int(row[0]))
        except (TypeError, ValueError):
            return True


async def set_user_notifications_enabled(user_id: int, enabled: bool) -> None:
    async with connect_db() as db:
        await db.execute(
            "UPDATE users SET notifications_enabled=? WHERE id=?",
            (1 if enabled else 0, user_id),
        )
        await db.commit()

async def get_user_leaderboard_visible(user_id: int) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COALESCE(leaderboard_visible, 1) FROM users WHERE id=?",
            (user_id,),
        )
        row = await cur.fetchone()
        return bool((row[0] if row else 1) or 0)


async def set_user_leaderboard_visible(user_id: int, visible: bool) -> None:
    async with connect_db() as db:
        await db.execute(
            "UPDATE users SET leaderboard_visible=? WHERE id=?",
            (1 if visible else 0, user_id),
        )
        await db.commit()


async def add_user_reminder(
    user_id: int, dow: int, hour: int, minute: int, day_no: int | None = None
) -> bool:
    try:
        converted_dow = int(dow)
    except (TypeError, ValueError):
        return False
    if not 0 <= converted_dow <= 6:
        return False
    dow = converted_dow

    async with connect_db() as db:
        if day_no is None:
            cur = await db.execute(
                "SELECT COALESCE(MAX(day_no), 0) FROM user_reminders WHERE user_id=?",
                (user_id,),
            )
            row = await cur.fetchone()
            day_no = int(row[0] or 0) + 1
        await db.execute(
            "DELETE FROM user_reminders WHERE user_id=? AND day_no=?",
            (user_id, day_no),
        )
        await db.execute(
            "INSERT INTO user_reminders(user_id, day_no, dow, hour, minute) VALUES(?,?,?,?,?)",
            (user_id, day_no, dow, hour, minute),
        )
        await db.commit()
    return True


async def list_user_reminders(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, day_no, dow, hour, minute
            FROM user_reminders
            WHERE user_id=?
            ORDER BY COALESCE(day_no, id)
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        cur = await db.execute(
            "SELECT day_index FROM user_days WHERE user_id=? AND is_active=1",
            (user_id,),
        )
        active_rows = await cur.fetchall()
        active_days = {int(row[0]) for row in active_rows}
        result: list[tuple[int, int, int, int]] = []
        next_fallback = 1
        to_delete: list[int] = []
        for row_id, day_no, dow, hour, minute in rows:
            day_idx = int(day_no) if day_no is not None else next_fallback
            next_fallback = max(next_fallback, day_idx + 1)
            if active_days and day_idx not in active_days:
                to_delete.append(int(row_id))
                continue
            dow_int = int(dow) if dow is not None else -1
            if dow is not None and not 0 <= dow_int <= 6:
                dow_int = normalize_dow(dow)
            hour_int = int(hour) if hour is not None else 0
            minute_int = int(minute) if minute is not None else 0
            result.append((day_idx, dow_int, hour_int, minute_int))
        if to_delete:
            await db.executemany(
                "DELETE FROM user_reminders WHERE id=?",
                ((row_id,) for row_id in to_delete),
            )
        await db.commit()
    return result


async def clear_user_reminders(user_id: int):
    async with connect_db() as db:
        await db.execute("DELETE FROM user_reminders WHERE user_id=?", (user_id,))
        await db.commit()


async def wipe_user(user_id: int):
    async with connect_db() as db:
        await db.execute("BEGIN")
        try:
            await db.execute("DELETE FROM running_entries WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM session_exercises WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)", (user_id,))
            await db.execute("DELETE FROM session_exercises WHERE user_exercise_id IN (SELECT id FROM user_exercises WHERE user_id=?)", (user_id,))
            await db.execute("DELETE FROM sets WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)", (user_id,))
            await db.execute("DELETE FROM sets WHERE user_exercise_id IN (SELECT id FROM user_exercises WHERE user_id=?)", (user_id,))
            await db.execute("DELETE FROM day_completions WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM exercise_baseline WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM user_measurements WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM user_measurement_custom WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM user_measurement_categories WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM user_muscle_groups WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM user_reminders WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM user_prefs WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM subscriptions WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM payments WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM trainer_links WHERE trainee_user_id=? OR trainer_user_id=?", (user_id, user_id))
            await db.execute("DELETE FROM user_days WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM user_exercises WHERE user_id=?", (user_id,))
            await db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            await db.execute(
                """
                UPDATE users
                SET
                    tz='UTC',
                    workouts_per_week=NULL,
                    day_finish_total=0,
                    subscription_prompt_total=0,
                    notifications_enabled=1,
                    leaderboard_visible=1,
                    is_trainer=0,
                    onboarding_video_chat_id=NULL,
                    onboarding_video_message_id=NULL,
                    onboarding_intro_chat_id=NULL,
                    onboarding_intro_message_id=NULL,
                    onboarding_completed=0
                WHERE id=?
                """,
                (user_id,),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def list_users_with_reminders():
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT r.user_id, u.tg_id, COALESCE(r.day_no, r.id) AS day_no, r.dow, r.hour, r.minute "
            "FROM user_reminders r "
            "JOIN users u ON u.id = r.user_id "
            "WHERE COALESCE(u.notifications_enabled, 1) = 1 "
            "ORDER BY r.user_id, COALESCE(r.day_no, r.id)"
        )
        return await cur.fetchall()


async def list_all_user_tg_ids():
    async with connect_db() as db:
        cur = await db.execute("SELECT tg_id FROM users WHERE tg_id IS NOT NULL")
        rows = await cur.fetchall()
        return [row[0] for row in rows]


async def count_active_subscriptions() -> int:
    now_iso = datetime.now(UTC).isoformat()
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status='active' AND expires_at >= ?",
            (now_iso,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def cleanup_expired_subscriptions(user_id: int | None = None):
    now_iso = datetime.now(UTC).isoformat()
    async with connect_db() as db:
        if user_id is None:
            await db.execute(
                "UPDATE subscriptions SET status='expired' WHERE status='active' AND expires_at <= ?",
                (now_iso,),
            )
        else:
            await db.execute(
                "UPDATE subscriptions SET status='expired' WHERE user_id=? AND status='active' AND expires_at <= ?",
                (user_id, now_iso),
            )
        await db.commit()


async def get_active_subscription(user_id: int) -> dict | None:
    await cleanup_expired_subscriptions(user_id)
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT plan, started_at, expires_at
            FROM subscriptions
            WHERE user_id=? AND status='active'
            ORDER BY expires_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        plan, started_at, expires_at = row
        started = datetime.fromisoformat(started_at) if started_at else None
        expires = datetime.fromisoformat(expires_at) if expires_at else None
        return {
            "plan": plan,
            "started_at": started,
            "expires_at": expires,
        }


async def get_latest_subscription(user_id: int) -> dict | None:
    await cleanup_expired_subscriptions(user_id)
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT plan, started_at, expires_at, status
            FROM subscriptions
            WHERE user_id=?
            ORDER BY expires_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        plan, started_at, expires_at, status = row
        started = datetime.fromisoformat(started_at) if started_at else None
        expires = datetime.fromisoformat(expires_at) if expires_at else None
        return {
            "plan": plan,
            "started_at": started,
            "expires_at": expires,
            "status": status,
        }


async def grant_subscription_days(
    user_id: int,
    days: int,
    plan: str = "manual",
) -> datetime:
    if days <= 0:
        raise ValueError("days must be positive")
    await cleanup_expired_subscriptions(user_id)
    now = datetime.now(UTC)
    base = now
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT expires_at FROM subscriptions WHERE user_id=? AND status='active' ORDER BY expires_at DESC LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()
        if row and row[0]:
            try:
                candidate = datetime.fromisoformat(row[0])
            except ValueError:
                candidate = now
            if candidate > base:
                base = candidate
        expires_at = base + timedelta(days=days)
        await db.execute(
            """
            INSERT INTO subscriptions(user_id, plan, started_at, expires_at, status)
            VALUES(?,?,?,?,?)
            """,
            (
                user_id,
                plan,
                now.isoformat(),
                expires_at.isoformat(),
                "active",
            ),
        )
        await db.commit()
    return expires_at


async def degrant_subscription_days(user_id: int, days: int) -> datetime | None:
    if days <= 0:
        raise ValueError("days must be positive")
    await cleanup_expired_subscriptions(user_id)
    now = datetime.now(UTC)
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, expires_at FROM subscriptions WHERE user_id=? AND status='active' ORDER BY expires_at DESC LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        sub_id, expires_at_raw = row
        try:
            expires_at = datetime.fromisoformat(expires_at_raw)
        except (TypeError, ValueError):
            expires_at = now
        reduced_expires_at = expires_at - timedelta(days=days)
        if reduced_expires_at <= now:
            await db.execute(
                "UPDATE subscriptions SET status='expired', expires_at=? WHERE user_id=? AND status='active'",
                (now.isoformat(), user_id),
            )
            await db.commit()
            return None
        await db.execute(
            "UPDATE subscriptions SET expires_at=? WHERE id=?",
            (reduced_expires_at.isoformat(), sub_id),
        )
        await db.commit()
    return reduced_expires_at


async def create_payment_record(
    user_id: int,
    provider: str,
    amount: int,
    currency: str,
    status: str,
    payload: dict | None = None,
    external_id: str | None = None,
) -> int:
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO payments(user_id, provider, amount, currency, created_at, status, payload_json, external_id)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                user_id,
                provider,
                amount,
                currency,
                datetime.now(UTC).isoformat(),
                status,
                payload_json,
                external_id,
            ),
        )
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


async def update_payment_status(
    external_id: str,
    status: str,
    payload: dict | None = None,
) -> None:
    updates = ["status=?"]
    params: list[object] = [status]
    if payload is not None:
        updates.append("payload_json=?")
        params.append(json.dumps(payload, ensure_ascii=False))
    params.append(external_id)
    async with connect_db() as db:
        await db.execute(
            f"UPDATE payments SET {', '.join(updates)} WHERE external_id=?",
            tuple(params),
        )
        await db.commit()


async def get_payment_by_external_id(external_id: str) -> dict | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, user_id, provider, amount, currency, created_at, status, payload_json
            FROM payments
            WHERE external_id=?
            LIMIT 1
            """,
            (external_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        payload = {}
        if row[7]:
            try:
                payload = json.loads(row[7])
            except json.JSONDecodeError:
                payload = {}
        return {
            "id": row[0],
            "user_id": row[1],
            "provider": row[2],
            "amount": row[3],
            "currency": row[4],
            "created_at": row[5],
            "status": row[6],
            "payload": payload,
        }


async def get_latest_pending_payment(user_id: int, provider: str = "yookassa") -> dict | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT external_id, amount, currency, payload_json, created_at
            FROM payments
            WHERE user_id=? AND provider=? AND status='pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, provider),
        )
        row = await cur.fetchone()
        if not row:
            return None
        payload = {}
        if row[3]:
            try:
                payload = json.loads(row[3])
            except json.JSONDecodeError:
                payload = {}
        return {
            "external_id": row[0],
            "amount": row[1],
            "currency": row[2],
            "payload": payload,
            "created_at": row[4],
        }


async def list_broadcast_targets(
    exclude_tg_ids: Sequence[int] | set[int],
    only_without_subscription: bool = False,
) -> list[tuple[int, int]]:
    await cleanup_expired_subscriptions()
    async with connect_db() as db:
        query = [
            "SELECT u.tg_id, u.id",
            "FROM users u",
            "LEFT JOIN (",
            "    SELECT user_id, MAX(expires_at) AS expires_at",
            "    FROM subscriptions",
            "    WHERE status='active'",
            "    GROUP BY user_id",
            ") s ON s.user_id = u.id",
            "WHERE u.tg_id IS NOT NULL",
        ]
        params: list[object] = []
        if only_without_subscription:
            now_iso = datetime.now(UTC).isoformat()
            query.append("  AND (s.expires_at IS NULL OR s.expires_at <= ?)")
            params.append(now_iso)
        exclude = list(exclude_tg_ids)
        if exclude:
            placeholders = ",".join("?" for _ in exclude)
            query.append(f"  AND u.tg_id NOT IN ({placeholders})")
            params.extend(exclude)
        sql = "\n".join(query)
        cur = await db.execute(sql, tuple(params))
        rows = await cur.fetchall()
        return [(int(row[0]), int(row[1])) for row in rows if row[0] is not None]


async def increment_day_finish_total(user_id: int) -> int:
    async with connect_db() as db:
        await db.execute(
            "UPDATE users SET day_finish_total = COALESCE(day_finish_total, 0) + 1 WHERE id=?",
            (user_id,),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT COALESCE(day_finish_total, 0) FROM users WHERE id=?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


async def get_subscription_prompt_total(user_id: int) -> int:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COALESCE(subscription_prompt_total, 0) FROM users WHERE id=?",
            (user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


async def set_subscription_prompt_total(user_id: int, total: int) -> None:
    async with connect_db() as db:
        await db.execute(
            "UPDATE users SET subscription_prompt_total=? WHERE id=?",
            (int(total), user_id),
        )
        await db.commit()


async def find_user_by_tg_id(tg_id: int) -> tuple[int, str | None] | None:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, username FROM users WHERE tg_id=?",
            (tg_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return int(row[0]), row[1]


async def find_user_by_id(user_id: int) -> tuple[int, int | None, str | None] | None:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT id, tg_id, username FROM users WHERE id=?",
            (user_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        tg_id = row[1] if row[1] is None else int(row[1])
        return int(row[0]), tg_id, row[2]


async def list_active_days(user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT day_index, label FROM user_days WHERE user_id=? AND is_active=1 ORDER BY day_index",
            (user_id,),
        )
        return await cur.fetchall()


async def list_day_completions(user_id: int, system_id: int | None = None):
    resolved_system_id = 0 if system_id is None else int(system_id)
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT day_index, completed_at FROM day_completions WHERE user_id=? AND system_id=?",
            (user_id, resolved_system_id),
        )
        return await cur.fetchall()


async def get_day_completion(user_id: int, day_index: int, system_id: int | None = None) -> str | None:
    resolved_system_id = 0 if system_id is None else int(system_id)
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT completed_at
            FROM day_completions
            WHERE user_id=? AND system_id=? AND day_index=?
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (user_id, resolved_system_id, day_index),
        )
        row = await cur.fetchone()
        return row[0] if row and row[0] else None


async def get_day_completion_volume_kg(
    user_id: int,
    day_index: int,
    system_id: int | None = None,
    completed_at: str | None = None,
) -> int:
    resolved_system_id = 0 if system_id is None else int(system_id)
    resolved_completed_at = completed_at or await get_day_completion(user_id, day_index, resolved_system_id)
    if not resolved_completed_at:
        return 0
    try:
        completed_date = datetime.fromisoformat(str(resolved_completed_at)).date().isoformat()
    except Exception:
        completed_date = str(resolved_completed_at)[:10]
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT COALESCE(SUM(MAX(st.reps, 0) * MAX(st.weight_kg, 0)), 0)
            FROM sessions s
            LEFT JOIN sets st ON st.session_id=s.id
            WHERE s.user_id=?
              AND s.day_index=?
              AND s.system_id=?
              AND s.date=?
            """,
            (int(user_id), int(day_index), int(resolved_system_id), completed_date),
        )
        row = await cur.fetchone()
    return int(round(float(row[0] or 0)))


async def get_last_completion_for_user(user_id: int, system_id: int | None = None):
    resolved_system_id = 0 if system_id is None else int(system_id)
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT day_index, completed_at
            FROM day_completions
            WHERE user_id = ? AND system_id=?
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (user_id, resolved_system_id),
        )
        return await cur.fetchone()


async def mark_day_completed(user_id: int, day_index: int, completed_at: str, system_id: int | None = None):
    resolved_system_id = 0 if system_id is None else int(system_id)
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO day_completion_history(user_id, system_id, day_index, completed_at)
            VALUES(?,?,?,?)
            """,
            (user_id, resolved_system_id, day_index, completed_at),
        )
        await db.execute(
            """
            INSERT INTO day_completions(user_id, system_id, day_index, completed_at)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id, system_id, day_index)
            DO UPDATE SET completed_at=excluded.completed_at
            """,
            (user_id, resolved_system_id, day_index, completed_at),
        )
        await db.commit()


async def clear_day_completions(user_id: int, system_id: int | None = None):
    resolved_system_id = None if system_id is None else int(system_id)
    async with connect_db() as db:
        if resolved_system_id is None:
            await db.execute("DELETE FROM day_completions WHERE user_id=?", (user_id,))
        else:
            await db.execute(
                "DELETE FROM day_completions WHERE user_id=? AND system_id=?",
                (user_id, resolved_system_id),
            )
        await db.commit()


async def get_day_label(user_id: int, day_index: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT label FROM user_days WHERE user_id=? AND day_index=?",
            (user_id, day_index),
        )
        row = await cur.fetchone()
        return row[0] if row else f"День {day_index}"


async def get_user_exercise_info(user_exercise_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT user_id, day_index FROM user_exercises WHERE id=? AND is_archived=0",
            (user_exercise_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return int(row[0]), int(row[1])

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
            """
            SELECT sets, reps, seconds, weight_kg
            FROM exercise_baseline
            WHERE user_id=? AND day_index=? AND exercise_id=? AND sets>=0
            """,
            (user_id, day_index, exercise_id),
        )
        row = await cur.fetchone()
        if row:
            return row
        cur = await db.execute(
            """
            SELECT sets, reps, seconds, weight_kg
            FROM exercise_baseline
            WHERE user_id=? AND exercise_id=? AND sets>=0
            ORDER BY day_index
            LIMIT 1
            """,
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
                INSERT INTO exercise_baseline(user_id, day_index, exercise_id, sets, reps, seconds, weight_kg)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(user_id, day_index, exercise_id)
                DO UPDATE SET
                    sets=excluded.sets,
                    reps=excluded.reps,
                    seconds=excluded.seconds,
                    weight_kg=excluded.weight_kg
                """,
                (user_id, day_index, exercise_id, SCHEME_SENTINEL, 0, 0, cleaned),
            )
        else:
            await db.execute(
                "DELETE FROM exercise_baseline WHERE user_id=? AND day_index=? AND exercise_id=? AND sets=?",
                (user_id, day_index, exercise_id, SCHEME_SENTINEL),
            )
        await db.commit()

async def get_last_session_summary(user_id: int, day_index: int, ue_id: int, today: str, system_id: int | None = None):
    async with connect_db() as db:
        if system_id is None:
            cur = await db.execute(
                "SELECT id FROM sessions WHERE user_id=? AND day_index=? AND date<? ORDER BY date DESC LIMIT 1",
                (user_id, day_index, today),
            )
        else:
            cur = await db.execute(
                "SELECT id FROM sessions WHERE user_id=? AND day_index=? AND date<? AND COALESCE(system_id,0)=? ORDER BY date DESC LIMIT 1",
                (user_id, day_index, today, int(system_id)),
            )
        row = await cur.fetchone()
        if not row:
            return None
        session_id = row[0]
        cur = await db.execute(
            """
            SELECT reps, seconds, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=? AND is_warmup=0
            ORDER BY set_no DESC
            LIMIT 1
            """,
            (session_id, ue_id),
        )
        last = await cur.fetchone()
        if not last:
            return None
        reps, seconds, weight = last
        cur = await db.execute(
            "SELECT COUNT(*) FROM sets WHERE session_id=? AND user_exercise_id=? AND is_warmup=0",
            (session_id, ue_id),
        )
        count = (await cur.fetchone())[0]
        return count, reps, seconds, weight

async def fetch_last_session_sets(user_id: int, day_index: int, ue_id: int, today: str, system_id: int | None = None):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT exercise_id FROM user_exercises WHERE id=?",
            (ue_id,),
        )
        row = await cur.fetchone()
        if not row:
            return []
        exercise_id = row[0]
        if system_id is None:
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
        else:
            cur = await db.execute(
                """
                SELECT s.id, st.user_exercise_id
                FROM sessions s
                JOIN sets st ON st.session_id=s.id AND st.is_warmup=0
                JOIN user_exercises ue ON ue.id=st.user_exercise_id
                WHERE s.user_id=? AND ue.exercise_id=? AND s.date<? AND COALESCE(s.system_id,0)=?
                ORDER BY s.date DESC, st.set_no DESC
                LIMIT 1
                """,
                (user_id, exercise_id, today, int(system_id)),
            )
        row = await cur.fetchone()
        if not row:
            return []
        session_id, prev_ue_id = row
        cur = await db.execute(
            """
            SELECT set_no, reps, seconds, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=? AND is_warmup=0
            ORDER BY set_no
            """,
            (session_id, prev_ue_id),
        )
        return await cur.fetchall()


async def count_completed_sessions_for_exercise(conn, user_id: int, exercise_id: int) -> int:
    """
    Сколько раз пользователь завершал упражнение (is_done=1) во всех сессиях.
    Счёт ведётся по catalog exercise_id, а не по user_exercise_id,
    чтобы история синхронизировалась между днями/системами.
    """
    cur = await conn.execute(
        """
        SELECT COUNT(*)
        FROM session_exercises se
        JOIN sessions s ON s.id = se.session_id
        JOIN user_exercises ue ON ue.id = se.user_exercise_id
        WHERE s.user_id = ?
          AND ue.exercise_id = ?
          AND se.is_done = 1
        """,
        (int(user_id), int(exercise_id)),
    )
    row = await cur.fetchone()
    return int((row[0] if row else 0) or 0)

async def fetch_exercise_sets(session_id: int, ue_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT set_no, reps, seconds, weight_kg, is_warmup
            FROM sets
            WHERE session_id=? AND user_exercise_id=?
            ORDER BY set_no
            """,
            (session_id, ue_id),
        )
        return await cur.fetchall()

async def add_set(
    session_id: int,
    user_ex_id: int,
    reps: int = 0,
    seconds: int = 0,
    weight: float = 0.0,
    is_warmup: bool = False,
):
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COALESCE(MAX(set_no),0)+1 FROM sets WHERE session_id=? AND user_exercise_id=?",
            (session_id, user_ex_id),
        )
        next_no = (await cur.fetchone())[0]
        await db.execute(
            """
            INSERT INTO sets(session_id, user_exercise_id, set_no, reps, seconds, weight_kg, is_warmup)
            VALUES(?,?,?,?,?,?,?)
            """,
            (session_id, user_ex_id, next_no, reps, seconds, weight, int(bool(is_warmup))),
        )
        if not is_warmup:
            await _upsert_session_defaults(db, session_id, user_ex_id, reps, seconds, weight)
        await db.commit()

async def remove_last_set(user_ex_id: int, session_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, reps, seconds, weight_kg
            FROM sets
            WHERE session_id=? AND user_exercise_id=?
            ORDER BY set_no DESC
            LIMIT 1
            """,
            (session_id, user_ex_id),
        )
        row = await cur.fetchone()
        if row:
            set_id, reps, seconds, weight = row
            await db.execute("DELETE FROM sets WHERE id=?", (set_id,))
            await _refresh_session_defaults(db, session_id, user_ex_id)
            cur = await db.execute(
                "SELECT COUNT(*) FROM sets WHERE session_id=? AND user_exercise_id=? AND is_warmup=0",
                (session_id, user_ex_id),
            )
            remaining = (await cur.fetchone())[0]
            if remaining == 0:
                await _upsert_session_defaults(db, session_id, user_ex_id, reps, seconds, weight)
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
            """
            SELECT last_reps, last_seconds, last_weight
            FROM session_exercises
            WHERE session_id=? AND user_exercise_id=?
            """,
            (session_id, ue_id),
        )
        row = await cur.fetchone()
        last_reps = row[0] if row and row[0] is not None else None
        last_seconds = row[1] if row and row[1] is not None else None
        last_weight = row[2] if row and row[2] is not None else None
        await db.execute(
            """
            INSERT INTO session_exercises(
                session_id, user_exercise_id, is_done, is_microcycle, done_at, last_reps, last_seconds, last_weight
            )
            VALUES(?,?,1,0,?,?,?,?)
            ON CONFLICT(session_id, user_exercise_id)
            DO UPDATE SET
                is_done=1,
                done_at=excluded.done_at,
                last_reps=COALESCE(excluded.last_reps, session_exercises.last_reps),
                last_seconds=COALESCE(excluded.last_seconds, session_exercises.last_seconds),
                last_weight=COALESCE(excluded.last_weight, session_exercises.last_weight)
            """,
            (
                session_id,
                ue_id,
                datetime.now(UTC).isoformat(),
                last_reps,
                last_seconds,
                last_weight,
            ),
        )
        await db.commit()


async def set_exercise_note(session_id: int, ue_id: int, note: str | None):
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO session_exercises(
                session_id,
                user_exercise_id,
                is_done,
                is_microcycle,
                done_at,
                last_reps,
                last_seconds,
                last_weight,
                note
            ) VALUES(?,?,0,0,NULL,NULL,NULL,NULL,?)
            ON CONFLICT(session_id, user_exercise_id)
            DO UPDATE SET note=excluded.note
            """,
            (session_id, ue_id, note),
        )
        await db.commit()


async def get_exercise_note(session_id: int, ue_id: int) -> str | None:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT note FROM session_exercises WHERE session_id=? AND user_exercise_id=?",
            (session_id, ue_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return row[0]


async def get_latest_completed_note(
    user_id: int, exercise_id: int, exclude_session_id: int | None = None
) -> tuple[int | None, str | None]:
    async with connect_db() as db:
        query = [
            "SELECT se.session_id, se.note",
            "FROM session_exercises se",
            "JOIN user_exercises ue ON ue.id = se.user_exercise_id",
            "JOIN sessions s ON s.id = se.session_id",
            "WHERE ue.exercise_id=? AND s.user_id=? AND se.is_done=1",
        ]
        params: list[object] = [exercise_id, user_id]
        if exclude_session_id is not None:
            query.append("AND se.session_id<>?")
            params.append(exclude_session_id)
        query.append(
            "ORDER BY s.date DESC, COALESCE(se.done_at, s.date || 'T00:00:00') DESC, se.session_id DESC LIMIT 1"
        )
        sql = "\n".join(query)
        cur = await db.execute(sql, tuple(params))
        row = await cur.fetchone()
        if not row:
            return None, None
        return int(row[0]), row[1]


async def list_recent_progress(
    user_id: int, day_index: int, ue_id: int, limit: int = 4, offset: int = 0
):
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
            SELECT s.id, s.date, se.user_exercise_id
            FROM sessions s
            JOIN session_exercises se ON se.session_id=s.id
            JOIN user_exercises ue ON ue.id=se.user_exercise_id
            WHERE s.user_id=? AND ue.exercise_id=? AND se.is_done=1
            ORDER BY s.date DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, exercise_id, limit, offset),
        )
        sessions = await cur.fetchall()
        results: list[
            tuple[str, int, int, int, float, list[tuple[int, int, float]]]
        ] = []
        for session_id, date_value, session_ue_id in sessions:
            cur_sets = await db.execute(
                """
                SELECT set_no, reps, seconds, weight_kg
                FROM sets
                WHERE session_id=? AND user_exercise_id=? AND is_warmup=0
                ORDER BY set_no, id
                """,
                (session_id, session_ue_id),
            )
            set_rows = await cur_sets.fetchall()
            details: list[tuple[int, int, float]] = [
                (int(row[1] or 0), int(row[2] or 0), float(row[3] or 0.0))
                for row in set_rows
            ]
            sets_cnt = len(details)
            max_reps = max((row[1] or 0 for row in set_rows), default=0)
            max_seconds = max((row[2] or 0 for row in set_rows), default=0)
            max_weight = max((row[3] or 0.0 for row in set_rows), default=0.0)
            results.append((date_value, sets_cnt, max_reps, max_seconds, max_weight, details))
        return results


async def list_exercise_weight_progress(
    user_id: int, *, days: int = 30
) -> list[dict]:
    since_date = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT
                ue.exercise_id,
                e.name,
                s.date,
                MAX(NULLIF(sets.weight_kg, 0))
            FROM sets
            JOIN sessions s ON s.id = sets.session_id
            JOIN user_exercises ue ON ue.id = sets.user_exercise_id
            JOIN exercises e ON e.id = ue.exercise_id
            WHERE s.user_id=?
              AND sets.is_warmup=0
              AND s.date>=?
            GROUP BY ue.exercise_id, s.id
            """,
            (user_id, since_date),
        )
        rows = await cur.fetchall()
    progress: dict[int, dict[str, object]] = {}
    for exercise_id, name, date_value, max_weight in rows:
        if max_weight is None:
            continue
        weight = float(max_weight or 0.0)
        if weight <= 0:
            continue
        entry = progress.setdefault(
            int(exercise_id), {"name": name, "values": []}
        )
        entry_values = entry.setdefault("values", [])
        entry_values.append((str(date_value), weight))
    results: list[dict] = []
    for exercise_id, entry in progress.items():
        values = sorted(entry.get("values", []), key=lambda item: item[0])
        if len(values) < 2:
            continue
        start_weight = float(values[0][1])
        end_weight = float(values[-1][1])
        if end_weight <= start_weight:
            continue
        results.append(
            {
                "exercise_id": exercise_id,
                "name": entry.get("name"),
                "start_weight": start_weight,
                "end_weight": end_weight,
                "delta": end_weight - start_weight,
            }
        )
    results.sort(key=lambda item: item["delta"], reverse=True)
    return results

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


async def get_webapp_prompt_suppressed(user_id: int) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT suppress_webapp_prompt FROM user_prefs WHERE user_id=?",
            (user_id,),
        )
        row = await cur.fetchone()
    if row and row[0] in (0, 1):
        return bool(row[0])
    return False


async def set_webapp_prompt_suppressed(user_id: int, suppressed: bool):
    value = 1 if suppressed else 0
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_prefs(user_id, suppress_webapp_prompt) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET suppress_webapp_prompt=excluded.suppress_webapp_prompt
            """,
            (user_id, value),
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


async def ensure_achievements_schema() -> None:
    async with connect_db() as db:
        await _ensure_achievements_schema(db)
        await db.commit()


async def list_user_achievements(user_id: int) -> list[tuple[str, str]]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT code, unlocked_at
            FROM user_achievements
            WHERE user_id=?
            ORDER BY unlocked_at DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


async def grant_achievement(user_id: int, code: str, unlocked_at: str | None = None) -> bool:
    ts = unlocked_at or datetime.now(UTC).isoformat()
    async with connect_db() as db:
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO user_achievements(user_id, code, unlocked_at)
            VALUES(?,?,?)
            """,
            (user_id, code, ts),
        )
        await db.commit()
        return bool(cur.rowcount)


async def create_team(owner_user_id: int, name: str, is_open: bool = False) -> dict:
    team_name = (name or "").strip()
    if not team_name:
        raise ValueError("team_name_required")

    async with connect_db() as db:
        now = _now_utc_iso()
        for _ in range(10):
            join_code = _generate_team_join_code()
            try:
                cur = await db.execute(
                    """
                    INSERT INTO teams(owner_user_id, name, join_code, is_open, created_at, updated_at)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (owner_user_id, team_name, join_code, 1 if is_open else 0, now, now),
                )
                team_id = int(cur.lastrowid)
                await db.execute(
                    """
                    INSERT INTO team_members(team_id, user_id, role, joined_at, left_at)
                    VALUES(?,?,?,?,NULL)
                    """,
                    (team_id, owner_user_id, "captain", now),
                )
                await db.commit()
                return {
                    "team_id": team_id,
                    "name": team_name,
                    "join_code": join_code,
                    "is_open": 1 if is_open else 0,
                    "frame_code": None,
                    "bg_code": None,
                    "emblem_code": None,
                }
            except aiosqlite.IntegrityError:
                await db.rollback()
                continue
    raise RuntimeError("team_join_code_generation_failed")


async def get_team_by_id(team_id: int) -> dict | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, owner_user_id, name, join_code, is_open, frame_code, bg_code, emblem_code, created_at, updated_at
            FROM teams
            WHERE id=?
            """,
            (team_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "team_id": int(row[0]),
        "owner_user_id": int(row[1]),
        "name": row[2],
        "join_code": row[3],
        "is_open": int(row[4] or 0),
        "frame_code": row[5],
        "bg_code": row[6],
        "emblem_code": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


async def get_team_by_code(join_code: str) -> dict | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, owner_user_id, name, join_code, is_open, frame_code, bg_code, emblem_code, created_at, updated_at
            FROM teams
            WHERE join_code=?
            """,
            ((join_code or "").strip().upper(),),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "team_id": int(row[0]),
        "owner_user_id": int(row[1]),
        "name": row[2],
        "join_code": row[3],
        "is_open": int(row[4] or 0),
        "frame_code": row[5],
        "bg_code": row[6],
        "emblem_code": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


async def get_user_team(user_id: int) -> dict | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT t.id, t.name, t.join_code, t.is_open, tm.role, t.frame_code, t.bg_code, t.emblem_code, t.owner_user_id
            FROM team_members tm
            JOIN teams t ON t.id = tm.team_id
            WHERE tm.user_id=? AND tm.left_at IS NULL
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "team_id": int(row[0]),
        "team_name": row[1],
        "join_code": row[2],
        "is_open": int(row[3] or 0),
        "role": row[4],
        "frame_code": row[5],
        "bg_code": row[6],
        "emblem_code": row[7],
        "owner_user_id": int(row[8]),
    }


async def leave_team(user_id: int) -> None:
    now = _now_utc_iso()
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE team_members
            SET left_at=?
            WHERE user_id=? AND left_at IS NULL
            """,
            (now, user_id),
        )
        await db.commit()


async def create_or_get_join_request(team_id: int, user_id: int) -> dict:
    now = _now_utc_iso()
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM team_members WHERE user_id=? AND left_at IS NULL LIMIT 1",
            (user_id,),
        )
        if await cur.fetchone():
            raise ValueError("already_in_team")

        cur = await db.execute(
            "SELECT COUNT(*) FROM team_members WHERE team_id=? AND left_at IS NULL",
            (team_id,),
        )
        members_total = int((await cur.fetchone() or [0])[0] or 0)
        if members_total >= 25:
            raise ValueError("team_full")

        cur = await db.execute(
            """
            SELECT id, status, created_at, updated_at
            FROM team_join_requests
            WHERE team_id=? AND user_id=? AND status='pending'
            LIMIT 1
            """,
            (team_id, user_id),
        )
        row = await cur.fetchone()
        if row:
            return {
                "request_id": int(row[0]),
                "team_id": int(team_id),
                "user_id": int(user_id),
                "status": row[1],
                "created_at": row[2],
                "updated_at": row[3],
            }

        cur = await db.execute(
            """
            INSERT INTO team_join_requests(team_id, user_id, status, created_at, updated_at)
            VALUES(?,?,?,?,?)
            """,
            (team_id, user_id, "pending", now, now),
        )
        request_id = int(cur.lastrowid)
        await db.commit()
        return {
            "request_id": request_id,
            "team_id": int(team_id),
            "user_id": int(user_id),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }


async def cancel_join_request(team_id: int, user_id: int) -> None:
    now = _now_utc_iso()
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE team_join_requests
            SET status='cancelled', updated_at=?
            WHERE team_id=? AND user_id=? AND status='pending'
            """,
            (now, team_id, user_id),
        )
        await db.commit()


async def list_team_requests(
    team_id: int,
    status: str = "pending",
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    safe_limit = max(1, min(200, int(limit)))
    safe_offset = max(0, int(offset))
    query = (q or "").strip()

    where = ["r.team_id=?", "r.status=?"]
    params: list[object] = [team_id, status]

    if query:
        where.append("LOWER(COALESCE(u.username, '')) LIKE ?")
        params.append(f"{query.lower()}%")

    where_sql = " AND ".join(where)

    async with connect_db() as db:
        cur = await db.execute(
            f"""
            SELECT
                r.id,
                r.user_id,
                COALESCE(u.username, ''),
                r.created_at,
                COALESCE((
                    SELECT ts.name
                    FROM training_systems ts
                    WHERE ts.user_id = r.user_id
                    ORDER BY ts.id DESC
                    LIMIT 1
                ), '') AS latest_system_name,
                COALESCE((
                    SELECT COUNT(*)
                    FROM day_completions dc
                    WHERE dc.user_id = r.user_id
                ), 0) AS sessions_total,
                COALESCE((
                    SELECT COUNT(*)
                    FROM day_completions dc
                    WHERE dc.user_id = r.user_id
                      AND dc.completed_at >= datetime('now', '-28 days')
                ), 0) AS sessions_28,
                COALESCE(u.created_at, '') AS user_created_at
            FROM team_join_requests r
            JOIN users u ON u.id = r.user_id
            WHERE {where_sql}
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (*params, safe_limit, safe_offset),
        )
        rows = await cur.fetchall()

        cur = await db.execute(
            f"""
            SELECT COUNT(*)
            FROM team_join_requests r
            JOIN users u ON u.id = r.user_id
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total_row = await cur.fetchone()

    items = [
        {
            "request_id": int(row[0]),
            "user_id": int(row[1]),
            "username": row[2],
            "created_at": row[3],
            "latest_system_name": row[4],
            "sessions_total": int(row[5] or 0),
            "sessions_28": int(row[6] or 0),
            "user_created_at": row[7],
        }
        for row in rows
    ]
    return items, int(total_row[0] if total_row else 0)


async def _get_captain_team_for_request(db, request_id: int, captain_user_id: int):
    cur = await db.execute(
        """
        SELECT r.id, r.team_id, r.user_id, r.status
        FROM team_join_requests r
        JOIN team_members tm ON tm.team_id = r.team_id
        WHERE r.id=?
          AND tm.user_id=?
          AND tm.role='captain'
          AND tm.left_at IS NULL
        LIMIT 1
        """,
        (request_id, captain_user_id),
    )
    return await cur.fetchone()


async def accept_team_request(request_id: int, captain_user_id: int) -> dict:
    now = _now_utc_iso()
    async with connect_db() as db:
        row = await _get_captain_team_for_request(db, request_id, captain_user_id)
        if not row:
            raise ValueError("not_team_captain")

        _, team_id, user_id, status = row
        if status != "pending":
            raise ValueError("request_not_pending")

        cur = await db.execute(
            "SELECT 1 FROM team_members WHERE user_id=? AND left_at IS NULL LIMIT 1",
            (user_id,),
        )
        if await cur.fetchone():
            raise ValueError("already_in_team")

        cur = await db.execute(
            "SELECT COUNT(*) FROM team_members WHERE team_id=? AND left_at IS NULL",
            (team_id,),
        )
        members_total = int((await cur.fetchone() or [0])[0] or 0)
        if members_total >= 25:
            raise ValueError("team_full")

        await db.execute(
            "UPDATE team_join_requests SET status='accepted', updated_at=? WHERE id=?",
            (now, request_id),
        )
        await db.execute(
            """
            INSERT INTO team_members(team_id, user_id, role, joined_at, left_at)
            VALUES(?,?,?,?,NULL)
            """,
            (team_id, user_id, "member", now),
        )
        await db.execute(
            """
            UPDATE team_join_requests
            SET status='cancelled', updated_at=?
            WHERE user_id=? AND status='pending' AND id<>?
            """,
            (now, user_id, request_id),
        )
        await db.commit()

    return {
        "request_id": int(request_id),
        "team_id": int(team_id),
        "user_id": int(user_id),
        "status": "accepted",
    }


async def reject_team_request(request_id: int, captain_user_id: int) -> None:
    now = _now_utc_iso()
    async with connect_db() as db:
        row = await _get_captain_team_for_request(db, request_id, captain_user_id)
        if not row:
            raise ValueError("not_team_captain")
        if row[3] != "pending":
            raise ValueError("request_not_pending")
        await db.execute(
            "UPDATE team_join_requests SET status='rejected', updated_at=? WHERE id=?",
            (now, request_id),
        )
        await db.commit()


async def set_team_style(
    team_id: int,
    captain_user_id: int,
    frame_code: str | None,
    bg_code: str | None,
    emblem_code: str | None,
) -> None:
    now = _now_utc_iso()
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT 1
            FROM team_members
            WHERE team_id=? AND user_id=? AND role='captain' AND left_at IS NULL
            LIMIT 1
            """,
            (team_id, captain_user_id),
        )
        if not await cur.fetchone():
            raise ValueError("not_team_captain")

        await db.execute(
            """
            UPDATE teams
            SET frame_code=?, bg_code=?, emblem_code=?, updated_at=?
            WHERE id=?
            """,
            (frame_code, bg_code, emblem_code, now, team_id),
        )
        await db.commit()


async def grant_team_achievement(team_id: int, code: str, unlocked_at: str | None = None) -> bool:
    ts = unlocked_at or _now_utc_iso()
    async with connect_db() as db:
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO team_achievements(team_id, code, unlocked_at)
            VALUES(?,?,?)
            """,
            (team_id, code, ts),
        )
        await db.commit()
        return bool(cur.rowcount)


async def list_team_achievements(team_id: int) -> set[str]:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT code FROM team_achievements WHERE team_id=?",
            (team_id,),
        )
        rows = await cur.fetchall()
    return {str(row[0]) for row in rows}


def _clamp_0_100(value: float) -> int:
    return int(max(0, min(100, round(float(value)))))


async def join_team_direct(team_id: int, user_id: int) -> None:
    now = _now_utc_iso()
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM team_members WHERE user_id=? AND left_at IS NULL LIMIT 1",
            (user_id,),
        )
        if await cur.fetchone():
            raise ValueError("already_in_team")
        cur = await db.execute(
            "SELECT COUNT(*) FROM team_members WHERE team_id=? AND left_at IS NULL",
            (team_id,),
        )
        members_total = int((await cur.fetchone() or [0])[0] or 0)
        if members_total >= 25:
            raise ValueError("team_full")
        try:
            await db.execute(
                """
                INSERT INTO team_members(team_id, user_id, role, joined_at, left_at)
                VALUES(?,?,?,?,NULL)
                """,
                (team_id, user_id, "member", now),
            )
        except aiosqlite.IntegrityError as exc:
            await db.rollback()
            raise ValueError("already_in_team") from exc
        await db.commit()


async def count_team_pending_requests(team_id: int) -> int:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM team_join_requests WHERE team_id=? AND status='pending'",
            (team_id,),
        )
        row = await cur.fetchone()
    return int(row[0] if row else 0)


async def fetch_team_leaderboard(limit: int = 10, offset: int = 0):
    safe_limit = max(1, int(limit or 10))
    safe_offset = max(0, int(offset or 0))
    async with connect_db() as db:
        cur = await db.execute(
            """
            WITH team_users AS (
                SELECT tm.team_id, tm.user_id, COALESCE(u.username, '') AS username
                FROM team_members tm
                JOIN users u ON u.id = tm.user_id
                WHERE tm.left_at IS NULL
            ),
            completed_sessions AS (
                SELECT s.id, s.user_id, s.date, s.day_index, s.system_id
                FROM sessions s
                JOIN day_completion_history dch
                  ON dch.user_id = s.user_id
                 AND dch.day_index = s.day_index
                 AND dch.system_id = s.system_id
                 AND date(dch.completed_at) = s.date
                GROUP BY s.id
            ),
            recent_sessions AS (
                SELECT s.user_id,
                       SUM(CASE WHEN s.date >= date('now', '-7 day') THEN 1 ELSE 0 END) AS sessions_7,
                       SUM(CASE WHEN s.date >= date('now', '-28 day') THEN 1 ELSE 0 END) AS sessions_28,
                       COUNT(DISTINCT CASE WHEN s.date >= date('now', '-28 day') THEN s.date END) AS training_days_28,
                       COUNT(DISTINCT CASE WHEN s.date >= date('now', '-56 day') THEN substr(s.date, 1, 8) || CAST(((CAST(substr(s.date, 9, 2) AS INTEGER)-1)/7) AS INTEGER) END) AS training_weeks_8
                FROM completed_sessions s
                GROUP BY s.user_id
            ),
            set_stats AS (
                SELECT s.user_id,
                       SUM(CASE WHEN s.date >= date('now', '-28 day') THEN 1 ELSE 0 END) AS sets_28,
                       COALESCE(SUM(CASE WHEN s.date >= date('now', '-28 day') THEN MAX(st.reps, 0) * MAX(st.weight_kg, 0) ELSE 0 END), 0) AS volume_28,
                       AVG(CASE WHEN s.date >= date('now', '-28 day') THEN MAX(st.reps, 0) * MAX(st.weight_kg, 0) END) AS avg_weighted_reps
                FROM sets st
                JOIN completed_sessions s ON s.id = st.session_id
                GROUP BY s.user_id
            ),
            exercise_variety AS (
                SELECT ue.user_id, COUNT(DISTINCT ue.exercise_id) AS active_exercise_count
                FROM user_exercises ue
                WHERE COALESCE(ue.is_archived, 0) = 0
                GROUP BY ue.user_id
            ),
            completion AS (
                SELECT s.user_id,
                       AVG(CASE WHEN se.is_done = 1 THEN 1.0 ELSE 0.0 END) AS completion_ratio
                FROM session_exercises se
                JOIN sessions s ON s.id = se.session_id
                WHERE s.date >= date('now', '-28 day')
                GROUP BY s.user_id
            ),
            recent_best AS (
                SELECT s.user_id, ue.exercise_id, MAX(st.weight_kg) AS max_w
                FROM sets st
                JOIN completed_sessions s ON s.id = st.session_id
                JOIN user_exercises ue ON ue.id = st.user_exercise_id
                WHERE s.date >= date('now', '-14 day')
                GROUP BY s.user_id, ue.exercise_id
            ),
            prev_best AS (
                SELECT s.user_id, ue.exercise_id, MAX(st.weight_kg) AS max_w
                FROM sets st
                JOIN completed_sessions s ON s.id = st.session_id
                JOIN user_exercises ue ON ue.id = st.user_exercise_id
                WHERE s.date >= date('now', '-28 day') AND s.date < date('now', '-14 day')
                GROUP BY s.user_id, ue.exercise_id
            ),
            progression AS (
                SELECT rb.user_id,
                       AVG(CASE WHEN pb.max_w > 0 THEN (rb.max_w - pb.max_w) / pb.max_w ELSE 0 END) AS progression_index
                FROM recent_best rb
                LEFT JOIN prev_best pb ON pb.user_id = rb.user_id AND pb.exercise_id = rb.exercise_id
                GROUP BY rb.user_id
            )
            SELECT tu.team_id,
                   tu.user_id,
                   tu.username,
                   COALESCE(rs.sessions_7, 0) AS sessions_7,
                   COALESCE(rs.sessions_28, 0) AS sessions_28,
                   COALESCE(rs.training_days_28, 0) AS training_days_28,
                   COALESCE(rs.training_weeks_8, 0) AS training_weeks_8,
                   COALESCE(ss.sets_28, 0) AS sets_28,
                   COALESCE(ss.volume_28, 0) AS volume_28,
                   COALESCE(ss.avg_weighted_reps, 0) AS avg_weighted_reps,
                   COALESCE(ev.active_exercise_count, 0) AS active_exercise_count,
                   COALESCE(c.completion_ratio, 0) AS completion_ratio,
                   COALESCE(p.progression_index, 0) AS progression_index,
                   t.name,
                   COALESCE(t.frame_code, NULL),
                   COALESCE(t.bg_code, NULL),
                   COALESCE(t.emblem_code, NULL)
            FROM team_users tu
            JOIN teams t ON t.id = tu.team_id
            LEFT JOIN recent_sessions rs ON rs.user_id = tu.user_id
            LEFT JOIN set_stats ss ON ss.user_id = tu.user_id
            LEFT JOIN exercise_variety ev ON ev.user_id = tu.user_id
            LEFT JOIN completion c ON c.user_id = tu.user_id
            LEFT JOIN progression p ON p.user_id = tu.user_id
            """
        )
        rows = await cur.fetchall()

    teams: dict[int, dict] = {}
    for row in rows:
        team_id = int(row[0])
        if team_id not in teams:
            teams[team_id] = {
                "team_id": team_id,
                "name": row[13] or f"team_{team_id}",
                "frame_code": row[14],
                "bg_code": row[15],
                "emblem_code": row[16],
                "members_count": 0,
                "active_members_7d": 0,
                "sessions_7": 0,
                "sessions_28": 0,
                "member_scores": [],
                "completion_values": [],
                "variety_values": [],
                "progression_values": [],
            }
        item = teams[team_id]
        member = {
            "training_days_28": int(row[5] or 0),
            "sessions_28": int(row[4] or 0),
            "training_weeks_8": int(row[6] or 0),
            "sets_28": int(row[7] or 0),
            "volume_28": float(row[8] or 0),
            "avg_weighted_reps": float(row[9] or 0),
            "active_exercise_count": int(row[10] or 0),
            "completion_ratio": float(row[11] or 0),
            "progression_index": float(row[12] or 0),
        }
        user_score = int(round(_leaderboard_score(member) * 100))

        item["members_count"] += 1
        item["sessions_7"] += int(row[3] or 0)
        item["sessions_28"] += int(row[4] or 0)
        if int(row[3] or 0) > 0:
            item["active_members_7d"] += 1
        item["member_scores"].append(user_score)
        item["completion_values"].append(float(row[11] or 0.0))
        item["variety_values"].append(int(row[10] or 0))
        item["progression_values"].append(float(row[12] or 0.0))

    ranked: list[dict] = []
    for team in teams.values():
        members_count = int(team["members_count"])
        avg_member_score_raw = (sum(team["member_scores"]) / members_count) if members_count else 0.0
        avg_completion_ratio_28 = (sum(team["completion_values"]) / members_count) if members_count else 0.0
        avg_variety = (sum(team["variety_values"]) / members_count) if members_count else 0.0
        avg_progression_index = (sum(team["progression_values"]) / members_count) if members_count else 0.0

        consistency_score = _clamp_0_100((team["sessions_28"] / max(1, members_count)) / 12 * 100)
        engagement_score = _clamp_0_100(team["active_members_7d"] / max(1, members_count) * 100)
        completion_score = _clamp_0_100(avg_completion_ratio_28 * 100)
        variety_score = _clamp_0_100(avg_variety / 25 * 100)
        progression_score = _clamp_0_100(avg_progression_index * 400)
        avg_member_score = _clamp_0_100(avg_member_score_raw)
        team_score = _clamp_0_100(
            0.40 * avg_member_score
            + 0.20 * consistency_score
            + 0.15 * engagement_score
            + 0.10 * completion_score
            + 0.10 * variety_score
            + 0.05 * progression_score
        )

        ranked.append(
            {
                "team_id": int(team["team_id"]),
                "name": team["name"],
                "score": team_score,
                "members_count": members_count,
                "active_members_7d": int(team["active_members_7d"]),
                "sessions_7": int(team["sessions_7"]),
                "sessions_28": int(team["sessions_28"]),
                "avg_member_score": avg_member_score,
                "avg_completion_ratio_28": float(avg_completion_ratio_28),
                "avg_variety": float(avg_variety),
                "avg_progression_index": float(avg_progression_index),
                "consistency_score": consistency_score,
                "engagement_score": engagement_score,
                "completion_score": completion_score,
                "variety_score": variety_score,
                "progression_score": progression_score,
                "frame_code": team["frame_code"],
                "bg_code": team["bg_code"],
                "emblem_code": team["emblem_code"],
            }
        )

    ranked.sort(
        key=lambda item: (
            -int(item["score"]),
            -int(item["sessions_28"]),
            -int(item["active_members_7d"]),
            -int(item["members_count"]),
            int(item["team_id"]),
        )
    )
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx

    total = len(ranked)
    paged = ranked[safe_offset:safe_offset + safe_limit]
    return paged, total, ranked


async def fetch_team_profile(team_id: int, viewer_user_id: int):
    _, _, full = await fetch_team_leaderboard(limit=10000, offset=0)
    summary = next((item for item in full if int(item["team_id"]) == int(team_id)), None)
    if not summary:
        return None

    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT role
            FROM team_members
            WHERE team_id=? AND user_id=? AND left_at IS NULL
            LIMIT 1
            """,
            (team_id, viewer_user_id),
        )
        role_row = await cur.fetchone()

        members = None
        if role_row:
            cur = await db.execute(
                """
                WITH completed_sessions AS (
                    SELECT s.id, s.user_id, s.date, s.day_index, s.system_id
                    FROM sessions s
                    JOIN day_completion_history dch
                      ON dch.user_id = s.user_id
                     AND dch.day_index = s.day_index
                     AND dch.system_id = s.system_id
                     AND date(dch.completed_at) = s.date
                    GROUP BY s.id
                ),
                recent_sessions AS (
                    SELECT s.user_id,
                           SUM(CASE WHEN s.date >= date('now', '-28 day') THEN 1 ELSE 0 END) AS sessions_28,
                           COUNT(DISTINCT CASE WHEN s.date >= date('now', '-28 day') THEN s.date END) AS training_days_28,
                           COUNT(DISTINCT CASE WHEN s.date >= date('now', '-56 day') THEN substr(s.date, 1, 8) || CAST(((CAST(substr(s.date, 9, 2) AS INTEGER)-1)/7) AS INTEGER) END) AS training_weeks_8
                    FROM completed_sessions s
                    GROUP BY s.user_id
                ),
                set_stats AS (
                    SELECT s.user_id,
                           SUM(CASE WHEN s.date >= date('now', '-28 day') THEN 1 ELSE 0 END) AS sets_28,
                           COALESCE(SUM(CASE WHEN s.date >= date('now', '-28 day') THEN MAX(st.reps, 0) * MAX(st.weight_kg, 0) ELSE 0 END), 0) AS volume_28,
                           AVG(CASE WHEN s.date >= date('now', '-28 day') THEN MAX(st.reps, 0) * MAX(st.weight_kg, 0) END) AS avg_weighted_reps
                    FROM sets st
                    JOIN sessions s ON s.id = st.session_id
                    GROUP BY s.user_id
                ),
                exercise_variety AS (
                    SELECT ue.user_id, COUNT(DISTINCT ue.exercise_id) AS active_exercise_count
                    FROM user_exercises ue
                    WHERE COALESCE(ue.is_archived, 0) = 0
                    GROUP BY ue.user_id
                ),
                completion AS (
                    SELECT s.user_id,
                           AVG(CASE WHEN se.is_done = 1 THEN 1.0 ELSE 0.0 END) AS completion_ratio
                    FROM session_exercises se
                    JOIN sessions s ON s.id = se.session_id
                    WHERE s.date >= date('now', '-28 day')
                    GROUP BY s.user_id
                ),
                recent_best AS (
                    SELECT s.user_id, ue.exercise_id, MAX(st.weight_kg) AS max_w
                    FROM sets st
                    JOIN sessions s ON s.id = st.session_id
                    JOIN user_exercises ue ON ue.id = st.user_exercise_id
                    WHERE s.date >= date('now', '-14 day')
                    GROUP BY s.user_id, ue.exercise_id
                ),
                prev_best AS (
                    SELECT s.user_id, ue.exercise_id, MAX(st.weight_kg) AS max_w
                    FROM sets st
                    JOIN sessions s ON s.id = st.session_id
                    JOIN user_exercises ue ON ue.id = st.user_exercise_id
                    WHERE s.date >= date('now', '-28 day') AND s.date < date('now', '-14 day')
                    GROUP BY s.user_id, ue.exercise_id
                ),
                progression AS (
                    SELECT rb.user_id,
                           AVG(CASE WHEN pb.max_w > 0 THEN (rb.max_w - pb.max_w) / pb.max_w ELSE 0 END) AS progression_index
                    FROM recent_best rb
                    LEFT JOIN prev_best pb ON pb.user_id = rb.user_id AND pb.exercise_id = rb.exercise_id
                    GROUP BY rb.user_id
                )
                SELECT tm.user_id,
                       COALESCE(u.username, ''),
                       COALESCE(rs.sessions_28, 0),
                       COALESCE(rs.training_days_28, 0),
                       COALESCE(rs.training_weeks_8, 0),
                       COALESCE(ss.sets_28, 0),
                       COALESCE(ss.volume_28, 0),
                       COALESCE(ss.avg_weighted_reps, 0),
                       COALESCE(ev.active_exercise_count, 0),
                       COALESCE(c.completion_ratio, 0),
                       COALESCE(p.progression_index, 0),
                       COALESCE(up.title_frame_code, '')
                FROM team_members tm
                JOIN users u ON u.id = tm.user_id
                LEFT JOIN user_prefs up ON up.user_id = tm.user_id
                LEFT JOIN recent_sessions rs ON rs.user_id = tm.user_id
                LEFT JOIN set_stats ss ON ss.user_id = tm.user_id
                LEFT JOIN exercise_variety ev ON ev.user_id = tm.user_id
                LEFT JOIN completion c ON c.user_id = tm.user_id
                LEFT JOIN progression p ON p.user_id = tm.user_id
                WHERE tm.team_id=? AND tm.left_at IS NULL
                """,
                (team_id,),
            )
            rows = await cur.fetchall()
            members = []
            for row in rows:
                m = {
                    "training_days_28": int(row[3] or 0),
                    "sessions_28": int(row[2] or 0),
                    "training_weeks_8": int(row[4] or 0),
                    "sets_28": int(row[5] or 0),
                    "volume_28": float(row[6] or 0),
                    "avg_weighted_reps": float(row[7] or 0),
                    "active_exercise_count": int(row[8] or 0),
                    "completion_ratio": float(row[9] or 0),
                    "progression_index": float(row[10] or 0),
                }
                members.append(
                    {
                        "user_id": int(row[0]),
                        "username": (row[1] or "").strip() or f"athlete_{int(row[0])}",
                        "score": int(round(_leaderboard_score(m) * 100)),
                        "sessions_28": int(row[2] or 0),
                        "training_days_28": int(row[3] or 0),
                        "title_frame_code": (row[11] or None),
                    }
                )
            members.sort(key=lambda item: (-int(item["score"]), -int(item["sessions_28"]), int(item["user_id"])))

    return {"team": summary, "members": members}


async def upsert_team_daily_scores(day_utc: str, items: list[dict]) -> None:
    if not items:
        return
    now = _now_utc_iso()
    rows = [
        (
            int(item["team_id"]),
            day_utc,
            int(item.get("score") or 0),
            int(item.get("rank") or 0),
            int(item.get("members_count") or 0),
            int(item.get("sessions_7") or 0),
            int(item.get("sessions_28") or 0),
            now,
        )
        for item in items
    ]
    async with connect_db() as db:
        await db.executemany(
            """
            INSERT INTO team_daily_scores(team_id, day_utc, score, rank, members, sessions_7, sessions_28, created_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(team_id, day_utc) DO UPDATE SET
                score=excluded.score,
                rank=excluded.rank,
                members=excluded.members,
                sessions_7=excluded.sessions_7,
                sessions_28=excluded.sessions_28,
                created_at=excluded.created_at
            """,
            rows,
        )
        await db.commit()


async def _resolve_user_system_id(db, user_id: int, system_id: int | None = None) -> int:
    if system_id is not None and int(system_id) > 0:
        return int(system_id)
    cur = await db.execute("SELECT active_system_id FROM users WHERE id=?", (user_id,))
    row = await cur.fetchone()
    active_id = int((row[0] if row and row[0] is not None else 0) or 0)
    if active_id > 0:
        return active_id
    cur = await db.execute(
        "SELECT id FROM training_systems WHERE user_id=? ORDER BY id LIMIT 1",
        (user_id,),
    )
    row = await cur.fetchone()
    return int((row[0] if row else 0) or 0)


async def get_cosmetics(user_id: int, system_id: int | None = None) -> dict[str, int | str | None]:
    async with connect_db() as db:
        resolved_system_id = await _resolve_user_system_id(db, user_id, system_id)
        if resolved_system_id > 0:
            cur = await db.execute(
                """
                SELECT title_frame_code, badge_code, badge_hidden
                FROM training_system_cosmetics
                WHERE user_id=? AND system_id=?
                """,
                (user_id, resolved_system_id),
            )
            row = await cur.fetchone()
            if row:
                title_frame_code, badge_code, badge_hidden = row
                return {
                    "title_frame_code": title_frame_code or None,
                    "badge_code": badge_code or None,
                    "badge_hidden": 1 if badge_hidden == 1 else 0,
                }

        cur = await db.execute(
            """
            SELECT title_frame_code, badge_code, badge_hidden
            FROM user_prefs
            WHERE user_id=?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return {"title_frame_code": None, "badge_code": None, "badge_hidden": 0}
    title_frame_code, badge_code, badge_hidden = row
    return {
        "title_frame_code": title_frame_code or None,
        "badge_code": badge_code or None,
        "badge_hidden": 1 if badge_hidden == 1 else 0,
    }


async def clone_system_cosmetics(user_id: int, source_system_id: int, target_system_id: int):
    now = datetime.now(UTC).isoformat()
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT title_frame_code, badge_code, badge_hidden
            FROM training_system_cosmetics
            WHERE user_id=? AND system_id=?
            """,
            (user_id, int(source_system_id)),
        )
        row = await cur.fetchone()
        if row is None:
            cur = await db.execute(
                """
                SELECT title_frame_code, badge_code, badge_hidden
                FROM user_prefs
                WHERE user_id=?
                """,
                (user_id,),
            )
            row = await cur.fetchone()
        if row is None:
            await db.execute(
                "DELETE FROM training_system_cosmetics WHERE user_id=? AND system_id=?",
                (user_id, int(target_system_id)),
            )
            await db.commit()
            return
        title_frame_code, badge_code, badge_hidden = row
        await db.execute(
            """
            INSERT INTO training_system_cosmetics(user_id, system_id, title_frame_code, badge_code, badge_hidden, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id, system_id)
            DO UPDATE SET
                title_frame_code=excluded.title_frame_code,
                badge_code=excluded.badge_code,
                badge_hidden=excluded.badge_hidden,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                int(target_system_id),
                title_frame_code,
                badge_code,
                1 if badge_hidden == 1 else 0,
                now,
            ),
        )
        await db.commit()


async def set_title_frame(user_id: int, frame_code_or_null: str | None, system_id: int | None = None):
    now = datetime.now(UTC).isoformat()
    async with connect_db() as db:
        resolved_system_id = await _resolve_user_system_id(db, user_id, system_id)
        if resolved_system_id > 0:
            cur = await db.execute(
                """
                SELECT badge_code, badge_hidden
                FROM training_system_cosmetics
                WHERE user_id=? AND system_id=?
                """,
                (user_id, resolved_system_id),
            )
            row = await cur.fetchone()
            if row is None:
                cur = await db.execute(
                    """
                    SELECT badge_code, badge_hidden
                    FROM user_prefs
                    WHERE user_id=?
                    """,
                    (user_id,),
                )
                row = await cur.fetchone()
            badge_code = (row[0] if row else None)
            badge_hidden = (1 if row and row[1] == 1 else 0)
            await db.execute(
                """
                INSERT INTO training_system_cosmetics(user_id, system_id, title_frame_code, badge_code, badge_hidden, updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id, system_id)
                DO UPDATE SET
                    title_frame_code=excluded.title_frame_code,
                    badge_code=excluded.badge_code,
                    badge_hidden=excluded.badge_hidden,
                    updated_at=excluded.updated_at
                """,
                (user_id, resolved_system_id, frame_code_or_null, badge_code, badge_hidden, now),
            )
            await db.commit()
            return

        await db.execute(
            """
            INSERT INTO user_prefs(user_id, title_frame_code) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET title_frame_code=excluded.title_frame_code
            """,
            (user_id, frame_code_or_null),
        )
        await db.commit()


async def set_badge(user_id: int, badge_code_or_null: str | None, system_id: int | None = None):
    now = datetime.now(UTC).isoformat()
    async with connect_db() as db:
        resolved_system_id = await _resolve_user_system_id(db, user_id, system_id)
        if resolved_system_id > 0:
            cur = await db.execute(
                """
                SELECT title_frame_code, badge_hidden
                FROM training_system_cosmetics
                WHERE user_id=? AND system_id=?
                """,
                (user_id, resolved_system_id),
            )
            row = await cur.fetchone()
            if row is None:
                cur = await db.execute(
                    """
                    SELECT title_frame_code, badge_hidden
                    FROM user_prefs
                    WHERE user_id=?
                    """,
                    (user_id,),
                )
                row = await cur.fetchone()
            title_frame_code = (row[0] if row else None)
            badge_hidden = (1 if row and row[1] == 1 else 0)
            await db.execute(
                """
                INSERT INTO training_system_cosmetics(user_id, system_id, title_frame_code, badge_code, badge_hidden, updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id, system_id)
                DO UPDATE SET
                    title_frame_code=excluded.title_frame_code,
                    badge_code=excluded.badge_code,
                    badge_hidden=excluded.badge_hidden,
                    updated_at=excluded.updated_at
                """,
                (user_id, resolved_system_id, title_frame_code, badge_code_or_null, badge_hidden, now),
            )
            await db.commit()
            return

        await db.execute(
            """
            INSERT INTO user_prefs(user_id, badge_code) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET badge_code=excluded.badge_code
            """,
            (user_id, badge_code_or_null),
        )
        await db.commit()


async def set_badge_hidden(user_id: int, hidden: bool, system_id: int | None = None):
    value = 1 if hidden else 0
    now = datetime.now(UTC).isoformat()
    async with connect_db() as db:
        resolved_system_id = await _resolve_user_system_id(db, user_id, system_id)
        if resolved_system_id > 0:
            cur = await db.execute(
                """
                SELECT title_frame_code, badge_code
                FROM training_system_cosmetics
                WHERE user_id=? AND system_id=?
                """,
                (user_id, resolved_system_id),
            )
            row = await cur.fetchone()
            if row is None:
                cur = await db.execute(
                    """
                    SELECT title_frame_code, badge_code
                    FROM user_prefs
                    WHERE user_id=?
                    """,
                    (user_id,),
                )
                row = await cur.fetchone()
            title_frame_code = (row[0] if row else None)
            badge_code = (row[1] if row else None)
            await db.execute(
                """
                INSERT INTO training_system_cosmetics(user_id, system_id, title_frame_code, badge_code, badge_hidden, updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id, system_id)
                DO UPDATE SET
                    title_frame_code=excluded.title_frame_code,
                    badge_code=excluded.badge_code,
                    badge_hidden=excluded.badge_hidden,
                    updated_at=excluded.updated_at
                """,
                (user_id, resolved_system_id, title_frame_code, badge_code, value, now),
            )
            await db.commit()
            return

        await db.execute(
            """
            INSERT INTO user_prefs(user_id, badge_hidden) VALUES(?,?)
            ON CONFLICT(user_id) DO UPDATE SET badge_hidden=excluded.badge_hidden
            """,
            (user_id, value),
        )
        await db.commit()


async def log_user_event(user_id: int, event_type: str, created_at: str | None = None):
    ts = created_at or datetime.now(UTC).isoformat()
    async with connect_db() as db:
        await db.execute(
            """
            INSERT INTO user_events(user_id, event_type, created_at)
            VALUES(?,?,?)
            """,
            (user_id, event_type, ts),
        )
        await db.commit()


async def count_user_events(user_id: int, event_type: str) -> int:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM user_events WHERE user_id=? AND event_type=?",
            (user_id, event_type),
        )
        row = await cur.fetchone()
    return int((row[0] if row and row[0] is not None else 0) or 0)


async def record_system_copy(
    source_user_id: int,
    source_system_id: int,
    target_user_id: int,
    target_system_id: int,
):
    copied_at = datetime.now(UTC).isoformat()
    async with connect_db() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO training_system_copy_events(
                source_user_id, source_system_id, target_user_id, target_system_id, copied_at
            ) VALUES(?,?,?,?,?)
            """,
            (source_user_id, source_system_id, target_user_id, target_system_id, copied_at),
        )
        await db.commit()


async def mark_copy_trained(
    target_user_id: int,
    target_system_id: int,
    trained_at: str | None = None,
) -> int:
    ts = trained_at or datetime.now(UTC).isoformat()
    async with connect_db() as db:
        cur = await db.execute(
            """
            UPDATE training_system_copy_events
            SET first_trained_at = COALESCE(first_trained_at, ?),
                last_trained_at = ?
            WHERE target_user_id=? AND target_system_id=?
            """,
            (ts, ts, target_user_id, target_system_id),
        )
        await db.commit()
        return int(cur.rowcount or 0)


async def count_trained_copies_for_source(source_user_id: int) -> int:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT COUNT(*)
            FROM training_system_copy_events
            WHERE source_user_id=? AND first_trained_at IS NOT NULL
            """,
            (source_user_id,),
        )
        row = await cur.fetchone()
    return int((row[0] if row and row[0] is not None else 0) or 0)


async def count_trained_copies_for_source_system(source_user_id: int, source_system_id: int) -> int:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT COUNT(*)
            FROM training_system_copy_events
            WHERE source_user_id=? AND source_system_id=? AND first_trained_at IS NOT NULL
            """,
            (source_user_id, source_system_id),
        )
        row = await cur.fetchone()
    return int((row[0] if row and row[0] is not None else 0) or 0)


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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def get_running_entry(
    user_id: int,
    user_exercise_id: int,
    *,
    session_id: int | None,
    day_index: int,
    create: bool = True,
) -> tuple | None:
    async with connect_db() as db:
        if session_id is not None:
            cur = await db.execute(
                """
                SELECT id, distance_km, duration_sec, duration_ms, calories, heart_rate, is_draft, created_at
                FROM running_entries
                WHERE session_id=? AND user_exercise_id=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id, user_exercise_id),
            )
        else:
            cur = await db.execute(
                """
                SELECT id, distance_km, duration_sec, duration_ms, calories, heart_rate, is_draft, created_at
                FROM running_entries
                WHERE user_id=? AND user_exercise_id=? AND session_id IS NULL AND is_draft=1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, user_exercise_id),
            )
        row = await cur.fetchone()
        if row or not create:
            return row
        created_at = _now_iso()
        cur = await db.execute(
            "SELECT exercise_id FROM user_exercises WHERE id=? LIMIT 1",
            (user_exercise_id,),
        )
        exercise_row = await cur.fetchone()
        exercise_id = int(exercise_row[0]) if exercise_row and exercise_row[0] is not None else None
        await db.execute(
            """
            INSERT INTO running_entries(
                user_id, user_exercise_id, exercise_id, session_id, day_index,
                distance_km, duration_sec, duration_ms, calories, heart_rate, is_draft, created_at
            ) VALUES(?,?,?,?,?,0,0,0,0,0,1,?)
            """,
            (user_id, user_exercise_id, exercise_id, session_id, day_index, created_at),
        )
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        new_id = (await cur.fetchone())[0]
        return (new_id, 0.0, 0, 0, 0, 0, 1, created_at)


async def update_running_entry(
    entry_id: int,
    *,
    distance_km: float | None = None,
    duration_sec: int | None = None,
    duration_ms: int | None = None,
    calories: int | None = None,
    heart_rate: int | None = None,
    is_draft: int | None = None,
):
    fields: list[str] = []
    values: list = []
    if distance_km is not None:
        fields.append("distance_km=?")
        values.append(float(distance_km))
    if duration_sec is not None:
        fields.append("duration_sec=?")
        values.append(int(duration_sec))
    if duration_ms is not None:
        fields.append("duration_ms=?")
        values.append(int(duration_ms))
    if calories is not None:
        fields.append("calories=?")
        values.append(int(calories))
    if heart_rate is not None:
        fields.append("heart_rate=?")
        values.append(int(heart_rate))
    if is_draft is not None:
        fields.append("is_draft=?")
        values.append(int(is_draft))
    if not fields:
        return
    values.append(entry_id)
    async with connect_db() as db:
        await db.execute(
            f"UPDATE running_entries SET {', '.join(fields)} WHERE id=?",
            tuple(values),
        )
        await db.commit()


async def mark_running_entry_done(entry_id: int):
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE running_entries
            SET is_draft=0, created_at=?
            WHERE id=?
            """,
            (_now_iso(), entry_id),
        )
        await db.commit()


async def list_running_history(
    user_id: int,
    user_exercise_id: int | None = None,
    *,
    exercise_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[tuple]:
    if user_exercise_id is None and exercise_id is None:
        raise ValueError("Either user_exercise_id or exercise_id must be provided")
    params: list[object] = [user_id]
    use_exercise = exercise_id is not None
    if use_exercise:
        params.append(exercise_id)
    else:
        params.append(user_exercise_id)
    if start_date:
        params.append(start_date)
    if end_date:
        params.append(end_date)
    params.extend([limit, offset])
    where_clause = (
        "re.user_id=? AND re.exercise_id=?" if use_exercise else "re.user_id=? AND re.user_exercise_id=?"
    )
    if start_date:
        where_clause += " AND DATE(re.created_at) >= DATE(?)"
    if end_date:
        where_clause += " AND DATE(re.created_at) <= DATE(?)"
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT re.id, re.distance_km, re.duration_sec, re.duration_ms, re.calories, re.heart_rate, re.created_at, re.day_index
            FROM running_entries re
            WHERE """
            + where_clause
            + """
              AND re.is_draft=0
            ORDER BY re.created_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params),
        )
        return await cur.fetchall()


async def fetch_public_training_systems(user_id: int):
    async with connect_db() as db:
        systems_cur = await db.execute(
            "SELECT id, name, color FROM training_systems WHERE user_id=? ORDER BY id",
            (user_id,),
        )
        systems_rows = await systems_cur.fetchall()
        if not systems_rows:
            fallback_plan = await fetch_public_training_plan(user_id)
            if not fallback_plan:
                return []
            return [{
                "system_id": 0,
                "name": "Система",
                "color": "#2ea6ff",
                "days": fallback_plan,
            }]
        exercise_stats_cur = await db.execute(
            """
            SELECT ue.exercise_id,
                   COALESCE(AVG(per_session.sets_count), 0) AS sets_avg,
                   COALESCE(AVG(per_session.reps_avg), 0) AS reps_avg,
                   COALESCE(AVG(per_session.seconds_avg), 0) AS seconds_avg,
                   COALESCE(AVG(per_session.weight_avg), 0) AS weight_avg
            FROM (
                SELECT ue.exercise_id,
                       s.id AS session_id,
                       COUNT(st.id) AS sets_count,
                       AVG(st.reps) AS reps_avg,
                       AVG(st.seconds) AS seconds_avg,
                       AVG(st.weight_kg) AS weight_avg
                FROM sessions s
                JOIN sets st ON st.session_id=s.id
                JOIN user_exercises ue ON ue.id=st.user_exercise_id
                WHERE s.user_id=?
                GROUP BY ue.exercise_id, s.id
            ) per_session
            JOIN user_exercises ue ON ue.exercise_id=per_session.exercise_id AND ue.user_id=?
            GROUP BY ue.exercise_id
            """,
            (user_id, user_id),
        )
        stats_rows = await exercise_stats_cur.fetchall()
        stats_map = {
            int(r[0]): {
                "avg_sets": round(float(r[1] or 0), 1),
                "avg_reps": round(float(r[2] or 0), 1),
                "avg_seconds": round(float(r[3] or 0), 1),
                "avg_weight": round(float(r[4] or 0), 1),
            }
            for r in stats_rows
        }
        result = []
        for system_id, system_name, color in systems_rows:
            days_cur = await db.execute(
                """
                SELECT day_index, label
                FROM training_system_days
                WHERE system_id=? AND is_active=1
                ORDER BY day_index
                """,
                (int(system_id),),
            )
            day_rows = await days_cur.fetchall()
            ex_cur = await db.execute(
                """
                SELECT tse.day_index, tse.exercise_id, e.name
                FROM training_system_exercises tse
                JOIN exercises e ON e.id=tse.exercise_id
                WHERE tse.system_id=?
                ORDER BY tse.day_index, e.name COLLATE NOCASE
                """,
                (int(system_id),),
            )
            exercises_rows = await ex_cur.fetchall()
            grouped: dict[int, list[dict]] = {}
            for day_index, exercise_id, ex_name in exercises_rows:
                ex_id = int(exercise_id)
                grouped.setdefault(int(day_index), []).append(
                    {
                        "exercise_id": ex_id,
                        "name": ex_name,
                        **stats_map.get(
                            ex_id,
                            {
                                "avg_sets": 0.0,
                                "avg_reps": 0.0,
                                "avg_seconds": 0.0,
                                "avg_weight": 0.0,
                            },
                        ),
                    }
                )
            result.append(
                {
                    "system_id": int(system_id),
                    "name": (system_name or "").strip() or "Система",
                    "color": (color or "#2ea6ff").strip() or "#2ea6ff",
                    "days": [
                        {
                            "day_index": int(day_index),
                            "label": label or f"День {int(day_index)}",
                            "exercises": grouped.get(int(day_index), []),
                        }
                        for day_index, label in day_rows
                    ],
                }
            )
        return result


async def get_running_entry_by_id(entry_id: int) -> tuple | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, user_id, user_exercise_id, session_id, day_index,
                   distance_km, duration_sec, duration_ms, calories, heart_rate, is_draft, created_at
            FROM running_entries
            WHERE id=?
            """,
            (entry_id,),
        )
        return await cur.fetchone()


async def add_custom_measurement(
    user_id: int, name: str, category_code: str | None = None
) -> str:
    async with connect_db() as db:
        created_at = _now_iso()
        await db.execute(
            """
            INSERT INTO user_measurement_custom(user_id, code, name, category_code, created_at)
            VALUES(?,?,?,?,?)
            """,
            (user_id, "", name, category_code or "", created_at),
        )
        cur = await db.execute("SELECT last_insert_rowid()")
        row = await cur.fetchone()
        raw_id = row[0]
        code = f"uc{user_id}_{raw_id}"
        await db.execute(
            "UPDATE user_measurement_custom SET code=? WHERE id=?",
            (code, raw_id),
        )
        await db.commit()
        return code


async def list_custom_measurements(user_id: int) -> list[tuple[str, str, str]]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT code, name, COALESCE(category_code, '')
            FROM user_measurement_custom
            WHERE user_id=?
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        return [(row[0], row[1], row[2]) for row in rows if row[0]]


async def get_custom_measurement(user_id: int, code: str) -> tuple[str, str] | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT code, name
            FROM user_measurement_custom
            WHERE user_id=? AND code=?
            LIMIT 1
            """,
            (user_id, code),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return row[0], row[1]


async def delete_custom_measurement(user_id: int, code: str) -> bool:
    async with connect_db() as db:
        await db.execute(
            "DELETE FROM user_measurements WHERE user_id=? AND metric=?",
            (user_id, code),
        )
        cur = await db.execute(
            "DELETE FROM user_measurement_custom WHERE user_id=? AND code=?",
            (user_id, code),
        )
        await db.commit()
        return cur.rowcount > 0


async def add_measurement_category(user_id: int, letter: str, name: str) -> str:
    async with connect_db() as db:
        created_at = _now_iso()
        await db.execute(
            """
            INSERT INTO user_measurement_categories(user_id, code, letter, name, created_at)
            VALUES(?,?,?,?,?)
            """,
            (user_id, "", letter, name, created_at),
        )
        cur = await db.execute("SELECT last_insert_rowid()")
        row = await cur.fetchone()
        raw_id = row[0]
        code = f"ucg{user_id}_{raw_id}"
        await db.execute(
            "UPDATE user_measurement_categories SET code=? WHERE id=?",
            (code, raw_id),
        )
        await db.commit()
        return code


async def list_measurement_categories(user_id: int) -> list[tuple[str, str, str]]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT code, letter, name
            FROM user_measurement_categories
            WHERE user_id=?
            ORDER BY letter ASC, created_at DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        return [
            (row[0], row[1], row[2])
            for row in rows
            if row[0] and row[1]
        ]


async def delete_measurement_category(user_id: int, code: str) -> bool:
    async with connect_db() as db:
        cur = await db.execute(
            "DELETE FROM user_measurement_categories WHERE user_id=? AND code=?",
            (user_id, code),
        )
        await db.commit()
        return cur.rowcount > 0


async def find_user_by_trainer_code(code: str):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, username, trainer_accepts_requests
            FROM users
            WHERE trainer_code = ? AND is_trainer = 1
            """,
            (code,),
        )
        return await cur.fetchone()


async def set_trainer_accepting_requests(user_id: int, accepting: bool) -> None:
    async with connect_db() as db:
        await db.execute(
            "UPDATE users SET trainer_accepts_requests = ? WHERE id=?",
            (1 if accepting else 0, user_id),
        )
        await db.commit()


async def reactivate_trainer_links(trainer_user_id: int) -> list[int]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT trainee_user_id
            FROM trainer_links
            WHERE trainer_user_id = ?
              AND status = 'trainer_disabled'
            """,
            (trainer_user_id,),
        )
        rows = await cur.fetchall()
        trainee_ids = [int(row[0]) for row in rows if row and row[0] is not None]
        if trainee_ids:
            await db.execute(
                """
                UPDATE trainer_links
                SET status = 'accepted'
                WHERE trainer_user_id = ?
                  AND status = 'trainer_disabled'
                """,
                (trainer_user_id,),
            )
            await db.commit()
        return trainee_ids


async def get_trainer_link(trainer_user_id: int, trainee_user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, status, can_edit_plan, trainer_label, trainee_label
            FROM trainer_links
            WHERE trainer_user_id = ? AND trainee_user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (trainer_user_id, trainee_user_id),
        )
        return await cur.fetchone()


async def get_active_trainer_link_for_trainee(trainee_user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, trainer_user_id, status, can_edit_plan, trainer_label, trainee_label
            FROM trainer_links
            WHERE trainee_user_id = ? AND status = 'accepted'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (trainee_user_id,),
        )
        return await cur.fetchone()


async def get_latest_trainer_link_for_trainee(trainee_user_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, trainer_user_id, status, can_edit_plan, trainer_label, trainee_label
            FROM trainer_links
            WHERE trainee_user_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (trainee_user_id,),
        )
        return await cur.fetchone()


async def create_trainer_request(
    trainer_user_id: int, trainee_user_id: int, *, can_edit_plan: bool = False
):
    async with connect_db() as db:
        created_at = _now_iso()
        cur = await db.execute(
            """
            INSERT INTO trainer_links(
                trainer_user_id,
                trainee_user_id,
                status,
                can_edit_plan,
                created_at
            )
            VALUES(?, ?, 'pending', ?, ?)
            """,
            (
                trainer_user_id,
                trainee_user_id,
                1 if can_edit_plan else 0,
                created_at,
            ),
        )
        await db.commit()
        return cur.lastrowid


async def clear_trainer_requests(trainer_user_id: int) -> None:
    async with connect_db() as db:
        await db.execute(
            "DELETE FROM trainer_links WHERE trainer_user_id = ? AND status = 'pending'",
            (trainer_user_id,),
        )
        await db.commit()


async def list_trainer_requests(trainer_user_id: int, limit: int = 20, offset: int = 0):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, trainee_user_id, status, created_at
            FROM trainer_links
            WHERE trainer_user_id = ? AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (trainer_user_id, limit, offset),
        )
        return await cur.fetchall()


async def count_trainer_requests(trainer_user_id: int) -> int:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM trainer_links WHERE trainer_user_id = ? AND status = 'pending'",
            (trainer_user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def list_trainer_trainees(trainer_user_id: int, limit: int = 20, offset: int = 0):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, trainee_user_id, trainer_label, can_edit_plan, created_at
            FROM trainer_links
            WHERE trainer_user_id = ? AND status = 'accepted'
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (trainer_user_id, limit, offset),
        )
        return await cur.fetchall()


async def count_trainer_trainees(trainer_user_id: int) -> int:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM trainer_links WHERE trainer_user_id = ? AND status = 'accepted'",
            (trainer_user_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def update_trainer_link_status(link_id: int, status: str):
    async with connect_db() as db:
        await db.execute(
            "UPDATE trainer_links SET status = ? WHERE id = ?",
            (status, link_id),
        )
        await db.commit()


async def deactivate_trainer_links(
    trainer_user_id: int, *, new_status: str = "trainer_disabled"
) -> list[int]:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT trainee_user_id
            FROM trainer_links
            WHERE trainer_user_id = ? AND status = 'accepted'
            """,
            (trainer_user_id,),
        )
        rows = await cur.fetchall()
        trainee_ids = [int(row[0]) for row in rows if row and row[0] is not None]
        if trainee_ids:
            await db.execute(
                """
                UPDATE trainer_links
                SET status = ?
                WHERE trainer_user_id = ? AND status = 'accepted'
                """,
                (new_status, trainer_user_id),
            )
            await db.commit()
        return trainee_ids


async def update_trainer_link_permissions(link_id: int, can_edit_plan: int):
    async with connect_db() as db:
        await db.execute(
            "UPDATE trainer_links SET can_edit_plan = ? WHERE id = ?",
            (can_edit_plan, link_id),
        )
        await db.commit()


async def update_trainer_label(link_id: int, trainer_label: str | None):
    async with connect_db() as db:
        await db.execute(
            "UPDATE trainer_links SET trainer_label = ? WHERE id = ?",
            (trainer_label, link_id),
        )
        await db.commit()


async def update_trainee_label(link_id: int, trainee_label: str | None):
    async with connect_db() as db:
        await db.execute(
            "UPDATE trainer_links SET trainee_label = ? WHERE id = ?",
            (trainee_label, link_id),
        )
        await db.commit()


async def list_user_exercises_for_mapping(
    user_id: int, query: str | None = None, muscle: str | None = None
):
    async with connect_db() as db:
        params: list[object] = [user_id, user_id]
        where = ["ue.user_id=?", "ue.is_archived=0"]
        if query:
            where.append("LOWER(e.name) LIKE ?")
            params.append(f"%{query.lower()}%")
        if muscle:
            if muscle == "none":
                where.append("(e.muscle_group IS NULL OR e.muscle_group='')")
            else:
                where.append("e.muscle_group=?")
                params.append(muscle)
        sql = (
            "SELECT DISTINCT e.id, e.name, e.muscle_group, "
            "EXISTS(SELECT 1 FROM user_exercise_muscles uem WHERE uem.user_id=? AND uem.exercise_id=e.id) AS has_override "
            "FROM user_exercises ue "
            "JOIN exercises e ON e.id = ue.exercise_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY e.name COLLATE NOCASE"
        )
        cur = await db.execute(sql, params)
        return await cur.fetchall()


async def set_exercise_muscle_group(exercise_id: int, muscle_group: str | None):
    async with connect_db() as db:
        await db.execute(
            "UPDATE exercises SET muscle_group=? WHERE id=?",
            (muscle_group, exercise_id),
        )
        await db.commit()


async def resolve_exercise_muscles(user_id: int, exercise_ids: Sequence[int]):
    if not exercise_ids:
        return {}

    ids = tuple({int(eid) for eid in exercise_ids if eid is not None})
    if not ids:
        return {}

    placeholders = ",".join("?" for _ in ids)
    result: dict[int, list[dict[str, float]]] = {}

    async with connect_db() as db:
        # User overrides
        cur = await db.execute(
            f"""
            SELECT exercise_id, muscle_code, weight_pct
            FROM user_exercise_muscles
            WHERE user_id=? AND exercise_id IN ({placeholders})
            """,
            (user_id, *ids),
        )
        for ex_id, muscle_code, pct in await cur.fetchall():
            result.setdefault(int(ex_id), []).append({"muscle_code": muscle_code, "weight_pct": float(pct)})

        missing = [eid for eid in ids if eid not in result]
        missing_ph = ",".join("?" for _ in missing) if missing else ""

        # Exercise defaults
        if missing:
            cur = await db.execute(
                f"""
                SELECT exercise_id, muscle_code, weight_pct
                FROM exercise_muscles
                WHERE exercise_id IN ({missing_ph})
                """,
                missing,
            )
            for ex_id, muscle_code, pct in await cur.fetchall():
                result.setdefault(int(ex_id), []).append({"muscle_code": muscle_code, "weight_pct": float(pct)})

        # Muscle groups for fallback
        cur = await db.execute(
            f"SELECT id, muscle_group FROM exercises WHERE id IN ({placeholders})",
            ids,
        )
        mg_map = {int(row[0]): (row[1] or "") for row in await cur.fetchall()}

    for ex_id in ids:
        if ex_id in result:
            continue
        mg = (mg_map.get(ex_id) or "").strip().lower()
        if mg in ANATOMICAL_GROUPS:
            result[ex_id] = [{"muscle_code": mg, "weight_pct": 100.0}]
        elif mg in {"run", "metcon", "cardio"}:
            result[ex_id] = [{"muscle_code": "cardio", "weight_pct": 100.0}]
        else:
            result[ex_id] = [{"muscle_code": "other", "weight_pct": 100.0}]

    return result


async def get_user_anatomy(user_id: int, exercise_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT muscle_code, weight_pct
            FROM user_exercise_muscles
            WHERE user_id=? AND exercise_id=?
            ORDER BY muscle_code
            """,
            (user_id, exercise_id),
        )
        return await cur.fetchall()


async def get_default_anatomy(exercise_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT muscle_code, weight_pct
            FROM exercise_muscles
            WHERE exercise_id=?
            ORDER BY muscle_code
            """,
            (exercise_id,),
        )
        return await cur.fetchall()


async def set_user_anatomy(user_id: int, exercise_id: int, items: Sequence[dict]):
    async with connect_db() as db:
        await db.execute(
            "DELETE FROM user_exercise_muscles WHERE user_id=? AND exercise_id=?",
            (user_id, exercise_id),
        )
        rows = [
            (
                user_id,
                exercise_id,
                (item.get("muscle_code") or "").strip().lower(),
                float(item.get("weight_pct") or 0),
            )
            for item in items
        ]
        if rows:
            await db.executemany(
                """
                INSERT INTO user_exercise_muscles(user_id, exercise_id, muscle_code, weight_pct)
                VALUES (?,?,?,?)
                """,
                rows,
            )
        await db.commit()


async def clear_user_anatomy(user_id: int, exercise_id: int):
    async with connect_db() as db:
        await db.execute(
            "DELETE FROM user_exercise_muscles WHERE user_id=? AND exercise_id=?",
            (user_id, exercise_id),
        )
        await db.commit()


async def fetch_session_sets_with_exercises(user_id: int, session_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT st.reps, st.seconds, st.weight_kg, ue.exercise_id, e.name
            FROM sets st
            JOIN sessions s ON s.id = st.session_id
            JOIN user_exercises ue ON ue.id = st.user_exercise_id
            JOIN exercises e ON e.id = ue.exercise_id
            WHERE st.session_id=? AND st.is_warmup=0 AND s.user_id=?
            """,
            (session_id, user_id),
        )
        rows = await cur.fetchall()
        return [
            {
                "reps": int(row[0]),
                "seconds": int(row[1]),
                "weight_kg": float(row[2] or 0.0),
                "exercise_id": int(row[3]),
                "exercise_name": row[4],
            }
            for row in rows
        ]


async def fetch_sets_in_date_range(user_id: int, start_date: str, end_date: str):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT st.reps, st.seconds, st.weight_kg, ue.exercise_id, e.name, s.date
            FROM sets st
            JOIN sessions s ON s.id = st.session_id
            JOIN user_exercises ue ON ue.id = st.user_exercise_id
            JOIN exercises e ON e.id = ue.exercise_id
            WHERE s.user_id=? AND s.date BETWEEN ? AND ? AND st.is_warmup=0
            """,
            (user_id, start_date, end_date),
        )
        rows = await cur.fetchall()
        return [
            {
                "reps": int(row[0]),
                "seconds": int(row[1]),
                "weight_kg": float(row[2] or 0.0),
                "exercise_id": int(row[3]),
                "exercise_name": row[4],
                "session_date": row[5],
            }
            for row in rows
        ]


def _safe_ratio(value: float, normalizer: float) -> float:
    if normalizer <= 0:
        return 0.0
    return max(0.0, min(1.0, float(value) / float(normalizer)))


def _leaderboard_score(row: dict) -> float:
    attendance = _safe_ratio(row.get("training_days_28", 0), 20)
    workout_count = _safe_ratio(row.get("sessions_28", 0), 26)
    volume = _safe_ratio(row.get("volume_28", 0), 260000)
    sets = _safe_ratio(row.get("sets_28", 0), 320)
    exercise_variety = _safe_ratio(row.get("active_exercise_count", 0), 40)
    weekly_consistency = _safe_ratio(row.get("training_weeks_8", 0), 8)
    progression_signal = _safe_ratio(row.get("progression_index", 0), 1)
    completion_ratio = _safe_ratio(row.get("completion_ratio", 0), 1)
    average_intensity = _safe_ratio(row.get("avg_weighted_reps", 0), 900)
    total = (
        attendance * 0.17
        + workout_count * 0.10
        + volume * 0.13
        + sets * 0.09
        + exercise_variety * 0.08
        + weekly_consistency * 0.10
        + progression_signal * 0.15
        + completion_ratio * 0.09
        + average_intensity * 0.09
    )
    return max(0.0, min(1.0, total))


def _to_top_percent(score_0_100: int) -> int:
    if score_0_100 >= 96:
        return 1
    if score_0_100 >= 90:
        return 3
    if score_0_100 >= 82:
        return 5
    if score_0_100 >= 70:
        return 10
    if score_0_100 >= 55:
        return 25
    if score_0_100 >= 40:
        return 40
    if score_0_100 >= 25:
        return 60
    return 100


async def fetch_productivity_leaderboard(limit: int = 10, offset: int = 0):
    async with connect_db() as db:
        cur = await db.execute(
            """
            WITH users_base AS (
                SELECT u.id, u.username
                FROM users u
                WHERE COALESCE(u.leaderboard_visible, 1) = 1
                  AND (
                      EXISTS (SELECT 1 FROM sessions s WHERE s.user_id=u.id)
                      OR EXISTS (SELECT 1 FROM sets st JOIN sessions s2 ON s2.id=st.session_id WHERE s2.user_id=u.id)
                      OR EXISTS (SELECT 1 FROM user_exercises ue WHERE ue.user_id=u.id AND COALESCE(ue.is_archived,0)=0)
                  )
            ),
            recent_sessions AS (
                SELECT s.user_id,
                       COUNT(*) AS sessions_28,
                       COUNT(DISTINCT s.date) AS training_days_28,
                       COUNT(DISTINCT substr(s.date, 1, 8) || CAST(((CAST(substr(s.date, 9, 2) AS INTEGER)-1)/7) AS INTEGER)) AS training_weeks_8
                FROM sessions s
                WHERE s.date >= date('now', '-56 day')
                GROUP BY s.user_id
            ),
            set_stats AS (
                SELECT s.user_id,
                       SUM(CASE WHEN s.date >= date('now', '-28 day') THEN 1 ELSE 0 END) AS sets_28,
                       COALESCE(SUM(CASE WHEN s.date >= date('now', '-28 day') THEN MAX(st.reps, 0) * MAX(st.weight_kg, 0) ELSE 0 END), 0) AS volume_28,
                       AVG(CASE WHEN s.date >= date('now', '-28 day') THEN MAX(st.reps, 0) * MAX(st.weight_kg, 0) END) AS avg_weighted_reps
                FROM sets st
                JOIN sessions s ON s.id = st.session_id
                GROUP BY s.user_id
            ),
            exercise_variety AS (
                SELECT ue.user_id, COUNT(DISTINCT ue.exercise_id) AS active_exercise_count
                FROM user_exercises ue
                WHERE ue.is_archived = 0
                GROUP BY ue.user_id
            ),
            completion AS (
                SELECT s.user_id,
                       AVG(CASE WHEN se.is_done = 1 THEN 1.0 ELSE 0.0 END) AS completion_ratio
                FROM session_exercises se
                JOIN sessions s ON s.id = se.session_id
                WHERE s.date >= date('now', '-28 day')
                GROUP BY s.user_id
            ),
            recent_best AS (
                SELECT s.user_id, ue.exercise_id, MAX(st.weight_kg) AS max_w
                FROM sets st
                JOIN sessions s ON s.id = st.session_id
                JOIN user_exercises ue ON ue.id = st.user_exercise_id
                WHERE s.date >= date('now', '-14 day')
                GROUP BY s.user_id, ue.exercise_id
            ),
            prev_best AS (
                SELECT s.user_id, ue.exercise_id, MAX(st.weight_kg) AS max_w
                FROM sets st
                JOIN sessions s ON s.id = st.session_id
                JOIN user_exercises ue ON ue.id = st.user_exercise_id
                WHERE s.date >= date('now', '-28 day') AND s.date < date('now', '-14 day')
                GROUP BY s.user_id, ue.exercise_id
            ),
            progression AS (
                SELECT rb.user_id,
                       AVG(CASE WHEN pb.max_w > 0 THEN (rb.max_w - pb.max_w) / pb.max_w ELSE 0 END) AS progression_index
                FROM recent_best rb
                LEFT JOIN prev_best pb ON pb.user_id = rb.user_id AND pb.exercise_id = rb.exercise_id
                GROUP BY rb.user_id
            )
            SELECT ub.id,
                   ub.username,
                   COALESCE(rs.sessions_28, 0) AS sessions_28,
                   COALESCE(rs.training_days_28, 0) AS training_days_28,
                   COALESCE(rs.training_weeks_8, 0) AS training_weeks_8,
                   COALESCE(ss.sets_28, 0) AS sets_28,
                   COALESCE(ss.volume_28, 0) AS volume_28,
                   COALESCE(ss.avg_weighted_reps, 0) AS avg_weighted_reps,
                   COALESCE(ev.active_exercise_count, 0) AS active_exercise_count,
                   COALESCE(c.completion_ratio, 0) AS completion_ratio,
                   COALESCE(p.progression_index, 0) AS progression_index
            FROM users_base ub
            LEFT JOIN recent_sessions rs ON rs.user_id = ub.id
            LEFT JOIN set_stats ss ON ss.user_id = ub.id
            LEFT JOIN exercise_variety ev ON ev.user_id = ub.id
            LEFT JOIN completion c ON c.user_id = ub.id
            LEFT JOIN progression p ON p.user_id = ub.id
            """
        )
        rows = await cur.fetchall()

    ranked: list[dict] = []
    for row in rows:
        data = {
            "user_id": int(row[0]),
            "username": (row[1] or "").strip(),
            "sessions_28": int(row[2] or 0),
            "training_days_28": int(row[3] or 0),
            "training_weeks_8": int(row[4] or 0),
            "sets_28": int(row[5] or 0),
            "volume_28": float(row[6] or 0),
            "avg_weighted_reps": float(row[7] or 0),
            "active_exercise_count": int(row[8] or 0),
            "completion_ratio": float(row[9] or 0),
            "progression_index": float(row[10] or 0),
        }
        raw = _leaderboard_score(data)
        score = int(round(raw * 100))
        data["score"] = score
        data["top_percent"] = _to_top_percent(score)
        ranked.append(data)

    ranked.sort(
        key=lambda item: (
            -item["score"],
            -item["training_days_28"],
            -item["volume_28"],
            -item["sets_28"],
            item["user_id"],
        )
    )
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx
        item["username"] = item["username"] or f"athlete_{item['user_id']}"
    total = len(ranked)
    paged = ranked[offset: offset + max(1, limit)]
    return paged, total, ranked


async def fetch_public_training_plan(user_id: int):
    async with connect_db() as db:
        days_cur = await db.execute(
            """
            SELECT day_index, label
            FROM user_days
            WHERE user_id=? AND is_active=1
            ORDER BY day_index
            """,
            (user_id,),
        )
        days_rows = await days_cur.fetchall()
        ex_cur = await db.execute(
            """
            SELECT ue.day_index,
                   ue.exercise_id,
                   e.name,
                   COALESCE(stats.sets_avg, 0) AS sets_avg,
                   COALESCE(stats.reps_avg, 0) AS reps_avg,
                   COALESCE(stats.seconds_avg, 0) AS seconds_avg,
                   COALESCE(stats.weight_avg, 0) AS weight_avg
            FROM user_exercises ue
            JOIN exercises e ON e.id = ue.exercise_id
            LEFT JOIN (
              SELECT ue2.user_id,
                     ue2.exercise_id,
                     AVG(per_session.sets_count) AS sets_avg,
                     AVG(per_session.reps_avg) AS reps_avg,
                     AVG(per_session.seconds_avg) AS seconds_avg,
                     AVG(per_session.weight_avg) AS weight_avg
              FROM (
                SELECT s.user_id,
                       ue.id AS user_exercise_id,
                       ue.exercise_id,
                       COUNT(st.id) AS sets_count,
                       AVG(st.reps) AS reps_avg,
                       AVG(st.seconds) AS seconds_avg,
                       AVG(st.weight_kg) AS weight_avg
                FROM sessions s
                JOIN sets st ON st.session_id = s.id
                JOIN user_exercises ue ON ue.id = st.user_exercise_id
                GROUP BY s.user_id, ue.id, ue.exercise_id, s.id
              ) per_session
              JOIN user_exercises ue2 ON ue2.id = per_session.user_exercise_id
              GROUP BY ue2.user_id, ue2.exercise_id
            ) stats ON stats.user_id = ue.user_id AND stats.exercise_id = ue.exercise_id
            WHERE ue.user_id=? AND ue.is_archived=0
            ORDER BY ue.day_index, e.name COLLATE NOCASE
            """,
            (user_id,),
        )
        ex_rows = await ex_cur.fetchall()

    grouped: dict[int, list[dict]] = {}
    for row in ex_rows:
        grouped.setdefault(int(row[0]), []).append(
            {
                "exercise_id": int(row[1]),
                "name": row[2],
                "avg_sets": round(float(row[3] or 0), 1),
                "avg_reps": round(float(row[4] or 0), 1),
                "avg_seconds": round(float(row[5] or 0), 1),
                "avg_weight": round(float(row[6] or 0), 1),
            }
        )
    days = []
    for day_index, label in days_rows:
        d = int(day_index)
        days.append({"day_index": d, "label": label or f"День {d}", "exercises": grouped.get(d, [])})
    return days


async def copy_training_plan_from_user(source_user_id: int, target_user_id: int):
    async with connect_db() as db:
        src_days_cur = await db.execute(
            "SELECT day_index, label FROM user_days WHERE user_id=? AND is_active=1 ORDER BY day_index",
            (source_user_id,),
        )
        src_days = await src_days_cur.fetchall()
        if not src_days:
            return {"days": 0, "exercises": 0}

        trg_days_cur = await db.execute(
            "SELECT day_index FROM user_days WHERE user_id=? AND is_active=1 ORDER BY day_index",
            (target_user_id,),
        )
        trg_days = [int(r[0]) for r in await trg_days_cur.fetchall()]
        day_map: dict[int, int] = {}
        for idx, (src_day, _label) in enumerate(src_days):
            if idx < len(trg_days):
                day_map[int(src_day)] = trg_days[idx]

        copied = 0
        for src_day, _label in src_days:
            mapped_day = day_map.get(int(src_day))
            if not mapped_day:
                continue
            ex_cur = await db.execute(
                """
                SELECT e.name
                FROM user_exercises ue
                JOIN exercises e ON e.id = ue.exercise_id
                WHERE ue.user_id=? AND ue.day_index=? AND ue.is_archived=0
                ORDER BY e.name COLLATE NOCASE
                """,
                (source_user_id, int(src_day)),
            )
            for (name,) in await ex_cur.fetchall():
                norm = (name or "").strip()
                if not norm:
                    continue
                ex_id_cur = await db.execute("SELECT id FROM exercises WHERE name=?", (norm,))
                row = await ex_id_cur.fetchone()
                if row:
                    ex_id = int(row[0])
                else:
                    cur = await db.execute(
                        "INSERT INTO exercises(name, muscle_group) VALUES(?, ?)",
                        (norm, "other"),
                    )
                    ex_id = int(cur.lastrowid)
                await db.execute(
                    """
                    INSERT OR IGNORE INTO user_exercises(user_id, exercise_id, day_index, is_archived)
                    VALUES (?, ?, ?, 0)
                    """,
                    (target_user_id, ex_id, mapped_day),
                )
                copied += 1
        await db.commit()
    return {"days": len(day_map), "exercises": copied}


async def copy_training_system_from_user(source_user_id: int, target_user_id: int, source_system_id: int | None = None, fallback_system_name: str | None = None):
    def _custom_group_id(group_code: str | None) -> int | None:
        raw = (group_code or "").strip().lower()
        if not raw.startswith("u"):
            return None
        try:
            value = int(raw[1:])
        except ValueError:
            return None
        return value if value > 0 else None

    async with connect_db() as db:
        systems_cur = await db.execute(
            "SELECT id, name, color FROM training_systems WHERE user_id=? ORDER BY id",
            (source_user_id,),
        )
        systems = await systems_cur.fetchall()
        if not systems:
            now = datetime.now(UTC).isoformat()
            fallback_name = (fallback_system_name or "").strip() or "Скопированная система"
            cur = await db.execute(
                "INSERT INTO training_systems(user_id, name, color, created_at) VALUES(?,?,?,?)",
                (target_user_id, fallback_name, "#2ea6ff", now),
            )
            new_system_id = int(cur.lastrowid)
            day_map = await fetch_public_training_plan(source_user_id)
            ex_count = 0
            for day in day_map:
                day_index = int(day.get("day_index") or 0)
                if day_index <= 0:
                    continue
                day_label = (day.get("label") or f"День {day_index}").strip() or f"День {day_index}"
                await db.execute(
                    "INSERT INTO training_system_days(system_id, day_index, label, is_active) VALUES(?,?,?,?)",
                    (new_system_id, day_index, day_label, 1),
                )
                for ex in (day.get("exercises") or []):
                    ex_name = (ex.get("name") or "").strip()
                    if not ex_name:
                        continue
                    ex_cur = await db.execute("SELECT id FROM exercises WHERE LOWER(name)=LOWER(?) LIMIT 1", (ex_name,))
                    ex_row = await ex_cur.fetchone()
                    if ex_row:
                        ex_id = int(ex_row[0])
                    else:
                        created_ex = await db.execute("INSERT INTO exercises(name, muscle_group) VALUES(?,?)", (ex_name, "other"))
                        ex_id = int(created_ex.lastrowid)
                    await db.execute(
                        "INSERT OR IGNORE INTO training_system_exercises(system_id, day_index, exercise_id) VALUES(?,?,?)",
                        (new_system_id, day_index, ex_id),
                    )
                    ex_count += 1
            if ex_count == 0:
                await db.execute("DELETE FROM training_systems WHERE id=?", (new_system_id,))
                await db.commit()
                return {"system_id": None, "days": 0, "exercises": 0}
            await db.commit()
            await apply_system_to_current_plan(target_user_id, new_system_id)
            return {"system_id": int(new_system_id), "days": len(day_map), "exercises": ex_count}

        selected = None
        if source_system_id is not None:
            for row in systems:
                if int(row[0]) == int(source_system_id):
                    selected = row
                    break
        if selected is None:
            selected = systems[0]

        selected_system_id = int(selected[0])
        fallback_name = (fallback_system_name or "").strip()
        name = (selected[1] or fallback_name or "Скопированная система").strip() or (fallback_name or "Скопированная система")
        color = (selected[2] or "#2ea6ff").strip() or "#2ea6ff"

        days_cur = await db.execute(
            """
            SELECT day_index, label, is_active
            FROM training_system_days
            WHERE system_id=?
            ORDER BY day_index
            """,
            (selected_system_id,),
        )
        source_days = await days_cur.fetchall()

        reminders_cur = await db.execute(
            """
            SELECT day_no, dow, hour, minute
            FROM training_system_reminders
            WHERE system_id=?
            ORDER BY day_no
            """,
            (selected_system_id,),
        )
        source_reminders = await reminders_cur.fetchall()

        ex_cur = await db.execute(
            """
            SELECT tse.day_index, e.name, e.muscle_group, tse.exercise_id
            FROM training_system_exercises tse
            JOIN exercises e ON e.id=tse.exercise_id
            WHERE tse.system_id=?
            ORDER BY tse.day_index, e.name COLLATE NOCASE
            """,
            (selected_system_id,),
        )
        source_exercises = await ex_cur.fetchall()

        source_meta_cur = await db.execute(
            """
            SELECT day_index, exercise_id, source_payload
            FROM training_system_exercise_sources
            WHERE system_id=?
            """,
            (selected_system_id,),
        )
        source_meta_rows = await source_meta_cur.fetchall()
        source_meta_map: dict[tuple[int, int], dict] = {}
        for day_no, ex_id, payload in source_meta_rows:
            try:
                source_meta_map[(int(day_no), int(ex_id))] = json.loads(payload or '{}')
            except Exception:
                source_meta_map[(int(day_no), int(ex_id))] = {}

        now = datetime.now(UTC).isoformat()
        cur = await db.execute(
            "INSERT INTO training_systems(user_id, name, color, created_at) VALUES(?,?,?,?)",
            (target_user_id, name, color, now),
        )
        new_system_id = int(cur.lastrowid)

        custom_groups_cache: dict[str, str] = {}

        async def ensure_target_custom_group(group_code: str | None) -> str:
            code = (group_code or "").strip().lower()
            cached = custom_groups_cache.get(code)
            if cached:
                return cached
            src_group_id = _custom_group_id(code)
            if src_group_id is None:
                custom_groups_cache[code] = code
                return code
            src_group_cur = await db.execute(
                "SELECT name FROM user_muscle_groups WHERE id=? AND user_id=?",
                (src_group_id, source_user_id),
            )
            src_group_row = await src_group_cur.fetchone()
            if not src_group_row:
                custom_groups_cache[code] = code
                return code
            group_name = (src_group_row[0] or "").strip()
            if not group_name:
                custom_groups_cache[code] = code
                return code
            trg_group_cur = await db.execute(
                "SELECT id FROM user_muscle_groups WHERE user_id=? AND LOWER(name)=LOWER(?)",
                (target_user_id, group_name),
            )
            trg_group_row = await trg_group_cur.fetchone()
            if trg_group_row:
                target_code = f"u{int(trg_group_row[0])}"
                custom_groups_cache[code] = target_code
                return target_code
            insert_group = await db.execute(
                "INSERT INTO user_muscle_groups(user_id, name) VALUES(?,?)",
                (target_user_id, group_name),
            )
            target_code = f"u{int(insert_group.lastrowid)}"
            custom_groups_cache[code] = target_code
            return target_code

        source_snapshot_cache: dict[int, dict] = {}

        async def get_source_snapshot(source_ex_id: int) -> dict:
            ex_id = int(source_ex_id or 0)
            if ex_id <= 0:
                return {}
            cached_snapshot = source_snapshot_cache.get(ex_id)
            if cached_snapshot is not None:
                return cached_snapshot
            latest_cur = await db.execute(
                """
                SELECT s.id
                FROM sets st
                JOIN sessions s ON s.id=st.session_id
                JOIN user_exercises ue ON ue.id=st.user_exercise_id
                WHERE s.user_id=? AND ue.exercise_id=?
                ORDER BY s.date DESC, s.id DESC, st.set_no DESC
                LIMIT 1
                """,
                (source_user_id, ex_id),
            )
            latest_row = await latest_cur.fetchone()
            if not latest_row:
                source_snapshot_cache[ex_id] = {}
                return {}
            latest_session_id = int(latest_row[0])
            count_cur = await db.execute(
                """
                SELECT COUNT(*)
                FROM sets st
                JOIN user_exercises ue ON ue.id=st.user_exercise_id
                WHERE st.session_id=? AND ue.exercise_id=?
                """,
                (latest_session_id, ex_id),
            )
            count_row = await count_cur.fetchone()
            last_cur = await db.execute(
                """
                SELECT st.reps, st.weight_kg
                FROM sets st
                JOIN user_exercises ue ON ue.id=st.user_exercise_id
                WHERE st.session_id=? AND ue.exercise_id=?
                ORDER BY st.set_no DESC
                LIMIT 1
                """,
                (latest_session_id, ex_id),
            )
            last_row = await last_cur.fetchone()
            snapshot = {
                'sets_count': int((count_row[0] if count_row else 0) or 0),
                'reps': int((last_row[0] if last_row else 0) or 0),
                'weight_kg': float((last_row[1] if last_row else 0.0) or 0.0),
            }
            source_snapshot_cache[ex_id] = snapshot
            return snapshot

        exercise_cache: dict[tuple[str, str], int] = {}

        async def ensure_target_exercise(ex_name: str, muscle_group: str | None) -> int:
            normalized_name = (ex_name or "").strip()
            normalized_group = (muscle_group or "other").strip().lower() or "other"
            key = (normalized_name.casefold(), normalized_group)
            cached = exercise_cache.get(key)
            if cached:
                return int(cached)
            cur_find = await db.execute(
                "SELECT id FROM exercises WHERE LOWER(name)=LOWER(?) AND COALESCE(muscle_group,'')=? LIMIT 1",
                (normalized_name, normalized_group),
            )
            row_find = await cur_find.fetchone()
            if row_find:
                ex_id = int(row_find[0])
                exercise_cache[key] = ex_id
                return ex_id
            cur_new = await db.execute(
                "INSERT INTO exercises(name, muscle_group) VALUES(?, ?)",
                (normalized_name, normalized_group),
            )
            ex_id = int(cur_new.lastrowid)
            exercise_cache[key] = ex_id
            return ex_id

        day_count = 0
        for day_index, label, is_active in source_days:
            day_index = int(day_index or 0)
            if day_index <= 0:
                continue
            day_count += 1
            day_label = (label or f"День {day_index}").strip() or f"День {day_index}"
            await db.execute(
                "INSERT INTO training_system_days(system_id, day_index, label, is_active) VALUES(?,?,?,?)",
                (new_system_id, day_index, day_label, int(is_active or 0)),
            )

        ex_count = 0
        copied_exercise_ids: set[int] = set()
        for day_index, ex_name, muscle_group, source_exercise_id in source_exercises:
            day_no = int(day_index or 0)
            if day_no <= 0:
                continue
            name_raw = (ex_name or "").strip()
            if not name_raw:
                continue
            target_group = await ensure_target_custom_group(muscle_group)
            exercise_id = await ensure_target_exercise(name_raw, target_group)
            await db.execute(
                "INSERT OR IGNORE INTO training_system_exercises(system_id, day_index, exercise_id) VALUES(?,?,?)",
                (new_system_id, day_no, exercise_id),
            )
            ex_count += 1
            copied_exercise_ids.add(exercise_id)
            source_meta = source_meta_map.get((day_no, int(source_exercise_id or 0))) or {}
            inherited_source_user_id = source_meta.get('source_user_id')
            inherited_source_system_id = source_meta.get('source_system_id')
            inherited_source_exercise_id = source_meta.get('source_exercise_id')
            inherited_source_exercise_name = (source_meta.get('source_exercise_name') or name_raw).strip() or name_raw
            payload_source_exercise_id = int(inherited_source_exercise_id) if inherited_source_exercise_id is not None else int(source_exercise_id or 0)
            inherited_sets_count = source_meta.get('sets_count')
            inherited_reps = source_meta.get('reps')
            inherited_weight = source_meta.get('weight_kg')
            snapshot = await get_source_snapshot(payload_source_exercise_id)
            payload = {
                'source_user_id': int(inherited_source_user_id) if inherited_source_user_id is not None else int(source_user_id),
                'source_system_id': int(inherited_source_system_id) if inherited_source_system_id is not None else int(selected_system_id),
                'source_exercise_id': payload_source_exercise_id,
                'source_exercise_name': inherited_source_exercise_name,
                'sets_count': int(inherited_sets_count) if inherited_sets_count is not None else int(snapshot.get('sets_count') or 0),
                'reps': int(inherited_reps) if inherited_reps is not None else int(snapshot.get('reps') or 0),
                'weight_kg': float(inherited_weight) if inherited_weight is not None else float(snapshot.get('weight_kg') or 0.0),
            }
            await db.execute(
                """
                INSERT INTO training_system_exercise_sources(system_id, day_index, exercise_id, source_payload)
                VALUES(?,?,?,?)
                ON CONFLICT(system_id, day_index, exercise_id)
                DO UPDATE SET source_payload=excluded.source_payload
                """,
                (new_system_id, day_no, exercise_id, json.dumps(payload, ensure_ascii=False)),
            )

        for day_no, dow, hour, minute in source_reminders:
            if int(day_no or 0) <= 0:
                continue
            await db.execute(
                "INSERT OR REPLACE INTO training_system_reminders(system_id, day_no, dow, hour, minute) VALUES(?,?,?,?,?)",
                (new_system_id, int(day_no), int(dow), int(hour), int(minute)),
            )

        for ex_id in copied_exercise_ids:
            await db.execute(
                """
                INSERT INTO user_exercises(user_id, exercise_id, day_index, is_archived)
                VALUES(?,?,0,0)
                ON CONFLICT(user_id, exercise_id, day_index)
                DO UPDATE SET is_archived=0
                """,
                (target_user_id, int(ex_id)),
            )

        if not day_count:
            for day_index in range(1, 8):
                await db.execute(
                    "INSERT INTO training_system_days(system_id, day_index, label, is_active) VALUES(?,?,?,?)",
                    (new_system_id, day_index, f"День {day_index}", 1 if day_index <= 3 else 0),
                )

        await db.commit()
    await apply_system_to_current_plan(target_user_id, new_system_id)
    return {"system_id": int(new_system_id), "days": day_count, "exercises": ex_count}
