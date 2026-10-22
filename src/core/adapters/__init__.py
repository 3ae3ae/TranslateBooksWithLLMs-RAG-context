"""
Adapter pattern implementation for generic file translation.

This module provides a unified interface for translating different file formats
(TXT, SRT, EPUB, PDF) using the adapter pattern. Each format implements the
FormatAdapter interface to handle format-specific operations.

"""

from .translation_unit import TranslationUnit
from .format_adapter import FormatAdapter
from .generic_translator import GenericTranslator
from .txt_adapter import TxtAdapter
from .srt_adapter import SrtAdapter
from .epub_adapter import EpubAdapter

# Unified translation entry point (Phase 6)
from .translate_file import translate_file, build_translated_output

# Refine-only entry point
from .refine_file import refine_file

from .exceptions import TranslationError, FileFormatError, UnsupportedFormatError

__all__ = [
    # Core adapter components
    'TranslationUnit',
    'FormatAdapter',
    'GenericTranslator',
    'TxtAdapter',
    'SrtAdapter',
    'EpubAdapter',

    # Unified translation entry point (Phase 6)
    'translate_file',
    'build_translated_output',

    # Refine-only entry point
    'refine_file',

    'TranslationError',
    'FileFormatError',
    'UnsupportedFormatError',
]
