import test from 'node:test';
import assert from 'node:assert/strict';
import {
  analysisSuccessPatch,
  answersForAnalysis,
  draftHasEdits,
  fieldsDiffer,
  replaceDraftText,
} from '../src/editor-state.js';
import { levelKey, translator } from '../src/i18n.js';
import * as editorState from '../src/editor-state.js';

test('clarification and published-edit field limits match the server title boundary', () => {
  assert.equal(editorState.fieldMaxLength('title'),180);
  for (const field of ['context','need','users','data','constraints','expected_result','success_criteria','contact','interaction_format']) {
    assert.equal(editorState.fieldMaxLength(field),4000);
  }
});

test('legacy long titles are rejected before analysis without silently truncating user text', () => {
  const fields = {title:'Ә'.repeat(181),context:'This context remains untouched.'};
  const original = structuredClone(fields);
  assert.equal(editorState.titleTooLong(fields),true);
  assert.deepEqual(fields,original);
  assert.equal(editorState.titleTooLong({title:'Ә'.repeat(180)}),false);
  assert.equal(editorState.titleTooLong({title:`  ${'Ә'.repeat(180)}  `}),false);
  assert.equal(editorState.titleTooLong({}),false);
  assert.equal(editorState.titleTooLong(null),false);
});

test('local checks use explicit non-AI headings in all supported languages', () => {
  assert.equal(translator('ru')('offlineSummary'),'Локальная проверка');
  assert.equal(translator('en')('offlineSummary'),'Local check');
  assert.equal(translator('kk')('offlineSummary'),'Жергілікті тексеру');
});

function reviewedDraft() {
  const fields = { title: 'Библиотечный поиск', context: 'Студенты не находят учебники.', data: 'Каталог CSV', users: 'Студенты первого курса', contact: 'library@example.kz' };
  return {
    text: 'Студенты не находят учебники на казахском языке.',
    topic: 'Образование',
    seedId: 'd1',
    stage: 2,
    answers: { ...fields },
    fields: { ...fields },
    analysis: { analysis_id: 'analysis-1', fields: { ...fields }, score: 65 },
    initialScore: 8,
    published: null,
  };
}

test('editing any scored field invalidates the preview, including after browser reload', () => {
  const draft = reviewedDraft();
  assert.equal(draftHasEdits(draft), false);
  draft.fields.data = 'Данные пока недоступны.';
  assert.equal(draftHasEdits(draft), true);
  assert.equal(draftHasEdits(JSON.parse(JSON.stringify(draft))), true);
});

test('clearing an existing fact invalidates the old score', () => {
  const draft = reviewedDraft();
  draft.fields.contact = '';
  assert.equal(draftHasEdits(draft), true);
  assert.equal(fieldsDiffer({ contact: '' }, { contact: 'owner@example.kz' }), true);
});

test('comparison matches server whitespace normalization, not text-length heuristics', () => {
  assert.equal(fieldsDiffer({ data: '  CSV export\n' }, { data: 'CSV export' }), false);
  assert.equal(fieldsDiffer({ data: 'CSV export' }, { data: 'XLS export' }), true);
  assert.equal(fieldsDiffer({ data: '' }, {}), false);
  assert.equal(fieldsDiffer(null, undefined), false);
});

test('an explicit local retry after AI failure keeps edited and deliberately cleared facts', async () => {
  const draft = reviewedDraft();
  draft.fields.data = 'Новый CSV: 30 обезличенных записей, доступ через координатора.';
  draft.fields.contact = '';
  const stateBeforeRequest = structuredClone(draft);
  const aiPayload = answersForAnalysis(draft);
  await assert.rejects(Promise.reject(new Error('AI unavailable')), /AI unavailable/);
  const localPayload = answersForAnalysis(draft);
  assert.deepEqual(localPayload, aiPayload);
  assert.equal(localPayload.data, draft.fields.data);
  assert.equal(localPayload.contact, '');
  assert.notEqual(localPayload.contact, draft.answers.contact);
  assert.deepEqual(draft, stateBeforeRequest);
});

test('review payload is an independent object and preserves other supplied answers', () => {
  const draft = reviewedDraft();
  draft.answers.interaction_format = 'Встреча каждую пятницу.';
  const payload = answersForAnalysis(draft);
  assert.equal(payload.interaction_format, 'Встреча каждую пятницу.');
  payload.data = 'Changed only in request';
  assert.equal(draft.fields.data, 'Каталог CSV');
  assert.equal(draft.answers.data, 'Каталог CSV');
});

test('clarification submits the latest answers rather than stale generated fields', () => {
  const draft = reviewedDraft();
  draft.stage = 1;
  draft.answers.data = 'User answer just entered';
  assert.equal(answersForAnalysis(draft).data, 'User answer just entered');
});

test('changing the problem removes earlier facts, analysis, seed and published references', () => {
  const draft = reviewedDraft();
  draft.published = { id: 'old-challenge' };
  const next = replaceDraftText(draft, 'Нужен анализ задержек доставки.');
  assert.equal(next.text, 'Нужен анализ задержек доставки.');
  assert.equal(next.stage, 0);
  assert.equal(next.seedId, '');
  assert.equal(next.analysis, null);
  assert.equal(next.initialScore, null);
  assert.equal(next.published, null);
  assert.deepEqual(next.fields, {});
  assert.deepEqual(next.answers, {});
  assert.equal(next.topic, draft.topic);
  assert.equal(draft.analysis.analysis_id, 'analysis-1');
  assert.equal(draft.fields.data, 'Каталог CSV');
});

test('an unchanged source does not discard answers or scores', () => {
  const draft = reviewedDraft();
  assert.equal(replaceDraftText(draft, draft.text), draft);
});

test('successful analysis preserves zero baseline and makes a separate editable field copy', () => {
  const draft = reviewedDraft();
  draft.initialScore = 0;
  const result = { analysis_id: 'analysis-2', score: 75, fields: { data: 'CSV export' } };
  const patch = analysisSuccessPatch(draft, result, { data: 'CSV export' }, 2);
  assert.equal(patch.initialScore, 0);
  assert.equal(patch.stage, 2);
  assert.equal(draftHasEdits({ ...draft, ...patch }), false);
  patch.fields.data = '';
  assert.equal(result.fields.data, 'CSV export');
  assert.equal(draftHasEdits({ ...draft, ...patch }), true);
});

test('a new source starts a new score baseline', () => {
  const next = replaceDraftText(reviewedDraft(), 'Новый проект: запись на консультации.');
  const patch = analysisSuccessPatch(next, { score: 12, fields: {} }, {}, 1);
  assert.equal(patch.initialScore, 12);
});

test('readiness boundaries match the case rubric exactly', () => {
  for (const [score, expected] of [[0,'draft'],[39,'draft'],[40,'working'],[69,'working'],[70,'ready'],[89,'ready'],[90,'priority'],[100,'priority']]) {
    assert.equal(levelKey(score), expected, `score ${score}`);
  }
});

test('visible counts use Russian plural rules, including the teen exception', () => {
  const t = translator('ru');
  for (const [count, expected] of [[0,'откликов'],[1,'отклик'],[2,'отклика'],[5,'откликов'],[11,'откликов'],[21,'отклик'],[22,'отклика'],[111,'откликов']]) {
    assert.equal(t('proposals',count),expected);
  }
  assert.equal(t('taskCount',1),'задача');
  assert.equal(t('taskCount',3),'задачи');
  assert.equal(t('taskCount',12),'задач');
});

test('English and Kazakh count labels retain their language and existing labels still work', () => {
  assert.equal(translator('en')('proposals',1),'proposal');
  assert.equal(translator('en')('proposals',2),'proposals');
  assert.equal(translator('kk')('proposals',1),'ұсыныс');
  assert.equal(translator('kk')('proposals',5),'ұсыныс');
  assert.equal(translator('ru')('catalog'),'Каталог задач');
});

function emptyEditorDraft() {
  return {text:'',topic:'',seedId:'',answers:{},fields:{},stage:0,analysis:null,initialScore:null,published:null};
}

test('opening Create task without saved work starts at an empty description, not a result', () => {
  assert.deepEqual(editorState.restoreDraft(),emptyEditorDraft());
  assert.deepEqual(editorState.restoreDraft({}),emptyEditorDraft());
});

test('a completed publication is not restored as the new-task editor, regardless of stale stage', () => {
  for (const stage of [0,1,2,3]) {
    const saved = {...reviewedDraft(),stage,published:{id:'published-task',title:'Already published',score:93}};
    const original = structuredClone(saved);
    const restored = editorState.restoreDraft(saved);
    assert.deepEqual(restored,emptyEditorDraft(),`published result with saved stage ${stage}`);
    assert.deepEqual(saved,original,'restoring must not alter saved data');
  }
});

test('completed stage 3 resets even when the saved publication payload is missing', () => {
  const saved = {...reviewedDraft(),stage:3,published:null};
  const original = structuredClone(saved);
  assert.deepEqual(editorState.restoreDraft(saved),emptyEditorDraft());
  assert.deepEqual(saved,original);
});

for (const stage of [0,1,2]) {
  test(`unfinished stage ${stage} restores text, answers, edited fields and analysis without mutation`, () => {
    const saved = {...reviewedDraft(),stage,initialScore:0,published:null};
    saved.fields.contact = '';
    saved.answers.data = 'Последний введённый ответ';
    const original = structuredClone(saved);
    Object.freeze(saved.fields);
    Object.freeze(saved.answers);
    Object.freeze(saved.analysis.fields);
    Object.freeze(saved.analysis);
    Object.freeze(saved);
    const restored = editorState.restoreDraft(saved);
    assert.deepEqual(restored,original);
    assert.equal(restored.fields.contact,'','a deliberate clearing must survive reopening');
    assert.equal(restored.answers.data,'Последний введённый ответ');
    assert.equal(restored.analysis.analysis_id,'analysis-1');
    assert.equal(restored.initialScore,0);
    assert.deepEqual(saved,original);
  });
}

test('null, JSON primitives and arrays restore safely to a blank editor', () => {
  for (const invalid of [null,true,false,0,42,'','published',[],['previous result']]) {
    assert.deepEqual(editorState.restoreDraft(invalid),emptyEditorDraft(),`invalid top-level value: ${JSON.stringify(invalid)}`);
  }
});

test('blank resets own fresh field and answer objects rather than sharing mutable defaults', () => {
  const first = editorState.restoreDraft({...reviewedDraft(),published:{id:'done'}});
  const second = editorState.restoreDraft({stage:3});
  const third = editorState.restoreDraft(null);
  assert.notEqual(first,second);
  assert.notEqual(first.fields,second.fields);
  assert.notEqual(first.answers,second.answers);
  assert.notEqual(first.fields,first.answers);
  first.fields.title = 'This edit belongs only to the first reopened editor';
  first.answers.data = 'Local response';
  assert.deepEqual(second,emptyEditorDraft());
  assert.deepEqual(third,emptyEditorDraft());
});
