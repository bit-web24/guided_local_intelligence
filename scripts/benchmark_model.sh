#!/usr/bin/env bash
# Usage: ./scripts/benchmark_model.sh [model_name]
# Runs a minimal tool-use task and prints whether the model returned structured output.

MODEL="${1:-gpt-oss:120b-cloud}"

echo "=== GLI Model Benchmark: $MODEL ==="
echo ""

# Test 1: does the model follow JSON-only instruction?
echo "[Test 1] JSON instruction following..."
RESPONSE=$(curl -s "http://localhost:11434/api/generate" -d "{
  \"model\": \"$MODEL\",
  \"stream\": false,
  \"prompt\": \"Output ONLY valid JSON. No prose. No markdown fences. Just the JSON object.\n\n{\\\"name\\\": \\\"list_directory\\\", \\\"arguments\\\": {\\\"path\\\": \\\"/tmp\\\"}}\",
  \"system\": \"You output only raw JSON. Never prose. Never fences.\"
}" | python3 -c "import sys,json; print(json.load(sys.stdin)['response'])" 2>/dev/null)

if echo "$RESPONSE" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  echo "  PASS — model returned parseable JSON"
else
  echo "  FAIL — model returned non-JSON output:"
  echo "  $RESPONSE"
fi

# Test 2: does the model obey step-by-step constraints?
echo ""
echo "[Test 2] Single-step constraint..."
RESPONSE=$(curl -s "http://localhost:11434/api/generate" -d "{
  \"model\": \"$MODEL\",
  \"stream\": false,
  \"prompt\": \"Execute step 1/3: Read the file at src/main.rs\nReturn only the result of this one step.\",
  \"system\": \"You execute exactly one step. You do not plan ahead or describe future steps.\"
}" | python3 -c "import sys,json; r=json.load(sys.stdin)['response']; print('PASS' if 'step 2' not in r.lower() and 'step 3' not in r.lower() else 'FAIL — model described future steps')" 2>/dev/null)
echo "  $RESPONSE"

echo ""
echo "=== Benchmark complete ==="
