# Changelog

All notable changes to GLI (Guided Local Intelligence) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- MCP (Model Context Protocol) integration for external tool support
- Reflection stage for semantic validation between execution and assembly
- Resumption capability for failed or interrupted runs
- Web search MCP server with no API key required
- Comprehensive verification layers throughout the pipeline
- TUI progress indicators and live updates
- Clarification dialogue for ambiguous prompts

### Changed
- Renamed project from ADP to GLI (Guided Local Intelligence)
- Updated default models to use qwen2.5 variants (1.5b) for local execution
- Improved error handling with detailed error messages
- Enhanced context injection mechanism
- Better documentation and examples

### Fixed
- Context window overflow issues
- Parallel execution bugs (now defaults to sequential)
- JSON parsing reliability in decomposition
- Template token leaks for temporal queries
- Source grounding for web search results

### Security
- Removed hardcoded API keys from configuration

## [0.1.0] - 2024-04-18

### Added
- Initial release of GLI (formerly ADP)
- 3-stage pipeline: Decompose, Execute, Assemble
- Context injection mechanism
- Sequential and parallel execution modes
- Basic MCP support
- TUI interface
- Command-line interface
- Comprehensive test suite

### Features
- Large model decomposition with dependency graphs
- Small model execution with context injection
- File assembly and validation
- Retry mechanisms with temperature escalation
- Debug mode for troubleshooting
- Output directory management

## Project History

### ADP to GLI Migration
The project was originally named "ADP" (Agentic Decomposition Pipeline) and was renamed to "GLI" (Guided Local Intelligence) to better reflect its core value proposition: providing intelligent guidance to local models through context injection.

### Key Milestones
- **Concept**: Realized that small models can generate reliable code if given proper context
- **Context Injection**: Developed mechanism to inject upstream outputs into downstream tasks
- **Local-First**: Designed pipeline to minimize large model usage
- **Verification**: Added multiple validation layers for quality assurance
- **MCP Integration**: Added external tool support for extended capabilities

### Architecture Evolution
1. **v0.1**: Basic 3-stage pipeline
2. **v0.2**: Added reflection stage
3. **v0.3**: Enhanced error handling and retries
4. **v0.4**: MCP integration and tool support
5. **v0.5**: Improved TUI and user experience