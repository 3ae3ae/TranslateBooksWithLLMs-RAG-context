# AGENTS.md

Instructions for coding agents working in this repo. `CLAUDE.md` imports this file, so edit only this one.

## Python environment — uv only

Dependencies are declared in `pyproject.toml` and pinned in `uv.lock` (commit both). Run everything through uv: `uv run translation_api.py` (web UI), `uv run translate.py ...` (CLI), `uv run pytest`. Change dependencies with `uv add` / `uv remove` (`uv add --dev` for test-only), not pip and not a requirements file.

## Code language

Code, identifiers, comments, and docstrings are in English, matching the existing codebase.

## Secrets

- Never put an API key, token, password, or secret-bearing URL in a source file, test, script, comment, doc, or commit message, not even temporarily.
- Load credentials from `.env` (gitignored) through the existing config code. If a value is missing, ask or fail with a clear message; never invent one.
- Docs and tests use inert placeholders such as `YOUR_API_KEY_HERE` or `sk-xxxxxxxx`.
- Before proposing a commit, check the diff for key-like literals (long base64/hex, `sk-`, `Bearer`, `ghp_`, `AKIA`, a non-empty `api_key`/`token`/`secret`) and alert the user if any appear.

## Frontend i18n

The web UI switches language at runtime. Strings live in `src/web/static/locales/<lang>/<namespace>.json` for `en`, `fr`, `es`, `de`, `zh-CN`, `ja`, `ko`; the machinery is in `src/web/static/js/i18n/i18n.js`.

- Static HTML: mark text with `data-i18n="ns:key"`, `data-i18n-html`, `data-i18n-attr="placeholder:ns:key;title:ns:key"`, and `data-i18n-params`. `applyToDOM` re-applies these on every language change.
- JS-rendered text: use `t('ns:key', params)` inside a render that re-runs on the `localeChanged` window event, or emit elements carrying `data-i18n*` attributes. Never cache a `t()` result at module load.
- No raw human-readable literals in `textContent`, `innerHTML`, `title`, `placeholder`, `aria-label`, `alt`, `alert()`/`confirm()`, toasts, or `MessageLogger`.
- A new key goes into all 7 locale files in the same change, English first, with the same `{{placeholder}}` tokens in every locale.
- Before calling an i18n change done, switch the UI language and confirm the text updates without a reload.

## Repo layout

Entrypoints at the root are `translate.py` and `translation_api.py` only. Tests live in `tests/` (pytest) and `tests/standalone/` (manual scripts); reusable helpers go in `scripts/`. Root-level `check_*.py`, `test_*.py`, `debug_*.py`, `scratch_*.py`, and `tmp_*.py` are gitignored scratch files and are never committed.
