# GLI Architecture

This document describes the detailed architecture of GLI (Guided Local Intelligence).

## High-Level Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   User Prompt   │───▶│   Decomposer     │───▶│   Task Plan     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │                         │
                              ▼                         ▼
                       ┌──────────────┐         ┌─────────────┐
                       │ Large Model  │         │ Dependencies │
                       │ (Ollama)     │         │   Graph      │
                       └──────────────┘         └─────────────┘
                                                       │
                                                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Final Files   │◀───│    Assembler     │◀───│   Executor      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              ▲                         │
                              │                         ▼
                       ┌──────────────┐         ┌─────────────┐
                       │ Large Model  │         │ Context     │
                       │ (Ollama)     │         │ Injection   │
                       └──────────────┘         └─────────────┘
                                                       │
                                                       ▼
                                               ┌─────────────┐
                                               │ Small Models│
                                               │ (Ollama)    │
                                               └─────────────┘
```

## Component Interactions

### Agent Graph Flow

```
Initialize → Plan → Execute → Reflect → Assemble → Finalize → Complete
                     ↓       ↓         ↑          ↓
                   Fail   Replan   ────┘        Fail
                     ↓
                   END
```

### Data Flow

```
User Prompt
     │
     ▼
┌─────────────────┐
│ Decomposition   │ ──── Creates TaskPlan with MicroTasks
└─────────────────┘
     │
     ▼
┌─────────────────┐
│ Context Build   │ ──── Empty context dict initially
└─────────────────┘
     │
     ▼
┌─────────────────┐
│ Execution       │ ──── For each task:
│                 │      1. Execute MCP tools (if any)
│                 │      2. Inject context into template
│                 │      3. Call local model
│                 │      4. Validate output
│                 │      5. Store in context
└─────────────────┘
     │
     ▼
┌─────────────────┐
│ Reflection      │ ──── Optional semantic validation
└─────────────────┘
     │
     ▼
┌─────────────────┐
│ Assembly        │ ──── Stitch outputs into files
└─────────────────┘
     │
     ▼
┌─────────────────┐
│ Verification    │ ──── Multiple validation stages
└─────────────────┘
     │
     ▼
┌─────────────────┐
│ File Write      │ ──── Write files via MCP or stdout
└─────────────────┘
```

## Core Abstractions

### MicroTask Lifecycle

```
Created → Running → Done/Failed
    ↓        ↓         ↓
   Retry  ←  Error  →  Skipped
```

### Context Injection Mechanism

```
Template: "Use {user_schema} to create {api_endpoint} with {auth_type}"
Context: {
    "user_schema": "CREATE TABLE users (...)",
    "api_endpoint": "/api/users",
    "auth_type": "JWT Bearer token"
}
Result: "Use CREATE TABLE users (...) to create /api/users with JWT Bearer token"
```

## Detailed Component Architecture

### Decomposer

```python
decomposer/
├── system_prompt          # Fixed prompt for task planning
├── retry_handler          # JSON parsing with self-correction
├── tool_integrator        # MCP tool discovery and assignment
└── plan_validator         # Ensure plan correctness
```

**Key Features:**
- Fixed system prompt for consistent behavior
- Up to 6 retries for JSON parsing
- Automatic MCP tool assignment
- Dependency graph construction

### Executor

```python
executor/
├── task_scheduler         # Dependency resolution
├── context_manager        # Template filling
├── mcp_tool_executor      # Tool call orchestration
├── model_caller          # Local model communication
└── output_validator       # Structure validation
```

**Execution Modes:**
- Sequential (default): Reliable, context-preserving
- Parallel: Faster but may have race conditions

### Assembler

```python
assembler/
├── fragment_validator     # Ensure all outputs present
├── file_builder          # Construct complete files
├── import_resolver       # Add necessary imports
└── output_formatter      # Final file formatting
```

**Assembly Process:**
1. Validate required outputs exist
2. Send fragments and filenames to model
3. Parse structured response
4. Validate file structure
5. Return complete files

## Model Strategy

### Model Selection

```
┌─────────────────┬──────────────┬────────────────┐
│ Stage           │ Model Size   │ Purpose        │
├─────────────────┼──────────────┼────────────────┤
│ Decomposer      │ Large (120B) │ Complex        │
│                 │              │ reasoning      │
├─────────────────┼──────────────┼────────────────┤
│ Executor Coder  │ Small (1.5B) │ Code           │
│                 │              │ generation     │
├─────────────────┼──────────────┼────────────────┤
│ Executor General│ Small (1.5B) │ Text/          │
│                 │              │ extraction     │
├─────────────────┼──────────────┼────────────────┤
│ Assembler       │ Large (120B) │ File           │
│                 │              │ composition    │
├─────────────────┼──────────────┼────────────────┤
│ Tool Router     │ Tiny (latest)│ Tool           │
│                 │              │ selection      │
└─────────────────┴──────────────┴────────────────┘
```

### Temperature Settings

```
Local Models: 0.0    # Deterministic, consistent output
Cloud Models: 0.2    # Slight creativity for planning
Retries: +0.1 each   # Increase creativity on failure
```

## MCP Integration Architecture

### MCP Server Lifecycle

```
Start → Load Config → Launch Servers → Build Registry → Use Tools → Stop
```

### Tool Call Flow

```
Task Ready → Check Tools → Execute Tools → Inject Results → Call Model
```

### Security Model

```
┌─────────────────┐
│ Isolation       │ ──── Each tool runs in separate process
└─────────────────┘
┌─────────────────┐
│ Permissions     │ ──── Filesystem limited to output dir
└─────────────────┘
┌─────────────────┐
│ Validation      │ ──── Tool args validated before call
└─────────────────┘
```

## State Management

### Run State Persistence

```
State Structure:
{
    run_id: str,
    user_prompt: str,
    plan: TaskPlan | None,
    context: dict[str, str],
    files: dict[str, str],
    status: str,
    completed_stages: list[str],
    replan_count: int,
    max_replans: int,
    last_error: str | None
}
```

### Resumption Logic

```
Load State → Determine Last Stage → Continue from Stage
```

## Error Handling Architecture

### Retry Strategies

```
┌─────────────────┬──────────────┬────────────────┐
│ Error Type      │ Strategy     │ Max Attempts   │
├─────────────────┼──────────────┼────────────────┤
│ JSON Parse      │ Self-correct │ 6              │
├─────────────────┼──────────────┼────────────────┤
│ Model Timeout   │ Increase     │ 3              │
│                 │ temperature  │                │
├─────────────────┼──────────────┼────────────────┤
│ Execution Fail  │ Replan       │ 2              │
├─────────────────┼──────────────┼────────────────┤
│ File Write      │ Retry        │ 3              │
└─────────────────┴──────────────┴────────────────┘
```

### Verification Layers

```
1. Task Output Validation
   - Structure (JSON, code, etc.)
   - Content requirements
   - Size limits

2. Assembly Validation
   - All outputs present
   - File structure correct
   - No content invention

3. Write Validation
   - Files actually written
   - Content matches expected
   - Permissions correct

4. Prompt Validation
   - Matches user intent
   - Completeness check
   - Quality assessment
```

## Performance Considerations

### Memory Management

```
Context Dictionary:
- Grows with task outputs
- Truncated for persistence
- Limited injection size

Tool Results:
- Character limit enforced
- Large files chunked
- Summarized when needed
```

### Execution Optimization

```
Sequential Mode:
- Predictable order
- Context preserved
- Lower memory usage

Parallel Mode:
- Faster execution
- Context copying
- Higher memory usage
```

## Security Architecture

### Isolation Layers

```
┌─────────────────┐
│ Model Isolation │ ──── No internet for models
└─────────────────┘
┌─────────────────┐
│ Tool Isolation  │ ──── Separate processes
└─────────────────┘
┌─────────────────┐
│ File Isolation  │ ──── Limited to output dir
└─────────────────┘
```

### Input Validation

```
Prompt Validation:
- Sanitize inputs
- Check for injection
- Limit length

Template Validation:
- No code execution
- Limited placeholders
- Safe rendering
```

## Extension Points

### Adding New Stages

```python
# 1. Create stage function
async def custom_stage(state: AgentState) -> AgentState:
    # Stage logic here
    return updated_state

# 2. Add to graph
graph.add_node("custom", custom_stage)
graph.add_edge("existing", "custom")
```

### Custom Validators

```python
# 1. Create validator
def validate_custom(requirement: str) -> None:
    if not meets_requirement(requirement):
        raise OutputVerificationError("Custom validation failed")

# 2. Call in stage
validate_custom(plan.custom_requirement)
```

### MCP Tools

```toml
# mcp_servers.toml
[[servers]]
name = "custom_tool"
transport = "stdio"
command = "python"
args = ["-m", "custom_mcp_server"]
```

## Monitoring and Observability

### Metrics Collection

```
- Task execution times
- Model call counts
- Error rates
- Token usage
- Memory usage
```

### Debug Information

```
Debug Mode Provides:
- Full system prompts
- Model outputs
- Tool call results
- State transitions
- Error traces
```

### Logging Levels

```
DEBUG: Detailed execution trace
INFO: Stage transitions
WARNING: Retry attempts
ERROR: Failures
CRITICAL: System errors
```

## Future Architecture Considerations

### Scalability

```
Potential Improvements:
- Distributed execution
- Model caching
- Streaming responses
- Batch processing
```

### Extensibility

```
Planned Features:
- Custom stage plugins
- Dynamic model routing
- Advanced tool composition
- Multi-modal support
```

### Performance

```
Optimization Opportunities:
- Async tool execution
- Smart caching
- Predictive pre-fetch
- Parallel validation
```