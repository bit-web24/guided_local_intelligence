use crate::tools::{read_memory_tool, web_search_tool, write_memory_tool, SharedMemory};
use crate::task_requirements::TaskRequirements;
use agent_b::AgentBuilder;
use std::env;
use std::path::PathBuf;

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

  Filesystem MCP server tools:
    read_file(path: string)
    read_multiple_files(paths: string[])
    list_directory(path: string)
    directory_tree(path: string)
    search_files(path: string, pattern: string)
    get_file_info(path: string)
    list_allowed_directories()
                                        — Use these to inspect the local project.
  web_search    (query: string)         — Search the web via DuckDuckGo. Use when uncertain.
  write_memory  (key: str, value: str)  — Save an important finding to use in later steps.
  read_memory   (key: str)              — Retrieve a previously saved finding from memory.

HOW TO CALL A TOOL — output ONLY this JSON block, nothing else:
```json
{"name": "TOOL_NAME", "arguments": {"arg": "value"}}
```
Wait for the tool result before writing anything else.
If you do NOT need a tool right now, answer directly in plain text."#;

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

// ── Agent base constructors ───────────────────────────────────────────────────

/// Tool-using base: for agents that need to read files (Planner, Executor).
fn tool_agent(
    task: &str,
    path_context: Option<&str>,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
    mem: SharedMemory,
) -> AgentBuilder {
    let allowed_dir = resolve_allowed_dir(path_context);
    let mcp_args = vec![
        "-y".to_string(),
        "@modelcontextprotocol/server-filesystem".to_string(),
        allowed_dir,
    ];

    AgentBuilder::new(task)
        .ollama(ollama_url)
        .model(model)
        .max_steps(max_steps)
        .mcp_server("npx", &mcp_args)
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

/// PlannerAgent — creates a small, execution-ready plan for any user task.
pub fn planner_agent(
    task: &str,
    path_context: Option<&str>,
    requirements: &TaskRequirements,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
    mem: SharedMemory,
) -> AgentBuilder {
    let full_task = match path_context {
        Some(p) => format!(
            "Task:\n{task}\n\nOptional workspace path:\n{p}\n\n\
             Tool policy:\n{}\n\n\
             If the task depends on local files, inspect the workspace before planning.",
            requirements.describe_for_prompt()
        ),
        None => format!("Task:\n{task}\n\nTool policy:\n{}", requirements.describe_for_prompt()),
    };

    // Compact system prompt + explicit tool schema so small models know the format.
    let system_prompt = format!(
        "You are the planning stage of a general-purpose agent.\
         \n{GENERAL_AGENT_PRINCIPLES}\
         \nPLANNING RULES:\
         \n- Output ONLY a numbered list.\
         \n- Create 4-8 very small steps.\
         \n- Each step must be atomic, observable, and executable by one follow-up agent run.\
         \n- Put information-gathering before decisions, decisions before actions, and actions before final packaging.\
         \n- If local files are relevant, first inspect the workspace with tools before finalizing the plan.\
         \n- Do not combine multiple actions in one step.\
         \n- No explanations, headings, or prose outside the numbered list.\
         {TOOL_SCHEMA_BLOCK}"
    );

    tool_agent(
        &full_task,
        path_context,
        model,
        ollama_url,
        max_steps,
        mem,
    )
        .system_prompt(&system_prompt)
        .task_type("planning")
}

/// ExecutorAgent — executes exactly one micro-step. May use filesystem tools.
pub fn executor_agent(
    step: &str,
    step_num: usize,
    total_steps: usize,
    context: &str,
    path_context: Option<&str>,
    requirements: &TaskRequirements,
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
        Some(p) => format!("\nWorkspace path: \"{}\". Use this exact path when the task requires local files.\n", p),
        None => String::new(),
    };

    let full_task = format!(
        "Execute step {step_num}/{total_steps}: {step}{target_section}{ctx_section}\
         Tool policy:\n{}\n\n\
         Complete only this step. Use tools when needed. Return the concrete result of this step.",
        requirements.describe_for_prompt()
    );

    // Compact system prompt + explicit tool schema.
    let system_prompt = format!(
        "You are the execution stage of a general-purpose agent.\
         \n{GENERAL_AGENT_PRINCIPLES}\
         \nEXECUTION RULES:\
         \n- Execute exactly one step and do not drift into later steps.\
         \n- If the step depends on local files, inspect them with tools before concluding.\
         \n- If the step depends on outside facts, use web_search before concluding.\
         \n- Base claims only on tool output or the provided context.\
         \n- Report in 2-5 short sentences. Include what was done, what was found, and any uncertainty.\
         {TOOL_SCHEMA_BLOCK}"
    );

    tool_agent(
        &full_task,
        path_context,
        model,
        ollama_url,
        max_steps,
        mem,
    )
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
            "You are a verifier for a production-grade general agent. \
             Check for unsupported claims, missed constraints, and logical gaps. \
             Fix errors. Mark uncertain items with [?]. Return only the corrected text.",
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
            "You are the final response stage of a production-grade general instruction-following agent. \
             Write a direct markdown answer that completes the user's task. \
             Use short sections only when helpful. \
             Include assumptions or uncertainty only if they materially affect the result. \
             Do not mention internal stages, planning, or agent mechanics.",
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
         Rewrite this task into a precise execution brief for a general-purpose agent. \
         Resolve ambiguity where possible from the provided text, but do not invent missing facts. \
         Output ONLY the following format, nothing else:\n\n\
         **Understanding:** [One sentence: what the user wants]\n\
         **Goals:** [2-4 bullet points of concrete outcomes]\n\
         **Scope:** [What's included, excluded, and any important constraints]\n\
         **Questions:** [Remaining ambiguities or write 'None']\n\
         **Execution Strategy:** [One short sentence on how to approach this with very small reliable steps]"
    );

    text_agent(&full_task, model, ollama_url)
        .system_prompt(
            "You are the clarification stage of a production-grade general instruction-following agent. \
             Convert the user's request into a compact, actionable brief optimized for small local models. \
             Make the task concrete, constrained, and easy to decompose. \
             Output ONLY the requested format.",
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
            "You are a strict quality checker for a production-grade general agent. \
             Approve only if the output clearly satisfies the user's request. \
             If anything material is missing, say so briefly. \
             Your reply MUST end with DONE or REFINE:<reason>.",
        )
        .task_type("reflection")
}

fn resolve_allowed_dir(path_context: Option<&str>) -> String {
    let base = path_context
        .map(PathBuf::from)
        .or_else(|| env::current_dir().ok())
        .unwrap_or_else(|| PathBuf::from("."));

    base.canonicalize()
        .unwrap_or(base)
        .to_string_lossy()
        .into_owned()
}
