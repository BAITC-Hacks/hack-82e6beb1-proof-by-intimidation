import { fieldsOrder } from './i18n.js';

export const fieldMaxLength = field => field === 'title' ? 180 : 4000;
export const titleTooLong = fields => String(fields?.title ?? '').trim().length > fieldMaxLength('title');

// Publication completes the draft. Keep the success screen in the current
// editor only; reopening the constructor must start a new draft. This also
// handles completed drafts saved by earlier versions without losing work in
// unfinished drafts.
export function restoreDraft(saved) {
  const blank = { text: '', topic: '', seedId: '', answers: {}, fields: {}, stage: 0, analysis: null, initialScore: null, published: null };
  if (!saved || typeof saved !== 'object' || Array.isArray(saved) || saved.published || saved.stage === 3) {
    return blank;
  }
  return { ...blank, ...saved };
}

// The server trims fields before comparing them to its stored analysis.
export function fieldsDiffer(first = {}, second = {}) {
  return fieldsOrder.some(key => String(first?.[key] ?? '').trim() !== String(second?.[key] ?? '').trim());
}

export function draftHasEdits(draft) {
  return Boolean(draft.analysis && fieldsDiffer(draft.fields, draft.analysis.fields));
}

// Review edits are authoritative, including a deliberate empty string. The same
// payload is used for a real AI attempt and an explicitly chosen local retry.
export function answersForAnalysis(draft) {
  return draft.stage === 2
    ? { ...draft.answers, ...draft.fields }
    : { ...draft.answers };
}

export function replaceDraftText(draft, text) {
  if (text === draft.text) return draft;
  return {
    ...draft,
    text,
    stage: 0,
    seedId: '',
    answers: {},
    fields: {},
    analysis: null,
    initialScore: null,
    published: null,
  };
}

export function analysisSuccessPatch(draft, result, answers, stage) {
  return {
    analysis: result,
    fields: { ...result.fields },
    answers: { ...answers },
    stage,
    initialScore: draft.initialScore ?? result.score,
  };
}

export function draftSnapshot(draft) {
  return JSON.stringify({ text:draft.text, answers:draft.answers, fields:draft.fields, stage:draft.stage });
}

export function completedDraftPatch(draft, job) {
  if (job?.status !== 'succeeded' || !job.analysis || job.meta?.snapshot !== draftSnapshot(draft)) return null;
  return analysisSuccessPatch(draft, job.analysis, job.meta.answers, job.meta.stage);
}
