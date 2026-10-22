import assert from 'node:assert/strict';
import { test } from 'node:test';
import { effect } from '../../src/web/static/vendor/signals-core.mjs';

globalThis.window = {
    location: new URL('http://localhost/'),
    __INITIAL_LOCALE__: 'ko',
};
const catalogs = {
    en: {
        greeting: 'Hello {{name}}: {{number}}',
        books_one: '{{count}} book', books_other: '{{count}} books',
        fallback: 'English fallback',
        fallback_books_one: '{{count}} English book', fallback_books_other: '{{count}} English books',
        empty: '',
    },
    ko: {
        greeting: '{{name}}: {{number}} 안녕하세요',
        books_other: '책 {{count}}권',
    },
};
const calls = [];
globalThis.fetch = async (path, options) => {
    calls.push({ path, options });
    if (options.method === 'POST') throw new TypeError('offline');
    const code = path.split('/').at(-1).split('.')[0];
    return Response.json(catalogs[code]);
};
const { locale, loadLocale, t } = await import('../../src/web/static/app/lib/i18n.js');

test('initial locale, catalog loading, interpolation and reactive switching', async () => {
    assert.equal(locale.value, 'ko');
    const rendered = [];
    const dispose = effect(() => rendered.push(t('greeting', { name: 'Ada', number: 1234 })));
    assert.equal(rendered.at(-1), 'greeting');
    await loadLocale('ko');
    assert.equal(rendered.at(-1), 'Ada: 1234 안녕하세요');
    assert.equal(t('greeting', { name: 'Ada' }), 'Ada: {{number}} 안녕하세요');
    await loadLocale('en');
    assert.equal(rendered.at(-1), 'Hello Ada: 1234');
    dispose();
    const persistence = calls.filter(call => call.path === '/api/ui-locale');
    assert.deepEqual(persistence.map(call => JSON.parse(call.options.body)), [{ locale: 'ko' }, { locale: 'en' }]);
});

test('plural rules and current locale → English → key fallback', async () => {
    await loadLocale('en');
    assert.equal(t('books', { count: 1 }), '1 book');
    assert.equal(t('books', { count: 0 }), '0 books');
    assert.equal(t('books', { count: 2 }), '2 books');
    assert.equal(t('empty'), '');
    await loadLocale('ko');
    assert.equal(t('books', { count: 1 }), '책 1권');
    assert.equal(t('books', { count: 2 }), '책 2권');
    assert.equal(t('fallback'), 'English fallback');
    assert.equal(t('fallback_books', { count: 1 }), '1 English book');
    assert.equal(t('missing'), 'missing');
    assert.equal(t('constructor'), 'constructor');
    assert.equal(t('toString'), 'toString');
});

test('catalogs are cached, unsupported locales rejected, latest selection wins', async () => {
    await loadLocale('en');
    await loadLocale('ko');
    for (const code of ['en', 'ko']) {
        assert.equal(calls.filter(call => call.path === `/static/app/i18n/${code}.json`).length, 1);
    }
    await assert.rejects(loadLocale('fr'), RangeError);
    await Promise.all([loadLocale('ko'), loadLocale('en')]);
    assert.equal(locale.value, 'en');
});

test('loading the initial English catalog also re-renders without a locale change', async () => {
    window.__INITIAL_LOCALE__ = 'en';
    const fresh = await import('../../src/web/static/app/lib/i18n.js?initial-en');
    const rendered = [];
    const dispose = effect(() => rendered.push(fresh.t('fallback')));
    await fresh.loadLocale('en');
    assert.deepEqual(rendered, ['fallback', 'English fallback']);
    dispose();
});

test('failed catalog loads can be retried and invalid initial locale uses English', async context => {
    window.__INITIAL_LOCALE__ = 'fr';
    const fresh = await import('../../src/web/static/app/lib/i18n.js?retry');
    assert.equal(fresh.locale.value, 'en');
    let failed = false;
    context.mock.method(globalThis, 'fetch', async () => {
        if (!failed) {
            failed = true;
            throw new TypeError('offline');
        }
        return Response.json(catalogs.en);
    });
    await assert.rejects(fresh.loadLocale('en'), { code: 'network' });
    await fresh.loadLocale('en');
    assert.equal(fresh.t('fallback'), 'English fallback');
});
