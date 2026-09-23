import { levelKey } from './i18n.js';

export const readinessLevels = [
  { key: 'draft', range: '0–39' },
  { key: 'working', range: '40–69' },
  { key: 'ready', range: '70–89' },
  { key: 'priority', range: '90–100' },
];

// Counts describe the whole published catalog, never an invented success metric.
export function readinessSummary(challenges = []) {
  const counts = { draft: 0, working: 0, ready: 0, priority: 0 };
  for (const challenge of challenges) counts[levelKey(challenge.score)] += 1;
  return readinessLevels.map(level => ({ ...level, count: counts[level.key] }));
}
