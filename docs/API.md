# GLI API Documentation

This document describes the internal API and architecture of GLI (Guided Local Intelligence).

## Core Components

### Pipeline Stages

#### Decomposer (`adp.stages.decomposer`)

The decomposer takes a user prompt and creates a structured task plan.

```python
async def decompose(
    user_prompt: str,
    tool_registry: ToolRegistry,
    project_dir: str,
    on_retry: Callable[[str], None] | None = None,
) -> TaskPlan
```

**Key Components:**
- Uses the large model (`gpt-oss:120b-cloud`) for planning
- Creates atomic micro-tasks with dependencies
- Generates few-shot examples for each task
- Assigns MCP tools when available

**Output Structure:**
```python
@dataclass
class TaskPlan:
    tasks: list[MicroTask]
    final_output_keys: list[str]
    output_filenames: list[str]
    write_to_file: bool
```

#### Executor (`adp.stages.executor`)

The executor runs tasks in dependency order with context injection.

```python
async def execute_plan(
    plan: TaskPlan,
    on_task_start: Callable[[MicroTask], None] | None = None,
    on_task_done: Callable[[MicroTask], None] | None = None,
    on_task_failed: Callable[[MicroTask], None] | None = None,
    on_tool_start: Callable[[str], None] | None = None,
    on_tool_done: Callable[[str, Any], None] | None = None,
    mcp_manager: MCPClientManager | None = None,
    tool_registry: ToolRegistry | None = None,
    initial_context: ContextDict | None = None,
    on_group_complete: Callable[[TaskPlan, ContextDict], None] | None = None,
) -> ContextDict
```

**Key Features:**
- Sequential execution by default
- Context injection between tasks
- MCP tool execution before model calls
- Retry logic with error injection

#### Assembler (`adp.stages.assembler`)

The assembler combines task outputs into complete files.

```python
async def assemble(
    plan: TaskPlan,
    context: ContextDict,
    user_prompt: str,
) -> dict[str, str]
```

**Process:**
1. Validates all required outputs are present
2. Sends fragments and filenames to large model
3. Returns assembled file contents
4. Performs structural validation

### Data Models

#### MicroTask

Represents a single atomic task in the pipeline.

```python
@dataclass
class MicroTask:
    id: str                          # Unique task identifier
    description: str                 # Human-readable description
    system_prompt_template: str      # Template with {placeholders}
    input_text: str                  # Input for the model
    output_key: str                  # Key in context dict
    depends_on: list[str]            # Task dependencies
    anchor: AnchorType               # Output delimiter
    parallel_group: int              # Execution group
    model_type: str                  # "coder" or "general"
    mcp_tools: list[str]             # Tools to execute first
    mcp_tool_args: dict[str, dict]   # Tool argument overrides
    # Runtime state
    status: TaskStatus = PENDING
    output: str | None = None
    retries: int = 0
    error: str | None = None
```

#### TaskStatus

Enum representing task execution state.

```python
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
```

#### AnchorType

Delimiter type for task outputs.

```python
class AnchorType(Enum):
    JSON = "JSON:"
    CODE = "Code:"
    OUTPUT = "Output:"
    MARKDOWN = "Markdown:"
    TOML = "TOML:"
```

### Engine Components

#### Cloud Client (`adp.engine.cloud_client`)

Handles communication with large Ollama models.

```python
async def call_cloud_async(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
) -> str
```

#### Local Client (`adp.engine.local_client`)

Handles communication with small Ollama models.

```python
async def call_local_async(
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    temperature: float | None = None,
    timeout: int | None = None,
) -> str
```

### MCP Integration

#### Tool Registry (`adp.mcp.registry`)

Manages available MCP tools and their capabilities.

```python
class ToolRegistry:
    def __init__(self, tools: list[McpTool])
    
    def get_tool(self, name: str) -> McpTool | None
    
    def list_tools(self) -> list[McpTool]
    
    def get_tools_for_names(self, names: list[str]) -> list[McpTool]
```

#### MCP Client Manager (`adp.mcp.client`)

Manages MCP server lifecycles.

```python
class MCPClientManager:
    async def start(self, config: list[ServerConfig]) -> ToolRegistry
    
    async def stop(self) -> None
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        task: MicroTask | None = None,
    ) -> Any
```

### Validation

#### Output Verification (`adp.engine.final_verifier`)

Comprehensive verification at multiple stages.

```python
async def verify_execution_succeeded(plan: TaskPlan) -> None

async def verify_assembly_inputs(plan: TaskPlan, context: ContextDict) -> None

async def verify_final_outputs(plan: TaskPlan, files: dict[str, str]) -> None

async def verify_written_outputs(
    plan: TaskPlan,
    expected_files: dict[str, str],
    output_dir: str,
) -> None

async def verify_files_match_user_prompt(
    user_prompt: str,
    plan: TaskPlan,
    files: dict[str, str],
) -> None
```

## Configuration

### Model Resolution

Models are resolved at runtime from environment variables:

```python
def resolve_stage_model(stage_name: str, default_model: str) -> str
```

Stage-specific overrides:
- `MODEL_DECOMPOSER` - Decomposition stage
- `MODEL_ASSEMBLER_CLOUD` - Assembly stage (cloud)
- `MODEL_EXECUTOR_CODER` - Execution (coder tasks)
- `MODEL_EXECUTOR_GENERAL` - Execution (general tasks)
- `MODEL_TOOL_ROUTER` - MCP tool routing

### Context Management

#### Context Injection (`adp.stages.executor`)

```python
def fill_template(template: str, context: ContextDict) -> str
```

Replaces `{placeholder}` variables in system prompt templates with values from the context dictionary.

#### Run Store (`adp.engine.run_store`)

Manages persistent state for run resumption.

```python
def save_run_state(
    output_dir: str,
    run_id: str,
    user_prompt: str,
    plan: TaskPlan | None,
    context: ContextDict,
    files: dict[str, str],
    status: str,
    completed_stages: StageList,
    replan_count: int,
    max_replans: int,
    last_error: str | None,
) -> None
```

## TUI Components

### Application (`adp.tui.app`)

Main TUI application with live updates.

```python
class TUICallbacks:
    def on_stage(self, stage: str) -> None
    
    def on_plan_ready(self, plan: TaskPlan) -> None
    
    def on_task_start(self, task: MicroTask) -> None
    
    def on_task_done(self, task: MicroTask) -> None
    
    def on_task_failed(self, task: MicroTask) -> None
    
    def on_complete(
        self,
        written_files: list[tuple[str, int]],
        output_dir: str,
        stdout_text: str | None = None,
    ) -> None
    
    def on_error(self, error: str) -> None
```

## Error Handling

### Retry Strategy

```python
class RetryConfig:
    max_retries: int = 3
    temperature_step: float = 0.1
    inject_error: bool = True
```

### Custom Exceptions

```python
class PlanValidationError(Exception)
class OutputVerificationError(Exception)
class McpConnectionError(Exception)
class ModelCallError(Exception)
```

## Extension Points

### Custom Stages

New pipeline stages can be added by:
1. Creating a stage module in `adp/stages/`
2. Implementing the stage function
3. Adding to the agent graph in `agent_graph.py`

### Custom Validators

Add new verification logic:
1. Create validator functions in `adp/engine/`
2. Call them from appropriate stages
3. Handle `OutputVerificationError`

### MCP Tools

Add new tools:
1. Configure in `mcp_servers.toml`
2. Tools automatically available to decomposer
3. Use in task definitions

## Performance Considerations

### Memory Management

- Context dict size monitoring
- Tool result character limits
- Run state truncation for large contexts

### Execution Speed

- Sequential vs parallel execution
- Model timeout configuration
- Batch processing options

### Caching

- Model response caching (planned)
- Tool result caching (partial)
- Template compilation

## Debugging

### Debug Mode

Enable with `--debug` flag to see:
- All system prompts
- Raw model outputs
- Tool call results
- Internal state transitions

### Logging

```python
import logging

logger = logging.getLogger(__name__)
logger.debug("Debug information")
```

### Test Utilities

```python
from adp.testing import make_task, make_plan

def test_custom_logic():
    task = make_task("test", [], 0)
    # Test logic here
```

## Best Practices

1. **Keep tasks atomic**: Each task should have one clear output
2. **Use context injection**: Leverage upstream outputs effectively
3. **Handle failures gracefully**: Implement proper retry logic
4. **Validate outputs**: Use the provided verification functions
5. **Monitor resources**: Watch context window usage
6. **Test thoroughly**: Mock external dependencies in tests