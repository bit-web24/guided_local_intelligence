use agent_b::Tool;
use std::collections::HashMap;
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
