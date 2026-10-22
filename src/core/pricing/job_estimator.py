"""Job estimates use real passage boundaries and historical request duration."""
import json
import math
from pathlib import Path
import posixpath
import sqlite3
from urllib.parse import unquote
import zipfile

from src import config
from src.api.services.path_validator import PathValidator
from src.core.chunking.token_chunker import TokenChunker
from src.core.pricing.estimator import SYSTEM_PROMPT_TOKENS, USER_TEMPLATE_TOKENS, get_output_ratio
from src.core.pricing.pricing_data import get_default_pricing
from src.utils.preferences import get_preferences


def load_job_units(path, file_type, *, passage_tokens, srt_lines_per_block, chapter_mode, simplify_formatting):
    from src.api.blueprints.sample_routes import _load_source_units
    from src.core.common.plain_text_pipeline import build_plain_segments

    if file_type not in ("epub", "docx"):
        return _load_source_units(str(path), file_type, passage_tokens=passage_tokens, srt_lines_per_block=srt_lines_per_block, chapter_mode=chapter_mode)
    units = []
    if file_type == "docx":
        from src.core.docx.docx_translation_adapter import DocxTranslationAdapter
        from src.core.docx.plain_extractor import extract_plain_paragraphs
        if simplify_formatting:
            content = extract_plain_paragraphs(str(path))
            units = build_plain_segments(content.paragraphs_text, passage_tokens, paragraph_kinds=content.paragraphs_style, chapter_mode=chapter_mode)
        else:
            adapter = DocxTranslationAdapter()
            html, context = adapter.extract_content(str(path), None)
            text, tags, _ = adapter.preserve_structure(html, context, None)
            units = adapter.create_chunks(text, tags, passage_tokens, None, chapter_mode=chapter_mode)
    else:
        from lxml import etree
        from src.core.epub.epub_translation_adapter import EpubTranslationAdapter
        from src.core.epub.plain_extractor import extract_plain_paragraphs
        from src.core.epub.translator import _get_content_files_from_spine
        with zipfile.ZipFile(path) as archive:
            parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
            container = etree.fromstring(archive.read("META-INF/container.xml"), parser)
            rootfile = container.find(".//{*}rootfile") if container is not None else None
            if rootfile is None or not rootfile.get("full-path"):
                raise ValueError("EPUB rootfile missing")
            opf_path = rootfile.get("full-path")
            opf = etree.fromstring(archive.read(opf_path), parser)
            if opf is None:
                raise ValueError("EPUB manifest missing")
            manifest, spine = opf.find("{*}manifest"), opf.find("{*}spine")
            if manifest is None or spine is None:
                raise ValueError("EPUB manifest or spine missing")
            for href in _get_content_files_from_spine(spine, manifest):
                member = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), unquote(href)))
                root = etree.fromstring(archive.read(member), parser)
                if root is None:
                    continue
                if simplify_formatting:
                    body = root.find(".//{*}body")
                    if body is None:
                        continue
                    paragraphs, kinds, _ = extract_plain_paragraphs(body)
                    units.extend(build_plain_segments(paragraphs, passage_tokens, paragraph_kinds=kinds, chapter_mode=chapter_mode))
                else:
                    adapter = EpubTranslationAdapter()
                    html, context = adapter.extract_content(root, None)
                    if not html.strip():
                        continue
                    text, tags, _ = adapter.preserve_structure(html, context, None)
                    units.extend(adapter.create_chunks(text, tags, passage_tokens, None, chapter_mode=chapter_mode))
    return [{"main_content": unit["text"]} for unit in units]


def resolve_pricing(connection, overrides):
    from src.core.llm.connections import list_models
    try:
        models = list_models(connection["connection_id"])
    except Exception:
        models = []
    pricing = next((m.get("pricing") for m in models if m["id"] == connection["model"]), None)
    if pricing is not None:
        return pricing, "models"
    pricing = overrides.get(connection["connection_id"] + ":" + connection["model"])
    if pricing is not None:
        return pricing, "override"
    pricing = get_default_pricing(connection["llm_provider"], connection["model"])
    return ({"input_per_m": pricing["input"], "output_per_m": pricing["output"]}, "table") if pricing else (None, "unknown")


def seconds_per_request(connection_id, model):
    db_path = Path(config.DATA_DIR) / "jobs.db"
    if not db_path.exists():
        return None
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='translation_jobs' AND type='table'").fetchone():
            return None
        rows = db.execute("SELECT config FROM translation_jobs WHERE status='completed'").fetchall()
    requests, elapsed = 0, 0
    for (raw,) in rows:
        job = json.loads(raw)
        if job.get("connection_id") != connection_id or job.get("model") != model:
            continue
        stats = job.get("stats") or {}
        count, seconds = stats.get("requests"), stats.get("elapsed_seconds")
        if type(count) in (int, float) and type(seconds) in (int, float) and math.isfinite(count) and math.isfinite(seconds) and count > 0 and seconds > 0:
            requests += count
            elapsed += seconds
    return elapsed / requests if requests else None


def estimate_job(data, uploads_dir):
    from src.core.llm.connections import resolve_for_pipeline
    from src.utils.custom_instructions import get_style
    from src.utils.notes_store import get_notes, serialize_sections
    from src.utils.file_detector import detect_file_type

    if not isinstance(data, dict):
        raise ValueError("Expected job object")
    defaults = get_preferences()
    files = data.get("files")
    if not isinstance(files, list) or not files or any(not isinstance(file, dict) for file in files):
        raise ValueError("files must be a non-empty array of file objects")
    task = data.get("task", defaults["task"])
    if task not in ("translate", "polish"):
        raise ValueError("task must be translate or polish")
    connection = resolve_for_pipeline(data.get("connection_id") or defaults["default_connection_id"], data.get("model") or defaults["default_model"], data.get("reasoning", defaults["default_reasoning"]))
    billing = "plan" if connection["connection_type"] == "ollama_cloud" else "local" if connection["local"] else "api"
    pricing, source = resolve_pricing(connection, defaults["price_overrides"]) if billing == "api" else (None, billing)
    passage_tokens = data.get("passage_tokens", defaults["passage_tokens"])
    srt_lines = data.get("srt_lines_per_block", defaults["srt_lines_per_block"])
    if type(passage_tokens) is not int or not 50 <= passage_tokens <= 1000000 or type(srt_lines) is not int or not 1 <= srt_lines <= 10000:
        raise ValueError("Invalid passage size")
    notes = data.get("notes") or {}
    if not isinstance(notes, dict):
        raise ValueError("notes must be an object")
    mode = notes.get("mode", ("copy" if notes.get("source") else "off") if task == "polish" else defaults["notes_mode"])
    if mode not in ("off", "build", "copy"):
        raise ValueError("Invalid notes mode")
    if task == "translate" and mode == "off":
        raise ValueError("Translation requires notes.mode to be build or copy")
    if task == "polish" and mode == "build":
        raise ValueError("Polish supports existing read-only notes or notes off")
    consolidation = notes.get("consolidation_interval", defaults["notes_consolidation_interval"])
    budget = notes.get("prompt_max_tokens", defaults["notes_prompt_max_tokens"])
    memory = notes.get("source_memory_chars", defaults["notes_source_memory_chars"])
    for name, value, minimum in [("consolidation_interval", consolidation, 0), ("prompt_max_tokens", budget, 0), ("source_memory_chars", memory, 0)]:
        if type(value) is not int or not minimum <= value <= 1000000:
            raise ValueError("Invalid notes " + name)
    chunker = TokenChunker(max_tokens=passage_tokens)
    style = data.get("style", defaults["style"])
    style_content = get_style(style) if style else {}
    notes_tokens = 0
    if notes.get("source"):
        notes_tokens = chunker.count_tokens(serialize_sections(get_notes(notes["source"])["sections"]))
    per_file = []
    total_output_min = total_output_max = 0
    for file in files:
        raw_path = file.get("file_path")
        if not isinstance(raw_path, str):
            raise ValueError("file_path must be text")
        path, error = PathValidator.validate_upload_path(raw_path, uploads_dir)
        if error:
            raise ValueError(error)
        ft = detect_file_type(str(path))
        units = load_job_units(path, ft, passage_tokens=passage_tokens, srt_lines_per_block=srt_lines, chapter_mode=data.get("chapter_mode", defaults["chapter_mode"]), simplify_formatting=data.get("simplify_formatting", defaults["simplify_formatting"]))
        passages = len(units)
        if not passages:
            raise ValueError("File has no passages")
        main_tokens = sum(chunker.count_tokens(unit["main_content"]) for unit in units)
        context_tokens = sum(chunker.count_tokens(unit.get("context_before", "") + unit.get("context_after", "")) for unit in units)
        passes = 1 + int(task == "translate" and bool(data.get("polish_after", defaults["polish_after"])))
        update_indices = range(1, passages + 1) if task == "translate" else ()
        updates = len(update_indices)
        consolidations = sum(index % consolidation == 0 or index == passages for index in update_indices) if consolidation else 0
        requests = passages * passes + updates + consolidations
        note_prompt = min(notes_tokens or budget, budget) if budget else notes_tokens
        if mode == "off":
            note_prompt = 0
        instructions = chunker.count_tokens(style_content.get("translation" if task == "translate" else "refinement") or "")
        overhead = SYSTEM_PROMPT_TOKENS + USER_TEMPLATE_TOKENS + note_prompt + instructions
        ratio_min, ratio_max = (0.95, 1.1) if task == "polish" else get_output_ratio(file.get("source_language", data.get("source_language", defaults["source_language"])), data.get("target_language", defaults["target_language"]))
        input_tokens = main_tokens + context_tokens + passages * overhead
        if passes == 2:
            draft_tokens = math.ceil(main_tokens * (ratio_min + ratio_max) / 2)
            polish_instructions = chunker.count_tokens(style_content.get('refinement') or '')
            input_tokens += draft_tokens + passages * (SYSTEM_PROMPT_TOKENS + USER_TEMPLATE_TOKENS + note_prompt + polish_instructions)
        input_tokens += updates * (overhead + math.ceil(main_tokens / passages) + math.ceil(memory / 4)) + consolidations * (SYSTEM_PROMPT_TOKENS + note_prompt)
        output_min = int(main_tokens * ratio_min * passes) + (updates + consolidations) * note_prompt
        output_max = int(main_tokens * ratio_max * passes) + (updates + consolidations) * max(note_prompt, budget)
        total_output_min += output_min
        total_output_max += output_max
        per_file.append(dict(file_path=file["file_path"], input_filename=file.get("input_filename", path.name), passages=passages, requests=requests, notes_updates=updates, consolidation_calls=consolidations, input_tokens=input_tokens, output_tokens=(output_min + output_max) // 2))
    passages = sum(f["passages"] for f in per_file)
    requests = sum(f["requests"] for f in per_file)
    input_tokens = sum(f["input_tokens"] for f in per_file)
    if billing != "api":
        cost_min = cost_max = 0.0
    elif pricing is None:
        cost_min = cost_max = None
    else:
        cost_min = round((input_tokens * pricing["input_per_m"] + total_output_min * pricing["output_per_m"]) / 1000000, 6)
        cost_max = round((input_tokens * pricing["input_per_m"] + total_output_max * pricing["output_per_m"]) / 1000000, 6)
    duration = seconds_per_request(connection["connection_id"], connection["model"])
    return dict(passages=passages, requests=requests, input_tokens=input_tokens, output_tokens=(total_output_min + total_output_max) // 2, cost_min_usd=cost_min, cost_max_usd=cost_max, price_source=source, billing=billing, time_min_s=round(duration * requests * 0.8) if duration else None, time_max_s=round(duration * requests * 1.2) if duration else None, time_source="history" if duration else "unknown", per_file=per_file)
