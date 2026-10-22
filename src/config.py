"""
Centralized configuration class
"""
import os
import sys
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Setup debug logger for configuration
_config_logger = logging.getLogger('config')

# Check for DEBUG_MODE early (before .env is loaded, check environment)
_debug_mode = os.getenv('DEBUG_MODE', 'false').lower() == 'true'
if _debug_mode:
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _config_logger.setLevel(logging.DEBUG)
    _config_logger.debug("🔍 DEBUG_MODE enabled - verbose logging active")

def resolve_tbl_home() -> Path:
    """Resolve user data independently of the launch directory."""
    if os.getenv('TBL_HOME'):
        path = Path(os.environ['TBL_HOME']).expanduser()
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library' / 'Application Support' / 'TBL'
    elif sys.platform == 'win32':
        path = Path(os.getenv('APPDATA') or Path.home() / 'AppData' / 'Roaming') / 'TBL'
    else:
        path = Path(os.getenv('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'tbl'
    # Relative overrides belong to the user's home, never the launch directory.
    return (Path.home() / path).resolve()


TBL_HOME = resolve_tbl_home()
NOVEL_CONTEXTS_DIR = TBL_HOME / 'notes'
CUSTOM_INSTRUCTIONS_DIR = TBL_HOME / 'styles'
DATA_DIR = TBL_HOME / 'data'
UPLOADS_DIR = DATA_DIR / 'uploads'
INCOMING_DIR = DATA_DIR / 'incoming'
THUMBNAILS_DIR = DATA_DIR / 'thumbnails'

# Process environment variables take precedence over TBL_HOME/.env.
_env_file = TBL_HOME / '.env'
_dotenv_result = load_dotenv(_env_file)
if _debug_mode:
    _config_logger.debug(f"📁 load_dotenv() returned: {_dotenv_result}")
    _config_logger.debug(f"📁 Loaded .env from: {_env_file.absolute()}")

# Format: (attribute_name, env_var_name, default_value)
_RELOADABLE_ENV_SETTINGS = (
    ('OLLAMA_API_ENDPOINT', 'OLLAMA_API_ENDPOINT', 'http://localhost:11434/api/generate'),
    ('OPENAI_API_ENDPOINT', 'OPENAI_API_ENDPOINT', 'https://api.openai.com/v1/chat/completions'),
    ('DEFAULT_MODEL',       'DEFAULT_MODEL',       'qwen3:14b'),
    ('LLM_PROVIDER',        'LLM_PROVIDER',        'ollama'),
    ('GEMINI_API_KEY',      'GEMINI_API_KEY',      ''),
    ('GEMINI_MODEL',        'GEMINI_MODEL',        'gemini-2.0-flash'),
    ('OPENAI_API_KEY',      'OPENAI_API_KEY',      ''),
    ('OPENROUTER_API_KEY',  'OPENROUTER_API_KEY',  ''),
    ('OPENROUTER_MODEL',    'OPENROUTER_MODEL',    'anthropic/claude-sonnet-4'),
    ('MISTRAL_API_KEY',     'MISTRAL_API_KEY',     ''),
    ('MISTRAL_MODEL',       'MISTRAL_MODEL',       'mistral-large-latest'),
    ('DEEPSEEK_API_KEY',    'DEEPSEEK_API_KEY',    ''),
    ('DEEPSEEK_MODEL',      'DEEPSEEK_MODEL',      'deepseek-v4-pro'),
    ('POE_API_KEY',         'POE_API_KEY',         ''),
    ('POE_MODEL',           'POE_MODEL',           'Claude-Sonnet-4'),
    ('NIM_API_KEY',         'NIM_API_KEY',         ''),
    ('NIM_MODEL',           'NIM_MODEL',           'meta/llama-3.1-8b-instruct'),
    ('OUTPUT_FILENAME_PATTERN', 'OUTPUT_FILENAME_PATTERN', '{originalName} ({targetLang}).{ext}'),
    ('DISABLE_AUTO_PAUSE',   'DISABLE_AUTO_PAUSE',   'false'),
    ('PARALLEL_TRANSLATIONS', 'PARALLEL_TRANSLATIONS', '1'),
    ('MAX_TOKENS_PER_CHUNK', 'MAX_TOKENS_PER_CHUNK', '450'),
    # Novel context prompt rendering. The full context file remains durable;
    # this limits only the selected context block injected into each prompt.
    ('NOVEL_CONTEXT_PROMPT_MAX_TOKENS', 'NOVEL_CONTEXT_PROMPT_MAX_TOKENS', '1800'),
    # Auto-update cadence for source-derived novel context. 1 preserves the
    # existing behavior (analyze every chunk); higher values analyze chunk 1,
    # then every Nth chunk while translation uses the latest available context.
    ('NOVEL_CONTEXT_UPDATE_INTERVAL', 'NOVEL_CONTEXT_UPDATE_INTERVAL', '1'),
    # Bounded previous-source tail injected only into context-analysis prompts.
    # This lets the analyzer resolve facts that span nearby chunk boundaries.
    ('NOVEL_CONTEXT_SOURCE_MEMORY_CHARS', 'NOVEL_CONTEXT_SOURCE_MEMORY_CHARS', '6000'),
    # Bypasses the deterministic validation layer to trust LLM context updates directly.
    ('BYPASS_CONTEXT_GATING', 'BYPASS_CONTEXT_GATING', 'true'),
    # LLM consolidation pass interval: after every Nth context chunk update, an
    # LLM call rewrites the Characters section to remove duplicate / redundant
    # descriptions that the deterministic merge layer missed. 0 = disabled.
    ('NOVEL_CONTEXT_CONSOLIDATION_INTERVAL', 'NOVEL_CONTEXT_CONSOLIDATION_INTERVAL', '5'),
)


_BOOL_ATTRS = {
    'BYPASS_CONTEXT_GATING'
}
_INT_ATTRS = {
    'PARALLEL_TRANSLATIONS',
    'MAX_TOKENS_PER_CHUNK',
    'NOVEL_CONTEXT_PROMPT_MAX_TOKENS',
    'NOVEL_CONTEXT_UPDATE_INTERVAL',
    'NOVEL_CONTEXT_SOURCE_MEMORY_CHARS',
    'NOVEL_CONTEXT_CONSOLIDATION_INTERVAL',
}


def _apply_reloadable_env_settings():
    g = globals()
    for attr, env_var, default in _RELOADABLE_ENV_SETTINGS:
        raw = os.getenv(env_var, default)
        if attr in _BOOL_ATTRS:
            g[attr] = str(raw).strip().lower() == 'true'
        elif attr in _INT_ATTRS:
            try:
                g[attr] = int(raw)
            except (TypeError, ValueError):
                g[attr] = int(default)
        else:
            g[attr] = raw
    # Legacy alias: API_ENDPOINT falls back to OLLAMA_API_ENDPOINT
    g['API_ENDPOINT'] = os.getenv('API_ENDPOINT', g['OLLAMA_API_ENDPOINT'])


_apply_reloadable_env_settings()

PORT = int(os.getenv('PORT', '5000'))
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '300'))
OLLAMA_NUM_CTX = int(os.getenv('OLLAMA_NUM_CTX', '4096'))

# =============================================================================
# PARALLEL TRANSLATION CONFIGURATION
# =============================================================================
# Number of chunks translated concurrently. Defaults to 1 (fully sequential,
# byte-for-byte identical to the legacy behavior, including cross-chunk
# translation context chaining). Values > 1 dispatch that many LLM requests at
# once in ordered windows; the per-chunk "previous translation" context is
# dropped in that mode (source context_before/after is still used).
#
# Only cloud providers benefit: a single local Ollama instance serializes
# requests anyway, so resolve_parallel_workers() forces local providers back to
# 1 regardless of this setting. See is_local_provider().

# Upper bound for the parallel worker count, both as a sanity cap and to keep
# the request settings within a reasonable range. Cloud rate limits make very
# high values counter-productive.
MAX_PARALLEL_TRANSLATIONS = int(os.getenv('MAX_PARALLEL_TRANSLATIONS', '16'))

# Providers that run on the user's own machine and serialize requests through a
# single model instance. Parallel dispatch gives them no speedup and can
# saturate the GPU, so the concurrency control is disabled for them.
LOCAL_PROVIDERS = {'ollama'}


def is_local_provider(provider: Optional[str]) -> bool:
    """Return True for providers that run locally and serialize requests."""
    return (provider or '').strip().lower() in LOCAL_PROVIDERS


def resolve_parallel_workers(provider: Optional[str], requested: Optional[int] = None) -> int:
    """Resolve the effective number of concurrent translation workers.

    Local providers are always forced to 1 (no benefit, risk of saturation).
    Cloud providers honor `requested` (falling back to PARALLEL_TRANSLATIONS),
    clamped to the [1, MAX_PARALLEL_TRANSLATIONS] window.
    """
    if is_local_provider(provider):
        return 1
    if requested is None:
        requested = PARALLEL_TRANSLATIONS
    try:
        requested = int(requested)
    except (TypeError, ValueError):
        requested = 1
    return max(1, min(MAX_PARALLEL_TRANSLATIONS, requested))


# =============================================================================
# THINKING MODEL CONFIGURATION
# =============================================================================
# Models are classified based on their behavior with the 'think' parameter:
#
# 1. UNCONTROLLABLE: Models that think even with think=false (need WARNING)
# 2. CONTROLLABLE: Models that respect think=false (no warning needed)
# 3. STANDARD: Models that don't think at all (no think param needed)
#
# Auto-detection at runtime will classify models by testing with think=true/false

# Models that CANNOT be prevented from thinking - show WARNING to user
# These models either ignore think=false or don't support the param but still think
UNCONTROLLABLE_THINKING_MODELS = [
    "qwen3:30b",      # Qwen3 30B ignores think=false (tested)
    "qwen3-vl",       # Qwen3 Vision models ignore think=false
    "phi4-reasoning", # Phi4 reasoning doesn't support think param but always thinks
    "deepseek-r1",    # DeepSeek R1 reasoning model
    "qwq",            # Qwen QwQ reasoning model
    "marco-o1",       # Alibaba reasoning model
    "exaone-deep",    # LG reasoning model
]

# Models that respect think=false - controllable, no warning needed
CONTROLLABLE_THINKING_MODELS = [
    "qwen3:8b",       # Respects think=false (tested)
    "qwen3:14b",      # Respects think=false (tested)
    "qwen3:4b",       # Smaller Qwen3 models likely controllable
    "qwen3:1.7b",     # Smaller Qwen3 models likely controllable
    "qwen3:0.6b",     # Smaller Qwen3 models likely controllable
    "qwen3.5:9b",     # Qwen3.5 tested
    "qwen3.5:35b",    # Qwen3.5 large - controllable
]

# Legacy alias for backward compatibility
THINKING_MODELS = UNCONTROLLABLE_THINKING_MODELS + CONTROLLABLE_THINKING_MODELS
_max_retries_legacy = os.getenv('MAX_RETRIES')
if _max_retries_legacy and not os.getenv('MAX_TRANSLATION_ATTEMPTS'):
    print(
        f"⚠️  MAX_RETRIES is not a recognized setting and was renamed to "
        f"MAX_TRANSLATION_ATTEMPTS. Accepting MAX_RETRIES={_max_retries_legacy} "
        f"for backward compatibility; please rename it in your .env."
    )
    try:
        MAX_TRANSLATION_ATTEMPTS = int(_max_retries_legacy)
    except ValueError:
        MAX_TRANSLATION_ATTEMPTS = 2
else:
    MAX_TRANSLATION_ATTEMPTS = int(os.getenv('MAX_TRANSLATION_ATTEMPTS', '2'))

# Sampling temperature applied to cloud LLM providers (gemini, deepseek, mistral,
# poe). Lower values favor consistent translations; higher values produce more
# variation. Ollama is unaffected because it uses its own server-side defaults.
TEMPERATURE = float(os.getenv('TEMPERATURE', '0.3'))

# Gemini safety filter threshold applied to all four harm categories
# (HARASSMENT, HATE_SPEECH, SEXUALLY_EXPLICIT, DANGEROUS_CONTENT). Default is
# BLOCK_NONE because the tool is used to translate adult-themed novels where
# Gemini's default MEDIUM threshold silently strips chunks and produces empty
# responses. Users who want the default filter can set BLOCK_MEDIUM_AND_ABOVE.
# Valid values: BLOCK_NONE, BLOCK_ONLY_HIGH, BLOCK_MEDIUM_AND_ABOVE,
# BLOCK_LOW_AND_ABOVE, HARM_BLOCK_THRESHOLD_UNSPECIFIED.
GEMINI_SAFETY_THRESHOLD = os.getenv('GEMINI_SAFETY_THRESHOLD', 'BLOCK_NONE')

# Auto-pause on HTTP 429 rate limit
# When True (default): translation pauses after retries are exhausted; user resumes manually.
# When False: translation auto-resumes from the last checkpoint after waiting `retry_after`
# seconds (or RATE_LIMIT_AUTO_RESUME_DELAY if no Retry-After header).
AUTO_PAUSE_ON_RATE_LIMIT = os.getenv('AUTO_PAUSE_ON_RATE_LIMIT', 'true').lower() == 'true'
RATE_LIMIT_AUTO_RESUME_DELAY = int(os.getenv('RATE_LIMIT_AUTO_RESUME_DELAY', '60'))

# Adaptive context optimization settings
# The new strategy starts at a small context and grows as needed based on actual token usage
AUTO_ADJUST_CONTEXT = os.getenv("AUTO_ADJUST_CONTEXT", "true").lower() == "true"
ADAPTIVE_CONTEXT_INITIAL = int(os.getenv("ADAPTIVE_CONTEXT_INITIAL", "2048"))  # Starting context size
ADAPTIVE_CONTEXT_INITIAL_THINKING = int(os.getenv("ADAPTIVE_CONTEXT_INITIAL_THINKING", "6144"))  # Starting context for thinking models (need more space for reasoning)
ADAPTIVE_CONTEXT_STEP = int(os.getenv("ADAPTIVE_CONTEXT_STEP", "2048"))  # Step size for increases
ADAPTIVE_CONTEXT_STABILITY_WINDOW = int(os.getenv("ADAPTIVE_CONTEXT_STABILITY_WINDOW", "5"))  # Chunks to track before reducing

# Repetition loop detection settings
# Thinking models may have natural repetitions in their reasoning, so we use higher thresholds
REPETITION_MIN_PHRASE_LENGTH = int(os.getenv("REPETITION_MIN_PHRASE_LENGTH", "5"))  # Min phrase length to detect
REPETITION_MIN_COUNT = int(os.getenv("REPETITION_MIN_COUNT", "10"))  # Min repetitions for standard models
REPETITION_MIN_COUNT_THINKING = int(os.getenv("REPETITION_MIN_COUNT_THINKING", "15"))  # Min repetitions for thinking models (more lenient)
REPETITION_MIN_COUNT_STREAMING = int(os.getenv("REPETITION_MIN_COUNT_STREAMING", "12"))  # Min repetitions during streaming (early detection)

# Token-based chunking configuration
# All file types use token-based chunking with tiktoken for consistent chunk sizes
MAX_TOKENS_PER_CHUNK = int(os.getenv('MAX_TOKENS_PER_CHUNK', '450'))
SOFT_LIMIT_RATIO = float(os.getenv('SOFT_LIMIT_RATIO', '0.8'))

# LLM Provider configuration
OPENROUTER_API_ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
MISTRAL_API_ENDPOINT = os.getenv('MISTRAL_API_ENDPOINT', 'https://api.mistral.ai/v1/chat/completions')
DEEPSEEK_API_ENDPOINT = os.getenv('DEEPSEEK_API_ENDPOINT', 'https://api.deepseek.com/chat/completions')
# DeepSeek V4 models (deepseek-v4-flash, deepseek-v4-pro) enable thinking by default,
# wasting ~10-25x tokens on translation. Set to 'false' to keep thinking enabled.
DEEPSEEK_DISABLE_THINKING = os.getenv('DEEPSEEK_DISABLE_THINKING', 'true').lower() == 'true'
POE_API_ENDPOINT = os.getenv('POE_API_ENDPOINT', 'https://api.poe.com/v1/chat/completions')
NIM_API_ENDPOINT = os.getenv('NIM_API_ENDPOINT', 'https://integrate.api.nvidia.com/v1/chat/completions')

# SRT-specific configuration
# Single knob for both translate and refine: every SRT block sent to the
# LLM contains exactly SRT_LINES_PER_BLOCK subtitles (no char cap). Keeping
# block sizes predictable makes [N] marker accounting reliable across the
# whole file. Lower it for tiny models (e.g. 5 for 4B params), raise it
# for large-context models that handle long structured outputs well.
SRT_LINES_PER_BLOCK = int(os.getenv('SRT_LINES_PER_BLOCK', '10'))

# Retries when a translated unit fails the adapter's structural validation
# (e.g. an SRT block whose LLM response is missing [N] index markers).
# Each retry reinforces the prompt with the exact missing markers.
# Total attempts = 1 + this value. After exhaustion the unit keeps its
# best-effort content and is marked failed (job ends 'partial', retryable).
UNIT_VALIDATION_RETRIES = int(os.getenv('UNIT_VALIDATION_RETRIES', '2'))

# Default languages from environment (optional)
# Source language: Auto-detected from file content (langdetect)
# Target language: Auto-detected from browser language in UI
DEFAULT_SOURCE_LANGUAGE = os.getenv('DEFAULT_SOURCE_LANGUAGE', '')  # Empty = auto-detect
DEFAULT_TARGET_LANGUAGE = os.getenv('DEFAULT_TARGET_LANGUAGE', '')  # Empty = use browser language

# Relative output overrides are anchored to TBL_HOME as well.
OUTPUT_DIR = str((TBL_HOME / Path(os.getenv('OUTPUT_DIR', 'translations')).expanduser()).resolve())

# Output filename pattern
# Placeholders: {originalName}, {targetLang}, {sourceLang}, {model}, {date}, {datetime}, {ext}
# OUTPUT_FILENAME_PATTERN is loaded via _apply_reloadable_env_settings()

# Debug mode (reload after .env is loaded)
DEBUG_MODE = os.getenv('DEBUG_MODE', 'false').lower() == 'true'


# Log loaded configuration in debug mode
if DEBUG_MODE or _debug_mode:
    _config_logger.setLevel(logging.DEBUG)
    _config_logger.debug("="*60)
    _config_logger.debug("📋 LOADED CONFIGURATION VALUES:")
    _config_logger.debug("="*60)
    _config_logger.debug(f"   API_ENDPOINT: {API_ENDPOINT}")
    _config_logger.debug(f"   DEFAULT_MODEL: {DEFAULT_MODEL}")
    _config_logger.debug(f"   LLM_PROVIDER: {LLM_PROVIDER}")
    _config_logger.debug(f"   PORT: {PORT}")
    _config_logger.debug(f"   DEFAULT_SOURCE_LANGUAGE: {DEFAULT_SOURCE_LANGUAGE}")
    _config_logger.debug(f"   DEFAULT_TARGET_LANGUAGE: {DEFAULT_TARGET_LANGUAGE}")
    _config_logger.debug(f"   OLLAMA_NUM_CTX: {OLLAMA_NUM_CTX}")
    _config_logger.debug(f"   REQUEST_TIMEOUT: {REQUEST_TIMEOUT}")
    _config_logger.debug(f"   GEMINI_API_KEY: {'***' + GEMINI_API_KEY[-4:] if GEMINI_API_KEY else '(not set)'}")
    _config_logger.debug(f"   OPENAI_API_KEY: {'***' + OPENAI_API_KEY[-4:] if OPENAI_API_KEY else '(not set)'}")
    _config_logger.debug(f"   OPENROUTER_API_KEY: {'***' + OPENROUTER_API_KEY[-4:] if OPENROUTER_API_KEY else '(not set)'}")
    _config_logger.debug(f"   OPENROUTER_MODEL: {OPENROUTER_MODEL}")
    _config_logger.debug(f"   MISTRAL_API_KEY: {'***' + MISTRAL_API_KEY[-4:] if MISTRAL_API_KEY else '(not set)'}")
    _config_logger.debug(f"   MISTRAL_MODEL: {MISTRAL_MODEL}")
    _config_logger.debug(f"   DEEPSEEK_API_KEY: {'***' + DEEPSEEK_API_KEY[-4:] if DEEPSEEK_API_KEY else '(not set)'}")
    _config_logger.debug(f"   DEEPSEEK_MODEL: {DEEPSEEK_MODEL}")
    _config_logger.debug(f"   POE_API_KEY: {'***' + POE_API_KEY[-4:] if POE_API_KEY else '(not set)'}")
    _config_logger.debug(f"   POE_MODEL: {POE_MODEL}")
    _config_logger.debug("="*60)

# Translation tags - Improved for LLM clarity and reliability
TRANSLATE_TAG_IN = "<TRANSLATION>"
TRANSLATE_TAG_OUT = "</TRANSLATION>"
INPUT_TAG_IN = "<SOURCE_TEXT>"
INPUT_TAG_OUT = "</SOURCE_TEXT>"

# ============================================================================
# TAG PLACEHOLDER CONFIGURATION
# ============================================================================
# These placeholders are used to temporarily replace HTML/XML tags during
# translation. The LLM must preserve them exactly in its output.
#
# Unified format: [id0], [id1], [id2], ...
# - Semantic naming helps LLM understand these are identifiers
# - Compact format reduces token usage
# - Adjacent tags are grouped into single placeholders
# - Strict validation ensures placeholder integrity

# Single unified format
PLACEHOLDER_PREFIX = "[id"
"""Prefix for tag placeholders (e.g., [id in [id0])"""

PLACEHOLDER_SUFFIX = "]"
"""Suffix for tag placeholders (e.g., ] in [id0])"""

PLACEHOLDER_PATTERN = r'\[id(\d+)\]'
"""Regex pattern for placeholders (e.g., [id0])"""

# Maximum retries for placeholder validation before falling back to source text
MAX_PLACEHOLDER_RETRIES = 0
"""Number of retry attempts when placeholder validation fails"""


# =============================================================================
# TOKEN ALIGNMENT FALLBACK CONFIGURATION (Phase 2)
# =============================================================================
# When LLM fails to preserve placeholders correctly, use word-level alignment
# to reinsert them at semantically correct positions.

EPUB_TOKEN_ALIGNMENT_ENABLED = os.getenv('EPUB_TOKEN_ALIGNMENT_ENABLED', 'true').lower() == 'true'
"""Enable token alignment fallback for EPUB translation (Phase 2)"""

STRUCTURED_REFINEMENT_HIDE_PLACEHOLDERS = os.getenv(
    'STRUCTURED_REFINEMENT_HIDE_PLACEHOLDERS',
    os.getenv('EPUB_REFINEMENT_HIDE_PLACEHOLDERS', 'true'),
).lower() == 'true'
"""Hide structured-document placeholders during refinement and reinsert them deterministically."""


def create_placeholder(tag_num: int, prefix: str = None, suffix: str = None) -> str:
    """
    Create a placeholder string for a given tag number.

    Args:
        tag_num: Tag number
        prefix: Optional custom prefix (defaults to PLACEHOLDER_PREFIX)
        suffix: Optional custom suffix (defaults to PLACEHOLDER_SUFFIX)

    Returns:
        Placeholder string like [id0]
    """
    if prefix is None:
        prefix = PLACEHOLDER_PREFIX
    if suffix is None:
        suffix = PLACEHOLDER_SUFFIX
    return f"{prefix}{tag_num}{suffix}"


def create_example_placeholder(prefix: str = None, suffix: str = None) -> str:
    """
    Create an example placeholder for documentation/prompts.

    Args:
        prefix: Optional custom prefix
        suffix: Optional custom suffix

    Returns:
        Example placeholder like [id0]
    """
    return create_placeholder(0, prefix, suffix)


def detect_format_from_placeholder(sample_placeholder: str) -> str:
    """
    Returns the unified format name.

    Args:
        sample_placeholder: A sample placeholder (parameter kept for backward compatibility)

    Returns:
        Format name (always "id" for [idN] format)
    """
    return "id"


# Sentence terminators
SENTENCE_TERMINATORS = tuple(list(".!?") + ['."', '?"', '!"', '."', ".'", "?'", "!'", ":", ".)"])

# EPUB-specific configuration
NAMESPACES = {
    'opf': 'http://www.idpf.org/2007/opf',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'xhtml': 'http://www.w3.org/1999/xhtml',
    'epub': 'http://www.idpf.org/2007/ops'
}

# Model family context size defaults (shared across providers)
# Used as fallback when context size cannot be detected from the server
# NOTE: Order matters! More specific patterns (gpt-4) must come before generic ones (gpt)
MODEL_FAMILY_CONTEXT_DEFAULTS = {
    "gpt-4": 128000,  # Must come before "gpt"
    "gpt": 8192,
    "claude": 100000,
    "deepseek": 64000,  # DeepSeek V3 models have 64K context
    "mistral": 32000,  # Mistral small has 32K, large/medium have 128K
    "gemma": 8192,
    "qwen": 8192,
    "llama": 4096,
    "phi": 2048,
}
DEFAULT_CONTEXT_FALLBACK = 2048


def detect_placeholder_format_in_text(text: str) -> tuple:
    """
    Returns the unified placeholder format [idN].

    Args:
        text: Text (parameter kept for backward compatibility but unused)

    Returns:
        (prefix, suffix) tuple for [idN] format

    Example:
        >>> detect_placeholder_format_in_text("Hello [id0] world [id1]")
        ("[id", "]")
    """
    return PLACEHOLDER_PREFIX, PLACEHOLDER_SUFFIX
