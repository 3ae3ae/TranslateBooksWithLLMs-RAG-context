"""
File utilities for translation operations
"""
import re
from pathlib import Path


PARTIAL_PREFIX = "[partial] "
# Accept both the current `[partial] ` form and the legacy `[partial NN%] ` form
# so cleanup also catches files left behind by older versions.
_PARTIAL_RE = re.compile(r'^\[partial(?:\s+\d+%)?\]\s+')


def get_partial_output_path(output_path):
    """Return the path with a `[partial] ` prefix on the basename, used to mark
    an interrupted EPUB output so it cannot be confused with a completed file."""
    p = Path(output_path)
    base = _PARTIAL_RE.sub('', p.name)
    return str(p.parent / f"{PARTIAL_PREFIX}{base}")


def find_partial_output_paths(output_path):
    """Return all sibling files in the same directory that match the partial
    naming convention for ``output_path`` (current and legacy formats)."""
    p = Path(output_path)
    parent = p.parent if str(p.parent) else Path('.')
    if not parent.exists():
        return []
    target = _PARTIAL_RE.sub('', p.name)
    pattern = re.compile(r'^\[partial(?:\s+\d+%)?\]\s+' + re.escape(target) + r'$')
    return [str(entry) for entry in parent.iterdir()
            if entry.is_file() and pattern.match(entry.name)]


def get_unique_output_path(output_path):
    """
    Generate a unique output path by adding a number suffix if the file already exists.

    Args:
        output_path (str): Desired output path

    Returns:
        str: Unique output path (original or with numeric suffix)

    Examples:
        book.epub -> book.epub (if doesn't exist)
        book.epub -> book (1).epub (if book.epub exists)
        book.epub -> book (2).epub (if book.epub and book (1).epub exist)
    """
    path = Path(output_path)

    # If the file doesn't exist, return the original path
    if not path.exists():
        return output_path

    # Extract components
    parent = path.parent
    stem = path.stem  # filename without extension
    suffix = path.suffix  # .epub, .txt, .srt, etc.

    # Try incrementing numbers until we find a free filename
    counter = 1
    while True:
        new_stem = f"{stem} ({counter})"
        new_path = parent / f"{new_stem}{suffix}"

        if not new_path.exists():
            return str(new_path)

        counter += 1

        # Safety check to avoid infinite loops (highly unlikely)
        if counter > 9999:
            raise RuntimeError(f"Could not find unique filename after 9999 attempts for: {output_path}")
