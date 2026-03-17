# EVALUATION.md

## Evaluating Guided Local Intelligence (GLI)

This document defines experiments to demonstrate the effectiveness of
GLI.

------------------------------------------------------------------------

# Goal

Demonstrate that:

Small local LLMs perform significantly better when guided by the GLI
orchestration strategy.

------------------------------------------------------------------------

# Experiment Setup

Compare two systems:

Baseline:

    Local LLM only

GLI system:

    Local LLM + Progressive Guidance Loop

------------------------------------------------------------------------

# Metrics

Measure:

-   task completion rate
-   reasoning correctness
-   hallucination reduction
-   output coherence

------------------------------------------------------------------------

# Experiment 1 --- Repository Analysis

Task:

    Analyze repository architecture

Baseline test:

    LLM prompt:
    "Summarize this repository"

GLI test:

    GLI decomposes task into steps

Expected improvement:

-   more accurate module detection
-   structured architecture report

------------------------------------------------------------------------

# Experiment 2 --- Multi-step Reasoning

Task:

    Perform multi-step data analysis

Example:

    Compute statistics and explain trends

Baseline:

Single LLM prompt

GLI:

Task decomposition + verification

------------------------------------------------------------------------

# Experiment 3 --- Complex Instruction Following

Task:

    Generate technical documentation

GLI approach:

-   plan sections
-   generate content
-   verify completeness
-   synthesize document

------------------------------------------------------------------------

# Expected Results

GLI should demonstrate:

-   improved reasoning quality
-   fewer hallucinations
-   better structured outputs
-   higher task completion success

------------------------------------------------------------------------

# Visualization

During demo show reasoning trace:

    PLAN
    EXECUTE
    VERIFY
    SYNTHESIZE
    REFLECT

This demonstrates structured intelligence rather than raw LLM output.
