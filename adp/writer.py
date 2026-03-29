"""File writer — writes assembled output files to disk."""
from __future__ import annotations

from pathlib import Path


def write_output_files(
    files: dict[str, str],
    output_dir: str,
) -> list[tuple[str, int]]:
    """
    Write all files to output_dir. Create directory tree as needed.

    Raises IOError if any file is written as 0 bytes (indicates silent failure).
    Returns list of (filename, byte_count) for TUI display.
    """
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)

    written: list[tuple[str, int]] = []
    for filename, content in files.items():
        path = base / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        size = path.stat().st_size
        if size == 0:
            raise IOError(
                f"File '{filename}' was written but is 0 bytes — "
                "this indicates the assembler returned empty content."
            )
        written.append((filename, size))

    return written
