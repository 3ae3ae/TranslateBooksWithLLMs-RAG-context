import { html, useState, useEffect, useMemo } from './html.js';
import { Button, Icon, Callout, Spinner } from './core.js';
import { Dialog, toast } from './overlays.js';
import { Field, TextInput, Textarea, NumberInput, Segmented, ToggleRow, Combobox } from './forms.js';
import { Disclosure } from './layout.js';
import { connectionsApi } from '../lib/api.js';
import { connectionTypes, loadConnections, loadModels } from '../lib/stores.js';
import { t } from '../lib/i18n.js';
import { formatNumber, formatCost } from '../lib/format.js';

export const TYPE_ICONS = {
  ollama: 'cpu', ollama_cloud: 'cloud', openai: 'sparkles', openai_compatible: 'server',
  openrouter: 'link', gemini: 'sparkles', mistral: 'wand-sparkles', deepseek: 'brain', poe: 'message-square-quote', nim: 'zap',
};
const TYPE_ORDER = ['ollama', 'ollama_cloud', 'openai_compatible', 'openai', 'openrouter', 'gemini', 'deepseek', 'mistral', 'poe', 'nim'];
const OPENAI_STYLE = new Set(['openai', 'openai_compatible', 'openrouter', 'mistral', 'deepseek', 'poe', 'nim']);

/** Mirror of the server's URL rules (design §14.2) for the live preview. */
export function resolveUrls(type, baseUrl) {
  let base = (baseUrl || '').trim().replace(/\/+$/, '');
  if (!base) return null;
  if (type === 'ollama' || type === 'ollama_cloud') {
    base = base.replace(/\/api(\/(chat|generate|tags))?$/, '');
    return { chat: `${base}/api/chat`, models: `${base}/api/tags` };
  }
  if (OPENAI_STYLE.has(type)) {
    base = base.replace(/\/chat\/completions$/, '');
    try {
      const u = new URL(base);
      if (type === 'openai_compatible' && (u.pathname === '/' || u.pathname === '')) base = `${base}/v1`;
    } catch { /* incomplete URL while typing */ }
    return { chat: `${base}/chat/completions`, models: `${base}/models` };
  }
  return null;
}

const isLocalHost = (url) => {
  try {
    const h = new URL(url).hostname;
    return ['localhost', '127.0.0.1', '::1', '[::1]'].includes(h) || h.endsWith('.local');
  } catch { return false; }
};

function TypePicker({ onPick }) {
  const types = [...connectionTypes.value].sort((a, b) => TYPE_ORDER.indexOf(a.type) - TYPE_ORDER.indexOf(b.type));
  return html`<div class="type-grid">
    ${types.map((ty) => html`<button type="button" class="type-tile" onClick=${() => onPick(ty)}>
      <span class="conn-card__icon" style="width:32px;height:32px"><${Icon} name=${TYPE_ICONS[ty.type] || 'plug'} /></span>
      <span class="stack" style="--gap:2px">
        <span class="type-tile__title">${t(`connection.type.${ty.type}`)}</span>
        <span class="type-tile__desc">${t(`connection.type_desc.${ty.type}`)}</span>
      </span>
    </button>`)}
  </div>`;
}

/**
 * Add or edit a model connection.
 * `connection` = existing (browser view) or undefined for a new one.
 */
export function ConnectionDialog({ connection, onClose, onSaved }) {
  const editing = !!connection;
  const [type, setType] = useState(connection ? connectionTypes.value.find((x) => x.type === connection.type) || { type: connection.type } : null);
  const [form, setForm] = useState(() => connection ? {
    name: connection.name,
    base_url: connection.base_url || '',
    keysText: '',
    replaceKeys: false,
    local: !!connection.local,
    localTouched: true,
    default_model: connection.default_model || '',
    parallel_requests: connection.parallel_requests,
    request_timeout: connection.request_timeout,
    max_attempts: connection.max_attempts,
    rate_limit_behavior: connection.rate_limit_behavior || 'retry',
    rate_limit_retry_seconds: connection.rate_limit_retry_seconds,
    temperature: connection.temperature,
  } : null);
  const [test, setTest] = useState(null); // {running, ok, model_count, chat_ok, error, models}
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [models, setModels] = useState([]);

  useEffect(() => {
    if (editing) loadModels(connection.id).then((m) => setModels(m || []));
  }, []);

  const pick = (ty) => {
    setType(ty);
    const local = ty.type === 'ollama';
    setForm({
      name: t(`connection.type.${ty.type}`),
      base_url: ty.default_base_url || '',
      keysText: '',
      replaceKeys: true,
      local,
      localTouched: false,
      default_model: '',
      parallel_requests: local ? 1 : 4,
      request_timeout: local ? 900 : 300,
      max_attempts: 2,
      rate_limit_behavior: 'retry',
      rate_limit_retry_seconds: 60,
      temperature: null,
    });
  };

  const set = (patch) => setForm((f) => {
    const next = { ...f, ...patch };
    if ('base_url' in patch && !f.localTouched) next.local = isLocalHost(patch.base_url);
    return next;
  });

  const keys = form ? form.keysText.split('\n').map((k) => k.trim()).filter(Boolean) : [];
  const showAddress = type && (type.base_url_required || ['ollama', 'openai_compatible'].includes(type.type));
  const resolved = type && form ? resolveUrls(type.type, form.base_url) : null;
  const needsKey = type && type.key_required;
  const keyMissing = needsKey && !keys.length && (!editing || form.replaceKeys || !connection.key_count);

  const draftBody = () => {
    const body = {
      name: form.name.trim(), type: type.type, base_url: form.base_url.trim() || undefined,
      default_model: form.default_model || undefined, local: form.local,
      parallel_requests: form.parallel_requests, request_timeout: form.request_timeout,
      max_attempts: form.max_attempts, rate_limit_behavior: form.rate_limit_behavior,
      rate_limit_retry_seconds: form.rate_limit_retry_seconds, temperature: form.temperature,
    };
    if (!editing || form.replaceKeys) body.api_keys = keys;
    return body;
  };

  const runTest = async () => {
    setTest({ running: true });
    try {
      const body = { ...draftBody(), model: form.default_model || undefined };
      if (editing) body.id = connection.id;
      const r = await connectionsApi.test(body);
      if (r.models) setModels(r.models);
      setTest({ ...r, running: false });
    } catch (e) {
      setTest({ running: false, ok: false, error: e.message });
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const r = editing ? await connectionsApi.update(connection.id, draftBody()) : await connectionsApi.create(draftBody());
      await loadConnections();
      const saved = r.connection || r;
      if (saved && saved.id) loadModels(saved.id, { refresh: true });
      toast({ tone: 'success', title: editing ? t('connection.toast.saved') : t('connection.toast.added') });
      onSaved && onSaved(saved);
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const modelOptions = useMemo(() => models.map((m) => ({
    value: m.id, label: m.name || m.id,
    meta: m.pricing && m.pricing.input_per_m != null
      ? t('model.price_per_m', { input: formatCost(m.pricing.input_per_m), output: formatCost(m.pricing.output_per_m || 0) }) : '',
  })), [models]);

  if (!type) {
    return html`<${Dialog} title=${t('connection.add_title')} desc=${t('connection.add_desc')} size="wide" onClose=${onClose}>
      <${TypePicker} onPick=${pick} />
    <//>`;
  }

  const canSave = form.name.trim() && !keyMissing && (!showAddress || form.base_url.trim());
  return html`<${Dialog}
    title=${editing ? t('connection.edit_title', { name: connection.name }) : t(`connection.type.${type.type}`)}
    desc=${t(`connection.type_desc.${type.type}`)}
    size="wide"
    onClose=${onClose}
    footer=${html`
      ${!editing && html`<${Button} variant="ghost" icon="arrow-left" onClick=${() => setType(null)}>${t('common.back')}<//>`}
      <span class="grow" />
      <${Button} variant="ghost" onClick=${onClose}>${t('common.cancel')}<//>
      <${Button} variant="primary" loading=${saving} disabled=${!canSave} onClick=${save}>${t('common.save')}<//>`}
  >
    <div class="form-rows">
      ${error && html`<${Callout} tone="danger">${error}<//>`}
      <${Field} label=${t('connection.field.name')} htmlFor="conn-name">
        <${TextInput} id="conn-name" value=${form.name} onInput=${(v) => set({ name: v })} />
      <//>

      ${showAddress && html`<${Field} label=${t('connection.field.address')} htmlFor="conn-url"
          help=${type.type === 'openai_compatible' ? t('connection.field.address_help_openai') : t('connection.field.address_help_ollama')}>
        <${TextInput} id="conn-url" value=${form.base_url} onInput=${(v) => set({ base_url: v })} placeholder=${type.default_base_url || 'http://localhost:8080/v1'} spellcheck="false" />
        ${resolved && html`<div class="tiny faint mono" style="line-height:1.6">
          <div>${t('connection.field.requests_go')} ${resolved.chat}</div>
          <div>${t('connection.field.models_from')} ${resolved.models}</div>
        </div>`}
      <//>`}

      ${type.type !== 'ollama' || editing ? html`<${Field} label=${t('connection.field.keys')} htmlFor="conn-keys"
          optional=${!needsKey}
          help=${t('connection.field.keys_help')}>
        ${editing && !form.replaceKeys && connection.key_count > 0
          ? html`<div class="row"><span class="mono small">${t('connection.field.keys_saved', { count: connection.key_count, n: formatNumber(connection.key_count), hint: connection.key_hint || '' })}</span>
              <${Button} size="sm" onClick=${() => set({ replaceKeys: true })}>${t('connection.field.replace_keys')}<//></div>`
          : html`<${Textarea} id="conn-keys" variant="mono" rows=${3} value=${form.keysText} onInput=${(v) => set({ keysText: v })}
              placeholder=${t('connection.field.keys_placeholder')} spellcheck="false" autocomplete="off" />`}
      <//>` : null}

      <${ToggleRow} title=${t('connection.field.local')} desc=${t('connection.field.local_desc')}
        checked=${form.local} onChange=${(v) => set({ local: v, localTouched: true })} />

      <${Field} label=${t('connection.field.default_model')} htmlFor="conn-model" help=${t('connection.field.default_model_help')}>
        <${Combobox} id="conn-model" value=${form.default_model} options=${modelOptions}
          placeholder=${models.length ? t('model.choose') : t('connection.field.test_first')}
          allowCustom customLabel=${(x) => t('model.use_typed', { name: x })}
          onChange=${(v) => set({ default_model: v })} />
      <//>

      <div class="stack" style="--gap:8px">
        <div class="row">
          <${Button} icon="plug" loading=${test && test.running} disabled=${keyMissing || (showAddress && !form.base_url.trim())} onClick=${runTest}>
            ${form.default_model ? t('connection.test_with_model') : t('connection.test')}
          <//>
          ${test && !test.running && (test.ok
            ? html`<span class="row small" style="color:var(--success)"><${Icon} name="circle-check" size="sm" />
                ${t('connection.test_ok', { count: test.model_count || 0, n: formatNumber(test.model_count || 0) })}
                ${test.chat_ok === true ? ` · ${t('connection.test_chat_ok')}` : ''}${test.latency_ms ? ` · ${formatNumber(test.latency_ms)} ms` : ''}</span>`
            : html`<span class="row small" style="color:var(--danger)"><${Icon} name="circle-alert" size="sm" />${test.error || t('connection.test_failed')}</span>`)}
        </div>
        ${test && test.ok && test.chat_ok === false && html`<${Callout} tone="warning">${t('connection.test_chat_failed', { error: test.chat_error || '' })}<//>`}
      </div>

      <${Disclosure} title=${t('connection.advanced')}>
        <div class="form-rows">
          ${!showAddress && html`<${Field} label=${t('connection.field.address')} htmlFor="conn-url-adv" help=${t('connection.field.address_proxy_help')}>
            <${TextInput} id="conn-url-adv" value=${form.base_url} onInput=${(v) => set({ base_url: v })} placeholder=${type.default_base_url} spellcheck="false" />
          <//>`}
          <div class="field-grid">
            <${Field} label=${t('connection.field.parallel')} htmlFor="conn-par" help=${form.local ? t('connection.field.parallel_local') : t('connection.field.parallel_help')}>
              <${NumberInput} id="conn-par" min=${1} max=${16} value=${form.parallel_requests} onCommit=${(v) => set({ parallel_requests: v || 1 })} />
            <//>
            <${Field} label=${t('connection.field.timeout')} htmlFor="conn-timeout" help=${t('connection.field.timeout_help')}>
              <${NumberInput} id="conn-timeout" min=${10} max=${3600} value=${form.request_timeout} onCommit=${(v) => set({ request_timeout: v || 300 })} suffix=${t('common.seconds')} />
            <//>
            <${Field} label=${t('connection.field.retries')} htmlFor="conn-retries" help=${t('connection.field.retries_help')}>
              <${NumberInput} id="conn-retries" min=${1} max=${10} value=${form.max_attempts} onCommit=${(v) => set({ max_attempts: v || 2 })} />
            <//>
          </div>
          <${Field} label=${t('connection.field.rate_limit')}>
            <${Segmented} label=${t('connection.field.rate_limit')} value=${form.rate_limit_behavior} onChange=${(v) => set({ rate_limit_behavior: v })} options=${[
              { value: 'retry', label: t('connection.field.rate_retry') },
              { value: 'pause', label: t('connection.field.rate_pause') },
            ]} />
            <div class="field__help">${form.rate_limit_behavior === 'retry' ? t('connection.field.rate_retry_help') : t('connection.field.rate_pause_help')}</div>
            ${form.rate_limit_behavior === 'retry' && html`<${NumberInput} min=${5} max=${3600} value=${form.rate_limit_retry_seconds}
              onCommit=${(v) => set({ rate_limit_retry_seconds: v || 60 })} suffix=${t('connection.field.rate_wait')} aria-label=${t('connection.field.rate_wait')} />`}
          <//>
          ${type.temperature !== false && html`<${Field} label=${t('connection.field.temperature')} help=${t('connection.field.temperature_help')}>
            <div class="row" style="--gap:12px">
              <${Segmented} label=${t('connection.field.temperature')} value=${form.temperature == null ? 'default' : 'custom'}
                onChange=${(v) => set({ temperature: v === 'default' ? null : 0.3 })} options=${[
                  { value: 'default', label: t('connection.field.temperature_default') },
                  { value: 'custom', label: t('connection.field.temperature_custom') },
                ]} />
              ${form.temperature != null && html`<${NumberInput} min=${0} max=${2} step=${0.1} value=${form.temperature} onCommit=${(v) => set({ temperature: v ?? 0.3 })} aria-label=${t('connection.field.temperature')} />`}
            </div>
          <//>`}
        </div>
      <//>
    </div>
  <//>`;
}

export { Spinner };
