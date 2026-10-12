"""Owner-local at-most-once reminder slot; a lost response is not retried."""
import sqlite3,time
from contextlib import closing

def reserve(path,tg_id,slot):
    with closing(sqlite3.connect(path,timeout=5)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS progressor_reminder_slots(user_id INTEGER,slot TEXT,reserved_at REAL,PRIMARY KEY(user_id,slot))')
        stamp=time.time();db.execute('DELETE FROM progressor_reminder_slots WHERE reserved_at<?',(stamp-90*86400,))
        return bool(db.execute('INSERT OR IGNORE INTO progressor_reminder_slots VALUES(?,?,?)',(tg_id,slot,stamp)).rowcount)
