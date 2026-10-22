import { html, useState, useEffect, useRef } from '../ui/html.js';
import { Button, Icon, Pill, Callout, Spinner, SavedIndicator } from '../ui/core.js';
import { Field, TextInput, Textarea, Select, Segmented, ToggleRow, Checkbox } from '../ui/forms.js';
import { PageHeader, Tabs } from '../ui/layout.js';
import { Menu, confirm, toast } from '../ui/overlays.js';
import { ConnectionDialog, TYPE_ICONS } from '../ui/connection-dialog.js';
import { connections, connectionsLoaded, loadConnections, loadModels, preferences, savePreferences, loadPreferences, themePref, setTheme, bookFont, setBookFont } from '../lib/stores.js';
import { connectionsApi, notificationsApi } from '../lib/api.js';
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
    try { await connectionsApi.remove(c.id); await loadConnections(); toast({ tone: 'success', title: t('connection.toast.deleted') }); }
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
        { label: t('common.delete'), icon: 'trash-2', danger: true, disabled: c.builtin, onSelect: remove },
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

// ----------------------------------------------------------- notifications

const PRESETS = {
  ntfy: { url: 'https://ntfy.sh/your-topic', method: 'POST', headers: '', payload: '' },
  gotify: { url: 'https://gotify.example.com/message?token=YOUR_TOKEN_HERE', method: 'POST', headers: '', payload: '' },
  discord: { url: 'https://discord.com/api/webhooks/XXXXX/YYYYY', method: 'POST', headers: '', payload: '{"content":"Translation **{event}**: `{file}` in {duration_seconds:.0f}s"}' },
  slack: { url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ', method: 'POST', headers: '', payload: '{"text":"Translation {event}: {file} ({duration_seconds:.0f}s)"}' },
  healthchecks: { url: 'https://hc-ping.com/your-uuid-here', method: 'GET', headers: '', payload: '' },
};
const EVENTS = ['success', 'failure', 'system_paused', 'queue_finished'];

function NotificationsSection() {
  const prefs = preferences.value;
  const n = (prefs && prefs.notifications) || {};
  const [form, setForm] = useState(null);
  const [state, setState] = useState(null);
  const [testing, setTesting] = useState(false);
  useEffect(() => {
    if (prefs && !form) {
      setForm({
        enabled: !!n.enabled,
        url: '', urlSet: !!(n.url && n.url.set), urlHint: n.url && n.url.hint,
        method: n.method || 'POST',
        headers: '', headersSet: !!(n.headers && n.headers.set),
        payload: n.payload || '',
        events: n.events || ['success', 'failure', 'system_paused', 'queue_finished'],
      });
    }
  }, [prefs]);
  if (!form) return html`<p class="muted">${t('common.loading')}</p>`;
  const set = (patch) => setForm({ ...form, ...patch });
  const save = async () => {
    setState('saving');
    try {
      const payload = { enabled: form.enabled, method: form.method, payload: form.payload, events: form.events };
      if (form.url) payload.url = form.url;
      if (form.headers.trim()) {
        try { payload.headers = JSON.parse(form.headers); }
        catch { setState('error'); toast({ tone: 'error', title: t('settings.notify.headers_invalid') }); return; }
      }
      await savePreferences({ notifications: payload });
      setForm(null);
      setState('saved');
    } catch (e) {
      setState('error');
      toast({ tone: 'error', title: t('common.save_failed'), message: e.message });
    }
  };
  const sendTest = async () => {
    setTesting(true);
    try { await notificationsApi.test('success'); toast({ tone: 'success', title: t('settings.notify.test_sent') }); }
    catch (e) { toast({ tone: 'error', title: t('settings.notify.test_failed'), message: e.message }); }
    finally { setTesting(false); }
  };
  const toggleEvent = (ev, on) => set({ events: on ? [...new Set([...form.events, ev])] : form.events.filter((x) => x !== ev) });
  return html`<div class="stack" style="--gap:16px;max-width:720px">
    <p class="muted">${t('settings.notify.desc')}</p>
    <${ToggleRow} title=${t('settings.notify.enabled')} desc=${t('settings.notify.enabled_desc')} checked=${form.enabled} onChange=${(v) => set({ enabled: v })} />
    <${Field} label=${t('settings.notify.presets')} help=${t('settings.notify.presets_help')}>
      <div class="chips">${Object.keys(PRESETS).map((k) => html`<button type="button" class="chip" onClick=${() => set({ ...PRESETS[k], enabled: true })}>${t(`settings.notify.preset.${k}`)}</button>`)}</div>
    <//>
    <${Field} label=${t('settings.notify.url')} htmlFor="notify-url" help=${form.urlSet && !form.url ? t('settings.notify.saved_secret', { hint: form.urlHint || '' }) : t('settings.notify.url_help')}>
      <${TextInput} id="notify-url" value=${form.url} onInput=${(v) => set({ url: v })} placeholder=${form.urlSet ? t('settings.notify.keep_saved') : 'https://…'} spellcheck="false" autocomplete="off" />
    <//>
    <div class="field-grid">
      <${Field} label=${t('settings.notify.method')} htmlFor="notify-method">
        <${Select} id="notify-method" value=${form.method} onChange=${(v) => set({ method: v })} options=${['POST', 'PUT', 'GET'].map((m) => ({ value: m, label: m }))} />
      <//>
    </div>
    <${Field} label=${t('settings.notify.headers')} htmlFor="notify-headers" optional help=${form.headersSet && !form.headers ? t('settings.notify.headers_saved') : t('settings.notify.headers_help')}>
      <${Textarea} id="notify-headers" variant="mono" rows=${3} value=${form.headers} onInput=${(v) => set({ headers: v })} placeholder=${form.headersSet ? t('settings.notify.keep_saved') : '{"Authorization": "Bearer …"}'} />
    <//>
    <${Field} label=${t('settings.notify.payload')} htmlFor="notify-payload" optional help=${t('settings.notify.payload_help')}>
      <${Textarea} id="notify-payload" variant="mono" rows=${4} value=${form.payload} onInput=${(v) => set({ payload: v })} />
    <//>
    <${Field} label=${t('settings.notify.events')}>
      <div class="stack" style="--gap:6px">
        ${EVENTS.map((ev) => html`<${Checkbox} checked=${form.events.includes(ev)} onChange=${(v) => toggleEvent(ev, v)}
          label=${html`<span>${t(`settings.notify.event.${ev}`)}</span>`} />`)}
      </div>
    <//>
    <div class="row">
      <${Button} variant="primary" onClick=${save}>${t('common.save')}<//>
      <${Button} icon="bell" loading=${testing} disabled=${!form.urlSet && !form.url} onClick=${sendTest}>${t('settings.notify.test')}<//>
      <${SavedIndicator} state=${state} />
    </div>
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
  const current = ['connections', 'notifications', 'appearance'].includes(section) ? section : 'connections';
  return html`<div class="page">
    <${PageHeader} title=${t('settings.title')} />
    <${Tabs} label=${t('settings.title')} current=${current} items=${[
      { id: 'connections', label: t('settings.tab.connections'), href: '#/settings/connections' },
      { id: 'notifications', label: t('settings.tab.notifications'), href: '#/settings/notifications' },
      { id: 'appearance', label: t('settings.tab.appearance'), href: '#/settings/appearance' },
    ]} />
    ${current === 'connections' && html`<${ConnectionsSection} />`}
    ${current === 'notifications' && html`<${NotificationsSection} />`}
    ${current === 'appearance' && html`<${AppearanceSection} />`}
  </div>`;
}
