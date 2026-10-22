// Live updates from the server. Jobs arrive as full summaries (design §14.4).
import { signal } from '../../vendor/signals-core.mjs';
import { upsertJob, dropJob, queueState, loadJobs } from './stores.js';

export const socketConnected = signal(false);
const listeners = new Map(); // event -> Set<fn>
let socket = null;

/** Subscribe to a raw socket event; returns an unsubscribe function. */
export function onSocket(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

function emitLocal(event, payload) {
  const set = listeners.get(event);
  if (set) for (const fn of set) { try { fn(payload); } catch (e) { console.error(e); } }
}

export function connectSocket() {
  if (socket || !window.io) return;
  socket = window.io({ auth: { token: window.__TBL_TOKEN__ }, transports: ['websocket', 'polling'] });
  socket.on('connect', () => {
    socketConnected.value = true;
    loadJobs().catch(() => {});
  });
  // A restarted server mints a new API token and refuses ours; reload to pick it up.
  socket.on('connect_error', () => { if (!socket.active) window.location.reload(); });
  socket.on('disconnect', () => { socketConnected.value = false; });
  socket.on('job_update', (msg) => {
    if (msg && msg.job) upsertJob(msg.job);
    emitLocal('job_update', msg);
  });
  socket.on('job_removed', (msg) => {
    if (msg && msg.id) dropJob(msg.id);
    emitLocal('job_removed', msg);
  });
  socket.on('queue_update', (msg) => {
    if (msg) queueState.value = { ...queueState.value, ...msg };
  });
  socket.on('sample_update', (msg) => emitLocal('sample_update', msg));
  socket.on('translation_update', (msg) => emitLocal('translation_update', msg));
}
