export class ApiError extends Error {
    constructor(status, code, message, details = null) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
        this.details = details;
    }
}

async function fetchResponse(method, path, { json, query, form, signal } = {}) {
    const url = new URL(path, window.location.href);
    if (url.origin !== window.location.origin) {
        throw new TypeError('API requests require a same-origin URL');
    }
    if (json !== undefined && form !== undefined) {
        throw new TypeError('Use either json or form');
    }
    for (const [key, value] of Object.entries(query || {})) {
        if (value !== undefined && value !== null) url.searchParams.set(key, value);
    }
    const headers = {};
    if (window.__TBL_TOKEN__) headers['X-API-Token'] = window.__TBL_TOKEN__;
    if (json !== undefined) headers['Content-Type'] = 'application/json';
    let response;
    try {
        response = await fetch(url.pathname + url.search, {
            method, headers, signal,
            body: json !== undefined ? JSON.stringify(json) : form,
        });
    } catch (error) {
        throw new ApiError(0, 'network', error.message);
    }
    if (!response.ok) {
        const body = await response.json().catch(() => null);
        const error = body?.error;
        throw new ApiError(
            response.status,
            error?.code || body?.code || 'http_error',
            (typeof error === 'string' ? error : error?.message)
                || body?.message || response.statusText || `HTTP ${response.status}`,
            error?.details ?? body?.details ?? null,
        );
    }
    return response;
}

export async function request(method, path, options) {
    const response = await fetchResponse(method, path, options);
    if (response.status === 204) return null;
    try { return await response.json(); } catch (error) {
        const invalidJson = error instanceof SyntaxError;
        throw new ApiError(invalidJson ? response.status : 0, invalidJson ? 'invalid_json' : 'network', error.message);
    }
}

export const get = (path, options) => request('GET', path, options);
export const post = (path, json, options) => request('POST', path, { ...options, json });
export const patch = (path, json, options) => request('PATCH', path, { ...options, json });
export const put = (path, json, options) => request('PUT', path, { ...options, json });
export const del = (path, options) => request('DELETE', path, options);

const blobUrls = new Map();

export function blobUrl(path) {
    if (!blobUrls.has(path)) {
        const result = fetchResponse('GET', path)
            .then(response => response.blob())
            .then(blob => URL.createObjectURL(blob))
            .catch(error => {
                blobUrls.delete(path);
                throw error;
            });
        blobUrls.set(path, result);
    }
    return blobUrls.get(path);
}

export async function downloadUrl(path) {
    const response = await fetchResponse('GET', path);
    const disposition = response.headers.get('Content-Disposition') || '';
    const extended = disposition.match(/filename\*\s*=\s*UTF-8'[^']*'([^;]+)/i);
    const plain = disposition.match(/filename\s*=\s*(?:"((?:\\.|[^"])*)"|([^;]*))/i);
    let filename = plain?.[1] !== undefined ? plain[1].replace(/\\(.)/g, '$1') : (plain?.[2] ?? '').trim();
    if (extended) {
        try { filename = decodeURIComponent(extended[1].trim()); } catch { /* Use the plain filename. */ }
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.append(link);
    try { link.click(); } finally {
        link.remove();
        // WebKit needs the URL to survive until the download starts.
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
}
