"""ADP configuration — all settings from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Models — both served via Ollama
# ---------------------------------------------------------------------------
CLOUD_MODEL = os.getenv("CLOUD_MODEL", "gpt-oss:120b-cloud")   # large: decompose + assemble
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "qwen2.5-coder:7b")      # small: execute micro-tasks
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
LOCAL_TEMPERATURE = 0.0     # always 0.0 for local — determinism is mandatory
CLOUD_TEMPERATURE = 0.2     # slight creativity for decomposition only
LOCAL_TIMEOUT = 120         # seconds per local model call
CLOUD_TIMEOUT = 180         # seconds per cloud model call (larger model, bigger output)
MAX_PARALLEL = 6            # max concurrent local model calls

# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------
HISTORY_FILE = os.path.expanduser("~/.adp_history")
MAX_HISTORY = 500

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
DEFAULT_OUTPUT_DIR = "./adp_output"
