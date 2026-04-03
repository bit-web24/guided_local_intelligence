"""All visual constants for the ADP TUI.

No colors, icons, or style strings are hardcoded anywhere else.
All visual changes go here.
"""

# ---------------------------------------------------------------------------
# Status icons
# ---------------------------------------------------------------------------
ICON_PENDING = "○"
ICON_RUNNING = "▶"
ICON_DONE = "✓"
ICON_FAILED = "✗"
ICON_SKIPPED = "–"
ICON_PARALLEL = "⟳"   # shown beside group label when multiple tasks run together
ICON_APP = "⬡"

# ---------------------------------------------------------------------------
# Rich style strings
# ---------------------------------------------------------------------------
COLOR_HEADER = "bold cyan"
COLOR_PENDING = "dim white"
COLOR_RUNNING = "bold yellow"
COLOR_DONE = "bold green"
COLOR_FAILED = "bold red"
COLOR_SKIPPED = "dim red"
COLOR_ANCHOR = "bold magenta"       # anchor word in prompt display
COLOR_INJECT = "bold blue"          # injected {placeholder} sections
COLOR_EXAMPLE = "dim cyan"          # few-shot example blocks
COLOR_STREAM = "white"              # live model output
COLOR_BORDER = "bright_black"
COLOR_FOOTER = "dim white"
COLOR_CLOUD = "bold cyan"
COLOR_LOCAL = "bold green"
COLOR_FILE = "bold cyan"
COLOR_SIZE = "dim white"
COLOR_ERROR = "bold red"
COLOR_STAGE = "bold magenta"
COLOR_TITLE = "bold white"

# ---------------------------------------------------------------------------
# Panel/layout
# ---------------------------------------------------------------------------
PANEL_BORDER = "rounded"    # rich panel box style
APP_TITLE = "⬡ Guided Local Intelligence"
APP_SUBTITLE = ""

# ---------------------------------------------------------------------------
# Stage labels (shown in header)
# ---------------------------------------------------------------------------
STAGE_LABELS = {
    "IDLE":        "Idle",
    "RESUMING":    "Resuming run…",
    "DECOMPOSING": "Decomposing prompt…",
    "EXECUTING":   "Executing tasks…",
    "REPLANNING":  "Replanning run…",
    "ASSEMBLING":  "Assembling files…",
    "WRITING":     "Writing to disk…",
    "FINAL_VERIFY":"Verifying written files…",
    "PROMPT_VERIFY":"Checking against prompt…",
    "DONE":        "Complete ✓",
    "ERROR":       "Error ✗",
}
