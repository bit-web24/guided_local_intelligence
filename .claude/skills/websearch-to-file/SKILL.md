---
name: websearch-to-file
description: Plan web search workflows that gather source content and write the result into a user-specified file. Use when the prompt asks to search the web, research online, collect sources, or save web findings to a file.
---

# Websearch To File

## Instructions

Use this Skill when the user asks to search the web, research online, gather sources, and write the result into a file.

Planning rules:

- First determine the output filename. If the prompt asks to write to a file but does not specify a filename, the clarifier should ask for it before planning.
- Use available MCP web-search tools for current or external information; do not ask the local model to invent search results.
- Prefer SerpAPI's generic `search` MCP tool when available.
- For SerpAPI's `search` tool, use arguments shaped like `{"params": {"q": "<query>", "engine": "google_light"}, "mode": "compact"}` unless the discovered tool schema requires a different shape.
- Assign search tools directly to the task that consumes the search results.
- Always use task-scoped MCP result placeholders such as `{t1_search_result}` or `{t2_web_search_result}` exactly as required by the selected tool name.
- Decompose into small tasks: build search query, run search, extract source facts, extract source URLs, draft file content, and assemble the final file content.
- Require URLs in the final content when the user asks for sources, citations, links, or research.
- Only include URLs present in tool results. Do not invent citations, article titles, dates, authors, or links.
- For markdown outputs, include clear headings and a concise sources section.
- Set `write_to_file` to true and include the exact relative output filename in `output_filenames`.
- Use final output keys that contain actual file content, not file path/status values.

## Examples

User request: "Search the web for quantization in LLMs and write it to info/quantization.md."

Good task shape:

- Build one focused search query for quantization in LLMs.
- Search the web using the available search MCP tool.
- Extract key findings and source URLs from the tool result.
- Write markdown content for `info/quantization.md` using only extracted findings.

Bad task shape:

- Write a report about quantization from memory.
- Create a file status task such as `file_created`.

User request: "Research the latest Python packaging news and save sources to packaging.md."

Good task shape:

- Build a current-news search query.
- Run web search with that query.
- Extract source-backed facts and URLs.
- Write `packaging.md` with findings and a sources section.

Bad task shape:

- Summarize latest news without using a web-search tool.
