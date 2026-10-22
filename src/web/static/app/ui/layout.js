import { html, cx, useState, useRef, useEffect, useUid } from './html.js';
import { Icon } from './core.js';
import { t } from '../lib/i18n.js';

export function PageHeader({ title, subtitle, back, actions }) {
  return html`<header class="page__header">
    <div class="page__titles">
      ${back && html`<a class="page__back" href=${back.href}><${Icon} name="arrow-left" size="sm" />${back.label}</a>`}
      <h1>${title}</h1>
      ${subtitle && html`<p class="page__subtitle">${subtitle}</p>`}
    </div>
    ${actions && html`<div class="row row--wrap">${actions}</div>`}
  </header>`;
}

export function Section({ step, title, desc, aside, children, id }) {
  return html`<section class="section" id=${id} aria-labelledby=${id && `${id}-title`}>
    <div class="section__head">
      <div>
        <h2 class="section__title" id=${id && `${id}-title`}>
          ${step && html`<span class="section__step" aria-hidden="true">${step}</span>`}${title}
        </h2>
        ${desc && html`<p class="section__desc">${desc}</p>`}
      </div>
      ${aside}
    </div>
    ${children}
  </section>`;
}

/**
 * Tabs. items: [{id, label, href?, count?}]. With href the tabs are links
 * (route-driven); otherwise onSelect(id) is called.
 */
export function Tabs({ items, current, onSelect, label }) {
  return html`<nav class="tabs" role="tablist" aria-label=${label}>
    ${items.map((it) => it.href
      ? html`<a class="tab" role="tab" href=${it.href} aria-selected=${String(it.id === current)}>
          ${it.label}${it.count !== undefined && html`<span class="tab__count">${it.count}</span>`}
        </a>`
      : html`<button type="button" class="tab" role="tab" aria-selected=${String(it.id === current)} onClick=${() => onSelect(it.id)}>
          ${it.label}${it.count !== undefined && html`<span class="tab__count">${it.count}</span>`}
        </button>`)}
  </nav>`;
}

export function Disclosure({ title, defaultOpen = false, inset, children, open: controlled, onToggle }) {
  const [own, setOwn] = useState(defaultOpen);
  const open = controlled !== undefined ? controlled : own;
  const id = useUid('disc');
  const toggle = () => { if (onToggle) onToggle(!open); else setOwn(!open); };
  return html`<div class=${cx('disclosure', inset && 'disclosure--inset')}>
    <button type="button" class="disclosure__toggle" aria-expanded=${String(open)} aria-controls=${id} onClick=${toggle}>
      <${Icon} name="chevron-right" size="sm" />${title}
    </button>
    ${open && html`<div class="disclosure__body" id=${id}>${children}</div>`}
  </div>`;
}

/**
 * File drop target with a hidden picker. onFiles(FileList-like array).
 * `accept` example: ".epub,.docx,.txt,.srt".
 */
export function Dropzone({ onFiles, accept, multiple = true, title, hint, compact, disabled }) {
  const [active, setActive] = useState(false);
  const inputRef = useRef(null);
  const take = (list) => { const files = [...(list || [])]; if (files.length) onFiles(multiple ? files : files.slice(0, 1)); };
  return html`<div
    class=${cx('dropzone', compact && 'dropzone--compact', active && 'dropzone--active')}
    role="button"
    tabindex=${disabled ? -1 : 0}
    aria-disabled=${disabled ? 'true' : undefined}
    onClick=${() => !disabled && inputRef.current.click()}
    onKeyDown=${(e) => { if (!disabled && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); inputRef.current.click(); } }}
    onDragOver=${(e) => { e.preventDefault(); e.stopPropagation(); if (!disabled) setActive(true); }}
    onDragLeave=${() => setActive(false)}
    onDrop=${(e) => { e.preventDefault(); setActive(false); if (!disabled) take(e.dataTransfer.files); }}
  >
    <div class="dropzone__icon"><${Icon} name="file-up" /></div>
    <div class=${compact ? 'stack' : 'stack'} style="--gap:2px">
      <div class="dropzone__title">${title || t('common.drop_files')}</div>
      ${hint && html`<div class="small">${hint}</div>`}
    </div>
    <input ref=${inputRef} type="file" class="hidden" accept=${accept} multiple=${multiple}
      onChange=${(e) => { take(e.currentTarget.files); e.currentTarget.value = ''; }} />
  </div>`;
}

/** Whole-page drop overlay: calls onFiles when files are dropped anywhere on the page. */
export function usePageDrop(onFiles, enabled = true) {
  const [over, setOver] = useState(false);
  useEffect(() => {
    if (!enabled) return undefined;
    let depth = 0;
    const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
    const enter = (e) => { if (!hasFiles(e)) return; depth += 1; setOver(true); };
    const leave = (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) setOver(false); };
    const over_ = (e) => { if (hasFiles(e)) e.preventDefault(); };
    const drop = (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); depth = 0; setOver(false);
      if (e.defaultPrevented && e.target.closest && e.target.closest('.dropzone')) return;
      onFiles([...e.dataTransfer.files]);
    };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', over_);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('dragover', over_);
      window.removeEventListener('drop', drop);
    };
  }, [enabled, onFiles]);
  return over;
}
