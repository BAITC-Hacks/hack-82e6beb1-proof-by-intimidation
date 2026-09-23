import { api } from './api.js';

const STORAGE_KEY = 'sana-analysis-jobs-v1';
const activeStatuses = new Set(['submitting', 'queued', 'running']);
export const jobIsPending = job => Boolean(job && activeStatuses.has(job.status));
export const analysisBusyKey = job => job?.payload?.offline ? 'checkingLocally' : 'analyzing';
export const inputSnapshot = value => JSON.stringify(value);

// This controller deliberately outlives routed React components. A request UUID
// is saved before POST; a lost acknowledgement retries the SAME server job.
export function createAnalysisJobs({ request = api, storage, uuid = () => crypto.randomUUID(), schedule = setTimeout, cancel = clearTimeout, interval = 1500 } = {}) {
  let records = {};
  try {
    const saved = JSON.parse(storage?.getItem(STORAGE_KEY) || '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      records = Object.fromEntries(Object.entries(saved).filter(([, job]) => job?.request_id && job?.payload && ['submitting','queued','running','succeeded','failed'].includes(job.status)));
    }
  } catch { /* An invalid saved job must not prevent the app from starting. */ }
  const listeners = new Set();
  const running = new Set();
  const timers = new Map();
  let disposed = false;
  const persist = () => {
    try {
      if (!storage) throw new Error('Browser storage is unavailable');
      storage.setItem(STORAGE_KEY, JSON.stringify(records));
    } catch {
      records = Object.fromEntries(Object.entries(records).map(([channel, job]) => [channel, { ...job, storageFailed:true }]));
    }
    listeners.forEach(listener => listener());
  };
  const update = (channel, requestId, patch) => {
    if (disposed || records[channel]?.request_id !== requestId) return false;
    records = { ...records, [channel]: { ...records[channel], ...patch } };
    persist();
    return true;
  };
  async function step(channel) {
    const job = records[channel];
    if (disposed || !jobIsPending(job) || running.has(job.request_id)) return;
    running.add(job.request_id);
    try {
      const result = job.job_id
        ? await request(`/analysis-jobs/${encodeURIComponent(job.job_id)}`, { timeoutMs: 15000 })
        : await request('/analysis-jobs', { method: 'POST', body: { ...job.payload, request_id: job.request_id }, timeoutMs: 15000 });
      if (!result?.job_id || !['queued','running','succeeded','failed'].includes(result.status) || (result.status === 'succeeded' && !result.analysis)) {
        const error = new Error('Invalid analysis job response'); error.code = 'invalid'; throw error;
      }
      const error = typeof result.error === 'object' ? result.error?.detail || result.error?.message || result.error?.code : result.error;
      update(channel, job.request_id, { ...result, error, connectionError: '', recovered: job.recovered || Boolean(job.connectionError) });
    } catch (error) {
      // Auth/input/rate-limit failures are terminal and need an explicit action.
      // Network/5xx errors are uncertain: retain the UUID and query/repost safely.
      if (error.status && error.status < 500) update(channel, job.request_id, { status: 'failed', error: error.message, connectionError: '' });
      else update(channel, job.request_id, { connectionError: error.message });
    } finally {
      running.delete(job.request_id);
      if (!disposed && jobIsPending(records[channel]) && records[channel]?.request_id === job.request_id) {
        timers.set(channel, schedule(() => { timers.delete(channel); void step(channel); }, records[channel].connectionError ? Math.max(interval, 5000) : interval));
      }
    }
  }
  return {
    get: channel => records[channel] || null,
    all: () => records,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    start(channel, payload, meta = {}) {
      if (jobIsPending(records[channel])) return records[channel];
      const record = { request_id: uuid(), status: 'submitting', payload: structuredClone(payload), meta: structuredClone(meta), started_at: Date.now(), recovered: false };
      records = { ...records, [channel]: record };
      persist();
      void step(channel);
      return record;
    },
    resume() {
      for (const [channel, job] of Object.entries(records)) {
        if (!jobIsPending(job)) continue;
        update(channel, job.request_id, { recovered: true });
        void step(channel);
      }
    },
    clear(channel) {
      cancel(timers.get(channel)); timers.delete(channel);
      const next = { ...records }; delete next[channel]; records = next; persist();
    },
    dispose() { disposed = true; timers.forEach(cancel); timers.clear(); listeners.clear(); },
  };
}

let browserStorage;
try { browserStorage = globalThis.localStorage; } catch { /* Private browser mode. */ }
export const analysisJobs = createAnalysisJobs({ storage: browserStorage });
