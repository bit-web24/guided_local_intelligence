# AGENT_IMPLEMENTATION_PLAN.md

## Guided Local Intelligence (GLI) --- Step‑by‑Step Implementation Plan

This document provides a **deterministic implementation plan** so an
autonomous coding agent can implement the GLI project.

GLI must integrate with the existing orchestration framework located at:

    ~/Desktop/Agent-B/

The framework should be used for:

-   agent lifecycle
-   tool execution
-   message passing
-   scheduling

GLI will implement a **Guidance Engine** that orchestrates reasoning
using the **Progressive Guidance Loop (PGL)**.

------------------------------------------------------------------------

# Implementation Objective

Build a system that enables **small local LLMs** to solve complex tasks
through structured orchestration.

The system should:

1.  Accept a complex user task
2.  Decompose the task
3.  Execute subtasks with agents
4.  Verify outputs
5.  Synthesize results
6.  Reflect and refine if needed

------------------------------------------------------------------------

# Core Algorithm

Progressive Guidance Loop:

    PLAN → EXECUTE → VERIFY → SYNTHESIZE → REFLECT

Repeat until the task is complete.

------------------------------------------------------------------------

# Step 1 --- Create Project Structure

Create directory:

    gli/

Structure:

    gli/
        main.py
        cli/
        guidance/
        agents/
        tools/
        utils/
        experiments/

------------------------------------------------------------------------

# Step 2 --- CLI Interface

Create file:

    cli/interface.py

Responsibilities:

-   accept user input
-   call GLI guidance engine
-   display reasoning trace

Example usage:

    gli "analyze repository ./project"

Output format:

    PLAN
    ...
    EXECUTE
    ...
    VERIFY
    ...
    RESULT
    ...

------------------------------------------------------------------------

# Step 3 --- Guidance Engine

Create:

    guidance/engine.py

Responsibilities:

-   manage task lifecycle
-   implement Progressive Guidance Loop
-   invoke agents

Pseudo‑logic:

    while not task_complete:

        plan = PlannerAgent(task)

        results = ExecutorAgent(plan)

        verified = VerifierAgent(results)

        output = SynthesizerAgent(verified)

        reflection = ReflectionAgent(output)

        if reflection indicates issue:
            repeat loop
        else:
            return output

------------------------------------------------------------------------

# Step 4 --- Planner Agent

File:

    agents/planner.py

Responsibilities:

-   break task into steps
-   produce execution plan

Example output:

    1 scan directory
    2 identify modules
    3 analyze dependencies
    4 generate summary

------------------------------------------------------------------------

# Step 5 --- Executor Agent

File:

    agents/executor.py

Responsibilities:

-   execute subtasks
-   call LLM
-   call tools when necessary

Tasks may include:

-   file reading
-   data extraction
-   summarization

------------------------------------------------------------------------

# Step 6 --- Verifier Agent

File:

    agents/verifier.py

Responsibilities:

-   check hallucinations
-   validate results
-   ensure completeness

Example checks:

    missing modules?
    invalid file references?
    inconsistent outputs?

------------------------------------------------------------------------

# Step 7 --- Synthesizer Agent

File:

    agents/synthesizer.py

Responsibilities:

-   combine validated outputs
-   generate final result

Example:

    module analysis + dependencies
    → architecture summary

------------------------------------------------------------------------

# Step 8 --- Reflection Agent

File:

    agents/reflection.py

Responsibilities:

-   critique final output
-   detect gaps
-   request refinement if needed

Example prompts:

    Is any step missing?
    Is reasoning consistent?
    Is output coherent?

------------------------------------------------------------------------

# Step 9 --- LLM Integration

Create:

    utils/llm_interface.py

Responsibilities:

-   connect to local LLM runtime
-   send prompts
-   return structured responses

The LLM should be treated as:

    Reasoning Engine

------------------------------------------------------------------------

# Step 10 --- Tool Integration

Create tool adapters:

    tools/
        calculator.py
        python_executor.py
        filesystem_reader.py
        repo_analyzer.py

Agents should call tools when tasks require computation or data
extraction.

------------------------------------------------------------------------

# Step 11 --- Logging and Trace

The system must output a reasoning trace.

Example:

    PLAN
    Analyze repository

    EXECUTE
    Scanning files

    VERIFY
    Checking missing modules

    SYNTHESIZE
    Generating architecture report

    REFLECT
    Evaluating completeness

------------------------------------------------------------------------

# Step 12 --- Demo Task Implementation

Implement example task:

    Repository Architecture Analyzer

Command:

    gli analyze ./project

Expected output:

-   architecture overview
-   module structure
-   improvement suggestions

------------------------------------------------------------------------

# Step 13 --- Experiments

Implement evaluation scripts in:

    experiments/

Compare:

Baseline:

    LLM only

GLI:

    LLM + Progressive Guidance Loop

Metrics:

-   accuracy
-   completeness
-   hallucination rate

------------------------------------------------------------------------

# Implementation Completion Criteria

The project is complete when:

1.  CLI accepts tasks
2.  GLI guidance engine runs PGL loop
3.  Agents execute through \~/Desktop/Agent-B/
4.  System produces reasoning trace
5.  Repository analysis demo works
