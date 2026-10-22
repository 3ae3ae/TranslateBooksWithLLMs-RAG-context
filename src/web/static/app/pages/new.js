import { html, useEffect, useRef, useState, useMemo, useCallback, cx } from '../ui/html.js';
import { Button, Icon, IconButton, Callout, Cover, Spinner, Pill } from '../ui/core.js';
import { Field, TextInput, NumberInput, Segmented, ChoiceGroup, ToggleRow, Select, Checkbox } from '../ui/forms.js';
import { PageHeader, Section, Disclosure, Dropzone, usePageDrop } from '../ui/layout.js';
import { toast } from '../ui/overlays.js';
import { ModelPicker, ReasoningControl } from '../ui/model-picker.js';
import { StyleDialog } from '../ui/style-dialog.js';
import { GlossaryExtractDialog } from '../ui/glossary-extract.js';
import { ConnectionDialog } from '../ui/connection-dialog.js';
import {
  draft, preferences, connections, connectionsLoaded, defaultConnection, glossaries, stylesList, notesList,
  loadGlossaries, loadStyles, loadNotes, loadConnections, upsertJob,
} from '../lib/stores.js';
import { uploadsApi, jobsApi, estimateApi } from '../lib/api.js';
import { LANGUAGES, findLanguage } from '../lib/languages.js';
import { navigate } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { formatBytes, formatCost, formatNumber, formatDuration } from '../lib/format.js';
import { displayName } from '../lib/names.js';

const ACCEPT = '.epub,.docx,.txt,.srt';
const BOOKISH = ['epub', 'docx', 'txt'];
let localId = 0;

function initialDraft(prefs) {
  const p = prefs || {};
  return {
    task: p.task || 'translate',
    polishAfter: !!p.polish_after,
    files: [],
    ocr: !!p.ocr_cleanup,
    source: p.source_language || '',
    target: p.target_language || '',
    connectionId: p.default_connection_id || null,
    model: p.default_model || '',
    reasoning: p.default_reasoning || 'off',
    notes: {
      mode: p.notes_mode || 'build',
      touched: false,
      source: '',
      keepUpdating: true,
      series: false,
      name: '',
      interval: p.notes_update_interval || 1,
      promptMaxTokens: p.notes_prompt_max_tokens ?? 1800,
      sourceMemoryChars: p.notes_source_memory_chars ?? 6000,
      consolidationInterval: p.notes_consolidation_interval ?? 5,
      acceptGender: p.notes_accept_gender_corrections ?? true,
    },
    glossaryId: p.glossary_id || null,
    style: p.style || '',
    simplify: !!p.simplify_formatting,
    bilingual: !!p.bilingual,
    passageTokens: p.passage_tokens || 450,
    chapterMode: !!p.chapter_mode,
    srtLines: p.srt_lines_per_block || 10,
    pattern: p.output_filename_pattern || '{originalName} ({targetLang}).{ext}',
    remember: true,
  };
}

const stem = (name) => name.replace(/\.[^.]+$/, '');

function previewName(pattern, file, d) {
  const ext = (file.file_type || file.name.split('.').pop() || '').toLowerCase();
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  return pattern
    .replaceAll('{originalName}', stem(file.name))
    .replaceAll('{targetLang}', d.target || '…')
    .replaceAll('{sourceLang}', d.source || file.detected || '…')
    .replaceAll('{model}', d.model || '…')
    .replaceAll('{date}', date)
    .replaceAll('{datetime}', `${date}_${pad(now.getHours())}${pad(now.getMinutes())}`)
    .replaceAll('{ext}', ext);
}

export function buildJobRequest(d) {
  return {
    task: d.task,
    polish_after: d.task === 'translate' && d.polishAfter,
    files: d.files.filter((f) => f.status === 'ready').map((f) => ({ file_path: f.file_path, input_filename: f.name })),
    source_language: d.task === 'polish' ? d.target : d.source,
    target_language: d.target,
    connection_id: d.connectionId,
    model: d.model,
    reasoning: d.reasoning,
    notes: {
      mode: d.notes.mode,
      source: d.notes.mode === 'copy' ? d.notes.source : undefined,
      keep_updating: d.task === 'polish' ? false : d.notes.keepUpdating,
      series: d.notes.series,
      name: d.notes.name || undefined,
      update_interval: d.notes.interval,
      prompt_max_tokens: d.notes.promptMaxTokens,
      source_memory_chars: d.notes.sourceMemoryChars,
      consolidation_interval: d.notes.consolidationInterval,
      accept_gender_corrections: d.notes.acceptGender,
    },
    glossary_id: d.glossaryId || undefined,
    style: d.style || undefined,
    ocr_cleanup: d.ocr,
    simplify_formatting: d.simplify,
    bilingual: d.bilingual,
    passage_tokens: d.passageTokens,
    chapter_mode: d.chapterMode,
    srt_lines_per_block: d.srtLines,
    output_filename_pattern: d.pattern,
    remember_defaults: d.remember,
  };
}

function LanguageInput({ id, value, onChange, placeholder, listId }) {
  return html`<input id=${id} class="input" list=${listId} value=${value} placeholder=${placeholder}
    autocomplete="off" onInput=${(e) => onChange(e.currentTarget.value)} />`;
}

function LanguageList({ id }) {
  return html`<datalist id=${id}>${LANGUAGES.map((l) => html`<option value=${l.value}>${t(`lang.name.${l.code}`)}</option>`)}</datalist>`;
}

function langLabel(name) {
  const l = findLanguage(name);
  return l ? t(`lang.name.${l.code}`) : name;
}

// ------------------------------------------------------------------ files

function FileRow({ f, index, d, series, onRemove, onMove }) {
  const detected = f.detected
    ? (f.confidence != null && f.confidence < 0.7
      ? html`<span style="color:var(--warning)">${t('new.files.detected_unsure', { lang: langLabel(f.detected) })}</span>`
      : html`<span>${t('new.files.detected', { lang: langLabel(f.detected) })}</span>`)
    : null;
  return html`<div class="file-row">
    <${Cover} src=${f.thumbnail ? `/api/thumbnails/${encodeURIComponent(f.thumbnail)}` : null} format=${f.file_type || f.name.split('.').pop()} size="sm" />
    <div class="stack" style="--gap:2px;min-width:0">
      <div class="file-row__name truncate">${series ? html`<span class="faint">${index + 1}. </span>` : ''}${f.name}</div>
      ${f.status === 'error'
        ? html`<div class="file-row__error">${f.error}</div>`
        : html`<div class="file-row__meta">
            <span>${(f.file_type || '').toUpperCase()}</span>
            ${f.size ? html`<span>${formatBytes(f.size)}</span>` : null}
            ${f.status === 'uploading' ? html`<span class="row" style="--gap:4px"><${Spinner} size="sm" />${t('common.uploading')}</span>` : detected}
            ${f.status === 'ready' && d.target && html`<span class="faint truncate" title=${t('new.files.output_name')}>→ ${previewName(d.pattern, f, d)}</span>`}
          </div>`}
    </div>
    <div class="row" style="--gap:2px">
      ${series && html`
        <${IconButton} icon="chevron-up" size="sm" label=${t('new.files.move_up')} disabled=${index === 0} onClick=${() => onMove(index, -1)} />
        <${IconButton} icon="chevron-down" size="sm" label=${t('new.files.move_down')} disabled=${index === d.files.length - 1} onClick=${() => onMove(index, 1)} />`}
      <${IconButton} icon="x" size="sm" label=${t('new.files.remove', { name: f.name })} onClick=${() => onRemove(f)} />
    </div>
  </div>`;
}

// ---------------------------------------------------------------- summary

function useEstimate(d, ready) {
  const [state, setState] = useState({ loading: false, data: null, error: null });
  const body = ready ? JSON.stringify(buildJobRequest(d)) : null;
  useEffect(() => {
    if (!body) { setState({ loading: false, data: null, error: null }); return undefined; }
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    const timer = setTimeout(() => {
      estimateApi.estimate(JSON.parse(body), ctrl.signal)
        .then((data) => setState({ loading: false, data, error: null }))
        .catch((error) => { if (error.name !== 'AbortError' && error.code !== 'network') setState({ loading: false, data: null, error }); });
    }, 500);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [body]);
  return state;
}

function EstimateBlock({ est }) {
  if (est.loading && !est.data) return html`<div class="row muted small"><${Spinner} size="sm" />${t('new.summary.estimating')}</div>`;
  if (est.error) return html`<div class="small muted">${t('new.summary.estimate_failed')}</div>`;
  const e = est.data;
  if (!e) return html`<div class="small muted">${t('new.summary.estimate_needs')}</div>`;
  let cost;
  if (e.billing === 'local') cost = t('new.summary.no_api_cost');
  else if (e.billing === 'plan') cost = t('new.summary.plan_billing');
  else if (e.cost_min_usd == null) cost = t('new.summary.price_unknown');
  else if (Math.abs((e.cost_max_usd || 0) - (e.cost_min_usd || 0)) < 0.005) cost = `≈ ${formatCost(e.cost_min_usd)}`;
  else cost = `≈ ${formatCost(e.cost_min_usd)} – ${formatCost(e.cost_max_usd)}`;
  const time = e.time_source === 'history' && e.time_min_s
    ? t('new.summary.time_range', { min: formatDuration(e.time_min_s), max: formatDuration(e.time_max_s || e.time_min_s) })
    : t('new.summary.time_unknown');
  return html`<div class="stack" style="--gap:6px;opacity:${est.loading ? 0.6 : 1}">
    <div class="summary__estimate">${cost}</div>
    <div class="small muted">${t('new.summary.counts', { passages: formatNumber(e.passages || 0), requests: formatNumber(e.requests || 0) })}</div>
    <div class="small muted">${time}</div>
    ${e.price_source && e.billing === 'api' && html`<div class="tiny faint">${t('new.summary.price_source', { source: e.price_source })}</div>`}
  </div>`;
}

// Why Start is disabled, if it is (null when ready).
function startBlocker(d) {
  if (!d) return t('common.loading');
  if (!d.files.length) return t('new.reason.no_files');
  if (d.files.some((f) => f.status === 'uploading')) return t('new.reason.uploading');
  if (d.files.some((f) => f.status === 'error')) return t('new.reason.upload_failed');
  if (!d.target.trim()) return d.task === 'polish' ? t('new.reason.no_language') : t('new.reason.no_target');
  if (!d.model) return t('new.reason.no_model');
  if (d.notes.mode === 'copy' && !d.notes.source) return t('new.reason.no_notes_source');
  return null;
}

// ------------------------------------------------------------------- page

export function NewTranslationPage() {
  const prefs = preferences.value;
  const [dialog, setDialog] = useState(null);
  const [starting, setStarting] = useState(false);
  const uploadsRef = useRef(new Map()); // localId -> AbortController

  useEffect(() => {
    if (!draft.value && prefs) draft.value = initialDraft(prefs);
  }, [prefs]);
  useEffect(() => {
    if (glossaries.value === null) loadGlossaries().catch(() => {});
    if (stylesList.value === null) loadStyles().catch(() => {});
    if (notesList.value === null) loadNotes().catch(() => {});
  }, []);

  const d = draft.value;
  const update = useCallback((patch) => {
    draft.value = { ...draft.value, ...(typeof patch === 'function' ? patch(draft.value) : patch) };
  }, []);
  const updateNotes = (patch) => update((cur) => ({ notes: { ...cur.notes, ...patch, touched: true } }));
  const setFile = (id, patch) => update((cur) => ({ files: cur.files.map((f) => (f.localId === id ? { ...f, ...patch } : f)) }));

  const addFiles = useCallback((list) => {
    const valid = list.filter((f) => /\.(epub|docx|txt|srt)$/i.test(f.name));
    if (valid.length < list.length) toast({ tone: 'warning', title: t('new.files.unsupported') });
    for (const file of valid) {
      const id = ++localId;
      const ctrl = new AbortController();
      uploadsRef.current.set(id, ctrl);
      update((cur) => ({ files: [...cur.files, { localId: id, name: file.name, size: file.size, status: 'uploading', file_type: file.name.split('.').pop().toLowerCase() }] }));
      uploadsApi.upload(file, ctrl.signal)
        .then((r) => {
          setFile(id, {
            status: 'ready', file_path: r.file_path, file_type: r.file_type, size: r.size,
            detected: r.detected_language || null, confidence: r.language_confidence ?? null, thumbnail: r.thumbnail || null,
          });
        })
        .catch((e) => { if (e.name !== 'AbortError') setFile(id, { status: 'error', error: e.message }); })
        .finally(() => uploadsRef.current.delete(id));
    }
  }, [update]);

  const pageDrop = usePageDrop(addFiles, !!d);
  const est = useEstimate(d, !startBlocker(d));

  // Default story-notes mode follows the file types until the user picks one.
  useEffect(() => {
    if (!d || d.notes.touched || !d.files.length) return;
    const bookish = d.files.some((f) => BOOKISH.includes(f.file_type));
    const mode = bookish ? (prefs && prefs.notes_mode) || 'build' : 'off';
    if (mode !== d.notes.mode) draft.value = { ...d, notes: { ...d.notes, mode } };
  }, [d && d.files.map((f) => f.file_type).join(',')]);

  // Pick the default model once connections are known.
  useEffect(() => {
    if (!d || d.model || !connectionsLoaded.value) return;
    const conn = defaultConnection.value;
    if (conn && conn.default_model) update({ connectionId: conn.id, model: conn.default_model });
  }, [connectionsLoaded.value, d && d.model]);

  if (!d) return html`<div class="page"><p class="muted">${t('common.loading')}</p></div>`;

  const removeFile = (f) => {
    const ctrl = uploadsRef.current.get(f.localId);
    if (ctrl) ctrl.abort();
    if (f.file_path) uploadsApi.remove(f.file_path).catch(() => {});
    update((cur) => ({ files: cur.files.filter((x) => x.localId !== f.localId) }));
  };
  const moveFile = (i, delta) => update((cur) => {
    const files = [...cur.files];
    const [x] = files.splice(i, 1);
    files.splice(i + delta, 0, x);
    return { files };
  });

  const polish = d.task === 'polish';
  const types = new Set(d.files.map((f) => f.file_type));
  const hasLayout = types.has('epub') || types.has('docx');
  const hasSrt = types.has('srt');
  const multi = d.files.length > 1;
  const notesOn = d.notes.mode !== 'off';
  const conn = connections.value.find((c) => c.id === d.connectionId);
  const usable = connections.value.length > 0;

  const reason = startBlocker(d);
  const ready = !reason;

  const start = async () => {
    if (!ready || starting) return;
    setStarting(true);
    try {
      const r = await jobsApi.create(buildJobRequest(d));
      const jobs = r.jobs || [];
      jobs.forEach((j) => upsertJob(j));
      draft.value = { ...d, files: [] };
      const running = jobs.length && jobs[0].status === 'queued' && jobs[0].queue_position > 1;
      toast({ tone: 'success', title: jobs.length > 1 ? t('new.toast.queued_many', { count: jobs.length }) : running ? t('new.toast.queued_behind') : t('new.toast.started') });
      navigate(jobs.length === 1 ? `/job/${jobs[0].id}` : '/translations');
    } catch (e) {
      toast({ tone: 'error', title: t('new.toast.start_failed'), message: e.message });
    } finally {
      setStarting(false);
    }
  };

  const onKey = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') start(); };

  const glossaryOptions = [{ value: '', label: t('common.none') }, ...((glossaries.value || []).map((g) => ({
    value: String(g.id),
    label: `${g.name} · ${t('glossary.term_count', { count: g.term_count ?? g.terms_count ?? 0, n: formatNumber(g.term_count ?? g.terms_count ?? 0) })}`,
  })))];
  const selectedGlossary = (glossaries.value || []).find((g) => String(g.id) === String(d.glossaryId));
  const glossaryMismatch = selectedGlossary && d.target && selectedGlossary.target_lang
    && selectedGlossary.target_lang.toLowerCase() !== d.target.toLowerCase();
  const styleOptions = [{ value: '', label: t('common.none') }, ...((stylesList.value || []).map((s) => ({ value: s.name, label: s.display_name || displayName(s.name) })))];
  const noteOptions = [{ value: '', label: t('new.notes.pick') }, ...((notesList.value || []).map((n) => ({ value: n.name, label: displayName(n.name) })))];

  const interval = d.notes.interval || 1;
  const notesCost = t('new.notes.cost');

  const chips = [];
  if (!polish && d.polishAfter) chips.push(t('new.chip.polish'));
  if (notesOn) chips.push(d.notes.mode === 'build' ? t('new.chip.notes_build') : t('new.chip.notes_copy'));
  if (selectedGlossary) chips.push(t('new.chip.glossary', { name: selectedGlossary.name }));
  if (d.style) chips.push(t('new.chip.style', { name: displayName(d.style) }));
  if (hasLayout && d.simplify) chips.push(t('new.chip.simplify'));
  if (d.bilingual) chips.push(t('new.chip.bilingual'));
  if (d.ocr) chips.push(t('new.chip.ocr'));

  return html`<div class="page" onKeyDown=${onKey}>
    <${PageHeader} title=${t('new.title')} subtitle=${t('new.subtitle')} />
    ${pageDrop && html`<div class="page-drop">${t('new.files.drop_anywhere')}</div>`}
    <${LanguageList} id="lang-list" />
    <div class="compose">
      <div class="compose__main">

        ${connectionsLoaded.value && !usable && html`<${Callout} tone="info" title=${t('new.connect.title')} class="section"
            actions=${html`<${Button} variant="primary" icon="plug" onClick=${() => setDialog({ kind: 'connection' })}>${t('new.connect.add')}<//>
              <${Button} icon="refresh-cw" onClick=${loadConnections}>${t('common.retry')}<//>`}>
          ${t('new.connect.body')}
        <//>`}

        <${Section} step="1" title=${t('new.task.title')} id="sec-task">
          <div class="stack">
            <${Segmented} label=${t('new.task.title')} value=${d.task} onChange=${(v) => update({ task: v })} options=${[
              { value: 'translate', label: t('new.task.translate'), icon: 'languages' },
              { value: 'polish', label: t('new.task.polish'), icon: 'sparkles' },
            ]} />
            <p class="muted">${polish ? t('new.task.polish_desc') : t('new.task.translate_desc')}</p>
            ${!polish && html`<${ToggleRow} title=${t('new.task.polish_after')} desc=${t('new.task.polish_after_desc')}
              checked=${d.polishAfter} onChange=${(v) => update({ polishAfter: v })} />`}
          </div>
        <//>

        <${Section} step="2" title=${t('new.files.title')} desc=${t('new.files.desc')} id="sec-files">
          <div class="stack">
            <${Dropzone} accept=${ACCEPT} onFiles=${addFiles} compact=${d.files.length > 0}
              title=${d.files.length ? t('new.files.add_more') : t('new.files.drop')} hint=${t('new.files.formats')} />
            ${d.files.length > 0 && html`<div class="file-list">
              ${d.files.map((f, i) => html`<${FileRow} key=${f.localId} f=${f} index=${i} d=${d}
                series=${multi && notesOn && d.notes.series} onRemove=${removeFile} onMove=${moveFile} />`)}
            </div>`}
            ${multi && html`<p class="small muted">${t('new.files.sequential')}</p>`}
            <${ToggleRow} title=${t('new.files.ocr')} desc=${t('new.files.ocr_desc')} checked=${d.ocr} onChange=${(v) => update({ ocr: v })} />
          </div>
        <//>

        <${Section} step="3" title=${t('new.lang.title')} id="sec-lang">
          ${polish
            ? html`<${Field} label=${t('new.lang.language')} htmlFor="lang-target" help=${t('new.lang.polish_help')}>
                <${LanguageInput} id="lang-target" listId="lang-list" value=${d.target} onChange=${(v) => update({ target: v })} placeholder=${t('new.lang.target_placeholder')} />
              <//>`
            : html`<div class="field-grid">
                <${Field} label=${t('new.lang.from')} htmlFor="lang-source" help=${t('new.lang.from_help')}>
                  <${LanguageInput} id="lang-source" listId="lang-list" value=${d.source} onChange=${(v) => update({ source: v })} placeholder=${t('new.lang.detect')} />
                <//>
                <${Field} label=${t('new.lang.to')} htmlFor="lang-target">
                  <${LanguageInput} id="lang-target" listId="lang-list" value=${d.target} onChange=${(v) => update({ target: v })} placeholder=${t('new.lang.target_placeholder')} />
                <//>
              </div>`}
        <//>

        <${Section} step="4" title=${t('new.model.title')} id="sec-model"
          aside=${html`<${Button} variant="link" icon="scale" onClick=${() => navigate('/compare?from=draft')} disabled=${!d.files.some((f) => f.status === 'ready')}>${t('new.model.try')}<//>`}>
          <div class="form-rows">
            <${Field} label=${t('new.model.label')} htmlFor="model-picker"
              help=${conn && conn.local ? t('new.model.local_help') : null}>
              <${ModelPicker} id="model-picker" value=${{ connectionId: d.connectionId, model: d.model }}
                onChange=${(v) => update({ connectionId: v.connectionId, model: v.model })} />
            <//>
            ${d.connectionId && html`<${Field} label=${t('reasoning.label')}>
              <${ReasoningControl} connectionId=${d.connectionId} value=${d.reasoning} onChange=${(v) => update({ reasoning: v })} />
            <//>`}
          </div>
        <//>

        <${Section} step="5" title=${t('new.consistency.title')} desc=${t('new.consistency.desc')} id="sec-consistency">
          <div class="form-rows">
            <div class="stack" style="--gap:10px">
              <h3>${t('new.notes.title')}</h3>
              <p class="small muted">${t('new.notes.explain')}</p>
              <${ChoiceGroup} label=${t('new.notes.title')} value=${d.notes.mode} onChange=${(v) => updateNotes({ mode: v })} options=${[
                { value: 'build', title: t('new.notes.build'), desc: t('new.notes.build_desc'), icon: 'notebook-pen', disabled: polish },
                { value: 'copy', title: t('new.notes.copy'), desc: t('new.notes.copy_desc'), icon: 'copy' },
                { value: 'off', title: t('new.notes.off'), desc: t('new.notes.off_desc'), icon: 'minus' },
              ]} />
              ${d.notes.mode === 'copy' && html`<div class="field-grid">
                <${Field} label=${t('new.notes.source')} htmlFor="notes-source">
                  <${Select} id="notes-source" value=${d.notes.source} options=${noteOptions} onChange=${(v) => updateNotes({ source: v })} />
                <//>
                ${!polish && html`<div class="row" style="align-self:end;padding-bottom:8px">
                  <${Checkbox} checked=${d.notes.keepUpdating} onChange=${(v) => updateNotes({ keepUpdating: v })}
                    label=${html`<span>${t('new.notes.keep_updating')}</span>`} />
                </div>`}
              </div>`}
              ${notesOn && !polish && (d.notes.mode === 'build' || d.notes.keepUpdating) && html`<div class="row row--wrap" style="--gap:12px">
                <${Field} label=${t('new.notes.interval')} htmlFor="notes-interval">
                  <${NumberInput} id="notes-interval" min=${1} max=${50} value=${interval} onCommit=${(v) => updateNotes({ interval: v || 1 })}
                    suffix=${t('new.notes.interval_suffix')} />
                <//>
                <span class="small muted" style="align-self:end;padding-bottom:9px">${notesCost}</span>
              </div>`}
              ${notesOn && multi && html`<${Field} label=${t('new.notes.multi')}>
                <${Segmented} label=${t('new.notes.multi')} value=${d.notes.series ? 'series' : 'separate'}
                  onChange=${(v) => updateNotes({ series: v === 'series' })} options=${[
                    { value: 'separate', label: t('new.notes.separate') },
                    { value: 'series', label: t('new.notes.series') },
                  ]} />
                <div class="field__help">${d.notes.series ? t('new.notes.series_help') : t('new.notes.separate_help')}</div>
              <//>`}
            </div>

            <div class="field-grid">
              <${Field} label=${t('new.glossary.label')} htmlFor="glossary-select"
                help=${glossaryMismatch ? null : t('new.glossary.help')}
                error=${glossaryMismatch ? t('new.glossary.mismatch', { lang: selectedGlossary.target_lang }) : null}
                labelExtra=${html`<${Button} variant="link" class="small" disabled=${!d.files.some((f) => f.status === 'ready')}
                  title=${d.files.some((f) => f.status === 'ready') ? undefined : t('new.reason.no_files')}
                  onClick=${() => setDialog({ kind: 'extract' })}>${t('new.glossary.extract')}<//>`}>
                <${Select} id="glossary-select" value=${d.glossaryId ? String(d.glossaryId) : ''} options=${glossaryOptions}
                  onChange=${(v) => update({ glossaryId: v ? Number(v) : null })} />
              <//>
              <${Field} label=${t('new.style.label')} htmlFor="style-select" help=${t('new.style.help')}
                labelExtra=${html`<span class="row" style="--gap:12px">
                  ${d.style && html`<${Button} variant="link" class="small" href=${`#/styles/${encodeURIComponent(d.style)}`}>${t('common.edit')}<//>`}
                  <${Button} variant="link" class="small" onClick=${() => setDialog({ kind: 'style' })}>${t('new.style.new')}<//>
                </span>`}>
                <${Select} id="style-select" value=${d.style} options=${styleOptions} onChange=${(v) => update({ style: v })} />
              <//>
            </div>
          </div>
        <//>

        <${Section} step="6" title=${t('new.output.title')} id="sec-output">
          <div class="stack" style="--gap:4px">
            ${hasLayout && html`<${Field} label=${t('new.output.formatting')}>
              <${ChoiceGroup} label=${t('new.output.formatting')} value=${d.simplify ? 'simplify' : 'keep'} cols=${2}
                onChange=${(v) => update({ simplify: v === 'simplify' })} options=${[
                  { value: 'keep', title: t('new.output.keep'), desc: t('new.output.keep_desc') },
                  { value: 'simplify', title: t('new.output.simplify'), desc: t('new.output.simplify_desc') },
                ]} />
            <//>`}
            <${ToggleRow} title=${t('new.output.bilingual')} desc=${t('new.output.bilingual_desc')}
              checked=${d.bilingual} onChange=${(v) => update({ bilingual: v })} />
          </div>
        <//>

        <${Disclosure} title=${t('new.advanced.title')}>
          <div class="form-rows">
            <div class="field-grid">
              <${Field} label=${t('new.advanced.passage')} htmlFor="adv-passage" help=${t('new.advanced.passage_help')}>
                <${NumberInput} id="adv-passage" min=${50} max=${4000} step=${50} value=${d.passageTokens}
                  onCommit=${(v) => update({ passageTokens: v || 450 })} suffix=${t('new.advanced.tokens')} />
              <//>
              ${hasSrt && html`<${Field} label=${t('new.advanced.srt_lines')} htmlFor="adv-srt" help=${t('new.advanced.srt_lines_help')}>
                <${NumberInput} id="adv-srt" min=${1} max=${50} value=${d.srtLines} onCommit=${(v) => update({ srtLines: v || 10 })} />
              <//>`}
            </div>
            <${ToggleRow} title=${t('new.advanced.chapters')} desc=${t('new.advanced.chapters_desc')}
              checked=${d.chapterMode} onChange=${(v) => update({ chapterMode: v })} />
            <${Field} label=${t('new.advanced.pattern')} htmlFor="adv-pattern" help=${t('new.advanced.pattern_help')}>
              <${TextInput} id="adv-pattern" value=${d.pattern} onInput=${(v) => update({ pattern: v })} />
              <div class="chips">
                ${['{originalName}', '{targetLang}', '{sourceLang}', '{model}', '{date}', '{datetime}', '{ext}'].map((p) => html`<button type="button" class="chip mono"
                  onClick=${() => update((cur) => ({ pattern: cur.pattern + p }))}>${p}</button>`)}
              </div>
            <//>
            ${notesOn && html`<div class="stack" style="--gap:8px">
              <h3>${t('new.advanced.notes_title')}</h3>
              <div class="field-grid">
                <${Field} label=${t('new.advanced.notes_budget')} htmlFor="adv-budget" help=${t('new.advanced.notes_budget_help')}>
                  <${NumberInput} id="adv-budget" min=${0} max=${20000} step=${100} value=${d.notes.promptMaxTokens}
                    onCommit=${(v) => updateNotes({ promptMaxTokens: v ?? 1800 })} suffix=${t('new.advanced.tokens')} />
                <//>
                <${Field} label=${t('new.advanced.notes_lookback')} htmlFor="adv-lookback" help=${t('new.advanced.notes_lookback_help')}>
                  <${NumberInput} id="adv-lookback" min=${0} max=${50000} step=${500} value=${d.notes.sourceMemoryChars}
                    onCommit=${(v) => updateNotes({ sourceMemoryChars: v ?? 6000 })} suffix=${t('new.advanced.chars')} />
                <//>
                <${Field} label=${t('new.advanced.notes_tidy')} htmlFor="adv-tidy" help=${t('new.advanced.notes_tidy_help')}>
                  <${NumberInput} id="adv-tidy" min=${0} max=${100} value=${d.notes.consolidationInterval}
                    onCommit=${(v) => updateNotes({ consolidationInterval: v ?? 5 })} suffix=${t('new.advanced.updates')} />
                <//>
              </div>
              <${ToggleRow} title=${t('new.advanced.gender')} desc=${t('new.advanced.gender_desc')}
                checked=${d.notes.acceptGender} onChange=${(v) => updateNotes({ acceptGender: v })} />
            </div>`}
          </div>
        <//>
      </div>

      <aside class="compose__aside" aria-label=${t('new.summary.title')}>
        <div class="card summary">
          <div class="summary__block">
            <div class="summary__title">${t('new.summary.title')}</div>
            <div class="summary__line"><span>${t('new.summary.files')}</span>
              <span>${d.files.length ? t('new.summary.files_value', { count: d.files.length, n: formatNumber(d.files.length), size: formatBytes(d.files.reduce((a, f) => a + (f.size || 0), 0)) }) : '—'}</span></div>
            <div class="summary__line"><span>${t('new.summary.languages')}</span>
              <span>${polish ? langLabel(d.target) || '—' : `${d.source ? langLabel(d.source) : t('new.lang.detect')} → ${d.target ? langLabel(d.target) : '—'}`}</span></div>
            <div class="summary__line"><span>${t('new.summary.model')}</span>
              <span>${d.model ? `${d.model}${d.reasoning && d.reasoning !== 'off' ? ` · ${t(`reasoning.${d.reasoning}`)}` : ''}` : '—'}</span></div>
            ${chips.length > 0 && html`<div class="chips" style="margin-top:8px">${chips.map((c) => html`<span class="chip">${c}</span>`)}</div>`}
          </div>
          <div class="summary__block">
            <div class="summary__title">${t('new.summary.estimate')}</div>
            <${EstimateBlock} est=${est} />
          </div>
          ${notesOn && !polish && (d.notes.mode === 'build' || d.notes.keepUpdating) && html`<div class="summary__block">
            <div class="row small muted" style="align-items:flex-start"><${Icon} name="info" size="sm" />${t('new.summary.notes_sequential')}</div>
          </div>`}
          <div class="summary__actions">
            <${Button} variant="primary" size="lg" block icon="play" disabled=${!ready} loading=${starting} onClick=${start}>
              ${polish ? t('new.start_polish') : t('new.start')}
            <//>
            ${reason ? html`<div class="summary__reason">${reason}</div>` : html`<div class="summary__reason">${t('new.start_hint')}</div>`}
            <${Checkbox} checked=${d.remember} onChange=${(v) => update({ remember: v })}
              label=${html`<span class="small">${t('new.remember')}</span>`} />
          </div>
        </div>
      </aside>
    </div>

    ${dialog && dialog.kind === 'style' && html`<${StyleDialog} onClose=${() => setDialog(null)}
      onSaved=${(name) => { loadStyles(); update({ style: name }); }} />`}
    ${dialog && dialog.kind === 'extract' && html`<${GlossaryExtractDialog}
      file=${d.files.find((f) => f.status === 'ready')}
      sourceLanguage=${d.source} targetLanguage=${d.target}
      onClose=${() => setDialog(null)}
      onCreated=${(g) => { loadGlossaries(); update({ glossaryId: g.id }); }} />`}
    ${dialog && dialog.kind === 'connection' && html`<${ConnectionDialog} onClose=${() => setDialog(null)} onSaved=${() => loadConnections()} />`}
  </div>`;
}
