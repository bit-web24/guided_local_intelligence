# GLI Documentation

Welcome to the GLI (Guided Local Intelligence) documentation hub.

## Quick Start

- [Main README](../README.md) - Project overview and quick start guide
- [Quick Reference](QUICK_REFERENCE.md) - Common patterns and examples
- [Migration Guide](MIGRATION.md) - Migrating from ADP to GLI

## User Documentation

### Getting Started
- [Installation](../README.md#quick-start) - Install and setup GLI
- [Usage](../README.md#usage) - Basic usage examples
- [Configuration](../README.md#configuration) - Configure models and settings

### Advanced Features
- [MCP Integration](../README.md#mcp-servers) - External tool integration
- [Architecture](ARCHITECTURE.md) - System design and components
- [API Reference](API.md) - Internal API documentation

### Guides
- [Examples](QUICK_REFERENCE.md#common-use-cases) - Real-world examples
- [Troubleshooting](../README.md#troubleshooting) - Common issues and solutions

## Developer Documentation

### Development
- [Contributing](../CONTRIBUTING.md) - How to contribute
- [Testing](TESTING.md) - Test strategy and guidelines
- [Architecture](ARCHITECTURE.md) - Detailed system architecture

### Reference
- [API Documentation](API.md) - Complete API reference
- [Configuration Reference](../README.md#environment-variables) - All configuration options
- [Changelog](../CHANGELOG.md) - Version history and changes

## Project Structure

```
docs/
├── README.md              # This file - documentation hub
├── QUICK_REFERENCE.md     # Common patterns and examples
├── MIGRATION.md          # Migration from ADP to GLI
├── ARCHITECTURE.md       # System architecture
├── API.md                # Internal API documentation
├── TESTING.md            # Testing guidelines
└── legacy/               # Old documentation (archived)
    ├── *.odt
    ├── *.pdf
    └── *.ods
```

## Documentation Conventions

### Code Blocks
- Inline code: `variable_name`
- Command line: ```bash
- Python code: ```python
- Configuration files: ```toml

### Notes and Warnings
- ℹ️ **Note**: Informational content
- ⚠️ **Warning**: Important cautions
- ✅ **Tip**: Helpful suggestions
- ❌ **Error**: Things to avoid

### Navigation
- See [Related Section](#section-name) for more details
- External links: [GitHub](https://github.com/example/gli)
- File references: [`config.py`](../adp/config.py)

## Contributing to Documentation

We welcome documentation improvements! Please:

1. Check existing documentation before adding new content
2. Follow the style guide above
3. Test all examples and commands
4. Update multiple files if needed (e.g., add feature to README and API docs)
5. Use clear, simple language

### Documentation Style

- Use active voice ("Create a file" not "A file should be created")
- Keep sentences short and direct
- Use examples to illustrate concepts
- Include troubleshooting tips for common issues

## Getting Help

If you can't find what you're looking for:

1. Search all documentation
2. Check the [main README](../README.md)
3. Look at [examples](QUICK_REFERENCE.md)
4. Ask in GitHub discussions
5. Open an issue if documentation is missing or unclear

## Documentation Versions

Documentation corresponds to GLI versions:

- Current documentation: GLI v0.1.x
- For older versions, check git history
- Migration guide covers breaking changes

## Quick Links

### Common Tasks
- [Install GLI](../README.md#quick-start)
- [Generate Python code](QUICK_REFERENCE.md#1-generate-a-python-application)
- [Configure models](../README.md#model-configuration)
- [Debug issues](../README.md#troubleshooting)

### API Reference
- [Decomposer](API.md#decomposer) - Task decomposition
- [Executor](API.md#executor) - Task execution
- [Assembler](API.md#assembler) - File assembly
- [Models](API.md#data-models) - Data structures

### Development
- [Run tests](TESTING.md#running-tests)
- [Add features](../CONTRIBUTING.md#making-changes)
- [Architecture decisions](ARCHITECTURE.md#extension-points)