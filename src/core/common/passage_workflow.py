"""Durable source -> draft -> polish stages shared by the passage loops."""

from src.core.llm.exceptions import RateLimitError

WORKFLOW_VERSION = 1


def is_polished(row):
    data = row.get('chunk_data') or {}
    return data.get('passage_workflow_version') == WORKFLOW_VERSION and data.get('polish_status') == 'done'


def passage_stage(row, polishes):
    if not polishes:
        return None
    data = row.get('chunk_data') or {}
    if data.get('passage_workflow_version') != WORKFLOW_VERSION:
        return 'draft'
    return {'done': 'polished', 'failed': 'polish_failed'}.get(data.get('polish_status'), 'draft')


def passage_progress(rows, total):
    total = max(total, len(rows))
    translated = sum('draft_text' in (row.get('chunk_data') or {}) or row['status'] == 'completed' for row in rows)
    decided = sum((row.get('chunk_data') or {}).get('polish_status') in ('done', 'failed') for row in rows)
    failed = sum(row['status'] == 'failed' or (row['status'] == 'partial' and 'draft_text' not in (row.get('chunk_data') or {})) for row in rows)
    return dict(interleaved=True, total_chunks=total, translated_chunks=translated, polished_chunks=decided,
                completed_chunks=decided, failed_chunks=failed,
                percent=round((translated + decided) / (2 * total) * 100, 2) if total else 0)


class _SourceContext:
    """Supply the source analysis verbatim; polishing never analyzes a draft."""

    auto_analyze = False

    def __init__(self, options, metadata):
        from src.utils.novel_context import decode_context_snapshot
        snapshot = metadata.get('context_snapshot')
        self.content = decode_context_snapshot(snapshot, '')[0] if snapshot else options.get('novel_context', '')
        if options.get('_repolish_passages'):
            from src.utils.novel_context import normalize_refinement_context
            self.content = normalize_refinement_context(self.content, options.get('_refinement_lore', ''))
        self.current_dialogue_attribution = metadata.get('dialogue_attribution')

    async def next_context(self, **kwargs):
        return self.content


class PassageWorkflow:
    def __init__(self, checkpoint_manager, translation_id, llm_client, model_name,
                 target_language, prompt_options, log_callback=None,
                 check_interruption_callback=None):
        self.manager = checkpoint_manager
        self.tid = translation_id
        self.client = llm_client
        self.model = model_name
        self.language = target_language
        self.options = prompt_options
        self.log = log_callback
        self.interrupt = check_interruption_callback
        self.rows = {row['chunk_index']: row for row in checkpoint_manager.db.get_chunks(translation_id)}
        self.context_revision = (checkpoint_manager.get_job(translation_id) or {}).get('config', {}).get('context_revision', 0)

    def saved(self, index, source):
        row = self.rows.get(index)
        return row if row and row['original_text'] == source else None

    def draft(self, index, source):
        row = self.saved(index, source)
        if not row:
            return None
        data = row.get('chunk_data') or {}
        if 'draft_text' in data:
            return data['draft_text']
        # Legacy translate+polish rows contain drafts, never a durable polish.
        return row.get('translated_text') if row.get('status') == 'completed' else None

    def action(self, index, phase):
        if self.log:
            self.log('passage_stage', phase, data={'current_unit': index, 'phase': phase})

    def _save(self, index, source, text, metadata):
        status = {'pending': 'partial', 'done': 'completed', 'failed': 'failed'}[metadata['polish_status']]
        if not self.manager.db.save_chunk(self.tid, index, source, text, metadata, status=status):
            raise RuntimeError('Could not save passage stage')
        self.rows[index] = dict(chunk_index=index, original_text=source, translated_text=text,
                                chunk_data=dict(metadata), status=status)

    async def finish(self, index, source, draft, metadata, *, kind='txt', chunk=None,
                     placeholder_format=None, context_manager=None):
        saved = self.saved(index, source)
        if saved and is_polished(saved):
            metadata.update(saved.get('chunk_data') or {})
            return saved['translated_text'], True
        metadata.update((saved or {}).get('chunk_data') or {})
        has_saved_draft = bool(saved and (saved.get('chunk_data') or {}).get('passage_workflow_version') == WORKFLOW_VERSION and 'draft_text' in (saved.get('chunk_data') or {}))
        metadata.update(draft_text=draft, passage_workflow_version=WORKFLOW_VERSION)
        self.action(index, 'polishing')
        if not has_saved_draft:
            metadata['polish_status'] = 'pending'
            self._save(index, source, draft, metadata)
        if self.interrupt and self.interrupt():
            return draft, False

        tracker = _SourceContext(self.options, metadata)
        options = {**self.options, 'novel_context': tracker.content,
                   'dialogue_attribution': tracker.current_dialogue_attribution,
                   'auto_update_context': False, 'parallel_workers': 1, '_passage_index': index}
        previous = self.rows.get(index - 1) or {}
        previous_text = previous.get('translated_text', '') if is_polished(previous) else ''
        succeeded = False
        result = draft
        try:
            if kind == 'structured':
                from src.core.epub.xhtml_translator import _refine_epub_chunks
                decisions = []
                values = await _refine_epub_chunks(
                    [draft], [{**(chunk or {}), **metadata}], self.language, self.model,
                    self.client, context_manager, placeholder_format, self.log, options,
                    context_tracker=tracker,
                    result_callback=lambda i, text, ok: decisions.append(ok),
                )
                succeeded = bool(decisions and decisions[0])
                result = values[0] if succeeded else draft
            elif kind == 'srt':
                from src.core.srt_processor import SRTProcessor
                from src.core.subtitle_translator import refine_subtitle_translations
                mapping = {int(k): v for k, v in metadata['local_to_global'].items()}
                translations = SRTProcessor().extract_block_translations_with_remapping(draft, mapping)
                prior_mapping = (previous.get('chunk_data') or {}).get('local_to_global') or {}
                prior = SRTProcessor().extract_block_translations_with_remapping(
                    previous_text, {int(k): v for k, v in prior_mapping.items()}) if previous_text else {}
                state = {'previous_refined_block': '\n'.join(f'[{i}]{text}' for i, text in enumerate(list(prior.values())[-5:]))}
                decisions = []
                block = [{'position': pos} for pos in mapping.values()]
                values = await refine_subtitle_translations(
                    translations, self.language, self.model, self.client, log_callback=self.log,
                    prompt_options=options, post_processing_instructions=options.get('refinement_instructions', ''),
                    subtitle_blocks=[block], subtitle_positions={id(cue): cue['position'] for cue in block},
                    context_tracker=tracker, refinement_state=state,
                    result_callback=lambda i, texts, ok: decisions.append(ok),
                )
                succeeded = bool(decisions and decisions[0]) or not any(value.strip() for value in translations.values())
                result = '\n'.join(f'[{local}]{values[pos]}' for local, pos in mapping.items()) if succeeded else draft
            else:
                from src.core.translator import _make_refinement_request
                from src.core.post_processor import clean_translated_text
                text, _ = await _make_refinement_request(
                    draft_translation=draft, context_before='', context_after='',
                    previous_refined_context=' '.join(previous_text.split()[-25:]),
                    target_language=self.language, model=self.model, llm_client=self.client,
                    log_callback=self.log, has_placeholders=False, prompt_options=options,
                    context_manager=context_manager, context_content=tracker.content,
                )
                succeeded = bool(text and text.strip())
                if succeeded:
                    result = clean_translated_text(text)
                    if kind == 'plain':
                        from src.core.common.plain_text_pipeline import strip_hallucinated_markup
                        result = strip_hallucinated_markup(result, draft)
        except RateLimitError:
            raise
        except Exception as exc:
            if self.log:
                self.log('passage_polish_failed', f'Polish failed for passage {index + 1}: {exc}')
        metadata['polish_status'] = 'done' if succeeded else 'failed'
        metadata['polish_context_revision'] = self.context_revision
        current_revision = (self.manager.get_job(self.tid) or {}).get('config', {}).get('context_revision', 0)
        if current_revision != self.context_revision:
            # A notes edit while the request was in flight must keep this polish pending.
            latest = next((row for row in self.manager.db.get_chunks(self.tid) if row['chunk_index'] == index), {})
            metadata.update({key: value for key, value in (latest.get('chunk_data') or {}).items() if key in ('context_snapshot', 'dialogue_attribution')})
            metadata['polish_status'] = 'pending'
            succeeded = False
        self._save(index, source, result, metadata)
        return result, succeeded
