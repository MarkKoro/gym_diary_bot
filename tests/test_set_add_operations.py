"""Actual Gym API/SQLite: add intent survives lost replies without duplicate sets."""
import asyncio,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
import httpx,db
import webapp_backend as api

class SetAddOperations(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
  self.dbpatch=patch.object(db,'DB_PATH',str(Path(self.tmp.name)/'gym.sqlite3'));self.dbpatch.start()
  await db.init_db()
  self.owner=await db.get_or_create_user(900000000081,'owner');self.other=await db.get_or_create_user(900000000082,'other');self.trainer=await db.get_or_create_user(900000000083,'trainer')
  self.system=await db.ensure_training_system_defaults(self.owner);await db.set_workouts_per_week(self.owner,1)
  async with db.connect_db() as c:
   self.ex=(await c.execute("INSERT INTO exercises(name,muscle_group,created_by_user_id) VALUES('Receipt squat','legs',?)",(self.owner,))).lastrowid;await c.commit()
  await db.add_user_exercise(self.owner,1,self.ex)
  async with db.connect_db() as c:self.ue=(await (await c.execute('SELECT id FROM user_exercises WHERE user_id=? AND day_index=1 AND exercise_id=?',(self.owner,self.ex))).fetchone())[0]
  self.ctx=api.AuthCtx(900000000081,self.owner,'owner',None,None,int(time.time()));self.day='2030-01-10';self.seq=0
 async def asyncTearDown(self):self.dbpatch.stop();self.tmp.cleanup()
 def payload(self):
  self.seq+=1;return dict(reps=10,seconds=0,weight_kg=30,is_warmup=False,operation_id=f'{self.seq:032x}')
 async def add(self,surface='today',p=None,ctx=None,day=None):
  p=self.payload() if p is None else p;ctx=ctx or self.ctx
  if surface=='today':return await api.add_set_fast(1,self.ue,payload=p,date=day or self.day,ctx=ctx)
  return await api.all_exercise_add_set(self.ex,payload=p,date=day or self.day,ctx=ctx)
 async def rows(self,table):
  async with db.connect_db() as c:return await (await c.execute(f'SELECT * FROM {table}')).fetchall()
 async def trainer_ctx(self):
  async with db.connect_db() as c:
   await c.execute("INSERT INTO trainer_links(trainer_user_id,trainee_user_id,status,can_edit_plan,created_at) VALUES(?,?,'accepted',1,'2030-01-01')",(self.trainer,self.owner));await c.commit()
  return api.AuthCtx(900000000083,self.owner,'trainer',None,None,int(time.time()),actor_user_id=self.trainer,acting_can_edit=True,is_acting=True)
 async def test_both_surfaces_lost_200_retry_has_one_receipt_and_one_set(self):
  for surface in ('today','all_exercises'):
   p=self.payload();a=await self.add(surface,p);b=await self.add(surface,p)
   self.assertFalse(a['operation']['replayed']);self.assertTrue(b['operation']['replayed']);self.assertEqual(a['operation']['set_id'],b['operation']['set_id']);self.assertEqual(len(b['sets']),1)
  self.assertEqual(len(await self.rows('sets')),2);self.assertEqual(len(await self.rows('set_add_operations')),2)
 async def test_both_surfaces_intentional_identical_sets_remain_distinct(self):
  for surface in ('today','all_exercises'):
   a,b=await self.add(surface),await self.add(surface)
   self.assertNotEqual(a['operation']['set_id'],b['operation']['set_id']);self.assertEqual(len(b['sets']),2)
 async def test_concurrent_retries_commit_one_set(self):
  for surface in ('today','all_exercises'):
   p=self.payload();rs=await asyncio.gather(*(self.add(surface,p) for _ in range(4)))
   self.assertEqual(len({r['operation']['set_id'] for r in rs}),1);self.assertEqual(sum(not r['operation']['replayed'] for r in rs),1)
 async def test_changed_payload_conflicts_without_changing_original(self):
  p=self.payload();a=await self.add(p=p)
  for field,value in (('reps',11),('weight_kg',31),('seconds',10),('is_warmup',True)):
   with self.subTest(field=field):
    with self.assertRaises(api.HTTPException) as caught:await self.add(p={**p,field:value})
    self.assertEqual(caught.exception.status_code,409)
  self.assertEqual(a['sets'],(await self.add(p=p))['sets']);self.assertEqual(len(await self.rows('sets')),1)
 async def test_same_key_different_date_or_surface_conflicts(self):
  p=self.payload();await self.add(p=p)
  for surface,day in (('today','2030-01-11'),('all_exercises',self.day)):
   with self.assertRaises(api.HTTPException) as caught:await self.add(surface,p,day=day)
   self.assertEqual(caught.exception.status_code,409)
  self.assertEqual(len(await self.rows('sets')),1)
 async def test_replay_cannot_restore_deleted_set_when_number_reused(self):
  for surface in ('today','all_exercises'):
   p=self.payload();a=await self.add(surface,p);ue=self.ue if surface=='today' else a['user_exercise_id']
   await db.remove_last_set(ue,a['operation']['session_id']);b=await self.add(surface);r=await self.add(surface,p)
   self.assertEqual(r['operation']['state'],'removed');self.assertEqual(r['operation']['set_id'],a['operation']['set_id']);self.assertEqual(r['sets'],b['sets']);self.assertNotEqual(a['operation']['set_id'],b['operation']['set_id'])
 async def test_replay_preserves_later_edit_without_touching_free_session(self):
  p=self.payload();a=await self.add('all_exercises',p)
  async with db.connect_db() as c:
   await c.execute('UPDATE sets SET weight_kg=42 WHERE id=?',(a['operation']['set_id'],));await c.execute(__import__('progressor_free_workout').SCHEMA)
   await c.execute("INSERT OR REPLACE INTO progressor_free_sessions VALUES(?,100,'finished','2030-01-10T12:00:00+00:00','explicit_finish',200)",(a['operation']['session_id'],));await c.commit()
  before=await self.rows('progressor_free_sessions');r=await self.add('all_exercises',p)
  self.assertEqual(r['sets'][0]['weight_kg'],42);self.assertEqual(before,await self.rows('progressor_free_sessions'))
 async def test_failed_transaction_rolls_back_receipt_and_append(self):
  p=self.payload()
  with patch('progressor_free_workout.touch',new=AsyncMock(side_effect=RuntimeError('synthetic rollback'))):
   with self.assertRaises(RuntimeError):await self.add(p=p)
  self.assertEqual(await self.rows('sets'),[]);self.assertEqual(await self.rows('set_add_operations'),[])
  self.assertFalse((await self.add(p=p))['operation']['replayed'])
 async def test_cross_owner_key_and_session_exercise_mismatch_cannot_write(self):
  p=self.payload();await self.add(p=p);sid=await db.get_or_create_today_session(self.other,self.day,1,0)
  async with db.connect_db() as c:
   ue=(await c.execute('INSERT INTO user_exercises(user_id,exercise_id,day_index) VALUES(?,?,1)',(self.other,self.ex))).lastrowid;await c.commit()
  with self.assertRaises(db.SetOperationConflict):await db.add_set(sid,ue,10,0,30,operation_id=p['operation_id'],owner_id=self.other,actor_id=self.other,request_context='day:1:1:2030-01-10')
  with self.assertRaises(db.SetOperationAccessError):await db.add_set(sid,self.ue,10,0,30,operation_id=self.payload()['operation_id'],owner_id=self.other,actor_id=self.other,request_context='test')
  self.assertEqual(len(await self.rows('sets')),1)
 async def test_revoked_trainer_permission_is_rechecked_before_replay(self):
  ctx=await self.trainer_ctx();p=self.payload();await self.add(p=p,ctx=ctx)
  async with db.connect_db() as c:await c.execute('UPDATE trainer_links SET can_edit_plan=0');await c.commit()
  with self.assertRaises(api.HTTPException) as caught:await self.add(p=p,ctx=ctx)
  self.assertEqual(caught.exception.status_code,403);self.assertEqual(len(await self.rows('sets')),1)
  with self.assertRaises(api.HTTPException) as caught:await self.add('all_exercises',p,ctx=ctx)
  self.assertEqual(caught.exception.status_code,403)
 async def test_owner_cannot_reuse_trainer_key(self):
  ctx=await self.trainer_ctx();p=self.payload();await self.add(p=p,ctx=ctx)
  with self.assertRaises(api.HTTPException) as caught:await self.add(p=p)
  self.assertEqual(caught.exception.status_code,409)
 async def test_legacy_clients_without_key_still_append(self):
  for surface in ('today','all_exercises'):
   p=dict(reps=10,seconds=0,weight_kg=30);await self.add(surface,p);r=await self.add(surface,p)
   self.assertEqual(len(r['sets']),2);self.assertIsNone(r['operation'])
  self.assertEqual(await self.rows('set_add_operations'),[])
 async def test_invalid_key_or_missing_original_values_reject_before_session(self):
  for surface in ('today','all_exercises'):
   for p in ({'operation_id':[]},{'operation_id':'short'},{'operation_id':'a'*32,'reps':10}):
    with self.assertRaises(api.HTTPException) as caught:await self.add(surface,p)
    self.assertEqual(caught.exception.status_code,400)
  self.assertEqual(await self.rows('sessions'),[]);self.assertEqual(await self.rows('sets'),[])
 async def test_whoami_advertises_owned_operation_capability_without_workout_write(self):
  response=await api.whoami(self.ctx)
  self.assertEqual(response['set_add_operations_version'],1);self.assertEqual(response['tg_id'],900000000081)
  self.assertEqual(await self.rows('sets'),[]);self.assertEqual(await self.rows('sessions'),[])
 async def test_versioned_routes_require_key_and_only_append_once(self):
  api.app.dependency_overrides[api.get_auth_ctx]=lambda:self.ctx
  try:
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://synthetic') as client:
    for url in (f'/day/1/exercise/{self.ue}/set/add_once?date={self.day}',f'/all_exercises/exercise/{self.ex}/set/add_once?date={self.day}'):
     rejected=await client.post(url,json={'reps':10,'seconds':0,'weight_kg':30})
     self.assertEqual(rejected.status_code,400,rejected.text)
     p=self.payload();a=await client.post(url,json=p);b=await client.post(url,json=p)
     self.assertEqual(a.status_code,200,a.text);self.assertEqual(b.status_code,200,b.text)
     self.assertEqual(len(b.json()['sets']),1);self.assertTrue(b.json()['operation']['replayed'])
  finally:api.app.dependency_overrides.pop(api.get_auth_ctx,None)
  self.assertEqual(len(await self.rows('sets')),2)
 async def test_http_receipt_and_payload_conflict_409(self):
  api.app.dependency_overrides[api.get_auth_ctx]=lambda:self.ctx
  try:
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://synthetic') as client:
    for url in (f'/day/1/exercise/{self.ue}/set/add?date={self.day}',f'/all_exercises/exercise/{self.ex}/set/add?date={self.day}'):
     p=self.payload();a=await client.post(url,json=p);b=await client.post(url,json=p)
     self.assertEqual(a.status_code,200,a.text);self.assertEqual(b.status_code,200,b.text);self.assertTrue(b.json()['operation']['replayed'])
     self.assertEqual((await client.post(url,json={**p,'weight_kg':50})).status_code,409)
  finally:api.app.dependency_overrides.pop(api.get_auth_ctx,None)
 async def test_wipe_erases_only_owners_receipts(self):
  await self.add();await db.wipe_user(self.other);self.assertEqual(len(await self.rows('set_add_operations')),1)
  await db.wipe_user(self.owner);self.assertEqual(await self.rows('set_add_operations'),[]);self.assertEqual(await self.rows('sets'),[])

if __name__=='__main__':unittest.main()
