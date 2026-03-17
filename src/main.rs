mod agents;
mod config;
mod context_summarizer;
mod guidance_engine;
mod tools;

use clap::Parser;
use colored::Colorize;
use config::Config;
use guidance_engine::GuidanceEngine;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cfg = Config::parse();

    // ── Welcome banner ───────────────────────────────────────────────────────
    println!();
    println!(
        "{}",
        "╔══════════════════════════════════════════════════════╗".bright_blue()
    );
    println!(
        "{}",
        "║       Guided Local Intelligence (GLI)  v1.0          ║"
            .bright_blue()
            .bold()
    );
    println!(
        "{}",
        "║       Progressive Guidance Loop — PLAN -> EXEC -> SYNTHESIZE -> REFLECT  ║"
            .bright_blue()
    );
    println!(
        "{}",
        "╚══════════════════════════════════════════════════════╝".bright_blue()
    );
    println!();
    println!("  {} {}", "Task:".bold(), cfg.task.yellow());
    println!("  {} {}", "Model:".bold(), cfg.model.cyan());
    println!("  {} {}", "LLM URL:".bold(), cfg.ollama_url.dimmed());
    if let Some(ref p) = cfg.path {
        println!("  {} {}", "Path context:".bold(), p.cyan());
    }
    println!(
        "  {} {}",
        "Max loops:".bold(),
        cfg.max_loops.to_string().cyan()
    );
    println!("  {} {}", "Reports dir:".bold(), cfg.reports_dir.cyan());
    println!();

    // ── Run the guidance engine ──────────────────────────────────────────────
    let engine = GuidanceEngine::new(
        cfg.model.clone(),
        cfg.ollama_url.clone(),
        cfg.max_loops,
        cfg.max_steps,
        cfg.path.clone(),
        cfg.reports_dir.clone(),
    );

    match engine.run(&cfg.task).await {
        Ok(result) => {
            println!();
            println!(
                "{}",
                "╔══════════════════════════════════════════════════════╗".bright_green()
            );
            println!(
                "{}",
                "║                    FINAL RESULT                      ║"
                    .bright_green()
                    .bold()
            );
            println!(
                "{}",
                "╚══════════════════════════════════════════════════════╝".bright_green()
            );
            println!();
            println!("{}", result.trim());
            println!();
            println!(
                "{}",
                "═══════════════════════════════════════════════════════"
                    .bright_green()
                    .dimmed()
            );
            println!("{}", "  GLI run complete.".bright_green());
        }
        Err(e) => {
            eprintln!();
            eprintln!(
                "{}",
                "╔══════════════════════════════════════════════════════╗".bright_red()
            );
            eprintln!(
                "{}",
                "║                      ERROR                           ║"
                    .bright_red()
                    .bold()
            );
            eprintln!(
                "{}",
                "╚══════════════════════════════════════════════════════╝".bright_red()
            );
            eprintln!();
            eprintln!("  {}: {}", "GLI failed".bright_red().bold(), e);
            eprintln!();
            std::process::exit(1);
        }
    }

    Ok(())
}
