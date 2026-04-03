"""ADP configuration — runtime settings and model selection."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ModelConfig:
    """Runtime-resolved model names for the pipeline."""

    cloud: str
    local_coder: str
    local_general: str


# ---------------------------------------------------------------------------
# Models — both served via Ollama
# ---------------------------------------------------------------------------
DEFAULT_CLOUD_MODEL = "gpt-oss:120b-cloud"      # large: decompose + assemble
DEFAULT_LOCAL_CODER_MODEL = "qwen2.5-coder:1.5b"  # small: logic/coding tasks
DEFAULT_LOCAL_GENERAL_MODEL = "qwen2.5:1.5b"      # small: text/extraction tasks
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


def get_model_config() -> ModelConfig:
    """Resolve the active model set from environment variables at runtime."""
    return ModelConfig(
        cloud=os.getenv("CLOUD_MODEL", DEFAULT_CLOUD_MODEL),
        local_coder=os.getenv("LOCAL_CODER_MODEL", DEFAULT_LOCAL_CODER_MODEL),
        local_general=os.getenv("LOCAL_GENERAL_MODEL", DEFAULT_LOCAL_GENERAL_MODEL),
    )


def set_model_config(
    *,
    cloud: str | None = None,
    local_coder: str | None = None,
    local_general: str | None = None,
    local: str | None = None,
) -> ModelConfig:
    """Apply model overrides globally for the current process."""
    if local is not None:
        local_coder = local_coder or local
        local_general = local_general or local

    if cloud is not None:
        os.environ["CLOUD_MODEL"] = cloud
    if local_coder is not None:
        os.environ["LOCAL_CODER_MODEL"] = local_coder
    if local_general is not None:
        os.environ["LOCAL_GENERAL_MODEL"] = local_general

    return get_model_config()

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
DECOMPOSITION_MAX_RETRIES = int(os.getenv("DECOMPOSITION_MAX_RETRIES", "6"))
MAX_REPLANS = int(os.getenv("MAX_REPLANS", "2"))
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
RUN_STATE_DIRNAME = ".gli_runs"

# ---------------------------------------------------------------------------
# Reflection (per-task semantic validation between EXECUTE and ASSEMBLE)
# ---------------------------------------------------------------------------
REFLECT_ENABLED = os.getenv("REFLECT_ENABLED", "true").lower() in ("true", "1", "yes")
# Tasks with Code anchor + implementation verbs + >= this many deps → cloud reflection
REFLECT_CLOUD_DEP_THRESHOLD = int(os.getenv("REFLECT_CLOUD_DEP_THRESHOLD", "2"))

# ---------------------------------------------------------------------------
# Retry strategy
# ---------------------------------------------------------------------------
RETRY_TEMPERATURE_STEP = float(os.getenv("RETRY_TEMPERATURE_STEP", "0.1"))
RETRY_INJECT_ERROR = os.getenv("RETRY_INJECT_ERROR", "true").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# MCP (Model Context Protocol)
# ---------------------------------------------------------------------------
# Maximum characters of a tool result injected into a local model's context.
# Prevents context window overflow for tools like read_file on large files.
MCP_MAX_TOOL_RESULT_CHARS = int(os.getenv("MCP_MAX_TOOL_RESULT_CHARS", "3000"))

# Path to the MCP server configuration TOML file.
# Falls back to ~/.config/adp/mcp_servers.toml if project-local file not found.
MCP_CONFIG_PATHS = [
    os.path.join(os.getcwd(), "mcp_servers.toml"),
    os.path.expanduser("~/.config/adp/mcp_servers.toml"),
]
