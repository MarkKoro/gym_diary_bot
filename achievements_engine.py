from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import db


@dataclass(frozen=True)
class AchievementDef:
    code: str
    title: str
    icon: str
    rarity: str
    frame_code: str
    secret: bool = False


ACHIEVEMENTS: tuple[AchievementDef, ...] = (
    AchievementDef("first_set", "Первый подход", "🥇", "common", "frame_first_set"),
    AchievementDef("first_day_done", "День закрыт", "✅", "common", "frame_check"),
    AchievementDef("streak_7", "Неделя без пропусков", "🔥", "rare", "frame_fire"),
    AchievementDef("streak_21", "Марафон дисциплины", "🧨", "epic", "frame_fuse", secret=True),
    AchievementDef("variety_12_week", "Полка инструментов", "🧰", "rare", "frame_toolbox"),
    AchievementDef("variety_20_week", "Арсенал", "🧪", "epic", "frame_lab", secret=True),
    AchievementDef("volume_100k", "Тоннажник", "🧱", "rare", "frame_brick"),
    AchievementDef("volume_500k", "Кран", "🏗️", "legendary", "frame_crane", secret=True),
    AchievementDef("sets_500", "Станок", "⚙️", "rare", "frame_gear"),
    AchievementDef("run_10km", "Пыль дорог", "🏃", "rare", "frame_runner"),
    AchievementDef("run_42km", "42", "🏁", "epic", "frame_finish"),
    AchievementDef("plan_architect", "Архитектор", "🧩", "rare", "frame_puzzle"),
    AchievementDef("rename_master", "Кастомщик", "🎨", "rare", "frame_paint"),
    AchievementDef("leaderboard_on", "На свет", "🌟", "common", "frame_star"),
    AchievementDef("copied_plan_3days", "Разведчик", "🕵️", "rare", "frame_spy"),
    AchievementDef("inspired_3", "Вдохновитель", "📈", "epic", "frame_graph"),
    AchievementDef("arnold_15", "Арнольд", "🦾", "legendary", "frame_gym"),
    AchievementDef("coach_1", "Тренер", "🧑‍🏫", "rare", "frame_coach"),
    AchievementDef("apprentice_10", "Подопечный", "🐣", "rare", "frame_chick"),
    AchievementDef("comeback_14", "Возвращение", "🪃", "rare", "frame_boomerang"),
    AchievementDef("day_done_50", "Пятьдесят закрытых", "🧱", "epic", "frame_wall"),
    AchievementDef("night_shift", "Ночь — мой зал", "🌙", "epic", "frame_moon", secret=True),
)

ACHIEVEMENTS_BY_CODE = {item.code: item for item in ACHIEVEMENTS}
FRAME_TO_CODE = {item.frame_code: item.code for item in ACHIEVEMENTS}


async def _fetch_metrics(user_id: int) -> dict:
    tz_name = await db.get_user_timezone(user_id)
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")

    async with db.connect_db() as conn:
        q = "SELECT COUNT(*) FROM sets st JOIN sessions s ON s.id=st.session_id WHERE s.user_id=? AND COALESCE(st.is_warmup,0)=0"
        sets_non_warmup = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

        q = "SELECT COUNT(*) FROM day_completion_history WHERE user_id=?"
        day_done_total = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

        q = "SELECT completed_at FROM day_completion_history WHERE user_id=? ORDER BY completed_at ASC"
        completed_rows = await (await conn.execute(q, (user_id,))).fetchall()

        q = """
        SELECT COUNT(DISTINCT ue.exercise_id)
        FROM session_exercises se
        JOIN sessions s ON s.id=se.session_id
        JOIN user_exercises ue ON ue.id=se.user_exercise_id
        WHERE s.user_id=? AND se.is_done=1 AND s.date >= date('now', '-7 day')
        """
        variety_week = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

        q = "SELECT COALESCE(SUM(MAX(reps,0)*MAX(weight_kg,0)),0) FROM sets st JOIN sessions s ON s.id=st.session_id WHERE s.user_id=? AND reps>0 AND weight_kg>0"
        volume = float((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0.0)

        q = "SELECT COALESCE(SUM(distance_km),0) FROM running_entries WHERE user_id=? AND COALESCE(is_draft,1)=0"
        run_km = float((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0.0)

        q = "SELECT COUNT(*) FROM training_systems WHERE user_id=?"
        systems_count = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

        q = "SELECT COUNT(*) FROM user_exercises WHERE user_id=? AND COALESCE(is_archived,0)=0"
        active_user_exercises = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

        q = "SELECT COALESCE(leaderboard_visible,1) FROM users WHERE id=?"
        leaderboard_visible = bool(int((await (await conn.execute(q, (user_id,))).fetchone() or [1])[0] or 1))

        q = """
        SELECT COUNT(*)
        FROM training_system_copy_events ce
        WHERE ce.target_user_id=? AND ce.first_trained_at IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM day_completion_history d
            WHERE d.user_id=? AND d.system_id=ce.target_system_id
            GROUP BY d.system_id
            HAVING COUNT(*) >= 3
          )
        """
        copied_plan_3days = int((await (await conn.execute(q, (user_id, user_id))).fetchone())[0] or 0)

        inspired = await db.count_trained_copies_for_source(user_id)

        q = "SELECT COUNT(*) FROM trainer_links WHERE trainer_user_id=? AND status='accepted'"
        accepted_trainees = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

        q = """
        SELECT COUNT(*)
        FROM trainer_links l
        WHERE l.trainer_user_id=? AND l.status='accepted'
          AND (
            SELECT COUNT(*) FROM day_completion_history d WHERE d.user_id=l.trainee_user_id
          ) >= 5
        """
        coach_ok = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

        q = "SELECT COUNT(*) FROM trainer_links WHERE trainee_user_id=? AND status='accepted'"
        accepted_trainer_links = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

    local_dates: list[datetime] = []
    for (iso_ts,) in completed_rows:
        try:
            dt = datetime.fromisoformat(str(iso_ts))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        local_dates.append(dt.astimezone(tz))

    return {
        "sets_non_warmup": sets_non_warmup,
        "day_done_total": day_done_total,
        "local_completions": local_dates,
        "variety_week": variety_week,
        "volume": volume,
        "run_km": run_km,
        "systems_count": systems_count,
        "active_user_exercises": active_user_exercises,
        "rename_count": await db.count_user_events(user_id, "rename"),
        "leaderboard_visible": leaderboard_visible,
        "copied_plan_3days": copied_plan_3days,
        "inspired": inspired,
        "accepted_trainees": accepted_trainees,
        "coach_ok": coach_ok,
        "accepted_trainer_links": accepted_trainer_links,
    }


def _max_streak(local_completions: list[datetime]) -> int:
    if not local_completions:
        return 0
    uniq = sorted({d.date() for d in local_completions})
    best = 1
    cur = 1
    for i in range(1, len(uniq)):
        if (uniq[i] - uniq[i - 1]).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def _has_comeback_14(local_completions: list[datetime]) -> bool:
    uniq = sorted({d.date() for d in local_completions})
    for i in range(1, len(uniq)):
        if (uniq[i] - uniq[i - 1]).days >= 14:
            return True
    return False


async def evaluate(user_id: int) -> dict:
    existing = {code: ts for code, ts in await db.list_user_achievements(user_id)}
    m = await _fetch_metrics(user_id)
    streak = _max_streak(m["local_completions"])

    earned: set[str] = set(existing.keys())
    checks = {
        "first_set": m["sets_non_warmup"] >= 1,
        "first_day_done": m["day_done_total"] >= 1,
        "streak_7": streak >= 7,
        "streak_21": streak >= 21,
        "variety_12_week": m["variety_week"] >= 12,
        "variety_20_week": m["variety_week"] >= 20,
        "volume_100k": m["volume"] >= 100000,
        "volume_500k": m["volume"] >= 500000,
        "sets_500": m["sets_non_warmup"] >= 500,
        "run_10km": m["run_km"] >= 10,
        "run_42km": m["run_km"] >= 42,
        "plan_architect": m["systems_count"] >= 3 or m["active_user_exercises"] >= 30,
        "rename_master": m["rename_count"] >= 5,
        "leaderboard_on": bool(m["leaderboard_visible"]),
        "copied_plan_3days": m["copied_plan_3days"] >= 1,
        "inspired_3": m["inspired"] >= 3,
        "arnold_15": m["inspired"] >= 15,
        "coach_1": m["coach_ok"] >= 1,
        "apprentice_10": m["accepted_trainer_links"] >= 1 and m["day_done_total"] >= 10,
        "comeback_14": _has_comeback_14(m["local_completions"]),
        "day_done_50": m["day_done_total"] >= 50,
        "night_shift": any(d.hour >= 23 or d.hour <= 4 for d in m["local_completions"]),
    }

    newly: list[str] = []
    now_iso = datetime.now(UTC).isoformat()
    for code, ok in checks.items():
        if not ok:
            continue
        earned.add(code)
        if code not in existing:
            inserted = await db.grant_achievement(user_id, code, now_iso)
            if inserted:
                newly.append(code)
    return {"earned_codes": sorted(earned), "newly_unlocked_codes": newly}


async def achievements_overview_payload(user_id: int, has_subscription: bool, is_admin: bool = False) -> dict:
    eval_result = await evaluate(user_id)
    unlocked_map = {code: ts for code, ts in await db.list_user_achievements(user_id)}
    cosmetics = await db.get_cosmetics(user_id)
    return {
        "has_subscription": bool(has_subscription),
        "cosmetics": cosmetics,
        "achievements": [
            {
                "code": item.code,
                "title": item.title,
                "icon": item.icon,
                "rarity": item.rarity,
                "frame_code": item.frame_code,
                "unlocked": bool(is_admin) or item.code in unlocked_map,
                "unlocked_at": unlocked_map.get(item.code),
                "secret": bool(item.secret),
            }
            for item in ACHIEVEMENTS
        ],
        "newly_unlocked": eval_result["newly_unlocked_codes"],
    }
