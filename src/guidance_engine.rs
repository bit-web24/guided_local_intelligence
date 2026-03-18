use anyhow::Result;
use colored::Colorize;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use crate::agents::{
    clarifier_agent, executor_agent, planner_agent, reflection_agent, synthesizer_agent,
    verifier_agent,
};
use crate::context_summarizer::ContextSummarizer;
use crate::task_requirements::{infer_task_requirements, TaskRequirements};
use crate::tools::extract_tool_call_from_text;
use agent_b::HistoryEntry;

pub struct GuidanceEngine {
    pub model: String,
    pub ollama_url: String,
    pub max_loops: usize,
    pub max_steps: usize,
    pub path_context: Option<String>,
}

const PROGRESS_STATE_MARKER: &str = "\n--- GLI_RESUME_STATE ---\n";

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct ProgressState {
    original_task: String,
    current_task: String,
    status: String,
    stage: String,
    loop_index: usize,
    step_index: Option<usize>,
    total_steps: Option<usize>,
    clarification_notes: Vec<String>,
    clarification_summary: String,
    plan_summary: String,
    execution_summary: String,
    verification_summary: String,
    synthesis_summary: String,
    final_output: String,
    last_error: String,
    updated_at: String,
    transcript: String,
}

impl GuidanceEngine {
    pub fn new(
        model: impl Into<String>,
        ollama_url: impl Into<String>,
        max_loops: usize,
        max_steps: usize,
        path_context: Option<String>,
    ) -> Self {
        Self {
            model: model.into(),
            ollama_url: ollama_url.into(),
            max_loops,
            max_steps,
            path_context,
        }
    }

    /// Run the Progressive Guidance Loop for the given task.
    /// Returns the final synthesized answer.
    pub async fn run(&self, task: &str) -> Result<String> {
        let start_time = std::time::Instant::now();
        let mut current_task = task.to_string();
        let mut final_output = String::new();
        let task_requirements = infer_task_requirements(task, self.path_context.as_deref());
        let mut progress = self
            .load_progress(task)
            .unwrap_or_else(|| ProgressState::new(task));
        let resumed_from_progress = progress.should_resume(task);

        // The exact SharedMemory structure defined in tools.rs
        type SharedMemory = Arc<Mutex<HashMap<String, String>>>;
        let memory: SharedMemory = Arc::new(Mutex::new(HashMap::new()));

        if resumed_from_progress {
            current_task = progress.current_task.clone();
            let resume_message = format!(
                "Resuming from {} at stage {}.",
                self.progress_path()?.display(),
                progress.stage
            );
            println!("{}", resume_message.yellow().bold());
            self.append_progress_text(&mut progress, &format!("\n{resume_message}\n"))?;
        }

        let run_result: Result<String> = async {
            progress.status = "in_progress".to_string();
            progress.current_task = current_task.clone();
            self.write_progress(&progress)?;

            // ── Stage 0: CLARIFY (one-time, before any loops) ──────────────────
            if !(resumed_from_progress && progress.stage != "CLARIFY") {
                self.print_stage("CLARIFY", None);
                self.append_progress_text(
                    &mut progress,
                    &format!("\n{}\n", stage_line("CLARIFY", None)),
                )?;
                let mut clarification_loop_count = 0;
                let max_clarification_loops = 3;
                let mut clarification_notes = progress.clarification_notes.clone();

                loop {
                    progress.stage = "CLARIFY".to_string();
                    progress.current_task = current_task.clone();
                    progress.clarification_notes = clarification_notes.clone();
                    self.write_progress(&progress)?;

                    let clarification = self
                        .run_agent(clarifier_agent(
                            &current_task,
                            self.path_context.as_deref(),
                            &self.model,
                            &self.ollama_url,
                        ))
                        .await?;
                    println!("{}", clarification.trim().dimmed());
                    self.append_progress_text(&mut progress, clarification.trim())?;
                    println!();
                    println!("{}", "Compact task brief:".yellow().bold());
                    let clarification_summary =
                        ContextSummarizer::summarize_clarification(&clarification);
                    println!("{}", clarification_summary.trim().dimmed());
                    self.append_progress_text(
                        &mut progress,
                        &format!(
                            "\nCompact task brief:\n{}\n",
                            clarification_summary.trim()
                        ),
                    )?;

                    progress.clarification_summary = clarification_summary;
                    self.write_progress(&progress)?;

                    let quick_plan = self
                        .run_agent(planner_agent(
                            &current_task,
                            self.path_context.as_deref(),
                            &task_requirements,
                            &self.model,
                            &self.ollama_url,
                            self.max_steps,
                            memory.clone(),
                        ))
                        .await?;
                    let quick_plan_summary = ContextSummarizer::summarize_plan(&quick_plan);

                    println!();
                    println!("{}", "Compact plan preview:".yellow().bold());
                    println!("{}", quick_plan_summary.trim().dimmed());
                    self.append_progress_text(
                        &mut progress,
                        &format!("\nCompact plan preview:\n{}\n", quick_plan_summary.trim()),
                    )?;

                    progress.plan_summary = quick_plan_summary.clone();
                    self.write_progress(&progress)?;

                    println!();
                    println!("{}", "Does this match what you want to do?".bold().yellow());
                    println!(
                        "{}",
                        "(type 'yes' or 'y' to continue, anything else to clarify and replan)"
                            .dimmed()
                    );
                    self.append_progress_text(
                        &mut progress,
                        "Does this match what you want to do?\n(type 'yes' or 'y' to continue, anything else to clarify and replan)",
                    )?;
                    print!("{} ", "→".yellow().bold());
                    io::stdout().flush()?;

                    let mut user_input = String::new();
                    io::stdin().read_line(&mut user_input)?;
                    let user_input = user_input.trim();
                    self.append_progress_text(&mut progress, &format!("→ {}", user_input))?;

                    if user_input.eq_ignore_ascii_case("y")
                        || user_input.eq_ignore_ascii_case("yes")
                    {
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
                    } else if !user_input.is_empty() {
                        clarification_loop_count += 1;
                        clarification_notes.push(user_input.to_string());
                        progress.clarification_notes = clarification_notes.clone();
                        current_task = format!(
                            "{}\n\nUser clarifications:\n{}",
                            task,
                            clarification_notes
                                .iter()
                                .enumerate()
                                .map(|(idx, note)| format!("{}. {}", idx + 1, note))
                                .collect::<Vec<_>>()
                                .join("\n")
                        );
                        progress.current_task = current_task.clone();
                        self.write_progress(&progress)?;

                        println!(
                            "\n{}",
                            "Replanning with your clarification...".yellow().italic()
                        );
                        self.append_progress_text(
                            &mut progress,
                            "\nReplanning with your clarification...",
                        )?;

                        if clarification_loop_count >= max_clarification_loops {
                            println!(
                                "{}",
                                "Clarification limit reached. Proceeding with the latest replanned task."
                                    .yellow()
                            );
                            self.append_progress_text(
                                &mut progress,
                                "Clarification limit reached. Proceeding with the latest replanned task.",
                            )?;
                            break;
                        }
                    } else {
                        println!("\n{}", "Proceeding...".yellow());
                        self.append_progress_text(&mut progress, "\nProceeding...")?;
                        break;
                    }
                }
            }

            println!("\n{}", "Proceeding with task...".green().bold());
            self.append_progress_text(&mut progress, "\nProceeding with task...\n")?;

            for loop_idx in progress.loop_index..self.max_loops {
                if loop_idx > 0 {
                    let loop_message =
                        format!("  ↻  Loop {} of {} — refining…", loop_idx + 1, self.max_loops);
                    println!("\n{}", loop_message.yellow().bold());
                    self.append_progress_text(&mut progress, &format!("\n{loop_message}\n"))?;
                }

                progress.stage = "PLAN".to_string();
                progress.loop_index = loop_idx;
                progress.step_index = None;
                progress.total_steps = None;
                progress.current_task = current_task.clone();
                self.write_progress(&progress)?;
                self.print_stage("PLAN", None);
                self.append_progress_text(
                    &mut progress,
                    &format!("\n{}\n", stage_line("PLAN", None)),
                )?;
                let plan = self
                    .run_agent_enforcing_tools(
                        planner_agent(
                            &current_task,
                            self.path_context.as_deref(),
                            &task_requirements,
                            &self.model,
                            &self.ollama_url,
                            self.max_steps,
                            memory.clone(),
                        ),
                        ToolEnforcement::for_planning(&task_requirements),
                    )
                    .await?;
                println!("{}", plan.trim().dimmed());
                self.append_progress_text(&mut progress, plan.trim())?;

                let steps = parse_steps(&plan);
                let plan_summary = ContextSummarizer::summarize_plan(&plan);
                progress.plan_summary = plan_summary.clone();
                self.write_progress(&progress)?;

                progress.stage = "EXECUTE".to_string();
                progress.execution_summary.clear();
                self.write_progress(&progress)?;
                self.print_stage("EXECUTE", None);
                self.append_progress_text(
                    &mut progress,
                    &format!("\n{}\n", stage_line("EXECUTE", None)),
                )?;
                let mut accumulated_context = plan_summary.clone();
                let mut step_summaries: Vec<String> = Vec::new();

                for (i, step) in steps.iter().enumerate() {
                    let idx = i + 1;
                    progress.step_index = Some(idx);
                    progress.total_steps = Some(steps.len());
                    progress.execution_summary =
                        ContextSummarizer::summarize_execution(&step_summaries);
                    self.write_progress(&progress)?;
                    self.print_stage("EXECUTE", Some(&format!("step {}/{}", idx, steps.len())));
                    self.append_progress_text(
                        &mut progress,
                        &format!(
                            "\n{}\n  → {}\n",
                            stage_line("EXECUTE", Some(&format!("step {}/{}", idx, steps.len()))),
                            step
                        ),
                    )?;
                    println!("{}", format!("  → {}", step).cyan());

                    let step_requirements = requirements_for_step(
                        step,
                        &task_requirements,
                        self.path_context.as_deref(),
                    );
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

                    println!("{}", result.trim().dimmed());
                    self.append_progress_text(&mut progress, result.trim())?;

                    let step_summary = ContextSummarizer::summarize_step_result(&result, idx);
                    step_summaries.push(step_summary.clone());
                    accumulated_context.push_str(&format!("{}\n", step_summary));
                    progress.execution_summary =
                        ContextSummarizer::summarize_execution(&step_summaries);
                    self.write_progress(&progress)?;
                }

                progress.stage = "VERIFY".to_string();
                progress.step_index = None;
                self.write_progress(&progress)?;
                self.print_stage("VERIFY", None);
                self.append_progress_text(
                    &mut progress,
                    &format!("\n{}\n", stage_line("VERIFY", None)),
                )?;
                let verification_input =
                    ContextSummarizer::summarize_for_verification(&plan_summary, &step_summaries);
                let verified = self
                    .run_agent(verifier_agent(
                        &verification_input,
                        &self.model,
                        &self.ollama_url,
                    ))
                    .await?;
                println!("{}", verified.trim().dimmed());
                self.append_progress_text(&mut progress, verified.trim())?;

                let verification_summary = ContextSummarizer::summarize_verification(&verified);
                progress.verification_summary = verification_summary.clone();
                self.write_progress(&progress)?;

                progress.stage = "SYNTHESIZE".to_string();
                self.write_progress(&progress)?;
                self.print_stage("SYNTHESIZE", None);
                self.append_progress_text(
                    &mut progress,
                    &format!("\n{}\n", stage_line("SYNTHESIZE", None)),
                )?;
                let synthesized = self
                    .run_agent(synthesizer_agent(
                        &verification_summary,
                        task,
                        &self.model,
                        &self.ollama_url,
                    ))
                    .await?;
                println!("{}", synthesized.trim().dimmed());
                self.append_progress_text(&mut progress, synthesized.trim())?;
                final_output = synthesized.clone();

                let synthesis_summary = ContextSummarizer::summarize_synthesis(&synthesized);
                progress.synthesis_summary = synthesis_summary.clone();
                progress.final_output = final_output.clone();
                self.write_progress(&progress)?;

                progress.stage = "REFLECT".to_string();
                self.write_progress(&progress)?;
                self.print_stage("REFLECT", None);
                self.append_progress_text(
                    &mut progress,
                    &format!("\n{}\n", stage_line("REFLECT", None)),
                )?;
                let reflection = self
                    .run_agent(reflection_agent(
                        &synthesis_summary,
                        task,
                        &self.model,
                        &self.ollama_url,
                    ))
                    .await?;
                println!("{}", reflection.trim().dimmed());
                self.append_progress_text(&mut progress, reflection.trim())?;

                if is_done(&reflection) {
                    let done_message = "  ✓  DONE — output accepted.";
                    println!("\n{}", done_message.green().bold());
                    self.append_progress_text(&mut progress, &format!("\n{done_message}"))?;
                    progress.status = "completed".to_string();
                    progress.stage = "COMPLETED".to_string();
                    progress.final_output = final_output.clone();
                    self.write_progress(&progress)?;
                    break;
                } else {
                    let reason = extract_refine_reason(&reflection);
                    let refine_message = format!("  ↻  REFINE — {}", reason);
                    println!("\n{}", refine_message.yellow());
                    self.append_progress_text(&mut progress, &format!("\n{refine_message}"))?;
                    current_task = format!(
                        "{}\n\nPrevious answer was incomplete because: {}\nImprove it.",
                        task, reason
                    );
                    progress.current_task = current_task.clone();
                    self.write_progress(&progress)?;
                }
            }

            let elapsed = start_time.elapsed();
            let elapsed_message =
                format!("  ⏱  Total Execution Time: {:.1} seconds", elapsed.as_secs_f64());
            println!("\n{}", elapsed_message.cyan().bold());
            self.append_progress_text(&mut progress, &format!("\n{elapsed_message}"))?;

            Ok(final_output)
        }
        .await;

        match run_result {
            Ok(output) => {
                self.clear_progress()?;
                Ok(output)
            }
            Err(e) => {
                progress.status = "failed".to_string();
                progress.current_task = current_task;
                progress.last_error = e.to_string();
                let error_message = format!("\nERROR: {}", progress.last_error);
                let _ = self.append_progress_text(&mut progress, &error_message);
                let _ = self.write_progress(&progress);
                Err(e)
            }
        }
    }

    fn progress_path(&self) -> Result<PathBuf> {
        Ok(std::env::current_dir()?.join("progress.txt"))
    }

    fn load_progress(&self, task: &str) -> Option<ProgressState> {
        let path = self.progress_path().ok()?;
        let content = fs::read_to_string(path).ok()?;
        let (_, state_blob) = content.split_once(PROGRESS_STATE_MARKER)?;
        let state: ProgressState = serde_json::from_str(state_blob).ok()?;
        if state.should_resume(task) {
            Some(state)
        } else {
            None
        }
    }

    fn write_progress(&self, progress: &ProgressState) -> Result<()> {
        let path = self.progress_path()?;
        let mut snapshot = progress.clone();
        snapshot.updated_at = chrono::Local::now().to_rfc3339();
        let state_blob = serde_json::to_string_pretty(&snapshot)?;
        let transcript = snapshot.transcript.trim_end();
        let content = if transcript.is_empty() {
            format!("{PROGRESS_STATE_MARKER}{state_blob}")
        } else {
            format!("{transcript}{PROGRESS_STATE_MARKER}{state_blob}")
        };
        fs::write(path, content)?;
        Ok(())
    }

    fn clear_progress(&self) -> Result<()> {
        let path = self.progress_path()?;
        if path.exists() {
            fs::remove_file(path)?;
        }
        Ok(())
    }

    fn append_progress_text(&self, progress: &mut ProgressState, text: &str) -> Result<()> {
        progress.transcript.push_str(text);
        if !text.ends_with('\n') {
            progress.transcript.push('\n');
        }
        self.write_progress(progress)
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    fn print_stage(&self, stage: &str, detail: Option<&str>) {
        let label = match detail {
            Some(d) => format!(" [{}] {} ", stage, d),
            None => format!(" [{}] ", stage),
        };
        let dashes = "━".repeat(50usize.saturating_sub(label.len()));
        let line = format!("{}{}", label, dashes);
        let colored_line = match stage {
            "PLAN" => line.bright_blue().bold().to_string(),
            "EXECUTE" => line.bright_cyan().bold().to_string(),
            "VERIFY" => line.bright_yellow().bold().to_string(),
            "SYNTHESIZE" => line.bright_magenta().bold().to_string(),
            "REFLECT" => line.bright_green().bold().to_string(),
            _ => line.white().bold().to_string(),
        };
        println!("\n{}", colored_line);
    }

    async fn run_agent(&self, builder: agent_b::AgentBuilder) -> Result<String> {
        let mut engine = builder.build()?;
        let answer = engine.run().await?;
        Ok(answer)
    }

    async fn run_agent_enforcing_tools(
        &self,
        builder: agent_b::AgentBuilder,
        enforcement: ToolEnforcement,
    ) -> Result<String> {
        let mut engine = builder.build()?;
        let answer = engine.run().await?;
        let _ = extract_tool_call_from_text(&answer);

        if let Some(reason) = missing_required_tool_use(&engine.memory.history, &enforcement) {
            anyhow::bail!(reason);
        }

        Ok(answer)
    }
}

#[derive(Debug, Clone, Copy, Default)]
struct ToolEnforcement {
    require_filesystem: bool,
    require_web_search: bool,
}

impl ToolEnforcement {
    fn for_planning(requirements: &TaskRequirements) -> Self {
        Self {
            require_filesystem: requirements.require_filesystem_before_planning,
            require_web_search: false,
        }
    }

    fn for_execution(requirements: &TaskRequirements) -> Self {
        Self {
            require_filesystem: requirements.require_filesystem_tools,
            require_web_search: requirements.require_web_search,
        }
    }
}

impl ProgressState {
    fn new(task: &str) -> Self {
        Self {
            original_task: task.to_string(),
            current_task: task.to_string(),
            status: "in_progress".to_string(),
            stage: "CLARIFY".to_string(),
            updated_at: chrono::Local::now().to_rfc3339(),
            ..Self::default()
        }
    }

    fn should_resume(&self, task: &str) -> bool {
        self.original_task.trim() == task.trim()
            && !self.current_task.trim().is_empty()
            && self.status != "completed"
    }
}

// ── Pure helpers ─────────────────────────────────────────────────────────────

/// Parse any numbered or bullet-point list from the planner output.
fn parse_steps(plan: &str) -> Vec<String> {
    let steps: Vec<String> = plan
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| {
            !l.is_empty()
                && (l.starts_with(|c: char| c.is_ascii_digit())
                    || l.starts_with('-')
                    || l.starts_with('•')
                    || l.starts_with('*'))
        })
        .collect();

    if steps.is_empty() {
        // Fallback: every non-empty line becomes a step
        plan.lines()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty())
            .collect()
    } else {
        steps
    }
}

fn is_done(reflection: &str) -> bool {
    match reflection_terminal_decision(reflection) {
        ReflectionDecision::Done => true,
        ReflectionDecision::Refine | ReflectionDecision::Unknown => false,
    }
}

fn extract_refine_reason(reflection: &str) -> String {
    if let ReflectionDecision::Refine = reflection_terminal_decision(reflection) {
        if let Some(last_line) = reflection
            .lines()
            .rev()
            .map(str::trim)
            .find(|line| !line.is_empty())
        {
            if let Some(reason) = last_line.strip_prefix("REFINE:") {
                let reason = reason.trim();
                if !reason.is_empty() {
                    return reason.to_string();
                }
            }
        }
    }

    for line in reflection.lines() {
        let upper = line.to_uppercase();
        if let Some(pos) = upper.find("REFINE:") {
            let after = line[pos + "REFINE:".len()..].trim().to_string();
            if !after.is_empty() {
                return after;
            }
        }
    }
    reflection
        .lines()
        .rev()
        .find(|l| !l.trim().is_empty())
        .unwrap_or("output needs improvement")
        .trim()
        .to_string()
}

enum ReflectionDecision {
    Done,
    Refine,
    Unknown,
}

fn reflection_terminal_decision(reflection: &str) -> ReflectionDecision {
    let Some(last_line) = reflection
        .lines()
        .rev()
        .map(str::trim)
        .find(|line| !line.is_empty())
    else {
        return ReflectionDecision::Unknown;
    };

    if last_line.eq_ignore_ascii_case("DONE") {
        return ReflectionDecision::Done;
    }

    if last_line.len() >= "REFINE:".len()
        && last_line[.. "REFINE:".len()].eq_ignore_ascii_case("REFINE:")
    {
        return ReflectionDecision::Refine;
    }

    ReflectionDecision::Unknown
}

fn stage_line(stage: &str, detail: Option<&str>) -> String {
    let label = match detail {
        Some(d) => format!(" [{}] {} ", stage, d),
        None => format!(" [{}] ", stage),
    };
    let dashes = "━".repeat(50usize.saturating_sub(label.len()));
    format!("{}{}", label, dashes)
}

fn requirements_for_step(
    step: &str,
    base: &TaskRequirements,
    path_context: Option<&str>,
) -> TaskRequirements {
    let mut req = base.clone();
    let step_lower = step.to_lowercase();

    if !base.require_filesystem_tools && path_context.is_some() {
        req.require_filesystem_tools = contains_any(
            &step_lower,
            &[
                "project",
                "repo",
                "repository",
                "code",
                "codebase",
                "file",
                "files",
                "workspace",
                "implementation",
            ],
        );
    }

    if !base.require_web_search {
        req.require_web_search = contains_any(
            &step_lower,
            &[
                "latest",
                "current",
                "recent",
                "today",
                "official docs",
                "documentation",
                "web",
                "internet",
                "external",
                "online",
            ],
        );
    }

    req
}

fn missing_required_tool_use(
    history: &[HistoryEntry],
    enforcement: &ToolEnforcement,
) -> Option<String> {
    if enforcement.require_filesystem && !used_filesystem_tool(history) {
        return Some(
            "Mandatory filesystem tool use was required by task policy, but the agent answered without any successful filesystem inspection.".to_string(),
        );
    }

    if enforcement.require_web_search && !used_web_search(history) {
        return Some(
            "Mandatory web search was required by task policy, but the agent answered without any successful web lookup.".to_string(),
        );
    }

    None
}

fn used_filesystem_tool(history: &[HistoryEntry]) -> bool {
    history
        .iter()
        .any(|entry| entry.success && is_filesystem_tool(&entry.tool.name))
}

fn used_web_search(history: &[HistoryEntry]) -> bool {
    history
        .iter()
        .any(|entry| entry.success && entry.tool.name == "web_search")
}

fn is_filesystem_tool(tool_name: &str) -> bool {
    matches!(
        tool_name,
        "read_file"
            | "read_multiple_files"
            | "list_directory"
            | "directory_tree"
            | "search_files"
            | "get_file_info"
            | "list_allowed_directories"
    )
}

fn contains_any(haystack: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| haystack.contains(needle))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reflection_done_when_last_line_is_done() {
        let reflection = "REFINE: earlier draft was incomplete.\nDONE";
        assert!(is_done(reflection));
    }

    #[test]
    fn reflection_refine_when_last_line_is_refine() {
        let reflection = "Looks close.\nREFINE: add the missing print statement";
        assert!(!is_done(reflection));
        assert_eq!(
            extract_refine_reason(reflection),
            "add the missing print statement"
        );
    }

    #[test]
    fn reflection_reason_falls_back_when_no_terminal_reason() {
        let reflection = "Needs work overall";
        assert_eq!(extract_refine_reason(reflection), "Needs work overall");
    }
}
