---
name: writing-documentation
description: Plan clear project documentation. Use when creating READMEs, API docs, architecture notes, changelogs, setup guides, or usage examples.
---

# Writing Documentation

## Instructions

Use this Skill when the user asks for documentation, explanations, guides, or markdown deliverables.

Planning rules:

- Identify the audience before writing: new user, contributor, maintainer, or operator.
- Inspect existing project files when documenting an existing codebase.
- Decompose documentation into sections: purpose, installation, usage, configuration, examples, troubleshooting, and development workflow when relevant.
- Keep factual extraction tasks separate from prose-writing tasks.
- For API docs, first extract routes, inputs, outputs, errors, and authentication requirements.
- For architecture docs, first identify components and data flow, then write the explanation.
- Avoid invented commands, endpoints, configuration keys, or dependencies.

## Examples

User request: "Write a README for this project."

Good task shape:

- Inspect pyproject and package layout.
- Extract project purpose and entry points.
- Extract install and test commands.
- Write README overview and quick start.
- Write usage, configuration, and development sections.

Bad task shape:

- Write the entire README from the prompt alone.

User request: "Document this API."

Good task shape:

- Extract route list.
- Extract request and response schemas.
- Extract error behavior.
- Write endpoint reference sections.
