use anyhow::Result;
use colored::Colorize;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::{Arc, Mutex};

use crate::agents::{
    executor_agent, planner_agent, reflection_agent, synthesizer_agent, verifier_agent,
};

pub struct GuidanceEngine {
    pub model: String,
    pub ollama_url: String,
    pub max_loops: usize,
    pub max_steps: usize,
    pub path_context: Option<String>,
    /// Directory where reports are saved (created on demand).
    pub reports_dir: String,
}

impl GuidanceEngine {
    pub fn new(
        model: impl Into<String>,
        ollama_url: impl Into<String>,
        max_loops: usize,
        max_steps: usize,
        path_context: Option<String>,
        reports_dir: impl Into<String>,
    ) -> Self {
        Self {
            model: model.into(),
            ollama_url: ollama_url.into(),
            max_loops,
            max_steps,
            path_context,
            reports_dir: reports_dir.into(),
        }
    }

    /// Run the Progressive Guidance Loop for the given task.
    /// Returns the final synthesized answer and saves a report to `reports_dir`.
    pub async fn run(&self, task: &str) -> Result<String> {
        let mut current_task = task.to_string();
        let mut final_output = String::new();

        // The exact SharedMemory structure defined in tools.rs
        type SharedMemory = Arc<Mutex<HashMap<String, String>>>;
        let memory: SharedMemory = Arc::new(Mutex::new(HashMap::new()));

        for loop_idx in 0..self.max_loops {
            if loop_idx > 0 {
                println!(
                    "\n{}",
                    format!(
                        "  ↻  Loop {} of {} — refining…",
                        loop_idx + 1,
                        self.max_loops
                    )
                    .yellow()
                    .bold()
                );
            }

            // ── Stage 1: PLAN ────────────────────────────────────────────────
            self.print_stage("PLAN", None);
            let plan = self
                .run_agent(planner_agent(
                    &current_task,
                    self.path_context.as_deref(),
                    &self.model,
                    &self.ollama_url,
                    self.max_steps,
                    memory.clone(),
                ))
                .await?;
            println!("{}", plan.trim().dimmed());

            // Parse plan into steps
            let steps = parse_steps(&plan);

            // ── Stage 2: EXECUTE ─────────────────────────────────────────────
            self.print_stage("EXECUTE", None);
            let mut execution_results: Vec<String> = Vec::new();
            let mut accumulated_context = String::new();

            for (i, step) in steps.iter().enumerate() {
                let idx = i + 1;
                self.print_stage("EXECUTE", Some(&format!("step {}/{}", idx, steps.len())));
                println!("{}", format!("  → {}", step).cyan());

                let result = self
                    .run_agent(executor_agent(
                        step,
                        idx,
                        steps.len(),
                        &accumulated_context,
                        &self.model,
                        &self.ollama_url,
                        self.max_steps,
                        memory.clone(),
                    ))
                    .await?;

                println!("{}", result.trim().dimmed());
                accumulated_context.push_str(&format!(
                    "Step {}: {}\nResult: {}\n\n",
                    idx,
                    step,
                    result.trim()
                ));
                execution_results.push(format!(
                    "### Step {}: {}\n{}",
                    idx,
                    step,
                    result.trim()
                ));
            }

            // ── Stage 3: VERIFY ──────────────────────────────────────────────
            self.print_stage("VERIFY", None);
            let results_combined = execution_results.join("\n\n");
            let verified = self
                .run_agent(verifier_agent(
                    &results_combined,
                    &self.model,
                    &self.ollama_url,
                ))
                .await?;
            println!("{}", verified.trim().dimmed());

            // ── Stage 4: SYNTHESIZE ──────────────────────────────────────────
            self.print_stage("SYNTHESIZE", None);
            let synthesized = self
                .run_agent(synthesizer_agent(
                    &verified,
                    task,
                    &self.model,
                    &self.ollama_url,
                ))
                .await?;
            println!("{}", synthesized.trim().dimmed());
            final_output = synthesized.clone();

            // ── Stage 5: REFLECT ─────────────────────────────────────────────
            self.print_stage("REFLECT", None);
            let reflection = self
                .run_agent(reflection_agent(
                    &synthesized,
                    task,
                    &self.model,
                    &self.ollama_url,
                ))
                .await?;
            println!("{}", reflection.trim().dimmed());

            // Decide: DONE or REFINE
            if is_done(&reflection) {
                println!("\n{}", "  ✓  DONE — output accepted.".green().bold());
                break;
            } else {
                let reason = extract_refine_reason(&reflection);
                println!("\n{}", format!("  ↻  REFINE — {}", reason).yellow());
                current_task = format!(
                    "{}\n\nPrevious answer was incomplete because: {}\nImprove it.",
                    task, reason
                );
            }
        }

        // ── Save report ──────────────────────────────────────────────────────
        if let Err(e) = self.save_report(task, &final_output) {
            eprintln!("{}", format!("  ⚠  Could not save report: {}", e).yellow());
        }

        Ok(final_output)
    }

    // ── Report saving ────────────────────────────────────────────────────────

    fn save_report(&self, task: &str, content: &str) -> Result<()> {
        // Create Reports/ directory if it doesn't exist
        let reports_path = Path::new(&self.reports_dir);
        fs::create_dir_all(reports_path)?;

        // Filename: sanitised task slug + timestamp
        let timestamp = chrono::Local::now().format("%Y%m%d_%H%M%S");
        let slug: String = task
            .chars()
            .map(|c| if c.is_alphanumeric() { c.to_ascii_lowercase() } else { '_' })
            .take(40)
            .collect::<String>()
            .trim_matches('_')
            .to_string();
        let filename = format!("{}_{}.md", timestamp, slug);
        let filepath = reports_path.join(&filename);

        // Compose the markdown report
        let report = format!(
            "# GLI Report\n\n\
             **Task:** {task}\n\
             **Model:** {model}\n\
             **Generated:** {ts}\n\n\
             ---\n\n\
             {content}\n",
            task = task,
            model = self.model,
            ts = chrono::Local::now().format("%Y-%m-%d %H:%M:%S"),
            content = content,
        );

        fs::write(&filepath, report)?;
        println!(
            "\n{}",
            format!("  📄  Report saved → {}", filepath.display()).bright_green()
        );
        Ok(())
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
    let upper = reflection.to_uppercase();
    // "DONE" present but "REFINE" is not the dominant signal
    upper.contains("DONE") && !upper.contains("REFINE:")
}

fn extract_refine_reason(reflection: &str) -> String {
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
