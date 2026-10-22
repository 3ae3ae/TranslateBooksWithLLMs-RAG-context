import { html, useState } from '../ui/html.js';
import { Button, Icon, Progress, Cover, EmptyState, Callout } from '../ui/core.js';
import { Menu, toast } from '../ui/overlays.js';
import { PageHeader } from '../ui/layout.js';
import { JobStatusPill, primaryAction, menuItems, langPair, jobFacts, ChangeModelDialog, AddChaptersDialog } from '../ui/jobs.js';
import { jobGroups, jobsLoaded, queueState } from '../lib/stores.js';
import { queueApi, foldersApi, jobsApi } from '../lib/api.js';
import { navigate } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { formatNumber, formatDuration } from '../lib/format.js';

function JobRow({ job, onDialog }) {
  const action = primaryAction(job);
  const running = job.status === 'running';
  const facts = running ? [] : jobFacts(job);
  const open = () => navigate(`/job/${job.id}`);
  return html`<div class="job-row" role="link" tabindex="0"
      onClick=${open} onKeyDown=${(e) => { if (e.key === 'Enter') open(); }}>
    <${Cover} src=${job.has_cover ? jobsApi.coverPath(job.id) : null} format=${job.file_type} />
    <div class="job-row__main">
      <div class="job-row__title truncate">${job.title}</div>
      <div class="job-row__meta">
        <span>${langPair(job)}</span>
        ${job.model && html`<span class="faint">·</span><span class="truncate">${job.model}</span>`}
        ${facts.map((f) => html`<span class="faint">·</span><span>${f}</span>`)}
      </div>
      ${running && html`<div class="job-row__progress">
        <${Progress} value=${job.percent} label=${t('job.progress_label')} />
        <span class="small muted num">${formatNumber(Math.round(job.percent || 0))}%</span>
        ${job.eta_seconds ? html`<span class="small faint">${t('job.eta', { time: formatDuration(job.eta_seconds) })}</span>` : null}
      </div>`}
      ${job.status === 'failed' && job.error && html`<div class="small" style="color:var(--danger)">${job.error}</div>`}
    </div>
    <div class="job-row__status"><${JobStatusPill} job=${job} /></div>
    <div class="job-row__actions" onClick=${(e) => e.stopPropagation()}>
      ${action && html`<${Button} size="sm" variant=${action.variant || 'secondary'} icon=${action.icon} onClick=${action.run}>${action.label}<//>`}
      <${Menu} items=${menuItems(job, {
        onChangeModel: () => onDialog({ kind: 'model', job }),
        onAddChapters: () => onDialog({ kind: 'chapters', job }),
      })} />
    </div>
  </div>`;
}

function Group({ title, jobs, onDialog, collapsible, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  if (!jobs.length) return null;
  return html`<section class="group">
    <h2 class="group__title">
      ${collapsible
        ? html`<button type="button" class="btn btn--ghost btn--sm" style="margin-left:-10px" aria-expanded=${String(open)} onClick=${() => setOpen(!open)}>
            <${Icon} name=${open ? 'chevron-down' : 'chevron-right'} size="sm" />${title}
            <span class="group__count">${formatNumber(jobs.length)}</span>
          </button>`
        : html`${title}<span class="group__count">${formatNumber(jobs.length)}</span>`}
    </h2>
    ${open && html`<div class="job-list">${jobs.map((j) => html`<${JobRow} key=${j.id} job=${j} onDialog=${onDialog} />`)}</div>`}
  </section>`;
}

export function TranslationsPage() {
  const [query, setQuery] = useState('');
  const [dialog, setDialog] = useState(null);
  const groups = jobGroups.value;
  const queue = queueState.value;
  const q = query.trim().toLocaleLowerCase();
  const filter = (list) => (q ? list.filter((j) => `${j.title} ${j.input_filename}`.toLocaleLowerCase().includes(q)) : list);
  const inProgress = filter(groups.inProgress);
  const attention = filter(groups.attention);
  const finished = filter(groups.finished);
  const hasQueue = groups.inProgress.some((j) => j.status === 'queued');

  const toggleQueue = async () => {
    try {
      const r = await queueApi.setPaused(!queue.paused);
      queueState.value = { ...queue, ...r };
    } catch (e) {
      toast({ tone: 'error', title: t('errors.action_failed'), message: e.message });
    }
  };

  if (!jobsLoaded.value) {
    return html`<div class="page"><${PageHeader} title=${t('translations.title')} /><p class="muted">${t('common.loading')}</p></div>`;
  }

  if (!groups.total) {
    return html`<div class="page">
      <${PageHeader} title=${t('translations.title')} />
      <${EmptyState} icon="book-open" title=${t('translations.empty.title')}
        actions=${html`<${Button} variant="primary" icon="plus" href="#/new">${t('nav.new')}<//>`}>
        <ol class="steps">
          <li>${t('translations.empty.step1')}</li>
          <li>${t('translations.empty.step2')}</li>
          <li>${t('translations.empty.step3')}</li>
        </ol>
      <//>
    </div>`;
  }

  return html`<div class="page">
    <${PageHeader}
      title=${t('translations.title')}
      actions=${html`
        ${(hasQueue || queue.paused) && html`<${Button} icon=${queue.paused ? 'play' : 'pause'} onClick=${toggleQueue}>
          ${queue.paused ? t('translations.queue.resume') : t('translations.queue.pause')}
        <//>`}
        <${Button} icon="folder-open" onClick=${() => foldersApi.open('output').catch((e) => toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }))}>${t('translations.open_output')}<//>
        <${Button} variant="primary" icon="plus" href="#/new">${t('nav.new')}<//>`}
    />
    ${queue.paused && html`<${Callout} tone=${queue.reason === 'restart' ? 'warning' : 'info'}
        title=${queue.reason === 'restart' ? t('translations.queue.held_restart') : t('translations.queue.held_user')}
        actions=${html`<${Button} size="sm" variant="primary" icon="play" onClick=${toggleQueue}>${t('translations.queue.resume')}<//>`}
        class="group">
      ${t('translations.queue.held_desc')}
    <//>`}
    <div class="toolbar">
      <div class="input-affix toolbar__search">
        <${Icon} name="search" size="sm" />
        <input class="input" type="search" placeholder=${t('translations.search')} aria-label=${t('translations.search')}
          value=${query} onInput=${(e) => setQuery(e.currentTarget.value)} />
      </div>
    </div>
    <${Group} title=${t('translations.group.in_progress')} jobs=${inProgress} onDialog=${setDialog} />
    <${Group} title=${t('translations.group.attention')} jobs=${attention} onDialog=${setDialog} />
    <${Group} title=${t('translations.group.finished')} jobs=${finished} onDialog=${setDialog} collapsible />
    ${q && !inProgress.length && !attention.length && !finished.length && html`<p class="muted">${t('translations.no_match')}</p>`}
    ${dialog && dialog.kind === 'model' && html`<${ChangeModelDialog} job=${dialog.job} onClose=${() => setDialog(null)} />`}
    ${dialog && dialog.kind === 'chapters' && html`<${AddChaptersDialog} job=${dialog.job} onClose=${() => setDialog(null)} />`}
  </div>`;
}
