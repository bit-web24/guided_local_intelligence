# Contributing to GLI

Thank you for your interest in contributing to GLI (Guided Local Intelligence)! This document provides guidelines and information for contributors.

## Getting Started

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) for package management
- [Ollama](https://ollama.ai) for local model serving
- Node.js and npm (for MCP servers)

### Development Setup

1. Clone the repository:
```bash
git clone https://github.com/your-username/guided_local_intelligence.git
cd guided_local_intelligence
```

2. Create a virtual environment and install dependencies:
```bash
uv sync
```

3. Pull the required Ollama models:
```bash
ollama pull gpt-oss:120b-cloud
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5:1.5b
ollama pull functiongemma:latest
```

4. Copy the environment configuration:
```bash
cp .env.example .env
```

5. Run tests to ensure everything is working:
```bash
uv run pytest -v
```

## Development Workflow

### Making Changes

1. Create a new branch for your feature or bugfix:
```bash
git checkout -b feature/your-feature-name
```

2. Make your changes following the code style guidelines below.

3. Add tests for your changes if applicable.

4. Run the test suite:
```bash
uv run pytest -v
```

5. Check code coverage (optional):
```bash
uv run pytest --cov=adp --cov-report=html
```

6. Commit your changes with a clear commit message:
```bash
git commit -m "feat: add new feature description"
```

7. Push to your fork and create a pull request.

### Code Style

- Follow PEP 8 for Python code formatting
- Use type hints for all function signatures
- Keep functions focused and small
- Add docstrings for all public functions and classes
- Use descriptive variable names

### Testing

GLI uses pytest for testing. Tests are organized in the `tests/` directory:

- Unit tests test individual components in isolation
- Integration tests test component interactions
- End-to-end tests test the full pipeline

#### Running Tests

```bash
# Run all tests
uv run pytest -v

# Run specific test file
uv run pytest tests/test_executor.py -v

# Run with coverage
uv run pytest --cov=adp --cov-report=html

# Run tests without Ollama (unit tests only)
uv run pytest tests/test_graph.py tests/test_validator.py tests/test_decomposer.py tests/test_executor.py -v
```

#### Writing Tests

When adding new functionality, please include appropriate tests:

1. **Unit tests** for individual functions and classes
2. **Integration tests** if your code interacts with other components
3. **Mock external dependencies** (like Ollama and MCP) for unit tests

Example test structure:
```python
def test_function_name():
    """Test that function does X."""
    # Arrange
    input_data = ...
    
    # Act
    result = function_name(input_data)
    
    # Assert
    assert result == expected_result
```

## Architecture Overview

GLI follows a 3-stage pipeline architecture:

### 1. Decomposer (`adp/stages/decomposer.py`)
- Takes user prompts and breaks them into atomic micro-tasks
- Creates dependency graphs and few-shot examples
- Uses the large Ollama model for planning

### 2. Executor (`adp/stages/executor.py`)
- Executes micro-tasks in dependency order
- Implements context injection between tasks
- Uses small Ollama models for code generation

### 3. Assembler (`adp/stages/assembler.py`)
- Combines task outputs into complete files
- Ensures structural correctness
- Uses the large Ollama model for assembly

### Supporting Components

- **Agent Graph** (`adp/agent_graph.py`): LangGraph-based orchestration
- **Models** (`adp/models/`): Data structures for tasks and results
- **Engine** (`adp/engine/`): Model clients and validation
- **TUI** (`adp/tui/`): Terminal user interface
- **MCP** (`adp/mcp/`): Model Context Protocol integration

## Contributing Guidelines

### What to Contribute

We welcome contributions in the following areas:

1. **Bug fixes**: Help us squash bugs!
2. **Documentation**: Improve docs, add examples
3. **New features**: Core pipeline features or tool integrations
4. **Performance**: Optimizations and speed improvements
5. **Tests**: Better test coverage and test utilities

### Before You Start

1. Check if there's an existing issue for your change
2. Discuss major changes in an issue first
3. Look at the contribution priorities in the project README

### Submitting Changes

1. **Small changes**: Feel free to submit directly
2. **Large changes**: Open an issue to discuss first
3. **Breaking changes**: Must be discussed and approved first

### Pull Request Process

1. Update the README.md with details of your changes if applicable
2. Update any relevant documentation
3. Ensure your PR description clearly describes the change
4. Link to any relevant issues
5. Include screenshots if adding UI changes

## Code Review Process

1. All submissions require review
2. Maintain responsive communication
3. Address review feedback promptly
4. Keep PRs focused and manageable in size

## Release Process

Releases are managed by maintainers following semantic versioning:

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

## Community

- Be respectful and inclusive
- Help others learn and grow
- Ask questions if you're unsure
- Share your knowledge and experiences

## Resources

- [GLI Documentation](README.md)
- [Ollama Documentation](https://ollama.ai/documentation)
- [LangGraph Documentation](https://python.langchain.com/docs/langgraph)
- [MCP Documentation](https://modelcontextprotocol.io)

## Getting Help

If you need help:

1. Check existing documentation
2. Search existing issues
3. Create a new issue with details
4. Join discussions in issues/PRs

Thank you for contributing to GLI! 🚀