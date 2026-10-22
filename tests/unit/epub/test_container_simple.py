def test_import_config():
    """Test that TranslationConfig can be imported."""
    from src.config import MAX_TOKENS_PER_CHUNK
    from src.core.epub.container import TranslationConfig

    config = TranslationConfig()
    assert config.max_tokens_per_chunk == MAX_TOKENS_PER_CHUNK
