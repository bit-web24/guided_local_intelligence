# Clarification Stage — Task Understanding Confirmation

## Overview

The **Clarification Stage** is a new preliminary step added to the Guided Local Intelligence (GLI) workflow. It runs **before any planning or execution** and serves to ensure the agent fully understands the user's intent before proceeding.

### Problem It Solves

Previously, the agent would:
1. Receive a user prompt
2. Immediately create a plan
3. Execute the plan (which might be misaligned with the user's actual intent)

This often led to:
- Incorrect task interpretation
- Wasted execution cycles on wrong approaches
- Poor final results that didn't address the real need

### Solution

The new workflow is:

```
USER INPUT
    ↓
[CLARIFY] ← NEW STAGE
    ↓
User confirms understanding
    ↓
[PLAN]
    ↓
[EXECUTE]
    ↓
[VERIFY]
    ↓
[SYNTHESIZE]
    ↓
[REFLECT]
```

## How It Works

### Stage 1: Automatic Clarification

When you run GLI, it will:

1. **Receive your task** from the command line
2. **Rephrase and expand** your request through the `clarifier_agent`
3. **Output the clarified understanding** in a structured format:
   - **Understanding:** The core request rephrased clearly
   - **Goals:** Specific objectives to achieve
   - **Scope:** What is included and what is not
   - **Questions:** Any clarifications needed from you

Example output:
```
**Understanding:** Create a README file documenting the authentication system

**Goals:**
- List all authentication methods supported
- Explain JWT token flow
- Provide setup instructions
- Include security best practices

**Scope:**
- Covers: Authentication module only
- Doesn't cover: Authorization, role-based access control

**Questions:**
- Should the README include code examples?
- What audience level (beginner/advanced)?
```

### Stage 2: User Confirmation

After clarification, you're asked:

```
Does this match what you want to do?
(type 'yes' or 'y' to continue, anything else to refine)
→ 
```

**If you type 'yes' or 'y':**
- The agent proceeds with planning and execution
- Your confirmed understanding is locked in

**If you type anything else:**
- You're prompted to enter a refined task description
- The clarification runs again with your new input
- You get another chance to confirm

### Stage 3: Task Proceeds

Once confirmed, the normal GLI loop begins:
- Plan creation (now based on correct understanding)
- Execution of planned steps
- Verification and synthesis
- Reflection loop (if needed)

## Usage Examples

### Example 1: Simple Confirmation

```bash
$ gli --task "List all Python files in the project"
```

**Clarification output:**
```
Understanding: Find and list all Python source files (.py) in the project

Goals:
- Identify all files with .py extension
- Organize by directory structure
- Count total Python files

Scope:
- Includes: All .py files in the project
- Doesn't include: .pyc, __pycache__, virtual environments
```

**User response:** `y` → Proceeds with plan

---

### Example 2: Refinement

```bash
$ gli --task "Fix bugs"
```

**Clarification output:**
```
Understanding: Identify and fix all bugs in the codebase

Goals:
- Find all existing bugs
- Fix each bug
- Verify fixes work

Scope:
- Includes: All bug fixes
- Doesn't include: Feature development, refactoring

Questions:
- What type of bugs (runtime errors, logic errors, performance)?
- Should I run tests after fixing?
```

**User response:** `n` (or anything not 'y')

**Refine prompt:**
```
Enter your refined task description:
→ Fix all critical runtime errors in the authentication module, then run unit tests
```

**Re-clarification output:**
```
Understanding: Identify and fix critical runtime errors specifically in the authentication module, then verify fixes with unit tests

Goals:
- Find critical runtime errors in auth module
- Fix identified errors
- Run unit tests to verify
- Document what was fixed

Scope:
- Includes: Auth module only, critical errors, runtime issues
- Doesn't include: Non-critical warnings, other modules
```

**User response:** `yes` → Proceeds with plan

---

## Implementation Details

### New Components

#### 1. `clarifier_agent()` function
- **Location:** `src/agents.rs`
- **Type:** Text-only agent (no tools)
- **Purpose:** Rephrases and expands the user's task
- **Output:** Structured understanding with goals, scope, and questions

#### 2. Clarification stage in guidance loop
- **Location:** `src/guidance_engine.rs`
- **When:** Before any planning loops
- **Action:** Runs once at startup, before the main loop
- **User interaction:** Confirmation prompt with optional refinement

### Key Features

✅ **One-time clarification** — Happens before main loop, not during refinement cycles

✅ **Interactive confirmation** — User explicitly approves understanding before proceeding

✅ **Refinement capability** — User can refine and re-clarify if needed

✅ **Structured output** — Clear format (Understanding, Goals, Scope, Questions)

✅ **Path context aware** — Clarifier knows about the project context if provided

## Configuration

The clarification stage respects these CLI arguments:

- `--model` — LLM model to use for clarification
- `--ollama-url` — Ollama server endpoint
- `--path` — Project path context (optional, helps clarifier understand the project)

Example with path context:

```bash
$ gli --task "Document the API endpoints" --path "/home/user/my_project"
```

The clarifier will:
- Know the project location
- Better understand the scope of "API endpoints"
- Provide more contextual goals and scope

## Best Practices

### For Users

1. **Be specific in your initial prompt** — Details help the clarifier be more accurate
2. **Review the clarified understanding carefully** — This is your chance to catch misunderstandings
3. **Refine if needed** — Don't proceed if something feels wrong
4. **Use project context** — Provide `--path` when working with code projects

### For Agents (Downstream)

The planner now receives:
- A confirmed, well-understood task
- Clear goals and scope boundaries
- Explicit clarifications about what's included/excluded

This leads to:
- ✅ More accurate plans
- ✅ Fewer wasted execution steps
- ✅ Better final results
- ✅ Fewer refinement loops needed

## Troubleshooting

### Clarifier gives vague output?
- **Cause:** Vague initial prompt
- **Fix:** Be more specific. Include what you're working with and what success looks like

### Clarifier asks too many questions?
- **Cause:** Ambiguous task
- **Fix:** In the refinement step, provide answers to those questions in your refined task

### Want to skip clarification?
- **Currently:** Not possible — clarification always runs once
- **Future:** Could add `--no-clarify` flag if desired

## Example Workflow (Full)

```bash
$ gli --task "Create unit tests for the payment module" --path "/home/user/ecommerce"

[CLARIFY] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Understanding: Create comprehensive unit tests for the payment processing module

Goals:
- Identify all functions in payment module
- Write test cases for happy path and error scenarios
- Ensure 80%+ code coverage
- Document test setup instructions

Scope:
- Includes: Unit tests only, payment module code
- Doesn't include: Integration tests, API tests, other modules

Questions:
- What testing framework should I use (Jest, pytest, unittest)?
- Should I test external payment gateway integration?

Does this match what you want to do?
(type 'yes' or 'y' to continue, anything else to refine)
→ yes

Proceeding with task...

[PLAN] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Examine payment module structure and identify all functions
2. Research existing test framework in the project
3. Write unit tests for core payment functions
4. Write unit tests for error handling paths
5. Check code coverage and add missing tests

[EXECUTE] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
...
```

## Future Enhancements

Possible improvements (not yet implemented):

- **Multi-round clarification** — User can ask for re-clarification during execution
- **Auto-clarify flag** — `--auto-clarify` to skip confirmation
- **Clarification templates** — Pre-defined clarity questions for common task types
- **Clarification memory** — Store user answers for similar future tasks
- **Confidence scoring** — Clarifier outputs confidence level in understanding

---

## Summary

The **Clarification Stage** transforms GLI from a "ask once, plan blindly" system to an "ask, understand, confirm, then plan" system. This simple but powerful addition dramatically improves:

- **Task accuracy** ← User confirms the understanding
- **Plan quality** ← Plans are based on confirmed understanding
- **Execution success** ← Fewer wasted steps due to misunderstanding
- **User confidence** ← You know the agent understands before execution starts

It's a small addition with outsized impact on task completion quality.