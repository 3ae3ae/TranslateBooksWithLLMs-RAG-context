import { html, cx, useEffect, useRef, useState, signal, useDismiss } from './html.js';
import { Icon, IconButton, Button } from './core.js';
import { t } from '../lib/i18n.js';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Traps focus inside `ref` while mounted; restores focus to the opener on unmount. */
function useFocusTrap(ref, onEscape) {
  useEffect(() => {
    const opener = document.activeElement;
    const el = ref.current;
    const first = el && (el.querySelector('[data-autofocus]') || el.querySelector(FOCUSABLE));
    if (first) first.focus();
    const onKey = (e) => {
      if (e.key === 'Escape' && onEscape) { e.stopPropagation(); onEscape(); return; }
      if (e.key !== 'Tab' || !el) return;
      const items = [...el.querySelectorAll(FOCUSABLE)].filter((n) => n.offsetParent !== null);
      if (!items.length) return;
      const a = items[0];
      const b = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); b.focus(); }
      else if (!e.shiftKey && document.activeElement === b) { e.preventDefault(); a.focus(); }
    };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
      if (opener && opener.focus) opener.focus();
    };
  }, []);
}

/** Modal dialog. Render conditionally: `${open && html`<${Dialog} …/>`}` */
export function Dialog({ title, desc, onClose, footer, size, children, dismissable = true }) {
  const ref = useRef(null);
  useFocusTrap(ref, dismissable ? onClose : null);
  return html`<div class="scrim" onMouseDown=${(e) => { if (dismissable && e.target === e.currentTarget) onClose(); }}>
    <div class=${cx('dialog', size && `dialog--${size}`)} role="dialog" aria-modal="true" aria-label=${title} ref=${ref}>
      <div class="dialog__header">
        <div class="grow">
          <div class="dialog__title">${title}</div>
          ${desc && html`<div class="dialog__desc">${desc}</div>`}
        </div>
        ${dismissable && html`<${IconButton} icon="x" label=${t('common.close')} size="sm" onClick=${onClose} />`}
      </div>
      ${children && html`<div class="dialog__body">${children}</div>`}
      ${footer && html`<div class="dialog__footer">${footer}</div>`}
    </div>
  </div>`;
}

export function Drawer({ title, subtitle, onClose, footer, width, children }) {
  const ref = useRef(null);
  useFocusTrap(ref, onClose);
  return html`
    <div class="drawer-scrim" onMouseDown=${onClose} />
    <aside class="drawer" role="dialog" aria-modal="true" aria-label=${title} ref=${ref} style=${width ? { '--drawer-w': width } : undefined}>
      <div class="drawer__header">
        <div class="grow">
          <h2>${title}</h2>
          ${subtitle && html`<div class="muted small" style="margin-top:4px">${subtitle}</div>`}
        </div>
        <${IconButton} icon="x" label=${t('common.close')} onClick=${onClose} />
      </div>
      <div class="drawer__body">${children}</div>
      ${footer && html`<div class="drawer__footer">${footer}</div>`}
    </aside>`;
}

/**
 * Overflow menu. items: [{label, icon, onSelect, danger, disabled} | 'sep']
 * `trigger` defaults to an ellipsis icon button.
 */
export function Menu({ items, label, icon = 'ellipsis', align, buttonSize }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useDismiss(open, () => setOpen(false), ref);
  const visible = items.filter(Boolean);
  useEffect(() => {
    if (open && ref.current) {
      const first = ref.current.querySelector('.menu__item:not(:disabled)');
      if (first) first.focus();
    }
  }, [open]);
  const onKey = (e) => {
    if (!['ArrowDown', 'ArrowUp'].includes(e.key)) return;
    e.preventDefault();
    const nodes = [...ref.current.querySelectorAll('.menu__item:not(:disabled)')];
    const i = nodes.indexOf(document.activeElement);
    const next = e.key === 'ArrowDown' ? (i + 1) % nodes.length : (i - 1 + nodes.length) % nodes.length;
    nodes[next].focus();
  };
  return html`<div class="menu-anchor" ref=${ref} onClick=${(e) => e.stopPropagation()}>
    <${IconButton} icon=${icon} label=${label || t('common.more_actions')} size=${buttonSize}
      aria-haspopup="menu" aria-expanded=${String(open)} onClick=${() => setOpen(!open)} />
    ${open && html`<div class="menu" role="menu" style=${align === 'left' ? { left: 0, right: 'auto' } : undefined} onKeyDown=${onKey}>
      ${visible.map((it) => it === 'sep'
        ? html`<div class="menu__sep" role="separator" />`
        : html`<button type="button" role="menuitem" class=${cx('menu__item', it.danger && 'menu__item--danger')}
            disabled=${it.disabled} onClick=${() => { setOpen(false); it.onSelect(); }}>
            ${it.icon && html`<${Icon} name=${it.icon} />`}<span class="grow">${it.label}</span>
          </button>`)}
    </div>`}
  </div>`;
}

// ---------------------------------------------------------------- confirm()

const confirmState = signal(null);

/**
 * Promise-based confirmation dialog (replaces window.confirm).
 * confirm({title, body, confirmLabel, danger, checkbox: {label, default}}) → false | true | {checked}
 */
export function confirm(opts) {
  return new Promise((resolve) => { confirmState.value = { ...opts, resolve }; });
}

export function ConfirmHost() {
  const s = confirmState.value;
  const [checked, setChecked] = useState(false);
  useEffect(() => { if (s) setChecked(!!(s.checkbox && s.checkbox.default)); }, [s]);
  if (!s) return null;
  const close = (result) => { confirmState.value = null; s.resolve(result); };
  return html`<${Dialog}
    title=${s.title}
    onClose=${() => close(false)}
    footer=${html`
      <${Button} variant="ghost" onClick=${() => close(false)}>${s.cancelLabel || t('common.cancel')}<//>
      <${Button} variant=${s.danger ? 'danger' : 'primary'} data-autofocus onClick=${() => close(s.checkbox ? { checked } : true)}>
        ${s.confirmLabel || t('common.confirm')}
      <//>`}
  >
    <div class="stack">
      ${typeof s.body === 'string' ? html`<p class="muted">${s.body}</p>` : s.body}
      ${s.checkbox && html`<label class="checkbox"><input type="checkbox" checked=${checked} onChange=${(e) => setChecked(e.currentTarget.checked)} /><span>${s.checkbox.label}</span></label>`}
    </div>
  <//>`;
}

// ------------------------------------------------------------------ toasts

export const toasts = signal([]);
let toastId = 0;
const TOAST_ICONS = { success: 'circle-check', error: 'circle-alert', warning: 'triangle-alert', info: 'info' };

/** toast({tone, title, message, action: {label, onSelect}, timeout}) */
export function toast(opts) {
  const id = ++toastId;
  const item = { id, tone: 'info', timeout: opts.tone === 'error' ? 9000 : 4500, ...opts };
  toasts.value = [...toasts.value.slice(-4), item];
  if (item.timeout) setTimeout(() => dismissToast(id), item.timeout);
  return id;
}

export function dismissToast(id) {
  toasts.value = toasts.value.filter((x) => x.id !== id);
}

export function ToastHost() {
  return html`<div class="toasts" role="status" aria-live="polite">
    ${toasts.value.map((x) => html`<div class=${`toast toast--${x.tone}`} key=${x.id}>
      <${Icon} name=${TOAST_ICONS[x.tone] || 'info'} />
      <div class="toast__body">
        ${x.title && html`<div class="toast__title">${x.title}</div>`}
        ${x.message && html`<div class="toast__msg">${x.message}</div>`}
        ${x.action && html`<div style="margin-top:6px"><${Button} variant="link" onClick=${() => { dismissToast(x.id); x.action.onSelect(); }}>${x.action.label}<//></div>`}
      </div>
      <${IconButton} icon="x" size="sm" label=${t('common.dismiss')} onClick=${() => dismissToast(x.id)} />
    </div>`)}
  </div>`;
}
