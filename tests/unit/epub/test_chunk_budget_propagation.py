from unittest.mock import AsyncMock

import pytest
from lxml import etree

from src.core.docx.docx_translation_adapter import DocxTranslationAdapter
from src.core.epub.container import TranslationContainer
from src.core.epub.epub_translation_adapter import EpubTranslationAdapter


class _RecordingChunker:
    created_with = []

    def __init__(self, max_tokens):
        self.max_tokens = max_tokens
        self.created_with.append(max_tokens)

    def chunk_html_with_placeholders(self, text, tag_map):
        return [{"text": text, "max_tokens": self.max_tokens}]


def test_docx_adapter_honors_explicit_job_chunk_budget(monkeypatch):
    import src.core.docx.docx_translation_adapter as module

    _RecordingChunker.created_with = []
    adapter = DocxTranslationAdapter()
    monkeypatch.setattr(module, "HtmlChunker", _RecordingChunker)

    chunks = adapter.create_chunks("document", {}, 137, None)

    assert _RecordingChunker.created_with == [137]
    assert chunks[0]["max_tokens"] == 137


def test_epub_adapter_honors_explicit_job_chunk_budget(monkeypatch):
    import src.core.epub.html_chunker as chunker_module

    _RecordingChunker.created_with = []
    adapter = EpubTranslationAdapter()
    monkeypatch.setattr(chunker_module, "HtmlChunker", _RecordingChunker)

    chunks = adapter.create_chunks("document", {}, 163, None)

    assert _RecordingChunker.created_with == [163]
    assert chunks[0]["max_tokens"] == 163


def test_shared_xhtml_chunker_honors_explicit_budget(monkeypatch):
    import src.core.epub.xhtml_translator as module

    _RecordingChunker.created_with = []
    monkeypatch.setattr(module, "HtmlChunker", _RecordingChunker)

    chunks = module._create_chunks(
        "document",
        {},
        211,
        container=TranslationContainer(),
    )

    assert _RecordingChunker.created_with == [211]
    assert chunks[0]["max_tokens"] == 211

@pytest.mark.asyncio
async def test_epub_plain_text_forwards_continuation_base_id(monkeypatch):
    pipeline = AsyncMock(return_value=(["Translated paragraph"], {}, False))
    monkeypatch.setattr(
        "src.core.common.plain_text_pipeline.translate_paragraphs_plain", pipeline
    )
    root = etree.fromstring(b"<html><body><p>Original paragraph</p></body></html>")

    success, _ = await EpubTranslationAdapter().translate_content(
        raw_content=root,
        structure_map={},
        context={},
        source_language="English",
        target_language="French",
        model_name="test-model",
        llm_client=None,
        max_tokens_per_chunk=100,
        prompt_options={"plain_text_mode": True},
        continuation_base_id="continued-chapter",
    )

    assert success
    assert pipeline.await_args.kwargs["continuation_base_id"] == "continued-chapter"
    assert root.find(".//p").text == "Translated paragraph"
