import test from 'node:test';
import assert from 'node:assert/strict';
import { clearSaved, readSaved, saveLocal } from '../src/persistence.js';

function browserStorage(t, broken=false) {
  const values=new Map();
  const previous=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{
    getItem:key => values.get(key) || null,
    setItem:(key,value) => {if(broken) throw new Error('Quota exceeded');values.set(key,value);},
    removeItem:key => values.delete(key),
  }});
  t.after(() => {if(previous) Object.defineProperty(globalThis,'localStorage',previous);else delete globalThis.localStorage;});
  return values;
}

test('unfinished proposal input is saved synchronously and isolated per challenge',t => {
  browserStorage(t);
  const first={team_name:'Research group',idea:'Test with 20 students',plan:'First interview the librarian',link:''};
  const second={team_name:'Another team',idea:'A different solution'};
  assert.equal(saveLocal('proposal-a',first),true);
  saveLocal('proposal-b',second);
  assert.deepEqual(readSaved('proposal-a',{}),first);
  assert.deepEqual(readSaved('proposal-b',{}),second);
  clearSaved('proposal-a');
  assert.deepEqual(readSaved('proposal-a',{}),{});
  assert.deepEqual(readSaved('proposal-b',{}),second);
});

test('published edits retain deliberately empty fields, review and original version',t => {
  browserStorage(t);
  const edit={editing:true,fields:{contact:'',data:'Replacement CSV'},analysis:{analysis_id:'review-2'},baseVersion:3};
  saveLocal('published-edit',edit);
  assert.deepEqual(readSaved('published-edit',{}),edit);
  assert.equal(readSaved('published-edit',{}).baseVersion,3);
});

test('blocked storage is reported but in-app navigation retains current work in memory',t => {
  browserStorage(t,true);
  assert.equal(saveLocal('blocked-proposal',{idea:'Keep this idea'}),false);
  assert.deepEqual(readSaved('blocked-proposal',{}),{idea:'Keep this idea'});
  clearSaved('blocked-proposal');
  assert.deepEqual(readSaved('blocked-proposal',{}),{});
});

test('a failed save cannot restore older persisted text over the latest in-memory edits',t => {
  const values=browserStorage(t,true);
  values.set('old-saved-draft',JSON.stringify({fields:{contact:'old@example.kz',data:'Old CSV'}}));
  const latest={fields:{contact:'',data:'Newest CSV'}};
  assert.equal(saveLocal('old-saved-draft',latest),false);
  assert.deepEqual(readSaved('old-saved-draft',{}),latest);
  assert.equal(readSaved('old-saved-draft',{}).fields.contact,'');
});

test('corrupt JSON and non-object form data cannot crash the form',t => {
  const values=browserStorage(t);
  for(const invalid of ['not-json','null','[]','42','true']) {
    values.set('invalid-form',invalid);
    assert.deepEqual(readSaved('invalid-form',() => ({idea:''})),{idea:''});
  }
});
