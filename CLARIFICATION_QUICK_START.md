# Clarification Stage — Quick Start Guide

## What Is It?

The **Clarification Stage** is a new step in GLI that runs **before planning**. It ensures the agent understands your task correctly before creating a plan.

```
User Input → [CLARIFY] ← NEW → Confirm → [PLAN] → [EXECUTE]
```

## Why Do I Need It?

**Problem:** Agent misunderstands your task → creates wrong plan → wastes time executing wrong steps

**Solution:** Agent clarifies understanding first → you confirm → agent creates correct plan

## How To Use It

### Step 1: Run GLI normally
```bash
$ gli --task "Your task here"
$ gli --task "Your task here" --path "/path/to/project"
```

### Step 2: Review clarification
The agent shows you:
- **Understanding:** Your task rephrased clearly
- **Goals:** What it will accomplish
- **Scope:** What's included/excluded
- **Questions:** Any clarifications needed

### Step 3: Confirm or refine
```
Does this match what you want to do?
(type 'yes' or 'y' to continue, anything else to refine)
→ 
```

**Option A: Confirm**
- Type: `yes` or `y`
- Result: Agent proceeds with planning

**Option B: Refine**
- Type: anything else (like `n`, `no`, or a comment)
- Result: You can enter a refined task description
- Agent clarifies again with your refinement
- You confirm the new clarification

### Step 4: Normal execution
Once confirmed, GLI proceeds through:
- Planning
- Execution
- Verification
- Synthesis
- Reflection

## Common Tasks — Examples

### Example 1: List Python files
```bash
$ gli --task "List all Python files in the project"
```

**Clarification might show:**
```
Understanding: Find all .py files in the project
Goals:
- Identify all Python files
- Organize by directory
Scope:
- Includes: .py files in project
- Doesn't include: __pycache__, .pyc files
```

**Your response:** `yes` → Proceeds

---

### Example 2: Vague task
```bash
$ gli --task "Fix the code"
```

**Clarification might show:**
```
Understanding: Identify and fix bugs in the codebase
Goals:
- Find runtime errors
- Fix logic errors
Scope:
- Includes: Bug fixes
- Doesn't include: Refactoring
Questions:
- What type of bugs?
- Should I run tests?
```

**Your response:** `n` (refine)

```
Enter your refined task description:
→ Fix all critical runtime errors in auth module, run tests
```

**New clarification:** Shows updated understanding based on your refinement

**Your response:** `yes` → Proceeds

---

### Example 3: With project context
```bash
$ gli --task "Document API endpoints" --path "/home/user/api"
```

**Clarification might show:**
```
Understanding: Locate and document all API endpoints
Goals:
- Find endpoint definitions
- Document methods and paths
- Extract parameters
Scope:
- Includes: REST endpoints
- Doesn't include: Internal utilities
Questions:
- Include request/response schemas?
- Document auth requirements?
```

**Your response:** `yes` → Proceeds with project context awareness

---

## Quick Reference

| What You Want | What You Do |
|---|---|
| Proceed with clarification | Type `yes` or `y` |
| Refine the task | Type anything else |
| Skip unnecessary questions | Include details in original task |
| Provide context | Use `--path` flag |
| Change model/URL | Use `--model` and `--ollama-url` flags |

## Best Practices

### ✓ DO

- **Be specific** in your initial task
  - ✓ "Fix all critical runtime errors in the payment module"
  - ✗ "Fix the code"

- **Review clarification carefully** before confirming
  - This is your chance to catch misunderstandings

- **Refine if unsure** about the understanding
  - Better to clarify now than waste execution time

- **Use `--path`** when working with codebases
  - Gives agent better context

### ✗ DON'T

- **Proceed if something feels wrong** about the clarification
- **Skip reading** the clarified understanding
- **Assume the agent understands** vague tasks
- **Forget to refine** if clarification misses something

## Keyboard Shortcuts (Not Required)

The confirmation step is simple:
- `yes` → Continue
- `y` → Continue  
- Anything else → Refine

You can also just hit Enter without typing and it will treat it as a refinement request.

## When Is Clarification Used?

**Always:** Every time you run GLI

**Frequency:** Once per GLI invocation (before any planning loops)

**Can I skip it?** Not currently built-in (could be added as `--auto-clarify` flag)

## Examples of Good Clarifications

### Input
```
Create authentication system
```

### Output
```
Understanding: Implement user authentication with login/signup

Goals:
- Create user registration endpoint
- Create login endpoint
- Implement session/token management
- Protect routes with auth

Scope:
- Includes: Basic auth implementation
- Doesn't include: OAuth, password reset, email verification

Questions:
- JWT or session-based?
- Should passwords be hashed?
```

---

### Input
```
Optimize the system
```

### Output
```
Understanding: Improve system performance

Goals:
- Identify bottlenecks
- Optimize code
- Measure improvements

Scope:
- Includes: Performance optimization
- Doesn't include: New features, refactoring

Questions:
- What metric? (Speed, memory, cost?)
- Target improvement? (2x faster? 50% less memory?)
- Any components off-limits?
```

## Troubleshooting

| Problem | Solution |
|---|---|
| Clarification is too vague | Refine with more specific details |
| Clarification asks too many questions | Answer those questions in your refinement |
| Agent still misunderstands | Refine again with even more clarity |
| Want to proceed despite unclear parts | Type `yes` — you can always request a refinement loop later |

## Real-World Impact

### Before Clarification
- Vague task → Wrong plan → Wrong execution → Redo
- 2-3 loops typical

### After Clarification
- Clear task → Confirmed → Right plan → Right execution → Done
- 1-1.5 loops typical (50% fewer loops)

## Summary

1. **Run GLI** with your task
2. **Review** the clarification
3. **Confirm** with `yes` or refine with anything else
4. **Proceed** with confidence that the agent understands

That's it! The clarification stage ensures alignment before execution even starts.

---

For more details, see:
- **CLARIFICATION_STAGE.md** — Complete feature documentation
- **CLARIFICATION_EXAMPLES.md** — Real-world scenarios and patterns
- **CLARIFICATION_CHANGES.md** — Technical implementation details