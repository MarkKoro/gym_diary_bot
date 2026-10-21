/* Owner regressions execute the shipped HTML functions with independent storage. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const test=require('node:test'),assert=require('node:assert/strict');
const html=fs.readFileSync(path.join(__dirname,'../webapp/index.html'),'utf8');
const section=(start,end)=>{const a=html.indexOf(start),b=html.indexOf(end,a);assert(a>=0&&b>a);return html.slice(a,b)};
const code=[
 section('    function hasVerifiedOwnGymSubject()', '    window.ProgressorDomain='),
 section('    function activeOwnerContextKey()', '    function resetScopedCachesForActorSwitch()'),
 section('    let viewerIdentityLoading = null;', '    async function apiFetch('),
 section('    function workoutStorageScope()', '    function deriveDraft('),
 section('    function pendingAiApplyStorageKey(', '    function openAiCoachSheet()'),
 section('    async function loadSettingsOverview(', '    async function ensureSettingsOverviewLoaded('),
].join('\n');
function fixture({session=new Map(),local=new Map(),denied=false,api}={}){
 let currentLaunch=null,provider=api;const calls=[];
 const state={nativeSubject:'741',nativeIdentityProof:'proofA',initData:'proofA',userId:null,acting:{userId:null},
  dayIndex:1,exercises:new Map([[1,{exercise_id:141}]]),settings:{systems:{activeSystemId:0},requestId:0,days:[],remindersRevision:0},
  aiCoach:{loading:false,applying:false,parsed:null,mode:'replace_exercises',requestId:0,hasResponse:false,summary:''},currentRoute:'today'};
 const storage=map=>({getItem(k){calls.push(['get',k]);if(denied)throw Error('denied');return map.get(k)||null},setItem(k,v){calls.push(['set',k]);if(denied)throw Error('denied');map.set(k,v)},removeItem(k){calls.push(['remove',k]);if(denied)throw Error('denied');map.delete(k)}});
 const context={state,window:{Progressor:{_launchBridge:{getState:()=>currentLaunch}}},location:{pathname:'/gymapp_prod/'},
  localStorage:storage(local),sessionStorage:storage(session),Date,Number,String,Map,Set,Object,JSON,Promise,RegExp,
  getAllExercisesDate:()=> '2030-01-02',getIsoDate:()=> '2030-01-02',loadViewerRole:async()=>{},
  aiCoachContextKey:()=>context.activeOwnerContextKey()+':'+state.settings.systems.activeSystemId,
  document:{getElementById:()=>null},getAiActionDecisionKey:(_,i)=>String(i),updateAiCoachCounter(){},renderAiCoachResult(){},toast(){},
  apiFetch:async(...args)=>{calls.push(['api',...args]);return provider?provider(...args):{found:false}},
  setTimeout:(fn,ms)=>setTimeout(fn,Math.min(ms,10)),clearTimeout,
  renderSettings(){},syncSetOperationControls(){},mergeDayLabels:(_,days)=>days};
 vm.createContext(context);vm.runInContext(code,context,{filename:'actual-owner-storage.js'});
 const setOwner=(subject,proof)=>{state.nativeSubject=subject;state.nativeIdentityProof=proof;state.initData=proof};
 return {context,state,session,local,calls,setOwner,setLaunch(value){currentLaunch=value},setApi(value){provider=value}};
}
const values={weight_kg:93.5,reps:19,seconds:0},proposal={request_id:'owner_pending_741',system_id:0,actions:[{type:'add_exercise',day_index:1,exercise_name:'A private'}]};
test('systems unavailable: same reference exercise never transfers last values A→B→A',()=>{
 const f=fixture(),ex={exercise_id:141};const aKey=f.context.getLastValuesCacheKey(ex);
 f.context.saveCachedLastValues(ex,values);f.setOwner('742','proofB');const bKey=f.context.getLastValuesCacheKey(ex);
 assert.notEqual(aKey,bKey);assert.equal(f.context.getCachedLastValues(ex),null);
 f.context.saveCachedLastValues(ex,{weight_kg:22,reps:8,seconds:0});f.setOwner('741','fresh-proofA');
 assert.equal(f.context.getCachedLastValues(ex).weight_kg,93.5);
});
test('SDK hints never select the owner namespace',()=>{const f=fixture();f.state.userId=999;assert.match(f.context.workoutStorageScope(),/viewer:741:self:0$/);assert.doesNotMatch(f.context.workoutStorageScope(),/999/)});
test('viewer and acting owner are separate even for identical target id',()=>{const f=fixture();f.state.acting.userId=17;const key=f.context.workoutDraftKey(1,'sets');f.setOwner('742','B');assert.notEqual(key,f.context.workoutDraftKey(1,'sets'));f.state.acting.userId=null;assert.notEqual(key,f.context.workoutDraftKey(1,'sets'))});
test('unverified owner never reads/writes shared storage or pending data',async()=>{
 const f=fixture();f.state.nativeIdentityProof='old';
 assert.equal(f.context.workoutStorageScope(),null);assert.equal(f.context.getCachedLastValues({exercise_id:141}),null);f.context.saveCachedLastValues({exercise_id:141},values);
 assert.equal(f.context.readWorkoutDraft(1,'sets'),null);f.context.persistWorkoutDraft(1,'sets',values);f.context.storePendingAiApply(proposal);await f.context.restorePendingAiApply();assert.equal(f.calls.filter(c=>c[0]!=='api').length,0);
});
test('Core mismatch refuses cache; Core outage retains valid native-owner cache',()=>{
 const f=fixture();f.setLaunch({session:{user:{id:'742'}},launchData:'proofA'});assert.equal(f.context.workoutStorageScope(),null);
 f.setLaunch(null);assert.match(f.context.workoutStorageScope(),/viewer:741:self/);
});
test('new proof changes late-response guard but keeps same-owner persisted recovery',()=>{
 const f=fixture();const oldContext=f.context.activeOwnerContextKey(),oldStorage=f.context.workoutDraftKey(1,'sets');f.context.persistWorkoutDraft(1,'sets',values);
 f.setOwner('741','fresh-proof');assert.notEqual(f.context.activeOwnerContextKey(),oldContext);assert.equal(f.context.workoutDraftKey(1,'sets'),oldStorage);assert.equal(f.context.readWorkoutDraft(1,'sets').weight_kg,93.5);
});
test('unverified proof transitions also invalidate runtime guards',()=>{const f=fixture();f.state.nativeSubject=null;const old=f.context.activeOwnerContextKey();f.state.initData='another';assert.notEqual(old,f.context.activeOwnerContextKey())});
test('pending AI proposal remains with A while B has independent pending and recovery',async()=>{
 const f=fixture();f.context.storePendingAiApply(proposal);const aKey=f.context.pendingAiApplyStorageKey();
 f.setOwner('742','B');await f.context.restorePendingAiApply();assert.equal(f.state.aiCoach.parsed,null);assert.equal(f.calls.filter(c=>c[0]==='api').length,0);
 const bKey=f.context.pendingAiApplyStorageKey();assert.notEqual(aKey,bKey);f.context.storePendingAiApply({...proposal,request_id:'owner_pending_742'});
 f.setOwner('741','newA');await f.context.restorePendingAiApply();assert.equal(f.state.aiCoach.parsed.actions[0].exercise_name,'A private');assert(f.session.has(aKey)&&f.session.has(bKey));
});
test('clearing one owner receipt cannot delete another owner pending record',()=>{const f=fixture();const owner=f.context.nativeOwnerStorageScope();f.context.storePendingAiApply(proposal);f.setOwner('742','B');f.context.storePendingAiApply({...proposal,request_id:'owner_pending_742'});const b=f.context.pendingAiApplyStorageKey();f.context.clearPendingAiApply(owner,proposal.request_id);assert.equal(f.session.size,1);assert(f.session.has(b))});
test('legacy unbound guest/self entries are ignored without guessing a migration',()=>{
 const f=fixture();f.local.set('gd_last_vals_v2:/gymapp_prod/:guest:self:0:141',JSON.stringify(values));f.session.set('gym_diary_ai_apply_v1:self',JSON.stringify({owner:'self',payload:proposal}));
 assert.equal(f.context.getCachedLastValues({exercise_id:141}),null);assert.match(f.context.pendingAiApplyStorageKey(),/v2:viewer:741:/);assert.equal(f.local.size,1);
});
test('draft validation preserves12h expiry and never reads another kind/owner',()=>{
 const f=fixture();f.context.persistWorkoutDraft(1,'sets',values);assert.equal(f.context.readWorkoutDraft(1,'sets').reps,19);f.setOwner('742','B');assert.equal(f.context.readWorkoutDraft(1,'sets'),null);f.setOwner('741','A');
 const key=f.context.workoutDraftKey(1,'sets');f.session.set(key,JSON.stringify({savedAt:Date.now()-13*3600000,values}));assert.equal(f.context.readWorkoutDraft(1,'sets'),null);
});
test('storage denial remains a safe cache miss',()=>{const f=fixture({denied:true});f.context.persistWorkoutDraft(1,'sets',values);f.context.saveCachedLastValues({exercise_id:141},values);f.context.storePendingAiApply(proposal);assert.equal(f.context.readWorkoutDraft(1,'sets'),null);assert.equal(f.context.getCachedLastValues({exercise_id:141}),null)});
test('actual settings loader ignores held A response after genuine owner/proof changes',async()=>{
 let release;const response=new Promise(r=>release=r);const f=fixture({api:()=>response});const work=f.context.loadSettingsOverview();f.setOwner('742','proofB');f.state.settings.workoutsPerWeek=2;
 release({workouts_per_week:1,days:[{label:'A private'}]});await work;assert.equal(f.state.settings.workoutsPerWeek,2);assert.equal(f.state.settings.days.length,0);
});
test('identity JSON/body hang has a total deadline and verification can retry afterwards',async()=>{
 const f=fixture({api:()=>new Promise(()=>{})});await f.context.loadViewerRole();assert.equal(f.state.nativeSubject,null);
 assert.equal(f.calls[0][2].timeoutMs,1800);assert.equal(f.calls[0][2].retryReads,false);
 f.setApi(()=>({ok:true,tg_id:741}));await f.context.loadViewerRole();assert.equal(f.state.nativeSubject,'741');assert.equal(f.context.hasVerifiedOwnGymSubject(),true);
});
test('late old identity response cannot bind cache to a replacement proof',async()=>{
 let release;const f=fixture({api:()=>new Promise(r=>release=r)});const old=f.context.loadViewerRole();f.state.initData='B';release({ok:true,tg_id:741});await old;assert.equal(f.context.nativeOwnerStorageScope(),null);
});
test('concurrent identity callers share bounded JSON probe; expired result cannot replace newer success',async()=>{
 let releaseOld;const f=fixture({api:()=>new Promise(r=>releaseOld=r)});
 const first=f.context.loadViewerRole(),second=f.context.loadViewerRole();await Promise.all([first,second]);
 assert.equal(f.calls.filter(c=>c[0]==='api').length,1);assert.equal(f.state.nativeSubject,null);
 f.state.initData='proofB';f.setApi(()=>({ok:true,tg_id:742}));await f.context.loadViewerRole();
 assert.equal(f.state.nativeSubject,'742');assert.equal(f.state.nativeIdentityProof,'proofB');
 releaseOld({ok:true,tg_id:741});await new Promise(r=>setImmediate(r));
 assert.equal(f.state.nativeSubject,'742');assert.equal(f.state.nativeIdentityProof,'proofB');assert.equal(f.context.hasVerifiedOwnGymSubject(),true);
});
