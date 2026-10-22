import { signal } from '../../vendor/signals-core.mjs';
import { get, post } from './api-core.js';

const supported = ['en', 'ko'];
export const locale = signal(supported.includes(window.__INITIAL_LOCALE__)
    ? window.__INITIAL_LOCALE__ : 'en');
const catalogs = signal({});
const pending = new Map();
let latestLoad = 0;

function loadCatalog(code) {
    if (!pending.has(code)) {
        pending.set(code, get(`/static/app/i18n/${code}.json`).then(messages => {
            catalogs.value = { ...catalogs.peek(), [code]: messages };
        }).catch(error => {
            pending.delete(code);
            throw error;
        }));
    }
    return pending.get(code);
}

export async function loadLocale(code) {
    if (!supported.includes(code)) throw new RangeError(`Unsupported locale: ${code}`);
    const id = ++latestLoad;
    await Promise.all((code === 'en' ? ['en'] : ['en', code]).map(loadCatalog));
    if (id === latestLoad) {
        locale.value = code;
        void post('/api/ui-locale', { locale: code }).catch(() => {});
    }
    return locale.value;
}

export function t(key, params = {}) {
    const code = locale.value;
    const messages = catalogs.value;
    let text;
    for (const language of new Set([code, 'en'])) {
        const catalog = messages[language] || {};
        const form = typeof params.count === 'number'
            ? new Intl.PluralRules(language).select(params.count) : null;
        const pluralKey = `${key}_${form}`;
        text = form && Object.hasOwn(catalog, pluralKey) ? catalog[pluralKey]
            : Object.hasOwn(catalog, key) ? catalog[key] : undefined;
        if (text !== undefined) break;
    }
    return (text ?? key).replace(/\{\{\s*([^{}\s]+)\s*\}\}/g,
        (placeholder, name) => Object.hasOwn(params, name) ? String(params[name]) : placeholder);
}
