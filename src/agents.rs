use crate::tools::{
    detect_language_tool, list_directory_tool, read_file_tool, read_memory_tool, scan_repo_tool,
    web_search_tool, write_memory_tool, SharedMemory,
};
use agent_b::AgentBuilder;

// ── Inline tool schema for small Ollama models ───────────────────────────────
//
// Ollama (localhost) never receives the native `tools[]` payload from Agent-B
// because small models return 400 errors on that schema.  Instead we inject an
// explicit, compact tool reference directly into every system prompt that uses
// tools, so the model knows exactly what to call and in what format.
//
// Format used — most compatible across Qwen, Llama, Mistral small models:
//
//   ```json
//   {"name": "tool_name", "arguments": {"arg": "value"}}
//   ```
//
// Agent-B's planning state already parses this JSON-block pattern.  We also
// support the `TOOL_CALL:` line pattern via the extended parser added to
// planning.rs.

const TOOL_SCHEMA_BLOCK: &str = r#"
AVAILABLE TOOLS — call one per reply when needed:

  scan_repo     (path: string)          — Recursively list all files in a directory tree.
  list_directory(path: string)          — List immediate children of a directory.
  read_file     (path: string)          — Read text content of a file (up to 4 KB).
  detect_language(path: string)         — Detect programming languages used in a project.
  web_search    (query: string)         — Search the web via DuckDuckGo. Use when uncertain.
  write_memory  (key: str, value: str)  — Save an important finding to use in later steps.
  read_memory   (key: str)              — Retrieve a previously saved finding from memory.

HOW TO CALL A TOOL — output ONLY this JSON block, nothing else:
```json
{"name": "TOOL_NAME", "arguments": {"arg": "value"}}
```
Wait for the tool result before writing anything else.
If you do NOT need a tool right now, answer directly in plain text."#;

// ── Agent base constructors ───────────────────────────────────────────────────

/// Tool-using base: for agents that need to read files (Planner, Executor).
fn tool_agent(
    task: &str,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
    mem: SharedMemory,
) -> AgentBuilder {
    AgentBuilder::new(task)
        .ollama(ollama_url)
        .model(model)
        .max_steps(max_steps)
        .add_tool(read_file_tool())
        .add_tool(list_directory_tool())
        .add_tool(scan_repo_tool())
        .add_tool(detect_language_tool())
        .add_tool(web_search_tool())
        .add_tool(read_memory_tool(mem.clone()))
        .add_tool(write_memory_tool(mem))
}

/// Text-only base: for agents that only reason over provided text (Verifier, Synthesizer, Reflector).
/// NO tools — prevents small models from looping on tool calls they don't need.
fn text_agent(task: &str, model: &str, ollama_url: &str) -> AgentBuilder {
    AgentBuilder::new(task)
        .ollama(ollama_url)
        .model(model)
        .max_steps(4) // Hard cap: these agents should finish in 1-2 LLM calls
}

// ── Agent factories ──────────────────────────────────────────────────────────

/// PlannerAgent — scans the path (if given), then outputs a numbered 3-5 step plan.
pub fn planner_agent(
    task: &str,
    path_context: Option<&str>,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
    mem: SharedMemory,
) -> AgentBuilder {
    let full_task = match path_context {
        Some(p) => format!(
            "First call scan_repo with path=\"{p}\" to see the project. \
             Then make a numbered plan (1,2,3,4,... steps) to accomplish:\n{task}"
        ),
        None => format!("Make a numbered plan (1,2,3,4,... steps) to accomplish:\n{task}"),
    };

    // Compact system prompt + explicit tool schema so small models know the format.
    let system_prompt = format!(
        "You are a planner. Output ONLY a numbered list of 3-5 short steps.\
         \nCRITICAL: DO NOT GUESS OR ASSUME. If you need information about the project, you MUST plan to use tools to read it.\
         \nUse tools to read the project first if a path is given.\
         \nNo prose, no explanations. Just the numbered list.\
         {TOOL_SCHEMA_BLOCK}"
    );

    tool_agent(&full_task, model, ollama_url, max_steps, mem)
        .system_prompt(&system_prompt)
        .task_type("planning")
}

/// ExecutorAgent — executes exactly one step. May use filesystem tools.
pub fn executor_agent(
    step: &str,
    step_num: usize,
    total_steps: usize,
    context: &str,
    path_context: Option<&str>,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
    mem: SharedMemory,
) -> AgentBuilder {
    let ctx_section = if context.is_empty() {
        String::new()
    } else {
        // Truncate context to keep the prompt short for small models
        let trimmed: String = context.chars().take(800).collect();
        format!("\nPrevious results:\n{trimmed}\n")
    };

    let target_section = match path_context {
        Some(p) => format!("\nIMPORTANT: Your target project path is \"{}\". Use this exact path in your tool calls when examining the project.\n", p),
        None => String::new(),
    };

    let full_task = format!(
        "Execute step {step_num}/{total_steps}: {step}{target_section}{ctx_section}\
         Use a tool if you need to read or list files. Report what you found."
    );

    // Compact system prompt + explicit tool schema.
    let system_prompt = format!(
        "You are an executor. Do exactly what the step says.\
         \nCRITICAL: DO NOT GUESS OR MAKE ASSUMPTIONS. If you are asked about the code, you MUST use read_file or list_directory to look at it first.\
         \nReport in 2-4 sentences. Be factual and concise based ONLY on tool output.\
         {TOOL_SCHEMA_BLOCK}"
    );

    tool_agent(&full_task, model, ollama_url, max_steps, mem)
        .system_prompt(&system_prompt)
        .task_type("execution")
}

/// VerifierAgent — text-only; checks provided results for errors.
pub fn verifier_agent(results: &str, model: &str, ollama_url: &str) -> AgentBuilder {
    // Truncate to keep prompt manageable for small models
    let trimmed: String = results.chars().take(2000).collect();
    let full_task = format!(
        "Review these results. Fix errors and hallucinations. \
         Mark uncertain claims with [?]. Return the corrected version:\n\n{trimmed}"
    );

    text_agent(&full_task, model, ollama_url)
        .system_prompt(
            "You are a verifier. Fix errors in the results. \
             Mark uncertain items [?]. Return only the corrected text.",
        )
        .task_type("verification")
}

/// SynthesizerAgent — text-only; writes the final structured report.
pub fn synthesizer_agent(
    verified_results: &str,
    original_task: &str,
    model: &str,
    ollama_url: &str,
) -> AgentBuilder {
    let trimmed: String = verified_results.chars().take(2000).collect();
    let full_task = format!(
        "Write a clear markdown answer for: \"{original_task}\"\
         \nBased on these findings:\n{trimmed}"
    );

    text_agent(&full_task, model, ollama_url)
        .system_prompt(
            "You are a report writer. Write a clear markdown answer with ## headings and bullets.\
             \nBe complete. Answer the task directly.",
        )
        .task_type("synthesis")
}

/// ClarifierAgent — text-only; rephrases and expands the user prompt for clarity.
pub fn clarifier_agent(
    task: &str,
    path_context: Option<&str>,
    model: &str,
    ollama_url: &str,
) -> AgentBuilder {
    let context_note = match path_context {
        Some(p) => format!("\nProject path: {}", p),
        None => String::new(),
    };

    let full_task = format!(
        "Task: {task}{context_note}\n\n\
         Rephrase this task clearly and concisely. Output ONLY the following format, nothing else:\n\n\
         **Understanding:** [One sentence: what the user wants]\n\
         **Goals:** [2-3 bullet points of specific goals]\n\
         **Scope:** [What's included and not included]\n\
         **Questions:** [Any ambiguities? List them or write 'None']"
    );

    text_agent(&full_task, model, ollama_url)
        .system_prompt(
            "You are a task clarifier. Output ONLY the requested format. Be direct and concise. Do not explain, do not add extra text.",
        )
        .task_type("clarification")
}

/// ReflectionAgent — text-only; MUST end with DONE or REFINE:<reason>.
pub fn reflection_agent(
    output: &str,
    original_task: &str,
    model: &str,
    ollama_url: &str,
) -> AgentBuilder {
    let trimmed: String = output.chars().take(1500).collect();
    let full_task = format!(
        "Task: \"{original_task}\"\
         \nOutput:\n{trimmed}\
         \nDoes this output fully answer the task?\
         \nEnd your reply with exactly one of:\
         \nDONE\
         \nREFINE: <one sentence saying what is missing>"
    );

    text_agent(&full_task, model, ollama_url)
        .system_prompt(
            "You are a quality checker. Does the output fully address the task?\
             \nYour reply MUST end with DONE or REFINE:<reason>.",
        )
        .task_type("reflection")
}
