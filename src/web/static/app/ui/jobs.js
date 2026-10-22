import { html, useState } from './html.js';
import { Pill, Button, Callout } from './core.js';
import { Dialog, confirm, toast } from './overlays.js';
import { Field } from './forms.js';
import { Dropzone } from './layout.js';
import { ModelPicker, ReasoningControl } from './model-picker.js';
import { jobsApi, uploadsApi, queueApi } from '../lib/api.js';
import { downloadUrl } from '../lib/api-core.js';
import { upsertJob, dropJob, jobsById, loadJobs, queueState } from '../lib/stores.js';
import { navigate } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { formatDuration, formatRelativeTime, formatCost, formatNumber } from '../lib/format.js';

export const isUnfinished = (j) => j.status !== 'completed';

export function langPair(job) {
  const src = job.source_language || t('lang.auto');
  return job.task === 'polish' ? job.target_language : `${src} → ${job.target_language}`;
}

export function phaseLabel(job) {
  if (job.phase === 'polishing') return t('job.phase.polishing');
  if (job.phase === 'notes') return t('job.phase.notes');
  return t('job.phase.translating');
}

export function statusInfo(job) {
  switch (job.status) {
    case 'running': return { tone: 'accent', dot: 'busy', label: phaseLabel(job) };
    case 'queued': return { tone: undefined, icon: 'clock', label: job.queue_position ? t('job.status.queued_n', { n: job.queue_position }) : t('job.status.queued') };
    case 'waiting': return { tone: 'warning', icon: 'clock', label: t('job.status.waiting') };
    case 'paused': return { tone: 'warning', icon: 'pause', label: t(`job.status.paused_${job.status_reason || 'user'}`, {}) };
    case 'partial': return { tone: 'warning', icon: 'triangle-alert', label: t('job.status.partial') };
    case 'failed': return { tone: 'danger', icon: 'circle-alert', label: t('job.status.failed') };
    case 'completed': return { tone: 'success', icon: 'circle-check', label: t('job.status.completed') };
    default: return { label: job.status };
  }
}

export function JobStatusPill({ job }) {
  const s = statusInfo(job);
  return html`<${Pill} tone=${s.tone} icon=${s.icon} dot=${s.dot}>${s.label}<//>`;
}

/** One-line facts about a finished or stopped job. */
export function jobFacts(job) {
  const parts = [];
  if (job.units_total) parts.push(t('job.facts.passages', { count: job.units_total, n: formatNumber(job.units_total) }));
  if (job.elapsed_seconds) parts.push(formatDuration(job.elapsed_seconds));
  if (job.cost_usd != null && job.cost_usd > 0) parts.push(formatCost(job.cost_usd));
  const when = job.finished_at || job.updated_at;
  if (when) parts.push(formatRelativeTime(when));
  return parts;
}

// ---------------------------------------------------------------- actions

async function act(fn, successMsg) {
  try {
    const r = await fn();
    if (r && r.job) upsertJob(r.job);
    if (successMsg) toast({ tone: 'success', title: successMsg(r) });
    return r;
  } catch (e) {
    toast({ tone: 'error', title: t('errors.action_failed'), message: e.message });
    return null;
  }
}

export const jobActions = {
  pause: (job) => act(() => jobsApi.pause(job.id)),
  resume: (job, overrides) => act(() => jobsApi.resume(job.id, overrides), () => {
    // A resumed job is briefly "queued" even when it starts right away; only mention the queue if something else runs.
    const q = queueState.value;
    if (q.paused && q.reason !== 'restart') return t('job.toast.resume_held');
    const busy = Object.values(jobsById.value).some((j) => j.status === 'running' && j.id !== job.id);
    return busy ? t('job.toast.resume_queued') : t('job.toast.resumed');
  }),
  move: (job, to) => act(() => jobsApi.move(job.id, to)),
  removeFromQueue: async (job) => {
    const ok = await confirm({ title: t('job.confirm.remove_queue_title'), body: t('job.confirm.remove_queue_body', { title: job.title }), confirmLabel: t('job.action.remove_from_queue'), danger: true });
    if (ok) await act(() => jobsApi.removeFromQueue(job.id));
  },
  download: async (job) => {
    try { await downloadUrl(jobsApi.downloadPath(job.output_filename)); }
    catch (e) { toast({ tone: 'error', title: t('errors.download_failed'), message: e.message }); }
  },
  open: (job) => act(() => jobsApi.open(job.id)),
  reveal: (job) => act(() => jobsApi.reveal(job.id)),
  remove: async (job, { thenNavigate } = {}) => {
    const r = await confirm({
      title: t('job.confirm.delete_title'),
      body: html`<div class="stack"><p class="muted">${t('job.confirm.delete_body', { title: job.title })}</p><p class="muted small">${t('job.confirm.delete_keeps')}</p></div>`,
      confirmLabel: t('job.action.delete'),
      danger: true,
      checkbox: job.output_exists ? { label: t('job.confirm.delete_output'), default: false } : null,
    });
    if (!r) return;
    const deleteOutput = typeof r === 'object' && r.checked;
    const ok = await act(() => jobsApi.remove(job.id, deleteOutput));
    if (ok !== null) {
      dropJob(job.id);
      toast({ tone: 'success', title: t('job.toast.deleted') });
      if (thenNavigate) navigate('/translations');
    }
  },
};

/** Primary button for a job in its current state. */
export function primaryAction(job) {
  switch (job.status) {
    case 'running': return { label: t('job.action.pause'), icon: 'pause', run: () => jobActions.pause(job) };
    case 'paused':
    case 'failed': return { label: t('job.action.resume'), icon: 'play', variant: 'primary', run: () => jobActions.resume(job) };
    case 'partial': return { label: t('job.action.retry'), icon: 'rotate-ccw', variant: 'primary', run: () => jobActions.resume(job) };
    case 'completed': return job.output_exists ? { label: t('job.action.download'), icon: 'download', run: () => jobActions.download(job) } : null;
    case 'queued': return { label: t('job.action.remove_from_queue'), icon: 'x', run: () => jobActions.removeFromQueue(job) };
    default: return null;
  }
}

export function menuItems(job, { onChangeModel, onAddChapters, thenNavigate }) {
  const items = [];
  if (job.output_exists) {
    items.push({ label: t('job.action.open'), icon: 'external-link', onSelect: () => jobActions.open(job) });
    items.push({ label: t('job.action.reveal'), icon: 'folder-open', onSelect: () => jobActions.reveal(job) });
    if (job.status !== 'completed') items.push({ label: t('job.action.download'), icon: 'download', onSelect: () => jobActions.download(job) });
  }
  if (job.status === 'queued') {
    items.push('sep');
    items.push({ label: t('job.action.move_top'), icon: 'arrow-up-down', onSelect: () => jobActions.move(job, 'top') });
    items.push({ label: t('job.action.move_up'), icon: 'chevron-up', onSelect: () => jobActions.move(job, 'up') });
    items.push({ label: t('job.action.move_down'), icon: 'chevron-down', onSelect: () => jobActions.move(job, 'down') });
  }
  if (['paused', 'partial', 'failed'].includes(job.status) && onChangeModel) {
    items.push('sep');
    items.push({ label: t('job.action.change_model'), icon: 'cpu', onSelect: onChangeModel });
  }
  if (job.status === 'completed' && onAddChapters) {
    items.push('sep');
    items.push({ label: t('job.action.add_chapters'), icon: 'file-up', onSelect: onAddChapters });
  }
  items.push('sep');
  items.push({ label: t('job.action.delete'), icon: 'trash-2', danger: true, disabled: job.status === 'running', onSelect: () => jobActions.remove(job, { thenNavigate }) });
  return items;
}

// ---------------------------------------------------------------- dialogs

export function ChangeModelDialog({ job, onClose }) {
  const [value, setValue] = useState({ connectionId: job.connection_id, model: job.model });
  const [reasoning, setReasoning] = useState(job.reasoning || 'off');
  const [busy, setBusy] = useState(false);
  const changed = value.connectionId !== job.connection_id || value.model !== job.model;
  const submit = async () => {
    setBusy(true);
    const r = await jobActions.resume(job, { connection_id: value.connectionId, model: value.model, reasoning });
    setBusy(false);
    if (r) onClose();
  };
  return html`<${Dialog}
    title=${t('job.change_model.title')}
    desc=${t('job.change_model.desc')}
    onClose=${onClose}
    footer=${html`
      <${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>
      <${Button} variant="primary" loading=${busy} disabled=${!value.model} onClick=${submit}>${t('job.change_model.submit')}<//>`}
  >
    <div class="form-rows">
      <${Field} label=${t('new.model.label')} htmlFor="change-model">
        <${ModelPicker} id="change-model" value=${value} onChange=${setValue} />
      <//>
      <${Field} label=${t('reasoning.label')}>
        <${ReasoningControl} connectionId=${value.connectionId} value=${reasoning} onChange=${setReasoning} />
      <//>
      ${changed && html`<div class="callout callout--warning"><div class="callout__body">${t('job.change_model.style_warning')}</div></div>`}
    </div>
  <//>`;
}

export function AddChaptersDialog({ job, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const take = async (files) => {
    const file = files[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const up = await uploadsApi.upload(file);
      const r = await jobsApi.continueWith(job.id, { file_path: up.file_path, input_filename: up.original_filename || file.name });
      const created = r && (r.job || (r.jobs && r.jobs[0]) || (r.id && { id: r.id }));
      await loadJobs();
      toast({ tone: 'success', title: t('job.add_chapters.started') });
      onClose();
      if (created) navigate(`/job/${created.id}`);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return html`<${Dialog}
    title=${t('job.add_chapters.title')}
    desc=${t('job.add_chapters.desc')}
    onClose=${onClose}
    footer=${html`<${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>`}
  >
    <div class="stack">
      <${Dropzone} multiple=${false} accept=${`.${job.file_type}`} disabled=${busy}
        title=${busy ? t('common.uploading') : t('job.add_chapters.drop', { ext: (job.file_type || '').toUpperCase() })}
        hint=${t('job.add_chapters.hint')} onFiles=${take} />
      ${error && html`<div class="field__error">${error}</div>`}
    </div>
  <//>`;
}

export function useJob(id) {
  return jobsById.value[id] || null;
}

export async function setQueuePaused(paused) {
  try {
    const r = await queueApi.setPaused(paused);
    queueState.value = { ...queueState.value, ...r };
  } catch (e) {
    toast({ tone: 'error', title: t('errors.action_failed'), message: e.message });
  }
}

/** Explains a held queue wherever queued work would otherwise just sit there. */
export function QueuePausedNotice({ context }) {
  const q = queueState.value;
  if (!q.paused) return null;
  const restart = q.reason === 'restart';
  return html`<${Callout} tone=${restart ? 'warning' : 'info'}
      title=${restart ? t('translations.queue.held_restart') : t('translations.queue.held_user')}
      actions=${html`<${Button} size="sm" variant="primary" icon="play" onClick=${() => setQueuePaused(false)}>${t('translations.queue.resume')}<//>`}>
    ${context === 'new' ? t('translations.queue.held_new') : restart ? t('translations.queue.held_desc') : t('translations.queue.held_user_desc')}
  <//>`;
}
