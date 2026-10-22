"""Persistent jobs facade. The legacy translation routes remain available."""
import copy
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from src.api.job_runner import get_job_runner
from src.api.services.path_validator import PathValidator
from src.persistence.database import sanitize_config_secrets


def _iso(value):
    """Timestamps leave the API as ISO 8601 UTC, whatever form they were stored in."""
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    text = str(value).replace(' ', 'T')
    # SQLite CURRENT_TIMESTAMP is UTC without an offset.
    return text if text.endswith('Z') or '+' in text[10:] or '-' in text[10:] else text + 'Z'


_PHASES = {'context': 'notes', 'refining': 'polishing', 'refinement': 'polishing', 'translation': 'translating'}


def job_summary(runner, job):
    config = job['config']
    tid = job['translation_id']
    live = runner.state.get_translation(tid) or {}
    stats = {**job['progress'], **config.get('stats', {}), **live.get('stats', {})}
    status = job['status']
    if tid == runner.active:
        status = live.get('status', status)
    status = {'interrupted': 'paused', 'error': 'failed', 'resyncing': 'running', 'rate_limited': 'paused' if config.get('auto_pause_on_rate_limit', True) else 'waiting'}.get(status, status)
    order = runner.db.queue_state()['order']
    output = live.get('output_filepath') or config.get('output_filepath')
    if not output and config.get('output_filename'):
        output = str(Path(runner.output_dir) / config['output_filename'])
    epub = stats.get('epub_accumulated_stats') or {}
    done, total = stats.get('completed_chunks', 0), stats.get('total_chunks', 0)
    # The runner keeps the total across pauses; the pipeline's own timer restarts on every resume.
    elapsed = config.get('stats', {}).get('elapsed_seconds', stats.get('elapsed_time', 0))
    if runner.active == tid:
        elapsed += max(0, time.time() - live.get('stats', {}).get('start_time', time.time()))
    notes_rebuild = config.get('_context_resync')
    rebuild_indices = [row['chunk_index'] for row in runner.db.get_chunks(tid)] if notes_rebuild else []
    phase = 'context' if config.get('_pending_operation') == 'notes_rebuild' else stats.get('phase', stats.get('current_phase', 'translation'))
    return {
        'id': tid, 'title': Path(config.get('input_filename') or 'Translation').stem,
        'input_filename': config.get('input_filename'), 'file_type': job['file_type'],
        'task': config.get('task', 'polish' if config.get('refine_only') else 'translate'),
        'polish_after': config.get('polish_after', config.get('refine_after', False)),
        'status': status, 'status_reason': config.get('status_reason'),
        'phase': _PHASES.get(phase, phase),
        'percent': stats.get('percent', stats.get('progress_percent', done / total * 100 if total else 0)),
        'units_done': done, 'units_total': total, 'units_failed': stats.get('failed_chunks', 0),
        'units_untranslated': stats.get('fallback_used', epub.get('fallback_used', 0)),
        'formatting_approximated': stats.get('token_alignment_used', epub.get('token_alignment_used', 0)),
        'source_language': config.get('source_language', ''), 'target_language': config.get('target_language'),
        'connection_id': config.get('connection_id'), 'connection_name': config.get('connection_name'),
        'model': config.get('model'), 'reasoning': config.get('reasoning', 'off'),
        'created_at': _iso(job['created_at']), 'started_at': _iso(config.get('started_at')),
        'updated_at': _iso(job['updated_at']), 'finished_at': _iso(config.get('finished_at', job.get('completed_at'))),
        'queue_position': order.index(tid) + 1 if tid in order else None,
        'output_filename': Path(output).name if output else config.get('output_filename'),
        'output_exists': bool(output and Path(output).is_file()), 'has_cover': bool(config.get('cover_path') and Path(config['cover_path']).is_file()),
        'cost_usd': stats.get('cost_usd', stats.get('openrouter_cost') or None),
        'requests': stats.get('requests', 0), 'elapsed_seconds': elapsed,
        'eta_seconds': elapsed / done * max(0, total - done) if done and status == 'running' else None,
        'error': live.get('error') or config.get('error'), 'resume_at': config.get('resume_at'),
        'notes_name': config.get('notes_file'),
        'notes_rebuild': {'status': notes_rebuild.get('status'), 'done': sum(notes_rebuild.get('start_chunk_index', -1) < index <= notes_rebuild.get('last_processed_chunk', -1) for index in rebuild_indices), 'total': sum(index > notes_rebuild.get('start_chunk_index', -1) for index in rebuild_indices)} if notes_rebuild else None,
        'series_id': config.get('series_id'),
    }


def _integer(value, name, minimum=1, maximum=1000000):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer between {minimum} and {maximum}')
    return value


def build_configs(body, state_manager, output_dir):
    from src.utils.preferences import get_preferences
    from src.core.llm.connections import resolve_for_pipeline
    from src.utils.notes_store import prepare_job_notes
    from src.utils.file_detector import detect_file_type
    from src.utils.language_detector import LanguageDetector
    from src.utils.custom_instructions import load_custom_instructions, is_safe_filename
    from src.config import CUSTOM_INSTRUCTIONS_DIR, SOFT_LIMIT_RATIO, UNIT_VALIDATION_RETRIES, OLLAMA_NUM_CTX

    if not isinstance(body, dict):
        raise ValueError('Expected a JSON object')
    defaults = get_preferences()
    data = {**defaults, **body}
    files = body.get('files')
    if not isinstance(files, list) or not files or any(not isinstance(f, dict) for f in files):
        raise ValueError('files must be a non-empty list')
    connection_id = body.get('connection_id', defaults.get('default_connection_id'))
    model = body.get('model', defaults.get('default_model'))
    reasoning = body.get('reasoning', defaults.get('default_reasoning', 'off'))
    if not isinstance(connection_id, str) or not connection_id or not isinstance(model, str) or not model.strip():
        raise ValueError('connection_id and model are required')
    if reasoning not in ('off', 'low', 'medium', 'high', 'default'):
        raise ValueError('Invalid reasoning')
    task = data.get('task', 'translate')
    if task not in ('translate', 'polish'):
        raise ValueError('task must be translate or polish')
    for key in ('polish_after', 'ocr_cleanup', 'simplify_formatting', 'bilingual', 'chapter_mode', 'remember_defaults'):
        if key in data and not isinstance(data[key], bool):
            raise ValueError(f'{key} must be a boolean')
    if not isinstance(data.get('source_language', ''), str) or not isinstance(data.get('target_language'), str) or not data['target_language'].strip():
        raise ValueError('target_language is required; languages must be strings')
    connection = resolve_for_pipeline(connection_id, model, reasoning)
    connection['retry_delay'] = connection.get('retry_delay', 2)
    notes_input = body.get('notes') or {}
    if not isinstance(notes_input, dict):
        raise ValueError('notes must be an object')
    notes = {key: defaults.get('notes_' + key, fallback) for key, fallback in (
        ('mode', 'build'), ('update_interval', 1), ('prompt_max_tokens', 1800), ('source_memory_chars', 6000), ('consolidation_interval', 5), ('accept_gender_corrections', True))}
    notes.update(keep_updating=True, series=False)
    notes.update(notes_input)
    if notes['mode'] not in ('build', 'copy', 'off'):
        raise ValueError('Invalid notes mode')
    for key in ('keep_updating', 'series', 'accept_gender_corrections'):
        if not isinstance(notes[key], bool):
            raise ValueError(f'notes.{key} must be a boolean')
    for key in ('update_interval', 'prompt_max_tokens', 'source_memory_chars', 'consolidation_interval'):
        _integer(notes[key], f'notes.{key}', 1 if key == 'update_interval' else 0, 10000 if key in ('update_interval', 'consolidation_interval') else 1000000)
    if task == 'polish' and notes['mode'] == 'build':
        if 'mode' in notes_input:
            raise ValueError('Polish supports existing read-only notes or notes off')
        notes['mode'] = 'off'
    if task == 'polish':
        notes['keep_updating'] = False
    if notes['mode'] == 'copy' and not notes.get('source'):
        raise ValueError('notes.source is required for copy')
    tokens = _integer(data.get('passage_tokens', 450), 'passage_tokens', 50)
    lines = _integer(data.get('srt_lines_per_block', 10), 'srt_lines_per_block', maximum=10000)
    style = data.get('style')
    style_text = None
    if style:
        if not isinstance(style, str) or not is_safe_filename(style):
            raise ValueError('Invalid style filename')
        style_text = load_custom_instructions(style, CUSTOM_INSTRUCTIONS_DIR)
    series_id = uuid.uuid4().hex if notes['series'] and notes['mode'] != 'off' else None
    configs = []
    for file in files:
        path, error = PathValidator.validate_upload_path(file.get('file_path'), Path(output_dir) / 'uploads')
        if error or not path.is_file():
            raise ValueError(error or 'Upload is not a file')
        name = file.get('input_filename') or path.name
        if not isinstance(name, str) or not PathValidator.validate_filename(name)[0]:
            raise ValueError('Invalid input_filename')
        file_type = detect_file_type(str(path))
        source = file.get('source_language', data.get('source_language', ''))
        if not isinstance(source, str):
            raise ValueError('source_language must be a string')
        if task == 'polish':
            source = data['target_language']
        if not source.strip():
            if file_type == 'docx':
                from src.core.docx.plain_extractor import extract_plain_paragraphs
                detection_data = '\n'.join(extract_plain_paragraphs(str(path)).paragraphs_text).encode('utf-8')
                detection_name = 'source.txt'
            else:
                detection_data, detection_name = path.read_bytes(), name
            source, _ = LanguageDetector.detect_language_from_file(detection_data, detection_name)
            if not source:
                raise ValueError(f'Could not detect the language of {name}; choose a source language')
        pattern = data.get('output_filename_pattern') or '{originalName} ({targetLang}).{ext}'
        if not isinstance(pattern, str):
            raise ValueError('output_filename_pattern must be a string')
        replacements = {'originalName': Path(name).stem, 'sourceLang': source, 'targetLang': data['target_language'], 'ext': file_type, 'model': model, 'date': time.strftime('%Y-%m-%d'), 'datetime': time.strftime('%Y-%m-%d_%H-%M-%S')}
        output = pattern
        for key, value in replacements.items():
            value = re.sub(r'[/\\:*?"<>|]+', '_', value)
            value = ' '.join(value.split())
            output = output.replace('{' + key + '}', value)
        if not PathValidator.validate_filename(output)[0] or output in ('.', '..'):
            raise ValueError('Invalid output filename')
        file_notes = copy.deepcopy(notes)
        if file_type == 'srt' and 'mode' not in notes_input:
            file_notes['mode'] = 'off'
        prompt = {
            'text_cleanup': data.get('ocr_cleanup', False), 'plain_text_mode': data.get('simplify_formatting', False),
            'bilingual': data.get('bilingual', False), 'chapter_mode': data.get('chapter_mode', False),
            'auto_update_context': file_notes['mode'] != 'off' and file_notes['keep_updating'],
            'novel_context_update_interval': file_notes['update_interval'],
            'novel_context_prompt_max_tokens': file_notes['prompt_max_tokens'],
            'novel_context_source_memory_chars': file_notes['source_memory_chars'],
            'novel_context_consolidation_interval': file_notes['consolidation_interval'],
            'bypass_context_gating': file_notes['accept_gender_corrections'],
        }
        if style_text:
            if style_text.get('translation'):
                prompt['custom_instructions'] = style_text['translation']
            if style_text.get('refinement'):
                prompt['refinement_instructions'] = style_text['refinement']
        config = {
            **sanitize_config_secrets(connection),
            'connection': sanitize_config_secrets(connection), 'reasoning': reasoning,
            'task': task, 'polish_after': data.get('polish_after', False),
            'refine_only': task == 'polish', 'refine_after': task == 'translate' and data.get('polish_after', False),
            'file_path': str(path), 'input_filename': name, 'file_type': file_type,
            'source_language': source, 'target_language': data['target_language'], 'output_filename': output,
            'output_filename_pattern': pattern, 'notes': file_notes, 'notes_file': None,
            'series_id': series_id if file_notes['mode'] != 'off' else None,
            'style': style, 'style_text': style_text,
            'prompt_options': prompt, 'max_tokens_per_chunk': tokens, 'passage_tokens': tokens,
            'srt_lines_per_block': lines, 'soft_limit_ratio': SOFT_LIMIT_RATIO,
            'unit_validation_retries': UNIT_VALIDATION_RETRIES,
            'context_window': OLLAMA_NUM_CTX,
            'auto_adjust_context': connection['local'] and connection['connection_type'] == 'ollama',
            'bilingual_output': data.get('bilingual', False), 'parallel_workers': 1 if connection['local'] else connection['parallel_requests'],
            'auto_pause_on_rate_limit': connection['rate_limit_behavior'] == 'pause',
            'retry_delay': connection.get('retry_delay', 2), 'status_reason': None,
            'ocr_cleanup': data.get('ocr_cleanup', False), 'simplify_formatting': data.get('simplify_formatting', False),
            'bilingual': data.get('bilingual', False), 'chapter_mode': data.get('chapter_mode', False),
        }
        configs.append(config)
    # Validate every file before creating notes or persisting any jobs.
    seen_series = False
    for config in configs:
        if config['file_type'] == 'epub':
            from src.core.epub.cover_extractor import EPUBCoverExtractor
            thumbnails = Path(output_dir) / 'thumbnails'
            thumbnails.mkdir(parents=True, exist_ok=True)
            cover = EPUBCoverExtractor.extract_cover(config['file_path'], thumbnails)
            if cover:
                config['cover_path'] = str(thumbnails / cover)
        if not (config['series_id'] and seen_series):
            n = config['notes']
            config['notes_file'] = prepare_job_notes(n['mode'], source=n.get('source'), name=n.get('name'), job_title=config['input_filename'])
            config['prompt_options']['novel_context_file'] = config['notes_file']
        if config['series_id']:
            seen_series = True
    return configs


def create_jobs_blueprint(state_manager, output_dir, socketio=None):
    bp = Blueprint('jobs', __name__)
    runner = get_job_runner(state_manager, output_dir, socketio)

    @bp.errorhandler(ValueError)
    @bp.errorhandler(TypeError)
    @bp.errorhandler(KeyError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @bp.route('/api/queue', methods=['GET', 'POST'])
    def queue():
        if request.method == 'POST':
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or not isinstance(body.get('paused'), bool):
                raise ValueError('paused must be a boolean')
            runner.pause_queue(body['paused'])
        return jsonify(runner.db.queue_state())

    @bp.route('/api/jobs', methods=['GET', 'POST'])
    def jobs():
        if request.method == 'GET':
            return jsonify(jobs=[job_summary(runner, j) for j in runner.db.list_jobs()])
        body = request.get_json(silent=True)
        try:
            configs = build_configs(body, state_manager, output_dir)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        except Exception as exc:
            from src.core.llm.connections import ConnectionNotFound
            if isinstance(exc, ConnectionNotFound):
                return jsonify(error='Connection removed — choose a model', status_reason='connection_removed'), 400
            raise
        result = []
        previous = None
        with runner.condition:
            for config in configs:
                tid = uuid.uuid4().hex
                if config.get('series_id') and previous:
                    config['series_previous_id'] = previous
                runner.enqueue(tid, config)
                result.append({'id': tid, 'status': 'queued', 'queue_position': runner.db.queue_state()['order'].index(tid) + 1})
                if config.get('series_id'):
                    previous = tid
        if body.get('remember_defaults', True):
            from src.utils.preferences import remember_job_defaults
            try:
                remember_job_defaults(body)
            except ValueError:
                for item in result:
                    state_manager.append_log(item['id'], {'type': 'warning', 'message': 'Translation queued, but the default choices could not be saved.'})
        return jsonify(jobs=result), 201

    def get_job(tid):
        return runner.db.get_job(tid)

    @bp.route('/api/jobs/<tid>', methods=['GET', 'DELETE'])
    def detail(tid):
        job = get_job(tid)
        if not job:
            return jsonify(error='Job not found'), 404
        summary = job_summary(runner, job)
        if request.method == 'DELETE':
            if tid == runner.active:
                return jsonify(error='Pause the job before deleting it'), 409
            output = job['config'].get('output_filepath') or str(Path(output_dir) / (summary['output_filename'] or ''))
            if request.args.get('delete_output', '').lower() in ('1', 'true') and Path(output).is_file():
                if not PathValidator.is_within_directory(output, output_dir):
                    return jsonify(error='Output is outside the output directory'), 403
                Path(output).unlink()
            runner.tasks.pop(tid, None)
            from .translation_routes import _release_context_resync
            _release_context_resync(tid)
            if not state_manager.delete_checkpoint(tid):
                return jsonify(error='Pause the job before deleting it'), 409
            state_manager.log_path(tid).unlink(missing_ok=True)
            return jsonify(id=tid)
        chunks = runner.db.get_chunks(tid)
        return jsonify(**summary, config=sanitize_config_secrets(job['config']),
                       output_path=job['config'].get('output_filepath'),
                       latest_preview=state_manager.get_translation_field(tid, 'latest_preview') or job['config'].get('latest_preview'),
                       notes_snapshots=[c['chunk_index'] for c in chunks if (c.get('chunk_data') or {}).get('context_snapshot')])

    @bp.route('/api/jobs/<tid>/<action>', methods=['POST'])
    def action(tid, action):
        job = get_job(tid)
        if not job:
            return jsonify(error='Job not found'), 404
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise ValueError('Expected a JSON object')
        if action in ('pause', 'remove-from-queue'):
            if action == 'remove-from-queue' and tid not in runner.db.queue_state()['order']:
                return jsonify(error='Job is not queued'), 409
            runner.pause(tid)
        elif action == 'move':
            runner.move(tid, body.get('to'))
        elif action == 'resume':
            if tid == runner.active or job['status'] == 'completed':
                return jsonify(error='Job cannot be resumed in its current state'), 409
            config = job['config']
            config['is_resume'] = True
            if any(k in body for k in ('connection_id', 'model', 'reasoning')):
                from src.core.llm.connections import resolve_for_pipeline
                from src.core.llm.connections import ConnectionNotFound
                try:
                    resolved = resolve_for_pipeline(body.get('connection_id', config.get('connection_id')), body.get('model', config['model']), body.get('reasoning', config.get('reasoning', 'off')))
                except ConnectionNotFound:
                    return jsonify(error='Connection removed — choose a model', status_reason='connection_removed'), 400
                safe = sanitize_config_secrets(resolved)
                config.update(safe, connection=safe, reasoning=body.get('reasoning', config.get('reasoning', 'off')), parallel_workers=1 if safe['local'] else safe['parallel_requests'], auto_pause_on_rate_limit=safe['rate_limit_behavior'] == 'pause')
            if config.get('_context_resync', {}).get('status') == 'paused':
                from flask import current_app
                runner.db.update_job_config(tid, config)
                resume_notes = current_app.view_functions.get('translation.resume_context_resync')
                if resume_notes is None:
                    return jsonify(error='Notes routes are not registered'), 409
                response = current_app.make_response(resume_notes(tid))
                if response.status_code >= 400:
                    return response
                return jsonify(job=job_summary(runner, get_job(tid)))
            runner.enqueue(tid, config, next_up=True)
            # Resuming is an explicit "run this", so it lifts the hold a restart put on the queue.
            if runner.db.queue_state().get('reason') == 'restart':
                runner.pause_queue(False)
        elif action == 'continue':
            if job['status'] != 'completed':
                return jsonify(error='Only a completed job can accept new chapters'), 409
            path, error = PathValidator.validate_upload_path(body.get('file_path'), Path(output_dir) / 'uploads')
            if error or not path.is_file():
                raise ValueError(error or 'Upload is not a file')
            from src.utils.file_detector import detect_file_type
            if detect_file_type(str(path)) != job['file_type']:
                raise ValueError('Updated source must use the same file format')
            name = body.get('input_filename') or path.name
            if not isinstance(name, str) or not PathValidator.validate_filename(name)[0]:
                raise ValueError('Invalid input_filename')
            config = copy.deepcopy(job['config'])
            output = config.get('output_filepath') or str(Path(output_dir) / config['output_filename'])
            for key in ('stats', 'finished_at', 'started_at', 'preserved_input_path', 'output_filepath', 'refinement_source_path', '_force_output_filepath', 'is_resume', 'resume_from_index', '_context_resync'):
                config.pop(key, None)
            config.update(file_path=str(path), input_filename=body.get('input_filename') or path.name, continuation_base_id=tid, continue_output_path=output)
            if config.get('notes_file'):
                from src.utils.notes_store import prepare_job_notes
                config['notes_file'] = prepare_job_notes('copy', source=config['notes_file'], name=None, job_title=config['input_filename'])
                config['prompt_options']['novel_context_file'] = config['notes_file']
            config.pop('series_previous_id', None)
            new_id = uuid.uuid4().hex
            runner.enqueue(new_id, config)
            return jsonify(id=new_id, status='queued'), 201
        elif action in ('open', 'reveal'):
            from src.api.services.file_service import FileService
            service = FileService(str(output_dir))
            fn = service.open_file if action == 'open' else service.reveal_file
            ok, message, path = fn(job_summary(runner, job)['output_filename'])
            return jsonify(success=ok, message=message, path=path), 200 if ok else 400
        else:
            return jsonify(error='Unknown action'), 404
        runner.emit_job(tid)
        return jsonify(job=job_summary(runner, get_job(tid)))

    @bp.route('/api/jobs/<tid>/passages')
    def passages(tid):
        if not get_job(tid):
            return jsonify(error='Job not found'), 404
        offset = max(0, int(request.args.get('offset', 0)))
        limit = max(1, min(500, int(request.args.get('limit', 50))))
        query = request.args.get('q', '').casefold()
        from src.common.placeholder_format import PlaceholderFormat
        placeholders = PlaceholderFormat.from_config()
        items = []
        for row in runner.db.get_chunks(tid):
            source = placeholders.remove_all(row['original_text'] or '')
            translation = placeholders.remove_all(row['translated_text'] or '')
            if not query or query in source.casefold() or query in translation.casefold():
                items.append({'index': row['chunk_index'], 'source': source, 'translation': translation, 'status': row['status']})
        return jsonify(total=len(items), items=items[offset:offset + limit])

    @bp.route('/api/jobs/<tid>/log')
    def log(tid):
        if not get_job(tid):
            return jsonify(error='Job not found'), 404
        from collections import deque
        tail = max(1, min(10000, int(request.args.get('tail', 500))))
        path = state_manager.log_path(tid)
        if not path.exists():
            return jsonify(items=[])
        with path.open(encoding='utf-8') as stream:
            entries = []
            for line in deque(stream, tail):
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return jsonify(items=entries)

    @bp.route('/api/jobs/<tid>/cover')
    def cover(tid):
        job = get_job(tid)
        if not job:
            return jsonify(error='Job not found'), 404
        path = job['config'].get('cover_path')
        if not path or not Path(path).is_file():
            return jsonify(error='Cover not found'), 404
        return send_file(path)

    return bp
