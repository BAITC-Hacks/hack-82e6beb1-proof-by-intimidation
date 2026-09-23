import test from 'node:test';
import assert from 'node:assert/strict';
import { analysisBusyKey, createAnalysisJobs, jobIsPending } from '../src/analysis-jobs.js';
import { answersForAnalysis, completedDraftPatch, draftSnapshot, restoreDraft } from '../src/editor-state.js';

const flush = () => new Promise(resolve => setImmediate(resolve));
function storage() {
  const values = new Map();
  return { getItem:key => values.get(key) || null, setItem:(key,value) => values.set(key,value) };
}
function harness(t, replies, saved = storage()) {
  const calls = [];
  const timers = new Map();
  let id = 0;
  let requestId = 0;
  const manager = createAnalysisJobs({
    storage:saved, uuid:() => `request-${++requestId}`, interval:1,
    schedule:callback => { timers.set(++id,callback); return id; }, cancel:timer => timers.delete(timer),
    request:async (path,options) => {
      calls.push({path,options});
      const next = replies.shift();
      if (next instanceof Error) throw next;
      return typeof next === 'function' ? next(path,options) : next;
    },
  });
  t.after(() => manager.dispose());
  return {manager,calls,timers,saved,async tick() { const next=timers.entries().next().value; assert.ok(next,'a recovery poll is scheduled'); timers.delete(next[0]); next[1](); await flush(); }};
}
const payload = {draft:'Students cannot find textbooks.', answers:{data:'CSV export',contact:''}, language:'en', offline:false};
const analysis = {analysis_id:'analysis-1',score:40,fields:{data:'CSV export',contact:''},questions:[]};
const done = {job_id:'job-1',status:'succeeded',analysis};

test('a delayed review survives component unsubscribe and completes without a second POST',async t => {
  const h=harness(t,[{job_id:'job-1',status:'queued'},{job_id:'job-1',status:'running'},done]);
  let updates=0;
  const unsubscribe=h.manager.subscribe(() => updates++);
  h.manager.start('editor',payload,{stage:1});
  await flush(); unsubscribe();
  await h.tick(); await h.tick();
  assert.ok(updates>=2);
  assert.equal(h.manager.get('editor').status,'succeeded');
  assert.deepEqual(h.manager.get('editor').analysis,analysis);
  assert.equal(h.calls.filter(call => call.options.method==='POST').length,1);
  assert.equal(h.timers.size,0);
});

test('reload resumes a persisted job by ID and never charges another AI request',async t => {
  const saved=storage();
  const first=harness(t,[{job_id:'job-1',status:'running'}],saved);
  first.manager.start('editor',payload,{stage:2}); await flush(); first.manager.dispose();
  const next=harness(t,[done],saved);
  next.manager.resume(); await flush();
  assert.equal(next.calls[0].path,'/analysis-jobs/job-1');
  assert.equal(next.calls[0].options.method,undefined);
  assert.equal(next.manager.get('editor').recovered,true);
  assert.deepEqual(next.manager.get('editor').analysis,analysis);
});

test('lost POST acknowledgement retries the saved UUID, not a new paid request',async t => {
  const timeout=Object.assign(new Error('Timed out'),{code:'timeout'});
  const h=harness(t,[timeout,done]);
  h.manager.start('editor',payload); await flush();
  assert.equal(h.manager.get('editor').connectionError,'Timed out');
  await h.tick();
  assert.equal(h.calls.length,2);
  assert.equal(h.calls[0].options.body.request_id,h.calls[1].options.body.request_id);
  assert.equal(h.manager.get('editor').status,'succeeded');
});

test('reload after uncertain creation reuses the persisted UUID and payload',async t => {
  const saved=storage();
  const first=harness(t,[new TypeError('Connection lost')],saved);
  first.manager.start('editor',payload); await flush(); first.manager.dispose();
  const next=harness(t,[done],saved);
  next.manager.resume(); await flush();
  assert.deepEqual(next.calls[0].options.body,first.calls[0].options.body);
});

test('provider failure is terminal; local analysis requires an explicit new request',async t => {
  const h=harness(t,[{job_id:'job-1',status:'failed',error:{code:'provider_unavailable',detail:'AI unavailable'}}, {...done,job_id:'job-2',analysis:{...analysis,mode:'offline'}}]);
  h.manager.start('editor',payload); await flush();
  assert.equal(h.manager.get('editor').error,'AI unavailable');
  assert.equal(h.timers.size,0);
  assert.equal(h.calls.length,1);
  h.manager.resume(); await flush();
  assert.equal(h.calls.length,1,'terminal failures must not restart automatically');
  h.manager.start('editor',{...payload,offline:true}); await flush();
  assert.equal(h.calls[1].options.body.offline,true);
  assert.notEqual(h.calls[0].options.body.request_id,h.calls[1].options.body.request_id);
  assert.equal(h.manager.get('editor').analysis.mode,'offline');
});

test('double-clicking analyze cannot start duplicate jobs',async t => {
  let resolve;
  const h=harness(t,[() => new Promise(done => { resolve=done; })]);
  const first=h.manager.start('editor',payload);
  const second=h.manager.start('editor',{...payload,draft:'Different source'});
  assert.equal(second.request_id,first.request_id);
  assert.equal(h.calls.length,1);
  resolve(done); await flush();
});

test('ownership and input failures are visible and do not poll forever',async t => {
  for (const status of [403,404,409,422,429]) {
    const h=harness(t,[Object.assign(new Error(`Failure ${status}`),{status})]);
    h.manager.start('editor',payload); await flush();
    assert.equal(h.manager.get('editor').status,'failed');
    assert.equal(h.timers.size,0);
    assert.equal(h.manager.get('editor').error,`Failure ${status}`);
  }
});

test('server restart failure remains recoverable through an explicit retry',async t => {
  const h=harness(t,[{job_id:'job-1',status:'failed',error:{code:'server_restarted',detail:'Server restarted. Retry analysis.'}},done]);
  h.manager.start('editor',payload); await flush();
  assert.match(h.manager.get('editor').error,/Server restarted/);
  h.manager.start('editor',payload); await flush();
  assert.equal(h.calls.length,2);
  assert.notEqual(h.calls[0].options.body.request_id,h.calls[1].options.body.request_id);
});

test('inputs, cleared values and completion metadata are copied before async work',async t => {
  const input=structuredClone(payload);
  const meta={stage:2,answers:{data:'Edited CSV',contact:''}};
  const h=harness(t,[done]);
  h.manager.start('editor',input,meta);
  input.answers.contact='do not restore'; meta.answers.data='changed elsewhere';
  await flush();
  assert.equal(h.manager.get('editor').payload.answers.contact,'');
  assert.equal(h.manager.get('editor').meta.answers.data,'Edited CSV');
});

test('failed local storage is reported while navigation still retains the job in memory',async t => {
  const saved={getItem:() => null,setItem:() => {throw new Error('Quota exceeded');}};
  const h=harness(t,[done],saved);
  h.manager.start('editor',payload); await flush();
  assert.equal(h.manager.get('editor').storageFailed,true);
  assert.equal(h.manager.get('editor').status,'succeeded');
});

test('completed job restores exactly the matching unfinished draft after reload',() => {
  const draft={...restoreDraft(),text:payload.draft,stage:2,answers:{contact:'old@example.kz'},fields:{data:'Edited CSV',contact:''},initialScore:0};
  const answers=answersForAnalysis(draft);
  const job={...done,meta:{snapshot:draftSnapshot(draft),answers,stage:2}};
  const reloaded=JSON.parse(JSON.stringify(draft));
  const patch=completedDraftPatch(reloaded,job);
  assert.equal(patch.answers.contact,'');
  assert.equal(patch.answers.data,'Edited CSV');
  assert.equal(patch.initialScore,0);
  assert.equal(patch.stage,2);
  assert.equal(patch.analysis.analysis_id,'analysis-1');
  assert.equal(draft.answers.contact,'old@example.kz','application cannot mutate saved source');
});

test('an old completion never overwrites a changed source, answer, cleared field or stage',() => {
  const draft={...restoreDraft(),text:payload.draft,stage:2,answers:{data:'CSV'},fields:{contact:'owner@example.kz'}};
  const job={...done,meta:{snapshot:draftSnapshot(draft),answers:draft.answers,stage:2}};
  for(const updated of [{...draft,text:'A different business problem'}, {...draft,answers:{data:'New CSV'}}, {...draft,fields:{contact:''}}, {...draft,stage:0}]) {
    assert.equal(completedDraftPatch(updated,job),null);
  }
});

test('completed publication is never recovered as a new-task draft',() => {
  const draft={...restoreDraft(),text:payload.draft};
  const job={...done,meta:{snapshot:draftSnapshot(draft),answers:{},stage:1}};
  assert.equal(completedDraftPatch(restoreDraft({...draft,published:{id:'already-published'}}),job),null);
});

test('pending state is limited to actual queued work, not errors or completed results',() => {
  for(const status of ['submitting','queued','running']) assert.equal(jobIsPending({status}),true);
  for(const status of ['failed','succeeded',undefined]) assert.equal(jobIsPending({status}),false);
  assert.equal(jobIsPending(null),false);
});

test('pending local analysis never uses the AI loading label, including after reload',() => {
  const job = {status:'running',payload:{...payload,offline:true}};
  assert.equal(analysisBusyKey(job),'checkingLocally');
  assert.equal(analysisBusyKey(JSON.parse(JSON.stringify(job))),'checkingLocally');
  assert.equal(analysisBusyKey({payload}),'analyzing');
  assert.equal(analysisBusyKey(null),'analyzing');
});
