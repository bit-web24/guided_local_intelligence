#!/usr/bin/env bash
# Usage: ./scripts/check_ollama_tools.sh [model_name]
# Checks whether the given Ollama model responds to native tool call schemas.
# If tool_calls is null, GLI falls back to prompt-injected JSON tool calling.

MODEL="${1:-gpt-oss:120b-cloud}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

echo "Checking tool call support for model: $MODEL"

RESPONSE=$(curl -s "$OLLAMA_URL/api/chat" -d "{
  \"model\": \"$MODEL\",
  \"stream\": false,
  \"messages\": [{\"role\":\"user\",\"content\":\"List files in /tmp\"}],
  \"tools\": [{
    \"type\": \"function\",
    \"function\": {
      \"name\": \"list_dir\",
      \"description\": \"List files in a directory\",
      \"parameters\": {
        \"type\": \"object\",
        \"properties\": {\"path\": {\"type\": \"string\"}},
        \"required\": [\"path\"]
      }
    }
  }]
}")

TOOL_CALLS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message',{}).get('tool_calls'))" 2>/dev/null)

if [ "$TOOL_CALLS" = "None" ] || [ -z "$TOOL_CALLS" ]; then
  echo "RESULT: Native tool calls NOT supported — GLI will use prompt-injected JSON format."
  echo "        This is fine. Ensure TOOL_SCHEMA_BLOCK is present in all agent system prompts."
else
  echo "RESULT: Native tool calls SUPPORTED — $TOOL_CALLS"
fi
