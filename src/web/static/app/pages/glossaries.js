import { html, useState, useEffect, useMemo } from '../ui/html.js';
import { Button, Icon, IconButton, Callout, EmptyState, SavedIndicator } from '../ui/core.js';
import { Field, TextInput, Textarea, Select, Checkbox, Segmented } from '../ui/forms.js';
import { PageHeader, Dropzone } from '../ui/layout.js';
import { Menu, Dialog, confirm, toast } from '../ui/overlays.js';
import { GlossaryExtractDialog, typeOptions } from '../ui/glossary-extract.js';
import { glossaries, loadGlossaries } from '../lib/stores.js';
import { glossariesApi } from '../lib/api.js';
import { downloadUrl } from '../lib/api-core.js';
import { navigate } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { formatRelativeTime, formatNumber } from '../lib/format.js';
import { LANGUAGES } from '../lib/languages.js';

const langPairText = (g) => (g.source_lang || g.target_lang) ? `${g.source_lang || '—'} → ${g.target_lang || '—'}` : t('glossary.any_language');

function ImportDialog({ glossary, onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [mode, setMode] = useState('merge');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await glossariesApi.importFile(glossary.id, file, mode);
      toast({ tone: 'success', title: t('glossary.import.done', { inserted: formatNumber(r.imported ?? 0), skipped: formatNumber((r.skipped_empty ?? 0) + (r.skipped_duplicate ?? 0)) }) });
      onDone();
      onClose();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return html`<${Dialog} title=${t('glossary.import.title')} onClose=${onClose} footer=${html`
      <${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>
      <${Button} variant="primary" loading=${busy} disabled=${!file} onClick=${run}>${t('glossary.import.run')}<//>`}>
    <div class="form-rows">
      ${error && html`<${Callout} tone="danger">${error}<//>`}
      ${file
        ? html`<div class="row"><${Icon} name="file" /><span class="grow truncate">${file.name}</span><${Button} variant="link" onClick=${() => setFile(null)}>${t('common.change')}<//></div>`
        : html`<${Dropzone} multiple=${false} accept=".csv,.json" title=${t('glossary.import.drop')} hint=${t('glossary.import.hint')} onFiles=${(f) => setFile(f[0])} />`}
      <${Field} label=${t('glossary.import.mode')}>
        <${Segmented} label=${t('glossary.import.mode')} value=${mode} onChange=${setMode} options=${[
          { value: 'merge', label: t('glossary.import.merge') },
          { value: 'replace', label: t('glossary.import.replace') },
        ]} />
        <div class="field__help">${mode === 'merge' ? t('glossary.import.merge_help') : t('glossary.import.replace_help')}</div>
      <//>
    </div>
  <//>`;
}

function TestDialog({ glossary, onClose }) {
  const [text, setText] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setResult(await glossariesApi.previewBlock(glossary.id, text)); }
    catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
    finally { setBusy(false); }
  };
  return html`<${Dialog} title=${t('glossary.test.title')} desc=${t('glossary.test.desc')} size="wide" onClose=${onClose}
    footer=${html`<${Button} variant="ghost" onClick=${onClose}>${t('common.close')}<//><${Button} variant="primary" loading=${busy} disabled=${!text.trim()} onClick=${run}>${t('glossary.test.run')}<//>`}>
    <div class="form-rows">
      <${Textarea} rows=${6} variant="book" value=${text} onInput=${setText} placeholder=${t('glossary.test.placeholder')} aria-label=${t('glossary.test.title')} data-autofocus />
      ${result && html`<div class="stack">
        <div class="small muted">${t('glossary.test.matched', { matched: formatNumber(result.matched_count ?? result.matched ?? 0), total: formatNumber(result.total_terms ?? result.total ?? 0) })}</div>
        ${result.capped && html`<${Callout} tone="warning">${t('glossary.test.capped')}<//>`}
        <pre class="card card--flat mono small" style="padding:12px;white-space:pre-wrap;margin:0">${result.block || t('glossary.test.no_match')}</pre>
      </div>`}
    </div>
  <//>`;
}

export function GlossariesPage() {
  const [importFor, setImportFor] = useState(null);
  useEffect(() => { loadGlossaries().catch(() => {}); }, []);
  const list = glossaries.value;
  const create = async () => {
    try {
      const g = await glossariesApi.create({ name: t('glossary.new_name') });
      await loadGlossaries();
      navigate(`/glossaries/${g.id}`);
    } catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  const remove = async (g) => {
    const ok = await confirm({ title: t('glossary.confirm.delete_title', { name: g.name }), body: t('glossary.confirm.delete_body'), confirmLabel: t('common.delete'), danger: true });
    if (!ok) return;
    try { await glossariesApi.remove(g.id); await loadGlossaries(); toast({ tone: 'success', title: t('glossary.toast.deleted') }); }
    catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  const duplicate = async (g) => {
    try { await glossariesApi.duplicate(g.id); await loadGlossaries(); toast({ tone: 'success', title: t('glossary.toast.duplicated') }); }
    catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  return html`<div class="page">
    <${PageHeader} title=${t('glossary.title')} subtitle=${t('glossary.subtitle')}
      actions=${html`<${Button} variant="primary" icon="plus" onClick=${create}>${t('glossary.new')}<//>`} />
    ${list === null && html`<p class="muted">${t('common.loading')}</p>`}
    ${list && !list.length && html`<${EmptyState} icon="book-a" title=${t('glossary.empty_title')}
      actions=${html`<${Button} variant="primary" icon="plus" onClick=${create}>${t('glossary.new')}<//>`}>${t('glossary.empty_desc')}<//>`}
    ${list && list.length > 0 && html`<div class="table-wrap"><table class="table table--clickable">
      <thead><tr><th>${t('glossary.col.name')}</th><th>${t('glossary.col.languages')}</th><th>${t('glossary.col.terms')}</th><th>${t('glossary.col.updated')}</th><th class="col-actions"></th></tr></thead>
      <tbody>${list.map((g) => html`<tr onClick=${() => navigate(`/glossaries/${g.id}`)}>
        <td class="strong">${g.name}</td>
        <td class="muted">${langPairText(g)}</td>
        <td class="num">${formatNumber(g.term_count || 0)}</td>
        <td class="muted">${g.updated_at ? formatRelativeTime(g.updated_at) : '—'}</td>
        <td class="col-actions" onClick=${(e) => e.stopPropagation()}><${Menu} items=${[
          { label: t('glossary.import.title'), icon: 'file-up', onSelect: () => setImportFor(g) },
          { label: t('common.duplicate'), icon: 'copy', onSelect: () => duplicate(g) },
          'sep',
          { label: t('common.delete'), icon: 'trash-2', danger: true, onSelect: () => remove(g) },
        ]} /></td>
      </tr>`)}</tbody>
    </table></div>`}
    ${importFor && html`<${ImportDialog} glossary=${importFor} onClose=${() => setImportFor(null)} onDone=${loadGlossaries} />`}
  </div>`;
}

const cmp = (a, b) => String(a || '').localeCompare(String(b || ''));

export function GlossaryPage({ id }) {
  const [g, setG] = useState(null);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null);
  const [saveState, setSaveState] = useState(null);
  const [filter, setFilter] = useState('');
  const [sort, setSort] = useState(null); // {col, dir}
  const [selected, setSelected] = useState(new Set());
  const [bulkType, setBulkType] = useState('');
  const [newRow, setNewRow] = useState({ source: '', target: '', category: '' });
  const [dialog, setDialog] = useState(null);

  const load = () => glossariesApi.get(id).then((x) => {
    setG(x);
    setMeta({ name: x.name, source_lang: x.source_lang || '', target_lang: x.target_lang || '' });
    setError(null);
  }).catch(setError);
  useEffect(() => { setG(null); setSelected(new Set()); load(); }, [id]);

  const saveMeta = async (patch) => {
    const next = { ...meta, ...patch };
    setMeta(next);
    setSaveState('saving');
    try { await glossariesApi.update(g.id, next); setSaveState('saved'); loadGlossaries().catch(() => {}); }
    catch (e) { setSaveState('error'); toast({ tone: 'error', title: t('common.save_failed'), message: e.message }); }
  };
  const updateTerm = async (term, patch) => {
    if (Object.keys(patch).every((k) => (term[k] || '') === (patch[k] || ''))) return;
    setSaveState('saving');
    try {
      const updated = await glossariesApi.updateTerm(g.id, term.id, { ...term, ...patch });
      setG({ ...g, terms: g.terms.map((x) => (x.id === term.id ? { ...x, ...(updated.term || updated) } : x)) });
      setSaveState('saved');
    } catch (e) {
      setSaveState('error');
      toast({ tone: 'error', title: t('common.save_failed'), message: e.message });
      load();
    }
  };
  const addTerm = async () => {
    if (!newRow.source.trim()) return;
    try {
      const created = await glossariesApi.addTerm(g.id, { ...newRow, source: newRow.source.trim(), target: newRow.target.trim(), category: newRow.category || null });
      setG({ ...g, terms: [...g.terms, created.term || created] });
      setNewRow({ source: '', target: '', category: '' });
      setSaveState('saved');
      document.getElementById('new-term-source')?.focus();
    } catch (e) { toast({ tone: 'error', title: t('glossary.toast.add_failed'), message: e.message }); }
  };
  const removeTerms = async (ids) => {
    const ok = await confirm({ title: t('glossary.confirm.delete_terms', { count: ids.length, n: formatNumber(ids.length) }), confirmLabel: t('common.delete'), danger: true });
    if (!ok) return;
    try {
      if (ids.length === 1) await glossariesApi.removeTerm(g.id, ids[0]);
      else await glossariesApi.bulk(g.id, { action: 'delete', term_ids: ids });
      setG({ ...g, terms: g.terms.filter((x) => !ids.includes(x.id)) });
      setSelected(new Set());
    } catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  const setTypes = async () => {
    const ids = [...selected];
    try {
      await glossariesApi.bulk(g.id, { action: 'set_category', term_ids: ids, category: bulkType });
      setG({ ...g, terms: g.terms.map((x) => (selected.has(x.id) ? { ...x, category: bulkType } : x)) });
      setSelected(new Set());
    } catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  const removeGlossary = async () => {
    const ok = await confirm({ title: t('glossary.confirm.delete_title', { name: g.name }), body: t('glossary.confirm.delete_body'), confirmLabel: t('common.delete'), danger: true });
    if (!ok) return;
    try { await glossariesApi.remove(g.id); await loadGlossaries(); navigate('/glossaries'); }
    catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };

  const rows = useMemo(() => {
    if (!g) return [];
    const q = filter.trim().toLocaleLowerCase();
    let out = q ? g.terms.filter((x) => `${x.source} ${x.target} ${x.category}`.toLocaleLowerCase().includes(q)) : g.terms;
    if (sort) out = [...out].sort((a, b) => cmp(a[sort.col], b[sort.col]) * (sort.dir === 'asc' ? 1 : -1));
    return out;
  }, [g, filter, sort]);

  if (error) return html`<div class="page"><${Callout} tone="danger">${error.message}<//></div>`;
  if (!g || !meta) return html`<div class="page"><p class="muted">${t('common.loading')}</p></div>`;

  const toggleSort = (col) => setSort(!sort || sort.col !== col ? { col, dir: 'asc' } : sort.dir === 'asc' ? { col, dir: 'desc' } : null);
  const SortTh = ({ col, label }) => html`<th aria-sort=${sort && sort.col === col ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
    <button type="button" class="th-sort" onClick=${() => toggleSort(col)}>${label}
      <${Icon} name=${sort && sort.col === col ? (sort.dir === 'asc' ? 'chevron-up' : 'chevron-down') : 'arrow-up-down'} size="sm" />
    </button></th>`;
  const allVisibleSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const langOptions = [{ value: '', label: t('glossary.any_language') }, ...LANGUAGES.map((l) => ({ value: l.value, label: t(`lang.name.${l.code}`) }))];
  const withCurrent = (opts, v) => (v && !opts.some((o) => o.value === v) ? [...opts, { value: v, label: v }] : opts);

  return html`<div class="page">
    <${PageHeader} title=${meta.name || t('glossary.untitled')} back=${{ href: '#/glossaries', label: t('glossary.title') }}
      actions=${html`<${SavedIndicator} state=${saveState} />
        <${Button} icon="sparkles" onClick=${() => setDialog('extract')}>${t('glossary.extract.title')}<//>
        <${Menu} items=${[
          { label: t('glossary.import.title'), icon: 'file-up', onSelect: () => setDialog('import') },
          { label: t('glossary.export_csv'), icon: 'file-down', onSelect: () => downloadUrl(glossariesApi.exportPath(g.id, 'csv')) },
          { label: t('glossary.export_json'), icon: 'file-down', onSelect: () => downloadUrl(glossariesApi.exportPath(g.id, 'json')) },
          { label: t('glossary.test.title'), icon: 'search', onSelect: () => setDialog('test') },
          'sep',
          { label: t('glossary.delete'), icon: 'trash-2', danger: true, onSelect: removeGlossary },
        ]} />`} />

    <div class="field-grid" style="grid-template-columns:2fr 1fr 1fr;margin-bottom:20px">
      <${Field} label=${t('glossary.field.name')} htmlFor="g-name">
        <${TextInput} id="g-name" value=${meta.name} onInput=${(v) => setMeta({ ...meta, name: v })} onCommit=${(v) => v.trim() && saveMeta({ name: v.trim() })} />
      <//>
      <${Field} label=${t('glossary.field.source')} htmlFor="g-src">
        <${Select} id="g-src" value=${meta.source_lang} options=${withCurrent(langOptions, meta.source_lang)} onChange=${(v) => saveMeta({ source_lang: v })} />
      <//>
      <${Field} label=${t('glossary.field.target')} htmlFor="g-tgt">
        <${Select} id="g-tgt" value=${meta.target_lang} options=${withCurrent(langOptions, meta.target_lang)} onChange=${(v) => saveMeta({ target_lang: v })} />
      <//>
    </div>

    <p class="small muted" style="margin-bottom:12px">${t('glossary.help')}</p>

    <div class="toolbar">
      <div class="input-affix toolbar__search">
        <${Icon} name="search" size="sm" />
        <input class="input" type="search" placeholder=${t('glossary.filter')} aria-label=${t('glossary.filter')} value=${filter} onInput=${(e) => setFilter(e.currentTarget.value)} />
      </div>
      <span class="small muted">${t('glossary.count', { shown: formatNumber(rows.length), total: formatNumber(g.terms.length) })}</span>
      ${selected.size > 0 && html`<div class="row" style="margin-left:auto">
        <span class="small">${t('glossary.selected', { count: selected.size, n: formatNumber(selected.size) })}</span>
        <${Select} class="input--sm" value=${bulkType} options=${typeOptions()} onChange=${setBulkType} aria-label=${t('glossary.col.type')} />
        <${Button} size="sm" onClick=${setTypes}>${t('glossary.set_type')}<//>
        <${Button} size="sm" variant="danger-ghost" icon="trash-2" onClick=${() => removeTerms([...selected])}>${t('common.delete')}<//>
        <${Button} size="sm" variant="ghost" onClick=${() => setSelected(new Set())}>${t('common.clear')}<//>
      </div>`}
    </div>

    <div class="table-wrap">
      <table class="table">
        <thead><tr>
          <th class="col-check"><${Checkbox} label=${t('common.select_all')} checked=${allVisibleSelected}
            indeterminate=${!allVisibleSelected && rows.some((r) => selected.has(r.id))}
            onChange=${(v) => setSelected(v ? new Set([...selected, ...rows.map((r) => r.id)]) : new Set([...selected].filter((x) => !rows.some((r) => r.id === x))))} /></th>
          <${SortTh} col="source" label=${t('glossary.col.source')} />
          <${SortTh} col="target" label=${t('glossary.col.target')} />
          <${SortTh} col="category" label=${t('glossary.col.type')} />
          <th class="col-actions"></th>
        </tr></thead>
        <tbody>
          <tr>
            <td class="col-check"><${Icon} name="plus" size="sm" class="faint" /></td>
            <td><input id="new-term-source" class="cell-input" placeholder=${t('glossary.new_source')} value=${newRow.source}
              onInput=${(e) => setNewRow({ ...newRow, source: e.currentTarget.value })} onKeyDown=${(e) => { if (e.key === 'Enter') addTerm(); }} aria-label=${t('glossary.new_source')} /></td>
            <td><input class="cell-input" placeholder=${t('glossary.new_target')} value=${newRow.target}
              onInput=${(e) => setNewRow({ ...newRow, target: e.currentTarget.value })} onKeyDown=${(e) => { if (e.key === 'Enter') addTerm(); }} aria-label=${t('glossary.new_target')} /></td>
            <td><${Select} class="input--sm" value=${newRow.category} options=${typeOptions()} onChange=${(v) => setNewRow({ ...newRow, category: v })} aria-label=${t('glossary.col.type')} /></td>
            <td class="col-actions"><${Button} size="sm" disabled=${!newRow.source.trim()} onClick=${addTerm}>${t('common.add')}<//></td>
          </tr>
          ${rows.map((x) => html`<tr key=${x.id}>
            <td class="col-check"><${Checkbox} label=${x.source} checked=${selected.has(x.id)}
              onChange=${(v) => { const s = new Set(selected); if (v) s.add(x.id); else s.delete(x.id); setSelected(s); }} /></td>
            <td><input class="cell-input" value=${x.source} aria-label=${t('glossary.col.source')}
              onChange=${(e) => { const v = e.currentTarget.value.trim(); if (v) updateTerm(x, { source: v }); else e.currentTarget.value = x.source; }} /></td>
            <td><input class="cell-input" value=${x.target} aria-label=${t('glossary.col.target')} onChange=${(e) => updateTerm(x, { target: e.currentTarget.value.trim() })} /></td>
            <td><${Select} class="input--sm" value=${x.category || ''} options=${typeOptions()} aria-label=${t('glossary.col.type')} onChange=${(v) => updateTerm(x, { category: v })} /></td>
            <td class="col-actions"><${IconButton} icon="trash-2" size="sm" label=${t('glossary.delete_term', { term: x.source })} onClick=${() => removeTerms([x.id])} /></td>
          </tr>`)}
        </tbody>
      </table>
    </div>
    ${!g.terms.length && html`<p class="muted small" style="margin-top:12px">${t('glossary.no_terms')}</p>`}

    ${dialog === 'import' && html`<${ImportDialog} glossary=${g} onClose=${() => setDialog(null)} onDone=${load} />`}
    ${dialog === 'test' && html`<${TestDialog} glossary=${g} onClose=${() => setDialog(null)} />`}
    ${dialog === 'extract' && html`<${GlossaryExtractDialog} glossary=${g} onClose=${() => setDialog(null)} onCreated=${load} />`}
  </div>`;
}
