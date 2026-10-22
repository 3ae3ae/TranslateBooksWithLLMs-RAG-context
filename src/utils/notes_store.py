"""Section-based story notes over the translation pipeline's canonical format."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading

from src import config
from src.utils import novel_context as context

_lock = threading.RLock()
SECTION_DEFINITIONS = [
    ("characters", "Characters & genders", "book", True, context.CHARACTERS_SECTION),
    ("aliases", "Character aliases", "book", True, context.ALIASES_SECTION),
    ("name_map", "Name translation map", "book", False, context.NAME_MAP_SECTION),
    ("glossary", "Glossary & terminology", "book", True, context.GLOSSARY_SECTION),
    ("addressing", "Current addressing forms", "story", True, context.ADDRESSING_SECTION),
    ("relationships", "Relationship evolution", "story", True, context.RELATIONSHIP_SECTION),
]


def _path(name):
    if not isinstance(name, str) or not context.is_safe_filename(name) or len(name.encode("utf-8")) > 240:
        raise ValueError("Invalid notes filename")
    directory = Path(config.NOVEL_CONTEXTS_DIR)
    path = directory / name
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("Notes must be inside the notes directory")
    return path


def parse_sections(text) -> list[dict]:
    sections = []
    for key, title, scope, editable, heading in SECTION_DEFINITIONS:
        source = context.extract_global_lore(text) if scope == "book" else (context.extract_dynamic_state_from_text(text) or "")
        match = re.search(r"^" + re.escape(heading) + r"\s*$\n?(.*?)(?=^## |^---DYNAMIC_STATE_|\Z)", source, re.M | re.S)
        sections.append(dict(key=key, title=title, scope=scope, editable=editable, body=match.group(1).strip() if match else ""))
    return sections


def serialize_sections(sections) -> str:
    if not isinstance(sections, list):
        raise ValueError("sections must be an array")
    bodies = {}
    keys = {definition[0] for definition in SECTION_DEFINITIONS}
    for section in sections:
        if not isinstance(section, dict) or section.get("key") not in keys or not isinstance(section.get("body"), str):
            raise ValueError("Each section needs a known key and a text body")
        if section["key"] in bodies:
            raise ValueError("Duplicate section key")
        body = section["body"].strip()
        if re.search(r"^\s*#|---DYNAMIC_STATE_", body, re.M):
            raise ValueError("Section bodies cannot contain headings or state markers")
        bodies[section["key"]] = body
    book, story = [], []
    for key, _title, scope, _editable, heading in SECTION_DEFINITIONS:
        (book if scope == "book" else story).append(heading + "\n" + bodies.get(key, ""))
    return "# GLOBAL LORE\n\n" + "\n\n".join(book) + "\n\n" + context.DYNAMIC_STATE_START + "\n# DYNAMIC RELATIONSHIP STATE\n" + "\n\n".join(story) + "\n" + context.DYNAMIC_STATE_END


def normalize_sections(sections) -> tuple[list[dict], list[str]]:
    original = serialize_sections(sections)
    normalized = parse_sections(context.normalize_novel_context_content(original))
    retained = Counter(line.strip() for section in normalized for line in section["body"].splitlines() if line.strip())
    removed = []
    for section in sections:
        for line in section["body"].splitlines():
            line = line.strip()
            if not line:
                continue
            if retained[line]:
                retained[line] -= 1
            else:
                removed.append(line)
    return normalized, removed


def notes_in_use(name) -> list[str]:
    _path(name)
    db_path = Path(config.DATA_DIR) / "jobs.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='translation_jobs'").fetchone():
            return []
        rows = db.execute("SELECT translation_id, config FROM translation_jobs WHERE status != 'completed'").fetchall()
    used = []
    for job_id, raw in rows:
        job_config = json.loads(raw)
        if job_config.get("notes_file") == name:
            used.append(job_id)
    return used


class NotesInUseError(ValueError):
    def __init__(self, jobs):
        self.jobs = jobs
        super().__init__("Notes are used by unfinished jobs")


def _assert_unused(name):
    jobs = notes_in_use(name)
    if jobs:
        raise NotesInUseError(jobs)


def list_notes():
    directory = Path(config.NOVEL_CONTEXTS_DIR)
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("*.txt")):
        try:
            path = _path(path.name)
        except ValueError:
            continue
        stat = path.stat()
        result.append(dict(name=path.name, updated_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(), size=stat.st_size, used_by=notes_in_use(path.name)))
    return result


def get_notes(name):
    path = _path(name)
    return {"name": name, "sections": parse_sections(context.normalize_novel_context_content(path.read_text(encoding="utf-8-sig")))}


def put_notes(name, sections, *, dry_run=False):
    with _lock:
        existing = get_notes(name)
        _assert_unused(name)
        serialize_sections(sections)
        current = {s["key"]: s for s in existing["sections"]}
        for section in sections:
            if not current[section["key"]]["editable"] and section["body"].strip() != current[section["key"]]["body"]:
                raise ValueError("Name translation map is generated and cannot be edited")
            current[section["key"]] = section
        normalized, removed = normalize_sections(list(current.values()))
        if not dry_run:
            context.save_novel_context(name, Path(config.NOVEL_CONTEXTS_DIR), serialize_sections(list(current.values())))
        return {"normalized_sections": normalized, "removed_lines": removed}


def create_notes(name, source=None):
    with _lock:
        path = _path(name)
        text = _path(source).read_text(encoding="utf-8-sig") if source else serialize_sections([])
        text = context.normalize_novel_context_content(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
        return get_notes(name)


def rename_notes(name, new_name):
    with _lock:
        path, destination = _path(name), _path(new_name)
        _assert_unused(name)
        if destination.exists():
            raise FileExistsError("Notes already exist")
        path.rename(destination)
        return get_notes(new_name)


def delete_notes(name):
    with _lock:
        _assert_unused(name)
        _path(name).unlink()


def prepare_job_notes(mode, *, source=None, name=None, job_title, carry_from=None) -> str | None:
    if mode == "off":
        return None
    if mode not in ("build", "copy"):
        raise ValueError("Invalid notes mode")
    if mode == "copy" and not (carry_from or source):
        raise ValueError("Copy mode requires source notes")
    with _lock:
        if name:
            if not isinstance(name, str) or "/" in name or "\\" in name:
                raise ValueError("Invalid notes name")
            stem = context.safe_context_filename_stem(name.removesuffix(".txt"))
            filename = stem + ".txt"
            _path(filename)
        else:
            stem = context.make_novel_context_filename(job_title)[:-12] + "_notes"
        number = 1
        while True:
            filename = f"{stem}{'_' + str(number) if number > 1 else ''}.txt"
            try:
                create_notes(filename, (carry_from or source) if mode == "copy" else None)
                return filename
            except FileExistsError:
                number += 1
