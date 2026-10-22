import copy
import threading
import time
from pathlib import Path

from src.persistence.database import sanitize_config_secrets


def resolve_connection(config):
    from src.core.llm.connections import resolve_for_pipeline
    current = resolve_for_pipeline(config['connection_id'], config['model'], config.get('reasoning', 'off'))
    # Only credentials are live. Connection edits must not change a queued job.
    return {**current, **config['connection'], 'api_key': current['api_key']}


class JobRunner:
    def __init__(self, state_manager, output_dir, socketio=None, *, execute=None):
        self.state = state_manager
        self.db = state_manager.get_checkpoint_manager().db
        self.output_dir = str(output_dir)
        self.socketio = socketio
        self.execute = execute
        self.condition = threading.Condition(threading.RLock())
        self.active = None
        self.tasks = {}
        self.thread = None
        self.stopped = False
        self.had_work = bool(self.db.queue_state()['order'])
        state_manager.job_runner = self
        self.db.passage_callback = self.passage_completed

    def passage_completed(self, tid, index, source, translation):
        from src.common.placeholder_format import PlaceholderFormat
        placeholders = PlaceholderFormat.from_config()
        clean = lambda value: placeholders.remove_all(value or '')[:4000]
        preview = {'unit': index, 'source': clean(source), 'translation': clean(translation)}
        self.state.set_translation_field(tid, 'latest_preview', preview)
        if self.socketio:
            from .blueprints.jobs_routes import job_summary
            self.socketio.emit('job_update', {'job': job_summary(self, self.db.get_job(tid)), 'preview': preview}, namespace='/')

    def start(self):
        with self.condition:
            if self.thread is None:
                self.thread = threading.Thread(target=self._work, name='job-runner', daemon=True)
                self.thread.start()
        return self

    def restart_hold(self):
        with self.condition:
            interrupted = False
            for job in self.db.list_jobs():
                config = job['config']
                if job['status'] in ('running', 'rate_limited') or config.get('_pending_operation'):
                    interrupted = True
                    if config.get('_pending_operation'):
                        config.setdefault('_context_resync', {})['status'] = 'paused'
                        self.db.set_queue_order([tid for tid in self.db.queue_state()['order'] if tid != job['translation_id']])
                    config['status_reason'] = 'server_restart'
                    self.db.update_job_config(job['translation_id'], config)
                    self.db.update_job_progress(job['translation_id'], status='interrupted')
                    from src.utils.notifier import notify
                    notify('system_paused', {'translation_id': job['translation_id'], 'error': 'Server restarted'})
                if self.state.exists(job['translation_id']):
                    continue
                self.state.create_translation(job['translation_id'], config)
                self.state.set_translation_field(job['translation_id'], 'status', self.db.get_job(job['translation_id'])['status'])
                self.state.update_stats(job['translation_id'], config.get('stats', job['progress']))
            # Hold the queue only when work was cut off, so the interrupted job can go first.
            if interrupted:
                self.db.set_queue_paused(True, 'restart')

    def _emit_queue(self):
        if self.socketio:
            state = self.db.queue_state()
            self.socketio.emit('queue_update', {k: state[k] for k in ('paused', 'reason')}, namespace='/')

    def pause_queue(self, paused):
        with self.condition:
            self.db.set_queue_paused(paused, 'user' if paused else None)
            self.condition.notify_all()
            self._emit_queue()
        return self.db.queue_state()

    def enqueue(self, tid, config=None, *, next_up=False, task=None):
        with self.condition:
            job = self.db.get_job(tid)
            config = copy.deepcopy(config or (job or {}).get('config') or {})
            config['status_reason'] = None
            config.pop('error', None)
            if task:
                config['_pending_operation'] = 'notes_rebuild'
            if not job:
                if not self.state.get_checkpoint_manager().start_job(tid, config['file_type'], config, config.get('file_path')):
                    raise RuntimeError('Could not persist the translation job')
            else:
                self.db.update_job_config(tid, config)
            if tid != self.active:
                if not self.state.exists(tid):
                    self.state.create_translation(tid, config)
                self.state.set_translation_field(tid, 'config', config)
                self.state.set_interrupted(tid, False)
                self.state.set_translation_field(tid, 'error', None)
                self.state.set_translation_field(tid, 'status', 'queued')
                self.db.update_job_progress(tid, status='queued')
            order = [i for i in self.db.queue_state()['order'] if i != tid]
            order.insert(0 if next_up else len(order), tid)
            self.db.set_queue_order(order)
            if task:
                self.tasks[tid] = task
            self.had_work = True
            self.condition.notify_all()
            self._emit_queue()
            for queued in order:
                self.emit_job(queued)

    def move(self, tid, to):
        with self.condition:
            order = self.db.queue_state()['order']
            if tid not in order:
                raise ValueError('Job is not queued')
            if to not in ('top', 'up', 'down'):
                raise ValueError('to must be top, up or down')
            index = order.index(tid)
            order.pop(index)
            target = 0 if to == 'top' else max(0, index - 1) if to == 'up' else min(len(order), index + 1)
            order.insert(target, tid)
            self.db.set_queue_order(order)
            self._emit_queue()
            for queued in order:
                self.emit_job(queued)

    def pause(self, tid):
        with self.condition:
            job = self.db.get_job(tid)
            if not job:
                raise KeyError(tid)
            config = job['config']
            config['status_reason'] = 'user'
            if config.get('_pending_operation') == 'notes_rebuild':
                config.setdefault('_context_resync', {}).update(pause_requested=True, status='pause_requested' if tid == self.active else 'paused')
                if tid != self.active:
                    self.tasks.pop(tid, None)
                    from .blueprints.translation_routes import _release_context_resync
                    _release_context_resync(tid)
            self.db.update_job_config(tid, config)
            self.state.set_interrupted(tid, True)
            self.state.set_translation_field(tid, 'config', config)
            if tid != self.active:
                self.db.set_queue_order([i for i in self.db.queue_state()['order'] if i != tid])
                self.db.update_job_progress(tid, status='interrupted')
                self.state.set_translation_field(tid, 'status', 'interrupted')
            self.condition.notify_all()

    def _eligible(self, tid):
        config = self.db.get_job(tid)['config']
        previous = config.get('series_previous_id')
        return not previous or (self.db.get_job(previous) or {}).get('status') == 'completed'

    def run_next(self):
        with self.condition:
            queue = self.db.queue_state()
            if self.active or queue['paused']:
                return False
            tid = queue['order'][0] if queue['order'] else None
            if tid is None or not self._eligible(tid):
                return False
            self.active = tid
            self.db.set_queue_order([i for i in queue['order'] if i != tid])
        try:
            self._run(tid)
        except Exception as exc:
            config = self.db.get_job(tid)['config']
            config.update(status_reason='error', error=str(exc))
            self.db.update_job_config(tid, config)
            self.db.update_job_progress(tid, status='error')
            self.state.set_translation_field(tid, 'status', 'error')
            self.state.set_translation_field(tid, 'error', str(exc))
        finally:
            with self.condition:
                self.active = None
                self.condition.notify_all()
                if not self.db.queue_state()['order'] and self.had_work:
                    self.had_work = False
                    from src.utils.notifier import notify
                    notify('queue_finished', {'translation_id': tid})
            self.emit_job(tid)
        return True

    def _run(self, tid):
        job = self.db.get_job(tid)
        config = copy.deepcopy(job['config'])
        if config.get('connection_id'):
            try:
                config['connection'] = resolve_connection(config)
            except Exception as exc:
                from src.core.llm.connections import ConnectionNotFound
                if not isinstance(exc, ConnectionNotFound):
                    raise
                config.update(status_reason='connection_removed', error='Connection removed — choose a model')
                self.db.update_job_config(tid, config)
                self.db.update_job_progress(tid, status='error')
                self.state.set_translation_field(tid, 'status', 'error')
                self.state.set_translation_field(tid, 'error', config['error'])
                return
        elif config.get('connection') is not None:
            from .api_keys import resolve_api_key
            provider = config.get('llm_provider', 'ollama')
            live_config = self.state.get_translation_field(tid, 'config') or {}
            key = (live_config.get('connection') or {}).get('api_key')
            config['connection']['api_key'] = key or resolve_api_key(live_config.get(f'{provider}_api_key'), f'{provider.upper()}_API_KEY') or ''
        previous = config.get('series_previous_id')
        if previous and not config.get('notes_file'):
            from src.utils.notes_store import prepare_job_notes
            carry = self.db.get_job(previous)['config'].get('notes_file')
            config['notes_file'] = prepare_job_notes('copy', source=None, name=config['notes'].get('name'), job_title=config['input_filename'], carry_from=carry)
            config['prompt_options']['novel_context_file'] = config['notes_file']
        preserved = config.get('preserved_input_path')
        if preserved and Path(preserved).is_file():
            config['file_path'] = preserved
        chunks = self.db.get_chunks(tid)
        if chunks:
            checkpoint = self.state.get_checkpoint_manager().load_checkpoint(tid)
            config.update(is_resume=True, resume_from_index=checkpoint['resume_from_index'])
        config['started_at'] = config.get('started_at') or time.time()
        config['status_reason'] = None
        config.pop('error', None)
        self.db.update_job_config(tid, config)
        self.db.update_job_progress(tid, status='running')
        self.state.set_translation_field(tid, 'config', config)
        self.state.set_translation_field(tid, 'status', 'resyncing' if tid in self.tasks else 'running')
        self.state.set_interrupted(tid, False)
        self.state.set_translation_field(tid, 'error', None)
        self.state.update_stats(tid, {'start_time': time.time()})
        started = time.monotonic()
        task = self.tasks.pop(tid, None)
        if task:
            task()
        else:
            if self.execute:
                self.execute(tid, config)
            else:
                from .handlers import run_translation_async_wrapper
                run_translation_async_wrapper(tid, config, self.state, self.output_dir, self.socketio)
        current = self.db.get_job(tid)
        live = self.state.get_translation(tid) or {}
        # Checkpoint writes may add output paths or resync state during execution.
        final = {**config, **current['config']}
        final['stats'] = live.get('stats', {})
        final['stats']['elapsed_seconds'] = config.get('stats', {}).get('elapsed_seconds', 0) + time.monotonic() - started
        final['latest_preview'] = live.get('latest_preview')
        final['error'] = live.get('error')
        final['output_filepath'] = live.get('output_filepath') or final.get('output_filepath')
        if final['output_filepath']:
            final['output_filename'] = Path(final['output_filepath']).name
        status = live.get('status', 'error')
        if task:
            final.pop('_pending_operation', None)
        if status == 'resyncing':
            resync = current['config'].get('_context_resync', {})
            status = 'interrupted' if resync.get('status') == 'paused' else 'error' if resync.get('status') == 'failed' else config.get('_resync_previous_status', 'completed')
        elif status == 'running':
            status = 'completed' if task else 'error'
        if tid in self.db.queue_state()['order']:
            status = 'queued'
        if status == 'interrupted' and not final.get('status_reason'):
            final['status_reason'] = 'user'
        if status == 'error' and not final.get('status_reason'):
            final['status_reason'] = 'error'
        if status == 'completed' and final.get('_context_resync_refinement'):
            final['refine_only'] = final.pop('_resync_original_refine_only', False)
            final['refine_after'] = final.pop('_resync_original_refine_after', False)
            final['file_path'] = final.pop('_resync_original_file_path', final.get('file_path'))
            final['preserved_input_path'] = final.pop('_resync_original_preserved_input_path', final.get('preserved_input_path'))
            final.pop('_context_resync_refinement', None)
            final.pop('_resync_polish', None)
        if status in ('completed', 'partial', 'error'):
            final['finished_at'] = time.time()
        if status == 'completed' and final.get('continue_output_path'):
            output = Path(final['output_filepath'])
            target = Path(final['continue_output_path'])
            if output != target:
                from src.utils.file_utils import get_unique_output_path
                backup = Path(get_unique_output_path(str(target.with_name(f'{target.stem} (before update){target.suffix}'))))
                if target.exists():
                    target.rename(backup)
                try:
                    output.rename(target)
                except OSError:
                    if backup.exists():
                        backup.rename(target)
                    raise
                previous = self.db.get_job(final['continuation_base_id'])
                previous_config = previous['config']
                previous_config.update(output_filepath=str(backup), output_filename=backup.name)
                self.db.update_job_config(previous['translation_id'], previous_config)
                self.state.set_translation_field(previous['translation_id'], 'config', previous_config)
                self.state.set_translation_field(previous['translation_id'], 'output_filepath', str(backup))
                self.emit_job(previous['translation_id'])
                final.update(output_filepath=str(target), output_filename=target.name)
        self.db.update_job_config(tid, final)
        self.db.update_job_progress(tid, status=status)
        self.state.set_translation_field(tid, 'config', sanitize_config_secrets(final))
        self.state.set_translation_field(tid, 'status', status)

    def emit_job(self, tid):
        if self.socketio and self.db.get_job(tid):
            from .blueprints.jobs_routes import job_summary
            self.socketio.emit('job_update', {'job': job_summary(self, self.db.get_job(tid))}, namespace='/')

    def _work(self):
        while not self.stopped:
            if not self.run_next():
                with self.condition:
                    self.condition.wait(timeout=1)


def get_job_runner(state_manager, output_dir, socketio=None):
    runner = getattr(state_manager, 'job_runner', None)
    if runner is None:
        runner = JobRunner(state_manager, output_dir, socketio)
    return runner
