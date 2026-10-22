import { html, cx, useState, useRef, useEffect, useMemo, useUid, useDismiss } from './html.js';
import { Icon, Spinner } from './core.js';
import { t } from '../lib/i18n.js';

export function Field({ label, help, error, htmlFor, optional, children, class: className, labelExtra }) {
  return html`<div class=${cx('field', className)}>
    ${label && html`<div class="row row--between">
      <label class="field__label" for=${htmlFor}>
        ${label}${optional && html` <span class="faint">${t('common.optional')}</span>`}
      </label>
      ${labelExtra}
    </div>`}
    ${children}
    ${error ? html`<div class="field__error" role="alert">${error}</div>` : help && html`<div class="field__help">${help}</div>`}
  </div>`;
}

export function TextInput({ value, onInput, onCommit, size, invalid, class: className, ...rest }) {
  return html`<input
    class=${cx('input', size && `input--${size}`, className)}
    value=${value ?? ''}
    aria-invalid=${invalid ? 'true' : undefined}
    onInput=${(e) => onInput && onInput(e.currentTarget.value)}
    onChange=${(e) => onCommit && onCommit(e.currentTarget.value)}
    ...${rest}
  />`;
}

/** Number input that reports numbers (or null when empty). Commits on change/blur. */
export function NumberInput({ value, onCommit, min, max, step = 1, suffix, invalid, class: className, ...rest }) {
  const [draft, setDraft] = useState(value ?? '');
  useEffect(() => { setDraft(value ?? ''); }, [value]);
  const commit = () => {
    if (draft === '' || draft === null) { onCommit && onCommit(null); return; }
    let n = Number(draft);
    if (!Number.isFinite(n)) { setDraft(value ?? ''); return; }
    if (min !== undefined) n = Math.max(min, n);
    if (max !== undefined) n = Math.min(max, n);
    setDraft(n);
    if (n !== value) onCommit && onCommit(n);
  };
  const input = html`<input
    type="number"
    class=${cx('input input--num', className)}
    value=${draft}
    min=${min} max=${max} step=${step}
    aria-invalid=${invalid ? 'true' : undefined}
    onInput=${(e) => setDraft(e.currentTarget.value)}
    onBlur=${commit}
    onKeyDown=${(e) => { if (e.key === 'Enter') commit(); }}
    ...${rest}
  />`;
  return suffix ? html`<div class="row" style="--gap:8px">${input}<span class="muted small">${suffix}</span></div>` : input;
}

export function Textarea({ value, onInput, onCommit, variant, rows = 4, invalid, class: className, ...rest }) {
  return html`<textarea
    class=${cx('textarea', variant && `textarea--${variant}`, className)}
    rows=${rows}
    aria-invalid=${invalid ? 'true' : undefined}
    onInput=${(e) => onInput && onInput(e.currentTarget.value)}
    onChange=${(e) => onCommit && onCommit(e.currentTarget.value)}
    ...${rest}
  >${value ?? ''}</textarea>`;
}

/** Native select. options: [{value, label, disabled}] */
export function Select({ value, onChange, options, class: className, ...rest }) {
  return html`<select class=${cx('select', className)} value=${value ?? ''} onChange=${(e) => onChange(e.currentTarget.value)} ...${rest}>
    ${options.map((o) => html`<option value=${o.value} disabled=${o.disabled}>${o.label}</option>`)}
  </select>`;
}

export function Switch({ checked, onChange, disabled, id, label }) {
  return html`<span class="switch">
    <input type="checkbox" role="switch" id=${id} checked=${!!checked} disabled=${disabled} aria-label=${label}
      onChange=${(e) => onChange(e.currentTarget.checked)} />
    <span class="switch__track" />
  </span>`;
}

/** Switch with a title and a plain-language description. `reason` explains why it is disabled. */
export function ToggleRow({ title, desc, checked, onChange, disabled, reason, children }) {
  const id = useUid('toggle');
  return html`<div class=${cx('toggle-row', disabled && 'toggle-row--disabled')}>
    <${Switch} id=${id} checked=${checked} onChange=${onChange} disabled=${disabled} />
    <div class="toggle-row__text">
      <label class="toggle-row__title" for=${id}>${title}</label>
      ${desc && html`<div class="toggle-row__desc">${desc}</div>`}
      ${disabled && reason && html`<div class="toggle-row__desc">${reason}</div>`}
      ${children}
    </div>
  </div>`;
}

export function Checkbox({ checked, onChange, label, disabled, indeterminate }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = !!indeterminate; }, [indeterminate]);
  return html`<label class="checkbox">
    <input ref=${ref} type="checkbox" checked=${!!checked} disabled=${disabled}
      onChange=${(e) => onChange(e.currentTarget.checked)} aria-label=${typeof label === 'string' ? label : undefined} />
    ${typeof label === 'string' ? html`<span class="sr-only">${label}</span>` : label}
  </label>`;
}

/** Segmented control. options: [{value, label, icon, disabled, title}] */
export function Segmented({ value, onChange, options, label, size }) {
  const onKey = (e) => {
    const enabled = options.filter((o) => !o.disabled);
    const i = enabled.findIndex((o) => o.value === value);
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); onChange(enabled[(i + 1) % enabled.length].value); }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); onChange(enabled[(i - 1 + enabled.length) % enabled.length].value); }
  };
  return html`<div class="segmented" role="radiogroup" aria-label=${label} onKeyDown=${onKey}>
    ${options.map((o) => html`<button
      type="button"
      role="radio"
      class=${cx('segmented__opt', size && `segmented__opt--${size}`)}
      aria-checked=${String(o.value === value)}
      tabindex=${o.value === value ? 0 : -1}
      disabled=${o.disabled}
      title=${o.title}
      onClick=${() => onChange(o.value)}
    >${o.icon && html`<${Icon} name=${o.icon} size="sm" />`}${o.label}</button>`)}
  </div>`;
}

/** Radio cards with a title and description each. options: [{value, title, desc, icon, disabled}] */
export function ChoiceGroup({ value, onChange, options, label, cols }) {
  const onKey = (e) => {
    const enabled = options.filter((o) => !o.disabled);
    const i = enabled.findIndex((o) => o.value === value);
    if (['ArrowRight', 'ArrowDown'].includes(e.key)) { e.preventDefault(); onChange(enabled[(i + 1) % enabled.length].value); }
    if (['ArrowLeft', 'ArrowUp'].includes(e.key)) { e.preventDefault(); onChange(enabled[(i - 1 + enabled.length) % enabled.length].value); }
  };
  return html`<div class="choices" role="radiogroup" aria-label=${label} style=${{ '--cols': cols || options.length }} onKeyDown=${onKey}>
    ${options.map((o) => html`<button
      type="button"
      role="radio"
      class="choice"
      aria-checked=${String(o.value === value)}
      tabindex=${o.value === value ? 0 : -1}
      disabled=${o.disabled}
      onClick=${() => onChange(o.value)}
    >
      <span class="choice__title">${o.icon && html`<${Icon} name=${o.icon} />`}${o.title}</span>
      ${o.desc && html`<span class="choice__desc">${o.desc}</span>`}
    </button>`)}
  </div>`;
}

const norm = (s) => String(s ?? '').toLocaleLowerCase();

/**
 * Searchable select with optional groups and free text.
 * options: [{value, label, meta, group, icon, disabled}]
 * allowCustom: lets the user pick the typed text; customLabel(text) renders that row.
 */
export function Combobox({
  value, onChange, options, placeholder, label, id, disabled, loading,
  allowCustom, customLabel, emptyText, searchPlaceholder, align, triggerMeta, renderValue,
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const rootRef = useRef(null);
  const searchRef = useRef(null);
  const listRef = useRef(null);
  const uid = useUid('combo');
  useDismiss(open, () => setOpen(false), rootRef);

  const selected = options.find((o) => o.value === value);
  const filtered = useMemo(() => {
    const q = norm(query.trim());
    if (!q) return options;
    return options.filter((o) => norm(o.label).includes(q) || norm(o.value).includes(q) || norm(o.meta).includes(q));
  }, [options, query]);
  const custom = allowCustom && query.trim() && !options.some((o) => norm(o.label) === norm(query.trim()))
    ? { value: query.trim(), label: customLabel ? customLabel(query.trim()) : query.trim(), custom: true }
    : null;
  const rows = custom ? [...filtered, custom] : filtered;

  useEffect(() => {
    if (open) {
      setQuery('');
      const i = options.findIndex((o) => o.value === value);
      setActive(i >= 0 ? i : 0);
      setTimeout(() => searchRef.current && searchRef.current.focus(), 0);
    }
  }, [open]);
  useEffect(() => { setActive(0); }, [query]);
  useEffect(() => {
    const el = listRef.current && listRef.current.querySelector('[data-active="true"]');
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [active, open]);

  const pick = (o) => {
    if (!o || o.disabled) return;
    onChange(o.value, o);
    setOpen(false);
  };
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(rows.length - 1, a + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(rows[active]); }
    else if (e.key === 'Tab') setOpen(false);
  };

  let lastGroup = null;
  const display = selected
    ? (renderValue ? renderValue(selected) : selected.label)
    : (value && allowCustom ? value : null);

  return html`<div class="combo" ref=${rootRef}>
    <button
      type="button"
      id=${id}
      class="combo__trigger"
      aria-haspopup="listbox"
      aria-expanded=${String(open)}
      aria-controls=${`${uid}-list`}
      aria-label=${label}
      disabled=${disabled}
      onClick=${() => setOpen(!open)}
      onKeyDown=${(e) => { if (e.key === 'ArrowDown' && !open) { e.preventDefault(); setOpen(true); } }}
    >
      ${selected && selected.icon && html`<${Icon} name=${selected.icon} size="sm" />`}
      <span class=${cx('combo__value', !display && 'combo__placeholder')}>${display || placeholder}</span>
      ${loading ? html`<${Spinner} size="sm" />` : (triggerMeta || (selected && selected.meta)) && html`<span class="combo__meta">${triggerMeta || selected.meta}</span>`}
      <${Icon} name="chevron-down" size="sm" class="combo__chev" />
    </button>
    ${open && html`<div class=${cx('popover', align === 'right' && 'popover--right')}>
      <div class="popover__search">
        <div class="input-affix">
          <${Icon} name="search" size="sm" />
          <input
            ref=${searchRef}
            class="input input--sm"
            placeholder=${searchPlaceholder || t('common.search')}
            value=${query}
            role="combobox"
            aria-expanded="true"
            aria-controls=${`${uid}-list`}
            aria-activedescendant=${rows[active] ? `${uid}-opt-${active}` : undefined}
            onInput=${(e) => setQuery(e.currentTarget.value)}
            onKeyDown=${onKey}
          />
        </div>
      </div>
      <div class="popover__list" role="listbox" id=${`${uid}-list`} ref=${listRef}>
        ${rows.length === 0 && html`<div class="popover__empty">${emptyText || t('common.no_results')}</div>`}
        ${rows.map((o, i) => {
          const header = !o.custom && o.group && o.group !== lastGroup ? html`<div class="popover__group">${o.group}</div>` : null;
          if (!o.custom) lastGroup = o.group;
          return html`${header}<button
            type="button"
            role="option"
            id=${`${uid}-opt-${i}`}
            class="option"
            data-active=${String(i === active)}
            aria-selected=${String(o.value === value)}
            disabled=${o.disabled}
            onMouseEnter=${() => setActive(i)}
            onClick=${() => pick(o)}
          >
            ${o.custom ? html`<${Icon} name="plus" size="sm" />` : o.icon && html`<${Icon} name=${o.icon} size="sm" />`}
            <span class="option__label">${o.label}</span>
            ${o.meta && html`<span class="option__meta">${o.meta}</span>`}
            ${o.value === value && !o.custom && html`<${Icon} name="check" size="sm" class="option__check" />`}
          </button>`;
        })}
      </div>
    </div>`}
  </div>`;
}
