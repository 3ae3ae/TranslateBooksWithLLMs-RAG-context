import { signal } from '../../vendor/signals-core.mjs';

// The app registers its routes with defineRoutes() at boot.
let routes = [];

function matchRoute() {
    const hash = window.location.hash.replace(/^#/, '');
    const separator = hash.indexOf('?');
    let path = (separator < 0 ? hash : hash.slice(0, separator)).replace(/\/$/, '');
    if (!path) path = '/translations';
    if (path === '/settings') path = '/settings/connections';
    const query = Object.fromEntries(new URLSearchParams(separator < 0 ? '' : hash.slice(separator + 1)));
    const segments = path.split('/');
    for (const { name, pattern } of routes) {
        const parts = pattern.split('/');
        if (parts.length !== segments.length) continue;
        const params = {};
        try {
            if (parts.every((part, index) => {
                if (!part.startsWith(':')) return part === segments[index];
                if (!segments[index]) return false;
                params[part.slice(1)] = decodeURIComponent(segments[index]);
                return true;
            })) return { name, params, path, query };
        } catch { /* Malformed URL escapes do not match a route. */ }
    }
    return { name: 'not_found', params: {}, path, query };
}

export const route = signal(matchRoute());
const updateRoute = () => { route.value = matchRoute(); };
window.addEventListener('hashchange', updateRoute);

export function defineRoutes(definitions) {
    routes = definitions;
    updateRoute();
}

export function navigate(path, { replace = false } = {}) {
    const hash = `#${path.replace(/^#/, '')}`;
    if (replace) window.history.replaceState(null, '', hash);
    else window.location.hash = hash;
    updateRoute();
}
