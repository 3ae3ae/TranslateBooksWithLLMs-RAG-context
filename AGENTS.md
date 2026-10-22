# AGENTS.md

Instructions for coding agents working in this repo. `CLAUDE.md` imports this file, so edit only this one.

## Python environment — uv only

Dependencies are declared in `pyproject.toml` and pinned in `uv.lock` (commit both). Run everything through uv: `uv run translation_api.py` (the app) and `uv run pytest`. Change dependencies with `uv add` / `uv remove` (`uv add --dev` for test-only), not pip and not a requirements file.

## Code language

Code, identifiers, comments, and docstrings are in English, matching the existing codebase.

## Secrets

- Never put an API key, token, password, or secret-bearing URL in a source file, test, script, comment, doc, or commit message, not even temporarily.
- The web app stores model API keys in `TranslateBook_Data/connections.json` (git-ignored, mode 0600) and never returns them from the API. If a value is missing, ask or fail with a clear message; never invent one.
- Real API keys may be set in your shell. Run tests and the app with a clean environment, `env -i PATH="$PATH" HOME="$HOME" uv run …`, so nothing reaches a paid service by accident, and never print environment variables.
- Docs and tests use inert placeholders such as `YOUR_API_KEY_HERE` or `sk-xxxxxxxx`.
- Before proposing a commit, check the diff for key-like literals (long base64/hex, `sk-`, `Bearer`, `ghp_`, `AKIA`, a non-empty `api_key`/`token`/`secret`) and alert the user if any appear.

## Web UI

The UI is a no-build Preact app served at `/`: modules in `src/web/static/app/`, shell in `src/web/templates/app.html`, and Preact, htm, and signals vendored in `src/web/static/vendor/` behind the import map in `app.html`. Do not add a bundler or npm dependencies. JS unit tests live in `tests/js/` and run with `node --test tests/js` (pytest runs them too).

## UI text and i18n

The UI switches between English and Korean at runtime without a reload. Strings live in flat key → string catalogs, `src/web/static/app/i18n/en.json` and `ko.json`; `t()` is in `src/web/static/app/lib/i18n.js`.

- Every user-visible string, including `title`, `placeholder`, `aria-label`, and toast text, goes through `t('area.key', params)`. No raw human-readable literals in components.
- Call `t()` during render. It reads the `locale` signal, so components re-render on a language switch. Never store a `t()` result in a module-level constant.
- Plurals use `_one` / `_other` keys and a numeric `count` param; pass the formatted number separately (e.g. `n`).
- A new key goes into both catalogs in the same change, English first, with the same `{{placeholder}}` tokens. `tests/test_app_i18n.py` checks key and placeholder parity and that every literal `t('…')` key exists.
- Korean copy is written for Korean readers, not translated word for word: polite 해요체, and no particle fallbacks like `이(가)` after a placeholder (put a noun after it instead).
- Server error messages are English. When the UI shows one to the user, map known error codes to translated text.
- Before calling a UI text change done, switch the language in the running app and confirm the text updates.

## Repo layout

The only entrypoint at the root is `translation_api.py`; there is no command-line tool. Tests live in `tests/` (pytest); reusable helpers go in `scripts/`. Tests must not write to the real `data/` or `TranslateBook_Data/` folders; `tests/conftest.py` redirects uploads and story notes to a temporary folder. Root-level `check_*.py`, `test_*.py`, `debug_*.py`, `scratch_*.py`, and `tmp_*.py` are gitignored scratch files and are never committed.
