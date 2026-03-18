# GLI Upgrade Instructions for Coding Agents

This document contains all required changes to make Guided Local Intelligence (GLI)
perform at the level of cloud-grade coding agents (Codex, Claude Code, OpenClaw, etc.)
when running local Ollama models.

**Apply every change described below.** Each section identifies the target file, the
exact location of the change, and the replacement code. Do not skip sections — they
are interdependent.

---

## Prerequisites

### 1. Pull a capable base model

Run these shell commands before making any code changes:

```bash
ollama pull qwen2.5-coder:7b
```

If the host machine has less than 6 GB VRAM available, use the 3B variant instead:

```bash
ollama pull qwen2.5-coder:3b
```

### 2. Create a tuned Modelfile and register it with Ollama

Create a file called `Modelfile` in the repository root with this exact content:

```
FROM qwen2.5-coder:7b
PARAMETER num_ctx 8192
PARAMETER num_predict 2048
PARAMETER temperature 0.1
PARAMETER repeat_penalty 1.1
```

Then register the model:

```bash
ollama create gli-coder -f Modelfile
```

### 3. Add the `regex` crate to Cargo.toml

In `Cargo.toml`, inside the `[dependencies]` block, add:

```toml
regex = "1"
```

---

## File: `src/config.rs`

### Change: default model name

Find this line:

```rust
#[arg(long, default_value = "qwen2.5:1.5b")]
pub model: String,
```

Replace it with:

```rust
#[arg(long, default_value = "gli-coder")]
pub model: String,
```

---

## File: `src/agents.rs`

### Change 1: replace `GENERAL_AGENT_PRINCIPLES`

Find the entire constant definition:

```rust
const GENERAL_AGENT_PRINCIPLES: &str = r#"
GENERAL RULES:
- You are a production-grade general instruction-following agent.
- Your job is to complete exactly what the user asked, not just analyze.
- Break work into the smallest reliable units. Prefer many atomic steps over a few broad steps.
- Each step should do one thing, produce one concrete outcome, and reduce uncertainty.
- Never guess. If information is missing, inspect with tools or state the uncertainty explicitly.
- Use the path context only when it is relevant to the task.
- Prefer direct, verifiable outputs over speculation or filler.
- Keep replies compact so small local models stay accurate."#;
```

Replace it with:

```rust
const GENERAL_AGENT_PRINCIPLES: &str = r#"
RULES (follow exactly, no exceptions):
- Complete the task. Do not describe what you will do — do it immediately.
- Use one tool per reply. Wait for the result before calling the next tool.
- Never begin a reply with "I will now...", "Let me...", or "I'll...". Act.
- If you need file contents: read the file. If you need a fact: search it.
- Output only your concrete result or a single tool call JSON block.
- Do not repeat previous results back. Move forward every reply.
- Maximum prose before a tool call: two sentences.
- If a tool returns an error, try a different approach — do not repeat the same call.
- When done with a step, call write_memory with any key finding, path, or decision."#;
```

### Change 2: tighten the planner system prompt

Inside `planner_agent`, find the `system_prompt` format string. It currently ends with:

```rust
         \n- Do not combine multiple actions in one step.\
         \n- No explanations, headings, or prose outside the numbered list.\
         {TOOL_SCHEMA_BLOCK}"
```

Replace those final lines (keeping everything above them) with:

```rust
         \n- Do not combine multiple actions in one step.\
         \n- No explanations, headings, or prose outside the numbered list.\
         \n- Each step must be so small that a single tool call can complete it.\
         \n- Bad step: 'Analyze the codebase'. Good step: 'Read src/main.rs'.\
         \n- Bad step: 'Set up the environment'. Good step: 'Run cargo check and record errors'.\
         \n- Name the specific tool each step will use in parentheses, e.g. (read_file).\
         \n- If implementing a feature, decompose it: read existing code → locate insertion \
            point → write new code → verify it compiles. Never merge these into one step.\
         {TOOL_SCHEMA_BLOCK}"
```

Also change the step count guidance. Find:

```rust
         \n- Create 4-8 very small steps.\
```

Replace with:

```rust
         \n- Create 6-14 very small steps.\
```

### Change 3: tighten the executor system prompt

Inside `executor_agent`, find the `system_prompt` format string. It currently ends with:

```rust
         \n- Report in 2-5 short sentences. Include what was done, what was found, and any uncertainty.\
         {TOOL_SCHEMA_BLOCK}"
```

Replace those final two lines with:

```rust
         \n- Report in 2-5 short sentences: what was done, what was found, any uncertainty.\
         \n- If the step depends on a file path you are unsure about, call list_directory first.\
         \n- After completing the step successfully, call write_memory to save any important \
            finding. Use a short descriptive key like 'auth_file_path' or 'db_schema'.\
         \n- If this step fails, state the error clearly and suggest one alternative approach.\
         {TOOL_SCHEMA_BLOCK}"
```

### Change 4: increase context limits in text-only agents

Find the `verifier_agent` function. Change the truncation limit from 2000 to 4000:

```rust
// BEFORE
let trimmed: String = results.chars().take(2000).collect();

// AFTER
let trimmed: String = results.chars().take(4000).collect();
```

Find the `synthesizer_agent` function. Change the truncation limit from 2000 to 4000:

```rust
// BEFORE
let trimmed: String = verified_results.chars().take(2000).collect();

// AFTER
let trimmed: String = verified_results.chars().take(4000).collect();
```

Find the `reflection_agent` function. Change the truncation limit from 1500 to 2500:

```rust
// BEFORE
let trimmed: String = output.chars().take(1500).collect();

// AFTER
let trimmed: String = output.chars().take(2500).collect();
```

---

## File: `src/tools.rs` (new function — append to end of file)

Add the following function at the very end of `src/tools.rs`. It is a fallback tool-call
extractor for models that wrap JSON in markdown fences or use slight formatting variations:

```rust
/// Attempt to extract a JSON tool call from free-form model output.
/// Tries several common patterns small models use when they don't output raw JSON.
/// Returns None if no recognisable tool call structure is found.
pub fn extract_tool_call_from_text(text: &str) -> Option<serde_json::Value> {
    use regex::Regex;

    let patterns: &[&str] = &[
        r"(?s)```json\s*(\{.*?\})\s*```",
        r"(?s)```\s*(\{.*?\})\s*```",
        r"TOOL_CALL:\s*(\{.*?\})",
        r#"(?s)(\{"name"\s*:.*?"arguments"\s*:.*?\})"#,
        r#"(?s)(\{"name"\s*:.*?"arguments"\s*:\s*\{[^}]*\}\s*\})"#,
    ];

    for pattern in patterns {
        if let Ok(re) = Regex::new(pattern) {
            if let Some(cap) = re.captures(text) {
                let candidate = cap.get(1).map(|m| m.as_str()).unwrap_or("");
                if let Ok(val) = serde_json::from_str::<serde_json::Value>(candidate) {
                    if val.get("name").is_some() {
                        return Some(val);
                    }
                }
            }
        }
    }
    None
}
```

---

## File: `src/guidance_engine.rs`

### Change 1: add `extract_tool_call_from_text` to the imports at the top

Find the existing tools import:

```rust
use crate::task_requirements::{infer_task_requirements, TaskRequirements};
```

Add the following line immediately after it:

```rust
use crate::tools::extract_tool_call_from_text;
```

### Change 2: add a per-step retry with error context

Inside the `run` method, locate the step execution block. It currently looks like this
(simplified — match on the surrounding context to find the right location):

```rust
let result = self
    .run_agent_enforcing_tools(
        executor_agent(
            step,
            idx,
            steps.len(),
            &accumulated_context,
            self.path_context.as_deref(),
            &step_requirements,
            &self.model,
            &self.ollama_url,
            self.max_steps,
            memory.clone(),
        ),
        ToolEnforcement::for_execution(&step_requirements),
    )
    .await?;
```

Replace that entire block (from `let result =` through `.await?;`) with:

```rust
let result = {
    let first_attempt = self
        .run_agent_enforcing_tools(
            executor_agent(
                step,
                idx,
                steps.len(),
                &accumulated_context,
                self.path_context.as_deref(),
                &step_requirements,
                &self.model,
                &self.ollama_url,
                self.max_steps,
                memory.clone(),
            ),
            ToolEnforcement::for_execution(&step_requirements),
        )
        .await;

    match first_attempt {
        Ok(r) => r,
        Err(e) => {
            // One retry with explicit error context injected into the step
            let retry_step = format!(
                "{step}\n\nPREVIOUS ATTEMPT FAILED: {e}\n\
                 Try a different approach. If you need a file path, call \
                 list_directory first. If a tool call failed, change the \
                 arguments or use a different tool."
            );
            self.run_agent(executor_agent(
                &retry_step,
                idx,
                steps.len(),
                &accumulated_context,
                self.path_context.as_deref(),
                &step_requirements,
                &self.model,
                &self.ollama_url,
                self.max_steps,
                memory.clone(),
            ))
            .await?
        }
    }
};
```

### Change 3: persist clarification notes into shared memory

Inside the clarification loop, after the user confirms (the `break` after `yes`), add a
block that writes the clarification summary into shared memory so every downstream agent
can read it. Find the line:

```rust
break;
```

that follows the `if user_input.eq_ignore_ascii_case("y") || user_input.eq_ignore_ascii_case("yes")` check.
Replace it with:

```rust
// Write the confirmed clarification into shared memory so all agents can access it
if let Ok(mut mem) = memory.lock() {
    mem.insert(
        "task_clarification".to_string(),
        clarification.trim().to_string(),
    );
    mem.insert(
        "confirmed_task".to_string(),
        current_task.trim().to_string(),
    );
}
break;
```

---

## File: `src/context_summarizer.rs`

### Change: increase step summary length

Find:

```rust
let summary = if trimmed.len() > 150 {
    let first_part = &trimmed[..150];
```

Replace with:

```rust
let summary = if trimmed.len() > 300 {
    let first_part = &trimmed[..300];
```

Also find:

```rust
    format!("{}...", &trimmed[..77])
```

(inside `summarize_plan`) and replace with:

```rust
    format!("{}...", &trimmed[..120])
```

---

## New file: `scripts/check_ollama_tools.sh`

Create this file at `scripts/check_ollama_tools.sh` and make it executable
(`chmod +x scripts/check_ollama_tools.sh`). It lets you verify whether the active
Ollama model supports native tool calls before running GLI:

```bash
#!/usr/bin/env bash
# Usage: ./scripts/check_ollama_tools.sh [model_name]
# Checks whether the given Ollama model responds to native tool call schemas.
# If tool_calls is null, GLI falls back to prompt-injected JSON tool calling.

MODEL="${1:-gli-coder}"
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
```

---

## New file: `scripts/benchmark_model.sh`

Create this file at `scripts/benchmark_model.sh` and make it executable. It runs a
quick sanity check to compare the active model against a known-good task:

```bash
#!/usr/bin/env bash
# Usage: ./scripts/benchmark_model.sh [model_name]
# Runs a minimal tool-use task and prints whether the model returned structured output.

MODEL="${1:-gli-coder}"

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
```

---

## Updated `README.md` section — add under "Requirements"

In the existing `README.md`, find the "Requirements" section and add the following
after the existing bullet points:

```markdown
## Model Requirements

GLI requires a model with at least 7B parameters for reliable tool-use and
multi-step code tasks. The default model is `gli-coder`, a tuned version of
`qwen2.5-coder:7b`.

### Recommended models (in order of capability)

| Model | VRAM | Use case |
|---|---|---|
| `qwen2.5-coder:7b` (via `gli-coder`) | 6–8 GB | Default — coding + reasoning |
| `qwen2.5:7b` | 6–8 GB | General tasks, documentation |
| `qwen2.5-coder:3b` | 3–4 GB | Memory-constrained machines |
| `deepseek-coder:6.7b` | 5–6 GB | Alternative coding model |

### One-time setup

```bash
# Pull the base model
ollama pull qwen2.5-coder:7b

# Create the tuned variant with the correct context window and temperature
cat > Modelfile << 'EOF'
FROM qwen2.5-coder:7b
PARAMETER num_ctx 8192
PARAMETER num_predict 2048
PARAMETER temperature 0.1
PARAMETER repeat_penalty 1.1
EOF

ollama create gli-coder -f Modelfile

# Verify tool call support
./scripts/check_ollama_tools.sh gli-coder

# Run a quick benchmark
./scripts/benchmark_model.sh gli-coder
```

### Why these parameters matter

- `num_ctx 8192` — default Ollama context is 2048 tokens, which causes the model to
  forget earlier steps in long task chains. 8192 tokens covers a full GLI run.
- `temperature 0.1` — lower temperature makes small models more deterministic and
  reduces malformed JSON in tool call outputs.
- `repeat_penalty 1.1` — prevents the model from repeating the previous step's output
  verbatim instead of making progress.

## Verifying the upgrade

After applying all code changes and running `cargo build`, test with:

```bash
# Simple file task (tests executor + filesystem tools)
cargo run -- "list all Rust source files in this project and count the lines in each" --path .

# Multi-step reasoning task (tests planner + memory)
cargo run -- "find the largest function by line count in src/ and explain what it does" --path .

# Tool fallback test (tests retry logic)
cargo run -- "read the file at a/nonexistent/path.rs and handle the error" --path .
```

A successful run will show:
1. The `CLARIFY` stage producing a concrete task brief
2. The `PLAN` stage producing 6-14 numbered atomic steps
3. Each `EXECUTE` step calling exactly one tool per reply
4. `write_memory` calls after key findings
5. The `SYNTHESIZE` stage producing a coherent answer without repeating raw tool output
```

---

## Summary of all changes

| File | Change | Reason |
|---|---|---|
| `Modelfile` (new) | Sets context=8192, temp=0.1 | Prevent context overflow and format errors |
| `Cargo.toml` | Add `regex = "1"` | Required by tool-call fallback parser |
| `src/config.rs` | Default model → `gli-coder` | Use the tuned model automatically |
| `src/agents.rs` | Replace `GENERAL_AGENT_PRINCIPLES` | Remove vague directives; add action-forcing rules |
| `src/agents.rs` | Tighten planner system prompt | Force atomic steps with named tools |
| `src/agents.rs` | Tighten executor system prompt | Force `write_memory` and alternative-on-fail |
| `src/agents.rs` | Increase truncation limits | Prevent synthesizer losing key findings |
| `src/tools.rs` | Add `extract_tool_call_from_text` | Parse tool calls from imperfect model output |
| `src/guidance_engine.rs` | Import new extractor | Wire up the fallback parser |
| `src/guidance_engine.rs` | Per-step retry with error context | Recover from tool failures automatically |
| `src/guidance_engine.rs` | Write clarification to shared memory | Let all agents access the confirmed task |
| `src/context_summarizer.rs` | Increase step summary length | Preserve more context between stages |
| `scripts/check_ollama_tools.sh` (new) | Tool support diagnostic | Detect native vs prompt-based tool calling |
| `scripts/benchmark_model.sh` (new) | Model sanity check | Verify model behaviour before long runs |
| `README.md` | Add model requirements section | Document setup for new users and agents |
