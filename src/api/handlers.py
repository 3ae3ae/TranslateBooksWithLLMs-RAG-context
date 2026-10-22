"""
Translation job handlers and processing logic
"""
import os
import time
import asyncio
import copy
import tempfile
from datetime import datetime
from pathlib import Path

from src.utils.unified_logger import setup_web_logger, LogType
from src.utils.file_utils import get_unique_output_path, find_partial_output_paths, _PARTIAL_RE
from src.utils.custom_instructions import (
    load_custom_instructions,
    is_safe_filename,
)
from src.core.llm import OpenRouterProvider
from src.core.llm.exceptions import RateLimitError
from src.config import AUTO_PAUSE_ON_RATE_LIMIT, RATE_LIMIT_AUTO_RESUME_DELAY
from src.core.adapters import translate_file, refine_file
from src.core.progress import snapshot_from_legacy_stats
from .websocket import emit_update


def run_translation_async_wrapper(translation_id, config, state_manager, output_dir, socketio):
    """
    Wrapper for running translation in async context
    
    Args:
        translation_id (str): Translation job ID
        config (dict): Translation configuration
        state_manager: State manager instance
        output_dir (str): Output directory path
        socketio: SocketIO instance
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(perform_actual_translation(translation_id, config, state_manager, output_dir, socketio))
    except Exception as e:
        error_msg = f"Uncaught major error in translation wrapper {translation_id}: {str(e)}"
        if state_manager.exists(translation_id):
            state_manager.set_translation_field(translation_id, 'status', 'error')
            state_manager.set_translation_field(translation_id, 'error', error_msg)
            logs = state_manager.get_translation_field(translation_id, 'logs')
            if logs is None:
                logs = []
            logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] CRITICAL WRAPPER ERROR: {error_msg}")
            state_manager.set_translation_field(translation_id, 'logs', logs)
            emit_update(socketio, translation_id, {'error': error_msg, 'status': 'error', 'log': f"CRITICAL WRAPPER ERROR: {error_msg}"}, state_manager)
    finally:
        loop.close()


async def perform_actual_translation(translation_id, config, state_manager, output_dir, socketio):
    """
    Perform the actual translation job
    
    Args:
        translation_id (str): Translation job ID
        config (dict): Translation configuration
        state_manager: State manager instance
        output_dir (str): Output directory path
        socketio: SocketIO instance
    """
    if not state_manager.exists(translation_id):
        return

    state_manager.set_translation_field(translation_id, 'status', 'running')
    emit_update(socketio, translation_id, {'status': 'running', 'log': 'Translation task started by worker.'}, state_manager)

    def should_interrupt_current_task():
        if state_manager.exists(translation_id) and state_manager.get_translation_field(translation_id, 'interrupted'):
            _log_message_callback("interruption_check", f"Interruption signal detected for job {translation_id}. Halting processing.")
            return True
        return False

    # Setup unified logger for web interface
    def web_callback(log_entry):
        """Callback for WebSocket emission"""
        # Send full log entry for structured processing on client side
        emit_update(socketio, translation_id, {'log': log_entry['message'], 'log_entry': log_entry}, state_manager)
    
    def storage_callback(log_entry):
        """Callback for storing logs"""
        logs = state_manager.get_translation_field(translation_id, 'logs')
        if logs is None:
            logs = []
        logs.append(log_entry)
        state_manager.set_translation_field(translation_id, 'logs', logs)
    
    logger = setup_web_logger(web_callback, storage_callback)

    def _ui_step_metadata(message_key):
        """Mark user-visible workflow milestones for the activity log."""
        key = (message_key or "").lower()
        if key.endswith(("_request", "_response")):
            return None
        visible = (
            key.startswith((
                "novel_context",
                "refine",
                "refinement",
                "epub_refine",
                "docx_refine",
                "srt_refine",
            ))
            or key in {
                "prepare_start",
                "units_found",
                "unit_start",
                "unit_complete",
                "reconstruct_start",
                "reconstruct_complete",
                "translation_complete",
                "translation_interrupted",
            }
            or key.endswith((
                "_start",
                "_complete",
                "_done",
                "_updated",
                "_refined",
                "_fallback",
                "_failed",
                "_error",
                "_interrupted",
            ))
        )
        if not visible:
            return None
        if "context" in key:
            phase = "context"
        elif "refine" in key or "refinement" in key:
            phase = "refinement"
        else:
            phase = "translation"
        return {"ui_step": message_key, "phase": phase}
    
    def _log_message_callback(message_key_from_translate_module, message_content="", data=None):
        """Legacy callback wrapper for backward compatibility"""
        # Skip debug messages for web interface
        if message_key_from_translate_module in ["llm_prompt_debug", "llm_raw_response_preview"]:
            return
        
        if isinstance(data, dict) and data.get('type') in ('llm_request', 'refinement_request'):
            stats = state_manager.get_translation_field(translation_id, 'stats') or {}
            state_manager.update_stats(translation_id, {'requests': stats.get('requests', 0) + 1})
        step_metadata = _ui_step_metadata(message_key_from_translate_module)
        structured_data = dict(data) if isinstance(data, dict) else {}
        if step_metadata:
            structured_data.update(step_metadata)

        # Handle structured data from new logging system
        if structured_data:
            log_type = structured_data.get('type')
            if log_type == 'llm_request':
                logger.info("LLM Request", LogType.LLM_REQUEST, structured_data)
            elif log_type == 'llm_response':
                # Use INFO level to ensure translation preview works even when DEBUG_MODE=false
                logger.info("LLM Response", LogType.LLM_RESPONSE, structured_data)
            elif log_type == 'refinement_request':
                # Refinement uses same log type as LLM request for UI display
                logger.info("Refinement Request", LogType.REFINEMENT_REQUEST, structured_data)
            elif log_type == 'refinement_response':
                # Refinement uses same log type as LLM response for UI display
                # Use INFO level to ensure translation preview works even when DEBUG_MODE=false
                logger.info("Refinement Response", LogType.REFINEMENT_RESPONSE, structured_data)
            elif log_type == 'progress':
                logger.info("Progress Update", LogType.PROGRESS, structured_data)
            elif log_type == 'novel_context_state':
                logger.info(message_content or "Context Updated", LogType.NOVEL_CONTEXT_STATE, structured_data)
            else:
                logger.info(message_content, data=structured_data)
        else:
            # Map specific message patterns to appropriate log types
            if "error" in message_key_from_translate_module.lower():
                logger.error(message_content)
            elif "warning" in message_key_from_translate_module.lower():
                logger.warning(message_content)
            else:
                logger.info(message_content)

    # Single progress-emit seam. The translate_file → refine_file orchestration
    # still runs two independent engine-side trackers, but the *workflow phase*
    # is now owned here and passed explicitly per phase (TRANSLATING vs
    # REFINING) by whichever call is driving the emit — replacing the old
    # mutable `_workflow_meta` side-channel. A monotonic floor on the canonical
    # `percent` guarantees the bar never regresses across the phase boundary,
    # which is what previously required a manual counter reset at the
    # transition.
    _progress_floor = {'value': 0.0}

    def _context_chunk_indices():
        prompt_options = config.get('prompt_options') or {}
        if not (
            prompt_options.get('novel_context_file')
            or prompt_options.get('auto_update_context')
        ):
            return []
        try:
            rows = state_manager.get_checkpoint_manager().db.get_chunks(
                translation_id
            )
        except Exception:
            return []
        return sorted({
            row['chunk_index']
            for row in rows
            if (
                isinstance(row.get('chunk_index'), int)
                and row.get('status') in ('completed', 'partial', 'failed')
                and (row.get('chunk_data') or {}).get('context_snapshot')
            )
        })

    def _emit_progress(new_stats_dict, phase_meta):
        if not state_manager.exists(translation_id):
            return
        state_manager.update_stats(translation_id, {**new_stats_dict, **phase_meta})
        current_stats = state_manager.get_translation_field(translation_id, 'stats') or {}
        checkpoint_job = state_manager.get_checkpoint_manager().get_job(translation_id)
        if checkpoint_job:
            persisted = checkpoint_job['config']
            persisted['stats'] = current_stats
            state_manager.get_checkpoint_manager().update_job_config(translation_id, persisted)
        current_stats['elapsed_time'] = time.time() - current_stats.get('start_time', time.time())
        # Attach the canonical progress contract alongside the legacy fields,
        # applying the monotonic floor so the global bar never moves backward.
        snapshot = snapshot_from_legacy_stats(current_stats).to_dict()
        if snapshot['percent'] < _progress_floor['value']:
            snapshot['percent'] = _progress_floor['value']
        else:
            _progress_floor['value'] = snapshot['percent']
        current_stats.update(snapshot)
        current_stats['context_chunk_indices'] = _context_chunk_indices()
        state_manager.set_translation_field(translation_id, 'stats', current_stats)
        emit_update(socketio, translation_id, {'stats': current_stats}, state_manager)

        completed = current_stats.get('completed_chunks', 0)
        total = current_stats.get('total_chunks', 0)
        if total > 0:
            logger.update_progress(completed, total)

    def _translate_stats_callback(new_stats_dict):
        # Phase 1. enable_refinement advertises the two-phase bar up-front when
        # a refine-after pass will follow, so phase 1 maps to the [0, 50] band.
        _emit_progress(new_stats_dict, {
            'enable_refinement': bool(config.get('refine_after')),
            'current_phase': 1,
        })

    def _refine_after_stats_callback(new_stats_dict):
        # Phase 2 of a refine-after workflow: maps to the [50, 100] band.
        _emit_progress(new_stats_dict, {'enable_refinement': True, 'current_phase': 2})

    def _refine_only_stats_callback(new_stats_dict):
        # Single-phase refine-only: the whole bar is the refinement pass.
        _emit_progress(new_stats_dict, {
            'enable_refinement': False, 'refine_only': True, 'current_phase': 1,
        })

    def _finalize_stats_callback(new_stats_dict):
        # Finalization pushes (e.g. final elapsed_time) must not re-assert a
        # phase; the stored stats already carry the terminal phase/percent.
        _emit_progress(new_stats_dict, {})

    def _openrouter_cost_callback(cost_data):
        """Update OpenRouter cost in state. No emit: this callback runs on the
        provider's HTTP response thread, and a cross-thread emit can overtake
        the main loop's stats emit on the wire (showing a stale snapshot and
        rolling the progress bar backward). The cost is picked up by the next
        chunk's stats_callback, which is the same thread that owns progress."""
        if state_manager.exists(translation_id):
            state_manager.update_stats(translation_id, {
                'openrouter_cost': cost_data['session_cost'],
                'openrouter_prompt_tokens': cost_data['total_prompt_tokens'],
                'openrouter_completion_tokens': cost_data['total_completion_tokens']
            })

    # Setup OpenRouter cost callback if using OpenRouter provider
    if config.get('llm_provider') == 'openrouter':
        OpenRouterProvider.reset_session_cost()
        OpenRouterProvider.set_cost_callback(_openrouter_cost_callback)

    # Get checkpoint manager and handle resume
    checkpoint_manager = state_manager.get_checkpoint_manager()
    resume_from_index = config.get('resume_from_index', 0)
    is_resume = config.get('is_resume', False)

    try:
        # Create checkpoint for new jobs (not for resumed jobs)
        if not is_resume:
            file_type = config['file_type']
            input_file_path = config.get('file_path')
            checkpoint_manager.start_job(
                translation_id,
                file_type,
                config,
                input_file_path
            )

        # PHASE 2: Configuration validation is now handled by AdaptiveContextManager during translation

        # Normal jobs avoid overwriting existing files. A context re-sync
        # correction deliberately replaces the same final output after replaying
        # refinement from its preserved first-pass translation.
        if is_resume and config['file_type'] == 'epub':
            config['output_filename'] = _PARTIAL_RE.sub('', config['output_filename'])
        forced_output_path = config.get('_force_output_filepath')
        if forced_output_path:
            output_filepath_on_server = os.path.abspath(forced_output_path)
            os.makedirs(
                os.path.dirname(output_filepath_on_server),
                exist_ok=True,
            )
        else:
            tentative_output_path = os.path.join(
                output_dir,
                config['output_filename'],
            )
            output_filepath_on_server = get_unique_output_path(
                tentative_output_path
            )

        # Update config with the actual filename (may have been modified)
        actual_output_filename = os.path.basename(output_filepath_on_server)
        if actual_output_filename != config['output_filename']:
            _log_message_callback("output_filename_modified",
                f"ℹ️ Output filename modified to avoid overwriting: {config['output_filename']} → {actual_output_filename}")
            config['output_filename'] = actual_output_filename

        # Log translation start with unified logger
        logger.info("Translation Started", LogType.TRANSLATION_START, {
            'source_lang': config['source_language'],
            'target_lang': config['target_language'],
            'file_type': config['file_type'].upper(),
            'model': config['model'],
            'translation_id': translation_id,
            'output_file': config['output_filename'],
            'api_endpoint': config['llm_api_endpoint'],
            'chunk_size': config.get('chunk_size', 'default')
        })

        # Make the resumed portion's model/provider explicit in the job log so a
        # resume that switched model/provider (issue #183) is auditable.
        if is_resume:
            _log_message_callback(
                "resume_model_info",
                f"↻ Resuming from chunk {resume_from_index} using "
                f"{config.get('llm_provider', 'ollama')} / {config['model']}."
            )
        if config.get('continuation_base_id'):
            _log_message_callback(
                "continuation_start",
                "➕ Add New Content: comparing the updated source with the "
                "previous checkpoint and reusing the matching translated prefix.",
            )

        input_path_for_translate_module = config.get('file_path')

        # Handle special case for TXT with inline text content (no file upload)
        temp_txt_file_path = None
        if config['file_type'] == 'txt' and 'text' in config and input_path_for_translate_module is None:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".txt", dir=output_dir) as tmp_f:
                tmp_f.write(config['text'])
                temp_txt_file_path = tmp_f.name
            input_path_for_translate_module = temp_txt_file_path

        # Validate input file path
        if not input_path_for_translate_module:
            _log_message_callback("error_no_path", f"❌ {config['file_type'].upper()} translation requires a file path from upload.")
            raise Exception(f"{config['file_type'].upper()} translation requires a file_path.")

        # Read custom instruction file if specified
        custom_instruction_file = config.get('prompt_options', {}).get('custom_instruction_file', '')

        translation_instructions = None
        refinement_instructions = None

        if custom_instruction_file and not config.get('connection_id'):
            from src.config import CUSTOM_INSTRUCTIONS_DIR
            custom_instructions_dir = CUSTOM_INSTRUCTIONS_DIR

            if not is_safe_filename(custom_instruction_file):
                _log_message_callback(
                    "custom_instructions_invalid",
                    f"⚠️ Custom instructions file name '{custom_instruction_file}' is invalid "
                    f"(allowed: alphanumeric, underscore, hyphen, dot; must end in .txt, .yaml, or .yml). "
                    f"Translation will proceed without it."
                )
            else:
                try:
                    loaded = load_custom_instructions(
                        custom_instruction_file, custom_instructions_dir
                    )
                    translation_instructions = loaded.get('translation')
                    refinement_instructions = loaded.get('refinement')

                    if translation_instructions or refinement_instructions:
                        phases = []
                        if translation_instructions:
                            phases.append('translation')
                        if refinement_instructions:
                            phases.append('refinement')
                        _log_message_callback(
                            "custom_instructions",
                            f"📝 Loaded custom instructions: {custom_instruction_file} "
                            f"(phases: {', '.join(phases)})"
                        )
                    else:
                        _log_message_callback(
                            "custom_instructions_empty",
                            f"⚠️ Custom instructions file '{custom_instruction_file}' is empty. "
                            f"Translation will proceed without it."
                        )
                except FileNotFoundError:
                    _log_message_callback(
                        "custom_instructions_missing",
                        f"⚠️ Custom instructions file '{custom_instruction_file}' was selected "
                        f"but not found in {custom_instructions_dir}. Translation will proceed "
                        f"without it."
                    )
                except (ValueError, Exception) as e:
                    _log_message_callback(
                        "custom_instructions_error",
                        f"⚠️ Failed to load custom instructions '{custom_instruction_file}': {e}. "
                        f"Translation will proceed without it."
                    )

        # Inject phase-specific custom instructions into prompt_options
        if translation_instructions or refinement_instructions:
            if 'prompt_options' not in config:
                config['prompt_options'] = {}
            if translation_instructions:
                config['prompt_options']['custom_instructions'] = translation_instructions
            if refinement_instructions:
                config['prompt_options']['refinement_instructions'] = refinement_instructions

        if config.get('refine_only'):
            is_context_resync_refinement = bool(
                config.get('_context_resync_refinement')
            )
            refinement_prompt_options = copy.deepcopy(
                config.get('prompt_options', {})
            )
            if is_context_resync_refinement:
                refinement_prompt_options['_refine_after'] = True
            if is_context_resync_refinement:
                _log_message_callback(
                    "refinement_replay_start",
                    "🛠️ Re-sync correction: refining the preserved first-pass "
                    "translation with the repaired context timeline.",
                )
            else:
                _log_message_callback(
                    "refine_only_mode",
                    "✨ Refine-only mode: skipping translation, polishing the input file as-is."
                )
            src_lang = config.get('source_language')
            tgt_lang = config.get('target_language')
            if (
                not is_context_resync_refinement
                and src_lang
                and tgt_lang
                and src_lang != tgt_lang
            ):
                _log_message_callback(
                    "refine_only_lang_mismatch",
                    f"⚠️ source_language ({src_lang}) ≠ target_language ({tgt_lang}). "
                    f"Refinement is monolingual; the file will be polished as {tgt_lang}."
                )
            refine_success = await refine_file(
                input_filepath=input_path_for_translate_module,
                output_filepath=output_filepath_on_server,
                target_language=config['target_language'],
                model_name=config['model'],
                llm_provider=config.get('llm_provider', 'ollama'),
                checkpoint_manager=checkpoint_manager,
                translation_id=translation_id,
                log_callback=_log_message_callback,
                stats_callback=(
                    _refine_after_stats_callback
                    if is_context_resync_refinement
                    else _refine_only_stats_callback
                ),
                check_interruption_callback=should_interrupt_current_task,
                resume_from_index=resume_from_index,
                llm_api_endpoint=config['llm_api_endpoint'],
                gemini_api_key=config.get('gemini_api_key', ''),
                openai_api_key=config.get('openai_api_key', ''),
                openrouter_api_key=config.get('openrouter_api_key', ''),
                mistral_api_key=config.get('mistral_api_key', ''),
                deepseek_api_key=config.get('deepseek_api_key', ''),
                poe_api_key=config.get('poe_api_key', ''),
                nim_api_key=config.get('nim_api_key', ''),
                context_window=config.get('context_window', 2048),
                auto_adjust_context=config.get('auto_adjust_context', True),
                max_tokens_per_chunk=config.get('max_tokens_per_chunk'),
                prompt_options=refinement_prompt_options,
                parallel_workers=config.get('parallel_workers', 1),
                bilingual_output=config.get('bilingual_output', False),
                soft_limit_ratio=config.get('soft_limit_ratio'),
                connection=config.get('connection'),
                request_timeout=config.get('request_timeout'),
                max_attempts=config.get('max_attempts'),
                retry_delay=config.get('retry_delay', 2),
                srt_lines_per_block=config.get('srt_lines_per_block'),
                unit_validation_retries=config.get('unit_validation_retries'),
            )
            refinement_failed_chunks = (
                state_manager.get_translation_field(
                    translation_id,
                    'stats',
                    {},
                ).get('failed_chunks', 0)
            )
            refine_completed_cleanly = (
                refine_success
                and not should_interrupt_current_task()
                and refinement_failed_chunks == 0
            )
            if (
                is_context_resync_refinement
                and refine_completed_cleanly
            ):
                checkpoint_manager.mark_refinement_current(translation_id)
                _log_message_callback(
                    "refinement_replay_complete",
                    "✅ Corrective refinement completed; the final output now "
                    "matches the re-synced context.",
                )
            if not refine_success and not should_interrupt_current_task():
                if os.path.exists(output_filepath_on_server):
                    current_stats = (
                        state_manager.get_translation_field(translation_id, 'stats') or {}
                    )
                    current_stats['failed_chunks'] = max(
                        1,
                        current_stats.get('failed_chunks', 0),
                    )
                    state_manager.set_translation_field(
                        translation_id,
                        'stats',
                        current_stats,
                    )
                    _log_message_callback(
                        "refine_only_partial",
                        "⚠️ Refinement finished with errors; the best available output was saved.",
                    )
                else:
                    raise RuntimeError("Refinement failed before an output file was produced")
        else:
            # The translate-phase callback advertises the two-phase workflow
            # up-front (via enable_refinement) when a refine-after pass will
            # follow, so the UI renders the phase bar from the start of phase 1.
            translation_prompt_options = copy.deepcopy(
                config.get('prompt_options', {})
            )
            if config.get('refine_after'):
                # The handler owns the second phase. Disable legacy adapter-
                # internal refinement to avoid refining EPUB/DOCX twice.
                translation_prompt_options['refine'] = False

            translation_success = await translate_file(
                input_filepath=input_path_for_translate_module,
                output_filepath=output_filepath_on_server,
                source_language=config['source_language'],
                target_language=config['target_language'],
                model_name=config['model'],
                llm_provider=config.get('llm_provider', 'ollama'),
                checkpoint_manager=checkpoint_manager,
                translation_id=translation_id,
                log_callback=_log_message_callback,
                stats_callback=_translate_stats_callback,
                check_interruption_callback=should_interrupt_current_task,
                resume_from_index=resume_from_index,
                llm_api_endpoint=config['llm_api_endpoint'],
                gemini_api_key=config.get('gemini_api_key', ''),
                openai_api_key=config.get('openai_api_key', ''),
                openrouter_api_key=config.get('openrouter_api_key', ''),
                mistral_api_key=config.get('mistral_api_key', ''),
                deepseek_api_key=config.get('deepseek_api_key', ''),
                poe_api_key=config.get('poe_api_key', ''),
                nim_api_key=config.get('nim_api_key', ''),
                context_window=config.get('context_window', 2048),
                auto_adjust_context=config.get('auto_adjust_context', True),
                max_tokens_per_chunk=config.get('max_tokens_per_chunk'),
                prompt_options=translation_prompt_options,
                bilingual_output=config.get('bilingual_output', False),
                parallel_workers=config.get('parallel_workers', 1),
                soft_limit_ratio=config.get('soft_limit_ratio'),
                connection=config.get('connection'),
                request_timeout=config.get('request_timeout'),
                max_attempts=config.get('max_attempts'),
                retry_delay=config.get('retry_delay', 2),
                srt_lines_per_block=config.get('srt_lines_per_block'),
                unit_validation_retries=config.get('unit_validation_retries'),
                continuation_base_id=config.get('continuation_base_id'),
            )

            if (
                not translation_success
                and not should_interrupt_current_task()
                and state_manager.get_translation_field(translation_id, 'status')
                    not in ('error', 'partial', 'rate_limited')
            ):
                if not os.path.exists(output_filepath_on_server):
                    raise RuntimeError(
                        "Translation stopped before a usable output file was produced"
                    )
                current_stats = (
                    state_manager.get_translation_field(translation_id, 'stats')
                    or {}
                )
                current_stats['failed_chunks'] = max(
                    1,
                    current_stats.get('failed_chunks', 0),
                )
                state_manager.set_translation_field(
                    translation_id,
                    'stats',
                    current_stats,
                )
                _log_message_callback(
                    "translation_partial_output",
                    "⚠️ Translation stopped with errors; the best available "
                    "output was saved and the checkpoint was kept.",
                )

            # Optional chained refinement pass on the translated output.
            should_refine_after = (
                config.get('refine_after')
                and translation_success
                and os.path.exists(output_filepath_on_server)
                and not state_manager.get_translation_field(translation_id, 'interrupted')
                and state_manager.get_translation_field(translation_id, 'status')
                    not in ('error', 'partial', 'rate_limited')
            )
            if config.get('refine_after') and not should_refine_after:
                _log_message_callback(
                    "refine_after_skipped",
                    "⚠️ Refinement pass skipped because translation did not finish cleanly.",
                )
            if should_refine_after:
                refinement_source = (
                    checkpoint_manager.preserve_refinement_source(
                        translation_id,
                        output_filepath_on_server,
                        config,
                    )
                )
                if refinement_source:
                    _log_message_callback(
                        "refinement_source_preserved",
                        "💾 Preserved the first-pass translation for safe "
                        "context re-sync refinement.",
                    )
                else:
                    _log_message_callback(
                        "refinement_source_warning",
                        "⚠️ Could not preserve the first-pass translation; "
                        "future context re-sync will require a manual "
                        "refinement pass.",
                    )
                # Phase 2. No manual counter reset is needed: the refine-phase
                # callback always tags emits as phase 2 with the refine engine's
                # own counters (starting at 0), so a stale phase-1 count can
                # never pair with phase 2, and the monotonic floor in
                # _emit_progress keeps the bar from regressing across the
                # transition.
                _log_message_callback(
                    "refine_after_start",
                    "✨ Translation done — running refinement pass on the output."
                )
                refinement_prompt_options = copy.deepcopy(
                    translation_prompt_options
                )
                refinement_prompt_options['_refine_after'] = True
                refine_success = await refine_file(
                    input_filepath=output_filepath_on_server,
                    output_filepath=output_filepath_on_server,
                    target_language=config['target_language'],
                    model_name=config['model'],
                    llm_provider=config.get('llm_provider', 'ollama'),
                    checkpoint_manager=checkpoint_manager,
                    translation_id=translation_id,
                    log_callback=_log_message_callback,
                    stats_callback=_refine_after_stats_callback,
                    check_interruption_callback=should_interrupt_current_task,
                    resume_from_index=0,
                    llm_api_endpoint=config['llm_api_endpoint'],
                    gemini_api_key=config.get('gemini_api_key', ''),
                    openai_api_key=config.get('openai_api_key', ''),
                    openrouter_api_key=config.get('openrouter_api_key', ''),
                    mistral_api_key=config.get('mistral_api_key', ''),
                    deepseek_api_key=config.get('deepseek_api_key', ''),
                    poe_api_key=config.get('poe_api_key', ''),
                    nim_api_key=config.get('nim_api_key', ''),
                    context_window=config.get('context_window', 2048),
                    auto_adjust_context=config.get('auto_adjust_context', True),
                    max_tokens_per_chunk=config.get('max_tokens_per_chunk'),
                    prompt_options=refinement_prompt_options,
                    parallel_workers=config.get('parallel_workers', 1),
                    bilingual_output=config.get('bilingual_output', False),
                    soft_limit_ratio=config.get('soft_limit_ratio'),
                    connection=config.get('connection'),
                    request_timeout=config.get('request_timeout'),
                    max_attempts=config.get('max_attempts'),
                    retry_delay=config.get('retry_delay', 2),
                    srt_lines_per_block=config.get('srt_lines_per_block'),
                unit_validation_retries=config.get('unit_validation_retries'),
                )
                refinement_failed_chunks = (
                    state_manager.get_translation_field(
                        translation_id,
                        'stats',
                        {},
                    ).get('failed_chunks', 0)
                )
                refine_completed_cleanly = (
                    refine_success
                    and not should_interrupt_current_task()
                    and refinement_failed_chunks == 0
                )
                if refine_completed_cleanly:
                    checkpoint_manager.mark_refinement_current(translation_id)
                    _log_message_callback(
                        "refine_after_complete",
                        "✅ Refinement pass completed; final output is ready.",
                    )
                elif not should_interrupt_current_task():
                    _log_message_callback(
                        "refine_after_fallback",
                        "⚠️ Refinement pass did not complete; keeping the translated output.",
                    )

        # If an EPUB translation was paused, the file was saved with a `[partial NN%]`
        # prefix. Re-point the tracking variables to the actual file on disk so the
        # download endpoint and UI list the right name.
        if (config['file_type'] == 'epub'
                and state_manager.get_translation_field(translation_id, 'interrupted')
                and not os.path.exists(output_filepath_on_server)):
            candidates = find_partial_output_paths(output_filepath_on_server)
            if candidates:
                # Pick the most recently written one if several exist
                actual = max(candidates, key=lambda p: os.path.getmtime(p))
                output_filepath_on_server = actual
                config['output_filename'] = os.path.basename(actual)
                _log_message_callback("output_marked_partial",
                    f"💾 Partial EPUB saved as: {config['output_filename']}")

        # Set result message based on file type
        file_type_upper = config['file_type'].upper()
        result_action = "refined" if config.get('refine_only') else "translated"
        if os.path.exists(output_filepath_on_server) and state_manager.get_translation_field(translation_id, 'status') not in ['error', 'interrupted_before_save']:
            state_manager.set_translation_field(
                translation_id,
                'result',
                f"[{file_type_upper} file {result_action} - download to view]",
            )
        elif not os.path.exists(output_filepath_on_server):
            state_manager.set_translation_field(
                translation_id,
                'result',
                f"[{file_type_upper} file (partially) {result_action} - content not loaded for preview or write failed]",
            )

        # Clean up temporary text file if created
        if temp_txt_file_path and os.path.exists(temp_txt_file_path):
            os.remove(temp_txt_file_path)

        state_manager.set_translation_field(translation_id, 'output_filepath', output_filepath_on_server)
        persisted_config = (checkpoint_manager.get_job(translation_id) or {}).get('config', {})
        persisted_config.update(output_filepath=output_filepath_on_server, output_filename=config['output_filename'])
        checkpoint_manager.update_job_config(translation_id, persisted_config)

        stats = state_manager.get_translation_field(translation_id, 'stats') or {}
        elapsed_time = time.time() - stats.get('start_time', time.time())
        _finalize_stats_callback({'elapsed_time': elapsed_time})

        final_status_payload = {
            'result': state_manager.get_translation_field(translation_id, 'result'),
            'output_filename': config['output_filename'],
            'output_dir': os.path.dirname(os.path.abspath(output_filepath_on_server)),
            'file_type': config['file_type']
        }

        if state_manager.get_translation_field(translation_id, 'interrupted'):
            state_manager.set_translation_field(translation_id, 'status', 'interrupted')
            _log_message_callback("summary_interrupted", f"🛑 Translation interrupted - partial result saved ({elapsed_time:.2f}s)")
            final_status_payload['status'] = 'interrupted'

            # Mark checkpoint as interrupted in database
            checkpoint_manager.mark_interrupted(translation_id)

            # DON'T clean up uploaded file on interruption - keep it for resume capability
            # The file will be preserved in the job-specific directory by checkpoint_manager
            # Only clean up if the preserved file exists (meaning backup was successful)
            preserved_path = config.get('preserved_input_path')
            if preserved_path and Path(preserved_path).exists():
                # Preserved file exists, we can safely delete the original upload
                if 'file_path' in config and config['file_path']:
                    uploaded_file_path = config['file_path']
                    upload_path = Path(uploaded_file_path)

                    if upload_path.exists() and upload_path != Path(preserved_path):
                        try:
                            # Only delete if it's in the uploads directory root (not in a job subdirectory)
                            uploads_dir = Path(output_dir) / 'uploads'
                            resolved_path = upload_path.resolve()

                            # Check if file is directly in uploads/ (not in a job subdirectory)
                            if resolved_path.parent.resolve() == uploads_dir.resolve():
                                upload_path.unlink()
                                _log_message_callback("cleanup_uploaded_file", f"🗑️ Cleaned up uploaded source file (preserved copy exists): {upload_path.name}")
                            else:
                                _log_message_callback("cleanup_skipped", f"ℹ️ Skipped cleanup - file is not in uploads root directory")
                        except Exception as e:
                            _log_message_callback("cleanup_error", f"⚠️ Could not delete uploaded file {upload_path.name}: {str(e)}")
                else:
                    _log_message_callback("cleanup_info", "ℹ️ Original upload file not found or already cleaned up")
            else:
                _log_message_callback("cleanup_skipped_no_preserve", "ℹ️ Skipped cleanup - preserved file not found, keeping original for resume")

        elif state_manager.get_translation_field(translation_id, 'status') != 'error':
            # Get stats for consolidated message
            final_stats = stats
            stats_summary = ""
            failed = final_stats.get('failed_chunks', 0) + final_stats.get('fallback_used', 0)
            if (config['file_type'] in ('txt', 'srt', 'docx')
                    or (config['file_type'] == 'epub' and stats.get('total_chunks', 0) > 0)):
                completed = final_stats.get('completed_chunks', 0)
                failed = final_stats.get('failed_chunks', 0) + final_stats.get('fallback_used', 0)
                total = final_stats.get('total_chunks', 0)
                unit = 'subtitles' if config['file_type'] == 'srt' else 'chunks'
                stats_summary = f" | {completed}/{total} {unit}"
                if failed > 0:
                    stats_summary += f" ({failed} failed)"

            # If chunks remain in failed state after auto-retry, keep the job resumable
            # as 'partial' instead of marking it 'completed' and deleting the checkpoint.
            # The user can then resume to retry the failed chunks without re-running the file.
            if failed > 0:
                state_manager.set_translation_field(translation_id, 'status', 'partial')
                _log_message_callback("summary_partial",
                    f"⚠️ Translation finished with {failed} failed chunk(s) in {elapsed_time:.2f}s"
                    f"{stats_summary} — checkpoint kept for retry")
                final_status_payload['status'] = 'partial'
                checkpoint_manager.mark_partial(translation_id)
                # Skip cleanup_completed_job — we want the checkpoint to survive for retry.
            else:
                state_manager.set_translation_field(translation_id, 'status', 'completed')
                completion_label = "Refinement" if config.get('refine_only') else "Translation"
                _log_message_callback(
                    "summary_completed",
                    f"✅ {completion_label} completed in {elapsed_time:.2f}s{stats_summary}",
                )
                final_status_payload['status'] = 'completed'

                # Retain job history; the checkpoint manager handles legacy source cleanup.
                checkpoint_manager.cleanup_completed_job(translation_id)

            # Clean up uploaded file if it exists and is in the uploads directory
            # On completion, we can safely delete the original upload file
            if 'file_path' in config and config['file_path']:
                uploaded_file_path = config['file_path']
                # Convert to Path object for reliable path operations
                upload_path = Path(uploaded_file_path)

                # Check if file exists
                if upload_path.exists():
                    try:
                        # Only delete if it's in the uploads directory root (not in a job subdirectory)
                        uploads_dir = Path(output_dir) / 'uploads'
                        resolved_path = upload_path.resolve()

                        # Check if file is directly in uploads/ (not in a job subdirectory)
                        if resolved_path.parent.resolve() == uploads_dir.resolve():
                            upload_path.unlink()
                            # Removed verbose cleanup message - file cleanup is automatic
                    except Exception as e:
                        _log_message_callback("cleanup_error", f"⚠️ Could not delete uploaded file {upload_path.name}: {str(e)}")
        else:
            _log_message_callback("summary_error_final", f"❌ Translation finished with errors ({elapsed_time:.2f}s)")
            final_status_payload['status'] = 'error'
            final_status_payload['error'] = state_manager.get_translation_field(translation_id, 'error') or 'Unknown error during finalization.'

        # Stats are now included in the consolidated completion message above

        # Log OpenRouter cost summary if applicable
        if config.get('llm_provider') == 'openrouter':
            cost = stats.get('openrouter_cost', 0.0)
            prompt_tokens = stats.get('openrouter_prompt_tokens', 0)
            completion_tokens = stats.get('openrouter_completion_tokens', 0)
            total_tokens = prompt_tokens + completion_tokens
            if cost > 0 or total_tokens > 0:
                _log_message_callback("openrouter_cost_final",
                    f"💰 OpenRouter Cost: ${cost:.4f} | Tokens: {total_tokens:,} ({prompt_tokens:,} prompt + {completion_tokens:,} completion)")
            # Clear the callback to avoid memory leaks
            OpenRouterProvider.set_cost_callback(None)

        # Attach final stats so the completion card can render its summary
        # (cost, tokens, failed chunks…). emit_update no longer auto-attaches.
        final_status_payload['stats'] = state_manager.get_translation_field(translation_id, 'stats') or {}
        emit_update(socketio, translation_id, final_status_payload, state_manager)

    except RateLimitError as e:
        auto_pause = config.get('auto_pause_on_rate_limit', AUTO_PAUSE_ON_RATE_LIMIT)
        retry_msg = f" Retry suggested after ~{e.retry_after}s." if e.retry_after else ""
        provider_name = e.provider or config.get('llm_provider', 'API')

        if not state_manager.exists(translation_id):
            return

        config['status_reason'] = 'rate_limit'
        checkpoint_manager.update_job_config(translation_id, config)

        # Auto-resume mode keeps the job running: wait, then re-enter from the checkpoint.
        if not auto_pause:
            wait_seconds = e.retry_after or config.get('rate_limit_retry_seconds', RATE_LIMIT_AUTO_RESUME_DELAY)
            config['resume_at'] = time.time() + wait_seconds
            checkpoint_manager.update_job_config(translation_id, config)
            wait_msg = (f"⏳ Rate limited by {provider_name}.{retry_msg} "
                        f"Auto-resume in {wait_seconds}s (auto-pause disabled).")
            _log_message_callback("rate_limit_auto_resume", wait_msg)

            # Surface 'rate_limited' transiently so the UI shows what's happening.
            state_manager.set_translation_field(translation_id, 'status', 'rate_limited')
            emit_update(socketio, translation_id, {
                'status': 'rate_limited',
                'log': wait_msg
            }, state_manager)

            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline and not state_manager.get_translation_field(translation_id, 'interrupted'):
                await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
            config.pop('resume_at', None)
            config['status_reason'] = 'user' if state_manager.get_translation_field(translation_id, 'interrupted') else None
            checkpoint_manager.update_job_config(translation_id, config)

            # Honor an interrupt that arrived during the wait by falling through to pause.
            if state_manager.get_translation_field(translation_id, 'interrupted'):
                _log_message_callback("rate_limit_auto_resume_cancelled",
                    "🛑 Auto-resume cancelled by user, pausing instead.")
            else:
                cp_data = checkpoint_manager.load_checkpoint(translation_id)
                if cp_data:
                    # Track consecutive auto-resume cycles that fail without
                    # translating any chunk past the checkpoint. After three
                    # such cycles the daily quota is probably exhausted and
                    # the loop is just burning time, so we warn the user.
                    # We keep auto-resuming because they explicitly opted in,
                    # but the warning lets them choose to pause manually.
                    resume_index = cp_data['resume_from_index']
                    last_resume_index = config.get('_auto_resume_last_index')
                    stuck_count = config.get('_auto_resume_stuck_count', 0)
                    if last_resume_index == resume_index:
                        stuck_count += 1
                    else:
                        stuck_count = 1
                    if stuck_count >= 3:
                        _log_message_callback(
                            "rate_limit_auto_resume_stuck",
                            f"⚠️ Auto-resume has looped {stuck_count} times without "
                            f"progress (still stuck at chunk {resume_index}). Your "
                            f"daily quota may be exhausted or the provider is "
                            f"throttling this account; consider interrupting now "
                            f"and checking your provider's quota dashboard. "
                            f"Auto-resume will keep trying but may be wasting time."
                        )

                    new_config = dict(config)
                    new_config['is_resume'] = True
                    new_config['resume_from_index'] = resume_index
                    new_config['_auto_resume_last_index'] = resume_index
                    new_config['_auto_resume_stuck_count'] = stuck_count
                    if new_config.get('connection_id'):
                        from .job_runner import resolve_connection
                        from src.core.llm.connections import ConnectionNotFound
                        try:
                            new_config['connection'] = resolve_connection(new_config)
                        except ConnectionNotFound:
                            new_config.update(status_reason='connection_removed', error='Connection removed — choose a model')
                            checkpoint_manager.update_job_config(translation_id, new_config)
                            state_manager.set_translation_field(translation_id, 'status', 'error')
                            state_manager.set_translation_field(translation_id, 'error', new_config['error'])
                            return
                    checkpoint_manager.mark_running(translation_id)
                    state_manager.set_translation_field(translation_id, 'status', 'running')
                    emit_update(socketio, translation_id, {
                        'status': 'running',
                        'log': f"▶️ Auto-resuming from chunk {resume_index}..."
                    }, state_manager)
                    await perform_actual_translation(
                        translation_id, new_config, state_manager, output_dir, socketio
                    )
                    return
                # No checkpoint available, fall through to the pause path below.
                _log_message_callback("rate_limit_no_checkpoint",
                    "⚠️ Auto-resume requested but no checkpoint found, falling back to pause.")

        config['status_reason'] = config.get('status_reason') or 'rate_limit'
        checkpoint_manager.update_job_config(translation_id, config)

        pause_msg = f"⏸️ Rate limited by {provider_name}.{retry_msg} Translation auto-paused, you can resume when ready."
        _log_message_callback("rate_limit_auto_pause", pause_msg)

        state_manager.set_translation_field(translation_id, 'status', 'rate_limited')
        state_manager.set_translation_field(translation_id, 'interrupted', True)
        checkpoint_manager.mark_interrupted(translation_id)

        stats = state_manager.get_translation_field(translation_id, 'stats') or {}
        elapsed_time = time.time() - stats.get('start_time', time.time())
        _finalize_stats_callback({'elapsed_time': elapsed_time})

        emit_update(socketio, translation_id, {
            'status': 'rate_limited',
            'log': pause_msg,
            'result': state_manager.get_translation_field(translation_id, 'result') or f"Translation paused (rate limited)"
        }, state_manager)

    except Exception as e:
        critical_error_msg = f"Critical error during translation task ({translation_id}): {str(e)}"
        _log_message_callback("critical_error_perform_task", critical_error_msg)
        import traceback
        tb_str = traceback.format_exc()
        _log_message_callback("critical_error_perform_task_traceback", tb_str)

        if state_manager.exists(translation_id):
            state_manager.set_translation_field(translation_id, 'status', 'error')
            state_manager.set_translation_field(translation_id, 'error', critical_error_msg)

            emit_update(socketio, translation_id, {
                'error': critical_error_msg,
                'status': 'error',
                'result': state_manager.get_translation_field(translation_id, 'result') or f"Translation failed: {critical_error_msg}"
            }, state_manager)


def freeze_legacy_config(config, state_manager):
    import src.config as defaults
    from .api_keys import resolve_api_key
    config = copy.deepcopy(config)
    config['parallel_workers'] = 1
    prompt = config.setdefault('prompt_options', {})
    for key, setting in (
        ('novel_context_update_interval', 'NOVEL_CONTEXT_UPDATE_INTERVAL'),
        ('novel_context_prompt_max_tokens', 'NOVEL_CONTEXT_PROMPT_MAX_TOKENS'),
        ('novel_context_source_memory_chars', 'NOVEL_CONTEXT_SOURCE_MEMORY_CHARS'),
        ('novel_context_consolidation_interval', 'NOVEL_CONTEXT_CONSOLIDATION_INTERVAL'),
        ('bypass_context_gating', 'BYPASS_CONTEXT_GATING'),
    ):
        prompt.setdefault(key, getattr(defaults, setting))
    config.setdefault('srt_lines_per_block', defaults.SRT_LINES_PER_BLOCK)
    config.setdefault('max_tokens_per_chunk', defaults.MAX_TOKENS_PER_CHUNK)
    config.setdefault('soft_limit_ratio', defaults.SOFT_LIMIT_RATIO)
    config.setdefault('unit_validation_retries', defaults.UNIT_VALIDATION_RETRIES)
    config.setdefault('context_window', defaults.OLLAMA_NUM_CTX)
    config.setdefault('request_timeout', defaults.REQUEST_TIMEOUT)
    config.setdefault('max_attempts', defaults.MAX_TRANSLATION_ATTEMPTS)
    config.setdefault('retry_delay', 2)
    config.setdefault('auto_adjust_context', defaults.AUTO_ADJUST_CONTEXT)
    provider = config.get('llm_provider', 'ollama')
    if not config.get('connection'):
        config['connection'] = {
            'llm_provider': provider, 'llm_api_endpoint': config.get('llm_api_endpoint'),
            'api_key': resolve_api_key(config.get(f'{provider}_api_key'), f'{provider.upper()}_API_KEY') or '',
            'model': config['model'], 'reasoning_effort': config.get('reasoning', 'default'),
            'local': provider == 'ollama', 'connection_type': provider,
            'request_timeout': config.get('request_timeout', defaults.REQUEST_TIMEOUT),
            'max_attempts': config.get('max_attempts', defaults.MAX_TRANSLATION_ATTEMPTS),
            'retry_delay': config.get('retry_delay', 2), 'temperature': config.get('temperature', defaults.TEMPERATURE),
            'rate_limit_behavior': 'pause' if config.get('auto_pause_on_rate_limit', True) else 'retry',
            'rate_limit_retry_seconds': config.get('rate_limit_retry_seconds', defaults.RATE_LIMIT_AUTO_RESUME_DELAY),
        }
    instruction = prompt.pop('custom_instruction_file', None)
    if instruction:
        loaded = load_custom_instructions(instruction, defaults.CUSTOM_INSTRUCTIONS_DIR)
        config.update(style=instruction, style_text=loaded)
        if loaded.get('translation'):
            prompt['custom_instructions'] = loaded['translation']
        if loaded.get('refinement'):
            prompt['refinement_instructions'] = loaded['refinement']
    return config


def start_translation_job(translation_id, config, state_manager, output_dir, socketio):
    """
    Enqueue a translation on the shared worker

    Args:
        translation_id (str): Translation job ID
        config (dict): Translation configuration
        state_manager: State manager instance
        output_dir (str): Output directory path
        socketio: SocketIO instance
    """
    from .job_runner import get_job_runner
    runner = get_job_runner(state_manager, output_dir, socketio)
    config = freeze_legacy_config(config, state_manager)
    runner.enqueue(translation_id, config)
    runner.start()
