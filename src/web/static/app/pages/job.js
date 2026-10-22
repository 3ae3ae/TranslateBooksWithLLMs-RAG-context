import { html, useState, useEffect, useRef, useMemo, cx } from '../ui/html.js';
import { Button, Icon, IconButton, Progress, Callout, Cover, Spinner, Pill, EmptyState } from '../ui/core.js';
import { Field, Select, Segmented, NumberInput } from '../ui/forms.js';
import { Tabs, Disclosure } from '../ui/layout.js';
import { Menu, Dialog, toast } from '../ui/overlays.js';
import { JobStatusPill, primaryAction, menuItems, langPair, phaseLabel, statusInfo, jobActions, ChangeModelDialog, AddChaptersDialog, QueuePausedNotice } from '../ui/jobs.js';
import { NotesView, NotesEditor, NormalizationPreview } from '../ui/notes-editor.js';
import { jobsById, upsertJob, jobsLoaded, connections } from '../lib/stores.js';
import { jobsApi, jobNotesApi } from '../lib/api.js';
import { onSocket } from '../lib/socket.js';
import { navigate, route } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { formatDuration, formatCost, formatNumber, formatDate } from '../lib/format.js';

const TABS = ['review', 'notes', 'log'];

function useJobDetail(id) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const load = () => jobsApi.get(id).then((d) => { setDetail(d); upsertJob(d); setError(null); }).catch(setError);
  useEffect(() => { setDetail(null); load(); }, [id]);
  return { detail, error, reload: load };
}

function useCountdown(iso) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!iso) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [iso]);
  return iso ? Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000)) : null;
}

// ---------------------------------------------------------------- progress

/** Same billing rule as the estimate: local models and Ollama plans have no per-request price. */
function costLabel(job) {
  if (job.cost_usd != null) return formatCost(job.cost_usd);
  const conn = connections.value.find((c) => c.id === job.connection_id);
  if (conn && conn.type === 'ollama_cloud') return t('new.summary.plan_billing');
  return conn && conn.local ? t('new.summary.no_api_cost') : t('job.stat.cost_unknown');
}

function Stat({ label, value }) {
  return html`<div class="stat"><span class="stat__label">${label}</span><span class="stat__value">${value}</span></div>`;
}

function SettingsUsed({ config, job }) {
  if (!config) return null;
  const rows = [
    [t('job.used.source_file'), job.input_filename],
    [t('job.used.output_file'), config.output_path || job.output_filename],
    [t('job.used.languages'), langPair(job)],
    [t('job.used.model'), `${job.connection_name || ''} · ${job.model}`],
    [t('reasoning.label'), t(`reasoning.${job.reasoning || 'off'}`)],
    [t('job.used.task'), job.task === 'polish' ? t('new.task.polish') : job.polish_after ? t('job.used.translate_polish') : t('new.task.translate')],
    [t('new.notes.title'), job.notes_name ? html`<a href=${`#/notes/${encodeURIComponent(job.notes_name)}`}>${job.notes_name}</a>` : t('new.notes.off')],
    [t('new.style.label'), config.style || t('common.none')],
    [t('new.output.formatting'), config.simplify_formatting ? t('new.output.simplify') : t('new.output.keep')],
    [t('new.output.bilingual'), config.bilingual ? t('common.yes') : t('common.no')],
    [t('new.files.ocr'), config.ocr_cleanup ? t('common.yes') : t('common.no')],
    [t('new.advanced.passage'), formatNumber(config.passage_tokens || 0)],
    [t('job.used.created'), job.created_at && formatDate(job.created_at, { dateStyle: 'medium', timeStyle: 'short' })],
    [t('job.used.id'), html`<span class="mono small">${job.id}</span>`],
  ].filter(Boolean);
  return html`<dl class="dl">${rows.map(([k, v]) => html`<dt>${k}</dt><dd>${v || '—'}</dd>`)}</dl>`;
}

function StatusPanel({ job, detail }) {
  const countdown = useCountdown(job.status === 'waiting' ? job.resume_at : null);
  const running = job.status === 'running';
  const done = job.status === 'completed';
  const unitsLine = job.units_total
    ? t('job.units', { done: formatNumber(job.units_done || 0), total: formatNumber(job.units_total) })
    : '';
  const canRetry = ['paused', 'partial', 'failed'].includes(job.status);
  return html`<div class="stack" style="--gap:24px">
    ${done && html`<${Callout} tone="success" title=${t('job.done.title', { time: formatDuration(job.elapsed_seconds || 0) })}
        actions=${job.output_exists && html`
          <${Button} size="sm" variant="primary" icon="download" onClick=${() => jobActions.download(job)}>${t('job.action.download')}<//>
          <${Button} size="sm" icon="external-link" onClick=${() => jobActions.open(job)}>${t('job.action.open')}<//>
          <${Button} size="sm" icon="folder-open" onClick=${() => jobActions.reveal(job)}>${t('job.action.reveal')}<//>`}>
      ${job.output_filename}
    <//>`}
    ${job.status === 'queued' && html`<${QueuePausedNotice} />`}
    ${job.status === 'failed' && job.error && html`<${Callout} tone="danger" title=${t('job.failed.title')}>${job.error}<//>`}
    ${job.status === 'paused' && job.status_reason === 'connection_removed' && html`<${Callout} tone="warning" title=${t('job.paused.connection_removed')}>${t('job.paused.connection_removed_desc')}<//>`}

    <div class="card"><div class="card__body">
      <div class="phase">
        <span class="phase__label">${done ? t('job.phase.done') : job.status === 'running' ? phaseLabel(job) : statusInfo(job).label}${unitsLine && html` <span class="muted" style="font-weight:500">— ${unitsLine}</span>`}</span>
        <span class="phase__pct">${formatNumber(Math.round(job.percent || 0))}%</span>
      </div>
      <${Progress} size="lg" value=${job.percent} tone=${done ? 'success' : job.status === 'failed' ? 'danger' : undefined}
        indeterminate=${running && !job.units_total} label=${t('job.progress_label')} />
      <div class="stat-row">
        <${Stat} label=${t('job.stat.elapsed')} value=${job.elapsed_seconds ? formatDuration(job.elapsed_seconds) : '—'} />
        ${!done && html`<${Stat} label=${t('job.stat.remaining')} value=${job.eta_seconds ? formatDuration(job.eta_seconds) : '—'} />`}
        <${Stat} label=${done ? t('job.stat.cost_total') : t('job.stat.cost')} value=${costLabel(job)} />
        <${Stat} label=${t('job.stat.requests')} value=${job.requests != null ? formatNumber(job.requests) : '—'} />
      </div>
    </div></div>

    ${job.status === 'waiting' && html`<${Callout} tone="warning" title=${t('job.waiting.title')}
        actions=${html`<${Button} size="sm" icon="refresh-cw" onClick=${() => jobActions.resume(job)}>${t('job.waiting.retry_now')}<//>`}>
      ${countdown != null ? t('job.waiting.desc', { time: formatDuration(countdown) }) : t('job.waiting.desc_unknown')}
    <//>`}
    ${(job.units_untranslated > 0 || job.units_failed > 0 || job.formatting_approximated > 0) && html`<div class="stack" style="--gap:10px">
      ${job.units_untranslated > 0 && html`<${Callout} tone="warning" title=${t('job.issue.untranslated', { count: job.units_untranslated, n: formatNumber(job.units_untranslated) })}
          actions=${canRetry && html`<${Button} size="sm" variant="primary" icon="rotate-ccw" onClick=${() => jobActions.resume(job)}>${t('job.action.retry')}<//>`}>
        ${t('job.issue.untranslated_desc')}
      <//>`}
      ${job.units_failed > 0 && html`<${Callout} tone="danger" title=${t('job.issue.failed', { count: job.units_failed, n: formatNumber(job.units_failed) })}
          actions=${canRetry && html`<${Button} size="sm" variant="primary" icon="rotate-ccw" onClick=${() => jobActions.resume(job)}>${t('job.action.retry')}<//>`}>
        ${t('job.issue.failed_desc')}
      <//>`}
      ${job.formatting_approximated > 0 && html`<${Callout} tone="info" title=${t('job.issue.approximated', { count: job.formatting_approximated, n: formatNumber(job.formatting_approximated) })}>
        ${t('job.issue.approximated_desc')}
      <//>`}
    </div>`}

    <${Disclosure} title=${t('job.used.title')}>
      <${SettingsUsed} config=${detail && detail.config} job=${job} />
    <//>
  </div>`;
}

// ------------------------------------------------------------------ review

const WINDOW = 40;
const KEEP_WHILE_FOLLOWING = 150;

/** Checked and flagged passages, per job. shortcut: kept in this browser only; move to the server if reviews must follow the user. */
function useReviewMarks(jobId) {
  const storageKey = `tbl.review.${jobId}`;
  const read = () => {
    try {
      const v = JSON.parse(localStorage.getItem(storageKey) || '{}');
      return { checked: new Set(v.checked || []), flagged: new Set(v.flagged || []) };
    } catch { return { checked: new Set(), flagged: new Set() }; }
  };
  const [marks, setMarks] = useState(read);
  useEffect(() => { setMarks(read()); }, [jobId]);
  const toggle = (kind, index) => setMarks((cur) => {
    const next = { checked: new Set(cur.checked), flagged: new Set(cur.flagged) };
    if (next[kind].has(index)) next[kind].delete(index); else next[kind].add(index);
    localStorage.setItem(storageKey, JSON.stringify({ checked: [...next.checked], flagged: [...next.flagged] }));
    return next;
  });
  return [marks, toggle];
}

const nearBottom = () => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 160;
const scrollToEnd = () => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });

/** Stage badge for passages of jobs that polish each passage right after translating it. */
function StageBadge({ p, job }) {
  if (p.stage === 'draft') {
    const active = job.status === 'running' && job.phase === 'polishing' && job.current_unit === p.index;
    return html`<${Pill} tone=${active ? 'accent' : undefined} dot=${active ? 'busy' : undefined}>${t(active ? 'job.review.stage.polishing' : 'job.review.stage.waiting')}<//>`;
  }
  if (p.stage === 'polish_failed') return html`<${Pill} tone="warning" icon="triangle-alert">${t('job.review.stage.polish_failed')}<//>`;
  return null;
}

function ReviewRow({ p, job, marks, onToggle }) {
  const [showDraft, setShowDraft] = useState(false);
  const checked = marks.checked.has(p.index);
  const flagged = marks.flagged.has(p.index);
  // Text still being polished will change, so it can't be signed off yet.
  const checkable = p.stage !== 'draft';
  const canCompare = p.stage === 'polished' && p.draft && p.draft !== p.translation;
  const showingDraft = (showDraft && canCompare) || p.stage === 'polish_failed';
  const text = showingDraft ? p.draft || p.translation : p.translation;
  return html`<article id=${`passage-${p.index}`} class=${cx('review-row', checked && checkable && 'review-row--checked', flagged && 'review-row--flagged')}>
    <header class="review-row__head">
      <span class="review-row__num">${t('job.live.passage', { n: formatNumber(p.index + 1) })}</span>
      ${p.stage ? html`<${StageBadge} p=${p} job=${job} />`
        : p.status && p.status !== 'completed' && html`<${Pill} tone=${p.status === 'failed' ? 'danger' : 'warning'}>${t(`job.passages.status.${p.status}`)}<//>`}
      <span class="grow" />
      ${canCompare && html`<${Button} variant="link" size="sm" icon=${showDraft ? 'eye-off' : 'eye'} aria-pressed=${String(showDraft)}
        onClick=${() => setShowDraft(!showDraft)}>${showDraft ? t('job.review.show_polished') : t('job.review.show_draft')}<//>`}
      ${job.notes_name && html`<a class="small" href=${`#/job/${encodeURIComponent(job.id)}/notes?at=${p.index}`}>${t('job.passages.notes_here')}</a>`}
      <${IconButton} size="sm" icon="flag" label=${t('job.review.flag')} pressed=${flagged} onClick=${() => onToggle('flagged', p.index)} />
      <${IconButton} size="sm" icon="check" label=${checkable ? t('job.review.check') : t('job.review.check_after_polish')} pressed=${checked && checkable}
        disabled=${!checkable} onClick=${() => onToggle('checked', p.index)} />
    </header>
    <div class="passage passage--review">
      <div class="passage__col"><div class="passage__text">${p.source}</div></div>
      <div class=${cx('passage__col', showingDraft && 'passage__col--draft')}>
        ${showingDraft && html`<div class="passage__lang">${t('job.review.draft_label')}</div>`}
        <div class="passage__text">${text || html`<span class="faint">${t('job.passages.not_yet')}</span>`}</div>
      </div>
    </div>
  </article>`;
}

/**
 * Every finished passage, source next to translation, growing as the job runs.
 * Sticks to the newest passage only while the reader is at the bottom, like a chat.
 */
function ReviewStream({ job }) {
  const [marks, toggle] = useReviewMarks(job.id);
  const [items, setItems] = useState([]);
  const [start, setStart] = useState(null); // offset of items[0] among finished passages
  const [total, setTotal] = useState(0);
  const [fresh, setFresh] = useState(0);
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const running = job.status === 'running';

  // Open on the newest passages while translating, at the beginning once finished.
  useEffect(() => {
    let alive = true;
    const first = running ? Math.max(0, (job.units_done || 0) - WINDOW / 2) : 0;
    jobsApi.passages(job.id, { offset: first, limit: WINDOW })
      .then((d) => { if (alive) { setItems(d.items); setStart(first); setTotal(d.total); setError(null); } })
      .catch((e) => { if (alive) setError(e); });
    return () => { alive = false; };
  }, [job.id]);

  // A passage finished (or was polished or retried): refresh the window and extend it to the end.
  useEffect(() => {
    if (start === null) return undefined;
    let alive = true;
    const following = nearBottom();
    const from = following && items.length > KEEP_WHILE_FOLLOWING * 1.5 ? start + items.length - KEEP_WHILE_FOLLOWING : start;
    jobsApi.passages(job.id, { offset: from, limit: Math.min(500, start + items.length - from + WINDOW) }).then((d) => {
      if (!alive) return;
      const added = d.total - total;
      setItems(d.items); setStart(from); setTotal(d.total);
      if (added > 0 && total > 0) {
        if (following) requestAnimationFrame(scrollToEnd);
        else setFresh((n) => n + added);
      }
    }).catch(() => {});
    return () => { alive = false; };
  }, [job.units_done, job.status, job.phase, job.passages_revision]);

  useEffect(() => {
    const onScroll = () => { if (nearBottom()) setFresh(0); };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => { const h = setTimeout(() => setQuery(q.trim()), 300); return () => clearTimeout(h); }, [q]);
  useEffect(() => {
    if (!query) { setResults(null); return undefined; }
    let alive = true;
    jobsApi.passages(job.id, { q: query, limit: 200 })
      .then((d) => { if (alive) setResults(d); })
      .catch((e) => { if (alive) setError(e); });
    return () => { alive = false; };
  }, [query, job.id, job.passages_revision]);

  const loadEarlier = async () => {
    const from = Math.max(0, start - WINDOW);
    const d = await jobsApi.passages(job.id, { offset: from, limit: start - from });
    const height = document.documentElement.scrollHeight;
    setItems((cur) => [...d.items, ...cur]);
    setStart(from);
    // Keep the passage the reader was looking at in place.
    requestAnimationFrame(() => window.scrollBy(0, document.documentElement.scrollHeight - height));
  };

  const jumpTo = async (index) => {
    if (q) setQ('');
    if (!items.some((p) => p.index === index)) {
      const from = Math.max(0, index - 5);
      const d = await jobsApi.passages(job.id, { offset: from, limit: WINDOW });
      setItems(d.items); setStart(from); setTotal(d.total);
    }
    requestAnimationFrame(() => {
      const el = document.getElementById(`passage-${index}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  };

  const flagged = [...marks.flagged].sort((a, b) => a - b);
  const atEnd = start !== null && start + items.length >= total;
  const rows = results ? results.items : items;

  return html`<section class="review" aria-label=${t('job.review.title')}>
    <div class="review-bar">
      <div class="input-affix review-bar__search">
        <${Icon} name="search" size="sm" />
        <input class="input" type="search" placeholder=${t('job.passages.search')} aria-label=${t('job.passages.search')}
          value=${q} onInput=${(e) => setQ(e.currentTarget.value)} />
      </div>
      <span class="small muted num">${t('job.review.checked', { n: formatNumber(marks.checked.size), total: formatNumber(total) })}</span>
      <span class="grow" />
      ${running && job.units_total > 0 && html`<span class="small muted num">
        ${t('job.units', { done: formatNumber(job.units_done || 0), total: formatNumber(job.units_total) })}${job.eta_seconds ? ` · ${t('job.eta', { time: formatDuration(job.eta_seconds) })}` : ''}
      </span>`}
      ${flagged.length > 0 && html`<${Menu} icon="flag" label=${t('job.review.flagged_list', { count: flagged.length, n: formatNumber(flagged.length) })}
        items=${flagged.map((i) => ({ label: t('job.live.passage', { n: formatNumber(i + 1) }), icon: 'flag', onSelect: () => jumpTo(i) }))} />`}
      ${flagged.length > 0 && html`<span class="small muted num">${t('job.review.flagged_list', { count: flagged.length, n: formatNumber(flagged.length) })}</span>`}
    </div>
    ${error && html`<${Callout} tone="danger">${error.message}<//>`}
    ${results && html`<p class="small muted">${t('job.passages.count', { count: results.total, n: formatNumber(results.total) })}</p>`}
    ${!results && start > 0 && html`<${Button} block icon="chevron-up" onClick=${loadEarlier}>${t('job.review.load_earlier', { n: formatNumber(start) })}<//>`}
    ${rows.length === 0 && !running && html`<p class="muted">${results ? t('job.passages.no_match') : t('job.review.empty')}</p>`}
    ${rows.map((p) => html`<${ReviewRow} key=${p.index} p=${p} job=${job} marks=${marks} onToggle=${toggle} />`)}
    ${!results && running && atEnd && job.phase !== 'polishing' && html`<div class="review-row review-row--pending" role="status">
      <${Spinner} size="sm" />${t(job.phase === 'notes' ? 'job.review.notes' : 'job.review.translating', { n: formatNumber((job.current_unit ?? job.units_done ?? 0) + 1) })}
    </div>`}
    ${!results && fresh > 0 && html`<button type="button" class="jump-pill" onClick=${() => { setFresh(0); scrollToEnd(); }}>
      <${Icon} name="arrow-down" size="sm" />${t('job.review.new_below', { count: fresh, n: formatNumber(fresh) })}
    </button>`}
  </section>`;
}

function ReviewTab({ job, detail }) {
  return html`<div class="stack" style="--gap:24px">
    <${StatusPanel} job=${job} detail=${detail} />
    ${job.status !== 'queued' && html`<${ReviewStream} job=${job} />`}
  </div>`;
}

// ------------------------------------------------------------------- notes

function RebuildDialog({ job, check, onConfirm, onClose, busy }) {
  const finished = ['completed', 'partial'].includes(job.status);
  const running = job.status === 'running';
  let body;
  if (running || check.will_pause_running_job) {
    body = t('job.rebuild.running', { count: check.estimated_requests, n: formatNumber(check.estimated_requests || 0) });
  } else if (finished && job.polish_after) {
    body = t('job.rebuild.finished_polish', { n: formatNumber(check.estimated_requests || 0), p: formatNumber(check.polish_requests || 0) });
  } else if (finished) {
    body = t('job.rebuild.finished_translate', { n: formatNumber(check.estimated_requests || 0) });
  } else {
    body = t('job.rebuild.paused', { n: formatNumber(check.estimated_requests || 0) });
  }
  const offerPolish = finished && !job.polish_after;
  return html`<${Dialog} title=${t('job.rebuild.title', { n: formatNumber((check.index ?? 0) + 1) })} size="wide" onClose=${onClose}
    footer=${html`
      <${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>
      ${offerPolish
        ? html`<${Button} loading=${busy === 'notes'} onClick=${() => onConfirm(false)}>${t('job.rebuild.notes_only')}<//>
            <${Button} variant="primary" loading=${busy === 'polish'} onClick=${() => onConfirm(true)}>${t('job.rebuild.and_polish', { n: formatNumber(check.polish_requests || job.units_total || 0) })}<//>`
        : html`<${Button} variant="primary" loading=${!!busy} onClick=${() => onConfirm(false)}>${t('job.rebuild.confirm')}<//>`}`}>
    <div class="stack">
      <p>${body}</p>
      <p class="small muted">${t('job.rebuild.kept')}</p>
      <${NormalizationPreview} result=${check} original=${check.original} />
    </div>
  <//>`;
}

function NotesTab({ job, detail }) {
  const at = route.value.query.at;
  const [view, setView] = useState(at != null ? 'passage' : 'latest');
  const [index, setIndex] = useState(at != null ? Number(at) : null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const snapshots = (data && data.snapshot_indices) || (detail && detail.notes_snapshots) || [];

  const load = () => {
    const idx = view === 'latest' ? 'latest' : view === 'book' ? (snapshots[0] ?? 0) : index;
    if (idx === null || idx === undefined) return;
    setError(null);
    jobNotesApi.snapshot(job.id, idx, view === 'book' ? 'global_lore' : undefined)
      .then(setData).catch(setError);
  };
  useEffect(load, [job.id, view, index]);
  useEffect(() => { if (view === 'passage' && index === null && snapshots.length) setIndex(snapshots[snapshots.length - 1]); }, [view, snapshots.length]);

  const rebuild = job.notes_rebuild;
  const canEdit = view !== 'latest' && data && !(rebuild && ['running', 'pause_requested'].includes(rebuild.status));

  const startSave = async () => {
    setBusy(true);
    try {
      const idx = view === 'book' ? (snapshots[0] ?? 0) : index;
      const r = await jobNotesApi.resync(job.id, idx, { sections: editing, scope: view === 'book' ? 'global_lore' : undefined, dry_run: true });
      setCheck({ ...r, index: idx, original: data.sections });
    } catch (e) {
      toast({ tone: 'error', title: t('errors.action_failed'), message: e.message });
    } finally {
      setBusy(false);
    }
  };
  const confirmSave = async (polish) => {
    setBusy(polish ? 'polish' : 'notes');
    try {
      const r = await jobNotesApi.resync(job.id, check.index, { sections: editing, scope: view === 'book' ? 'global_lore' : undefined, polish });
      if (r && r.job) upsertJob(r.job);
      toast({ tone: 'success', title: t('job.rebuild.started') });
      setCheck(null);
      setEditing(null);
      load();
    } catch (e) {
      toast({ tone: 'error', title: t('errors.action_failed'), message: e.message });
    } finally {
      setBusy(false);
    }
  };

  return html`<div class="stack" style="--gap:16px">
    <div class="row row--wrap row--between">
      <div class="row row--wrap">
        <${Segmented} label=${t('job.notes.as_of')} value=${view} onChange=${(v) => { setEditing(null); setView(v); }} options=${[
          { value: 'latest', label: t('job.notes.latest') },
          { value: 'book', label: t('job.notes.book') },
          { value: 'passage', label: t('job.notes.passage'), disabled: !snapshots.length },
        ]} />
        ${view === 'passage' && snapshots.length > 0 && html`<${Select} value=${index ?? ''} onChange=${(v) => setIndex(Number(v))}
          aria-label=${t('job.notes.pick_passage')}
          options=${snapshots.map((i) => ({ value: i, label: t('job.live.passage', { n: formatNumber(i + 1) }) }))} />`}
      </div>
      <div class="row">
        ${rebuild && rebuild.status && rebuild.status !== 'completed' && html`<span class="row small muted">
          ${rebuild.status === 'running' && html`<${Spinner} size="sm" />`}
          ${t(`job.rebuild.status.${rebuild.status}`, { done: formatNumber(rebuild.done || 0), total: formatNumber(rebuild.total || 0) })}
        </span>`}
        ${rebuild && rebuild.status === 'running' && html`<${Button} size="sm" icon="pause" onClick=${() => jobNotesApi.pauseResync(job.id).catch(() => {})}>${t('job.rebuild.pause')}<//>`}
        ${rebuild && rebuild.status === 'paused' && html`<${Button} size="sm" icon="play" onClick=${() => jobNotesApi.resumeResync(job.id).catch(() => {})}>${t('job.rebuild.resume')}<//>`}
        ${!editing && canEdit && html`<${Button} size="sm" icon="pencil" onClick=${() => setEditing(data.sections.map((s) => ({ ...s })))}>${t('common.edit')}<//>`}
      </div>
    </div>
    <p class="small muted">${t(view === 'book' ? 'job.notes.book_help' : view === 'passage' ? 'job.notes.passage_help' : 'job.notes.latest_help')}</p>
    ${error && html`<${Callout} tone="danger">${error.message}<//>`}
    ${!data && !error && html`<p class="muted">${t('common.loading')}</p>`}
    ${data && !editing && html`<${NotesView} sections=${data.sections} emptyText=${t('job.notes.empty')} />`}
    ${editing && html`<div class="stack">
      <${NotesEditor} sections=${editing} onChange=${setEditing} />
      <div class="row">
        <${Button} variant="primary" loading=${busy === true} onClick=${startSave}>${t('job.notes.review_save')}<//>
        <${Button} variant="ghost" onClick=${() => setEditing(null)}>${t('common.cancel')}<//>
      </div>
    </div>`}
    ${check && html`<${RebuildDialog} job=${job} check=${check} busy=${busy} onConfirm=${confirmSave} onClose=${() => setCheck(null)} />`}
  </div>`;
}

// --------------------------------------------------------------------- log

function LogTab({ job }) {
  const [entries, setEntries] = useState(null);
  const [level, setLevel] = useState('info');
  const [follow, setFollow] = useState(true);
  const boxRef = useRef(null);
  useEffect(() => {
    jobsApi.log(job.id, 1000).then((r) => setEntries(r.items || [])).catch(() => setEntries([]));
    return onSocket('job_update', (msg) => {
      if (msg && msg.log_entry && msg.job && msg.job.id === job.id) setEntries((cur) => [...(cur || []), msg.log_entry].slice(-3000));
    });
  }, [job.id]);
  useEffect(() => { if (follow && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight; }, [entries, follow, level]);
  const rank = { debug: 0, info: 1, warning: 2, error: 3 };
  const min = level === 'all' ? 0 : rank[level];
  const shown = (entries || []).filter((e) => (rank[(e.level || 'info').toLowerCase()] ?? 1) >= min);
  const copy = () => {
    const text = shown.map((e) => `${e.timestamp || ''} ${(e.level || '').toUpperCase()} ${e.message}`).join('\n');
    navigator.clipboard.writeText(text).then(() => toast({ tone: 'success', title: t('job.log.copied') }));
  };
  return html`<div class="stack" style="--gap:12px">
    <div class="row row--wrap row--between">
      <${Segmented} label=${t('job.log.level')} value=${level} onChange=${setLevel} options=${[
        { value: 'info', label: t('job.log.info') },
        { value: 'warning', label: t('job.log.warnings') },
        { value: 'error', label: t('job.log.errors') },
        { value: 'all', label: t('job.log.all') },
      ]} />
      <div class="row">
        <label class="checkbox small"><input type="checkbox" checked=${follow} onChange=${(e) => setFollow(e.currentTarget.checked)} />${t('job.log.follow')}</label>
        <${Button} size="sm" icon="copy" onClick=${copy} disabled=${!shown.length}>${t('common.copy')}<//>
      </div>
    </div>
    ${entries === null ? html`<p class="muted">${t('common.loading')}</p>` : html`<div class="log" ref=${boxRef} role="log" aria-live="off">
      ${shown.length === 0 && html`<div class="log__line"><span /><span /><span class="log__msg faint">${t('job.log.empty')}</span></div>`}
      ${shown.map((e) => {
        const lv = (e.level || 'info').toLowerCase();
        const time = e.timestamp ? String(e.timestamp).replace(/^.*T/, '').slice(0, 8) : '';
        return html`<div class=${`log__line log__line--${lv}`}>
          <span class="log__time">${time}</span>
          <span>${lv === 'error' ? '✕' : lv === 'warning' ? '!' : ''}</span>
          <span class="log__msg">${e.message}</span>
        </div>`;
      })}
    </div>`}
  </div>`;
}

// -------------------------------------------------------------------- page

export function JobPage({ id, tab }) {
  const job = jobsById.value[id];
  const { detail, error } = useJobDetail(id);
  const [dialog, setDialog] = useState(null);

  if (!job) {
    if (error && error.status === 404) {
      return html`<div class="page"><${EmptyState} icon="circle-alert" title=${t('job.not_found')}
        actions=${html`<${Button} href="#/translations">${t('shell.back_home')}<//>`} /></div>`;
    }
    return html`<div class="page"><p class="muted">${jobsLoaded.value ? t('common.loading') : t('common.loading')}</p></div>`;
  }

  const current = TABS.includes(tab) ? tab : 'review';
  const action = primaryAction(job);
  const tabs = [
    { id: 'review', label: t('job.tab.review'), href: `#/job/${encodeURIComponent(id)}` },
    job.notes_name && { id: 'notes', label: t('job.tab.notes'), href: `#/job/${encodeURIComponent(id)}/notes` },
    { id: 'log', label: t('job.tab.log'), href: `#/job/${encodeURIComponent(id)}/log` },
  ].filter(Boolean);

  return html`<div class="page">
    <a class="page__back" href="#/translations"><${Icon} name="arrow-left" size="sm" />${t('nav.translations')}</a>
    <header class="job-head">
      <${Cover} src=${job.has_cover ? jobsApi.coverPath(job.id) : null} format=${job.file_type} size="lg" />
      <div class="job-head__titles">
        <h1 class="truncate">${job.title}</h1>
        <div class="job-head__meta">
          <${JobStatusPill} job=${job} />
          <span>${langPair(job)}</span>
          <span>${job.model}${job.reasoning && job.reasoning !== 'off' ? ` · ${t(`reasoning.${job.reasoning}`)}` : ''}</span>
        </div>
      </div>
      <div class="job-head__actions">
        ${action && html`<${Button} variant=${action.variant || 'secondary'} icon=${action.icon} onClick=${action.run}>${action.label}<//>`}
        <${Menu} items=${menuItems(job, {
          onChangeModel: () => setDialog('model'),
          onAddChapters: () => setDialog('chapters'),
          thenNavigate: true,
        })} />
      </div>
    </header>
    <${Tabs} label=${t('job.tabs_label')} current=${current} items=${tabs} />
    ${current === 'review' && html`<${ReviewTab} job=${job} detail=${detail} />`}
    ${current === 'notes' && html`<${NotesTab} job=${job} detail=${detail} />`}
    ${current === 'log' && html`<${LogTab} job=${job} />`}
    ${dialog === 'model' && html`<${ChangeModelDialog} job=${job} onClose=${() => setDialog(null)} />`}
    ${dialog === 'chapters' && html`<${AddChaptersDialog} job=${job} onClose=${() => setDialog(null)} />`}
  </div>`;
}
