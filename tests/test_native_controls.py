import os,tempfile,unittest,time
from pathlib import Path
from unittest.mock import patch,AsyncMock
import db
import webapp_backend as api
from progressor_ai_guard import acquire,finish


class NativeControls(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.path=str(Path(self.tmp.name)/'gym.db');self.p=patch.object(db,'DB_PATH',self.path);self.p.start()
        await db.init_db();self.uid=await db.get_or_create_user(900000000001,'offline')
    async def asyncTearDown(self):self.p.stop();self.tmp.cleanup()
    async def test_completion_retry_preserves_duration_and_history(self):
        session=await db.get_or_create_today_session(self.uid,'2026-10-07',1,0)
        await db.mark_day_completed(self.uid,1,'2026-10-07T09:00:00+00:00',0,session_id=session,duration_seconds=3600)
        await db.mark_day_completed(self.uid,1,'2026-10-07T09:01:00+00:00',0,session_id=session)
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM day_completion_history')).fetchone())[0],1)
            self.assertEqual((await (await conn.execute('SELECT duration_seconds FROM workout_session_details')).fetchone())[0],3600)
    async def test_foreign_session_never_completed(self):
        other=await db.get_or_create_user(900000000002,'other')
        session=await db.get_or_create_today_session(other,'2026-10-07',1,0)
        with self.assertRaises(ValueError):await db.mark_day_completed(self.uid,1,'2026-10-07T09:00:00+00:00',0,session_id=session)
    async def test_requester_lock_precedes_quota_and_provider(self):
        token=acquire(self.path,900000000001,'gym_coach')
        ctx=api.AuthCtx(900000000001,self.uid,None,None,None,int(time.time()),actor_user_id=77,is_acting=True)
        quota=AsyncMock();provider=AsyncMock()
        with patch.object(db,'get_active_subscription',AsyncMock(return_value={'native':True})),patch.object(api,'consume_ai_coach_quota',quota),patch.object(api,'_run_ai_coach_query',provider):
            with self.assertRaises(api.HTTPException) as exc:await api.ai_coach_query(payload={'mode':'mistakes_analysis'},ctx=ctx)
        self.assertEqual(exc.exception.status_code,429);quota.assert_not_awaited();provider.assert_not_awaited();finish(self.path,token)
    async def test_bad_duration_rejected_before_completion(self):
        ctx=api.AuthCtx(900000000001,self.uid,None,None,None,int(time.time()))
        with patch.object(api,'_validate_day',AsyncMock(return_value=(1,[1]))),patch.object(api,'get_user_timezone',AsyncMock(return_value='UTC')),patch.object(api,'get_active_training_system_id',AsyncMock(return_value=0)),patch.object(api,'mark_day_completed',AsyncMock()) as completion:
            with self.assertRaises(api.HTTPException) as exc:await api.complete_day(1,date='2026-10-07',payload={'duration_minutes':True},ctx=ctx)
        self.assertEqual(exc.exception.status_code,422);completion.assert_not_awaited()
