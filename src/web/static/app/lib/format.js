import { locale } from './i18n.js';

export const formatNumber = (value, options = {}) =>
    new Intl.NumberFormat(locale.value, options).format(value);

export const formatPercent = (value, options = {}) =>
    formatNumber(value, { style: 'percent', maximumFractionDigits: 1, ...options });

export function formatBytes(bytes) {
    const units = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte', 'petabyte'];
    const index = Math.min(units.length - 1, Math.max(0, Math.floor(Math.log2(Math.abs(bytes)) / 10) || 0));
    return formatNumber(bytes / 1024 ** index, {
        style: 'unit', unit: units[index], unitDisplay: 'short', maximumFractionDigits: index ? 1 : 0,
    });
}

export function formatDuration(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor(total / 60) % 60;
    const korean = locale.value === 'ko';
    const unit = (value, en, ko) => `${formatNumber(value)}${korean ? ko : ` ${en}`}`;
    if (hours) return [unit(hours, 'h', '시간'), minutes ? unit(minutes, 'min', '분') : ''].filter(Boolean).join(' ');
    if (minutes) return unit(minutes, 'min', '분');
    return unit(total, 's', '초');
}

export function formatRelativeTime(dateOrIso) {
    const seconds = (new Date(dateOrIso).getTime() - Date.now()) / 1000;
    const units = [['year', 31536000], ['month', 2592000], ['week', 604800],
        ['day', 86400], ['hour', 3600], ['minute', 60], ['second', 1]];
    const [unit, size] = units.find(([, size]) => Math.abs(seconds) >= size) || units.at(-1);
    return new Intl.RelativeTimeFormat(locale.value, { numeric: 'auto' }).format(Math.round(seconds / size), unit);
}

export const formatDate = (dateOrIso, options = {}) =>
    new Intl.DateTimeFormat(locale.value, options).format(new Date(dateOrIso));

export function formatCost(usd) {
    const digits = usd > 0 && usd < 0.01 ? 4 : 2;
    const options = { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol',
        minimumFractionDigits: digits, maximumFractionDigits: digits };
    if (usd > 0 && usd < 0.0001) {
        return `<${formatNumber(0.01, { ...options, minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return formatNumber(usd, options);
}
