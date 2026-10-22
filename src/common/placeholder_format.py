"""
Centralized placeholder format detection and manipulation.

This module provides a unified interface for working with placeholders,
eliminating duplication across the codebase.
"""
import re
from typing import Optional

from src.config import (
    PLACEHOLDER_PREFIX,
    PLACEHOLDER_SUFFIX,
    PLACEHOLDER_PATTERN,
)


class PlaceholderFormat:
    """
    Encapsulates placeholder format detection and manipulation.

    This class centralizes all placeholder-related operations:
    - Format detection from config
    - Placeholder creation
    - Index extraction from placeholders
    - Pattern matching

    """

    def __init__(self, prefix: str, suffix: str, pattern: str):
        """
        Initialize placeholder format.

        Args:
            prefix: Placeholder prefix (e.g., "[id")
            suffix: Placeholder suffix (e.g., "]")
            pattern: Regex pattern (e.g., ``\\[id(\\d+)\\]``)
        """
        self.prefix = prefix
        self.suffix = suffix
        self.pattern = pattern
        self._compiled_pattern = re.compile(pattern)

    @classmethod
    def from_config(cls) -> 'PlaceholderFormat':
        """
        Create PlaceholderFormat from global config constants.

        Returns:
            PlaceholderFormat instance with default format [idN]

        Example:
            >>> fmt = PlaceholderFormat.from_config()
            >>> fmt.prefix
            '[id'
        """
        return cls(PLACEHOLDER_PREFIX, PLACEHOLDER_SUFFIX, PLACEHOLDER_PATTERN)

    def create(self, index: int) -> str:
        """
        Create a placeholder for the given index.

        Args:
            index: Placeholder index (e.g., 0, 1, 2, ...)

        Returns:
            Placeholder string

        Example:
            >>> fmt = PlaceholderFormat.from_config()
            >>> fmt.create(42)
            '[id42]'
        """
        return f"{self.prefix}{index}{self.suffix}"

    def parse(self, placeholder: str) -> Optional[int]:
        """
        Extract index from a placeholder string.

        Args:
            placeholder: Placeholder string (e.g., "[id42]")

        Returns:
            Index as integer, or None if invalid

        Example:
            >>> fmt = PlaceholderFormat.from_config()
            >>> fmt.parse('[id42]')
            42
            >>> fmt.parse('invalid')
            None
        """
        match = self._compiled_pattern.fullmatch(placeholder)
        if match:
            return int(match.group(1))
        return None

    def find_all(self, text: str) -> list:
        """
        Find all placeholders in text.

        Args:
            text: Text to search

        Returns:
            List of (start_pos, end_pos, placeholder_text, index) tuples

        Example:
            >>> fmt = PlaceholderFormat.from_config()
            >>> fmt.find_all("[id0]Hello[id1]")
            [(0, 5, '[id0]', 0), (10, 15, '[id1]', 1)]
        """
        results = []
        for match in self._compiled_pattern.finditer(text):
            results.append((
                match.start(),
                match.end(),
                match.group(0),
                int(match.group(1))
            ))
        return results

    def remove_all(self, text: str) -> str:
        """
        Remove all placeholders from text.

        Args:
            text: Text containing placeholders

        Returns:
            Text with placeholders removed

        Example:
            >>> fmt = PlaceholderFormat.from_config()
            >>> fmt.remove_all("[id0]Hello[id1] world[id2]")
            'Hello world'
        """
        return self._compiled_pattern.sub('', text)

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"PlaceholderFormat(prefix={self.prefix!r}, suffix={self.suffix!r})"

    def __eq__(self, other) -> bool:
        """Equality comparison."""
        if not isinstance(other, PlaceholderFormat):
            return False
        return (self.prefix == other.prefix and
                self.suffix == other.suffix and
                self.pattern == other.pattern)
