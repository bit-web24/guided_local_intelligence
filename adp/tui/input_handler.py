"""prompt_toolkit input with persistent history."""
from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from adp.config import HISTORY_FILE


def get_user_input(prompt_label: str = "❯", output_dir_hint: str = "") -> str | None:
    """
    Display styled interactive input prompt.

    Returns the entered text, or None if the user pressed ctrl+c or ctrl+d.

    Features:
    - Arrow keys (↑↓) navigate prompt history (persisted to HISTORY_FILE)
    - ctrl+c / ctrl+d returns None (caller should exit or loop)
    - Wraps long lines
    """
    session: PromptSession = PromptSession(
        history=FileHistory(HISTORY_FILE),
        style=Style.from_dict({
            "prompt": "bold cyan",
            "":       "white",
        }),
        wrap_lines=True,
        multiline=False,
    )

    hint = f"  output → {output_dir_hint}\n" if output_dir_hint else ""
    try:
        return session.prompt(f"{hint}  {prompt_label} ")
    except (KeyboardInterrupt, EOFError):
        return None


def get_user_prompt(output_dir_hint: str = "") -> str | None:
    """Backwards-compatible wrapper for the main prompt entry."""
    return get_user_input(output_dir_hint=output_dir_hint)
