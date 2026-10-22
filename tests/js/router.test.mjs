import assert from 'node:assert/strict';
import { test } from 'node:test';

globalThis.window = new EventTarget();
window.location = { hash: '' };
let replaced;
window.history = { replaceState: (_state, _title, hash) => {
    replaced = hash;
    window.location.hash = hash;
} };
const { route, navigate, defineRoutes } = await import('../../src/web/static/app/lib/router.js');

test('default and all design routes match', () => {
    defineRoutes([
        { name: 'translations', pattern: '/translations' }, { name: 'new', pattern: '/new' },
        { name: 'job', pattern: '/job/:id' }, { name: 'job_tab', pattern: '/job/:id/:tab' },
        { name: 'compare', pattern: '/compare' }, { name: 'notes', pattern: '/notes' },
        { name: 'note', pattern: '/notes/:name' }, { name: 'styles', pattern: '/styles' },
        { name: 'style', pattern: '/styles/:name' }, { name: 'settings', pattern: '/settings/:section' },
    ]);
    navigate('');
    assert.equal(route.value.name, 'translations');
    const examples = [
        ['/translations', 'translations'], ['/new', 'new'], ['/job/42', 'job'], ['/job/42/log', 'job_tab'],
        ['/compare', 'compare'], ['/notes', 'notes'],
        ['/notes/book', 'note'], ['/styles', 'styles'], ['/styles/book', 'style'],
        ['/settings/appearance', 'settings'], ['/settings', 'settings'],
    ];
    for (const [path, name] of examples) {
        navigate(path);
        assert.equal(route.value.name, name, path);
    }
});

test('parameters and queries decode without treating encoded slashes as segments', () => {
    navigate('/notes/My%20book%2F%ED%95%9C%EA%B8%80?tab=story+notes&filter=a%3Fb');
    assert.deepEqual(route.value, {
        name: 'note', params: { name: 'My book/한글' },
        path: '/notes/My%20book%2F%ED%95%9C%EA%B8%80', query: { tab: 'story notes', filter: 'a?b' },
    });
});

test('unknown routes, missing parameters and malformed escapes are not_found', () => {
    for (const path of ['/missing', '/job', '/job/', '/job/42/log/extra', '/notes/%ZZ']) {
        navigate(path);
        assert.equal(route.value.name, 'not_found', path);
        assert.deepEqual(route.value.params, {});
    }
});

test('replace navigation and browser hashchange both update the signal', () => {
    navigate('#/job/123', { replace: true });
    assert.equal(replaced, '#/job/123');
    assert.equal(route.value.params.id, '123');
    window.location.hash = '#/translations/?q=book';
    window.dispatchEvent(new Event('hashchange'));
    assert.equal(route.value.name, 'translations');
    assert.deepEqual(route.value.query, { q: 'book' });
});

test('defineRoutes replaces route definitions and matches literal punctuation', () => {
    defineRoutes([{ name: 'custom', pattern: '/custom.v1/:id' }]);
    navigate('/custom.v1/abc');
    assert.equal(route.value.name, 'custom');
    assert.deepEqual(route.value.params, { id: 'abc' });
    navigate('/customXv1/abc');
    assert.equal(route.value.name, 'not_found');
    navigate('/translations');
    assert.equal(route.value.name, 'not_found');
});
