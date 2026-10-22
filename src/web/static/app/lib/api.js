// One function per backend endpoint used by the app (contracts: design §14).
import { get, post, patch, put, del, request } from './api-core.js';

const enc = encodeURIComponent;

// ---- model connections
export const connectionsApi = {
  types: () => get('/api/connection-types'),
  list: () => get('/api/connections'),
  create: (body) => post('/api/connections', body),
  update: (id, body) => patch(`/api/connections/${enc(id)}`, body),
  remove: (id) => del(`/api/connections/${enc(id)}`),
  setDefault: (id, model) => post(`/api/connections/${enc(id)}/default`, model ? { model } : {}),
  test: (body) => post('/api/connections/test', body),
  models: (id) => get(`/api/connections/${enc(id)}/models`),
};

// ---- defaults / preferences
export const preferencesApi = {
  get: () => get('/api/preferences'),
  patch: (values) => patch('/api/preferences', values),
};

// ---- jobs & queue
export const jobsApi = {
  list: () => get('/api/jobs'),
  get: (id) => get(`/api/jobs/${enc(id)}`),
  create: (body) => post('/api/jobs', body),
  pause: (id) => post(`/api/jobs/${enc(id)}/pause`, {}),
  resume: (id, overrides) => post(`/api/jobs/${enc(id)}/resume`, overrides || {}),
  move: (id, to) => post(`/api/jobs/${enc(id)}/move`, { to }),
  removeFromQueue: (id) => post(`/api/jobs/${enc(id)}/remove-from-queue`, {}),
  remove: (id, deleteOutput) => del(`/api/jobs/${enc(id)}`, { query: { delete_output: deleteOutput ? 1 : 0 } }),
  continueWith: (id, body) => post(`/api/jobs/${enc(id)}/continue`, body),
  passages: (id, params) => get(`/api/jobs/${enc(id)}/passages`, { query: params }),
  log: (id, tail = 500) => get(`/api/jobs/${enc(id)}/log`, { query: { tail } }),
  open: (id) => post(`/api/jobs/${enc(id)}/open`, {}),
  reveal: (id) => post(`/api/jobs/${enc(id)}/reveal`, {}),
  coverPath: (id) => `/api/jobs/${enc(id)}/cover`,
  downloadPath: (filename) => `/api/files/${enc(filename)}`,
};

export const queueApi = {
  get: () => get('/api/queue'),
  setPaused: (paused) => post('/api/queue', { paused }),
};

export const estimateApi = {
  estimate: (body, signal) => post('/api/estimate', body, { signal }),
};

// ---- uploads
export const uploadsApi = {
  upload: (file, signal) => {
    const form = new FormData();
    form.append('file', file);
    return request('POST', '/api/upload', { form, signal });
  },
  // Abandoned upload: deleted by its stored file name (referenced uploads are protected).
  remove: (filePath) => post(`/api/uploads/${enc(String(filePath).split(/[\\/]/).pop())}/delete`, {}),
};

// ---- job story notes (rebuild = "resync")
export const jobNotesApi = {
  snapshot: (id, index, scope) => get(`/api/translation/${enc(id)}/context/${enc(index)}`, { query: { scope, format: 'sections' } }),
  resync: (id, index, body) => post(`/api/translation/${enc(id)}/context/${enc(index)}/resync`, body),
  pauseResync: (id) => post(`/api/translation/${enc(id)}/context/resync/pause`, {}),
  resumeResync: (id, body) => post(`/api/translation/${enc(id)}/context/resync/resume`, body || {}),
};

// ---- story notes library
export const notesApi = {
  list: () => get('/api/notes'),
  get: (name) => get(`/api/notes/${enc(name)}`),
  save: (name, sections, dryRun) => put(`/api/notes/${enc(name)}`, { sections }, { query: dryRun ? { dry_run: 1 } : undefined }),
  create: (name, from) => post('/api/notes', from ? { name, from } : { name }),
  rename: (name, newName) => post(`/api/notes/${enc(name)}/rename`, { name: newName }),
  remove: (name) => del(`/api/notes/${enc(name)}`),
};

// ---- style guides
export const stylesApi = {
  list: () => get('/api/styles'),
  get: (name) => get(`/api/styles/${enc(name)}`),
  create: (body) => post('/api/styles', body),
  save: (name, body) => put(`/api/styles/${enc(name)}`, body),
  remove: (name) => del(`/api/styles/${enc(name)}`),
  duplicate: (name, newName) => post(`/api/styles/${enc(name)}/duplicate`, { name: newName }),
};

// ---- compare (sample)
export const compareApi = {
  initialize: (body) => post('/api/sample/initialize', body),
  run: (body) => post('/api/sample/run', body),
  dispatch: (sampleId, body) => post(`/api/sample/${enc(sampleId)}/dispatch`, body || {}),
  stop: (sampleId) => post(`/api/sample/${enc(sampleId)}/stop`, {}),
  extract: (body) => post('/api/sample/extract', body),
};

// ---- misc
export const foldersApi = {
  open: (which) => post(`/api/folders/${enc(which)}/open`, {}),
};

export const healthApi = {
  get: () => get('/api/health'),
};
