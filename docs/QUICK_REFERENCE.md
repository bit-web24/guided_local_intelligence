# GLI Quick Reference Guide

This guide provides quick examples and common patterns for using GLI.

## Common Use Cases

### 1. Generate a Python Application

```bash
# Basic FastAPI app
uv run adp "Create a FastAPI app with CRUD endpoints for a todo list"

# With specific structure
uv run adp "Create a Flask app with models for User and Post, using SQLAlchemy"

# Include tests
uv run adp "Create a FastAPI app for a blog API with comprehensive pytest tests"
```

### 2. Generate Configuration Files

```bash
# Docker Compose
uv run adp "Generate a docker-compose.yml for a web app with nginx, postgres, redis"

# Kubernetes manifests
uv run adp "Create Kubernetes manifests for a 3-tier web application"

# CI/CD pipeline
uv run adp "Generate a GitHub Actions workflow for Python testing and deployment"
```

### 3. Documentation Generation

```bash
# API documentation
uv run adp "Generate OpenAPI documentation for a REST API"

# README from code
uv run adp "Create a comprehensive README.md for this Python package"

# Technical documentation
uv run adp "Write technical documentation explaining how this system works"
```

### 4. Data Processing

```bash
# Data analysis script
uv run adp "Write a Python script to analyze sales data from CSV files"

# ETL pipeline
uv run adp "Create an ETL pipeline using pandas to process JSON data"

# ML model
uv run adp "Generate a scikit-learn model for predicting house prices"
```

### 5. Web Development

```bash
# React component
uv run adp "Create a React component for a user profile page with TypeScript"

# Express.js API
uv run adp "Build an Express.js API with authentication middleware"

# CSS framework
uv run adp "Generate a responsive CSS grid layout for a dashboard"
```

## Advanced Patterns

### Custom Model Selection

```bash
# Use different models for different tasks
uv run adp \
  --cloud-model gemma4:31b-cloud \
  --coder-model qwen2.5-coder:3b \
  --general-model qwen2.5:3b \
  "Your complex prompt here"
```

### Environment Variables

```bash
# Set execution mode
export EXECUTION_MODE=parallel
export MAX_PARALLEL=4

# Adjust timeouts for slow models
export LOCAL_TIMEOUT=180
export CLOUD_TIMEOUT=300

# Disable reflection for faster execution
export REFLECT_ENABLED=false

# Run with custom settings
uv run adp "Your prompt here"
```

### Using with MCP Tools

```bash
# Ensure mcp_servers.toml is configured with:
# - filesystem server for file access
# - web search for research tasks

# Research and generate
uv run adp "Research latest trends in AI and write a summary report"

# Modify existing files
uv run adp "Read the requirements.txt and suggest improvements"
```

## Troubleshooting Quick Tips

### Model Issues

```bash
# Check if models are available
ollama list

# Pull missing models
ollama pull qwen2.5-coder:1.5b

# Check Ollama status
curl http://localhost:11434/api/tags
```

### Debug Mode

```bash
# See all prompts and outputs
uv run adp --debug "Your prompt"

# Save debug output to file
uv run adp --debug "Your prompt" 2>&1 | tee debug.log
```

### Resume Failed Runs

```bash
# List available runs
ls -la output/.gli_runs/

# Resume from specific run
uv run adp --resume RUN_ID_HERE "Refine the output"
```

## Performance Optimization

### Faster Execution

```bash
# Use parallel mode (may be less reliable)
export EXECUTION_MODE=parallel

# Disable reflection stage
export REFLECT_ENABLED=false

# Use smaller models
uv run adp --coder-model qwen2.5-coder:0.5b "Your prompt"
```

### Quality Improvements

```bash
# Enable reflection for better quality
export REFLECT_ENABLED=true
export REFLECT_USE_CLOUD=true

# Increase retries for difficult tasks
export MAX_RETRIES=5
export DECOMPOSITION_MAX_RETRIES=10

# Use larger models for complex tasks
uv run adp --cloud-model gpt-oss:120b-cloud "Your complex prompt"
```

## Integration Examples

### With Git Hooks

```bash
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: gli-generate
        name: GLI Generate
        entry: uv run adp --no-tui
        language: system
        args: ["Generate tests for modified files"]
        pass_filenames: false
```

### With Make

```makefile
# Makefile
.PHONY: generate docs test

generate:
	uv run adp --no-tui "Generate CRUD API for current models"

docs:
	uv run adp --no-tui "Update documentation from code changes"

test:
	pytest -v

all: generate docs test
```

### With CI/CD

```yaml
# .github/workflows/generate.yml
name: Generate Code

on:
  push:
    paths:
      - 'specs/*.md'

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - name: Setup Ollama
        run: |
          curl -fsSL https://ollama.ai/install.sh | sh
          ollama serve &
          ollama pull qwen2.5-coder:1.5b
      - name: Generate from specs
        run: |
          for spec in specs/*.md; do
            uv run adp --no-tui "$(cat $spec)"
          done
```

## Common Prompt Patterns

### Task Specification

```
Create a [language] [component type] that does [functionality].
Include [features/requirements].
Use [frameworks/libraries].
Follow [style/architecture].
```

### Code Generation

```
Write [language] code to implement [feature].
The code should:
- [requirement 1]
- [requirement 2]
- [requirement 3]
Include error handling and tests.
```

### Refactoring

```
Refactor the [component] to:
- [improvement 1]
- [improvement 2]
- [improvement 3]
Maintain backward compatibility.
Add tests for the refactored code.
```

### Documentation

```
Generate [type] documentation for [component].
Include:
- Overview/purpose
- API reference
- Usage examples
- Troubleshooting
```

## Tips and Best Practices

### Prompt Engineering

1. **Be specific**: Clearly define requirements and constraints
2. **Provide context**: Include relevant background information
3. **Structure requests**: Use bullet points for clarity
4. **Iterate**: Start simple, add complexity gradually
5. **Use examples**: Provide sample inputs/outputs when helpful

### Working with Large Projects

1. **Break down tasks**: Generate one component at a time
2. **Use existing files**: Reference current codebase via MCP
3. **Leverage context**: Build on previous outputs
4. **Test incrementally**: Validate each component
5. **Document decisions**: Keep track of architecture choices

### Error Prevention

1. **Validate inputs**: Check prompt clarity before running
2. **Monitor context**: Watch for window overflow warnings
3. **Use retries**: Let GLI handle transient failures
4. **Save state**: Use resume capability for long tasks
5. **Review outputs**: Always verify generated code

## Keyboard Shortcuts (TUI Mode)

- `Ctrl+C`: Cancel current operation
- `Ctrl+D`: Exit GLI
- `Tab`: Complete file paths
- `↑/↓`: Navigate command history
- `Enter`: Submit prompt
- `Esc`: Cancel current input

## Environment Quick Setup

```bash
# One-line setup for new environment
curl -LsSf https://astral.sh/uv/install.sh | sh && \
git clone <your-repo> && \
cd <your-repo> && \
uv sync && \
ollama pull gpt-oss:120b-cloud && \
ollama pull qwen2.5-coder:1.5b && \
ollama pull qwen2.5:1.5b && \
echo "Setup complete! Run: uv run adp"
```

## Resources

- [Full Documentation](../README.md)
- [API Reference](API.md)
- [Contributing Guide](../CONTRIBUTING.md)
- [Examples Repository](https://github.com/example/gli-examples)
- [Community Discord](https://discord.gg/gli)