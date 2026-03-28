# Agentic Decomposition Pipeline

## The Idea

A user gives a complex prompt to a cloud model. The cloud model does not answer it — it decomposes it into a dependency-ordered list of atomic micro tasks. Each micro task is then executed by a local model, one at a time, in the correct order. The output of each task is injected directly into the system prompt of the next task that depends on it. A final integrator assembles all outputs into the requested deliverable.

The cloud model is only used twice — once to decompose, once to assemble. Everything in between runs locally.

---

## Why This Works

Large cloud models are good at understanding intent and structure. Small local models are good at following a single, constrained instruction with examples. The pipeline exploits both: the cloud model figures out what needs to happen and in what order, the local models do the narrow execution work.

The key mechanism is **context injection** — the output of task A becomes part of the system prompt of task B. The local model executing task B never sees the original user prompt. It only sees what it needs to know, expressed as a precise instruction with examples, with the relevant upstream output already filled in.

---

## Core Concepts

**Micro task** — a single atomic operation with one input, one output, one format. The model answering it should never need to make a decision about scope.

**Output anchor** — every prompt ends with a trigger word (`JSON:`, `Output:`, `Code:`) so the local model knows exactly where to write its answer.

**Few-shot examples in every prompt** — every micro task prompt contains concrete input→output examples. The local model pattern-matches rather than reasons.

**Dependency graph** — tasks declare what they depend on. Tasks with no shared dependencies run in parallel. Tasks that need a prior output wait for it.

**Context dict** — a shared key-value store. Every completed task writes its output to a key. Downstream tasks read from it via placeholders in their system prompts.

---

## Example 1 — FastAPI project generation

**User prompt:**
> Create a REST API in Python using FastAPI with 5 endpoints for orders. Also write a pyproject.toml.

**What the cloud model produces:**

```
t1  resolve data model          → {order_fields}
t2  resolve python version      → {python_version}        [parallel with t1]
t3  resolve fastapi version     → {fastapi_version}       [parallel with t1]
t4  write OrderCreate schema    → {schema_create}         depends: t1
t5  write OrderResponse schema  → {schema_response}       depends: t1
t6  write in-memory store       → {store_code}            depends: t1
t7  write POST /orders          → {endpoint_create}       depends: t4, t5, t6
t8  write GET /orders           → {endpoint_list}         depends: t5, t6
t9  write GET /orders/{id}      → {endpoint_get}          depends: t5, t6
t10 write PATCH /orders/{id}    → {endpoint_update}       depends: t4, t5, t6
t11 write DELETE /orders/{id}   → {endpoint_delete}       depends: t6
t12 write pyproject.toml        → {pyproject}             depends: t2, t3
```

**How context injection works at task t7:**

The system prompt for t7 contains the literal text of `{schema_create}`, `{schema_response}`, and `{store_code}` already filled in before the local model sees it. The model is not asked to invent schemas — it is handed them and told to write one endpoint using them.

**Final output:** `main.py` + `pyproject.toml` written to disk.

---

## Example 2 — Multi-language README generation

**User prompt:**
> Read the structure of this project and write a README in English, Hindi, and Japanese.

**What the cloud model produces:**

```
t1  extract project name        → {project_name}
t2  extract project purpose     → {project_purpose}
t3  list key features           → {features}
t4  detect tech stack           → {tech_stack}
t5  write English README        → {readme_en}             depends: t1-t4
t6  translate to Hindi          → {readme_hi}             depends: t5
t7  translate to Japanese       → {readme_ja}             depends: t5
```

t6 and t7 run in parallel since they both only depend on t5.

**Final output:** `README.md`, `README.hi.md`, `README.ja.md`

---

## Example 3 — Database migration plan

**User prompt:**
> We are moving from MongoDB to PostgreSQL. Write a migration plan, a schema conversion guide, and a risk assessment.

**What the cloud model produces:**

```
t1  identify source db patterns     → {mongo_patterns}
t2  identify target db constraints  → {pg_constraints}
t3  map document→table conversions  → {schema_map}         depends: t1, t2
t4  identify high-risk fields       → {risk_fields}        depends: t3
t5  write schema conversion guide   → {schema_guide}       depends: t3
t6  write migration steps           → {migration_steps}    depends: t3
t7  write risk assessment           → {risk_doc}           depends: t4
```

**Final output:** `schema_conversion.md`, `migration_plan.md`, `risk_assessment.md`

---

## Example 4 — Test suite generation

**User prompt:**
> Write a pytest test suite for this FastAPI orders API.

**What the cloud model produces:**

```
t1  extract all endpoint signatures     → {endpoints}
t2  extract request/response schemas    → {schemas}
t3  write happy path tests              → {tests_happy}      depends: t1, t2
t4  write 404 / not found tests         → {tests_404}        depends: t1
t5  write validation error tests        → {tests_validation} depends: t2
t6  write conftest.py and fixtures      → {conftest}         depends: t1, t2
```

t3, t4, t5 run in parallel after t1 and t2 complete.

**Final output:** `test_orders.py`, `conftest.py`

---

## What This Is Not

- Not a RAG pipeline. There is no retrieval. Context is passed explicitly.
- Not a chat agent. There is no conversation. Each task is stateless.
- Not a fine-tuning approach. The local models are not modified.
- Not a single-agent loop. There is no reflection or self-critique cycle (that is GLI's PGL mode — a separate concern).

---

## The Boundary Between Cloud and Local

| Responsibility | Model |
|---|---|
| Understanding user intent | Cloud |
| Deciding task structure and order | Cloud |
| Assembling final output from parts | Cloud |
| Executing a single constrained instruction | Local |
| Extracting a single entity from text | Local |
| Generating code given an exact spec | Local |
| Validating a single value | Local |

The cloud model never writes the final code or content directly. The local models never see the full picture. Neither needs to do the other's job.

---

## The Single Most Important Property

Every micro task prompt contains **concrete examples** of the exact input→output transformation expected. The local model does not reason — it pattern-matches against those examples. This is what makes small models reliable in this pipeline. Remove the examples and the outputs become unpredictable. Keep them and a 1B model can reliably extract a Python version from a sentence.
