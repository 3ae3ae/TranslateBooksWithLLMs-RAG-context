import { html, useState, cx } from './html.js';
import { Icon, Pill, Callout } from './core.js';
import { Textarea } from './forms.js';
import { t } from '../lib/i18n.js';

const SECTION_HELP = {
  characters: 'notes.help.characters',
  aliases: 'notes.help.aliases',
  name_map: 'notes.help.name_map',
  glossary: 'notes.help.glossary',
  addressing: 'notes.help.addressing',
  relationships: 'notes.help.relationships',
};

function sectionTitle(s) {
  const key = `notes.section.${s.key}`;
  const label = t(key);
  return label === key ? s.title : label;
}

/** Read-only notes: one card per section, book-wide first. */
export function NotesView({ sections, emptyText }) {
  const visible = (sections || []).filter((s) => (s.body || '').trim());
  if (!visible.length) return html`<p class="muted">${emptyText || t('notes.empty')}</p>`;
  const book = visible.filter((s) => s.scope !== 'story');
  const story = visible.filter((s) => s.scope === 'story');
  const card = (s) => html`<div class=${cx('notes-card', s.scope === 'story' && 'notes-card--current')}>
    <div class="notes-card__title row">${sectionTitle(s)}${!s.editable && html`<${Pill}>${t('notes.generated')}<//>`}</div>
    <div class="notes-card__body">${s.body}</div>
  </div>`;
  return html`<div class="stack" style="--gap:20px">
    ${book.length > 0 && html`<div class="stack" style="--gap:8px">
      <h3>${t('notes.scope.book')}</h3>
      <div class="notes-grid">${book.map(card)}</div>
    </div>`}
    ${story.length > 0 && html`<div class="stack" style="--gap:8px">
      <h3>${t('notes.scope.story')}</h3>
      <p class="small muted">${t('notes.scope.story_help')}</p>
      <div class="notes-grid">${story.map(card)}</div>
    </div>`}
  </div>`;
}

/** Editable notes: a textarea per editable section; generated ones stay read-only. */
export function NotesEditor({ sections, onChange }) {
  const update = (key, body) => onChange(sections.map((s) => (s.key === key ? { ...s, body } : s)));
  return html`<div class="stack" style="--gap:18px">
    <p class="small muted">${t('notes.edit_help')}</p>
    ${sections.map((s) => html`<div class="field">
      <div class="row row--between">
        <label class="field__label" for=${`notes-${s.key}`}>${sectionTitle(s)}
          ${s.scope === 'story' && html` <span class="faint">${t('notes.scope.story_short')}</span>`}</label>
        ${!s.editable && html`<${Pill}>${t('notes.generated')}<//>`}
      </div>
      ${SECTION_HELP[s.key] && html`<div class="field__help">${t(SECTION_HELP[s.key])}</div>`}
      ${s.editable
        ? html`<${Textarea} id=${`notes-${s.key}`} rows=${Math.min(14, Math.max(3, (s.body || '').split('\n').length + 1))}
            value=${s.body} onInput=${(v) => update(s.key, v)} spellcheck="false" />`
        : html`<div class="notes-card__body card card--flat" style="padding:10px 12px">${s.body || '—'}</div>`}
    </div>`)}
  </div>`;
}

/** What a save will actually store (server normalization) and what it drops. */
export function NormalizationPreview({ result, original }) {
  if (!result) return null;
  const changed = (result.normalized_sections || []).filter((s) => {
    const o = (original || []).find((x) => x.key === s.key);
    return o && (o.body || '').trim() !== (s.body || '').trim();
  });
  const removed = result.removed_lines || [];
  return html`<div class="stack">
    ${removed.length > 0 && html`<${Callout} tone="warning" title=${t('notes.preview.removed', { count: removed.length })}>
      <ul style="margin:4px 0 0;padding-left:18px">${removed.slice(0, 12).map((l) => html`<li class="mono small">${l}</li>`)}</ul>
      ${removed.length > 12 && html`<div class="small">${t('notes.preview.more', { count: removed.length - 12 })}</div>`}
    <//>`}
    ${changed.length > 0 && html`<div class="stack" style="--gap:6px">
      <div class="small muted">${t('notes.preview.normalized')}</div>
      ${changed.map((s) => html`<div class="notes-card"><div class="notes-card__title">${sectionTitle(s)}</div><div class="notes-card__body">${s.body}</div></div>`)}
    </div>`}
    ${!removed.length && !changed.length && html`<div class="row small muted"><${Icon} name="check" size="sm" />${t('notes.preview.clean')}</div>`}
  </div>`;
}
