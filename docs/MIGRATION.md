# Migration Guide: ADP to GLI

This guide helps users migrate from ADP (Agentic Decomposition Pipeline) to GLI (Guided Local Intelligence).

## Overview of Changes

GLI is the new name for ADP, reflecting its core value proposition: providing intelligent guidance to local models through context injection. While the project name has changed, most of the core functionality remains the same.

## What's Changed

### 1. Project Name

- **Before**: `adp` command
- **After**: `gli` command (planned for future release)
- **Current**: Still uses `adp` command during transition

### 2. Default Models

Updated to more efficient smaller models:

| Component | Old Default | New Default |
|-----------|-------------|-------------|
| Local Coder | `qwen2.5-coder:7b` | `qwen2.5-coder:1.5b` |
| Local General | `qwen2.5:7b` | `qwen2.5:1.5b` |
| Tool Router | Not specified | `functiongemma:latest` |

### 3. New Features

- MCP (Model Context Protocol) integration
- Reflection stage for semantic validation
- Run resumption capability
- Enhanced verification layers
- Improved TUI with live updates

### 4. Configuration Changes

- Simplified model selection
- More environment variable options
- Better defaults for local execution

## Migration Steps

### Step 1: Update Your Installation

```bash
# If you have the old version
cd guided_local_intelligence
git pull origin main
uv sync

# Pull new default models
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5:1.5b
ollama pull functiongemma:latest
```

### Step 2: Update Your Configuration

If you have a custom `.env` file, update it:

```bash
# Backup old config
cp .env .env.backup

# Copy new template
cp .env.example .env

# Edit with your custom settings
nano .env
```

Key changes to consider:
- Update model names if you had custom models
- Review new MCP configuration options
- Check reflection settings (`REFLECT_ENABLED`)

### Step 3: Update Your Scripts

Update any scripts that use ADP:

```bash
# Old command patterns
adp "Your prompt here"
adp --model custom-model "Your prompt"

# These still work, but consider updating
uv run adp "Your prompt here"
uv run adp --coder-model qwen2.5-coder:1.5b "Your prompt"
```

### Step 4: Test Your Setup

```bash
# Test with a simple prompt
uv run adp --debug "Create a hello world function"

# Check that all models work
uv run adp --cloud-model gpt-oss:120b-cloud \
            --coder-model qwen2.5-coder:1.5b \
            --general-model qwen2.5:1.5b \
            "Test prompt"
```

## Breaking Changes

### 1. Model Default Changes

The default local models are now smaller (1.5B instead of 7B). This provides:
- Faster execution
- Lower memory usage
- Better for local hardware

**Action**: If you prefer the larger models, set them explicitly:
```bash
export LOCAL_CODER_MODEL=qwen2.5-coder:7b
export LOCAL_GENERAL_MODEL=qwen2.5:7b
```

### 2. Sequential Execution Default

Execution mode now defaults to `sequential` instead of `parallel` for better reliability.

**Action**: If you want parallel execution:
```bash
export EXECUTION_MODE=parallel
export MAX_PARALLEL=6
```

### 3. Reflection Stage Enabled

Reflection is now enabled by default, adding semantic validation.

**Action**: To disable for faster execution:
```bash
export REFLECT_ENABLED=false
```

## New Features You Should Use

### 1. MCP Integration

Configure MCP servers in `mcp_servers.toml`:

```toml
# Filesystem access (pre-configured)
[[servers]]
name = "filesystem"
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "./output"]

# Web search (pre-configured)
[[servers]]
name = "web_search"
transport = "stdio"
command = "npx"
args = ["-y", "open-websearch@latest"]
```

### 2. Run Resumption

If a run fails, you can resume:

```bash
# Find run ID
ls output/.gli_runs/

# Resume from that point
uv run adp --resume RUN_ID_HERE "Continue with refinement"
```

### 3. Clarification Dialogue

For ambiguous prompts, GLI will ask clarifying questions:

```bash
# This might trigger clarification
uv run adp "Build a web app"

# GLI will ask: "What kind of web app? What framework?"
```

## Configuration Migration

### Old Configuration

```bash
# Old .env format
CLOUD_MODEL=gpt-oss:120b-cloud
LOCAL_CODER_MODEL=qwen2.5-coder:7b
LOCAL_GENERAL_MODEL=qwen2.5:7b
```

### New Configuration

```bash
# New .env format with more options
CLOUD_MODEL=gpt-oss:120b-cloud
LOCAL_CODER_MODEL=qwen2.5-coder:1.5b
LOCAL_GENERAL_MODEL=qwen2.5:1.5b
LOCAL_TOOL_ROUTER_MODEL=functiongemma:latest

# Stage-specific overrides
MODEL_DECOMPOSER=gpt-oss:120b-cloud
MODEL_ASSEMBLER_CLOUD=ministral-3:3b-cloud
MODEL_EXECUTOR_CODER=qwen2.5-coder:1.5b

# Feature flags
REFLECT_ENABLED=true
REFLECT_USE_CLOUD=true
EXECUTION_MODE=sequential
```

## Troubleshooting Migration Issues

### Issue: Models Not Found

```
Error: Model qwen2.5-coder:1.5b not found
```

**Solution**: Pull the new models:
```bash
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5:1.5b
ollama pull functiongemma:latest
```

### Issue: Slower Execution

**Cause**: New defaults prioritize reliability over speed

**Solution**: Optimize for speed:
```bash
export REFLECT_ENABLED=false
export EXECUTION_MODE=parallel
export LOCAL_CODER_MODEL=qwen2.5-coder:3b
```

### Issue: Different Output Quality

**Cause**: Smaller models may produce different quality

**Solution**: Use larger models if needed:
```bash
export LOCAL_CODER_MODEL=qwen2.5-coder:7b
export LOCAL_GENERAL_MODEL=qwen2.5:7b
```

### Issue: MCP Tools Not Working

**Symptoms**: Tools not available or errors

**Solution**: Check MCP configuration:
```bash
# Verify npx is available
which npx

# Test MCP server manually
npx -y @modelcontextprotocol/server-filesystem --help

# Check mcp_servers.toml exists
ls mcp_servers.toml
```

## Migration Script

Here's a script to help with migration:

```bash
#!/bin/bash
# migrate_adp_to_gli.sh

echo "🔄 Migrating from ADP to GLI..."

# Backup old config
if [ -f .env ]; then
    echo "📦 Backing up old .env to .env.backup"
    cp .env .env.backup
fi

# Pull new models
echo "📥 Pulling new default models..."
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5:1.5b
ollama pull functiongemma:latest

# Update config
echo "⚙️ Updating configuration..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created new .env from template"
else
    echo "⚠️ .env exists. Please manually update it with new settings from .env.example"
fi

# Test installation
echo "🧪 Testing installation..."
if uv run adp --version > /dev/null 2>&1; then
    echo "✅ GLI is ready!"
else
    echo "❌ Installation issue. Please check error messages above."
fi

echo ""
echo "🎉 Migration complete! Next steps:"
echo "1. Review .env file for custom settings"
echo "2. Try: uv run adp \"Create a hello world function\""
echo "3. Read docs/MIGRATION.md for more details"
```

## Best Practices After Migration

### 1. Use New Features

- Enable MCP for external tool access
- Use reflection for better quality
- Leverage run resumption for long tasks

### 2. Optimize for Your Hardware

```bash
# For powerful hardware
export LOCAL_CODER_MODEL=qwen2.5-coder:7b
export EXECUTION_MODE=parallel

# For resource-constrained hardware
export REFLECT_ENABLED=false
export LOCAL_TIMEOUT=60
```

### 3. Update Documentation

Update any team documentation that references ADP:
- Update command examples
- Note new features
- Add troubleshooting tips

## Getting Help

If you encounter issues during migration:

1. Check this guide first
2. Review the main README.md
3. Open an issue on GitHub with:
   - Old version you were using
   - Error messages
   - Your .env configuration (without API keys)

## Timeline

- **Now**: Both `adp` and `gli` names work
- **Next release**: `gli` command available
- **Future**: `adp` command deprecated with warning
- **Eventually**: Only `gli` command supported

## FAQ

### Q: Do I need to migrate immediately?
A: No, `adp` will continue to work during the transition period.

### Q: Will my old prompts still work?
A: Yes, all prompts will work the same way.

### Q: Is GLI backward compatible?
A: Yes, the core API is the same, just with additional features.

### Q: Do I need to update my scripts?
A: Not immediately, but consider updating to use new model names for better performance.

### Q: What if I prefer the old default models?
A: Set them in your .env file:
```bash
LOCAL_CODER_MODEL=qwen2.5-coder:7b
LOCAL_GENERAL_MODEL=qwen2.5:7b
```