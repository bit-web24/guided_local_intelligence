use clap::Parser;

/// Guided Local Intelligence — orchestrate small local LLMs through structured reasoning.
#[derive(Parser, Debug, Clone)]
#[command(name = "gli", author, version, about, long_about = None)]
pub struct Config {
    /// The task to perform (e.g. "draft a migration plan" or "analyze this repository")
    pub task: String,

    /// Ollama model name to use
    #[arg(long, default_value = "qwen2.5:1.5b")]
    pub model: String,

    /// Ollama API base URL
    #[arg(long, default_value = "http://localhost:11434/v1")]
    pub ollama_url: String,

    /// Maximum number of PGL loop iterations
    #[arg(long, default_value_t = 3)]
    pub max_loops: usize,

    /// Optional path context for tasks that depend on local files
    #[arg(long, short)]
    pub path: Option<String>,

    /// Maximum agent steps per sub-agent run (for Planner and Executor)
    #[arg(long, default_value_t = 17)]
    pub max_steps: usize,

}
