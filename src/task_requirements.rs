#[derive(Debug, Clone, Default)]
pub struct TaskRequirements {
    pub require_filesystem_tools: bool,
    pub require_web_search: bool,
    pub require_filesystem_before_planning: bool,
}

impl TaskRequirements {
    pub fn describe_for_prompt(&self) -> String {
        let mut lines = Vec::new();

        if self.require_filesystem_before_planning {
            lines.push(
                "- Filesystem inspection is mandatory before planning if local workspace context is relevant.",
            );
        } else if self.require_filesystem_tools {
            lines.push("- Filesystem inspection is mandatory before answering relevant steps.");
        }

        if self.require_web_search {
            lines.push("- Web search is mandatory before answering claims that depend on external/current information.");
        }

        if lines.is_empty() {
            "- No mandatory tool policy was inferred.".to_string()
        } else {
            lines.join("\n")
        }
    }
}

pub fn infer_task_requirements(task: &str, path_context: Option<&str>) -> TaskRequirements {
    let normalized = task.to_lowercase();
    let path_present = path_context.is_some();

    let local_workspace_terms = [
        "this project",
        "this repo",
        "this repository",
        "this codebase",
        "this code",
        "this file",
        "current project",
        "current repo",
        "current repository",
        "existing code",
        "existing implementation",
        "implementation",
        "workspace",
        "source code",
        "files here",
    ];

    let local_action_terms = [
        "summarize",
        "analyze",
        "inspect",
        "review",
        "check",
        "fix",
        "debug",
        "explain",
        "document",
        "find",
        "trace",
        "compare",
        "update",
        "change",
    ];

    let deictic_terms = ["this", "here", "current", "existing", "present"];

    let web_terms = [
        "latest",
        "current version",
        "current price",
        "today",
        "recent",
        "news",
        "official docs",
        "documentation",
        "release notes",
        "api docs",
        "what changed",
        "online",
        "web",
        "internet",
    ];

    let require_filesystem_tools = path_present
        && (contains_any(&normalized, &local_workspace_terms)
            || (contains_any(&normalized, &deictic_terms)
                && contains_any(&normalized, &local_action_terms)));

    let require_web_search = contains_any(&normalized, &web_terms);

    TaskRequirements {
        require_filesystem_tools,
        require_web_search,
        require_filesystem_before_planning: require_filesystem_tools,
    }
}

fn contains_any(haystack: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| haystack.contains(needle))
}
