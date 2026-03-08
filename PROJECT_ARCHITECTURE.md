# PROJECT_ARCHITECTURE.md

## Guided Local Intelligence (GLI) System Architecture

### Overview

Guided Local Intelligence (GLI) is a system that enables small local
LLMs to solve complex tasks through structured orchestration.

GLI runs on top of an existing agent framework located at:

    ~/Desktop/Agent-B/

This framework provides the core infrastructure for agents, while GLI
introduces a **guidance layer** that implements reasoning strategies.

------------------------------------------------------------------------

# System Layers

    User Interface (CLI)
            ↓
    GLI Guidance Engine
            ↓
    Agent Orchestration Framework (~/Desktop/Agent-B/)
            ↓
    Local LLM Runtime
            ↓
    Tools / Execution Environment

------------------------------------------------------------------------

# Core Components

## 1. CLI Interface

Example:

    gli "analyze repository ./project"

Responsibilities: - accept user task - pass task to GLI engine - display
reasoning trace and results

------------------------------------------------------------------------

## 2. GLI Guidance Engine

Implements the **Progressive Guidance Loop (PGL)**.

Responsibilities:

-   task decomposition
-   planning
-   orchestrating agents
-   verification
-   reflection loops

------------------------------------------------------------------------

## 3. Agent Layer

Agents run through the framework in:

    ~/Desktop/Agent-B/

Suggested agents:

PlannerAgent ExecutorAgent VerifierAgent SynthesizerAgent
ReflectionAgent

------------------------------------------------------------------------

## 4. Local LLM Runtime

Runs local models.

Suggested runtime:

Ollama

Possible models:

-   small Llama variants
-   Qwen small models
-   other 1B--3B parameter models

LLM role:

-   reasoning
-   summarization
-   planning assistance

------------------------------------------------------------------------

## 5. Tool System

Agents may invoke tools such as:

    calculator
    python execution
    file reader
    repository scanner
    data analysis

Tools reduce reasoning load on the LLM.

------------------------------------------------------------------------

# Data Flow

    User Task
        ↓
    PlannerAgent
        ↓
    ExecutorAgent(s)
        ↓
    VerifierAgent
        ↓
    SynthesizerAgent
        ↓
    ReflectionAgent
        ↓
    Final Output

------------------------------------------------------------------------

# Key Principle

LLM is treated as a **reasoning component**, not the entire system.

GLI controls the reasoning process through structured orchestration.
