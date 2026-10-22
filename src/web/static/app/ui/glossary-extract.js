import { html, useState, useMemo } from './html.js';
import { Button, Callout, Spinner } from './core.js';
import { Dialog, toast } from './overlays.js';
import { Field, TextInput, NumberInput, Checkbox, Select } from './forms.js';
import { Dropzone } from './layout.js';
import { ModelPicker } from './model-picker.js';
import { glossariesApi, uploadsApi } from '../lib/api.js';
import { draft, preferences } from '../lib/stores.js';
import { t } from '../lib/i18n.js';
import { formatNumber } from '../lib/format.js';

export const TERM_TYPES = ['character', 'location', 'organization', 'item', 'title', 'other'];
export const typeOptions = () => [{ value: '', label: t('glossary.type.none') }, ...TERM_TYPES.map((c) => ({ value: c, label: t(`glossary.type.${c}`) }))];

/**
 * Find candidate terms in a book with the model and add the chosen ones.
 * With `glossary` the terms go there; otherwise a new glossary is created.
 * `file` is an uploaded file ({file_path, name}); without it the user picks one.
 */
export function GlossaryExtractDialog({ glossary, file: initialFile, sourceLanguage, targetLanguage, onClose, onCreated }) {
  const prefs = preferences.value || {};
  const d = draft.value;
  const [file, setFile] = useState(initialFile || null);
  const [uploading, setUploading] = useState(false);
  const [name, setName] = useState(initialFile ? t('glossary.extract.default_name', { book: initialFile.name.replace(/\.[^.]+$/, '') }) : '');
  const [samples, setSamples] = useState(10);
  const [chars, setChars] = useState(6000);
  const [model, setModel] = useState({
    connectionId: (d && d.connectionId) || prefs.default_connection_id || null,
    model: (d && d.model) || prefs.default_model || '',
  });
  const [phase, setPhase] = useState('setup'); // setup | running | review | adding
  const [result, setResult] = useState(null);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [target, setTarget] = useState(glossary);

  const src = glossary ? glossary.source_lang : sourceLanguage;
  const tgt = glossary ? glossary.target_lang : targetLanguage;
  const existing = useMemo(() => new Set(((glossary && glossary.terms) || []).map((x) => x.source)), [glossary]);

  const upload = async (files) => {
    const f = files[0];
    if (!f) return;
    setUploading(true);
    setError(null);
    try {
      const r = await uploadsApi.upload(f);
      setFile({ file_path: r.file_path, name: f.name });
      if (!glossary && !name) setName(t('glossary.extract.default_name', { book: f.name.replace(/\.[^.]+$/, '') }));
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  const run = async () => {
    setPhase('running');
    setError(null);
    try {
      let g = target;
      if (!g) {
        g = await glossariesApi.create({ name: name.trim(), source_lang: src || '', target_lang: tgt || '' });
        g = g.glossary || g;
        setTarget(g);
      }
      const form = new FormData();
      form.append('file_path', file.file_path);
      form.append('sample_count', String(samples));
      form.append('max_chars', String(chars));
      form.append('connection_id', model.connectionId || '');
      form.append('model', model.model || '');
      form.append('reasoning', 'off');
      if (src) form.append('source_lang', src);
      if (tgt) form.append('target_lang', tgt);
      const r = await glossariesApi.suggestTerms(g.id, form);
      setResult(r);
      setRows((r.candidates || []).map((c) => {
        const dup = c.already_in_glossary ?? existing.has(c.source);
        const same = (c.source || '').trim() === (c.target || '').trim();
        return { ...c, category: c.category || '', checked: !dup && !same, dup, same };
      }));
      setPhase('review');
    } catch (e) {
      setError(e.message);
      setPhase('setup');
    }
  };

  const add = async () => {
    const chosen = rows.filter((r) => r.checked).map((r) => ({ source: r.source, target: r.target, category: r.category || null }));
    setPhase('adding');
    try {
      const r = await glossariesApi.bulk(target.id, { action: 'add', terms: chosen });
      const conflicts = (r && r.conflicts && r.conflicts.length) || 0;
      toast({ tone: 'success', title: t('glossary.extract.added', { count: chosen.length - conflicts, n: formatNumber(chosen.length - conflicts) }) });
      onCreated && onCreated(target);
      onClose();
    } catch (e) {
      setError(e.message);
      setPhase('review');
    }
  };

  const setRow = (i, patch) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const checkedCount = rows.filter((r) => r.checked).length;
  const canRun = file && model.model && (glossary || name.trim()) && phase === 'setup';

  const footer = phase === 'review' && !rows.length
    ? html`<${Button} variant="ghost" onClick=${onClose}>${t('common.close')}<//>
        <${Button} variant="primary" icon="rotate-ccw" onClick=${() => setPhase('setup')}>${t('glossary.extract.retry')}<//>`
    : phase === 'review' || phase === 'adding'
    ? html`<span class="grow small muted">${t('glossary.extract.found', { count: rows.length, n: formatNumber(rows.length), fresh: formatNumber((result && result.new_count) ?? rows.filter((r) => !r.dup).length) })}</span>
        <${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>
        <${Button} variant="primary" loading=${phase === 'adding'} disabled=${!checkedCount} onClick=${add}>
          ${t('glossary.extract.add', { count: checkedCount, n: formatNumber(checkedCount) })}
        <//>`
    : html`<${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>
        <${Button} variant="primary" icon="sparkles" loading=${phase === 'running'} disabled=${!canRun} onClick=${run}>${t('glossary.extract.run')}<//>`;

  return html`<${Dialog} title=${t('glossary.extract.title')} desc=${t('glossary.extract.desc')} size=${phase === 'review' || phase === 'adding' ? 'xwide' : 'wide'} onClose=${onClose} footer=${footer}>
    ${error && html`<${Callout} tone="danger" class="stack">${error}<//>`}
    ${(phase === 'setup' || phase === 'running') && html`<div class="form-rows">
      ${!file
        ? html`<${Dropzone} multiple=${false} accept=".epub,.docx,.txt,.srt" disabled=${uploading}
            title=${uploading ? t('common.uploading') : t('glossary.extract.pick_file')} hint=${t('new.files.formats')} onFiles=${upload} />`
        : html`<div class="row small"><span class="muted">${t('glossary.extract.file')}</span><strong class="truncate">${file.name}</strong>
            ${!initialFile && html`<${Button} variant="link" onClick=${() => setFile(null)}>${t('common.change')}<//>`}</div>`}
      ${!glossary && html`<${Field} label=${t('glossary.extract.name')} htmlFor="extract-name">
        <${TextInput} id="extract-name" value=${name} onInput=${setName} />
      <//>`}
      <div class="field-grid">
        <${Field} label=${t('glossary.extract.samples')} htmlFor="extract-samples" help=${t('glossary.extract.samples_help')}>
          <${NumberInput} id="extract-samples" min=${1} max=${50} value=${samples} onCommit=${(v) => setSamples(v || 10)} />
        <//>
        <${Field} label=${t('glossary.extract.chars')} htmlFor="extract-chars" help=${t('glossary.extract.chars_help')}>
          <${NumberInput} id="extract-chars" min=${500} max=${6000} step=${500} value=${chars} onCommit=${(v) => setChars(v || 6000)} />
        <//>
      </div>
      <${Field} label=${t('glossary.extract.model')} htmlFor="extract-model" help=${t('glossary.extract.model_help')}>
        <${ModelPicker} id="extract-model" value=${model} onChange=${setModel} />
      <//>
      ${phase === 'running' && html`<div class="row muted"><${Spinner} />${t('glossary.extract.running')}</div>`}
    </div>`}
    ${(phase === 'review' || phase === 'adding') && html`<div class="stack">
      ${!rows.length && html`<${Callout} tone="info" title=${t('glossary.extract.none_title')}>${t('glossary.extract.none_body')}<//>`}
      ${rows.length > 0 && html`<div class="table-wrap" style="max-height:52vh;overflow:auto">
        <table class="table">
          <thead><tr>
            <th class="col-check"><${Checkbox} label=${t('common.select_all')} checked=${checkedCount === rows.length && rows.length > 0}
              indeterminate=${checkedCount > 0 && checkedCount < rows.length} onChange=${(v) => setRows(rows.map((r) => ({ ...r, checked: v })))} /></th>
            <th>${t('glossary.col.source')}</th><th>${t('glossary.col.target')}</th><th>${t('glossary.col.type')}</th><th></th>
          </tr></thead>
          <tbody>
            ${rows.map((r, i) => html`<tr style=${r.same ? 'opacity:.6' : ''}>
              <td class="col-check"><${Checkbox} label=${r.source} checked=${r.checked} onChange=${(v) => setRow(i, { checked: v })} /></td>
              <td>${r.source}</td>
              <td><input class="cell-input" value=${r.target} aria-label=${t('glossary.col.target')} onInput=${(e) => setRow(i, { target: e.currentTarget.value })} /></td>
              <td><${Select} class="input--sm" value=${r.category} options=${typeOptions()} onChange=${(v) => setRow(i, { category: v })} /></td>
              <td class="small faint">${r.dup ? t('glossary.extract.already') : r.same ? t('glossary.extract.same') : ''}</td>
            </tr>`)}
          </tbody>
        </table>
      </div>`}
    </div>`}
  <//>`;
}
