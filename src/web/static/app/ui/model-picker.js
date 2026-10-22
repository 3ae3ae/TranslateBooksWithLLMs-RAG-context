import { html, useEffect, useMemo } from './html.js';
import { Combobox, Segmented } from './forms.js';
import { Button, Callout } from './core.js';
import { connections, loadModels, modelsByConnection, typeInfo } from '../lib/stores.js';
import { t } from '../lib/i18n.js';
import { formatCost } from '../lib/format.js';

const SEP = '\u0000';
const key = (connId, model) => `${connId}${SEP}${model}`;

function priceMeta(m, conn) {
  if (conn && conn.local && !m.remote) return t('model.local');
  if (m.pricing && (m.pricing.input_per_m != null || m.pricing.output_per_m != null)) {
    return t('model.price_per_m', { input: formatCost(m.pricing.input_per_m || 0), output: formatCost(m.pricing.output_per_m || 0) });
  }
  if (conn && conn.type === 'ollama_cloud') return t('model.plan');
  return '';
}

/**
 * Model picker grouped by connection. Value = {connectionId, model}.
 * onChange({connectionId, model}).
 */
export function ModelPicker({ value, onChange, id, disabled, onlyConnection }) {
  const conns = connections.value.filter((c) => !onlyConnection || c.id === onlyConnection);
  useEffect(() => { conns.filter((c) => c.type !== 'ollama' || !c.local).forEach((c) => loadModels(c.id)); }, [conns.map((c) => c.id).join(',')]);
  const state = modelsByConnection.value;
  const loading = conns.some((c) => state[c.id] && state[c.id].loading);

  const options = useMemo(() => {
    const out = [];
    for (const c of conns) {
      const s = state[c.id];
      const models = (s && s.models) || [];
      for (const m of models) {
        out.push({ value: key(c.id, m.id), label: m.name || m.id, meta: priceMeta(m, c), group: c.name, conn: c, model: m.id });
      }
      // Keep the current choice visible even if the server no longer lists it.
      if (value && value.connectionId === c.id && value.model && !models.some((m) => m.id === value.model)) {
        out.push({ value: key(c.id, value.model), label: value.model, meta: s && s.loading ? '' : t('model.not_listed'), group: c.name, conn: c, model: value.model });
      }
    }
    return out;
  }, [conns, state, value && value.connectionId, value && value.model]);

  const current = value && value.model ? key(value.connectionId, value.model) : null;
  const fallbackConn = (value && value.connectionId) || (conns[0] && conns[0].id);
  const chosen = value && conns.find((c) => c.id === value.connectionId);
  const failed = chosen && state[chosen.id] && state[chosen.id].error;

  return html`<div class="stack" style="--gap:8px"><${Combobox}
    onOpen=${() => conns.forEach((c) => loadModels(c.id))}
    id=${id}
    value=${current}
    options=${options}
    loading=${loading}
    disabled=${disabled || !conns.length}
    placeholder=${conns.length ? t('model.choose') : t('model.no_connections')}
    searchPlaceholder=${t('model.search')}
    emptyText=${loading ? t('common.loading') : t('model.none_found')}
    allowCustom=${!!fallbackConn}
    customLabel=${(text) => t('model.use_typed', { name: text })}
    renderValue=${(o) => html`${o.label} <span class="faint">· ${o.conn.name}</span>`}
    onChange=${(v, o) => {
      if (o && o.custom) onChange({ connectionId: fallbackConn, model: v });
      else if (o) onChange({ connectionId: o.conn.id, model: o.model });
    }}
  />
  ${failed && html`<${Callout} tone="warning" title=${t('model.unreachable_title', { name: chosen.name })}
      actions=${html`<${Button} size="sm" icon="rotate-ccw" onClick=${() => loadModels(chosen.id, { refresh: true })}>${t('model.retry')}<//>
        <${Button} size="sm" variant="ghost" href="#/settings/connections">${t('model.open_settings')}<//>`}>
    ${chosen.local ? t('model.unreachable_local') : t('model.unreachable_remote')}
  <//>`}</div>`;
}

export const REASONING_LEVELS = ['off', 'low', 'medium', 'high', 'default'];

/** Reasoning segmented control; hidden when the connection type cannot control it. */
export function ReasoningControl({ connectionId, value, onChange, help = true }) {
  const conn = connections.value.find((c) => c.id === connectionId);
  const info = conn ? typeInfo(conn.type) : null;
  const support = info ? info.reasoning : 'best_effort';
  if (support === 'none') return null;
  const levels = support === 'on_off' ? ['off', 'high', 'default'] : REASONING_LEVELS;
  return html`<div class="stack" style="--gap:6px">
    <${Segmented}
      label=${t('reasoning.label')}
      value=${value || 'off'}
      onChange=${onChange}
      options=${levels.map((l) => ({ value: l, label: support === 'on_off' && l === 'high' ? t('reasoning.on') : t(`reasoning.${l}`) }))}
    />
    ${(help || support === 'best_effort') && html`<div class="field__help">
      ${[help && t('reasoning.help'), support === 'best_effort' && t('reasoning.best_effort')].filter(Boolean).join(' ')}
    </div>`}
  </div>`;
}
