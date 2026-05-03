---
name: testing-code
description: Plan robust code testing workflows. Use when writing tests, fixing pytest failures, improving coverage, or validating code behavior.
---

# Testing Code

## Instructions

Use this Skill when the user asks to create, repair, or improve automated tests.

Planning rules:

- Start by identifying the test target: module, function, CLI command, API route, or behavior.
- Prefer reading existing source and test files before generating tests for an existing project.
- Decompose into small tasks: inspect target API, identify behavior cases, write fixtures, write happy-path tests, write edge/error tests.
- Keep each generated test fragment focused on one behavior group.
- Include assertions that verify behavior, not only that code runs.
- For pytest, prefer explicit fixtures and plain assertions over broad snapshot-like checks.
- If fixing a failing test run, plan one task to extract the failure cause and one task to generate the minimal repair.

## Examples

User request: "Write pytest tests for the calculator module."

Good task shape:

- Inspect calculator public functions.
- Identify add/subtract/multiply/divide behavior cases.
- Write pytest tests for normal arithmetic behavior.
- Write pytest tests for invalid input or divide-by-zero behavior.

Bad task shape:

- Write all tests for the project.

User request: "Fix failing pytest."

Good task shape:

- Read the pytest failure output.
- Read the source file named in the traceback.
- Identify the minimal behavioral mismatch.
- Generate a targeted code or test repair.
