import { html, useState, useEffect, useRef, useMemo } from '../ui/html.js';
import { Button, Icon, Progress, Callout, Cover, Spinner, Pill, EmptyState } from '../ui/core.js';
import { Field, Select, Segmented, NumberInput } from '../ui/forms.js';
import { Tabs, Disclosure } from '../ui/layout.js';
import { Menu, Dialog, toast } from '../ui/overlays.js';
import { JobStatusPill, primaryAction, menuItems, langPair, phaseLabel, jobActions, ChangeModelDialog, AddChaptersDialog, QueuePausedNotice } from '../ui/jobs.js';
import { NotesView, NotesEditor, NormalizationPreview } from '../ui/notes-editor.js';
import { jobsById, upsertJob, jobsLoaded } from '../lib/stores.js';
import { jobsApi, jobNotesApi } from '../lib/api.js';
import { onSocket } from '../lib/socket.js';
import { navigate, route } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { formatDuration, formatCost, formatNumber, formatDate } from '../lib/format.js';

const TABS = ['progress', 'passages', 'notes', 'log'];

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

function Stat({ label, value }) {
  return html`<div class="stat"><span class="stat__label">${label}</span><span class="stat__value">${value}</span></div>`;
}

function PassagePair({ preview, job }) {
  if (!preview) return html`<p class="muted small">${t('job.live.waiting')}</p>`;
  return html`<div class="stack" style="--gap:8px">
    <div class="small muted">${t('job.live.passage', { n: formatNumber((preview.unit ?? 0) + 1) })}</div>
    <div class="passage">
      <div class="passage__col"><div class="passage__lang">${job.source_language || t('job.live.original')}</div><div class="passage__text">${preview.source}</div></div>
      <div class="passage__col"><div class="passage__lang">${job.target_language}</div><div class="passage__text">${preview.translation}</div></div>
    </div>
  </div>`;
}

function SettingsUsed({ config, job }) {
  if (!config) return null;
  const notes = config.notes || {};
  const rows = [
    [t('job.used.source_file'), job.input_filename],
    [t('job.used.output_file'), config.output_path || job.output_filename],
    [t('job.used.languages'), langPair(job)],
    [t('job.used.model'), `${job.connection_name || ''} · ${job.model}`],
    [t('reasoning.label'), t(`reasoning.${job.reasoning || 'off'}`)],
    [t('job.used.task'), job.task === 'polish' ? t('new.task.polish') : job.polish_after ? t('job.used.translate_polish') : t('new.task.translate')],
    [t('new.notes.title'), job.notes_name ? html`<a href=${`#/notes/${encodeURIComponent(job.notes_name)}`}>${job.notes_name}</a>` : t('new.notes.off')],
    notes.update_interval && [t('new.notes.interval'), formatNumber(notes.update_interval)],
    [t('new.glossary.label'), config.glossary_name || (config.glossary_id ? `#${config.glossary_id}` : t('common.none'))],
    [t('new.style.label'), config.style || t('common.none')],
    [t('new.output.formatting'), config.simplify_formatting ? t('new.output.simplify') : t('new.output.keep')],
    [t('new.output.bilingual'), config.bilingual ? t('common.yes') : t('common.no')],
    [t('new.files.ocr'), config.ocr_cleanup ? t('common.yes') : t('common.no')],
    [t('new.advanced.passage'), formatNumber(config.passage_tokens || 0)],
    [t('connection.field.parallel'), formatNumber(config.parallel_requests || 1)],
    [t('job.used.created'), job.created_at && formatDate(job.created_at, { dateStyle: 'medium', timeStyle: 'short' })],
    [t('job.used.id'), html`<span class="mono small">${job.id}</span>`],
  ].filter(Boolean);
  return html`<dl class="dl">${rows.map(([k, v]) => html`<dt>${k}</dt><dd>${v || '—'}</dd>`)}</dl>`;
}

function ProgressTab({ job, detail, preview }) {
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
        <span class="phase__label">${done ? t('job.phase.done') : job.status === 'queued' ? t('job.status.queued') : phaseLabel(job)}${unitsLine && html` <span class="muted" style="font-weight:500">— ${unitsLine}</span>`}</span>
        <span class="phase__pct">${formatNumber(Math.round(job.percent || 0))}%</span>
      </div>
      <${Progress} size="lg" value=${job.percent} tone=${done ? 'success' : job.status === 'failed' ? 'danger' : undefined}
        indeterminate=${running && !job.units_total} label=${t('job.progress_label')} />
      <div class="stat-row">
        <${Stat} label=${t('job.stat.elapsed')} value=${job.elapsed_seconds ? formatDuration(job.elapsed_seconds) : '—'} />
        ${!done && html`<${Stat} label=${t('job.stat.remaining')} value=${job.eta_seconds ? formatDuration(job.eta_seconds) : '—'} />`}
        <${Stat} label=${t('job.stat.cost')} value=${job.cost_usd != null ? formatCost(job.cost_usd) : t('job.stat.cost_unknown')} />
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

    ${job.status !== 'queued' && html`<section class="stack" style="--gap:10px">
      <h2>${done ? t('job.live.last') : t('job.live.title')}</h2>
      <${PassagePair} preview=${preview || (detail && detail.latest_preview)} job=${job} />
    </section>`}

    <${Disclosure} title=${t('job.used.title')}>
      <${SettingsUsed} config=${detail && detail.config} job=${job} />
    <//>
  </div>`;
}

// ---------------------------------------------------------------- passages

function PassagesTab({ job }) {
  const PAGE = 40;
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { const h = setTimeout(() => { setQuery(q.trim()); setOffset(0); }, 300); return () => clearTimeout(h); }, [q]);
  useEffect(() => {
    let alive = true;
    jobsApi.passages(job.id, { offset, limit: PAGE, q: query || undefined })
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(e); });
    return () => { alive = false; };
  }, [job.id, offset, query, job.units_done]);
  const total = (data && data.total) || 0;
  return html`<div class="stack" style="--gap:16px">
    <div class="toolbar" style="margin:0">
      <div class="input-affix toolbar__search" style="width:320px">
        <${Icon} name="search" size="sm" />
        <input class="input" type="search" placeholder=${t('job.passages.search')} aria-label=${t('job.passages.search')} value=${q} onInput=${(e) => setQ(e.currentTarget.value)} />
      </div>
      <span class="small muted">${data ? t('job.passages.count', { count: total, n: formatNumber(total) }) : ''}</span>
    </div>
    ${error && html`<${Callout} tone="danger">${error.message}<//>`}
    ${data && !data.items.length && html`<p class="muted">${query ? t('job.passages.no_match') : t('job.passages.none_yet')}</p>`}
    ${data && data.items.map((p) => html`<div class="stack" style="--gap:6px" key=${p.index}>
      <div class="row small muted">
        <span class="strong">${t('job.live.passage', { n: formatNumber(p.index + 1) })}</span>
        ${p.status && p.status !== 'completed' && html`<${Pill} tone=${p.status === 'failed' ? 'danger' : 'warning'}>${t(`job.passages.status.${p.status}`)}<//>`}
        ${job.notes_name && html`<a href=${`#/job/${encodeURIComponent(job.id)}/notes?at=${p.index}`} class="small">${t('job.passages.notes_here')}</a>`}
      </div>
      <div class="passage">
        <div class="passage__col"><div class="passage__text" style="font-size:15px">${p.source}</div></div>
        <div class="passage__col"><div class="passage__text" style="font-size:15px">${p.translation || html`<span class="faint">${t('job.passages.not_yet')}</span>`}</div></div>
      </div>
    </div>`)}
    ${total > PAGE && html`<div class="row row--between">
      <${Button} icon="chevron-left" disabled=${offset === 0} onClick=${() => setOffset(Math.max(0, offset - PAGE))}>${t('common.previous')}<//>
      <span class="small muted">${t('job.passages.range', { from: formatNumber(offset + 1), to: formatNumber(Math.min(total, offset + PAGE)), total: formatNumber(total) })}</span>
      <${Button} iconRight="chevron-right" disabled=${offset + PAGE >= total} onClick=${() => setOffset(offset + PAGE)}>${t('common.next')}<//>
    </div>`}
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
    ${view === 'latest' && html`<p class="small muted">${t('job.notes.latest_help')}</p>`}
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
  const [preview, setPreview] = useState(null);
  const [dialog, setDialog] = useState(null);
  useEffect(() => onSocket('job_update', (msg) => {
    if (msg && msg.preview && msg.job && msg.job.id === id) setPreview(msg.preview);
  }), [id]);
  useEffect(() => { setPreview(null); }, [id]);

  if (!job) {
    if (error && error.status === 404) {
      return html`<div class="page"><${EmptyState} icon="circle-alert" title=${t('job.not_found')}
        actions=${html`<${Button} href="#/translations">${t('shell.back_home')}<//>`} /></div>`;
    }
    return html`<div class="page"><p class="muted">${jobsLoaded.value ? t('common.loading') : t('common.loading')}</p></div>`;
  }

  const current = TABS.includes(tab) ? tab : 'progress';
  const action = primaryAction(job);
  const tabs = [
    { id: 'progress', label: t('job.tab.progress'), href: `#/job/${encodeURIComponent(id)}` },
    { id: 'passages', label: t('job.tab.passages'), href: `#/job/${encodeURIComponent(id)}/passages` },
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
    ${current === 'progress' && html`<${ProgressTab} job=${job} detail=${detail} preview=${preview} />`}
    ${current === 'passages' && html`<${PassagesTab} job=${job} />`}
    ${current === 'notes' && html`<${NotesTab} job=${job} detail=${detail} />`}
    ${current === 'log' && html`<${LogTab} job=${job} />`}
    ${dialog === 'model' && html`<${ChangeModelDialog} job=${job} onClose=${() => setDialog(null)} />`}
    ${dialog === 'chapters' && html`<${AddChaptersDialog} job=${job} onClose=${() => setDialog(null)} />`}
  </div>`;
}
