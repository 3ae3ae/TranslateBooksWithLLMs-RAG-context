// Languages offered as suggestions. `value` is what the model sees in prompts
// (English names, as the backend expects); `code` selects the UI label.
export const LANGUAGES = [
  { code: 'en', value: 'English' },
  { code: 'ko', value: 'Korean' },
  { code: 'ja', value: 'Japanese' },
  { code: 'zh', value: 'Chinese' },
  { code: 'zh_hant', value: 'Traditional Chinese' },
  { code: 'es', value: 'Spanish' },
  { code: 'fr', value: 'French' },
  { code: 'de', value: 'German' },
  { code: 'it', value: 'Italian' },
  { code: 'pt', value: 'Portuguese' },
  { code: 'ru', value: 'Russian' },
  { code: 'uk', value: 'Ukrainian' },
  { code: 'pl', value: 'Polish' },
  { code: 'nl', value: 'Dutch' },
  { code: 'tr', value: 'Turkish' },
  { code: 'vi', value: 'Vietnamese' },
  { code: 'th', value: 'Thai' },
  { code: 'id', value: 'Indonesian' },
  { code: 'ar', value: 'Arabic' },
  { code: 'hi', value: 'Hindi' },
];

const byValue = new Map(LANGUAGES.map((l) => [l.value.toLowerCase(), l]));
export const findLanguage = (name) => (name ? byValue.get(String(name).toLowerCase()) || null : null);
