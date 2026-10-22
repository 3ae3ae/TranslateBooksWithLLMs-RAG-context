import { html, render } from './ui/html.js';
import { App, ROUTES } from './app.js';
import { defineRoutes } from './lib/router.js';
import { loadLocale, locale } from './lib/i18n.js';
import { applyTheme, loadConnections, loadPreferences, loadJobs } from './lib/stores.js';
import { connectSocket } from './lib/socket.js';

async function boot() {
  applyTheme();
  defineRoutes(ROUTES);
  await loadLocale(locale.value).catch(() => loadLocale('en'));
  render(html`<${App} />`, document.getElementById('app'));
  // Data loads in parallel; pages render loading states until it arrives.
  loadConnections();
  loadPreferences().catch(() => {});
  loadJobs().catch(() => {});
  if (window.io) connectSocket();
  else window.addEventListener('load', connectSocket, { once: true });
}

boot();
