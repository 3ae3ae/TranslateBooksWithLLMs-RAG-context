"""
Translation job management routes
"""
import os
import time
import copy
import threading
from pathlib import Path
from flask import Blueprint, request, jsonify

import src.config as _config
from src.api.websocket import emit_update
from src.api.api_keys import resolve_api_key as _resolve_api_key
from src.utils.unified_logger import get_logger

logger = get_logger(__name__)


# Cloud providers whose key lives in config['<provider>_api_key'] and env var
# '<PROVIDER>_API_KEY'. The mapping is mechanical, so supporting a new provider
# in the resume-override path requires only adding it here (and nowhere else in
# this file).
_KEY_PROVIDERS = ('gemini', 'openai', 'openrouter', 'mistral', 'deepseek', 'poe', 'nim')

# Providers that talk to a user-supplied endpoint; the others use a built-in one.
_ENDPOINT_PROVIDERS = ('ollama', 'openai')

_CONTEXT_RESYNC_LOCK = threading.Lock()
_ACTIVE_CONTEXT_RESYNCS = set()


def _claim_context_resync(translation_id):
    with _CONTEXT_RESYNC_LOCK:
        if translation_id in _ACTIVE_CONTEXT_RESYNCS:
            return False
        _ACTIVE_CONTEXT_RESYNCS.add(translation_id)
        return True


def _release_context_resync(translation_id):
    with _CONTEXT_RESYNC_LOCK:
        _ACTIVE_CONTEXT_RESYNCS.discard(translation_id)


def _is_context_resync_active(translation_id):
    with _CONTEXT_RESYNC_LOCK:
        return translation_id in _ACTIVE_CONTEXT_RESYNCS


def _context_resync_state_from_config(config):
    state = (config or {}).get('_context_resync')
    return dict(state) if isinstance(state, dict) else {}


def _update_context_resync_state(
    checkpoint_manager,
    translation_id,
    updates,
    *,
    base_config=None,
):
    job = checkpoint_manager.get_job(translation_id)
    if not job:
        return None
    config = copy.deepcopy(base_config if base_config is not None else job.get('config') or {})
    state = _context_resync_state_from_config(config)
    state.update(updates)
    config['_context_resync'] = state
    if not checkpoint_manager.update_job_config(translation_id, config):
        return None
    return state


def _provider_credentials_error(config):
    """Return a credential error payload, or None when the config can run."""
    if config.get('connection_id'):
        return None
    provider = (config.get('llm_provider') or 'ollama').lower()

    if provider in _KEY_PROVIDERS:
        env_var = f"{provider.upper()}_API_KEY"
        # 'openai' also covers OpenAI-compatible local endpoints (llama.cpp,
        # LM Studio, vLLM) where a key is legitimately absent — only require
        # one for the official API, mirroring the factory's heuristic.
        key_required = (provider != 'openai'
                        or 'api.openai.com' in (config.get('llm_api_endpoint') or ''))
        if key_required and not (config.get(f"{provider}_api_key") or os.getenv(env_var)):
            return {
                "error": "Missing API key for provider",
                "message": (f"Resuming with '{provider}' requires an API key. "
                            f"Set {env_var} in .env or include it in the request."),
            }

    if provider in _ENDPOINT_PROVIDERS and not config.get('llm_api_endpoint'):
        return {
            "error": "Missing API endpoint for provider",
            "message": f"Resuming with '{provider}' requires an API endpoint.",
        }

    return None


def _validate_provider_credentials(config):
    """Return a Flask error response when a resume config cannot run."""
    error = _provider_credentials_error(config)
    if error is not None:
        return jsonify(error), 400
    return None


def _rehydrate_resume_credentials(config, overrides=None):
    """Restore non-persisted provider credentials into a resume config.

    Checkpoints deliberately exclude secrets. Every path that reconstructs a
    job from a checkpoint, including background context re-sync, must call this
    helper before starting a worker.
    """
    if config.get('connection_id'):
        return
    provider = (config.get('llm_provider') or 'ollama').lower()
    raw_key = overrides.get('api_key') if isinstance(overrides, dict) else None

    for key_provider in _KEY_PROVIDERS:
        env_var = f"{key_provider.upper()}_API_KEY"
        key_override = (
            raw_key
            if key_provider == provider and raw_key not in (None, '')
            else None
        )
        resolved = _resolve_api_key(
            key_override,
            env_var,
            getattr(_config, env_var, ''),
        )
        if resolved or f"{key_provider}_api_key" in config:
            config[f"{key_provider}_api_key"] = resolved


def _apply_resume_overrides(config, overrides):
    """Merge optional model/provider override fields into a resume config in place.

    Lets the resume request switch model/provider for the remaining chunks
    (issue #183). An empty/absent body leaves `config` untouched. API keys flow
    through `_resolve_api_key` exactly like the start endpoint, and a multi-key
    string is passed through unchanged so the key-rotation pool still works.

    Credentials are validated even with an empty body: checkpoints no longer
    persist API keys (issue #213), so every resume must find its key in .env
    or in the request.

    Returns a Flask (response, status) tuple to abort with on validation failure,
    or None on success.
    """
    if isinstance(overrides, dict) and overrides:
        if not config.get('connection_id') and any(overrides.get(key) for key in ('model', 'llm_provider', 'llm_api_endpoint')):
            config.pop('connection', None)
        if overrides.get('model'):
            config['model'] = overrides['model']
        if overrides.get('llm_provider'):
            config['llm_provider'] = str(overrides['llm_provider']).lower()
        if overrides.get('llm_api_endpoint'):
            config['llm_api_endpoint'] = overrides['llm_api_endpoint']
        if overrides.get('context_window') is not None:
            try:
                config['context_window'] = int(overrides['context_window'])
            except (TypeError, ValueError):
                return jsonify({"error": "context_window must be an integer"}), 400

    _rehydrate_resume_credentials(config, overrides)

    return _validate_provider_credentials(config)


def _available_context_chunk_indices(checkpoint_data):
    """Return canonical checkpoint indices that contain editable snapshots."""
    indices = []
    for chunk in (checkpoint_data or {}).get('chunks', []):
        chunk_data = chunk.get('chunk_data') or {}
        index = chunk.get('chunk_index')
        if (
            isinstance(index, int)
            and chunk.get('status') in ('completed', 'partial', 'failed')
            and chunk_data.get('context_snapshot')
        ):
            indices.append(index)
    return sorted(set(indices))


def _build_corrective_refinement_config(config, output_filepath=None):
    """Build a one-pass refinement replay after context re-sync.

    The replay always starts from the preserved first-pass translation, never
    from the already-refined output. Returning ``None`` means the checkpoint is
    legacy or incomplete and cannot safely replay refinement automatically.
    """
    if not (config.get("refine_after") or config.get("_resync_polish")):
        return None

    source_path = config.get("refinement_source_path")
    final_output_path = output_filepath or config.get("output_filepath")
    if not source_path or not final_output_path:
        return None
    if not Path(source_path).is_file() or not Path(final_output_path).is_file():
        return None

    correction = copy.deepcopy(config)
    correction.update({
        "_resync_original_refine_only": config.get('refine_only', False),
        "_resync_original_refine_after": config.get('refine_after', False),
        "_resync_original_file_path": config.get('file_path'),
        "_resync_original_preserved_input_path": config.get('preserved_input_path'),
        "file_path": str(Path(source_path).resolve()),
        "preserved_input_path": str(Path(source_path).resolve()),
        "output_filepath": str(Path(final_output_path).resolve()),
        "output_filename": Path(final_output_path).name,
        "resume_from_index": 0,
        "is_resume": True,
        "refine_only": True,
        "refine_after": False,
        "_context_resync_refinement": True,
        "_force_output_filepath": str(Path(final_output_path).resolve()),
    })
    return correction


def create_translation_blueprint(state_manager, start_translation_job, output_dir, socketio=None):
    """
    Create and configure the translation blueprint

    Args:
        state_manager: Translation state manager instance
        start_translation_job: Function to start translation jobs
    """
    bp = Blueprint('translation', __name__)

    @bp.errorhandler(ValueError)
    def invalid_value(exc):
        return jsonify(error=str(exc)), 400

    def make_context_resync_auto_resume_callback(translation_id):
        def resume_cb():
            logger.info(
                f"Auto-resuming translation {translation_id} after resync"
            )
            try:
                fresh_checkpoint = (
                    state_manager.checkpoint_manager.load_checkpoint(
                        translation_id
                    )
                )
                if not fresh_checkpoint:
                    raise RuntimeError(
                        "Translation checkpoint is unavailable."
                    )
                config = copy.deepcopy(fresh_checkpoint["job"]["config"])

                preserved_path = config.get("preserved_input_path")
                if not preserved_path:
                    preserved_path = (
                        state_manager.checkpoint_manager
                        .get_preserved_input_path(translation_id)
                    )
                if not preserved_path:
                    raise RuntimeError(
                        "The preserved input file is unavailable."
                    )

                config["file_path"] = preserved_path
                config["resume_from_index"] = fresh_checkpoint[
                    "resume_from_index"
                ]
                config["is_resume"] = True

                live_config = (
                    state_manager.get_translation_field(
                        translation_id,
                        "config",
                    )
                    or {}
                )
                provider = (config.get("llm_provider") or "ollama").lower()
                live_key = live_config.get(f"{provider}_api_key")
                _rehydrate_resume_credentials(
                    config,
                    {"api_key": live_key} if live_key else None,
                )
                credential_error = _provider_credentials_error(config)
                if credential_error is not None:
                    raise RuntimeError(credential_error["message"])

                if not state_manager.exists(translation_id):
                    if not state_manager.restore_job_from_checkpoint(
                        translation_id
                    ):
                        raise RuntimeError(
                            "Could not restore the translation job."
                        )

                state_manager.set_interrupted(translation_id, False)
                state_manager.set_translation_field(
                    translation_id,
                    "status",
                    "running",
                )
                state_manager.checkpoint_manager.mark_running(translation_id)
                emit_update(
                    socketio,
                    translation_id,
                    {
                        "status": "running",
                        "log": "Translation auto-resumed after context resync.",
                    },
                    state_manager,
                )
                start_translation_job(translation_id, config)
            except Exception as e:
                logger.error(f"Failed to auto-resume translation: {e}")
                if state_manager.exists(translation_id):
                    state_manager.set_translation_field(
                        translation_id,
                        "status",
                        "error",
                    )
                    state_manager.set_translation_field(
                        translation_id,
                        "error",
                        str(e),
                    )
                emit_update(
                    socketio,
                    translation_id,
                    {
                        "status": "error",
                        "error": str(e),
                        "log": (
                            "Context re-sync finished, but "
                            f"translation could not resume: {e}"
                        ),
                    },
                    state_manager,
                )

        return resume_cb

    def make_context_resync_polish_callback(translation_id):
        def start_corrective_refinement():
            """Replay refinement once against the fully re-synced snapshots."""
            try:
                fresh_checkpoint = (
                    state_manager.checkpoint_manager.load_checkpoint(
                        translation_id
                    )
                )
                if not fresh_checkpoint:
                    raise RuntimeError(
                        "Translation checkpoint is unavailable."
                    )

                persisted_config = copy.deepcopy(
                    fresh_checkpoint["job"]["config"]
                )
                live_output_path = state_manager.get_translation_field(
                    translation_id,
                    "output_filepath",
                )
                correction_config = _build_corrective_refinement_config(
                    persisted_config,
                    live_output_path,
                )
                if correction_config is None:
                    raise RuntimeError(
                        "The preserved first-pass translation or final output "
                        "is unavailable. Run refinement manually to apply the "
                        "re-synced context."
                    )

                live_config = (
                    state_manager.get_translation_field(
                        translation_id,
                        "config",
                    )
                    or {}
                )
                provider = (
                    correction_config.get("llm_provider") or "ollama"
                ).lower()
                live_key = live_config.get(f"{provider}_api_key")
                _rehydrate_resume_credentials(
                    correction_config,
                    {"api_key": live_key} if live_key else None,
                )
                credential_error = _provider_credentials_error(
                    correction_config
                )
                if credential_error is not None:
                    raise RuntimeError(credential_error["message"])

                if not state_manager.exists(translation_id):
                    if not state_manager.restore_job_from_checkpoint(
                        translation_id
                    ):
                        raise RuntimeError(
                            "Could not restore the translation job."
                        )

                state_manager.set_interrupted(translation_id, False)
                state_manager.set_translation_field(
                    translation_id,
                    "status",
                    "running",
                )
                state_manager.set_translation_field(
                    translation_id,
                    "output_filepath",
                    correction_config["output_filepath"],
                )
                state_manager.checkpoint_manager.mark_running(translation_id)
                emit_update(
                    socketio,
                    translation_id,
                    {
                        "status": "running",
                        "log": (
                            "Context re-sync changed refinement inputs; "
                            "restarting refinement from the preserved "
                            "first-pass translation."
                        ),
                    },
                    state_manager,
                )
                start_translation_job(
                    translation_id,
                    correction_config,
                )
            except Exception as e:
                logger.error(
                    f"Failed to start corrective refinement: {e}"
                )
                if state_manager.exists(translation_id):
                    state_manager.set_translation_field(
                        translation_id,
                        "status",
                        "error",
                    )
                    state_manager.set_translation_field(
                        translation_id,
                        "error",
                        str(e),
                    )
                emit_update(
                    socketio,
                    translation_id,
                    {
                        "status": "error",
                        "error": str(e),
                        "log": (
                            "Context re-sync completed, but corrective "
                            f"refinement could not start: {e}"
                        ),
                    },
                    state_manager,
                )

        return start_corrective_refinement

    @bp.route('/api/translation/<translation_id>/context/<chunk_index>', methods=['GET'])
    def get_context_snapshot(translation_id, chunk_index):
        """Fetch the dynamic context snapshot for a specific chunk"""
        checkpoint_data = state_manager.checkpoint_manager.load_checkpoint(translation_id)
        if not checkpoint_data:
            return jsonify({"error": "Translation not found"}), 404
            
        chunks = checkpoint_data.get('chunks', [])
        if chunk_index == 'latest':
            chunk_index = max(_available_context_chunk_indices(checkpoint_data), default=-1)
        else:
            try:
                chunk_index = int(chunk_index)
            except (TypeError, ValueError):
                return jsonify(error='Invalid passage index'), 400
        
        # Find the specific chunk index (may not exist yet during active translation)
        target_chunk = None
        for chunk in chunks:
            if chunk.get('chunk_index') == chunk_index:
                target_chunk = chunk
                break
        
        # Extract snapshot from chunk data if available
        snapshot = None
        if target_chunk:
            chunk_data = target_chunk.get('chunk_data') or {}
            snapshot = chunk_data.get('context_snapshot')
            
        plain_text_context = ""
        
        config = checkpoint_data.get('job', {}).get('config', {}) or {}
        novel_context_file = config.get('prompt_options', {}).get('novel_context_file')
        auto_update_context = config.get('prompt_options', {}).get('auto_update_context', False)
        
        if not novel_context_file and auto_update_context:
            from src.utils.novel_context import make_novel_context_filename
            novel_context_file = make_novel_context_filename(
                config.get('output_filename', 'translation')
            )
            
            # Update config copy and save back to the DB to repair permanently
            new_config = dict(config)
            if 'prompt_options' not in new_config:
                new_config['prompt_options'] = {}
            else:
                new_config['prompt_options'] = dict(new_config['prompt_options'])
            new_config['prompt_options']['novel_context_file'] = novel_context_file
            
            try:
                state_manager.checkpoint_manager.update_job_config(translation_id, new_config)
            except Exception as persist_err:
                from src.utils.unified_logger import get_logger
                get_logger(__name__).warning(f"Could not persist repaired novel_context_file to database: {persist_err}")
        
        if novel_context_file:
            from src.utils.novel_context import (
                decode_context_snapshot,
                load_novel_context,
                normalize_novel_context_filename,
                resolve_novel_context_path,
            )
            from src.config import NOVEL_CONTEXTS_DIR
            
            full_context = ""
            try:
                novel_context_file = normalize_novel_context_filename(novel_context_file)
                path = resolve_novel_context_path(novel_context_file, NOVEL_CONTEXTS_DIR)
                full_context = load_novel_context(path.name, path.parent)
            except Exception as e:
                from src.utils.unified_logger import get_logger
                get_logger(__name__).error(
                    f"Failed to load or parse context snapshot for file "
                    f"{novel_context_file}: {e}"
                )
            
            if snapshot:
                historical_context, _, _ = decode_context_snapshot(
                    snapshot,
                    full_context,
                )
                if request.args.get('scope') == 'global_lore':
                    from src.utils.novel_context import normalize_refinement_context
                    # Explicit global edits should use the latest book-wide
                    # lore while borrowing this chunk's dynamic-state anchor.
                    plain_text_context = normalize_refinement_context(
                        historical_context,
                        full_context,
                    )
                else:
                    # Historical chunk views should be timeline-safe: show the
                    # exact stored snapshot instead of mixing in future global
                    # facts from the latest context file.
                    plain_text_context = historical_context
            else:
                plain_text_context = full_context
        
        if snapshot and not novel_context_file:
            from src.utils.novel_context import decode_context_snapshot
            plain_text_context, _, _ = decode_context_snapshot(snapshot, '')

        if request.args.get('format') == 'sections' or request.path.startswith('/api/jobs/'):
            from src.utils.notes_store import parse_sections
            sections = parse_sections(plain_text_context)
            scope = request.args.get('scope', 'story')
            if scope == 'global_lore':
                sections = [section for section in sections if section.get('scope') == 'book']
            resync = config.get('_context_resync')
            return jsonify(index=chunk_index, scope=scope, sections=sections,
                           snapshot_indices=_available_context_chunk_indices(checkpoint_data),
                           resync={'status': resync.get('status'), 'done': sum(resync.get('start_chunk_index', -1) < index <= resync.get('last_processed_chunk', -1) for index in _available_context_chunk_indices(checkpoint_data)), 'total': sum(index > resync.get('start_chunk_index', -1) for index in _available_context_chunk_indices(checkpoint_data))} if resync else None)

        return jsonify({
            "translation_id": translation_id,
            "chunk_index": chunk_index,
            "context_content": plain_text_context,
            "has_novel_context": bool(novel_context_file) or bool(auto_update_context),
            "status": target_chunk.get('status') if target_chunk else 'pending',
            "available_chunk_indices": _available_context_chunk_indices(
                checkpoint_data
            ),
        }), 200

    @bp.route('/api/translation/<translation_id>/context/<chunk_index>/resync', methods=['POST'])
    def resync_context_snapshot(translation_id, chunk_index):
        """Update a context snapshot and trigger a background re-sync for subsequent chunks"""
        from src.utils.unified_logger import get_logger
        logger = get_logger(__name__)
        logger.info(f"Received context resync request for translation {translation_id} at chunk {chunk_index}")
        
        data = request.get_json(silent=True)
        normalized_sections, removed_lines = None, []
        if isinstance(data, dict) and 'sections' in data:
            from src.utils.notes_store import serialize_sections, normalize_sections
            if not isinstance(data['sections'], list):
                return jsonify(error='sections must be a list'), 400
            normalized_sections, removed_lines = normalize_sections(data['sections'])
            data['context_content'] = serialize_sections(normalized_sections)
        elif isinstance(data, dict) and data.get('dry_run') and isinstance(data.get('context_content'), str):
            from src.utils.notes_store import parse_sections, serialize_sections, normalize_sections
            normalized_sections, removed_lines = normalize_sections(parse_sections(data['context_content']))
            data['context_content'] = serialize_sections(normalized_sections)
        if not data or 'context_content' not in data:
            logger.error("Context resync failed: Missing context_content in request data")
            return jsonify({"error": "Missing context_content"}), 400
            
        new_content = data['context_content']
        if not isinstance(new_content, str):
            return jsonify({"error": "context_content must be a string"}), 400
        if len(new_content.encode('utf-8')) > 2 * 1024 * 1024:
            return jsonify({"error": "Context content is too large"}), 413

        from src.utils.novel_context import (
            build_novel_context,
            compress_dynamic_state,
            decode_context_snapshot,
            extract_dynamic_state_from_text,
            extract_global_lore,
        )
        dynamic_state = extract_dynamic_state_from_text(new_content)
        if dynamic_state is None:
            return jsonify({
                "error": "Context content must include DYNAMIC_STATE_START and DYNAMIC_STATE_END markers"
            }), 400
        new_content = build_novel_context(
            extract_global_lore(new_content),
            dynamic_state,
        )
        compressed_snapshot = compress_dynamic_state(new_content)
        
        # 1. Update the DB for the target chunk
        checkpoint_data = state_manager.checkpoint_manager.load_checkpoint(translation_id)
        if not checkpoint_data:
            logger.error(f"Context resync failed: Translation {translation_id} not found")
            return jsonify({"error": "Translation not found"}), 404
            
        chunks = checkpoint_data.get('chunks', [])
        if chunk_index == 'latest':
            chunk_index = max(_available_context_chunk_indices(checkpoint_data), default=-1)
        else:
            try:
                chunk_index = int(chunk_index)
            except (TypeError, ValueError):
                return jsonify(error='Invalid passage index'), 400
        target_chunk_idx = None
        for i, chunk in enumerate(chunks):
            if chunk.get('chunk_index') == chunk_index:
                target_chunk_idx = i
                break
                
        if target_chunk_idx is None:
            logger.info(
                f"Context snapshot {chunk_index} is no longer available for "
                f"translation {translation_id}."
            )
            return jsonify({"error": "Chunk is not available for resync"}), 409

        target_chunk = chunks[target_chunk_idx]
        status = target_chunk.get('status')
        if status not in ('completed', 'partial', 'failed'):
            return jsonify({"error": "Only chunks with context snapshots can be resynced"}), 409
        if not (target_chunk.get('chunk_data') or {}).get('context_snapshot'):
            return jsonify({"error": "Chunk has no context snapshot to resync"}), 409
        if data.get('sections') is not None:
            from src.utils.notes_store import parse_sections, serialize_sections, normalize_sections
            baseline, _, _ = decode_context_snapshot((target_chunk.get('chunk_data') or {}).get('context_snapshot'), '')
            previous_sections = {section['key']: section for section in parse_sections(baseline)}
            for section in data['sections']:
                previous = previous_sections.get(section.get('key'))
                if previous and not previous.get('editable', True) and section.get('body') != previous['body']:
                    return jsonify(error='The generated name map is read only'), 400
                previous_sections[section['key']] = section
            normalized_sections, removed_lines = normalize_sections(list(previous_sections.values()))
            new_content = serialize_sections(normalized_sections)
            dynamic_state = extract_dynamic_state_from_text(new_content)
            compressed_snapshot = compress_dynamic_state(new_content)
        if data.get('dry_run'):
            indices = _available_context_chunk_indices(checkpoint_data)
            affected = sum(index > chunk_index for index in indices)
            config = checkpoint_data['job']['config']
            polish = bool(data.get('polish') or config.get('refine_after'))
            polish_requests = len(chunks) if polish else 0
            return jsonify(normalized_sections=normalized_sections, removed_lines=removed_lines,
                           affected_passages=affected, estimated_requests=(0 if data.get('scope') == 'global_lore' else affected) + polish_requests,
                           polish_requests=polish_requests,
                           will_pause_running_job=(state_manager.get_translation_field(translation_id, 'status') == 'running'),
                           output_changes=polish)
        if data.get('polish'):
            config = copy.deepcopy(checkpoint_data['job']['config'])
            output_path = config.get('output_filepath') or state_manager.get_translation_field(translation_id, 'output_filepath')
            if not output_path or not Path(output_path).is_file():
                return jsonify(error='A saved output is required for corrective polish'), 409
            if not config.get('refinement_source_path'):
                if not state_manager.checkpoint_manager.preserve_refinement_source(translation_id, output_path, config):
                    return jsonify(error='Could not preserve the output for corrective polish'), 500
            config['_resync_polish'] = True
            state_manager.checkpoint_manager.update_job_config(translation_id, config)
            checkpoint_data['job']['config'] = config
        if not _claim_context_resync(translation_id):
            return jsonify({"error": "A context resync is already running for this translation"}), 409

        requested_scope = data.get("scope")
        previous_snapshot = (target_chunk.get('chunk_data') or {}).get(
            'context_snapshot'
        )
        _, _, previous_dynamic_state = decode_context_snapshot(
            previous_snapshot,
            "",
        )
        global_only_resync = (
            requested_scope == "global_lore"
            and previous_dynamic_state.strip() == dynamic_state.strip()
        )

        if target_chunk.get('chunk_data') is None:
            target_chunk['chunk_data'] = {}
        target_chunk['chunk_data']['context_snapshot'] = compressed_snapshot

        original_text = target_chunk.get('original_text')
        translated_text = target_chunk.get('translated_text')
        chunk_data = target_chunk.get('chunk_data')
            
        try:
            state_manager.checkpoint_manager.db.save_chunk(
                translation_id=translation_id,
                chunk_index=chunk_index,
                original_text=original_text,
                translated_text=translated_text,
                chunk_data=chunk_data,
                status=status
            )
        except Exception:
            _release_context_resync(translation_id)
            raise
        
        # Any refinement produced from the previous snapshots is now stale.
        context_revision = (
            state_manager.checkpoint_manager.mark_refinement_stale(
                translation_id
            )
        )
        if context_revision is not None:
            logger.info(
                f"Context revision {context_revision} recorded for "
                f"translation {translation_id}."
            )

        # 2. Trigger background resync task
        from src.core.adapters.generic_translator import resync_context_snapshots_background
        
        job_status = state_manager.get_translation(translation_id)
        was_active = False
        auto_resume_callback = None
        post_resync_callback = None
        post_resync_message = None

        start_corrective_refinement = make_context_resync_polish_callback(translation_id)

        if job_status and job_status.get('status') == 'running':
            was_active = True
            logger.info(f"Translation {translation_id} is running. Interrupting for context resync...")
            state_manager.set_interrupted(translation_id, True)
            emit_update(
                socketio,
                translation_id,
                {
                    "log": (
                        "⏸️ Context re-sync requested: waiting for active "
                        "chunk to finish before pausing translation..."
                    ),
                },
                state_manager,
            )

            current_phase = (job_status.get("stats") or {}).get(
                "current_phase"
            )
            if (
                checkpoint_data.get("job", {}).get("config", {}).get(
                    "refine_after"
                )
                and current_phase == 2
            ):
                post_resync_callback = start_corrective_refinement
                post_resync_message = (
                    "Context timeline repaired; restarting corrective "
                    "refinement..."
                )
            else:
                auto_resume_callback = (
                    make_context_resync_auto_resume_callback(translation_id)
                )
        else:
            persisted_status = checkpoint_data.get("job", {}).get("status")
            persisted_config = (
                checkpoint_data.get("job", {}).get("config", {})
            )
            if (
                persisted_status == "completed"
                and (persisted_config.get("refine_after") or persisted_config.get("_resync_polish"))
            ):
                post_resync_callback = start_corrective_refinement
                post_resync_message = (
                    "Context timeline repaired; starting corrective "
                    "refinement..."
                )

        follow_up_kind = None
        if post_resync_callback:
            follow_up_kind = "corrective_refinement"
        elif auto_resume_callback:
            follow_up_kind = "auto_resume_translation"

        persisted_state = _update_context_resync_state(
            state_manager.checkpoint_manager,
            translation_id,
            {
                "status": "running",
                "pause_requested": False,
                "start_chunk_index": chunk_index,
                "last_processed_chunk": chunk_index,
                "context_revision": context_revision,
                "follow_up_kind": follow_up_kind,
                "mode": "global_lore" if global_only_resync else "timeline_replay",
                "was_active": was_active,
                "updated_at": time.time(),
            },
        )
        if persisted_state is None:
            _release_context_resync(translation_id)
            return jsonify({"error": "Failed to persist context resync state"}), 500
            
        logger.info(f"Queueing context resync for translation {translation_id} starting at chunk {chunk_index}")
        
        # Run in a background thread so we don't block the API
        def run_resync():
            try:
                resync_context_snapshots_background(
                    translation_id,
                    chunk_index,
                    compressed_snapshot,
                    socketio,
                    False,
                    auto_resume_callback,
                    post_resync_callback,
                    post_resync_message,
                    global_only_resync,
                )
            finally:
                _release_context_resync(translation_id)

        from src.api.job_runner import get_job_runner
        runner = get_job_runner(state_manager, output_dir, socketio)
        config = state_manager.checkpoint_manager.get_job(translation_id)['config']
        config['_resync_previous_status'] = checkpoint_data['job'].get('status', checkpoint_data['job'].get('progress', {}).get('status', 'interrupted'))
        if was_active:
            state_manager.set_interrupted(translation_id, True)
        runner.enqueue(translation_id, config, next_up=True, task=run_resync)
        runner.start()
        if data.get('sections') is not None or request.path.startswith('/api/jobs/'):
            from .jobs_routes import job_summary
            return jsonify(job=job_summary(runner, runner.db.get_job(translation_id)))

        return jsonify({
            "message": "Context resync started successfully",
            "translation_id": translation_id,
            "chunk_index": chunk_index,
            "context_revision": context_revision,
            "resync_state": persisted_state,
        }), 200

    @bp.route('/api/translation/<translation_id>/context/resync/pause', methods=['POST'])
    def pause_context_resync(translation_id):
        checkpoint_data = state_manager.checkpoint_manager.load_checkpoint(translation_id)
        if not checkpoint_data:
            return jsonify({"error": "Translation not found"}), 404
        config = checkpoint_data.get('job', {}).get('config', {}) or {}
        state = _context_resync_state_from_config(config)
        if state.get("status") not in ("running", "pause_requested"):
            return jsonify({"error": "No running context resync to pause"}), 409
        updated = _update_context_resync_state(
            state_manager.checkpoint_manager,
            translation_id,
            {
                "status": "pause_requested",
                "pause_requested": True,
                "updated_at": time.time(),
            },
            base_config=config,
        )
        if updated is None:
            return jsonify({"error": "Failed to persist context resync pause"}), 500
        return jsonify({
            "message": "Context resync pause requested",
            "translation_id": translation_id,
            "resync_state": updated,
        }), 200

    @bp.route('/api/translation/<translation_id>/context/resync/resume', methods=['POST'])
    def resume_context_resync(translation_id):
        checkpoint_data = state_manager.checkpoint_manager.load_checkpoint(translation_id)
        if not checkpoint_data:
            return jsonify({"error": "Translation not found"}), 404
        config = copy.deepcopy(checkpoint_data.get('job', {}).get('config', {}) or {})
        state = _context_resync_state_from_config(config)
        if state.get("status") not in ("paused", "pause_requested", "running"):
            return jsonify({"error": "No paused context resync to resume"}), 409
        if _is_context_resync_active(translation_id):
            return jsonify({"error": "A context resync is already running for this translation"}), 409

        resume_chunk = state.get("last_processed_chunk", state.get("start_chunk_index"))
        try:
            resume_chunk = int(resume_chunk)
        except (TypeError, ValueError):
            return jsonify({"error": "Context resync resume point is invalid"}), 409

        source_chunk = next(
            (
                chunk for chunk in checkpoint_data.get('chunks', [])
                if chunk.get('chunk_index') == resume_chunk
            ),
            None,
        )
        resume_snapshot = (
            (source_chunk or {}).get('chunk_data') or {}
        ).get('context_snapshot')
        if not resume_snapshot:
            return jsonify({"error": "Context resync resume snapshot is unavailable"}), 409

        overrides = request.get_json(silent=True) or {}
        override_error = _apply_resume_overrides(config, overrides)
        if override_error is not None:
            return override_error

        config['_context_resync'] = {
            **state,
            "status": "running",
            "pause_requested": False,
            "last_processed_chunk": resume_chunk,
            "updated_at": time.time(),
        }
        if not state_manager.checkpoint_manager.update_job_config(translation_id, config):
            return jsonify({"error": "Failed to persist context resync resume"}), 500
        if not _claim_context_resync(translation_id):
            return jsonify({"error": "A context resync is already running for this translation"}), 409

        from src.core.adapters.generic_translator import resync_context_snapshots_background
        auto_resume_callback = None
        if state.get("follow_up_kind") == "auto_resume_translation":
            auto_resume_callback = make_context_resync_auto_resume_callback(
                translation_id
            )

        post_resync_callback = None
        if state.get('follow_up_kind') == 'corrective_refinement':
            post_resync_callback = make_context_resync_polish_callback(translation_id)

        def run_resync():
            try:
                resync_context_snapshots_background(
                    translation_id,
                    resume_chunk,
                    resume_snapshot,
                    socketio,
                    False,
                    auto_resume_callback,
                    post_resync_callback,
                    "Context timeline repaired; starting corrective polish...",
                    state.get("mode") == "global_lore",
                )
            finally:
                _release_context_resync(translation_id)

        from src.api.job_runner import get_job_runner
        runner = get_job_runner(state_manager, output_dir, socketio)
        runner.enqueue(translation_id, config, next_up=True, task=run_resync)
        runner.start()

        return jsonify({
            "message": "Context resync resumed successfully",
            "translation_id": translation_id,
            "resume_from_chunk": resume_chunk,
            "model": config.get('model'),
            "llm_provider": config.get('llm_provider'),
            "resync_state": config['_context_resync'],
        }), 200

    return bp
