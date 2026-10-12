import db
from progressor_timezone_history import preview,record,zone
from datetime import datetime,timezone

async def change(uid,tg_id,body):
    selected=body.get('timezone');zone(selected)
    from zoneinfo import ZoneInfo
    try:ZoneInfo(selected)
    except (ValueError,KeyError):raise ValueError('invalid_timezone')
    if body.get('action') not in ('preview','apply'):raise ValueError('invalid_action')
    async with db.connect_db() as conn:
        await conn.execute('BEGIN IMMEDIATE')
        user=await (await conn.execute('SELECT tg_id,tz FROM users WHERE id=?',(uid,))).fetchone()
        if not user or user[0]!=tg_id:raise ValueError('wrong_owner')
        current=user[1] or 'UTC'
        rows=await (await conn.execute('SELECT dow,hour,minute FROM user_reminders WHERE user_id=?',(uid,))).fetchall()
        slots=[['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][r[0]]+f' {r[1]:02d}:{r[2]:02d}' for r in rows]
        value=preview(current,selected,slots)
        if body['action']=='apply':
            if body.get('expected_timezone')!=current:raise ValueError('timezone_changed')
            await record(conn,tg_id,current,selected)
            await conn.execute('UPDATE users SET tz=? WHERE id=?',(selected,uid))
            await conn.execute("INSERT INTO app_meta(key,value) VALUES('reminders_updated_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(datetime.now(timezone.utc).isoformat(),))
        await conn.commit()
        return {**value,'applied':body['action']=='apply'}
