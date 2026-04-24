# Testing GLI

This document describes the testing strategy and guidelines for GLI.

## Test Structure

```
tests/
├── test_graph.py          # Agent graph orchestration
├── test_decomposer.py     # Task decomposition
├── test_executor.py       # Task execution
├── test_assembler.py      # File assembly
├── test_validator.py      # Output validation
├── test_reflector.py      # Reflection stage
├── test_replanner.py      # Replanning logic
├── test_clarifier.py      # Prompt clarification
├── test_model_config.py   # Configuration
├── test_run_store.py      # State persistence
├── test_mcp_client.py     # MCP integration
├── test_mcp_registry.py   # Tool registry
├── test_tui_summary.py    # TUI components
└── test_executor_mcp.py   # MCP execution
```

## Running Tests

### All Tests

```bash
# Run all tests
uv run pytest -v

# Run with coverage
uv run pytest --cov=adp --cov-report=html

# Run with coverage and show missing lines
uv run pytest --cov=adp --cov-report=term-missing
```

### Unit Tests Only (No Ollama Required)

```bash
# Fast unit tests that don't require Ollama
uv run pytest tests/test_graph.py tests/test_validator.py \
    tests/test_decomposer.py tests/test_executor.py -v
```

### Specific Test Categories

```bash
# Test MCP functionality
uv run pytest tests/test_mcp_*.py -v

# Test orchestration
uv run pytest tests/test_graph.py tests/test_replanner.py -v

# Test stages
uv run pytest tests/test_decomposer.py tests/test_executor.py \
    tests/test_assembler.py tests/test_reflector.py -v
```

## Testing Patterns

### Mocking External Dependencies

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_decomposer_with_mock():
    with patch('adp.engine.cloud_client.call_cloud_async') as mock_call:
        mock_call.return_value = '{"tasks": []}'
        result = await decompose("test prompt")
        assert result is not None
```

### Test Fixtures

```python
import pytest
from adp.models.task import MicroTask, TaskPlan

@pytest.fixture
def sample_task():
    return MicroTask(
        id="t1",
        description="Test task",
        system_prompt_template="Test: {input}",
        input_text="input",
        output_key="output",
        depends_on=[],
        anchor=AnchorType.OUTPUT,
        parallel_group=0,
    )

@pytest.fixture
def sample_plan(sample_task):
    return TaskPlan(
        tasks=[sample_task],
        final_output_keys=["output"],
        output_filenames=["test.txt"],
        write_to_file=True,
    )
```

### Parameterized Tests

```python
import pytest

@pytest.mark.parametrize("model_type,expected", [
    ("coder", "qwen2.5-coder:1.5b"),
    ("general", "qwen2.5:1.5b"),
    ("tool_router", "functiongemma:latest"),
])
def test_model_resolution(model_type, expected):
    result = resolve_model(model_type)
    assert result == expected
```

## Test Categories

### 1. Unit Tests

Test individual components in isolation:

```python
def test_fill_template():
    """Test template filling functionality."""
    template = "Hello {name}, you have {count} messages"
    context = {"name": "Alice", "count": "5"}
    result = fill_template(template, context)
    assert result == "Hello Alice, you have 5 messages"
```

### 2. Integration Tests

Test component interactions:

```python
@pytest.mark.asyncio
async def test_execution_with_context():
    """Test that context is properly injected between tasks."""
    task1 = make_task("t1", [], 0, output_key="result1")
    task2 = make_task("t2", ["t1"], 1, output_key="result2")
    plan = TaskPlan(tasks=[task1, task2], ...)
    
    with patch('adp.engine.local_client.call_local_async') as mock_call:
        # Mock responses for each task
        mock_call.side_effect = ["output1", "output2"]
        
        context = await execute_plan(plan)
        assert "result1" in context
        assert "result2" in context
```

### 3. End-to-End Tests

Test the full pipeline (requires Ollama):

```python
@pytest.mark.slow
@pytest.mark.asyncio
async def test_full_pipeline():
    """Test the complete pipeline with real models."""
    prompt = "Create a simple Python function that adds two numbers"
    
    result = await run_pipeline(
        user_prompt=prompt,
        output_dir=tmp_path,
        callbacks=make_plain_callbacks(),
        debug=True,
    )
    
    assert "main.py" in result.files
    assert "def add(" in result.files["main.py"]
```

## Test Utilities

### Test Helpers

```python
# tests/conftest.py
import pytest
from adp.models.task import MicroTask, TaskPlan, AnchorType

def make_task(id: str, depends_on: list[str], group: int, **kwargs):
    """Create a test MicroTask with sensible defaults."""
    defaults = {
        "description": f"Task {id}",
        "system_prompt_template": "Process: {input_text}",
        "input_text": "test input",
        "output_key": f"output_{id}",
        "anchor": AnchorType.OUTPUT,
        "parallel_group": group,
        "model_type": "general",
    }
    defaults.update(kwargs)
    return MicroTask(id=id, depends_on=depends_on, **defaults)

def make_plan(tasks: list[MicroTask], **kwargs):
    """Create a test TaskPlan."""
    defaults = {
        "final_output_keys": [t.output_key for t in tasks],
        "output_filenames": ["test.txt"],
        "write_to_file": True,
    }
    defaults.update(kwargs)
    return TaskPlan(tasks=tasks, **defaults)
```

### Assertion Helpers

```python
def assert_valid_task_plan(plan: TaskPlan):
    """Assert that a TaskPlan is valid."""
    assert plan.tasks
    assert plan.final_output_keys
    assert plan.output_filenames
    
    # Check dependencies
    task_ids = {t.id for t in plan.tasks}
    for task in plan.tasks:
        assert all(dep in task_ids for dep in task.depends_on)

def assert_valid_context(context: dict[str, str], plan: TaskPlan):
    """Assert that context contains all required keys."""
    for key in plan.final_output_keys:
        assert key in context
        assert context[key].strip()
```

## Mock Strategies

### Model Call Mocking

```python
class MockModelCall:
    def __init__(self):
        self.responses = []
        self.calls = []
    
    def add_response(self, response: str):
        self.responses.append(response)
    
    async def __call__(self, prompt: str, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.responses.pop(0) if self.responses else "default"

# Usage
mock_cloud = MockModelCall()
mock_cloud.add_response('{"tasks": [{"id": "t1", ...}]}')

with patch('adp.engine.cloud_client.call_cloud_async', mock_cloud):
    result = await decompose("test")
```

### MCP Mocking

```python
@pytest.fixture
def mock_mcp_manager():
    manager = AsyncMock()
    manager.call_tool.return_value = {"result": "mocked"}
    return manager

@pytest.mark.asyncio
async def test_mcp_integration(mock_mcp_manager):
    task = make_task("t1", [], 0, mcp_tools=["filesystem"])
    
    with patch('adp.engine.local_client.call_local_async'):
        result = await execute_task(task, mcp_manager=mock_mcp_manager)
        mock_mcp_manager.call_tool.assert_called_with("filesystem", {})
```

## Test Data Management

### Fixtures Directory

```
tests/
├── fixtures/
│   ├── sample_prompts.json    # Test prompts
│   ├── expected_outputs.json  # Expected results
│   └── mock_responses.json    # Mock model responses
```

### Test Data Example

```json
// tests/fixtures/sample_prompts.json
{
    "simple": "Create a function that adds two numbers",
    "complex": "Build a FastAPI app with user authentication",
    "debugging": "Fix the bug in this code snippet"
}
```

## Performance Testing

### Benchmark Tests

```python
@pytest.mark.benchmark
def test_decomposition_performance(benchmark):
    """Benchmark decomposition performance."""
    prompt = "Create a complex multi-file application"
    
    result = benchmark(
        decompose,
        prompt,
        tool_registry=mock_registry,
        project_dir="/tmp",
    )
    
    assert len(result.tasks) > 0
```

### Memory Tests

```python
@pytest.mark.memory
def test_context_memory_usage():
    """Test that context doesn't grow indefinitely."""
    import psutil
    import os
    
    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss
    
    # Execute many tasks
    for i in range(100):
        context = execute_large_plan()
    
    final_memory = process.memory_info().rss
    memory_growth = final_memory - initial_memory
    
    # Assert memory growth is reasonable (< 100MB)
    assert memory_growth < 100 * 1024 * 1024
```

## Continuous Integration

### GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      ollama:
        image: ollama/ollama
        ports:
          - 11434:11434
        options: --gpus all
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up uv
        uses: astral-sh/setup-uv@v3
        
      - name: Install dependencies
        run: uv sync
        
      - name: Pull models
        run: |
          ollama pull qwen2.5-coder:1.5b
          ollama pull qwen2.5:1.5b
          
      - name: Run unit tests
        run: uv run pytest tests/test_graph.py tests/test_validator.py -v
        
      - name: Run all tests (if models available)
        run: uv run pytest -v || echo "Full tests skipped"
        
      - name: Generate coverage
        run: uv run pytest --cov=adp --cov-report=xml
        
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

## Best Practices

### Test Organization

1. **One assert per test**: Keep tests focused
2. **Descriptive names**: Test names should describe the scenario
3. **Setup in fixtures**: Use fixtures for common setup
4. **Mock external dependencies**: Never rely on external services

### Writing Good Tests

```python
# Bad: Multiple assertions, unclear purpose
def test_pipeline():
    result = run_pipeline()
    assert result is not None
    assert "files" in result
    assert len(result.files) > 0

# Good: Single purpose, clear assertion
def test_pipeline_returns_files_when_given_valid_prompt():
    prompt = "Create a Python function"
    result = run_pipeline(prompt)
    assert result.files == {"main.py": expected_content}
```

### Testing Edge Cases

```python
@pytest.mark.parametrize("prompt", [
    "",  # Empty prompt
    " ",  # Whitespace only
    "a" * 10000,  # Very long prompt
    "🦄",  # Unicode characters
    "malformed\x00prompt",  # Null bytes
])
def test_decomposer_handles_edge_cases(prompt):
    """Test that decomposer handles unusual prompts gracefully."""
    with pytest.raises((ValueError, PlanValidationError)):
        decompose(prompt)
```

## Debugging Tests

### Debug Mode in Tests

```python
@pytest.mark.asyncio
async def test_failing_stage():
    """Debug a failing test with full output."""
    try:
        result = await execute_stage()
    except Exception as e:
        # Print full context for debugging
        import pprint
        pprint.pprint(result.__dict__ if hasattr(result, '__dict__') else result)
        raise
```

### Test Logging

```python
import logging

@pytest.fixture(autouse=True)
def configure_logging():
    logging.basicConfig(level=logging.DEBUG)

def test_with_logging():
    logger = logging.getLogger(__name__)
    logger.debug("Starting test")
    # Test logic here
    logger.debug("Test completed")
```

## Future Testing Considerations

### Property-Based Testing

```python
import hypothesis
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=100))
def test_decompose_with_any_prompt(prompt):
    """Test decomposition with various prompts."""
    result = decompose(prompt)
    assert result.tasks
    assert all(t.id for t in result.tasks)
```

### Contract Testing

```python
def test_model_contract():
    """Test that model interface matches contract."""
    # Verify cloud client interface
    assert callable(call_cloud_async)
    # Verify local client interface
    assert callable(call_local_async)
```

### Load Testing

```python
@pytest.mark.load
def test_concurrent_execution():
    """Test execution under load."""
    import asyncio
    
    tasks = [execute_pipeline() for _ in range(10)]
    results = asyncio.gather(*tasks)
    
    assert all(r is not None for r in results)
```