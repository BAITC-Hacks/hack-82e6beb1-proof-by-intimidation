import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { api, safeLink } from './api.js';
import { criterionLabels, fieldLabels, fieldsOrder, levelKey, translator } from './i18n.js';
import { answersForAnalysis, completedDraftPatch, draftHasEdits, draftSnapshot, fieldMaxLength, fieldsDiffer, replaceDraftText, restoreDraft, titleTooLong } from './editor-state.js';
import { analysisBusyKey, analysisJobs, inputSnapshot, jobIsPending } from './analysis-jobs.js';
import { clearSaved, readSaved, saveLocal, storageIsUnsaved } from './persistence.js';
import { readinessSummary } from './catalog-summary.js';

function useSavedForm(key, fallback, normalize = value => value) {
  const [value, update] = useState(() => normalize(readSaved(key, fallback)));
  const latest = useRef(value);
  const [storageFailed, setStorageFailed] = useState(() => storageIsUnsaved(key));
  const setValue = next => {
    const result = typeof next === 'function' ? next(latest.current) : next;
    latest.current = result;
    setStorageFailed(!saveLocal(key, normalize(result)));
    update(result);
  };
  return [value, setValue, storageFailed];
}
function useJob(channel) {
  return useSyncExternalStore(analysisJobs.subscribe, () => analysisJobs.get(channel));
}
function useLeaveWarning(active, message) {
  useEffect(() => {
    if (!active) return;
    const beforeUnload = event => { event.preventDefault(); event.returnValue = ''; };
    const navigate = event => { if (!window.confirm(message)) event.preventDefault(); };
    window.addEventListener('beforeunload', beforeUnload);
    window.addEventListener('sana-before-navigate', navigate);
    return () => { window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('sana-before-navigate', navigate); };
  }, [active, message]);
}
const allowNavigation = () => window.dispatchEvent(new Event('sana-before-navigate', { cancelable: true }));

function JobNotice({ job, t }) {
  useLeaveWarning(Boolean(job?.storageFailed), t('storageWarning'));
  if (!jobIsPending(job)) return job?.storageFailed ? <div className="notice error" role="alert"><Icon name="alert" size={18}/><p>{t('storageWarning')}</p></div> : null;
  return <div className={`notice ${job.connectionError ? 'warning' : 'info'} compact job-notice`} role="status"><Icon name={job.connectionError ? 'refresh' : 'clock'} size={18}/><div><strong>{t(job.connectionError ? 'jobReconnecting' : job.recovered ? 'jobRecovered' : 'jobRunning')}</strong><p>{t(job.storageFailed ? 'storageWarning' : 'jobNavigationSafe')}</p>{job.connectionError && <small>{job.connectionError}</small>}</div></div>;
}

const icons = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  brief: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></>,
  work: <><rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a25 25 0 0 0 18 0M12 11v4"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6"/>,
  back: <path d="M19 12H5m6-6-6 6 6 6"/>,
  chevron: <path d="m9 5 7 7-7 7"/>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  sparkle: <><path d="m12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8Z"/><path d="M20 2v4M18 4h4"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  checkCircle: <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
  users: <><circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M18 15a5 5 0 0 1 3 5"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  external: <><path d="M14 3h7v7M21 3l-9 9"/><path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/></>,
  message: <path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
  alert: <><path d="m10.3 3.9-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3.1l-8-14a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/></>,
  close: <path d="m6 6 12 12M6 18 18 6"/>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 6.1A8 8 0 0 1 19.4 9M4.6 15a8 8 0 0 0 13.3 2.9"/></>,
  edit: <><path d="m16 3 5 5-12 12-6 1 1-6ZM14 5l5 5"/></>,
  shield: <><path d="M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7Z"/><path d="m8 12 3 3 5-6"/></>,
  bookmark: <path d="M6 3h12v18l-6-4-6 4Z"/>,
  award: <><circle cx="12" cy="8" r="5"/><path d="m8.5 12-2 9 5.5-3 5.5 3-2-9"/></>,
  chart: <><path d="M4 3v18h17M8 15v2M13 10v7M18 5v12"/></>,
};

function Icon({ name, size = 20, className = '' }) {
  return <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{icons[name] || icons.brief}</svg>;
}
function Mark({ size = 32 }) {
  return <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true"><rect width="40" height="40" rx="11" fill="currentColor"/><g fill="white"><rect x="17.4" y="8" width="5.2" height="24" rx="2.6"/><rect x="8" y="17.4" width="24" height="5.2" rx="2.6"/><rect x="17.4" y="8" width="5.2" height="24" rx="2.6" transform="rotate(45 20 20)"/><rect x="17.4" y="8" width="5.2" height="24" rx="2.6" transform="rotate(-45 20 20)"/></g></svg>;
}
function readRoute() {
  const params = new URLSearchParams(window.location.search);
  return { view: params.get('view') || 'catalog', id: params.get('id') || '', q: params.get('q') || '', topic: params.get('topic') || '', level: params.get('level') || '' };
}
function routeUrl(view, values = {}) {
  const params = new URLSearchParams({ view, ...Object.fromEntries(Object.entries(values).filter(([, value]) => value !== '' && value != null)) });
  return `?${params}`;
}
function useRoute() {
  const [route, setRoute] = useState(readRoute);
  const lastUrl = useRef(window.location.href);
  useEffect(() => { const onPop = () => { if (allowNavigation()) { lastUrl.current = window.location.href; setRoute(readRoute()); } else window.history.pushState({}, '', lastUrl.current); }; window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop); }, []);
  const navigate = useCallback((view, values = {}, replace = false) => {
    if (!replace && !allowNavigation()) return;
    window.history[replace ? 'replaceState' : 'pushState']({}, '', routeUrl(view, values));
    lastUrl.current = window.location.href;
    setRoute(readRoute());
    if (!replace) window.scrollTo({ top: 0, behavior: 'instant' });
  }, []);
  return [route, navigate];
}
function NavLink({ view, values, navigate, children, className = '', ...props }) {
  return <a href={routeUrl(view, values)} className={className} onClick={event => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate(view, values); } }} {...props}>{children}</a>;
}
function Badge({ score, t, compact = false }) {
  const level = levelKey(score);
  return <span className={`badge ${level}`}><span className="status-dot" />{compact ? `${score}/100` : t(level)}</span>;
}
function EmptyState({ icon = 'brief', title, children, action }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={28} /></span><h2>{title}</h2><p>{children}</p>{action}</div>;
}
function ErrorBox({ title, error, children }) {
  if (!error) return null;
  return <div className="notice error" role="alert"><Icon name="alert"/><div><strong>{title}</strong><p>{String(error)}</p>{children}</div></div>;
}
function BusyButton({ busy, busyText, children, ...props }) {
  return <button {...props} disabled={busy || props.disabled}>{busy ? <><span className="spinner" aria-hidden="true"/>{busyText}</> : children}</button>;
}
function Field({ label, name, children, hint, required = false, className = '' }) {
  return <div className={`field ${className}`}><label htmlFor={name}>{label}{required && <span className="required-mark" aria-hidden="true"> *</span>}</label>{hint && <p className="field-hint" id={`${name}-hint`}>{hint}</p>}{children}</div>;
}
function textValue(value) {
  if (value == null) return '';
  if (Array.isArray(value)) return value.map(textValue).filter(Boolean).join('\n');
  if (typeof value === 'object') return value.quote || value.text || value.value || Object.values(value).map(textValue).join('\n');
  return String(value);
}
function criteriaList(criteria) {
  return Array.isArray(criteria) ? criteria : Object.entries(criteria || {}).map(([key, value]) => ({ key, ...value }));
}
function provenance(task, t) {
  return t(task.is_owner ? 'ownTask' : task.source === 'sample' ? 'seed' : 'sharedTask');
}

function RatingPanel({ analysis, initialScore, t, language, preview = false, compact = false }) {
  const score = Number(analysis?.score ?? 0);
  const list = criteriaList(analysis?.criteria);
  const level = levelKey(score);
  const gaps = [...list].filter(item => Number(item.points ?? item.score ?? 0) < Number(item.weight || item.max_points || 0) && item.next_step).sort((a,b) => (Number(b.weight || 0)-Number(b.points || 0))-(Number(a.weight || 0)-Number(a.points || 0))).slice(0,2);
  const supported = list.filter(item => Number(item.points ?? item.score ?? 0) > 0 && textValue(item.evidence));
  return <section className={`rating-panel ${compact ? 'compact' : ''}`} aria-label={t('rating')}>
    <div className="rating-heading"><h2>{t(preview ? 'previewScore' : 'readiness')}</h2><Icon name="chart" size={19}/></div>
    <div className="rating-total"><span className={`rating-number ${level}`}>{score}<small>/100</small></span><div><Badge score={score} t={t}/><p>{t(`${level}Hint`)}</p></div></div>
    <div className="rating-scale" aria-hidden="true"><span style={{ width: `${score}%` }} className={level}/></div>
    {initialScore !== undefined && score !== initialScore && <div className="score-change"><span>{t('originalScore')} <b>{initialScore}</b></span><Icon name="arrow" size={16}/><span>{t('nowScore')} <b>{score}</b></span><strong className={score < initialScore ? 'decreased' : ''}>{score > initialScore ? '+' : ''}{score - initialScore} {t('points',Math.abs(score-initialScore))}</strong></div>}
    <p className="rating-caption">{t(preview ? 'scoreHint' : 'scoreMeaning')}</p>
    {preview && list.length > 0 && <div className="rating-guidance"><p><strong>{t('supportedFacts')}</strong> {supported.length} / {list.length}</p>{gaps.length > 0 && <><strong>{t('priorityGaps')}</strong><ul>{gaps.map(item => <li key={item.key}><span>{criterionLabels[language][item.key] || item.label}</span><p>{item.next_step}</p></li>)}</ul></>}</div>}
    {analysis?.score_source && analysis.score_source !== 'ai' && <p className="rating-source"><Icon name="info" size={13}/>{t(analysis.analysis_fields_changed ? 'editedRating' : analysis.score_source === 'sample' ? 'sampleRating' : 'localRating')}</p>}
    {list.length > 0 && <div className="criteria-list">{list.map((criterion, index) => {
      const weight = Number(criterion.weight || criterion.max_points || 0);
      const value = Number(criterion.points ?? criterion.score ?? 0);
      const label = criterionLabels[language][criterion.key] || criterion.label || criterion.key;
      const evidence = textValue(criterion.evidence);
      return <details className="criterion" key={criterion.key || index}>
        <summary><span className="criterion-name">{label}</span><span className="criterion-score">{value}<small>/{weight}</small></span><Icon name="chevron" size={14}/><span className="criterion-track" aria-hidden="true"><span style={{ width: `${weight ? Math.min(100, value / weight * 100) : 0}%` }}/></span></summary>
        <div className="criterion-detail">{criterion.reason && <p>{criterion.reason}</p>}{evidence && <><strong>{t('evidence')}</strong><blockquote>{evidence}</blockquote></>}{criterion.next_step && value < weight && <><strong>{t('nextStep')}</strong><p>{criterion.next_step}</p></>}</div>
      </details>;
    })}</div>}
  </section>;
}

function Catalog({ data, route, navigate, t, language }) {
  const editorJob = useJob('editor');
  const [query, setQuery] = useState(route.q);
  useEffect(() => setQuery(route.q), [route.q]);
  const all = data.challenges || [];
  const topics = [...new Set(all.map(task => task.topic).filter(Boolean))];
  const tasks = useMemo(() => all.filter(task => {
    const search = `${task.title} ${task.topic} ${textValue(task.fields?.context)} ${textValue(task.fields?.need)}`.toLowerCase();
    return (!query || search.includes(query.toLowerCase())) && (!route.topic || task.topic === route.topic) && (!route.level || levelKey(task.score) === route.level);
  }).sort((a, b) => b.score - a.score), [all, query, route.topic, route.level]);
  const updateFilter = (key, value) => navigate('catalog', { q: query, topic: route.topic, level: route.level, [key]: value }, true);
  const activeFilters = query || route.topic || route.level;
  const readiness = readinessSummary(all);
  const number = new Intl.NumberFormat(['ru','kk','en'].includes(language) ? language : 'ru');
  return <>
    {editorJob && <div className="catalog-job"><JobNotice job={editorJob} t={t}/><NavLink view="editor" navigate={navigate} className="text-button">{t(editorJob.status === 'succeeded' ? 'openReview' : 'returnDraft')}<Icon name="arrow" size={16}/></NavLink></div>}
    <div className="page-heading catalog-heading"><div><h1>{t('catalogTitle')}</h1><p>{t('catalogIntro')}</p></div><NavLink view="editor" navigate={navigate} className="button primary"><Icon name="plus" size={18}/>{t('newTask')}</NavLink></div>
    <section className="readiness-overview" aria-label={t('readinessMap')}><div className="readiness-overview-label"><Icon name="chart" size={18}/><div><h2>{t('readinessMap')}</h2><p>{t('readinessMapHint')}</p></div></div><div className="readiness-levels">{readiness.map(level => <NavLink key={level.key} view="catalog" values={{q:query,topic:route.topic,level:route.level === level.key ? '' : level.key}} navigate={navigate} className={`readiness-level ${level.key} ${route.level === level.key ? 'selected' : ''}`} aria-current={route.level === level.key ? 'true' : undefined}><span className="readiness-level-name"><span className="status-dot"/>{t(level.key)}</span><strong>{number.format(level.count)}<small>{level.range}</small></strong></NavLink>)}</div></section>
    <div className="catalog-bar"><div className="catalog-tab">{t('allTasks')}<span>{all.length}</span></div><span className="catalog-sort"><Icon name="chart" size={16}/>{t('sort')}</span></div>
    <div className="filters"><div className="search-field"><Icon name="search" size={19}/><input aria-label={t('search')} type="search" name="search" autoComplete="off" placeholder={t('searchPlaceholder')} value={query} onChange={e => { setQuery(e.target.value); updateFilter('q', e.target.value); }}/></div><select aria-label={t('topic')} value={route.topic} onChange={e => updateFilter('topic', e.target.value)}><option value="">{t('allTopics')}</option>{topics.map(topic => <option key={topic}>{topic}</option>)}</select><select aria-label={t('readiness')} value={route.level} onChange={e => updateFilter('level', e.target.value)}><option value="">{t('allLevels')}</option>{['priority','ready','working','draft'].map(level => <option key={level} value={level}>{t(level)}</option>)}</select></div>
    {activeFilters && <div className="filter-results"><span>{tasks.length} {t('countOf')} {all.length} {t('taskCount',all.length)}</span><button className="text-button" onClick={() => navigate('catalog', {}, true)}>{t('clearFilters')}<Icon name="close" size={14}/></button></div>}
    {tasks.length ? <div className="task-grid">{tasks.map((task, index) => <ChallengeCard key={task.id} task={task} navigate={navigate} t={t} featured={index === 0 && !activeFilters}/>)}</div> : <EmptyState icon="search" title={t('noMatches')} action={<button className="button secondary" onClick={() => navigate('catalog', {}, true)}>{t('clearFilters')}</button>}>{t('noMatchesText')}</EmptyState>}
    <div className="catalog-footnote"><Icon name="info" size={17}/><p>{t('scoreMeaning')}</p></div>
  </>;
}

function ChallengeCard({ task, navigate, t, featured }) {
  const fields = task.fields || task;
  return <article className={`task-card ${levelKey(task.score)} ${featured ? 'featured' : ''}`}>
    <div className="task-card-top"><span className="topic-label">{task.topic || t('allTasks')}</span><Badge score={task.score} t={t}/></div>
    <div className="task-card-body"><div className="task-copy"><h2><NavLink view="task" values={{id: task.id}} navigate={navigate}>{task.title || fields.title}</NavLink></h2><p className="task-context">{fields.need || fields.context || task.draft}</p></div><div className="task-score" aria-label={`${t('readiness')}: ${task.score}/100`}><strong>{task.score}</strong><span>/ 100</span><small>{t('readiness')}</small><span className="task-score-track" aria-hidden="true"><i style={{width:`${Math.max(0,Math.min(100,Number(task.score) || 0))}%`}}/></span></div></div>
    {fields.expected_result && <p className="task-result"><span><Icon name="checkCircle" size={14}/>{t('result')}</span>{fields.expected_result}</p>}
    <div className="task-card-footer"><div className="task-meta"><span><Icon name="users" size={16}/>{task.proposal_count ?? task.proposals?.length ?? 0} {t('proposals',task.proposal_count ?? task.proposals?.length ?? 0)}</span><span className="seed-label">{provenance(task,t)}</span></div><NavLink view="task" values={{ id: task.id }} navigate={navigate} className="task-open">{t('openTask')}<Icon name="arrow" size={17}/></NavLink></div>
  </article>;
}

function TaskDetail({ id, data, navigate, t, language, onUpdate, notify }) {
  const [task, setTask] = useState(() => data.challenges.find(item => item.id === id));
  const [error, setError] = useState('');
  const [tab, updateTab] = useState('brief');
  const setTab = next => { if (allowNavigation()) updateTab(next); };
  const [reload, setReload] = useState(0);
  useEffect(() => { let current = true; setError(''); api(`/challenges/${encodeURIComponent(id)}`).then(value => { if (current) setTask(value.challenge || value); }).catch(err => current && setError(err.message)); return () => { current = false; }; }, [id,reload]);
  const retry = <button className="button secondary small" onClick={() => setReload(value => value+1)}>{t('retry')}</button>;
  if ((!task || task.summary) && error) return <ErrorBox title={t('loadError')} error={error}>{retry}</ErrorBox>;
  if (!task || task.summary) return <Loading t={t}/>;
  const fields = task.fields || task;
  return <>
    <NavLink view="catalog" navigate={navigate} className="back-link"><Icon name="back" size={17}/>{t('backCatalog')}</NavLink>
    <ErrorBox title={t('refreshFailed')} error={error}>{retry}</ErrorBox>
    <div className="detail-heading"><div className="inline-meta"><span className="topic-label">{task.topic}</span><span className="seed-label">{provenance(task,t)}</span></div><h1>{task.title || fields.title}</h1><div className="detail-heading-bottom"><Badge score={task.score} t={t}/><span><Icon name="users" size={17}/>{task.proposal_count ?? task.proposals?.length ?? 0} {t('proposals',task.proposal_count ?? task.proposals?.length ?? 0)}</span>{task.is_owner && <NavLink view="workspace" values={{id:task.id}} navigate={navigate} className="text-button">{t('viewWorkspace')}<Icon name="arrow" size={16}/></NavLink>}</div></div>
    <div className="detail-layout"><div><div className="section-tabs"><button className={tab === 'brief' ? 'active' : ''} onClick={() => setTab('brief')}>{t('taskDetails')}</button><button className={tab === 'apply' ? 'active' : ''} onClick={() => setTab('apply')}>{t('application')}<Icon name="arrow" size={15}/></button></div>
      {tab === 'brief' ? <article className="brief-document">{fieldsOrder.filter(key => key !== 'title').map(key => <section key={key} className={!fields[key] ? 'missing-field' : ''}><h2>{fieldLabels[language][key]}</h2><p>{textValue(fields[key]) || t('notProvided')}</p></section>)}<div className="document-action"><button className="button primary" onClick={() => setTab('apply')}>{t('application')}<Icon name="arrow" size={17}/></button><p>{t('noRestrictions')}</p></div></article> : <ProposalForm task={task} teams={data.teams} t={t} onSent={() => { onUpdate(); setReload(value => value+1); notify(t('proposalSent')); }}/>}</div>
      <aside className="detail-aside"><RatingPanel analysis={task} t={t} language={language}/><div className="aside-note"><Icon name="shield" size={19}/><p>{t('noRestrictions')}</p></div></aside>
    </div>
  </>;
}

function ProposalForm({ task, teams = [], t, onSent }) {
  const formKey = `sana-proposal-${task.id}`;
  const [form, setForm, storageFailed] = useSavedForm(formKey, { team_id: 'custom', team_name: '', skills: '', idea: '', plan: '', deadline: '', link: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  useLeaveWarning(busy || storageFailed, t(busy ? 'writePendingWarning' : 'storageWarning'));
  const selected = teams.find(team => team.id === form.team_id);
  const update = (key, value) => setForm(old => ({ ...old, [key]: value }));
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError('');
    try { const body = {idea:form.idea,plan:form.plan,deadline:form.deadline,link:form.link,...(form.team_id === 'custom' ? {team_name:form.team_name,skills:form.skills} : {team_id:form.team_id})}; await api(`/challenges/${encodeURIComponent(task.id)}/proposals`, { method: 'POST', body }); clearSaved(formKey); setSent(true); onSent(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  const fillDemo = () => setForm(old => ({...old, idea: t('idea') === 'Solution idea' ? `We will build a small working prototype for “${task.title}” and test it with the users described in the brief.` : t('idea') === 'Шешім идеясы' ? `«${task.title}» тапсырмасына шағын жұмыс прототипін жасап, сипаттамадағы пайдаланушылармен тексереміз.` : `Сделаем небольшой работающий прототип для задачи «${task.title}» и проверим его с пользователями из карточки.`, plan: t('plan') === 'Work plan' ? '1. Confirm available data and constraints with the business.\n2. Build and demonstrate one complete user scenario.\n3. Test against the stated success criteria and document results.' : t('plan') === 'Жұмыс жоспары' ? '1. Қолда бар деректер мен шектеулерді бизнеспен нақтылау.\n2. Бір толық сценарийдің прототипін көрсету.\n3. Табыс өлшемдері бойынша тексеріп, нәтижені тіркеу.' : '1. Уточнить с бизнесом доступные данные и ограничения.\n2. Собрать и показать один полный пользовательский сценарий.\n3. Проверить критерии успеха и зафиксировать результаты.', deadline: t('deadline') === 'Timeline' ? '2 weeks, weekly check-in' : t('deadline') === 'Мерзім' ? '2 апта, апта сайынғы кездесу' : '2 недели, еженедельная встреча', link:'https://example.com/prototype' }));
  const fillDemoClick = () => { if (form.team_id === 'custom' && !form.team_name && teams[0]) update('team_id',teams[0].id); fillDemo(); };
  if (sent) return <div className="proposal-success"><span className="success-symbol"><Icon name="check" size={30}/></span><h2>{t('proposalSent')}</h2><p>{t('proposalSentText')}</p><button className="button secondary" onClick={() => { setSent(false); setForm(old => ({...old, idea:'',plan:'',deadline:'',link:''})); }}>{t('sendAnother')}</button></div>;
  return <form className="proposal-form" onSubmit={submit}><h2>{t('application')}</h2><p className="form-intro">{t('noRestrictions')}</p><p className={`form-save-note ${storageFailed ? 'storage-error' : ''}`} role="status"><Icon name={storageFailed ? 'alert' : 'check'} size={14}/>{t(storageFailed ? 'storageWarning' : 'formSaved')}</p><fieldset disabled={busy} className="form-fields">
    <Field label={t('team')} name="proposal-team" required><select id="proposal-team" name="team_id" value={form.team_id} onChange={e => update('team_id', e.target.value)} required><option value="" disabled>{t('chooseTeam')}</option><option value="custom">{t('customTeam')}</option>{teams.map(team => <option key={team.id} value={team.id}>{team.name} · {t('seed')}</option>)}</select></Field>
    {form.team_id === 'custom' && <><Field label={t('teamName')} name="proposal-team-name" required><input id="proposal-team-name" name="team_name" minLength="2" maxLength="120" value={form.team_name} onChange={e => update('team_name',e.target.value)} placeholder={t('teamNameHint')} required/></Field><Field label={t('teamSkills')} name="proposal-skills"><input id="proposal-skills" name="skills" maxLength="1000" value={form.skills} onChange={e => update('skills',e.target.value)} placeholder={t('teamSkillsHint')}/></Field></>}
    {selected && <div className="selected-team"><span className="team-avatar">{selected.name?.slice(0,2)}</span><div><strong>{selected.name}</strong><p>{textValue(selected.skills)}</p></div></div>}
    <div className="demo-fill"><button type="button" className="text-button" onClick={fillDemoClick}><Icon name="brief" size={16}/>{t('proposalExample')}</button><small>{t('seed')}</small></div>
    <Field label={t('idea')} name="proposal-idea" required><textarea id="proposal-idea" name="idea" rows="4" minLength="20" maxLength="5000" value={form.idea} onChange={e => update('idea',e.target.value)} placeholder={t('ideaHint')} required/></Field>
    <Field label={t('plan')} name="proposal-plan" required><textarea id="proposal-plan" name="plan" rows="4" minLength="20" maxLength="5000" value={form.plan} onChange={e => update('plan',e.target.value)} placeholder={t('planHint')} required/></Field>
    <div className="form-two-col"><Field label={t('deadline')} name="proposal-deadline" required><input id="proposal-deadline" name="deadline" minLength="2" maxLength="200" value={form.deadline} onChange={e => update('deadline',e.target.value)} placeholder={t('deadlineHint')} required/></Field><Field label={t('prototype')} name="proposal-link" required><input id="proposal-link" name="link" type="url" spellCheck="false" maxLength="2000" value={form.link} onChange={e => update('link',e.target.value)} placeholder={t('prototypeHint')} required/></Field></div>
    </fieldset><ErrorBox title={t('error')} error={error}/><BusyButton type="submit" className="button primary" busy={busy} busyText={t('sending')}>{t('sendProposal')}<Icon name="arrow" size={17}/></BusyButton>
  </form>;
}

const blankDraft = restoreDraft();

function Editor({ drafts = [], t, language, navigate, notify, onUpdate }) {
  const [draft, setDraft, storageFailed] = useSavedForm('sana-draft-v2', restoreDraft, restoreDraft);
  const [seedChoice, setSeedChoice] = useState(draft.seedId);
  const [writeBusy, setBusy] = useState(false);
  const job = useJob('editor');
  const analysisLabel = t(analysisBusyKey(job));
  const busy = writeBusy || jobIsPending(job);
  const [error, setError] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const edited = draftHasEdits(draft);
  const [operation, setOperation] = useState('analyze');
  const [usedDemo, setUsedDemo] = useState(false);
  const [recovered, setRecovered] = useState(false);
  const sourceRef = useRef(null);
  useLeaveWarning(writeBusy || storageFailed, t(writeBusy ? 'writePendingWarning' : 'storageWarning'));
  useEffect(() => {
    if (job?.status === 'failed') { setError(job.error || t('analysisError')); return; }
    if (job?.status !== 'succeeded') return;
    const completed = completedDraftPatch(draft, job);
    if (completed) {
      setDraft(current => ({ ...current, ...completed }));
      setConfirmed(false); setError(''); setRecovered(true);
    } else setError(t('staleJob'));
    analysisJobs.clear('editor');
  }, [job]);
  const patch = values => setDraft(old => ({...old,...values}));
  const selectedSeed = drafts.find(seed => seed.id === draft.seedId);
  const seedAnswers = selectedSeed?.answers || {};
  const loadSeed = () => {
    const selected = drafts.find(seed => seed.id === seedChoice);
    if (!selected) return;
    analysisJobs.clear('editor'); setRecovered(false);
    setDraft({...blankDraft,text:selected.text,topic:selected.topic || '',seedId:selected.id}); setConfirmed(false); setError(''); setUsedDemo(false);
    sourceRef.current?.focus();
  };
  const reset = () => {
    if (draft.text && !window.confirm(t('resetConfirm'))) return;
    analysisJobs.clear('editor'); setRecovered(false);
    setDraft({...blankDraft}); setSeedChoice(''); setConfirmed(false); setError(''); setUsedDemo(false);
  };
  const analyze = ({ offline = false, stage = 1, answers = answersForAnalysis(draft) } = {}) => {
    if (draft.text.trim().length < 12) { setError(t('minDraft')); sourceRef.current?.focus(); return; }
    if (titleTooLong(answers)) { setError(t('titleTooLong')); return; }
    setOperation('analyze'); setError(''); setRecovered(false);
    analysisJobs.start('editor', { draft:draft.text, answers, language, offline }, { snapshot:draftSnapshot(draft), answers, stage });
  };
  const fillDemo = () => { patch({ answers: {...draft.answers,...seedAnswers} }); setUsedDemo(true); };
  const publish = async event => {
    event.preventDefault(); if (!confirmed || edited) return;
    setBusy(true); setOperation('publish'); setError('');
    try {
      const result = await api('/challenges', { method:'POST', body:{draft:draft.text, fields:draft.fields, topic:draft.topic || selectedSeed?.topic || (language === 'en' ? 'Education' : language === 'kk' ? 'Білім беру' : 'Образование'), analysis_id:draft.analysis?.analysis_id, confirmed:true,language} });
      const task = result.challenge || result;
      patch({published:task,stage:3}); onUpdate(); notify(t('published'));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  if (draft.published) return <div className="publish-result"><span className="success-symbol"><Icon name="check" size={34}/></span><h1>{t('published')}</h1><p>{t('publishedText')}</p><div className="published-preview"><span className="topic-label">{draft.published.topic || draft.topic}</span><h2>{draft.published.title || draft.fields.title}</h2><Badge score={draft.published.score ?? draft.analysis?.score} t={t}/></div><div className="button-row"><NavLink view="task" values={{id:draft.published.id}} navigate={navigate} className="button primary">{t('viewPublished')}<Icon name="arrow" size={17}/></NavLink><NavLink view="workspace" values={{id:draft.published.id}} navigate={navigate} className="button secondary">{t('viewWorkspace')}</NavLink></div><button className="text-button" onClick={() => { setDraft({...blankDraft}); setSeedChoice(''); }}>{t('resetDraft')}<Icon name="plus" size={16}/></button></div>;
  return <>
    <div className="page-heading"><div><h1>{t('editorTitle')}</h1><p>{t('editorIntro')}</p></div>{draft.text && <button className="button ghost small" onClick={reset} disabled={busy}><Icon name="plus" size={16}/>{t('resetDraft')}</button>}</div>
    <ol className="steps">{['stageDraft','stageClarify','stagePublish'].map((key,index) => <li key={key} className={`${draft.stage === index ? 'current' : ''} ${draft.stage > index ? 'complete' : ''}`} aria-current={draft.stage === index ? 'step' : undefined}><span>{draft.stage > index ? <Icon name="check" size={15}/> : index+1}</span>{t(key)}{index < 2 && <Icon name="chevron" size={16}/>}</li>)}</ol>
    <JobNotice job={job} t={t}/>
    {recovered && <p className="form-save-note" role="status"><Icon name="checkCircle" size={15}/>{t('reviewReady')}</p>}
    {storageFailed && <div className="notice error" role="alert"><Icon name="alert" size={18}/><p>{t('storageWarning')}</p></div>}
    <div className="editor-layout"><div className="editor-main">
      {draft.stage === 0 && <section className="draft-form panel"><h2>{t('source')}</h2><p className="form-intro">{t('sourceHint')}</p><div className="sample-picker"><label htmlFor="sample-draft"><Icon name="brief" size={16}/>{t('tryExample')}</label><div><select id="sample-draft" name="sample" value={seedChoice} onChange={e => setSeedChoice(e.target.value)}><option value="">{t('chooseExample')}</option>{drafts.map(seed => <option key={seed.id} value={seed.id}>{seed.title || seed.text.slice(0,75)}</option>)}</select><button className="button secondary small" disabled={!seedChoice || busy} onClick={loadSeed}>{t('useExample')}</button></div></div>
        <label htmlFor="draft-source" className="visually-hidden">{t('source')}</label><textarea ref={sourceRef} id="draft-source" name="draft" className="source-textarea" value={draft.text} onChange={e => setDraft(current => replaceDraftText(current,e.target.value))} rows="9" maxLength="12000" placeholder={t('sourcePlaceholder')} disabled={busy}/><div className="input-footer"><span><Icon name="check" size={13}/>{t('savedLocally')}</span><span>{draft.text.length.toLocaleString()} / 12,000</span></div>
        <Field label={t('topic')} name="draft-topic"><input id="draft-topic" name="topic" value={draft.topic} onChange={e => patch({topic:e.target.value})} maxLength="80" placeholder={t('topicPlaceholder')} disabled={busy}/></Field><BusyButton className="button primary full-width" busy={busy} busyText={analysisLabel} onClick={() => analyze()}><Icon name="sparkle" size={18}/>{t('analyze')}<Icon name="arrow" size={17}/></BusyButton>
      </section>}
      {draft.stage > 0 && <div className="source-summary"><Icon name="brief" size={20}/><div><strong>{t('source')}</strong><p>{draft.text}</p></div><button className="icon-button" aria-label={t('backDraft')} disabled={busy} onClick={() => patch({stage:0})}><Icon name="edit" size={18}/></button></div>}
      {draft.stage === 1 && <section className="questions-section"><div className="section-heading"><div><h2>{t('questions')}</h2><p>{t('questionsHint')}</p></div></div>{Object.keys(seedAnswers).length > 0 && <div className="demo-fill"><button className="text-button" disabled={busy} onClick={fillDemo}><Icon name="brief" size={16}/>{t('demoAnswers')}</button><small>{t('seed')}</small></div>}{usedDemo && <div className="notice info compact"><Icon name="info" size={17}/><p>{t('demoAnswersNote')}</p></div>}
        {(draft.analysis?.questions || []).map((question,index) => { const key = question.field || question.id; return <div className="question-block" key={question.id || index}><div className="question-title"><span>{index+1}</span><h3>{question.question || question.text}</h3>{question.max_points > 0 && <span className="question-weight">{question.max_points} {t('points',question.max_points)}</span>}</div>{question.why && <p className="question-reason">{question.why}</p>}<label htmlFor={`answer-${index}`} className="visually-hidden">{t('answer')}: {question.question}</label><textarea id={`answer-${index}`} name={key} rows="3" maxLength={fieldMaxLength(key)} value={draft.answers[key] || ''} onChange={e => patch({answers:{...draft.answers,[key]:e.target.value}})} placeholder={question.answer_hint || `${t('answer')}…`} disabled={busy}/></div>; })}
        <div className="editor-bottom-actions"><button className="button ghost" disabled={busy} onClick={() => patch({stage:0})}><Icon name="back" size={16}/>{t('backDraft')}</button><BusyButton className="button primary" busy={busy} busyText={analysisLabel} onClick={() => analyze({stage:2,offline:draft.analysis?.mode === 'offline'})}>{t('buildCard')}<Icon name="arrow" size={17}/></BusyButton></div>
      </section>}
      {draft.stage === 2 && <form onSubmit={publish} className="review-form"><div className="section-heading"><div><h2>{t('reviewTitle')}</h2><p>{t('reviewIntro')}</p></div></div><div className="fields-editor">{fieldsOrder.map(key => <Field key={key} name={`card-${key}`} label={fieldLabels[language][key]}>{key === 'title' || key === 'contact' ? <input id={`card-${key}`} name={key} maxLength={key === 'title' ? 180 : 300} value={textValue(draft.fields[key])} onChange={e => {patch({fields:{...draft.fields,[key]:e.target.value}});setConfirmed(false);}} disabled={busy} placeholder={t('notProvided')}/> : <textarea id={`card-${key}`} name={key} rows={key === 'context' || key === 'need' ? 3 : 2} maxLength="4000" value={textValue(draft.fields[key])} onChange={e => {patch({fields:{...draft.fields,[key]:e.target.value}});setConfirmed(false);}} disabled={busy} placeholder={t('notProvided')}/>}</Field>)}</div>
        {edited && <div className="notice info"><Icon name="info" size={18}/><div><p>{t('editsPending')}</p><BusyButton type="button" className="button secondary small" busy={busy} busyText={analysisLabel} onClick={() => analyze({stage:2,offline:draft.analysis?.mode === 'offline'})}>{t('updateRating')}</BusyButton></div></div>}
        <label className="confirmation"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} required disabled={busy}/><span>{t('confirm')}</span></label><div className="editor-bottom-actions"><button type="button" className="button ghost" onClick={() => patch({stage:1,answers:answersForAnalysis(draft)})} disabled={busy}><Icon name="back" size={16}/>{t('stageClarify')}</button><BusyButton type="submit" className="button primary" busy={busy} busyText={t('publishing')} disabled={!confirmed || edited}>{t('publish')}<Icon name="arrow" size={17}/></BusyButton></div>
      </form>}
      <ErrorBox title={operation === 'publish' ? t('error') : t('analysisError')} error={error}>{operation !== 'publish' && <><div className="button-row"><button type="button" className="button primary small" onClick={() => analyze({stage:job?.meta?.stage || (draft.stage === 0 ? 1 : draft.stage)})} disabled={busy}>{t('retryAI')}</button><button type="button" className="button secondary small" onClick={() => analyze({offline:true,stage:job?.meta?.stage || (draft.stage === 0 ? 1 : draft.stage)})} disabled={busy}>{t('offlineAction')}</button></div><small className="offline-explanation">{t('offlineNote')}</small></>}</ErrorBox>
    </div><aside className="editor-aside">{busy ? <div className="analysis-progress"><span className="ai-loading-mark"><Mark size={38}/></span><h2>{operation === 'publish' ? t('publishing') : analysisLabel}</h2><p>{t(operation === 'publish' ? 'publishedText' : job?.payload?.offline ? 'offlineNote' : 'analyzingHint')}</p><div className="skeleton-line"/><div className="skeleton-line short"/><div className="skeleton-line"/></div> : draft.analysis ? <>
      <div className={`analysis-summary ${draft.analysis.mode === 'offline' ? 'offline' : ''}`}><span className="analysis-mode"><Icon name={draft.analysis.mode === 'offline' ? 'info' : 'sparkle'} size={17}/>{t(draft.analysis.mode === 'offline' ? 'offlineBadge' : 'aiBadge')}</span><h2>{t(draft.analysis.mode === 'offline' ? 'offlineSummary' : 'summary')}</h2><p>{textValue(draft.analysis.summary)}</p></div><RatingPanel analysis={draft.analysis} initialScore={draft.initialScore ?? undefined} t={t} language={language} preview/>
      {!!draft.analysis.warnings?.length && <div className="analysis-warnings">{draft.analysis.warnings.map((warning,index) => <p key={index}><Icon name="info" size={16}/>{textValue(warning)}</p>)}</div>}
      {!!draft.analysis.trace?.length && <details className="trace"><summary>{t('trace')}<Icon name="chevron" size={15}/></summary><ol>{draft.analysis.trace.map((step,index) => <li key={index}><span className="trace-dot"/><div><strong>{step.tool || step.name}</strong><p>{textValue(step.summary || step.result)}</p>{step.input_preview && <details className="trace-input"><summary>{t('traceInput')}<Icon name="chevron" size={13}/></summary><pre>{textValue(step.input_preview)}</pre></details>}{step.elapsed_ms >= 50 && <small>{(step.elapsed_ms/1000).toFixed(1)}s</small>}</div></li>)}</ol></details>}
    </> : <div className="analyst-intro"><span className="analyst-symbol"><Icon name="sparkle" size={25}/></span><h2>{t('analystTitle')}</h2><p>{t('analystText')}</p><div className="promise-list">{['message','chart','shield'].map((icon,index) => <div key={icon}><Icon name={icon} size={20}/><div><h3>{t(`promise${index+1}`)}</h3><p>{t(`promise${index+1}Text`)}</p></div></div>)}</div></div>}</aside></div>
  </>;
}

function Workspace(props) {
  const owned = props.data.challenges.filter(task => task.is_owner);
  const activeId = owned.some(item => item.id === props.route.id) ? props.route.id : owned[0]?.id;
  return <WorkspaceForm key={activeId || 'empty'} {...props}/>;
}
function WorkspaceForm({ data, route, navigate, t, language, onUpdate, notify }) {
  const owned = data.challenges.filter(task => task.is_owner);
  const activeId = owned.some(item => item.id === route.id) ? route.id : owned[0]?.id;
  const formKey = `sana-published-edit-${activeId}`;
  const [edit, setEdit, storageFailed] = useSavedForm(formKey, { editing:false, fields:{}, analysis:null, baseVersion:null });
  const [task, setTask] = useState(null);
  const [writeBusy, setBusy] = useState('');
  const jobChannel = `workspace:${activeId}`;
  const job = useJob(jobChannel);
  const analysisLabel = t(analysisBusyKey(job));
  const busy = jobIsPending(job) ? 'analyze' : writeBusy;
  const [error, setError] = useState('');
  const { editing, fields, analysis: editAnalysis } = edit;
  const setFields = fields => setEdit(old => ({...old,fields}));
  const [editConfirmed, setEditConfirmed] = useState(false);
  useLeaveWarning(Boolean(writeBusy) || storageFailed, t(writeBusy ? 'writePendingWarning' : 'storageWarning'));
  const refreshTask = useCallback(async () => { if (!activeId) { setTask(null); return; } const result = await api(`/challenges/${encodeURIComponent(activeId)}`); setTask(result.challenge || result); }, [activeId]);
  useEffect(() => { setTask(owned.find(item => item.id === activeId) || null); setError(''); refreshTask().catch(err => setError(err.message)); }, [activeId]);
  useEffect(() => {
    if (job?.status === 'failed') { setError(job.error || t('analysisError')); return; }
    if (job?.status !== 'succeeded') return;
    if (job.meta.snapshot === inputSnapshot(fields) && job.meta.version === edit.baseVersion) {
      setEdit(old => ({...old, analysis:job.analysis, fields:{...job.analysis.fields}}));
      setEditConfirmed(false); setError('');
    } else setError(t('staleJob'));
    analysisJobs.clear(jobChannel);
  }, [job]);
  const decision = async (proposalId,status) => { setBusy(proposalId);setError(''); try { await api(`/proposals/${encodeURIComponent(proposalId)}`,{method:'PATCH',body:{status}}); await refreshTask(); onUpdate(); notify(t('decisionSaved')); } catch(err) {setError(err.message);} finally {setBusy('');} };
  const editChanged = fieldsDiffer(fields,task?.fields);
  const editReviewed = Boolean(editAnalysis && !fieldsDiffer(fields,editAnalysis.fields));
  const staleEdit = editing && task && !task.summary && edit.baseVersion !== task.version;
  const toggleEdit = () => {
    if (editing && editChanged && !window.confirm(t('discardEdits'))) return;
    setEdit({ editing:!editing, fields:editing ? {} : {...task.fields}, analysis:null, baseVersion:editing ? null : task.version });
    setEditConfirmed(false); setError(''); analysisJobs.clear(jobChannel);
  };
  const reviewEdits = (offline = false) => {
    if (titleTooLong(fields)) { setError(t('titleTooLong')); return; }
    setError('');
    analysisJobs.start(jobChannel, {draft:task.draft || task.fields.context,answers:fields,language,offline}, {snapshot:inputSnapshot(fields),version:edit.baseVersion});
  };
  const save = async event => {event.preventDefault();if(!editConfirmed || staleEdit || (editChanged && !editReviewed))return;setBusy('save');setError('');try {await api(`/challenges/${encodeURIComponent(task.id)}`,{method:'PATCH',body:{fields,confirmed:true,version:edit.baseVersion,language,analysis_id:editReviewed?editAnalysis.analysis_id:undefined}});setEdit({editing:false,fields:{},analysis:null,baseVersion:null});clearSaved(formKey);await refreshTask();onUpdate();notify(t('changesSaved'));} catch(err){setError(err.message);} finally {setBusy('');}};
  const proposals = task?.proposals || [];
  return <>
    <div className="page-heading"><div><h1>{t('workspaceTitle')}</h1><p>{t('workspaceIntro')}</p></div><NavLink view="editor" navigate={navigate} className="button primary"><Icon name="plus" size={18}/>{t('newTask')}</NavLink></div>
    {!owned.length ? <EmptyState icon="work" title={t('workspaceEmpty')} action={<NavLink view="editor" navigate={navigate} className="button primary">{t('newTask')}<Icon name="arrow" size={17}/></NavLink>}>{t('workspaceEmptyText')}</EmptyState> : <>
      <div className="workspace-toolbar"><Field label={t('myPublished')} name="workspace-task"><select id="workspace-task" value={activeId || ''} onChange={e => navigate('workspace',{id:e.target.value})}>{owned.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></Field><span className="workspace-count"><b>{owned.length}</b> {t('taskCount',owned.length)}</span></div>
      <ErrorBox title={t('error')} error={error}><button type="button" className="button secondary small" disabled={!!busy} onClick={() => {setError('');refreshTask().catch(err => setError(err.message));}}>{t('retry')}</button></ErrorBox>
      <JobNotice job={job} t={t}/>
      {editing && <p className={`form-save-note ${storageFailed ? 'storage-error' : ''}`} role="status"><Icon name={storageFailed ? 'alert' : 'check'} size={14}/>{t(storageFailed ? 'storageWarning' : 'editsSavedLocally')}</p>}
      {staleEdit && <div className="notice error" role="alert"><Icon name="alert" size={18}/><p>{t('staleEdit')}</p></div>}
      {task?.summary && !error && <Loading t={t}/>}
      {task && !task.summary && <><div className="workspace-task-summary"><div><span className="topic-label">{task.topic}</span><h2>{task.title}</h2><div className="inline-meta"><Badge score={task.score} t={t}/><span>{proposals.length} {t('proposals',proposals.length)}</span></div></div><div className="button-row"><button className="button secondary small" disabled={!!busy} onClick={toggleEdit}><Icon name="edit" size={16}/>{t(editing?'cancel':'editTask')}</button><NavLink view="task" values={{id:task.id}} navigate={navigate} className="button ghost small">{t('openTask')}<Icon name="external" size={15}/></NavLink></div></div>
      {editing ? <form className="workspace-edit" onSubmit={save}>
        <div className="fields-editor">{fieldsOrder.map(key => <Field key={key} label={fieldLabels[language][key]} name={`edit-${key}`}><textarea id={`edit-${key}`} name={key} rows="2" maxLength={fieldMaxLength(key)} value={fields[key] || ''} disabled={!!busy} onChange={e => {setFields({...fields,[key]:e.target.value});setEditConfirmed(false);}}/></Field>)}</div>
        {editChanged && !editReviewed && <div className="notice info"><Icon name="info" size={18}/><div><p>{t('ratingRequired')}</p><BusyButton type="button" className="button secondary small" busy={busy === 'analyze'} busyText={analysisLabel} disabled={staleEdit || !!busy} onClick={() => reviewEdits()}><Icon name="sparkle" size={16}/>{t('refreshAnalysis')}</BusyButton>{error && <><button className="button ghost small" type="button" onClick={() => reviewEdits(true)} disabled={!!busy || staleEdit}>{t('offlineAction')}</button><small className="offline-explanation">{t('offlineNote')}</small></>}</div></div>}
        {editAnalysis && <div className="workspace-review-score">{editAnalysis.mode === 'offline' && <p className="rating-source">{t('offlineBadge')}</p>}<RatingPanel analysis={editAnalysis} initialScore={task.score} t={t} language={language} preview/></div>}
        <label className="confirmation"><input type="checkbox" checked={editConfirmed} onChange={e => setEditConfirmed(e.target.checked)} required disabled={!!busy || staleEdit || (editChanged && !editReviewed)}/><span>{t('confirm')}</span></label>
        <BusyButton className="button primary" type="submit" busy={busy === 'save'} busyText={t('saving')} disabled={!!busy || staleEdit || !editConfirmed || (editChanged && !editReviewed)}>{t('saveChanges')}<Icon name="check" size={17}/></BusyButton>
      </form> : <><div className="section-heading proposals-heading"><div><h2>{t('compare')} <span className="count-pill">{proposals.length}</span></h2><p>{t('manualChoice')}</p></div><Icon name="users" size={23}/></div>
      {!proposals.length ? <EmptyState icon="message" title={t('noProposals')} action={<NavLink view="task" values={{id:task.id}} navigate={navigate} className="button secondary">{t('testProposal')}<Icon name="arrow" size={17}/></NavLink>}>{t('noProposalsText')}</EmptyState> : <div className="proposals-list">{proposals.map(proposal => <ProposalReview key={proposal.id} proposal={proposal} teams={data.teams} t={t} busy={busy === proposal.id} decision={decision} notify={notify} onUpdate={async () => {await refreshTask();onUpdate();}}/>)}</div>}</>}
      </>}
    </>}
  </>;
}

function ProposalReview({ proposal, teams, t, busy, decision, onUpdate, notify }) {
  const team = teams.find(item => item.id === proposal.team_id) || {};
  const status = proposal.status || 'submitted';
  const teamName = proposal.team_name || team.name || proposal.team_id;
  const milestones = proposal.milestone ? [proposal.milestone] : proposal.milestones || proposal.progress || [];
  const awarded = milestones.length > 0 || Number(proposal.points || 0) > 0;
  const [milestone, setMilestone] = useState({title:'',evidence:''});
  const [saving, setSaving] = useState(false);
  const [error,setError] = useState('');
  const fillMilestone = () => setMilestone({title:t('milestoneTitle') === 'Completed milestone' ? 'Sample: working prototype reviewed' : t('milestoneTitle') === 'Аяқталған кезең атауы' ? 'Мысал: жұмыс прототипі тексерілді' : 'Учебный пример: рабочий прототип проверен', evidence:t('milestoneTitle') === 'Completed milestone' ? `Demo confirmation: the team showed its first prototype and walked through the plan. Prototype: ${proposal.link || 'https://example.com/prototype'}` : t('milestoneTitle') === 'Аяқталған кезең атауы' ? `Демо растау: команда алғашқы прототипін және жұмыс жоспарын көрсетті. Прототип: ${proposal.link || 'https://example.com/prototype'}` : `Демо-подтверждение: команда показала первый прототип и прошла сценарий из плана. Прототип: ${proposal.link || 'https://example.com/prototype'}`});
  const confirm = async event => {event.preventDefault();setSaving(true);setError('');try {await api(`/proposals/${encodeURIComponent(proposal.id)}/milestones`,{method:'POST',body:milestone});await onUpdate();setMilestone({title:'',evidence:''});notify(t('milestoneSaved'));}catch(err){setError(err.message);}finally{setSaving(false);}};
  const link = safeLink(proposal.link || proposal.prototype_link);
  return <article className={`proposal-review ${status}`}><div className="proposal-review-head"><span className="team-avatar">{teamName?.slice(0,2)}</span><div><h3>{teamName}</h3><p>{textValue(team.skills || proposal.skills)}</p></div><span className={`badge proposal-status ${status}`}><span className="status-dot"/>{t(status)}</span></div><div className="proposal-sections"><div><h4>{t('idea')}</h4><p>{proposal.idea}</p></div><div><h4>{t('plan')}</h4><p>{proposal.plan}</p></div></div><div className="proposal-meta"><span><Icon name="clock" size={16}/>{proposal.deadline || t('notProvided')}</span>{link && <a href={link} target="_blank" rel="noreferrer">{t('prototype')}<Icon name="external" size={15}/></a>}</div>
    <div className="proposal-actions">{status !== 'accepted' && <BusyButton className="button primary small" busy={busy} busyText={t('saving')} onClick={() => decision(proposal.id,'accepted')}><Icon name="check" size={16}/>{t('accept')}</BusyButton>}{status !== 'shortlisted' && status !== 'accepted' && <button className="button secondary small" disabled={busy} onClick={() => decision(proposal.id,'shortlisted')}><Icon name="bookmark" size={16}/>{t('shortlist')}</button>}{status !== 'rejected' && !awarded && <button className="button ghost small" disabled={busy} onClick={() => decision(proposal.id,'rejected')}>{t('reject')}</button>}{status === 'accepted' && <span className="selected-confirmation"><Icon name="checkCircle" size={18}/>{t('selectedTeam')}</span>}</div>
    {status === 'accepted' && <div className="milestone-section"><h4><Icon name="award" size={19}/>{t('progress')}{awarded && <span className="team-points">{t('teamPoints')}: {proposal.points || 10}</span>}</h4>{milestones.map((item,index) => <div className="milestone-record" key={item.id || index}><Icon name="checkCircle" size={19}/><div><strong>{item.title}</strong><p>{item.evidence}</p></div><span>+{item.points || 10}</span></div>)}{!awarded && <form onSubmit={confirm}><div className="demo-fill"><button type="button" className="text-button" onClick={fillMilestone}><Icon name="brief" size={16}/>{t('milestoneExample')}</button><small>{t('seed')}</small></div><Field label={t('milestoneTitle')} name={`milestone-${proposal.id}`} required><input id={`milestone-${proposal.id}`} name="title" value={milestone.title} onChange={e => setMilestone({...milestone,title:e.target.value})} minLength="5" maxLength="180" placeholder={t('milestoneTitleHint')} required/></Field><Field label={t('milestoneEvidence')} name={`evidence-${proposal.id}`} required><textarea id={`evidence-${proposal.id}`} name="evidence" value={milestone.evidence} onChange={e => setMilestone({...milestone,evidence:e.target.value})} rows="2" minLength="10" maxLength="2000" placeholder={t('milestoneEvidenceHint')} required/></Field><ErrorBox title={t('error')} error={error}/><BusyButton type="submit" className="button secondary small" busy={saving} busyText={t('saving')}><Icon name="check" size={16}/>{t('confirmMilestone')}</BusyButton></form>}</div>}
  </article>;
}

function Loading({ t }) {
  return <div className="loading-page" role="status" aria-label={t('loading')}><div className="skeleton-line heading"/><div className="skeleton-line short"/><div className="skeleton-toolbar"/><div className="skeleton-grid">{[1,2,3,4].map(item => <div className="skeleton-card" key={item}><div className="skeleton-line short"/><div className="skeleton-line"/><div className="skeleton-line"/></div>)}</div><span className="visually-hidden">{t('loading')}</span></div>;
}

export default function App() {
  const [language, setLanguage] = useState(() => { try { return localStorage.getItem('sana-language') || 'ru'; } catch { return 'ru'; } });
  const t = translator(language);
  const [route, navigate] = useRoute();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const toastTimer = useRef(null);
  const notify = useCallback(message => {setToast(message);clearTimeout(toastTimer.current);toastTimer.current=setTimeout(() => setToast(''),5000);},[]);
  const refresh = useCallback(async () => {
    try { const result = await api('/bootstrap'); setData({...result,challenges:result.challenges || [],teams:result.teams || [],drafts:result.drafts || []});setError(''); }
    catch(err) {setError(err.message);}
  },[]);
  useEffect(() => {refresh();},[refresh]);
  useEffect(() => {analysisJobs.resume();},[]);
  useEffect(() => {document.documentElement.lang=language;try {localStorage.setItem('sana-language',language);}catch{}},[language]);
  useEffect(() => {document.title=`${route.view === 'task' ? t('taskDetails') : t(route.view === 'editor' ? 'editor' : route.view === 'workspace' ? 'workspace' : 'catalog')} — Sana`;},[route.view,language]);
  const ownedCount = data?.challenges.filter(task => task.is_owner).length || 0;
  const common = {data,route,navigate,t,language,onUpdate:refresh,notify};
  return <div className="app-shell"><a href="#main-content" className="skip-link">{language === 'ru' ? 'К содержимому' : language === 'kk' ? 'Мазмұнға өту' : 'Skip to content'}</a><aside className="sidebar"><NavLink view="catalog" navigate={navigate} className="brand" aria-label="Sana Challenge Hub"><Mark/><span><strong translate="no">sana<span className="brand-period">.</span></strong><small>Challenge Hub</small></span></NavLink><nav aria-label={language === 'ru' ? 'Основная навигация' : language === 'kk' ? 'Негізгі навигация' : 'Main navigation'}><NavLink view="catalog" navigate={navigate} className={`nav-item ${['catalog','task'].includes(route.view)?'active':''}`} aria-current={['catalog','task'].includes(route.view)?'page':undefined}><Icon name="grid"/>{t('catalog')}</NavLink><NavLink view="editor" navigate={navigate} className={`nav-item ${route.view==='editor'?'active':''}`} aria-current={route.view==='editor'?'page':undefined}><Icon name="sparkle"/>{t('editor')}</NavLink><NavLink view="workspace" navigate={navigate} className={`nav-item ${route.view==='workspace'?'active':''}`} aria-current={route.view==='workspace'?'page':undefined}><Icon name="work"/>{t('workspace')}{ownedCount>0 && <span className="nav-count">{ownedCount}</span>}</NavLink></nav><div className="sidebar-context"><div className="context-symbol"><Icon name="users" size={20}/></div><strong>AI Sana</strong><p>{t('hub')}</p><details className="how-it-works"><summary>{t('explain')}<Icon name="chevron" size={14}/></summary><p>{t('explainText')}</p></details></div><div className="sidebar-footer"><span className="workspace-avatar">S</span><div><strong>{t('demoLabel')}</strong><small>{t('demoNote')}</small></div></div></aside><div className="main-shell"><header className="topbar"><div className="breadcrumbs"><span>Challenge Hub</span><Icon name="chevron" size={14}/><strong>{t(route.view==='editor'?'editor':route.view==='workspace'?'workspace':'catalog')}</strong></div><div className="topbar-actions"><span className={`ai-status ${!data?'checking':data.ai?.available?'connected':''}`} aria-live="polite" title={data?.ai?.model ? `${t('aiModel')}: ${data.ai.model}` : ''}><span/>{t(!data ? (error ? 'unknownAI' : 'checkingAI') : data.ai?.available ? 'liveAI' : 'noAI')}</span><div className="language-switch" role="group" aria-label="Language">{['ru','kk','en'].map(code => <button key={code} lang={code} aria-pressed={language===code} onClick={() => setLanguage(code)} className={language===code?'active':''}>{code.toUpperCase()}</button>)}</div></div></header><main id="main-content" className={`main-content view-${route.view}`}>{!data ? error ? <EmptyState icon="alert" title={t('loadError')} action={<button className="button primary" onClick={refresh}><Icon name="refresh" size={17}/>{t('retry')}</button>}>{t('loadErrorHint')}<span className="connection-error">{error}</span></EmptyState> : <Loading t={t}/> : route.view==='editor' ? <Editor {...common} drafts={data.drafts}/> : route.view==='workspace' ? <Workspace {...common}/> : route.view==='task' ? <TaskDetail key={route.id} {...common} id={route.id}/> : <Catalog {...common}/>}</main><footer className="main-footer"><span translate="no">sana. <span>Challenge Hub</span></span><span>AI Sana · HackAlem</span></footer></div><div className={`toast ${toast?'visible':''}`} role="status" aria-live="polite">{toast && <><Icon name="checkCircle" size={20}/><span>{toast}</span><button className="icon-button" aria-label={t('close')} onClick={() => setToast('')}><Icon name="close" size={16}/></button></>}</div></div>;
}
