"""Owner-local explicit/90-minute free-session finish. Never infer workout duration.

Only actual writes touch activity; reading a screen, locking or closing it does not.
The same native session id is used by both views and all completion paths.
"""
import sqlite3
import time
from contextlib import closing
from datetime import datetime,timezone
from progressor_timezone_history import zone as native_zone

SCHEMA='''CREATE TABLE IF NOT EXISTS progressor_free_sessions(
 session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
 last_activity REAL NOT NULL,status TEXT NOT NULL,completed_at TEXT,
 completion_basis TEXT,last_finished_at REAL);
'''
PROOF_SCHEMA='''CREATE TABLE IF NOT EXISTS progressor_free_activity_proof(
 session_id INTEGER PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
 last_activity REAL NOT NULL,source_local_date TEXT NOT NULL,
 activity_timezone TEXT NOT NULL,
 proof_version INTEGER NOT NULL CHECK(proof_version=1),
 clock_kind TEXT NOT NULL CHECK(clock_kind='native_touch'))'''
PROOF_TRIGGERS=(
 '''CREATE TRIGGER IF NOT EXISTS progressor_free_proof_clock_update_v1
 AFTER UPDATE OF last_activity ON progressor_free_sessions
 BEGIN DELETE FROM progressor_free_activity_proof WHERE session_id=OLD.session_id; END''',
 '''CREATE TRIGGER IF NOT EXISTS progressor_free_proof_state_insert_v1
 AFTER INSERT ON progressor_free_sessions
 BEGIN DELETE FROM progressor_free_activity_proof WHERE session_id=NEW.session_id; END''',
 '''CREATE TRIGGER IF NOT EXISTS progressor_free_proof_state_delete_v1
 AFTER DELETE ON progressor_free_sessions
 BEGIN DELETE FROM progressor_free_activity_proof WHERE session_id=OLD.session_id; END''',
 '''CREATE TRIGGER IF NOT EXISTS progressor_free_proof_session_delete_v1
 AFTER DELETE ON sessions
 BEGIN DELETE FROM progressor_free_activity_proof WHERE session_id=OLD.id; END''',
)
SCHEMA_STATEMENTS=(SCHEMA,PROOF_SCHEMA,*PROOF_TRIGGERS)
IDLE_SECONDS=90*60

async def ensure_schema(conn):
    """Install after the sessions migration, without commits or proof backfill."""
    for statement in SCHEMA_STATEMENTS:
        await conn.execute(statement)

def _ensure_schema(db):
    for statement in SCHEMA_STATEMENTS:
        db.execute(statement)

async def touch(conn,session_id,now=None):
    stamp=time.time() if now is None else now
    row=await (await conn.execute('SELECT s.date,s.day_index,u.tz FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=?',(session_id,))).fetchone()
    if not row or row[1]!=0:return
    activity_zone=row[2] or 'UTC'
    try:day=datetime.fromtimestamp(stamp,native_zone(activity_zone)).date().isoformat()
    except (ValueError,KeyError):return
    if day!=row[0]:return  # Historical corrections cannot trigger today's notification.
    await ensure_schema(conn)
    # Updating even the same scalar invalidates an older witness. Only this
    # validated writer reinstalls it, using the same clock/day/zone transaction.
    await conn.execute("INSERT INTO progressor_free_sessions(session_id,last_activity,status,completed_at,completion_basis,last_finished_at) VALUES(?,?,'active',NULL,NULL,NULL) ON CONFLICT(session_id) DO UPDATE SET last_activity=excluded.last_activity,status='active',completed_at=NULL,completion_basis=NULL",(session_id,stamp))
    await conn.execute('''INSERT INTO progressor_free_activity_proof(
        session_id,last_activity,source_local_date,activity_timezone,proof_version,clock_kind)
        VALUES(?,?,?,?,1,'native_touch') ON CONFLICT(session_id) DO UPDATE SET
        last_activity=excluded.last_activity,source_local_date=excluded.source_local_date,
        activity_timezone=excluded.activity_timezone,proof_version=excluded.proof_version,
        clock_kind=excluded.clock_kind''',(session_id,stamp,row[0],activity_zone))

def _finish(db,session_id,stamp,basis):
    state=db.execute('SELECT * FROM progressor_free_sessions WHERE session_id=?',(session_id,)).fetchone()
    if state and state['status']=='finished':return {'finished':True,'already_finished':True,'completed_at':state['completed_at']}
    sets=list(db.execute('SELECT DISTINCT user_exercise_id FROM sets WHERE session_id=? AND COALESCE(is_warmup,0)=0 AND (COALESCE(reps,0)>0 OR COALESCE(seconds,0)>0)',(session_id,)))
    columns={r[1] for r in db.execute('PRAGMA table_info(running_entries)')}
    runs=[]
    if {'user_exercise_id','is_draft','duration_sec','duration_ms'}.issubset(columns):
        runs=list(db.execute('SELECT DISTINCT user_exercise_id FROM running_entries WHERE session_id=? AND COALESCE(is_draft,0)=0 AND (COALESCE(duration_sec,0)>0 OR COALESCE(duration_ms,0)>0)',(session_id,)))
    ids={r[0] for r in sets+runs}
    if not ids:
        if state:db.execute("UPDATE progressor_free_sessions SET status='empty' WHERE session_id=?",(session_id,))
        return {'finished':False,'reason':'no_actual_records'}
    actual=state['last_activity'] if state else stamp
    completed=datetime.fromtimestamp(actual,timezone.utc).isoformat()
    for ue_id in ids:
        db.execute('INSERT INTO session_exercises(session_id,user_exercise_id,is_done,done_at) VALUES(?,?,1,?) ON CONFLICT(session_id,user_exercise_id) DO UPDATE SET is_done=1,done_at=COALESCE(session_exercises.done_at,excluded.done_at)',(session_id,ue_id,completed))
    db.execute("INSERT INTO progressor_free_sessions(session_id,last_activity,status,completed_at,completion_basis,last_finished_at) VALUES(?,?,'finished',?,?,?) ON CONFLICT(session_id) DO UPDATE SET status='finished',completed_at=excluded.completed_at,completion_basis=excluded.completion_basis,last_finished_at=excluded.last_finished_at",(session_id,actual,completed,basis,stamp))
    return {'finished':True,'already_finished':False,'completed_at':completed,'completion_basis':basis,'duration_seconds':None}

def finish(path,user_id,session_id,now=None):
    stamp=time.time() if now is None else now
    with closing(sqlite3.connect(path,timeout=5)) as db,db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE');_ensure_schema(db)
        owner=db.execute('SELECT s.date,u.tz FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.user_id=? AND s.day_index=0',(session_id,user_id)).fetchone()
        if not owner:raise ValueError('free_session_owner_mismatch')
        # Explicit completion of an old recorded day stays a historical edit.
        result=_finish(db,session_id,stamp,'explicit_finish')
    return result

def expire(path,now=None):
    stamp=time.time() if now is None else now
    with closing(sqlite3.connect(path,timeout=5)) as db,db:
        db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE');_ensure_schema(db)
        rows=list(db.execute("SELECT session_id FROM progressor_free_sessions WHERE status='active' AND last_activity<=? ORDER BY last_activity LIMIT 100",(stamp-IDLE_SECONDS,)))
        return [_finish(db,r['session_id'],stamp,'inactivity_90_minutes') for r in rows]

def current(path,tg_user_id):
    with closing(sqlite3.connect(path,timeout=3)) as db:
        db.row_factory=sqlite3.Row
        user=db.execute('SELECT id,tz FROM users WHERE tg_id=?',(tg_user_id,)).fetchone()
        if not user:return None
        day=datetime.now(native_zone(user['tz'] or 'UTC')).date().isoformat()
        session=db.execute('SELECT id,user_id FROM sessions WHERE user_id=? AND date=? AND day_index=0 ORDER BY id DESC LIMIT 1',(user['id'],day)).fetchone()
        return dict(session) if session else None
