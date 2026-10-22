import { html, useState, useEffect, cx } from './ui/html.js';
import { Icon, IconButton, Button } from './ui/core.js';
import { ConfirmHost, ToastHost } from './ui/overlays.js';
import { route, navigate } from './lib/router.js';
import { t, locale, loadLocale } from './lib/i18n.js';
import { themePref, setTheme, defaultConnection, connectionsLoaded, jobGroups, preferences } from './lib/stores.js';
import { TranslationsPage } from './pages/translations.js';
import { NewTranslationPage } from './pages/new.js';
import { JobPage } from './pages/job.js';
import { ComparePage } from './pages/compare.js';
import { GlossariesPage, GlossaryPage } from './pages/glossaries.js';
import { NotesPage, NotePage } from './pages/notes.js';
import { StylesPage, StylePage } from './pages/styles.js';
import { SettingsPage } from './pages/settings.js';

export const ROUTES = [
  { name: 'translations', pattern: '/translations' },
  { name: 'new', pattern: '/new' },
  { name: 'job', pattern: '/job/:id' },
  { name: 'job_tab', pattern: '/job/:id/:tab' },
  { name: 'compare', pattern: '/compare' },
  { name: 'glossaries', pattern: '/glossaries' },
  { name: 'glossary', pattern: '/glossaries/:id' },
  { name: 'notes', pattern: '/notes' },
  { name: 'note', pattern: '/notes/:name' },
  { name: 'styles', pattern: '/styles' },
  { name: 'style', pattern: '/styles/:name' },
  { name: 'settings', pattern: '/settings/:section' },
];

const NAV = [
  { id: 'translations', href: '#/translations', icon: 'library', label: () => t('nav.translations'), match: ['translations', 'job', 'job_tab'] },
  { id: 'compare', href: '#/compare', icon: 'scale', label: () => t('nav.compare'), match: ['compare'] },
  { id: 'glossaries', href: '#/glossaries', icon: 'book-a', label: () => t('nav.glossaries'), match: ['glossaries', 'glossary'] },
  { id: 'notes', href: '#/notes', icon: 'notebook-pen', label: () => t('nav.notes'), match: ['notes', 'note'] },
  { id: 'styles', href: '#/styles', icon: 'feather', label: () => t('nav.styles'), match: ['styles', 'style'] },
  { id: 'settings', href: '#/settings/connections', icon: 'settings', label: () => t('nav.settings'), match: ['settings'] },
];

function ModelStatus() {
  const conn = defaultConnection.value;
  const prefs = preferences.value;
  if (!connectionsLoaded.value) return null;
  const model = (prefs && prefs.default_model) || (conn && conn.default_model);
  let dot = 'ok';
  if (!conn || !model) dot = 'warn';
  else if (conn.status && conn.status.ok === false) dot = 'err';
  const label = conn && model ? model : t('shell.no_model');
  const sub = conn ? conn.name : t('shell.set_up_model');
  return html`<a class="model-status" href="#/settings/connections" title=${t('shell.model_status_title')}>
    <span class=${`status-dot status-dot--${dot}`} />
    <span class="stack grow" style="--gap:0">
      <span class="truncate" style="color:var(--text);font-weight:550">${label}</span>
      <span class="truncate faint">${sub}</span>
    </span>
  </a>`;
}

function ThemeSwitch() {
  const opts = [
    { v: 'light', icon: 'sun', label: t('appearance.theme_light') },
    { v: 'dark', icon: 'moon', label: t('appearance.theme_dark') },
    { v: 'system', icon: 'monitor', label: t('appearance.theme_system') },
  ];
  return html`<div class="row" style="--gap:2px" role="group" aria-label=${t('appearance.theme')}>
    ${opts.map((o) => html`<${IconButton} icon=${o.icon} size="sm" label=${o.label} pressed=${themePref.value === o.v} onClick=${() => setTheme(o.v)} />`)}
  </div>`;
}

function LocaleSwitch() {
  const other = locale.value === 'ko' ? 'en' : 'ko';
  return html`<${Button} variant="ghost" size="sm" icon="globe" onClick=${() => loadLocale(other)}
    title=${t('appearance.language')} aria-label=${t('appearance.switch_language')}>
    ${locale.value === 'ko' ? '한국어' : 'English'}
  <//>`;
}

function Sidebar({ onNavigate }) {
  const r = route.value;
  const groups = jobGroups.value;
  const activeCount = groups.inProgress.length + groups.attention.length;
  return html`<aside class="sidebar" aria-label=${t('shell.sidebar')}>
    <div class="sidebar__brand">
      <img class="sidebar__logo" src="/static/TBL-Logo-alpha.png" alt="" />
      <span class="sidebar__name">TBL</span>
    </div>
    <${Button} variant="primary" icon="plus" class="sidebar__new" href="#/new" onClick=${onNavigate}>${t('nav.new')}<//>
    <nav aria-label=${t('shell.main_nav')}>
      <ul class="nav">
        ${NAV.map((item) => html`<li>
          <a class="nav__item" href=${item.href} aria-current=${item.match.includes(r.name) ? 'page' : undefined} onClick=${onNavigate}>
            <${Icon} name=${item.icon} />
            <span>${item.label()}</span>
            ${item.id === 'translations' && activeCount > 0 && html`<span class="nav__count">${activeCount}</span>`}
          </a>
        </li>`)}
      </ul>
    </nav>
    <div class="sidebar__footer">
      <${ModelStatus} />
      <div class="row row--between sidebar__prefs">
        <${ThemeSwitch} />
        <${LocaleSwitch} />
      </div>
    </div>
  </aside>`;
}

function NotFound() {
  return html`<div class="page"><div class="empty">
    <div class="empty__icon"><${Icon} name="circle-alert" size="xl" /></div>
    <div class="empty__title">${t('shell.not_found')}</div>
    <div class="empty__actions"><${Button} href="#/translations">${t('shell.back_home')}<//></div>
  </div></div>`;
}

function CurrentPage() {
  const r = route.value;
  switch (r.name) {
    case 'translations': return html`<${TranslationsPage} />`;
    case 'new': return html`<${NewTranslationPage} />`;
    case 'job': return html`<${JobPage} id=${r.params.id} tab="progress" />`;
    case 'job_tab': return html`<${JobPage} id=${r.params.id} tab=${r.params.tab} />`;
    case 'compare': return html`<${ComparePage} query=${r.query} />`;
    case 'glossaries': return html`<${GlossariesPage} />`;
    case 'glossary': return html`<${GlossaryPage} id=${r.params.id} />`;
    case 'notes': return html`<${NotesPage} />`;
    case 'note': return html`<${NotePage} name=${r.params.name} />`;
    case 'styles': return html`<${StylesPage} />`;
    case 'style': return html`<${StylePage} name=${r.params.name} />`;
    case 'settings': return html`<${SettingsPage} section=${r.params.section} />`;
    default: return html`<${NotFound} />`;
  }
}

export function App() {
  const [navOpen, setNavOpen] = useState(false);
  const r = route.value;
  useEffect(() => { setNavOpen(false); window.scrollTo(0, 0); }, [r.name, r.params.id, r.params.name, r.params.section]);
  useEffect(() => { document.documentElement.lang = locale.value; }, [locale.value]);
  return html`<div class=${cx('app', navOpen && 'app--nav-open')}>
    <div class="topbar">
      <${IconButton} icon="menu" label=${t('shell.open_menu')} onClick=${() => setNavOpen(true)} />
      <img class="sidebar__logo" src="/static/TBL-Logo-alpha.png" alt="" />
      <span class="sidebar__name">TBL</span>
    </div>
    ${navOpen && html`<div class="nav-scrim" onClick=${() => setNavOpen(false)} />`}
    <${Sidebar} onNavigate=${() => setNavOpen(false)} />
    <main class="main" id="main">
      <${CurrentPage} />
    </main>
    <${ConfirmHost} />
    <${ToastHost} />
  </div>`;
}

export { navigate };
