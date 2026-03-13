use agent_b::AgentBuilder;
use crate::tools::{detect_language_tool, list_directory_tool, read_file_tool, scan_repo_tool};

/// Shared base: Ollama-backed agent with all filesystem tools registered.
fn base_agent(task: &str, model: &str, ollama_url: &str, max_steps: usize) -> AgentBuilder {
    AgentBuilder::new(task)
        .ollama(ollama_url)
        .model(model)
        .max_steps(max_steps)
        .add_tool(read_file_tool())
        .add_tool(list_directory_tool())
        .add_tool(scan_repo_tool())
        .add_tool(detect_language_tool())
}

// ── Agent factories ──────────────────────────────────────────────────────────

/// PlannerAgent — produces a numbered list of 3-5 concrete steps.
/// When a path is provided it MUST scan it first, then plan based on findings.
pub fn planner_agent(
    task: &str,
    path_context: Option<&str>,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
) -> AgentBuilder {
    // When a path is given, prepend a mandatory scan instruction so the
    // small model reads the filesystem BEFORE deciding what the plan is.
    let full_task = match path_context {
        Some(p) => format!(
            "First call scan_repo with path=\"{p}\" to see the project. \
             Then make a numbered plan (3-5 steps) to accomplish:\n{task}"
        ),
        None => format!(
            "Make a numbered plan (3-5 short steps) to accomplish:\n{task}"
        ),
    };

    let system_prompt =
        "You are a planner. Output ONLY a numbered list of 3-5 short steps.\
         \nUse tools to read the project first if a path is given.\
         \nNo prose, no explanations. Just the numbered list.";

    base_agent(&full_task, model, ollama_url, max_steps)
        .system_prompt(system_prompt)
        .task_type("planning")
}

/// ExecutorAgent — executes exactly one step from the plan.
pub fn executor_agent(
    step: &str,
    step_num: usize,
    total_steps: usize,
    context: &str,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
) -> AgentBuilder {
    let ctx_section = if context.is_empty() {
        String::new()
    } else {
        format!("\nContext from previous steps:\n{context}\n")
    };

    let full_task = format!(
        "Execute step {step_num}/{total_steps}: {step}{ctx_section}\
         Use a tool if you need to read files or list directories. \
         Report only what you found."
    );

    let system_prompt =
        "You are an executor. Do exactly what the step says.\
         \nUse read_file or list_directory if you need to look at files.\
         \nReport your findings in 2-4 sentences. Be factual.";

    base_agent(&full_task, model, ollama_url, max_steps)
        .system_prompt(system_prompt)
        .task_type("execution")
}

/// VerifierAgent — checks results for obvious errors or gaps.
pub fn verifier_agent(
    results: &str,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
) -> AgentBuilder {
    let full_task = format!(
        "Review these results. Fix errors, remove hallucinations, mark uncertain claims with [?].\
         \nReturn the corrected results only:\n\n{results}"
    );

    let system_prompt =
        "You are a verifier. Fix errors and hallucinations in the results.\
         \nMark uncertain items with [?]. Return only the corrected version.";

    base_agent(&full_task, model, ollama_url, max_steps)
        .system_prompt(system_prompt)
        .task_type("verification")
}

/// SynthesizerAgent — merges verified results into a clean final report.
pub fn synthesizer_agent(
    verified_results: &str,
    original_task: &str,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
) -> AgentBuilder {
    let full_task = format!(
        "Write a clear answer for: \"{original_task}\"\
         \nBased on these findings:\n{verified_results}"
    );

    let system_prompt =
        "You are a report writer. Create a clear, structured markdown report.\
         \nUse ## headings and bullet points. Answer the task completely.";

    base_agent(&full_task, model, ollama_url, max_steps)
        .system_prompt(system_prompt)
        .task_type("synthesis")
}

/// ReflectionAgent — rates the output and returns DONE or REFINE:<reason>.
pub fn reflection_agent(
    output: &str,
    original_task: &str,
    model: &str,
    ollama_url: &str,
    max_steps: usize,
) -> AgentBuilder {
    let full_task = format!(
        "Task: \"{original_task}\"\
         \nOutput:\n{output}\
         \nDoes this output fully answer the task?\
         \nEnd your reply with exactly one of:\
         \nDONE\
         \nREFINE: <one sentence saying what is missing>"
    );

    let system_prompt =
        "You are a quality checker. Answer: does the output fully address the task?\
         \nYour reply MUST end with DONE or REFINE:<reason>. Nothing after that line.";

    base_agent(&full_task, model, ollama_url, max_steps)
        .system_prompt(system_prompt)
        .task_type("reflection")
}
