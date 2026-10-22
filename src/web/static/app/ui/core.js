import { html, cx, useEffect, useState } from './html.js';
import { ICONS } from './icons.js';
import { blobUrl } from '../lib/api-core.js';
import { t } from '../lib/i18n.js';

export function Icon({ name, size, class: className, title }) {
  const inner = ICONS[name] || ICONS.circle;
  return html`<svg
    class=${cx('icon', size && `icon--${size}`, className)}
    viewBox="0 0 24 24"
    aria-hidden=${title ? undefined : 'true'}
    role=${title ? 'img' : undefined}
    dangerouslySetInnerHTML=${{ __html: (title ? `<title>${title}</title>` : '') + inner }}
  />`;
}

export function Spinner({ size }) {
  return html`<${Icon} name="loader-circle" size=${size} class="spinner" />`;
}

/**
 * Button. `variant`: primary | secondary | ghost | danger | danger-ghost | link.
 * `href` renders an anchor. `loading` swaps the icon for a spinner and disables.
 */
export function Button({
  variant = 'secondary', size, icon, iconRight, loading, block, href, children,
  class: className, disabled, type = 'button', ...rest
}) {
  const classes = cx('btn', `btn--${variant}`, size && `btn--${size}`, block && 'btn--block', className);
  const content = html`
    ${loading ? html`<${Spinner} />` : icon && html`<${Icon} name=${icon} />`}
    ${children && html`<span>${children}</span>`}
    ${iconRight && html`<${Icon} name=${iconRight} />`}
  `;
  if (href && !disabled) return html`<a class=${classes} href=${href} ...${rest}>${content}</a>`;
  return html`<button type=${type} class=${classes} disabled=${disabled || loading} aria-busy=${loading ? 'true' : undefined} ...${rest}>${content}</button>`;
}

export function IconButton({ icon, label, size, class: className, pressed, ...rest }) {
  return html`<button
    type="button"
    class=${cx('icon-btn', size && `icon-btn--${size}`, className)}
    aria-label=${label}
    title=${label}
    aria-pressed=${pressed === undefined ? undefined : String(!!pressed)}
    ...${rest}
  ><${Icon} name=${icon} /></button>`;
}

export function Pill({ tone, icon, dot, children, title, class: className }) {
  return html`<span class=${cx('pill', tone && `pill--${tone}`, className)} title=${title}>
    ${dot && html`<span class=${cx('status-dot', dot && `status-dot--${dot}`)} />`}
    ${icon && html`<${Icon} name=${icon} />`}
    ${children}
  </span>`;
}

export function Progress({ value, tone, size, indeterminate, label }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return html`<div
    class=${cx('progress', size && `progress--${size}`, tone && `progress--${tone}`, indeterminate && 'progress--indeterminate')}
    role="progressbar"
    aria-label=${label}
    aria-valuemin="0"
    aria-valuemax="100"
    aria-valuenow=${indeterminate ? undefined : Math.round(pct)}
  ><div class="progress__bar" style=${{ width: `${pct}%` }} /></div>`;
}

const CALLOUT_ICONS = { info: 'info', warning: 'triangle-alert', danger: 'circle-alert', success: 'circle-check' };

export function Callout({ tone = 'info', title, icon, children, actions, class: className }) {
  return html`<div class=${cx('callout', `callout--${tone}`, className)} role=${tone === 'danger' ? 'alert' : undefined}>
    <${Icon} name=${icon || CALLOUT_ICONS[tone] || 'info'} />
    <div class="callout__body grow">
      ${title && html`<div class="callout__title">${title}</div>`}
      ${children && html`<div>${children}</div>`}
      ${actions && html`<div class="row row--wrap" style="margin-top:6px">${actions}</div>`}
    </div>
  </div>`;
}

export function EmptyState({ icon = 'book-open', title, children, actions }) {
  return html`<div class="empty">
    <div class="empty__icon"><${Icon} name=${icon} size="xl" /></div>
    <div class="empty__title">${title}</div>
    ${children && html`<div class="empty__desc">${children}</div>`}
    ${actions && html`<div class="empty__actions">${actions}</div>`}
  </div>`;
}

export function Kbd({ children }) {
  return html`<kbd class="kbd">${children}</kbd>`;
}

const FORMAT_ICONS = { epub: 'book-open', docx: 'file-text', txt: 'file-text', srt: 'subtitles' };

/** Book cover from an authenticated URL, or a format icon. */
export function Cover({ src, format, size = 'md' }) {
  const [url, setUrl] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    setUrl(null);
    setFailed(false);
    if (src) {
      blobUrl(src).then((u) => { if (alive) setUrl(u); }).catch(() => { if (alive) setFailed(true); });
    }
    return () => { alive = false; };
  }, [src]);
  const ext = (format || '').toLowerCase();
  return html`<div class=${cx('cover', `cover--${size}`)}>
    ${url && !failed
      ? html`<img src=${url} alt="" onError=${() => setFailed(true)} />`
      : html`<div class="stack" style="--gap:2px;align-items:center">
          <${Icon} name=${FORMAT_ICONS[ext] || 'file'} size=${size === 'lg' ? 'lg' : 'sm'} />
          ${size !== 'sm' && ext && html`<span class="cover__ext">${ext.toUpperCase()}</span>`}
        </div>`}
  </div>`;
}

/** Inline "Saved" / "Saving…" indicator for autosaving forms. */
export function SavedIndicator({ state }) {
  if (state === 'saving') return html`<span class="saved-indicator"><${Spinner} size="sm" />${t('common.saving')}</span>`;
  if (state === 'saved') return html`<span class="saved-indicator saved-indicator--ok"><${Icon} name="check" size="sm" />${t('common.saved')}</span>`;
  if (state === 'error') return html`<span class="saved-indicator" style="color:var(--danger)"><${Icon} name="circle-alert" size="sm" />${t('common.save_failed')}</span>`;
  return null;
}
