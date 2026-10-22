import { html, useState, useEffect } from '../ui/html.js';
import { Button, Callout, EmptyState, Pill } from '../ui/core.js';
import { Field, TextInput } from '../ui/forms.js';
import { PageHeader } from '../ui/layout.js';
import { Menu, Dialog, confirm, toast } from '../ui/overlays.js';
import { NotesView, NotesEditor, NormalizationPreview } from '../ui/notes-editor.js';
import { notesList, loadNotes, jobsById } from '../lib/stores.js';
import { notesApi, foldersApi } from '../lib/api.js';
import { navigate } from '../lib/router.js';
import { t } from '../lib/i18n.js';
import { formatRelativeTime, formatBytes } from '../lib/format.js';

function NameDialog({ title, initial = '', submitLabel, onSubmit, onClose }) {
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try { await onSubmit(name.trim()); onClose(); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return html`<${Dialog} title=${title} onClose=${onClose} footer=${html`
      <${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>
      <${Button} variant="primary" loading=${busy} disabled=${!name.trim()} onClick=${submit}>${submitLabel}<//>`}>
    <${Field} label=${t('notes.field.name')} htmlFor="note-name" error=${error}>
      <${TextInput} id="note-name" value=${name} onInput=${setName} data-autofocus
        onKeyDown=${(e) => { if (e.key === 'Enter' && name.trim()) submit(); }} />
    <//>
  <//>`;
}

const inUseLabel = (n) => (n.used_by && n.used_by.length ? t('notes.in_use', { count: n.used_by.length }) : null);

export function NotesPage() {
  const [dialog, setDialog] = useState(null);
  useEffect(() => { loadNotes().catch(() => {}); }, []);
  const list = notesList.value;

  const act = async (fn, msg) => {
    try { await fn(); await loadNotes(); if (msg) toast({ tone: 'success', title: msg }); }
    catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  const remove = async (n) => {
    const ok = await confirm({ title: t('notes.confirm.delete_title', { name: n.name }), body: t('notes.confirm.delete_body'), confirmLabel: t('common.delete'), danger: true });
    if (ok) act(() => notesApi.remove(n.name), t('notes.toast.deleted'));
  };

  return html`<div class="page">
    <${PageHeader} title=${t('notes.title')} subtitle=${t('notes.subtitle')} actions=${html`
      <${Button} icon="folder-open" onClick=${() => foldersApi.open('notes').catch(() => {})}>${t('common.open_folder')}<//>
      <${Button} variant="primary" icon="plus" onClick=${() => setDialog({ kind: 'new' })}>${t('notes.new')}<//>`} />
    <${Callout} tone="info" class="group">${t('notes.explain')}<//>
    ${list === null && html`<p class="muted">${t('common.loading')}</p>`}
    ${list && !list.length && html`<${EmptyState} icon="notebook-pen" title=${t('notes.empty_title')}>${t('notes.empty_desc')}<//>`}
    ${list && list.length > 0 && html`<div class="table-wrap"><table class="table table--clickable">
      <thead><tr><th>${t('notes.col.name')}</th><th>${t('notes.col.updated')}</th><th>${t('notes.col.size')}</th><th>${t('notes.col.used')}</th><th class="col-actions"></th></tr></thead>
      <tbody>${list.map((n) => html`<tr onClick=${() => navigate(`/notes/${encodeURIComponent(n.name)}`)}>
        <td class="strong">${n.name}</td>
        <td class="muted">${n.updated_at ? formatRelativeTime(n.updated_at) : '—'}</td>
        <td class="muted">${n.size != null ? formatBytes(n.size) : '—'}</td>
        <td>${inUseLabel(n) ? html`<${Pill} tone="accent">${inUseLabel(n)}<//>` : html`<span class="faint">—</span>`}</td>
        <td class="col-actions" onClick=${(e) => e.stopPropagation()}><${Menu} items=${[
          { label: t('common.duplicate'), icon: 'copy', onSelect: () => setDialog({ kind: 'dup', note: n }) },
          { label: t('common.rename'), icon: 'pencil', disabled: !!inUseLabel(n), onSelect: () => setDialog({ kind: 'rename', note: n }) },
          'sep',
          { label: t('common.delete'), icon: 'trash-2', danger: true, disabled: !!inUseLabel(n), onSelect: () => remove(n) },
        ]} /></td>
      </tr>`)}</tbody>
    </table></div>`}
    ${dialog && dialog.kind === 'new' && html`<${NameDialog} title=${t('notes.new')} submitLabel=${t('common.create')} onClose=${() => setDialog(null)}
      onSubmit=${async (name) => { const r = await notesApi.create(name); await loadNotes(); navigate(`/notes/${encodeURIComponent((r && r.name) || name)}`); }} />`}
    ${dialog && dialog.kind === 'dup' && html`<${NameDialog} title=${t('common.duplicate')} initial=${t('notes.copy_name', { name: dialog.note.name })} submitLabel=${t('common.duplicate')}
      onClose=${() => setDialog(null)} onSubmit=${(name) => act(() => notesApi.create(name, dialog.note.name), t('notes.toast.duplicated'))} />`}
    ${dialog && dialog.kind === 'rename' && html`<${NameDialog} title=${t('common.rename')} initial=${dialog.note.name} submitLabel=${t('common.rename')}
      onClose=${() => setDialog(null)} onSubmit=${(name) => act(() => notesApi.rename(dialog.note.name, name), t('notes.toast.renamed'))} />`}
  </div>`;
}

export function NotePage({ name }) {
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => notesApi.get(name).then((n) => { setNote(n); setError(null); }).catch(setError);
  useEffect(() => { setNote(null); setEditing(null); load(); if (notesList.value === null) loadNotes().catch(() => {}); }, [name]);
  const meta = (notesList.value || []).find((n) => n.name === name);
  const usedBy = (meta && meta.used_by) || [];

  const review = async () => {
    setBusy(true);
    try { setCheck(await notesApi.save(name, editing, true)); }
    catch (e) { toast({ tone: 'error', title: t('common.save_failed'), message: e.message }); }
    finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true);
    try {
      await notesApi.save(name, editing, false);
      toast({ tone: 'success', title: t('common.saved') });
      setCheck(null);
      setEditing(null);
      load();
    } catch (e) {
      toast({ tone: 'error', title: t('common.save_failed'), message: e.message });
    } finally {
      setBusy(false);
    }
  };

  return html`<div class="page">
    <${PageHeader} title=${name} back=${{ href: '#/notes', label: t('notes.title') }}
      actions=${!editing && note && html`<${Button} variant="primary" icon="pencil" disabled=${usedBy.length > 0}
        onClick=${() => setEditing(note.sections.map((s) => ({ ...s })))}>${t('common.edit')}<//>`} />
    ${usedBy.length > 0 && html`<${Callout} tone="warning" title=${t('notes.locked.title')} class="group">
      ${t('notes.locked.desc')}
      <div class="row row--wrap" style="margin-top:6px">${usedBy.map((id) => {
        const j = jobsById.value[id];
        return html`<a href=${`#/job/${encodeURIComponent(id)}`}>${j ? j.title : id}</a>`;
      })}</div>
    <//>`}
    ${error && html`<${Callout} tone="danger">${error.message}<//>`}
    ${!note && !error && html`<p class="muted">${t('common.loading')}</p>`}
    ${note && !editing && html`<${NotesView} sections=${note.sections} />`}
    ${editing && html`<div class="stack">
      <${NotesEditor} sections=${editing} onChange=${setEditing} />
      <div class="row">
        <${Button} variant="primary" loading=${busy} onClick=${review}>${t('notes.review_save')}<//>
        <${Button} variant="ghost" onClick=${() => setEditing(null)}>${t('common.cancel')}<//>
      </div>
    </div>`}
    ${check && html`<${Dialog} title=${t('notes.confirm.save_title')} size="wide" onClose=${() => setCheck(null)} footer=${html`
        <${Button} variant="ghost" onClick=${() => setCheck(null)}>${t('common.back')}<//>
        <${Button} variant="primary" loading=${busy} onClick=${save}>${t('common.save')}<//>`}>
      <${NormalizationPreview} result=${check} original=${editing} />
    <//>`}
  </div>`;
}
