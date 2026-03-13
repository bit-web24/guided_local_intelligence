use agent_b::Tool;
use std::fs;
use std::path::Path;

/// Maximum bytes to read from a file before truncating.
const MAX_FILE_BYTES: usize = 4096;

/// Tool: read_file
/// Reads the contents of a file and returns its text (truncated to 4 KB).
pub fn read_file_tool() -> Tool {
    Tool::new(
        "read_file",
        "Read the text contents of a file on disk. Returns up to 4 KB of content.",
    )
    .param("path", "string", "Absolute or relative path to the file to read")
    .call(|args| {
        let path = args
            .get("path")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "Missing required parameter: path".to_string())?;

        let content = fs::read_to_string(path)
            .map_err(|e| format!("Failed to read '{}': {}", path, e))?;

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

const SKIP_DIRS: &[&str] = &[".git", "target", "node_modules", ".next", "__pycache__", ".venv"];

fn walk_tree(path: &Path, depth: usize, max_depth: usize, lines: &mut Vec<String>) {
    if depth > max_depth {
        return;
    }
    let Ok(entries) = fs::read_dir(path) else { return };

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
    let Ok(entries) = fs::read_dir(path) else { return };

    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() {
            let name = p.file_name().unwrap_or_default().to_string_lossy().to_string();
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
