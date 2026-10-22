import { html, useState, useEffect, useRef } from '../ui/html.js';
import { Button, Icon, IconButton, Callout, Spinner, Pill } from '../ui/core.js';
import { Field, NumberInput, Segmented, Select } from '../ui/forms.js';
import { PageHeader, Section, Dropzone } from '../ui/layout.js';
import { toast } from '../ui/overlays.js';
import { ModelPicker, ReasoningControl } from '../ui/model-picker.js';
import { draft, preferences, glossaries, stylesList, notesList, loadGlossaries, loadStyles, loadNotes, savePreferences } from '../lib/stores.js';
import { compareApi, uploadsApi } from '../lib/api.js';
import { onSocket } from '../lib/socket.js';
import { navigate } from '../lib/router.js';
import { LANGUAGES } from '../lib/languages.js';
import { t } from '../lib/i18n.js';
import { formatNumber, formatCost } from '../lib/format.js';
import { displayName } from '../lib/names.js';

let colSeq = 0;
const newColumn = (base = {}) => ({ id: ++colSeq, connectionId: base.connectionId || null, model: base.model || '', reasoning: base.reasoning || 'off', style: base.style || '' });

function fromDraft() {
  const d = draft.value;
  if (!d) return null;
  const f = d.files.find((x) => x.status === 'ready');
  if (!f) return null;
  return {
    file: { file_path: f.file_path, name: f.name, file_type: f.file_type },
    source: d.source, target: d.target,
    mode: d.task === 'polish' ? 'refine' : d.polishAfter ? 'translate_refine' : 'translate',
    maxChars: Math.min(2000, Math.max(200, (d.passageTokens || 450) * 4)),
    glossaryId: d.glossaryId, notes: d.notes.mode === 'copy' ? d.notes.source : '',
    columns: [newColumn({ connectionId: d.connectionId, model: d.model, reasoning: d.reasoning, style: d.style })],
  };
}

function CellMetrics({ m }) {
  if (!m) return null;
  return html`<div class="compare-cell__metrics">
    ${m.latency_ms != null && html`<span>${formatNumber(Math.round(m.latency_ms / 100) / 10)} s</span>`}
    ${(m.prompt_tokens || m.completion_tokens) ? html`<span>${t('compare.tokens', { input: formatNumber(m.prompt_tokens || 0), output: formatNumber(m.completion_tokens || 0) })}</span>` : null}
    ${m.cost_usd != null && html`<span>${formatCost(m.cost_usd)}</span>`}
    ${m.was_truncated && html`<${Pill} tone="warning">${t('compare.truncated')}<//>`}
    ${m.was_fallback && html`<${Pill} tone="warning">${t('compare.fallback')}<//>`}
  </div>`;
}

export function ComparePage({ query }) {
  const prefs = preferences.value || {};
  const init = (query && query.from === 'draft' && fromDraft()) || null;
  const [file, setFile] = useState(init ? init.file : null);
  const [uploading, setUploading] = useState(false);
  const [source, setSource] = useState(init ? init.source : '');
  const [target, setTarget] = useState(init ? init.target : (prefs.target_language || ''));
  const [mode, setMode] = useState(init ? init.mode : 'translate');
  const [n, setN] = useState(5);
  const [maxChars, setMaxChars] = useState(init ? init.maxChars : 1200);
  const [glossaryId, setGlossaryId] = useState(init ? init.glossaryId : null);
  const [notes, setNotes] = useState(init ? init.notes : '');
  const [columns, setColumns] = useState(init ? init.columns : [newColumn({ connectionId: prefs.default_connection_id, model: prefs.default_model })]);
  const [items, setItems] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [results, setResults] = useState({}); // `${row}:${col}:${phase}` -> {output, metrics, error}
  const [run, setRun] = useState(null); // {id, running}
  const [error, setError] = useState(null);
  const runRef = useRef(null);
  runRef.current = run;

  useEffect(() => {
    if (glossaries.value === null) loadGlossaries().catch(() => {});
    if (stylesList.value === null) loadStyles().catch(() => {});
    if (notesList.value === null) loadNotes().catch(() => {});
  }, []);
  useEffect(() => onSocket('sample_update', (msg) => {
    const r = runRef.current;
    if (!r || !msg || msg.sample_id !== r.id) return;
    if (msg.type === 'cell_done' || msg.type === 'cell_error') {
      setResults((cur) => ({ ...cur, [`${msg.row}:${msg.col}:${msg.phase || 'translate'}`]: { output: msg.output, metrics: msg.metrics, error: msg.error } }));
    } else if (msg.type === 'sample_done' || msg.type === 'sample_stopped') {
      setRun((cur) => (cur ? { ...cur, running: false } : cur));
    }
  }), []);

  const upload = async (files) => {
    const f = files[0];
    if (!f) return;
    setUploading(true);
    setError(null);
    try {
      const r = await uploadsApi.upload(f);
      setFile({ file_path: r.file_path, name: f.name, file_type: r.file_type });
      if (!source && r.detected_language) setSource(r.detected_language);
      setItems(null);
      setResults({});
    } catch (e) { setError(e.message); } finally { setUploading(false); }
  };

  const pickPassages = async () => {
    setError(null);
    try {
      const r = await compareApi.initialize({ file_path: file.file_path, file_type: file.file_type, n_samples: n, max_chars: maxChars });
      setItems(r.items || []);
      setWarnings(r.warnings || []);
      setResults({});
    } catch (e) { setError(e.message); }
  };
  const addPassage = async () => {
    try {
      const r = await compareApi.extract({ file_path: file.file_path, file_type: file.file_type, max_chars: maxChars, exclude_indices: (items || []).map((x) => x.index) });
      setItems([...(items || []), r.item]);
    } catch (e) {
      toast({ tone: e.status === 409 ? 'info' : 'error', title: e.status === 409 ? t('compare.no_more') : t('errors.action_failed'), message: e.status === 409 ? '' : e.message });
    }
  };

  const start = async () => {
    setError(null);
    setResults({});
    try {
      const r = await compareApi.run({
        file_path: file.file_path, file_type: file.file_type,
        source_language: mode === 'refine' ? target : source, target_language: target,
        mode, n_samples: n, max_chars: maxChars, items,
        glossary_id: glossaryId || undefined, notes: notes || undefined,
        columns: columns.map((c) => ({ connection_id: c.connectionId, model: c.model, reasoning: c.reasoning, style: c.style || undefined })),
      });
      if (r.items) setItems(r.items);
      if (r.warnings) setWarnings(r.warnings);
      setRun({ id: r.sample_id, running: true });
      if (r.deferred) await compareApi.dispatch(r.sample_id, {});
    } catch (e) { setError(e.message); }
  };
  const stop = async () => {
    if (!run) return;
    try { await compareApi.stop(run.id); } catch { /* already finished */ }
    setRun({ ...run, running: false });
  };

  const useModel = async (c) => {
    if (draft.value) {
      draft.value = { ...draft.value, connectionId: c.connectionId, model: c.model, reasoning: c.reasoning };
      toast({ tone: 'success', title: t('compare.used_in_draft', { model: c.model }) });
      navigate('/new');
    } else {
      try { await savePreferences({ default_connection_id: c.connectionId, default_model: c.model, default_reasoning: c.reasoning }); toast({ tone: 'success', title: t('compare.used_default', { model: c.model }) }); }
      catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
    }
  };

  const phases = mode === 'translate_refine' ? ['translate', 'refine'] : [mode === 'refine' ? 'refine' : 'translate'];
  const lastPhase = phases[phases.length - 1];
  const ready = file && target.trim() && columns.length && columns.every((c) => c.model);
  const colStats = columns.map((c, ci) => {
    const cells = (items || []).map((_, ri) => phases.map((p) => results[`${ri}:${ci}:${p}`]).filter(Boolean)).flat();
    const lat = cells.filter((x) => x.metrics && x.metrics.latency_ms != null).map((x) => x.metrics.latency_ms);
    const cost = cells.reduce((a, x) => a + ((x.metrics && x.metrics.cost_usd) || 0), 0);
    const costKnown = cells.some((x) => x.metrics && x.metrics.cost_usd != null);
    return { done: cells.length, failed: cells.filter((x) => x.error).length, avg: lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : null, cost: costKnown ? cost : null };
  });
  const langOptions = LANGUAGES.map((l) => html`<option value=${l.value}>${t(`lang.name.${l.code}`)}</option>`);

  return html`<div class="page" style="max-width:1280px">
    <${PageHeader} title=${t('compare.title')} subtitle=${t('compare.subtitle')} />
    <datalist id="cmp-langs">${langOptions}</datalist>
    ${error && html`<${Callout} tone="danger" class="group">${error}<//>`}

    <${Section} step="1" title=${t('compare.setup')}>
      <div class="form-rows">
        ${file
          ? html`<div class="row"><${Icon} name="file" /><strong class="truncate">${file.name}</strong>
              <${Button} variant="link" onClick=${() => { setFile(null); setItems(null); setResults({}); }}>${t('common.change')}<//></div>`
          : html`<${Dropzone} multiple=${false} accept=".epub,.docx,.txt,.srt" disabled=${uploading}
              title=${uploading ? t('common.uploading') : t('compare.drop')} hint=${t('new.files.formats')} onFiles=${upload} />`}
        <div class="field-grid">
          ${mode !== 'refine' && html`<${Field} label=${t('new.lang.from')} htmlFor="cmp-src">
            <input id="cmp-src" class="input" list="cmp-langs" value=${source} placeholder=${t('new.lang.detect')} onInput=${(e) => setSource(e.currentTarget.value)} />
          <//>`}
          <${Field} label=${mode === 'refine' ? t('new.lang.language') : t('new.lang.to')} htmlFor="cmp-tgt">
            <input id="cmp-tgt" class="input" list="cmp-langs" value=${target} onInput=${(e) => setTarget(e.currentTarget.value)} />
          <//>
        </div>
        <${Field} label=${t('compare.mode')}>
          <${Segmented} label=${t('compare.mode')} value=${mode} onChange=${(v) => { setMode(v); setResults({}); }} options=${[
            { value: 'translate', label: t('compare.mode_translate') },
            { value: 'translate_refine', label: t('compare.mode_both') },
            { value: 'refine', label: t('compare.mode_polish') },
          ]} />
        <//>
        <div class="field-grid">
          <${Field} label=${t('new.glossary.label')} htmlFor="cmp-glossary">
            <${Select} id="cmp-glossary" value=${glossaryId ? String(glossaryId) : ''} onChange=${(v) => setGlossaryId(v ? Number(v) : null)}
              options=${[{ value: '', label: t('common.none') }, ...((glossaries.value || []).map((g) => ({ value: String(g.id), label: g.name })))]} />
          <//>
          <${Field} label=${t('compare.notes')} htmlFor="cmp-notes" help=${t('compare.notes_help')}>
            <${Select} id="cmp-notes" value=${notes} onChange=${setNotes}
              options=${[{ value: '', label: t('common.none') }, ...((notesList.value || []).map((x) => ({ value: x.name, label: displayName(x.name) })))]} />
          <//>
        </div>
      </div>
    <//>

    <${Section} step="2" title=${t('compare.passages')} desc=${t('compare.passages_desc')}
      aside=${items && html`<${Button} size="sm" icon="plus" onClick=${addPassage}>${t('compare.add_passage')}<//>`}>
      <div class="stack">
        <div class="row row--wrap" style="--gap:16px;align-items:flex-end">
          <${Field} label=${t('compare.count')} htmlFor="cmp-n"><${NumberInput} id="cmp-n" min=${2} max=${20} value=${n} onCommit=${(v) => setN(v || 5)} /><//>
          <${Field} label=${t('compare.length')} htmlFor="cmp-len"><${NumberInput} id="cmp-len" min=${50} max=${2000} step=${50} value=${maxChars} onCommit=${(v) => setMaxChars(v || 1200)} suffix=${t('new.advanced.chars')} /><//>
          <${Button} icon="shuffle" disabled=${!file} onClick=${pickPassages}>${items ? t('compare.repick') : t('compare.pick')}<//>
        </div>
        <p class="small muted">${t('compare.honest')}</p>
        ${warnings.length > 0 && html`<${Callout} tone="warning">${warnings.map((w) => (typeof w === 'string' ? w : t(`compare.warning.${w.code}`, w.params || {}))).join(' ')}<//>`}
      </div>
    <//>

    <${Section} step="3" title=${t('compare.models')}
      aside=${html`<${Button} size="sm" icon="plus" onClick=${() => setColumns([...columns, newColumn()])}>${t('compare.add_model')}<//>`}>
      <div class="stack">
        ${columns.map((c, i) => html`<div class="card card__body stack" style="--gap:10px" key=${c.id}>
          <div class="row row--between"><strong>${t('compare.model_n', { n: i + 1 })}</strong>
            <${IconButton} icon="x" size="sm" label=${t('compare.remove_model')} disabled=${columns.length === 1}
              onClick=${() => setColumns(columns.filter((x) => x.id !== c.id))} /></div>
          <div class="field-grid">
            <${ModelPicker} value=${{ connectionId: c.connectionId, model: c.model }}
              onChange=${(v) => setColumns(columns.map((x) => (x.id === c.id ? { ...x, connectionId: v.connectionId, model: v.model } : x)))} />
            <${Select} value=${c.style} aria-label=${t('new.style.label')} onChange=${(v) => setColumns(columns.map((x) => (x.id === c.id ? { ...x, style: v } : x)))}
              options=${[{ value: '', label: t('compare.no_style') }, ...((stylesList.value || []).map((s) => ({ value: s.name, label: s.display_name || displayName(s.name) })))]} />
          </div>
          ${c.connectionId && html`<${ReasoningControl} connectionId=${c.connectionId} value=${c.reasoning}
            onChange=${(v) => setColumns(columns.map((x) => (x.id === c.id ? { ...x, reasoning: v } : x)))} />`}
        </div>`)}
        <div class="row">
          ${run && run.running
            ? html`<${Button} variant="danger" icon="square" onClick=${stop}>${t('compare.stop')}<//><span class="small muted">${t('compare.stop_note')}</span>`
            : html`<${Button} variant="primary" icon="play" disabled=${!ready} onClick=${start}>${t('compare.run')}<//>`}
        </div>
      </div>
    <//>

    ${items && items.length > 0 && html`<section class="section">
      <h2 class="section__title" style="margin-bottom:14px">${t('compare.results')}</h2>
      <div class="compare-grid" style=${{ gridTemplateColumns: `minmax(260px, 1fr) repeat(${columns.length}, minmax(280px, 1fr))` }}>
        <div class="compare-cell compare-cell--source compare-cell--head strong">${t('compare.original')}</div>
        ${columns.map((c, i) => html`<div class="compare-cell compare-cell--head">
          <div class="strong truncate">${c.model || t('compare.model_n', { n: i + 1 })}</div>
          <div class="small muted">${t(`reasoning.${c.reasoning}`)}${c.style ? ` · ${displayName(c.style)}` : ''}</div>
        </div>`)}
        ${items.map((it, ri) => html`
          <div class="compare-cell compare-cell--source"><div class="compare-cell__text">${it.source_text}</div></div>
          ${columns.map((c, ci) => {
            const r = results[`${ri}:${ci}:${lastPhase}`];
            const draftR = phases.length > 1 ? results[`${ri}:${ci}:translate`] : null;
            return html`<div class="compare-cell">
              ${!r && !(draftR && draftR.error) && (run && run.running ? html`<div class="row small muted"><${Spinner} size="sm" />${t('compare.waiting')}</div>` : html`<span class="faint small">—</span>`)}
              ${draftR && draftR.error && html`<div class="small" style="color:var(--danger)">${draftR.error}</div>`}
              ${r && (r.error ? html`<div class="small" style="color:var(--danger)">${r.error}</div>` : html`<div class="compare-cell__text">${r.output}</div>`)}
              <${CellMetrics} m=${r && r.metrics} />
            </div>`;
          })}
        `)}
        <div class="compare-cell compare-cell--source small muted">${t('compare.summary')}</div>
        ${columns.map((c, ci) => {
          const s = colStats[ci];
          return html`<div class="compare-cell stack" style="--gap:6px">
            <div class="small muted">
              ${s.avg != null ? t('compare.avg_latency', { s: formatNumber(Math.round(s.avg / 100) / 10) }) : ''}
              ${s.cost != null ? ` · ${formatCost(s.cost)}` : ''}
              ${s.failed ? ` · ${t('compare.failures', { count: s.failed, n: formatNumber(s.failed) })}` : ''}
            </div>
            <${Button} size="sm" variant="primary" disabled=${!c.model} onClick=${() => useModel(c)}>${t('compare.use')}<//>
          </div>`;
        })}
      </div>
    </section>`}
  </div>`;
}
