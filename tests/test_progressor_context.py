import os
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import AsyncMock,patch
import db
import webapp_backend as api
import progressor_client as client

class CrossContext(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'gym.db')
        self.patch=patch.object(db,'DB_PATH',self.path);self.patch.start();await db.init_db()
        self.uid=await db.get_or_create_user(900000000001,'offline');client.ensure_schema(self.path)
    async def asyncTearDown(self):self.patch.stop();self.tmp.cleanup()
    async def test_bundle_gym_access_preserves_native_renewal(self):
        with patch.dict(os.environ,PROGRESSOR_CLIENT_ENABLED='1'):
            future=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat();client.apply_grants(self.path,[{'user_id':'900000000001','expires_at':future,'revision':1}])
            self.assertEqual((await db.get_active_subscription(self.uid))['plan'],'progressor_bundle')
            await db.grant_subscription_days(self.uid,10,'manual')
            client.apply_grants(self.path,[{'user_id':'900000000001','expires_at':'1970-01-01T00:00:00Z','revision':2}])
            self.assertEqual((await db.get_active_subscription(self.uid))['plan'],'manual')
    async def test_actual_gym_ai_prompt_and_response_sources(self):
        shared={'schema_version':1,'prompt_version':'progressor.cross_context.v1','sources':[{'source':'supply'}],'data':{'supply':{'reported_profile':{'height_cm':183,'weight_kg':84}}}}
        own={'user_profile':{'workouts_per_week':3},'catalog_context':{},'day_snapshots':[]}
        captured=[]
        async def llm(system,user,**kwargs):
            captured.append(user);return {'parsed':{'summary':'Проверка.'*20,'rationale':['one','two','three'],'action_plan':{'actions':[]}}}
        with patch('progressor_client.ai_context',AsyncMock(return_value=shared)),patch.object(api,'_build_ai_context_payload',AsyncMock(return_value=own)),patch.object(api,'_call_openai_chat',llm):
            response=await api._run_ai_coach_query(self.uid,'mistakes_analysis','Проверь',{}, {})
        self.assertIn('183',captured[0]);self.assertIn('84',captured[0]);self.assertIn('progressor_context',captured[0]);self.assertEqual(response['context_sources'],[{'source':'supply'}])
        with patch('progressor_client.ai_context',AsyncMock(return_value=None)),patch.object(api,'_build_ai_context_payload',AsyncMock(return_value=own)),patch.object(api,'_call_openai_chat',llm):
            response=await api._run_ai_coach_query(self.uid,'mistakes_analysis','Проверь',{}, {})
        self.assertNotIn('progressor_context',captured[1]);self.assertEqual(response['context_sources'],[])
