import test from 'node:test';
import assert from 'node:assert/strict';
import { readinessSummary } from '../src/catalog-summary.js';
import { translator } from '../src/i18n.js';

test('readiness overview counts every boundary with the same catalog levels', () => {
  const challenges = [0, 39, 40, 69, 70, 89, 90, 100].map(score => ({ score }));
  const original = structuredClone(challenges);
  assert.deepEqual(readinessSummary(challenges).map(level => level.count), [2, 2, 2, 2]);
  assert.deepEqual(challenges, original);
});

test('empty catalog remains empty without fabricated readiness metrics', () => {
  assert.deepEqual(readinessSummary().map(level => level.count), [0, 0, 0, 0]);
});

test('low-readiness and sample tasks are counted rather than hidden', () => {
  const summary = readinessSummary([{ score: 0 }, { score: 23, source: 'sample' }, { score: 87 }]);
  assert.equal(summary[0].count, 2);
  assert.equal(summary.reduce((total, level) => total + level.count, 0), 3);
});

test('readiness overview has native copy in all interface languages', () => {
  const headings = ['ru', 'kk', 'en'].map(language => translator(language)('readinessMap'));
  assert.equal(new Set(headings).size, 3);
  for (const language of ['ru', 'kk', 'en']) {
    assert.notEqual(translator(language)('readinessMapHint'), 'readinessMapHint');
  }
});
