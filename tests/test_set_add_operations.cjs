/* Executes the actual shipped HTML functions, not a second implementation. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto').webcrypto;
const html=fs.readFileSync(path.join(__dirname,'../webapp/index.html'),'utf8');
const start=html.indexOf('    // Pending add intentions are separate'),end=html.indexOf('    async function removeSet(',start);
assert(start>0&&end>start);
const ownerStart=html.indexOf('    function activeOwnerContextKey()'),ownerEnd=html.indexOf('    function resetNativeOwnerMemory()',ownerStart);
assert(ownerStart>0&&ownerEnd>ownerStart);
const source=html.slice(ownerStart,ownerEnd)+html.slice(start,end)+'\n globalThis.subject={queueAddSet,readSetOperation,setOperationContext,pendingSetOperations,activeSetOperations,activeOwnerContextKey};';
function fixture({storage=new Map(),failStorage=false,provider,identityProvider,secure=true,verified=true,version=1}={}){
 const ex={sets:[],exercise_id:12,user_exercise_id:5};let actor='self',date='2030-01-10',draft={reps:10,weight_kg:30,seconds:0},n=0,requests=[],applied=[],toasts=[];
 const state={setAddOperationsVersion:version,nativeSubject:'123',nativeIdentityProof:'proof',initData:'proof',settings:{systems:{activeSystemId:1}},draftRevision:{5:0},draftDirty:{5:false},exercises:new Map([[5,ex]]),acting:null,editor:{ueId:null,selectedSet:null}};
 const context={console,Map,Uint8Array,Number,Boolean,JSON,Promise,Error,crypto:secure?crypto:null,state,location:{pathname:'/gymapp/'},hasVerifiedOwnGymSubject:()=>verified,loadViewerRole:async()=>{await identityProvider?.(state)},
 sessionStorage:{getItem(k){if(failStorage)throw Error('denied');return storage.get(k)||null},setItem(k,v){if(failStorage)throw Error('denied');storage.set(k,v)},removeItem(k){if(failStorage)throw Error('denied');storage.delete(k)}},
 getExerciseActionSource:()=> 'today',getAllExercisesDate:()=>date,getIsoDate:()=>date,workoutStorageScope:()=>actor,
 getEditorActionUrl:(_ue,action)=>`/day/1/exercise/5/${action}?date=${date}`,getExerciseCards:()=>[],document:{getElementById:()=>null},
 ensureDraft:()=>({...draft}),flushInlineNumberInput:async()=>{},queueExerciseAction:async(_,f)=>f(),
 triggerHaptic(){},applySetsUpdate(_,sets){ex.sets=sets;applied.push(sets)},setFlashSet(){},scheduleAllExercisesMetaRefresh(){},toast(t){toasts.push(t)},
 apiFetch:async(url,options)=>{const p=JSON.parse(options.body);requests.push({url,p});n++;if(provider)return provider({url,p,n});return {sets:[{set_no:1,...p}],operation:{operation_id:p.operation_id,set_id:n,session_id:1,state:'present',replayed:false}}}
 };
 vm.createContext(context);vm.runInContext(source,context,{filename:'shipped-set-intents.js'});
 return {subject:context.subject,state,ex,requests,storage,applied,toasts,setDraft(x){draft={...draft,...x};state.draftDirty[5]=true;state.draftRevision[5]++},setActor(a){actor=a;state.nativeSubject=a;context.activeOwnerContextKey()},setProof(p){state.initData=p;state.nativeIdentityProof=p;context.activeOwnerContextKey()},setDate(d){date=d}};
}
const ack=(p,{replayed=false,id=1,sets=[]}={})=>({sets,operation:{operation_id:p.operation_id,set_id:id,session_id:1,state:'present',replayed}});
const turn=()=>new Promise(r=>setImmediate(r));
test('each confirmed identical physical set gets a fresh key',async()=>{const f=fixture();await f.subject.queueAddSet(5);await f.subject.queueAddSet(5);assert.equal(f.requests.length,2);assert.notEqual(f.requests[0].p.operation_id,f.requests[1].p.operation_id);assert.equal(f.storage.size,0)});
test('unknown result retains key and retries original values while preserving edited draft',async()=>{
 const f=fixture({provider:({p,n})=>{if(n===1)throw Error('lost HTTP reply');return ack(p,{replayed:true,sets:[{set_no:1,reps:10,weight_kg:30,seconds:0}]})}});
 await assert.rejects(f.subject.queueAddSet(5),e=>e.setOperationPending===true);assert.equal(f.storage.size,1);f.setDraft({weight_kg:35});
 await f.subject.queueAddSet(5);assert.equal(f.requests[0].p.operation_id,f.requests[1].p.operation_id);assert.equal(f.requests[1].p.weight_kg,30);assert.equal(f.state.draftDirty[5],true);assert.equal(f.storage.size,0);
});
test('double activation while first reply is pending sends one request',async()=>{let release;const held=new Promise(r=>release=r);const f=fixture({provider:async({p})=>{await held;return ack(p)}});const a=f.subject.queueAddSet(5),b=f.subject.queueAddSet(5);assert.equal(a,b);await turn();assert.equal(f.requests.length,1);release();await Promise.all([a,b]);assert.equal(f.requests.length,1)});
test('tab reload restores the unresolved key',async()=>{const storage=new Map(),a=fixture({storage,provider:()=>{throw Error('lost')}});await assert.rejects(a.subject.queueAddSet(5));const b=fixture({storage,provider:({p})=>ack(p,{replayed:true})});await b.subject.queueAddSet(5);assert.equal(a.requests[0].p.operation_id,b.requests[0].p.operation_id);assert.equal(storage.size,0)});
test('late response cannot apply sets in another account',async()=>{let release;const held=new Promise(r=>release=r);const f=fixture({provider:async({p})=>{await held;return ack(p,{sets:[{set_no:1,reps:10}]})}});const promise=f.subject.queueAddSet(5);await turn();const before=f.applied.length;f.setActor('another');release();assert.equal(await promise,null);assert.equal(f.applied.length,before);assert.equal(f.storage.size,0)});
test('malformed acknowledgment does not clear pending operation',async()=>{const f=fixture({provider:({p,n})=>n===1?{sets:[],operation:null}:ack(p,{replayed:true})});await assert.rejects(f.subject.queueAddSet(5));assert.equal(f.storage.size,1);await f.subject.queueAddSet(5);assert.equal(f.requests[0].p.operation_id,f.requests[1].p.operation_id)});
test('storage refusal keeps same-view in-memory recovery',async()=>{const f=fixture({failStorage:true,provider:({p,n})=>{if(n===1)throw Error('lost');return ack(p,{replayed:true})}});await assert.rejects(f.subject.queueAddSet(5));await f.subject.queueAddSet(5);assert.equal(f.requests[0].p.operation_id,f.requests[1].p.operation_id)});
test('pending intentions do not cross dates, returning reuses original key',async()=>{const f=fixture({provider:({p,n})=>{if(n===1)throw Error('lost');return ack(p)}});await assert.rejects(f.subject.queueAddSet(5));f.setDate('2030-01-11');await f.subject.queueAddSet(5);f.setDate('2030-01-10');await f.subject.queueAddSet(5);assert.notEqual(f.requests[0].p.operation_id,f.requests[1].p.operation_id);assert.equal(f.requests[0].p.operation_id,f.requests[2].p.operation_id)});
test('context changed before queue execution sends nothing',async()=>{const f=fixture();const p=f.subject.queueAddSet(5);f.setActor('another');assert.equal(await p,null);assert.equal(f.requests.length,0)});
test('secure key unavailable fails before sending a request',async()=>{const f=fixture({secure:false});await assert.rejects(f.subject.queueAddSet(5));assert.equal(f.requests.length,0);assert.equal(f.storage.size,0)});

test('old API capability refuses before a potentially non-idempotent POST',async()=>{const f=fixture({version:0});await assert.rejects(f.subject.queueAddSet(5),e=>e.setOperationUnavailable===true);assert.equal(f.requests.length,0);assert.equal(f.storage.size,0)});
test('unverified native identity refuses before POST',async()=>{const f=fixture({verified:false});await assert.rejects(f.subject.queueAddSet(5),e=>e.setOperationUnavailable===true);assert.equal(f.requests.length,0);assert.equal(f.storage.size,0)});

test('404 from rolled-back API keeps the same pending key and never uses append-only path',async()=>{const f=fixture({provider:({p,n})=>{if(n===1)throw Object.assign(Error('old API has no route'),{status:404});return ack(p)}});await assert.rejects(f.subject.queueAddSet(5),e=>e.setOperationPending===true);assert.equal(f.storage.size,1);await f.subject.queueAddSet(5);assert.equal(f.requests[0].p.operation_id,f.requests[1].p.operation_id);assert(f.requests.every(r=>r.url.includes('/set/add_once?')));assert.equal(f.storage.size,0)});


test('pending recovery key is stable for same verified owner under a fresh proof',async()=>{const storage=new Map(),f=fixture({storage,provider:()=>{throw Error('lost')}});await assert.rejects(f.subject.queueAddSet(5));const before=f.subject.setOperationContext(5);f.setProof('fresh-proof');const after=f.subject.setOperationContext(5);assert.equal(before.key,after.key);assert.notEqual(before.runtimeOwner,after.runtimeOwner);assert.equal(f.subject.readSetOperation(after).operation_id,f.requests[0].p.operation_id)});
test('late response after owner ABA cannot apply the old snapshot',async()=>{let release;const held=new Promise(r=>release=r);const f=fixture({provider:async({p})=>{await held;return ack(p,{sets:[{set_no:1,reps:10}]})}});const work=f.subject.queueAddSet(5);await turn();const applied=f.applied.length;f.setActor('another');f.setActor('123');release();assert.equal(await work,null);assert.equal(f.applied.length,applied)});
test('late response after proof ABA cannot apply the old snapshot',async()=>{let release;const held=new Promise(r=>release=r);const f=fixture({provider:async({p})=>{await held;return ack(p,{sets:[{set_no:1,reps:10}]})}});const work=f.subject.queueAddSet(5);await turn();const applied=f.applied.length;f.setProof('other-proof');f.setProof('proof');release();assert.equal(await work,null);assert.equal(f.applied.length,applied)});
test('context changed while refreshing capability cannot turn the old gesture into a new owner write',async()=>{let release;const held=new Promise(r=>release=r);const f=fixture({version:0,identityProvider:async state=>{await held;state.setAddOperationsVersion=1}});const work=f.subject.queueAddSet(5);f.setActor('another');f.setProof('B-proof');release();assert.equal(await work,null);assert.equal(f.requests.length,0);assert.equal(f.storage.size,0)});
