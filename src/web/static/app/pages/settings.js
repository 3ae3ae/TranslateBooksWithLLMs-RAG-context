import { html, useState } from '../ui/html.js';
import { Button, Icon, Pill, Spinner } from '../ui/core.js';
import { Field, Segmented } from '../ui/forms.js';
import { PageHeader, Tabs } from '../ui/layout.js';
import { Menu, confirm, toast } from '../ui/overlays.js';
import { ConnectionDialog, TYPE_ICONS } from '../ui/connection-dialog.js';
import { connections, connectionsLoaded, loadConnections, loadModels, loadPreferences, themePref, setTheme, bookFont, setBookFont } from '../lib/stores.js';
import { connectionsApi } from '../lib/api.js';
import { t, locale, loadLocale } from '../lib/i18n.js';
import { formatNumber } from '../lib/format.js';

// ------------------------------------------------------------- connections

function ConnectionCard({ c, onEdit }) {
  const [testing, setTesting] = useState(false);
  const [status, setStatus] = useState(c.status || null);
  const test = async () => {
    setTesting(true);
    try {
      const r = await connectionsApi.test({ id: c.id, model: c.default_model || undefined });
      setStatus(r);
      loadModels(c.id, { refresh: true });
    } catch (e) {
      setStatus({ ok: false, error: e.message });
    } finally {
      setTesting(false);
    }
  };
  const setDefault = async () => {
    try { await connectionsApi.setDefault(c.id); await loadConnections(); await loadPreferences().catch(() => {}); toast({ tone: 'success', title: t('connection.toast.default', { name: c.name }) }); }
    catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  const remove = async () => {
    const ok = await confirm({ title: t('connection.confirm.delete_title', { name: c.name }), body: t('connection.confirm.delete_body'), confirmLabel: t('common.delete'), danger: true });
    if (!ok) return;
    try { await connectionsApi.remove(c.id); await loadConnections(); await loadPreferences().catch(() => {}); toast({ tone: 'success', title: t('connection.toast.deleted') }); }
    catch (e) { toast({ tone: 'error', title: t('errors.action_failed'), message: e.message }); }
  };
  let statusEl = null;
  if (testing) statusEl = html`<span class="row" style="--gap:4px"><${Spinner} size="sm" />${t('connection.status.testing')}</span>`;
  else if (status && status.ok) statusEl = html`<span class="row" style="--gap:4px;color:var(--success)"><span class="status-dot status-dot--ok" />${t('connection.status.ready', { count: status.model_count || 0, n: formatNumber(status.model_count || 0) })}</span>`;
  else if (status && status.ok === false) statusEl = html`<span class="row" style="--gap:4px;color:var(--danger)" title=${status.error}><span class="status-dot status-dot--err" /><span class="truncate" style="max-width:360px">${status.error || t('connection.test_failed')}</span></span>`;

  return html`<div class="card conn-card">
    <div class="conn-card__icon"><${Icon} name=${TYPE_ICONS[c.type] || 'plug'} /></div>
    <div class="stack" style="--gap:4px;min-width:0">
      <div class="conn-card__title">
        <span class="truncate">${c.name}</span>
        ${c.is_default && html`<${Pill} tone="accent">${t('connection.default_badge')}<//>`}
        ${c.local && html`<${Pill}>${t('connection.local_badge')}<//>`}
      </div>
      <div class="conn-card__meta">
        <span>${t(`connection.type.${c.type}`)}</span>
        ${c.base_url && html`<span class="mono truncate" style="max-width:280px">${c.base_url}</span>`}
        ${c.default_model && html`<span>${t('connection.default_model', { model: c.default_model })}</span>`}
        ${c.key_count > 0 && html`<span>${t('connection.keys_count', { count: c.key_count, n: formatNumber(c.key_count) })}</span>`}
      </div>
      ${statusEl && html`<div class="small">${statusEl}</div>`}
    </div>
    <div class="row">
      <${Button} size="sm" icon="plug" onClick=${test} disabled=${testing}>${t('connection.test')}<//>
      <${Menu} items=${[
        { label: t('common.edit'), icon: 'pencil', onSelect: () => onEdit(c) },
        { label: t('connection.set_default'), icon: 'check', disabled: c.is_default, onSelect: setDefault },
        'sep',
        { label: t('common.delete'), icon: 'trash-2', danger: true, onSelect: remove },
      ]} />
    </div>
  </div>`;
}

function ConnectionsSection() {
  const [dialog, setDialog] = useState(null);
  return html`<div class="stack" style="--gap:16px">
    <div class="row row--between">
      <p class="muted">${t('settings.connections.desc')}</p>
      <${Button} variant="primary" icon="plus" onClick=${() => setDialog({})}>${t('connection.add')}<//>
    </div>
    ${!connectionsLoaded.value && html`<p class="muted">${t('common.loading')}</p>`}
    <div class="settings-list">
      ${connections.value.map((c) => html`<${ConnectionCard} key=${c.id} c=${c} onEdit=${(x) => setDialog({ connection: x })} />`)}
    </div>
    ${dialog && html`<${ConnectionDialog} connection=${dialog.connection} onClose=${() => setDialog(null)} />`}
  </div>`;
}

// -------------------------------------------------------------- appearance

function AppearanceSection() {
  return html`<div class="form-rows" style="max-width:560px">
    <${Field} label=${t('appearance.theme')}>
      <${Segmented} label=${t('appearance.theme')} value=${themePref.value} onChange=${setTheme} options=${[
        { value: 'system', label: t('appearance.theme_system'), icon: 'monitor' },
        { value: 'light', label: t('appearance.theme_light'), icon: 'sun' },
        { value: 'dark', label: t('appearance.theme_dark'), icon: 'moon' },
      ]} />
    <//>
    <${Field} label=${t('appearance.language')}>
      <${Segmented} label=${t('appearance.language')} value=${locale.value} onChange=${(v) => loadLocale(v)} options=${[
        { value: 'en', label: 'English' },
        { value: 'ko', label: '한국어' },
      ]} />
    <//>
    <${Field} label=${t('appearance.book_font')} help=${t('appearance.book_font_help')}>
      <${Segmented} label=${t('appearance.book_font')} value=${bookFont.value} onChange=${setBookFont} options=${[
        { value: 'sans', label: t('appearance.font_sans') },
        { value: 'serif', label: t('appearance.font_serif') },
      ]} />
      <p class="passage__text" style="margin-top:8px;max-height:none">${t('appearance.font_sample')}</p>
    <//>
  </div>`;
}

export function SettingsPage({ section }) {
  const current = ['connections', 'appearance'].includes(section) ? section : 'connections';
  return html`<div class="page">
    <${PageHeader} title=${t('settings.title')} />
    <${Tabs} label=${t('settings.title')} current=${current} items=${[
      { id: 'connections', label: t('settings.tab.connections'), href: '#/settings/connections' },
      { id: 'appearance', label: t('settings.tab.appearance'), href: '#/settings/appearance' },
    ]} />
    ${current === 'connections' && html`<${ConnectionsSection} />`}
    ${current === 'appearance' && html`<${AppearanceSection} />`}
  </div>`;
}
