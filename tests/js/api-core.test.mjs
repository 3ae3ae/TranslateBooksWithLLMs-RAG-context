import assert from 'node:assert/strict';
import { test } from 'node:test';

globalThis.window = {
    location: new URL('http://localhost/'),
    __TBL_TOKEN__: 'YOUR_API_TOKEN_HERE',
};
const { ApiError, request, get, post, patch, put, del, blobUrl, downloadUrl }
    = await import('../../src/web/static/app/lib/api-core.js');

test('requests carry auth, query, JSON and the AbortSignal', async context => {
    const fetchMock = context.mock.method(globalThis, 'fetch', async () => Response.json({ ok: true }));
    const signal = new AbortController().signal;
    assert.deepEqual(await request('POST', '/api/jobs?existing=1', {
        json: { id: 7 }, query: { search: 'a b', page: 0, omitted: null }, signal,
    }), { ok: true });
    const [path, options] = fetchMock.mock.calls[0].arguments;
    assert.equal(path, '/api/jobs?existing=1&search=a+b&page=0');
    assert.equal(options.headers['X-API-Token'], 'YOUR_API_TOKEN_HERE');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.equal(options.body, '{"id":7}');
    assert.equal(options.signal, signal);
});

test('verb helpers, multipart bodies and 204', async context => {
    const fetchMock = context.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 204 }));
    assert.equal(await get('/api/jobs'), null);
    assert.equal(await post('/api/jobs', { id: 1 }), null);
    await patch('/api/jobs/1', { id: 1 });
    await put('/api/jobs/1', { id: 1 });
    await del('/api/jobs/1', { query: { delete_output: 0 } });
    const form = new FormData();
    form.append('name', 'book');
    await post('/api/upload', undefined, { form });
    assert.deepEqual(fetchMock.mock.calls.map(call => call.arguments[1].method),
        ['GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'POST']);
    const options = fetchMock.mock.calls.at(-1).arguments[1];
    assert.equal(options.body, form);
    assert.equal(options.headers['Content-Type'], undefined);
});

test('new and legacy error bodies normalize to ApiError', async context => {
    const cases = [
        [{ error: { code: 'invalid', message: 'Invalid value', details: { field: 'name' } } }, 'invalid', 'Invalid value', { field: 'name' }],
        [{ error: 'Legacy failure' }, 'http_error', 'Legacy failure', null],
        [{ message: 'Message failure', details: ['name'] }, 'http_error', 'Message failure', ['name']],
    ];
    for (const [body, code, message, details] of cases) {
        context.mock.method(globalThis, 'fetch', async () => Response.json(body, { status: 400 }));
        await assert.rejects(get('/api/jobs'), error => {
            assert.ok(error instanceof ApiError);
            assert.equal(error.status, 400);
            assert.equal(error.code, code);
            assert.equal(error.message, message);
            assert.deepEqual(error.details, details);
            return true;
        });
    }
});

test('non-JSON HTTP failures and network errors normalize', async context => {
    context.mock.method(globalThis, 'fetch', async () => new Response('<html>Failure</html>', {
        status: 502, statusText: 'Bad Gateway',
    }));
    await assert.rejects(get('/api/jobs'), { status: 502, code: 'http_error', message: 'Bad Gateway' });
    context.mock.method(globalThis, 'fetch', async () => { throw new TypeError('offline'); });
    await assert.rejects(get('/api/jobs'), { status: 0, code: 'network', message: 'offline' });
});

test('invalid JSON and interrupted response bodies also throw ApiError', async context => {
    context.mock.method(globalThis, 'fetch', async () => new Response('invalid JSON'));
    await assert.rejects(get('/api/jobs'), { name: 'ApiError', status: 200, code: 'invalid_json' });
    context.mock.method(globalThis, 'fetch', async () => new Response(new ReadableStream({
        start(controller) { controller.error(new TypeError('offline')); },
    })));
    await assert.rejects(get('/api/jobs'), { name: 'ApiError', status: 0, code: 'network', message: 'offline' });
});

test('cross-origin requests cannot receive the token and JSON cannot overwrite form data', async context => {
    const fetchMock = context.mock.method(globalThis, 'fetch', async () => Response.json({}));
    await assert.rejects(get('https://example.com/api/jobs'), TypeError);
    await assert.rejects(request('POST', '/api/jobs', { json: {}, form: new FormData() }), TypeError);
    assert.equal(fetchMock.mock.calls.length, 0);
});

test('cover URLs share a cached authenticated fetch, and failed loads can retry', async context => {
    const fetchMock = context.mock.method(globalThis, 'fetch', async () => new Response('cover'));
    context.mock.method(URL, 'createObjectURL', () => 'blob:cover');
    assert.deepEqual(await Promise.all([blobUrl('/api/jobs/1/cover'), blobUrl('/api/jobs/1/cover')]),
        ['blob:cover', 'blob:cover']);
    assert.equal(await blobUrl('/api/jobs/1/cover'), 'blob:cover');
    assert.equal(fetchMock.mock.calls.length, 1);
    assert.equal(fetchMock.mock.calls[0].arguments[1].headers['X-API-Token'], 'YOUR_API_TOKEN_HERE');
    context.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 404 }));
    await assert.rejects(blobUrl('/api/jobs/2/cover'), { status: 404 });
    context.mock.method(globalThis, 'fetch', async () => new Response('cover'));
    assert.equal(await blobUrl('/api/jobs/2/cover'), 'blob:cover');
});

test('downloads use server filenames, including UTF-8, and release their URL', async context => {
    const names = [];
    let removed = 0;
    globalThis.document = {
        body: { append: () => {} },
        createElement: () => ({ click() { names.push(this.download); }, remove() { removed++; } }),
    };
    context.mock.method(URL, 'createObjectURL', () => 'blob:download');
    const revoke = context.mock.method(URL, 'revokeObjectURL', () => {});
    context.mock.method(globalThis, 'setTimeout', callback => { callback(); return 0; });
    for (const disposition of [
        'attachment; filename="my book.epub"',
        "attachment; filename=book.epub; filename*=UTF-8''%EC%B1%85.epub",
        "attachment; filename=book.epub; filename*=UTF-8''%ZZ",
        'attachment; filename = "my \\"book\\".epub"',
        "attachment; filename* = UTF-8'ko'%EC%B1%85.epub",
    ]) {
        context.mock.method(globalThis, 'fetch', async () => new Response('book', {
            headers: { 'Content-Disposition': disposition },
        }));
        await downloadUrl('/api/download/book');
    }
    assert.deepEqual(names, ['my book.epub', '책.epub', 'book.epub', 'my "book".epub', '책.epub']);
    assert.equal(removed, 5);
    assert.equal(revoke.mock.calls.length, 5);
});
