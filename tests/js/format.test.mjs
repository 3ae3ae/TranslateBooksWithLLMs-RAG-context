import assert from 'node:assert/strict';
import { test } from 'node:test';

globalThis.window = { location: new URL('http://localhost/') };
const { locale } = await import('../../src/web/static/app/lib/i18n.js');
const { formatNumber, formatPercent, formatBytes, formatDuration, formatRelativeTime, formatDate, formatCost }
    = await import('../../src/web/static/app/lib/format.js');

test('English number, percent, byte and duration outputs', () => {
    locale.value = 'en';
    assert.equal(formatNumber(1234.5), '1,234.5');
    assert.equal(formatPercent(0.125), '12.5%');
    assert.equal(formatBytes(0), '0 B');
    assert.equal(formatBytes(1536), '1.5 KB');
    assert.equal(formatDuration(38.9), '38 s');
    assert.equal(formatDuration(2520), '42 min');
    assert.equal(formatDuration(3900), '1 h 5 min');
    assert.equal(formatDuration(3600), '1 h');
    assert.equal(formatDuration(-1), '0 s');
});

test('Korean formatting reads locale on each call', () => {
    locale.value = 'ko';
    assert.equal(formatNumber(1234.5), '1,234.5');
    assert.equal(formatPercent(0.125), '12.5%');
    assert.equal(formatBytes(568), '568 B');
    assert.equal(formatDuration(38), '38초');
    assert.equal(formatDuration(2520), '42분');
    assert.equal(formatDuration(3900), '1시간 5분');
});

test('relative dates, future dates and calendar dates in both locales', context => {
    const now = Date.UTC(2026, 9, 22, 12);
    context.mock.method(Date, 'now', () => now);
    const yesterday = new Date(now - 86400000);
    locale.value = 'en';
    assert.equal(formatRelativeTime(yesterday), 'yesterday');
    assert.equal(formatRelativeTime(new Date(now + 120000).toISOString()), 'in 2 minutes');
    assert.equal(formatDate(yesterday, { timeZone: 'UTC' }), '10/21/2026');
    locale.value = 'ko';
    assert.equal(formatRelativeTime(yesterday), '어제');
    assert.equal(formatRelativeTime(new Date(now + 120000)), '2분 후');
    assert.equal(formatDate(yesterday, { timeZone: 'UTC' }), '2026. 10. 21.');
});

test('USD costs preserve small amounts and flag amounts below four-decimal precision', () => {
    for (const code of ['en', 'ko']) {
        locale.value = code;
        assert.equal(formatCost(0), '$0.00');
        assert.equal(formatCost(0.0042), '$0.0042');
        assert.equal(formatCost(1.2), '$1.20');
        assert.equal(formatCost(0.00001), '<$0.01');
        assert.equal(formatCost(0.0001), '$0.0001');
    }
});
