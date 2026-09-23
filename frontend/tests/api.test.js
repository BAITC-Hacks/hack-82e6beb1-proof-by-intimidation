import test from 'node:test';
import assert from 'node:assert/strict';
import { api, safeLink } from '../src/api.js';

function locale(t, language) {
  const previous = Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:() => language}});
  t.after(() => {if(previous) Object.defineProperty(globalThis,'localStorage',previous); else delete globalThis.localStorage;});
}

test('API sends one JSON request with browser ownership cookie and chosen locale', async t => {
  locale(t,'kk');
  const fetch = t.mock.method(globalThis,'fetch',async (url,options) => {
    assert.equal(url,'/api/challenges');
    assert.equal(options.credentials,'include');
    assert.equal(options.headers['Accept-Language'],'kk');
    assert.equal(options.headers['Content-Type'],'application/json');
    assert.deepEqual(JSON.parse(options.body),{confirmed:true});
    assert.equal(options.signal.aborted,false);
    return new Response(JSON.stringify({id:'task-1'}),{status:201});
  });
  assert.deepEqual(await api('/challenges',{method:'POST',body:{confirmed:true}}),{id:'task-1'});
  assert.equal(fetch.mock.callCount(),1);
});

for (const [language,phrase] of [['ru','Не удалось связаться'],['en','Could not reach'],['kk','Сервермен байланысу']]) {
  test(`network errors have a useful ${language} message and do not retry writes`,async t => {
    locale(t,language);
    const fetch = t.mock.method(globalThis,'fetch',async () => {throw new TypeError('Failed to fetch');});
    await assert.rejects(api('/challenges',{method:'POST',body:{}}),error => {
      assert.equal(error.code,'network');
      assert.ok(error.message.startsWith(phrase));
      assert.ok(error.message.length > phrase.length + 30);
      assert.equal(error.message.includes('Failed to fetch'),false);
      return true;
    });
    assert.equal(fetch.mock.callCount(),1);
  });
}

test('timeout aborts the request and warns about uncertain write results without retrying',async t => {
  locale(t,'en');
  const fetch = t.mock.method(globalThis,'fetch',(_url,{signal}) => new Promise((_resolve,reject) => {
    signal.addEventListener('abort',() => reject(new DOMException('Aborted','AbortError')),{once:true});
  }));
  await assert.rejects(api('/challenges',{method:'POST',body:{},timeoutMs:5}),error => {
    assert.equal(error.code,'timeout');
    assert.match(error.message,/timed out/);
    assert.match(error.message,/whether your changes were saved/);
    return true;
  });
  assert.equal(fetch.mock.callCount(),1);
  assert.equal(fetch.mock.calls[0].arguments[1].signal.aborted,true);
});

test('HTTP validation errors retain server detail and status',async t => {
  locale(t,'ru');
  t.mock.method(globalThis,'fetch',async () => new Response(JSON.stringify({detail:[{loc:['body','link'],msg:'Use an https link'}]}),{status:422}));
  await assert.rejects(api('/proposals',{method:'POST',body:{}}),error => {
    assert.equal(error.status,422);
    assert.equal(error.message,'link: Use an https link');
    assert.equal(error.detail[0].loc[1],'link');
    return true;
  });
});

test('successful non-JSON response fails clearly instead of producing incomplete app state',async t => {
  locale(t,'en');
  t.mock.method(globalThis,'fetch',async () => new Response('<html>proxy error</html>',{status:200}));
  await assert.rejects(api('/bootstrap'),error => error.code === 'invalid' && /invalid response/.test(error.message));
});

test('only external http and https links can become prototype anchors',() => {
  assert.equal(safeLink('javascript:alert(1)'),null);
  assert.equal(safeLink('data:text/html,test'),null);
  assert.equal(safeLink('/relative/prototype'),null);
  assert.equal(safeLink('https://example.com/prototype'),'https://example.com/prototype');
});
