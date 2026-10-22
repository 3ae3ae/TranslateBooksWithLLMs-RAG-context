// App-wide state as signals. Pages read these; loaders refresh them from the API.
import { signal, computed } from '../../vendor/signals-core.mjs';
import { connectionsApi, preferencesApi, jobsApi, queueApi, glossariesApi, notesApi, stylesApi } from './api.js';

// ---------------------------------------------------------------- theme
const THEME_KEY = 'tbl.theme';
export const themePref = signal(readLocal(THEME_KEY) || 'system');
const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

export function applyTheme() {
  const pref = themePref.value;
  const dark = pref === 'dark' || (pref === 'system' && media && media.matches);
  document.documentElement.toggleAttribute('data-theme', false);
  if (dark) document.documentElement.setAttribute('data-theme', 'dark');
}
export function setTheme(pref) {
  themePref.value = pref;
  writeLocal(THEME_KEY, pref);
  applyTheme();
}
if (media) media.addEventListener('change', applyTheme);

const FONT_KEY = 'tbl.bookFont';
export const bookFont = signal(readLocal(FONT_KEY) || 'sans');
export function setBookFont(value) {
  bookFont.value = value;
  writeLocal(FONT_KEY, value);
  document.documentElement.dataset.bookFont = value;
}
document.documentElement.dataset.bookFont = bookFont.value;

function readLocal(key) { try { return localStorage.getItem(key); } catch { return null; } }
function writeLocal(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } }

// --------------------------------------------------------- connections
export const connectionTypes = signal([]);
export const connections = signal([]);
export const connectionsLoaded = signal(false);
export const connectionsError = signal(null);
const modelCache = new Map();
export const modelsByConnection = signal({});

export async function loadConnections() {
  try {
    const [types, list] = await Promise.all([
      connectionTypes.value.length ? null : connectionsApi.types(),
      connectionsApi.list(),
    ]);
    if (types) connectionTypes.value = types.types || types;
    const def = list.default || {};
    connections.value = (list.connections || []).map((c) => ({ ...c, is_default: c.id === def.connection_id }));
    connectionsError.value = null;
  } catch (e) {
    connectionsError.value = e;
  } finally {
    connectionsLoaded.value = true;
  }
}

export const defaultConnection = computed(() => connections.value.find((c) => c.is_default) || null);

/** Model list for a connection; cached for the session unless `refresh`. */
export async function loadModels(connectionId, { refresh } = {}) {
  if (!connectionId) return [];
  if (!refresh && modelCache.has(connectionId)) return modelCache.get(connectionId);
  const set = (state) => { modelsByConnection.value = { ...modelsByConnection.value, [connectionId]: state }; };
  set({ loading: true, models: (modelsByConnection.value[connectionId] || {}).models || [] });
  const p = connectionsApi.models(connectionId)
    .then((r) => { const models = r.models || []; set({ loading: false, models }); return models; })
    .catch((error) => { modelCache.delete(connectionId); set({ loading: false, models: [], error }); return []; });
  modelCache.set(connectionId, p);
  return p;
}

export function typeInfo(type) {
  return connectionTypes.value.find((x) => x.type === type) || null;
}

// --------------------------------------------------------- preferences
export const preferences = signal(null);
export const preferencesSchema = signal({});

export async function loadPreferences() {
  try {
    const r = await preferencesApi.get();
    preferences.value = r.values;
    preferencesSchema.value = r.schema || {};
  } catch (e) {
    // Forms still work with built-in defaults when defaults can't be read.
    if (!preferences.value) preferences.value = {};
    throw e;
  }
  return preferences.value;
}

export async function savePreferences(patchValues) {
  const r = await preferencesApi.patch(patchValues);
  preferences.value = r.values;
  return r.values;
}

// ---------------------------------------------------------------- jobs
export const jobsById = signal({});
export const jobsLoaded = signal(false);
export const queueState = signal({ paused: false, reason: null });

export async function loadJobs() {
  const [list, queue] = await Promise.all([jobsApi.list(), queueApi.get().catch(() => null)]);
  const map = {};
  for (const j of list.jobs || []) map[j.id] = j;
  jobsById.value = map;
  if (queue) queueState.value = queue;
  jobsLoaded.value = true;
}

export function upsertJob(job) {
  if (!job || !job.id) return;
  jobsById.value = { ...jobsById.value, [job.id]: { ...(jobsById.value[job.id] || {}), ...job } };
}

export function dropJob(id) {
  if (!(id in jobsById.value)) return;
  const next = { ...jobsById.value };
  delete next[id];
  jobsById.value = next;
}

const byQueue = (a, b) => (a.queue_position ?? 1e9) - (b.queue_position ?? 1e9);
const byUpdated = (a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
const byFinished = (a, b) => String(b.finished_at || b.updated_at || '').localeCompare(String(a.finished_at || a.updated_at || ''));

export const jobGroups = computed(() => {
  const all = Object.values(jobsById.value);
  const running = all.filter((j) => j.status === 'running');
  const queued = all.filter((j) => j.status === 'queued').sort(byQueue);
  const attention = all.filter((j) => ['paused', 'waiting', 'partial', 'failed'].includes(j.status)).sort(byUpdated);
  const finished = all.filter((j) => j.status === 'completed').sort(byFinished);
  return { inProgress: [...running, ...queued], attention, finished, total: all.length };
});

// ----------------------------------------------------------- resources
export const glossaries = signal(null);
export const notesList = signal(null);
export const stylesList = signal(null);

export async function loadGlossaries() {
  const r = await glossariesApi.list();
  glossaries.value = r.glossaries || r || [];
  return glossaries.value;
}
export async function loadNotes() {
  const r = await notesApi.list();
  notesList.value = r.notes || r || [];
  return notesList.value;
}
export async function loadStyles() {
  const r = await stylesApi.list();
  stylesList.value = r.styles || r || [];
  return stylesList.value;
}

// ------------------------------------------------------- compose draft
// The New translation form survives navigation within the session.
export const draft = signal(null);
