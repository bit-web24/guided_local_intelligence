use agent_b::Tool;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::{Arc, Mutex};

// ── Shared Scratchpad Memory ─────────────────────────────────────────────────
pub type SharedMemory = Arc<Mutex<HashMap<String, String>>>;

// ── Scratchpad Tools (Short-term memory) ─────────────────────────────────────

/// Tool: write_memory
/// Saves context into a shared JSON-like scratchpad that survives across PGL loops.
pub fn write_memory_tool(mem: SharedMemory) -> Tool {
    Tool::new(
        "write_memory",
        "Save an important fact, code snippet, or finding across steps. \
         Use this so you don't have to reread the same files later.",
    )
    .param(
        "key",
        "string",
        "A short, descriptive name (e.g., 'auth_logic' or 'db_schema')",
    )
    .param("value", "string", "The information to save")
    .call(move |args| {
        let key = args
            .get("key")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: key".to_string())?
            .to_string();
        let val = args
            .get("value")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: value".to_string())?
            .to_string();

        mem.lock().unwrap().insert(key.clone(), val);
        Ok(format!("Saved to memory under key '{}'", key))
    })
}

/// Tool: read_memory
/// Retrieves context from the shared JSON-like scratchpad.
pub fn read_memory_tool(mem: SharedMemory) -> Tool {
    Tool::new(
        "read_memory",
        "Read a previously saved fact from your scratchpad memory.",
    )
    .param("key", "string", "The name of the memory to read")
    .call(move |args| {
        let key = args
            .get("key")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: key".to_string())?;

        let mem_guard = mem.lock().unwrap();
        if let Some(val) = mem_guard.get(key) {
            Ok(val.clone())
        } else {
            let keys: Vec<_> = mem_guard.keys().map(|s| s.as_str()).collect();
            Ok(format!("Key not found. Available keys: {:?}", keys))
        }
    })
}

// ── Maximum bytes to read from a file before truncating ──────────────────────
const MAX_FILE_BYTES: usize = 4096;

// ── Web search: DuckDuckGo Instant Answers API ───────────────────────────────
// No API key required. Returns AbstractText, related topic summaries,
// and definitions — enough to resolve uncertain factual questions locally.

/// Tool: web_search
/// Queries DuckDuckGo's Instant Answers API to look up factual information.
/// Use this when you are uncertain about a fact, need a definition,
/// or require information not available in the local filesystem.
pub fn web_search_tool() -> Tool {
    Tool::new(
        "web_search",
        "Search the web for factual information using DuckDuckGo. \
         Use this when you are uncertain or unclear about something, \
         need a definition, or lack information in local files. \
         Returns an instant-answer summary.",
    )
    .param(
        "query",
        "string",
        "The search query — be specific and concise",
    )
    .param_opt(
        "max_results",
        "integer",
        "Maximum number of related topics to include (default: 5)",
    )
    .call(|args| {
        let query = args
            .get("query")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: query".to_string())?;

        let max_results = args
            .get("max_results")
            .and_then(|v| v.as_u64())
            .unwrap_or(5) as usize;

        if query.trim().is_empty() {
            return Err("Query must not be empty".to_string());
        }

        // DuckDuckGo Instant Answers API — no key required
        let url = format!(
            "https://api.duckduckgo.com/?q={}&format=json&no_redirect=1&no_html=1&skip_disambig=1",
            urlencoding_simple(query)
        );

        let response = ureq::get(&url)
            .timeout(std::time::Duration::from_secs(10))
            .call()
            .map_err(|e| format!("Web search request failed: {e}"))?;

        let body: serde_json::Value = response
            .into_json()
            .map_err(|e| format!("Failed to parse search response: {e}"))?;

        let mut output = format!("Search results for: \"{}\"\n\n", query);

        // Abstract (best single-sentence answer)
        let abstract_text = body
            .get("AbstractText")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if !abstract_text.is_empty() {
            let abstract_url = body
                .get("AbstractURL")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            output.push_str(&format!("## Summary\n{}\n", abstract_text));
            if !abstract_url.is_empty() {
                output.push_str(&format!("Source: {}\n", abstract_url));
            }
            output.push('\n');
        }

        // Definition (for terminology/vocabulary queries)
        let definition = body
            .get("Definition")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if !definition.is_empty() {
            let def_url = body
                .get("DefinitionURL")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            output.push_str(&format!("## Definition\n{}\n", definition));
            if !def_url.is_empty() {
                output.push_str(&format!("Source: {}\n", def_url));
            }
            output.push('\n');
        }

        // Answer (for simple factual queries like "how many days in a year")
        let answer = body.get("Answer").and_then(|v| v.as_str()).unwrap_or("");
        if !answer.is_empty() {
            output.push_str(&format!("## Answer\n{}\n\n", answer));
        }

        // Related topics — capped to max_results
        if let Some(topics) = body.get("RelatedTopics").and_then(|v| v.as_array()) {
            let topic_lines: Vec<String> = topics
                .iter()
                .take(max_results)
                .filter_map(|t| {
                    let text = t.get("Text").and_then(|v| v.as_str())?;
                    if text.is_empty() {
                        return None;
                    }
                    Some(format!("- {}", text))
                })
                .collect();

            if !topic_lines.is_empty() {
                output.push_str("## Related Topics\n");
                output.push_str(&topic_lines.join("\n"));
                output.push('\n');
            }
        }

        if output.trim_end() == format!("Search results for: \"{}\"", query).trim_end() {
            // Nothing useful found — report it clearly
            output.push_str(
                "No direct answer found. Try a more specific query, or \
                 check a primary source directly.\n",
            );
        }

        // Trim to a reasonable size so we don't flood the context
        let trimmed: String = output.chars().take(3000).collect();
        Ok(trimmed)
    })
}

/// Minimal URL percent-encoding for the search query.
/// Only encodes characters that break query strings — avoids a heavy dep.
fn urlencoding_simple(s: &str) -> String {
    let mut out = String::with_capacity(s.len() * 2);
    for byte in s.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(byte as char)
            }
            b' ' => out.push('+'),
            other => out.push_str(&format!("%{:02X}", other)),
        }
    }
    out
}

/// Tool: read_file
/// Reads the contents of a file and returns its text (truncated to 4 KB).
pub fn read_file_tool() -> Tool {
    Tool::new(
        "read_file",
        "Read the text contents of a file on disk. Returns up to 4 KB of content.",
    )
    .param(
        "path",
        "string",
        "Absolute or relative path to the file to read",
    )
    .call(|args| {
        let path = args
            .get("path")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: path".to_string())?;

        let content =
            fs::read_to_string(path).map_err(|e| format!("Failed to read '{}': {}", path, e))?;

        if content.len() > MAX_FILE_BYTES {
            Ok(format!(
                "[First {} bytes of {}]\n{}",
                MAX_FILE_BYTES,
                path,
                &content[..MAX_FILE_BYTES]
            ))
        } else {
            Ok(format!("[{}]\n{}", path, content))
        }
    })
}

/// Tool: list_directory
/// Lists the immediate children of a directory.
pub fn list_directory_tool() -> Tool {
    Tool::new(
        "list_directory",
        "List files and subdirectories within a given directory path.",
    )
    .param("path", "string", "The directory path to list")
    .call(|args| {
        let path_str = args
            .get("path")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: path".to_string())?;

        let path = Path::new(path_str);
        if !path.exists() {
            return Err(format!("Path does not exist: {}", path_str));
        }
        if !path.is_dir() {
            return Err(format!("Path is not a directory: {}", path_str));
        }

        let mut entries: Vec<String> = Vec::new();
        let dir_iter = fs::read_dir(path)
            .map_err(|e| format!("Cannot read directory '{}': {}", path_str, e))?;

        for entry in dir_iter.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            let is_dir = entry.path().is_dir();
            let kind = if is_dir { "DIR " } else { "FILE" };
            entries.push(format!("[{}] {}", kind, name));
        }

        entries.sort();
        Ok(format!(
            "Contents of '{}':\n{}",
            path_str,
            entries.join("\n")
        ))
    })
}

/// Tool: scan_repo
/// Walks an entire repository tree (up to depth 4), returning a compact file-tree.
pub fn scan_repo_tool() -> Tool {
    Tool::new(
        "scan_repo",
        "Recursively scan a repository or project directory and return a compact file-tree. Ignores .git, target, node_modules directories.",
    )
    .param("path", "string", "Root path of the repository to scan")
    .param_opt("max_depth", "integer", "Maximum recursion depth (default: 4)")
    .call(|args| {
        let root = args
            .get("path")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: path".to_string())?;

        let max_depth = args
            .get("max_depth")
            .and_then(|v| v.as_u64())
            .unwrap_or(4) as usize;

        let path = Path::new(root);
        if !path.exists() {
            return Err(format!("Path does not exist: {}", root));
        }

        let mut lines: Vec<String> = Vec::new();
        walk_tree(path, 0, max_depth, &mut lines);

        Ok(format!(
            "Repository tree for '{}':\n{}",
            root,
            lines.join("\n")
        ))
    })
}

/// Tool: detect_language
/// Detects the primary programming language(s) used in a directory.
pub fn detect_language_tool() -> Tool {
    Tool::new(
        "detect_language",
        "Detect the primary programming language(s) used in a project directory based on file extensions.",
    )
    .param("path", "string", "Root path of the project directory")
    .call(|args| {
        let root = args
            .get("path")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: path".to_string())?;

        let path = Path::new(root);
        if !path.exists() {
            return Err(format!("Path does not exist: {}", root));
        }

        let mut counts: std::collections::HashMap<&str, usize> = std::collections::HashMap::new();
        count_extensions(path, &mut counts, 0, 5);

        if counts.is_empty() {
            return Ok("No recognizable source files found.".to_string());
        }

        let mut sorted: Vec<(&str, usize)> = counts.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));

        let result: Vec<String> = sorted
            .iter()
            .take(5)
            .map(|(lang, count)| format!("  {} — {} files", lang, count))
            .collect();

        Ok(format!("Detected languages in '{}':\n{}", root, result.join("\n")))
    })
}

// ── Private helpers ──────────────────────────────────────────────────────────

const SKIP_DIRS: &[&str] = &[
    ".git",
    "target",
    "node_modules",
    ".next",
    "__pycache__",
    ".venv",
];

fn walk_tree(path: &Path, depth: usize, max_depth: usize, lines: &mut Vec<String>) {
    if depth > max_depth {
        return;
    }
    let Ok(entries) = fs::read_dir(path) else {
        return;
    };

    let indent = "  ".repeat(depth);
    let mut children: Vec<_> = entries.flatten().collect();
    children.sort_by_key(|e| e.file_name());

    for entry in children {
        let name = entry.file_name().to_string_lossy().to_string();
        if entry.path().is_dir() {
            if SKIP_DIRS.contains(&name.as_str()) {
                continue;
            }
            lines.push(format!("{}📁 {}/", indent, name));
            walk_tree(&entry.path(), depth + 1, max_depth, lines);
        } else {
            lines.push(format!("{}📄 {}", indent, name));
        }
    }
}

fn count_extensions(
    path: &Path,
    counts: &mut std::collections::HashMap<&'static str, usize>,
    depth: usize,
    max_depth: usize,
) {
    if depth > max_depth {
        return;
    }
    let Ok(entries) = fs::read_dir(path) else {
        return;
    };

    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() {
            let name = p
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string();
            if !SKIP_DIRS.contains(&name.as_str()) {
                count_extensions(&p, counts, depth + 1, max_depth);
            }
        } else if let Some(ext) = p.extension().and_then(|e| e.to_str()) {
            let lang: Option<&'static str> = match ext {
                "rs" => Some("Rust"),
                "py" => Some("Python"),
                "js" | "mjs" | "cjs" => Some("JavaScript"),
                "ts" | "tsx" => Some("TypeScript"),
                "go" => Some("Go"),
                "java" => Some("Java"),
                "cpp" | "cc" | "cxx" => Some("C++"),
                "c" | "h" => Some("C"),
                "rb" => Some("Ruby"),
                "php" => Some("PHP"),
                "kt" => Some("Kotlin"),
                "swift" => Some("Swift"),
                "toml" | "yaml" | "yml" | "json" => Some("Config"),
                "md" => Some("Markdown"),
                _ => None,
            };
            if let Some(lang) = lang {
                *counts.entry(lang).or_insert(0) += 1;
            }
        }
    }
}
