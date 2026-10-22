import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "src/web/static/app"
PLACEHOLDER = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")
TRANSLATION_CALL = re.compile(r"(?<![\w$.])t\s*\(\s*(['\"])([^'\"\n\\]+)\1")


def load_catalog(code):
    catalog = json.loads((APP / "i18n" / f"{code}.json").read_text(encoding="utf-8"))
    assert isinstance(catalog, dict)
    assert all(isinstance(value, str) for value in catalog.values()), "Catalogs must be flat key → string maps"
    return catalog


def test_app_locale_key_and_placeholder_parity():
    en, ko = load_catalog("en"), load_catalog("ko")
    assert en.keys() == ko.keys(), f"Locale key mismatch: {en.keys() ^ ko.keys()}"
    for key in en:
        assert set(PLACEHOLDER.findall(en[key])) == set(PLACEHOLDER.findall(ko[key])), key


def test_app_literal_translation_keys_exist():
    en = load_catalog("en")
    missing = []
    for path in sorted(APP.rglob("*.js")):
        for match in TRANSLATION_CALL.finditer(path.read_text(encoding="utf-8")):
            key = match.group(2)
            if key not in en and f"{key}_other" not in en:
                missing.append(f"{path.relative_to(APP)}: {key}")
    assert not missing, "Missing English translation keys:\n" + "\n".join(missing)
