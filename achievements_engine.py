from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
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


@dataclass(frozen=True)
class TeamAchievementDef:
    code: str
    title: str
    icon: str
    rarity: str
    team_frame_code: str
    team_bg_code: str
    team_emblem_code: str
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
    AchievementDef("team_joined", "В стае", "🐺", "common", "frame_pack"),
    AchievementDef("team_founder", "Основатель", "🏴", "rare", "frame_banner"),
    AchievementDef("team_full_roster", "Полный состав", "🧱", "epic", "frame_honeycomb"),
    AchievementDef("team_top10_week", "В десятке", "🔟", "rare", "frame_ringed"),
    AchievementDef("team_top3_week", "На пьедестале", "🥉", "epic", "frame_laurel"),
    AchievementDef("team_top1_week", "Корона недели", "👑", "legendary", "frame_crownline", secret=True),
    AchievementDef("team_month_top1", "Трон месяца", "🏆", "legendary", "frame_throneveil", secret=True),
    AchievementDef("team_consistency", "Ровный темп", "🫀", "rare", "frame_pulse"),
    AchievementDef("team_night_ops", "Ночной отряд", "🌘", "epic", "frame_eclipse", secret=True),
    AchievementDef("team_recruit_3", "Вербовщик", "🧲", "rare", "frame_magnet"),
    AchievementDef("team_recruit_8", "Сборщик стаи", "🕸️", "epic", "frame_webweave", secret=True),
    AchievementDef("team_loyal_30", "Верность", "🧭", "epic", "frame_compassrose", secret=True),
)

TEAM_ACHIEVEMENTS: tuple[TeamAchievementDef, ...] = (
    TeamAchievementDef("t_foundation", "Фундамент", "🧱", "common", "team_frame_stitch", "team_bg_slate", "team_emblem_mark"),
    TeamAchievementDef("t_full_roster", "Полный состав", "🧩", "rare", "team_frame_honey", "team_bg_honeycomb", "team_emblem_wolf"),
    TeamAchievementDef("t_active_core", "Живое ядро", "🔥", "rare", "team_frame_ember", "team_bg_ember", "team_emblem_torch"),
    TeamAchievementDef("t_top10_week", "В десятке недели", "🔟", "rare", "team_frame_ring", "team_bg_neon_grid", "team_emblem_badge"),
    TeamAchievementDef("t_top3_week", "Пьедестал недели", "🥉", "epic", "team_frame_laurel", "team_bg_aurora", "team_emblem_wreath"),
    TeamAchievementDef("t_top1_week", "Корона недели", "👑", "legendary", "team_frame_crown", "team_bg_obsidian", "team_emblem_crown"),
    TeamAchievementDef("t_top1_month", "Трон месяца", "🏆", "legendary", "team_frame_throne", "team_bg_blackhole", "team_emblem_throne", secret=True),
    TeamAchievementDef("t_consistency_28", "28 дней темпа", "🫀", "epic", "team_frame_pulse", "team_bg_ocean", "team_emblem_wave"),
    TeamAchievementDef("t_night_ops", "Ночной состав", "🌘", "epic", "team_frame_eclipse", "team_bg_midnight", "team_emblem_moon", secret=True),
    TeamAchievementDef("t_web_of_power", "Паутина влияния", "🕸️", "legendary", "team_frame_web", "team_bg_violet_smoke", "team_emblem_spider", secret=True),
)

ACHIEVEMENTS_BY_CODE = {item.code: item for item in ACHIEVEMENTS}
FRAME_TO_CODE = {item.frame_code: item.code for item in ACHIEVEMENTS}
TEAM_ACHIEVEMENTS_BY_CODE = {item.code: item for item in TEAM_ACHIEVEMENTS}
ACHIEVEMENT_UNLOCK_HINTS: dict[str, str] = {
    "first_set": "Сделай 1 рабочий подход.",
    "first_day_done": "Заверши 1 тренировочный день.",
    "coach_1": "Подключи хотя бы одного подопечного.",
    "apprentice_10": "Стань подопечным и закрой 10 тренировочных дней.",
    "team_joined": "Вступи в любую команду.",
    "team_founder": "Создай свою команду.",
    "leaderboard_on": "Включи участие в рейтинге в настройках.",
    "copied_plan_3days": "Скопируй систему и закрой в ней 3 дня.",
}

TEAM_STYLE_CATALOG = {
    "frames": {item.team_frame_code: item.code for item in TEAM_ACHIEVEMENTS},
    "bgs": {item.team_bg_code: item.code for item in TEAM_ACHIEVEMENTS},
    "emblems": {item.team_emblem_code: item.code for item in TEAM_ACHIEVEMENTS},
}

if len(ACHIEVEMENTS_BY_CODE) != len(ACHIEVEMENTS):
    raise ValueError("Duplicate achievement code")
if len(FRAME_TO_CODE) != len(ACHIEVEMENTS):
    raise ValueError("Duplicate frame_code")
if len(TEAM_ACHIEVEMENTS_BY_CODE) != len(TEAM_ACHIEVEMENTS):
    raise ValueError("Duplicate team achievement code")
if len(TEAM_STYLE_CATALOG["frames"]) != len(TEAM_ACHIEVEMENTS):
    raise ValueError("Duplicate team_frame_code")
if len(TEAM_STYLE_CATALOG["bgs"]) != len(TEAM_ACHIEVEMENTS):
    raise ValueError("Duplicate team_bg_code")
if len(TEAM_STYLE_CATALOG["emblems"]) != len(TEAM_ACHIEVEMENTS):
    raise ValueError("Duplicate team_emblem_code")


async def _fetch_team_metrics(team_id: int) -> dict:
    async with db.connect_db() as conn:
        members_q = "SELECT COUNT(*) FROM team_members WHERE team_id=? AND left_at IS NULL"
        members_count = int((await (await conn.execute(members_q, (team_id,))).fetchone())[0] or 0)

        active_members_q = """
        SELECT COUNT(DISTINCT tm.user_id)
        FROM team_members tm
        JOIN sessions s ON s.user_id = tm.user_id
        JOIN users u ON u.id = tm.user_id
        WHERE tm.team_id=? AND tm.left_at IS NULL
          AND s.date BETWEEN date(local_date(datetime('now'), u.tz), '-6 day') AND local_date(datetime('now'), u.tz)
          AND EXISTS (
              SELECT 1 FROM day_completion_history d
              WHERE d.user_id=s.user_id AND d.system_id=s.system_id
                AND d.day_index=s.day_index AND local_date(d.completed_at, u.tz)=s.date
          )
        """
        active_members_7d = int((await (await conn.execute(active_members_q, (team_id,))).fetchone())[0] or 0)

        sessions_q = """
        SELECT
            SUM(CASE WHEN s.date BETWEEN date(local_date(datetime('now'), u.tz), '-6 day') AND local_date(datetime('now'), u.tz) THEN 1 ELSE 0 END),
            SUM(CASE WHEN s.date BETWEEN date(local_date(datetime('now'), u.tz), '-27 day') AND local_date(datetime('now'), u.tz) THEN 1 ELSE 0 END)
        FROM team_members tm
        JOIN users u ON u.id = tm.user_id
        LEFT JOIN sessions s ON s.user_id = tm.user_id
          AND EXISTS (
              SELECT 1 FROM day_completion_history d
              WHERE d.user_id=s.user_id AND d.system_id=s.system_id
                AND d.day_index=s.day_index AND local_date(d.completed_at, u.tz)=s.date
          )
        WHERE tm.team_id=? AND tm.left_at IS NULL
        """
        sessions_row = await (await conn.execute(sessions_q, (team_id,))).fetchone()
        sessions_7 = int((sessions_row[0] if sessions_row else 0) or 0)
        sessions_28 = int((sessions_row[1] if sessions_row else 0) or 0)

        rank_q = """
        SELECT
            MIN(CASE WHEN day_utc BETWEEN date('now', '-6 day') AND date('now') THEN rank END),
            MIN(CASE WHEN day_utc BETWEEN date('now', '-27 day') AND date('now') THEN rank END),
            SUM(CASE WHEN day_utc BETWEEN date('now', '-27 day') AND date('now') AND rank <= 3 THEN 1 ELSE 0 END),
            SUM(CASE WHEN day_utc BETWEEN date('now', '-27 day') AND date('now') AND rank <= 10 THEN 1 ELSE 0 END)
        FROM team_daily_scores
        WHERE team_id=?
        """
        rank_row = await (await conn.execute(rank_q, (team_id,))).fetchone()
        best_rank_7 = int(rank_row[0]) if rank_row and rank_row[0] is not None else None
        best_rank_28 = int(rank_row[1]) if rank_row and rank_row[1] is not None else None
        top3_days_28 = int((rank_row[2] if rank_row else 0) or 0)
        top10_days_28 = int((rank_row[3] if rank_row else 0) or 0)

        streak_rows = await (
            await conn.execute(
                """
                SELECT day_utc, rank
                FROM team_daily_scores
                WHERE team_id=? AND day_utc <= date('now')
                ORDER BY day_utc DESC
                LIMIT 35
                """,
                (team_id,),
            )
        ).fetchall()

        night_q = """
            SELECT MIN(dch.completed_at), u.tz
            FROM day_completion_history dch
            JOIN team_members tm ON tm.user_id = dch.user_id
            JOIN users u ON u.id = dch.user_id
            WHERE tm.team_id=? AND tm.left_at IS NULL
              AND local_date(dch.completed_at, u.tz)
                  BETWEEN date(local_date(datetime('now'), u.tz), '-27 day') AND local_date(datetime('now'), u.tz)
            GROUP BY dch.user_id, dch.system_id, dch.day_index, local_date(dch.completed_at, u.tz)
        """
        night_rows = await (await conn.execute(night_q, (team_id,))).fetchall()

    night_sessions_28 = 0
    for completed_at, tz_name in night_rows:
        try:
            dt = datetime.fromisoformat(str(completed_at))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            try:
                tz = ZoneInfo(tz_name or "UTC")
            except Exception:
                tz = ZoneInfo("UTC")
            local_hour = dt.astimezone(tz).hour
            night_sessions_28 += int(local_hour >= 23 or local_hour <= 4)
        except (TypeError, ValueError):
            continue

    top1_streak_days = 0
    expected_day = datetime.now(UTC).date()
    for day_iso, rank in streak_rows:
        try:
            row_day = date.fromisoformat(str(day_iso))
        except Exception:
            break
        if row_day != expected_day:
            break
        if int(rank or 0) != 1:
            break
        top1_streak_days += 1
        expected_day = expected_day - timedelta(days=1)

    return {
        "members_count": members_count,
        "active_members_7d": active_members_7d,
        "sessions_7": sessions_7,
        "sessions_28": sessions_28,
        "best_rank_7": best_rank_7,
        "best_rank_28": best_rank_28,
        "top1_streak_days": top1_streak_days,
        "top3_days_28": top3_days_28,
        "top10_days_28": top10_days_28,
        "night_sessions_28": night_sessions_28,
    }


async def _fetch_metrics(user_id: int) -> dict:
    tz_name = await db.get_user_timezone(user_id)
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")

    async with db.connect_db() as conn:
        q = "SELECT COUNT(*) FROM sets st JOIN sessions s ON s.id=st.session_id WHERE s.user_id=? AND COALESCE(st.is_warmup,0)=0"
        sets_non_warmup = int((await (await conn.execute(q, (user_id,))).fetchone())[0] or 0)

        q = "SELECT system_id, day_index, completed_at FROM day_completion_history WHERE user_id=? ORDER BY completed_at ASC"
        completed_rows = await (await conn.execute(q, (user_id,))).fetchall()

        q = """
        SELECT COUNT(DISTINCT ue.exercise_id)
        FROM session_exercises se
        JOIN sessions s ON s.id=se.session_id
        JOIN users u ON u.id=s.user_id
        JOIN user_exercises ue ON ue.id=se.user_exercise_id
        WHERE s.user_id=? AND se.is_done=1 AND s.date BETWEEN date(local_date(datetime('now'), u.tz), '-6 day') AND local_date(datetime('now'), u.tz)
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
        leaderboard_visible = bool(int((await (await conn.execute(q, (user_id,))).fetchone() or [1])[0]))

        q = """
        SELECT COUNT(*)
        FROM training_system_copy_events ce
        WHERE ce.target_user_id=? AND ce.first_trained_at IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM day_completion_history d
            WHERE d.user_id=? AND d.system_id=ce.target_system_id
            GROUP BY d.system_id
            HAVING COUNT(DISTINCT local_date(d.completed_at, ?)) >= 3
          )
        """
        copied_plan_3days = int((await (await conn.execute(q, (user_id, user_id, tz_name))).fetchone())[0] or 0)

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

        q = """
        SELECT tm.team_id, tm.role, tm.joined_at, t.owner_user_id
        FROM team_members tm
        JOIN teams t ON t.id=tm.team_id
        WHERE tm.user_id=? AND tm.left_at IS NULL
        LIMIT 1
        """
        team_row = await (await conn.execute(q, (user_id,))).fetchone()

    inspired = await db.count_trained_copies_for_source(user_id)

    team_id = int(team_row[0]) if team_row else None
    team_role = str(team_row[1]) if team_row and team_row[1] else None
    team_joined_at_raw = str(team_row[2]) if team_row and team_row[2] else None

    team_members_count = 0
    team_best_rank_7 = None
    team_top1_streak_days = 0
    team_sessions_per_member_28 = 0.0
    captain_recruits_count = 0
    if team_id is not None:
        t = await _fetch_team_metrics(team_id)
        team_members_count = int(t["members_count"])
        team_best_rank_7 = t["best_rank_7"]
        team_top1_streak_days = int(t["top1_streak_days"])
        team_sessions_per_member_28 = float(t["sessions_28"]) / max(1, team_members_count)
        if team_role == "captain":
            async with db.connect_db() as conn:
                q = "SELECT COUNT(*) FROM team_members WHERE team_id=? AND left_at IS NULL AND role<>'captain'"
                captain_recruits_count = int((await (await conn.execute(q, (team_id,))).fetchone())[0] or 0)

    local_dates: list[datetime] = []
    completed_days = set()
    for system_id, day_index, iso_ts in completed_rows:
        try:
            dt = datetime.fromisoformat(str(iso_ts))
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        local_dt = dt.astimezone(tz)
        completion_key = (system_id, day_index, local_dt.date())
        if completion_key not in completed_days:
            completed_days.add(completion_key)
            local_dates.append(local_dt)

    return {
        "sets_non_warmup": sets_non_warmup,
        "day_done_total": len(completed_days),
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
        "team_id": team_id,
        "team_role": team_role,
        "team_is_founder": bool(team_row and int(team_row[3]) == user_id),
        "team_members_count": team_members_count,
        "team_best_rank_7": team_best_rank_7,
        "team_top1_streak_days": team_top1_streak_days,
        "team_sessions_per_member_28": team_sessions_per_member_28,
        "captain_recruits_count": captain_recruits_count,
        "team_joined_at": team_joined_at_raw,
        "team_night_sessions_28": int(t["night_sessions_28"]) if team_id is not None else 0,
        "team_metrics": t if team_id is not None else None,
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


async def evaluate_team(team_id: int, *, metrics: dict | None = None) -> dict:
    existing_team = set(await db.list_team_achievements(team_id))
    m = metrics if metrics is not None else await _fetch_team_metrics(team_id)

    checks = {
        "t_foundation": m["members_count"] >= 1,
        "t_full_roster": m["members_count"] >= 8,
        "t_active_core": m["members_count"] >= 6 and m["active_members_7d"] >= 5,
        "t_top10_week": m["best_rank_7"] is not None and m["best_rank_7"] <= 10,
        "t_top3_week": m["best_rank_7"] is not None and m["best_rank_7"] <= 3,
        "t_top1_week": m["best_rank_7"] is not None and m["best_rank_7"] == 1,
        "t_top1_month": m["top1_streak_days"] >= 30,
        "t_consistency_28": (m["sessions_28"] / max(1, m["members_count"])) >= 12,
        "t_night_ops": m["night_sessions_28"] >= 12 and m["members_count"] >= 3,
        "t_web_of_power": m["top3_days_28"] >= 21 and m["members_count"] >= 8,
    }

    earned = set(existing_team)
    newly: list[str] = []
    now_iso = datetime.now(UTC).isoformat()
    for code, ok in checks.items():
        if not ok:
            continue
        earned.add(code)
        if code not in existing_team:
            inserted = await db.grant_team_achievement(team_id, code, now_iso)
            if inserted:
                newly.append(code)
    return {"earned_team_codes": sorted(earned), "newly_unlocked_team_codes": newly}


async def evaluate(user_id: int) -> dict:
    existing = {code: ts for code, ts in await db.list_user_achievements(user_id)}
    m = await _fetch_metrics(user_id)
    streak = _max_streak(m["local_completions"])

    team_loyal_30 = False
    if m["team_joined_at"]:
        try:
            joined_at = datetime.fromisoformat(str(m["team_joined_at"]))
            if joined_at.tzinfo is None:
                joined_at = joined_at.replace(tzinfo=UTC)
            team_loyal_30 = joined_at <= datetime.now(UTC) - timedelta(days=30)
        except Exception:
            team_loyal_30 = False

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
        "coach_1": m["accepted_trainees"] >= 1,
        "apprentice_10": m["accepted_trainer_links"] >= 1 and m["day_done_total"] >= 10,
        "comeback_14": _has_comeback_14(m["local_completions"]),
        "day_done_50": m["day_done_total"] >= 50,
        "night_shift": any(d.hour >= 23 or d.hour <= 4 for d in m["local_completions"]),
        "team_joined": m["team_id"] is not None,
        "team_founder": m["team_is_founder"],
        "team_full_roster": m["team_id"] is not None and m["team_members_count"] >= 8,
        "team_top10_week": m["team_best_rank_7"] is not None and m["team_best_rank_7"] <= 10,
        "team_top3_week": m["team_best_rank_7"] is not None and m["team_best_rank_7"] <= 3,
        "team_top1_week": m["team_best_rank_7"] is not None and m["team_best_rank_7"] == 1,
        "team_month_top1": m["team_top1_streak_days"] >= 30,
        "team_consistency": m["team_sessions_per_member_28"] >= 12,
        "team_night_ops": m["team_night_sessions_28"] >= 6,
        "team_recruit_3": m["team_role"] == "captain" and m["captain_recruits_count"] >= 3,
        "team_recruit_8": m["team_role"] == "captain" and m["captain_recruits_count"] >= 8,
        "team_loyal_30": m["team_id"] is not None and team_loyal_30,
    }

    if m["team_id"] is not None:
        await evaluate_team(int(m["team_id"]), metrics=m.get("team_metrics"))

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


def team_style_options_for_codes(earned_team_codes: set[str]) -> dict:
    frame_codes = sorted([code for code, req in TEAM_STYLE_CATALOG["frames"].items() if req in earned_team_codes])
    bg_codes = sorted([code for code, req in TEAM_STYLE_CATALOG["bgs"].items() if req in earned_team_codes])
    emblem_codes = sorted([code for code, req in TEAM_STYLE_CATALOG["emblems"].items() if req in earned_team_codes])
    return {
        "allowed_frames": frame_codes,
        "allowed_bgs": bg_codes,
        "allowed_emblems": emblem_codes,
    }


def is_team_style_allowed(
    earned_team_codes: set[str],
    frame_code: str | None,
    bg_code: str | None,
    emblem_code: str | None,
) -> bool:
    options = team_style_options_for_codes(earned_team_codes)
    if frame_code is not None and frame_code not in options["allowed_frames"]:
        return False
    if bg_code is not None and bg_code not in options["allowed_bgs"]:
        return False
    if emblem_code is not None and emblem_code not in options["allowed_emblems"]:
        return False
    return True


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
                "unlock_hint": ACHIEVEMENT_UNLOCK_HINTS.get(item.code),
            }
            for item in ACHIEVEMENTS
        ],
        "newly_unlocked": eval_result["newly_unlocked_codes"],
    }
