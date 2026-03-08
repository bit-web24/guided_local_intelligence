# TASKS.md

## Implementation Tasks for Guided Local Intelligence (GLI)

This document outlines tasks for implementing GLI using the existing
framework at:

    ~/Desktop/Agent-B/

------------------------------------------------------------------------

# Phase 1 --- Project Setup

Create project directory:

    gli/

Structure:

    gli/
        cli/
        guidance_engine/
        agents/
        tools/
        experiments/

------------------------------------------------------------------------

# Phase 2 --- CLI Interface

Implement CLI command:

    gli "<task>"

Responsibilities:

-   accept user prompt
-   send task to guidance engine
-   display reasoning trace

Example output:

    PLAN
    STEP 1
    STEP 2
    STEP 3

    RESULT
    ...

------------------------------------------------------------------------

# Phase 3 --- Guidance Engine

Implement **Progressive Guidance Loop (PGL)**.

Algorithm:

    PLAN → EXECUTE → VERIFY → SYNTHESIZE → REFLECT

Responsibilities:

-   maintain task state
-   schedule agents
-   manage loops

------------------------------------------------------------------------

# Phase 4 --- Implement Agents

Using framework at:

    ~/Desktop/Agent-B/

Create agents:

PlannerAgent ExecutorAgent VerifierAgent SynthesizerAgent
ReflectionAgent

Each agent should:

-   accept task input
-   interact with LLM
-   produce structured output

------------------------------------------------------------------------

# Phase 5 --- LLM Integration

Integrate local LLM runtime.

Requirements:

-   prompt interface
-   context injection
-   response parsing

------------------------------------------------------------------------

# Phase 6 --- Tool Integration

Implement tool adapters.

Suggested tools:

-   python execution
-   calculator
-   filesystem reader
-   repository analyzer

Agents should call tools through the framework.

------------------------------------------------------------------------

# Phase 7 --- Logging & Trace

System must output reasoning trace.

Example:

    PLAN
    Analyze repository

    EXECUTE
    Scanning files

    VERIFY
    Checking missing modules

    SYNTHESIZE
    Generating report

    REFLECT
    Checking completeness

------------------------------------------------------------------------

# Phase 8 --- Demo Task

Implement repository analysis task.

Example command:

    gli analyze ./project

Expected output:

-   architecture summary
-   module analysis
-   improvement suggestions
