import { html, useState, useEffect } from '../ui/html.js';
import { Button, Callout, EmptyState, Pill, SavedIndicator } from '../ui/core.js';
import { Field, TextInput, Textarea } from '../ui/forms.js';
import { PageHeader } from '../ui/layout.js';
import { Menu, confirm, toast } from '../ui/overlays.js';
import { StyleDialog } from '../ui/style-dialog.js';
import { stylesList, loadStyles } from '../lib/stores.js';
import { stylesApi, foldersApi } from '../lib/api.js';
import { navigate } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { formatRelativeTime } from '../lib/format.js';

export function StylesPage() {
  const [creating, setCreating] = useState(false);
  useEffect(() => { loadStyles().catch(() => {}); }, []);
  const list = stylesList.value;
  const act = async (fn, msg) => {
    try { await fn(); await loadStyles(); toast({ tone: 'success', title: msg }); }
    catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  const remove = async (s) => {
    const ok = await confirm({ title: t('styles.confirm.delete_title', { name: s.name }), body: t('styles.confirm.delete_body'), confirmLabel: t('common.delete'), danger: true });
    if (ok) act(() => stylesApi.remove(s.name), t('styles.toast.deleted'));
  };
  return html`<div class="page">
    <${PageHeader} title=${t('styles.title')} subtitle=${t('styles.subtitle')} actions=${html`
      <${Button} icon="folder-open" onClick=${() => foldersApi.open('styles').catch(() => {})}>${t('common.open_folder')}<//>
      <${Button} variant="primary" icon="plus" onClick=${() => setCreating(true)}>${t('styles.new')}<//>`} />
    ${list === null && html`<p class="muted">${t('common.loading')}</p>`}
    ${list && !list.length && html`<${EmptyState} icon="feather" title=${t('styles.empty_title')}
      actions=${html`<${Button} variant="primary" icon="plus" onClick=${() => setCreating(true)}>${t('styles.new')}<//>`}>${t('styles.empty_desc')}<//>`}
    ${list && list.length > 0 && html`<div class="table-wrap"><table class="table table--clickable">
      <thead><tr><th>${t('styles.col.name')}</th><th>${t('styles.col.covers')}</th><th>${t('styles.col.updated')}</th><th class="col-actions"></th></tr></thead>
      <tbody>${list.map((s) => html`<tr onClick=${() => navigate(`/styles/${encodeURIComponent(s.name)}`)}>
        <td class="strong">${s.name}</td>
        <td><div class="row" style="--gap:4px">
          ${s.has_translation && html`<${Pill}>${t('styles.covers.translation')}<//>`}
          ${s.has_polish && html`<${Pill}>${t('styles.covers.polish')}<//>`}
        </div></td>
        <td class="muted">${s.updated_at ? formatRelativeTime(s.updated_at) : '—'}</td>
        <td class="col-actions" onClick=${(e) => e.stopPropagation()}><${Menu} items=${[
          { label: t('common.duplicate'), icon: 'copy', onSelect: () => act(() => stylesApi.duplicate(s.name), t('styles.toast.duplicated')) },
          'sep',
          { label: t('common.delete'), icon: 'trash-2', danger: true, onSelect: () => remove(s) },
        ]} /></td>
      </tr>`)}</tbody>
    </table></div>`}
    ${creating && html`<${StyleDialog} onClose=${() => setCreating(false)} onSaved=${(name) => { loadStyles(); navigate(`/styles/${encodeURIComponent(name)}`); }} />`}
  </div>`;
}

export function StylePage({ name }) {
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [state, setState] = useState(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    setForm(null);
    stylesApi.get(name).then((s) => { setForm({ name: s.name, translation: s.translation || '', polish: s.polish || '' }); setDirty(false); }).catch(setError);
  }, [name]);
  const set = (patch) => { setForm({ ...form, ...patch }); setDirty(true); setState(null); };
  const save = async () => {
    setState('saving');
    try {
      const renamed = form.name.trim() !== name;
      const r = await stylesApi.save(name, { translation: form.translation, polish: form.polish, new_name: renamed ? form.name.trim() : undefined });
      setState('saved');
      setDirty(false);
      loadStyles();
      if (renamed) navigate(`/styles/${encodeURIComponent((r && r.name) || form.name.trim())}`, { replace: true });
    } catch (e) {
      setState('error');
      toast({ tone: 'error', title: t('common.save_failed'), message: e.message });
    }
  };
  return html`<div class="page page--narrow">
    <${PageHeader} title=${name} back=${{ href: '#/styles', label: t('styles.title') }} />
    ${error && html`<${Callout} tone="danger">${error.message}<//>`}
    ${!form && !error && html`<p class="muted">${t('common.loading')}</p>`}
    ${form && html`<div class="form-rows">
      <${Field} label=${t('styles.field.name')} htmlFor="style-name">
        <${TextInput} id="style-name" value=${form.name} onInput=${(v) => set({ name: v })} />
      <//>
      <${Field} label=${t('styles.field.translation')} htmlFor="style-translation" help=${t('styles.field.translation_help')}>
        <${Textarea} id="style-translation" rows=${10} value=${form.translation} onInput=${(v) => set({ translation: v })} />
      <//>
      <${Field} label=${t('styles.field.polish')} htmlFor="style-polish" optional help=${t('styles.field.polish_help')}>
        <${Textarea} id="style-polish" rows=${6} value=${form.polish} onInput=${(v) => set({ polish: v })} />
      <//>
      <div class="row">
        <${Button} variant="primary" disabled=${!dirty || !form.name.trim()} loading=${state === 'saving'} onClick=${save}>${t('common.save')}<//>
        <${SavedIndicator} state=${state === 'saving' ? null : state} />
      </div>
      <p class="small muted">${t('styles.snapshot_note')}</p>
    </div>`}
  </div>`;
}
