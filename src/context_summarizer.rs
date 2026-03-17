/// Summarizes step responses to reduce context window footprint
pub struct ContextSummarizer;

impl ContextSummarizer {
    /// Summarize clarification output into a compact task brief.
    pub fn summarize_clarification(clarification: &str) -> String {
        let mut summary_lines = Vec::new();

        for line in clarification.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }

            if trimmed.starts_with("**Understanding:**")
                || trimmed.starts_with("**Goals:**")
                || trimmed.starts_with("**Scope:**")
                || trimmed.starts_with("**Questions:**")
                || trimmed.starts_with('-')
            {
                summary_lines.push(limit_line(trimmed, 90));
            }
        }

        if summary_lines.is_empty() {
            format!("CLARIFY: {}", limit_line(clarification.trim(), 120))
        } else {
            format!("CLARIFY:\n{}", summary_lines.join("\n"))
        }
    }

    /// Summarize a plan to its key points
    pub fn summarize_plan(plan: &str) -> String {
        let lines: Vec<&str> = plan.lines().collect();

        // Extract numbered steps only
        let steps: Vec<String> = lines
            .iter()
            .filter(|line| {
                let trimmed = line.trim();
                trimmed.starts_with(|c: char| c.is_ascii_digit()) || trimmed.starts_with('-')
            })
            .map(|line| {
                let trimmed = line.trim();
                // Keep step brief - first 80 chars max
                if trimmed.len() > 80 {
                    format!("{}...", &trimmed[..77])
                } else {
                    trimmed.to_string()
                }
            })
            .collect();

        if steps.is_empty() {
            "[Plan: proceed with execution]".to_string()
        } else {
            format!("PLAN:\n{}", steps.join("\n"))
        }
    }

    /// Summarize a step execution result to reduce context
    pub fn summarize_step_result(result: &str, step_num: usize) -> String {
        let trimmed = result.trim();

        // Keep only first 150 chars + summary
        let summary = if trimmed.len() > 150 {
            let first_part = &trimmed[..150];
            // Try to find a natural break point
            if let Some(pos) = first_part.rfind('.') {
                format!("{}...", &first_part[..pos + 1])
            } else if let Some(pos) = first_part.rfind('\n') {
                format!("{}...", &first_part[..pos])
            } else {
                format!("{}...", first_part)
            }
        } else {
            trimmed.to_string()
        };

        // Extract key information
        let key_info = extract_key_info(result);

        if !key_info.is_empty() {
            format!("Step {}: {} [Key: {}]", step_num, summary, key_info)
        } else {
            format!("Step {}: {}", step_num, summary)
        }
    }

    /// Summarize the execution phase as a compact list of outcomes.
    pub fn summarize_execution(step_summaries: &[String]) -> String {
        if step_summaries.is_empty() {
            return "[Execution: no completed steps]".to_string();
        }

        let compact_steps: Vec<String> = step_summaries
            .iter()
            .take(8)
            .map(|summary| limit_line(summary, 140))
            .collect();

        let mut output = format!("EXECUTION:\n{}", compact_steps.join("\n"));
        if step_summaries.len() > compact_steps.len() {
            output.push_str(&format!(
                "\n...plus {} additional summarized steps",
                step_summaries.len() - compact_steps.len()
            ));
        }

        output
    }

    /// Build a compact packet for verification from plan + execution summaries.
    pub fn summarize_for_verification(plan_summary: &str, step_summaries: &[String]) -> String {
        format!(
            "{}\n{}\nReview only these compact findings.",
            plan_summary.trim(),
            Self::summarize_execution(step_summaries).trim()
        )
    }

    /// Summarize verification results
    pub fn summarize_verification(verified: &str) -> String {
        let lines: Vec<&str> = verified.lines().collect();

        // Keep first line and any error/issue mentions
        let mut summary = String::new();

        for (idx, line) in lines.iter().enumerate() {
            if idx >= 3 {
                break;
            }
            if !line.trim().is_empty() {
                summary.push_str(line);
                summary.push('\n');
            }
        }

        if summary.is_empty() {
            "[Verification: Results verified]".to_string()
        } else {
            format!("VERIFIED:\n{}", summary.trim())
        }
    }

    /// Summarize synthesis into compact form
    pub fn summarize_synthesis(synthesized: &str) -> String {
        let lines: Vec<&str> = synthesized.lines().collect();

        // Extract heading lines and first line after each heading
        let mut summary = String::new();
        let mut prev_was_heading = false;

        for line in lines.iter().take(20) {
            let trimmed = line.trim();

            if trimmed.starts_with('#') {
                summary.push_str(trimmed);
                summary.push('\n');
                prev_was_heading = true;
            } else if !trimmed.is_empty() && prev_was_heading {
                if trimmed.len() > 80 {
                    summary.push_str(&trimmed[..77]);
                    summary.push_str("...\n");
                } else {
                    summary.push_str(trimmed);
                    summary.push('\n');
                }
                prev_was_heading = false;
            }
        }

        if summary.is_empty() {
            "[Synthesis complete]".to_string()
        } else {
            summary
        }
    }

    /// Create a compact execution context for next iteration
    #[allow(dead_code)]
    pub fn create_compact_context(accumulated_results: &[String], step_count: usize) -> String {
        let mut context = format!("Completed {} steps:\n", step_count);

        for (idx, result) in accumulated_results.iter().enumerate().take(5) {
            context.push_str(&format!("{}. {}\n", idx + 1, result));
        }

        if accumulated_results.len() > 5 {
            context.push_str(&format!(
                "...and {} more steps\n",
                accumulated_results.len() - 5
            ));
        }

        context
    }

    /// Summarize all execution results into a brief context
    #[allow(dead_code)]
    pub fn summarize_all_executions(execution_results: &[String]) -> String {
        let mut brief = String::new();
        brief.push_str("EXECUTION SUMMARY:\n");

        for (idx, result) in execution_results.iter().enumerate() {
            let first_line = result.lines().next().unwrap_or("[No output]");

            brief.push_str(&format!(
                "Step {}: {}\n",
                idx + 1,
                if first_line.len() > 70 {
                    format!("{}...", &first_line[..67])
                } else {
                    first_line.to_string()
                }
            ));
        }

        brief
    }
}

fn limit_line(line: &str, max_chars: usize) -> String {
    if line.chars().count() <= max_chars {
        line.to_string()
    } else {
        let truncated: String = line.chars().take(max_chars.saturating_sub(3)).collect();
        format!("{truncated}...")
    }
}

/// Extract key information from a result (errors, findings, etc.)
fn extract_key_info(result: &str) -> String {
    let result_lower = result.to_lowercase();

    if result_lower.contains("error") {
        "ERROR".to_string()
    } else if result_lower.contains("found") || result_lower.contains("identified") {
        "FOUND".to_string()
    } else if result_lower.contains("success") || result_lower.contains("complete") {
        "SUCCESS".to_string()
    } else if result_lower.contains("not found") || result_lower.contains("no") {
        "NOT_FOUND".to_string()
    } else {
        String::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_summarize_plan() {
        let plan = "1. Scan the project\n2. Analyze code\n3. Generate report";
        let summary = ContextSummarizer::summarize_plan(plan);
        assert!(summary.contains("1."));
        assert!(summary.contains("PLAN:"));
    }

    #[test]
    fn test_summarize_long_result() {
        let long_result = "a".repeat(200);
        let summary = ContextSummarizer::summarize_step_result(&long_result, 1);
        assert!(summary.len() < long_result.len());
    }

    #[test]
    fn test_summarize_for_verification() {
        let output = ContextSummarizer::summarize_for_verification(
            "PLAN:\n1. Inspect auth flow",
            &[
                "Step 1: Read auth controller [Key: FOUND]".to_string(),
                "Step 2: Found null token path [Key: ERROR]".to_string(),
            ],
        );

        assert!(output.contains("PLAN:"));
        assert!(output.contains("EXECUTION:"));
        assert!(output.contains("Step 2"));
    }
}
