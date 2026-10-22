from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_epub_translation_propagates_failure(monkeypatch, tmp_path):
    from src.core.adapters.translate_file import translate_file
    import src.core.epub.translator as epub_translator

    input_path = tmp_path / "book.epub"
    input_path.write_bytes(b"not-needed-by-mocked-translator")
    mocked_translate = AsyncMock(return_value=False)
    monkeypatch.setattr(
        epub_translator,
        "translate_epub_file",
        mocked_translate,
    )

    success = await translate_file(
        input_filepath=str(input_path),
        output_filepath=str(tmp_path / "translated.epub"),
        source_language="Korean",
        target_language="English",
        model_name="gemini-test",
        llm_provider="gemini",
        checkpoint_manager=object(),
        translation_id="job",
        gemini_api_key="test-placeholder",
    )

    assert success is False
    mocked_translate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", ["txt", "srt", "docx"])
async def test_translation_forwards_nim_key(monkeypatch, tmp_path, extension):
    from src.core.adapters.generic_translator import GenericTranslator
    from src.core.adapters.translate_file import translate_file

    translate = AsyncMock(return_value=True)
    factory = Mock()
    if extension == "docx":
        monkeypatch.setattr("src.core.llm_client.LLMClient", factory)
        monkeypatch.setattr("src.core.docx.translator.translate_docx_file", AsyncMock(return_value={"success": True}))
    else:
        monkeypatch.setattr(GenericTranslator, "translate", translate)
    input_path = tmp_path / f"book.{extension}"
    input_path.write_text("Content is not read by the mocked translator.")

    success = await translate_file(
        input_filepath=str(input_path),
        output_filepath=str(tmp_path / f"translated.{extension}"),
        source_language="English",
        target_language="Korean",
        model_name="test-model",
        llm_provider="nim",
        checkpoint_manager=object(),
        translation_id="job",
        nim_api_key="YOUR_API_KEY_HERE",
    )

    assert success is True
    forwarded = factory.call_args if extension == "docx" else translate.call_args
    assert forwarded.kwargs["nim_api_key"] == "YOUR_API_KEY_HERE"
