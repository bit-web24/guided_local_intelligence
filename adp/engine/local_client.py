"""Async httpx client for the small Ollama model (micro-task execution).

Temperature is always 0.0 — hardcoded, never accepted as a parameter.
"""
from __future__ import annotations

import asyncio

import httpx

from adp.config import (
    LOCAL_MODEL,
    LOCAL_TEMPERATURE,
    LOCAL_TIMEOUT,
    OLLAMA_BASE_URL,
)


async def call_local_async(
    system_prompt: str,
    input_text: str,
    anchor_str: str,
) -> str:
    """
    Call the small Ollama model asynchronously.

    The full user-facing prompt is: "Input: {input_text}\\n{anchor_str}"
    The system prompt is passed as the 'system' field (already filled with
    upstream context before this function is called).

    Returns the raw model output string (may include preamble before anchor).
    """
    full_prompt = f"Input: {input_text}\n{anchor_str}"
    payload = {
        "model": LOCAL_MODEL,
        "system": system_prompt,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": LOCAL_TEMPERATURE,  # always 0.0 — determinism mandatory
            "num_predict": 2048,
        },
    }
    async with httpx.AsyncClient(timeout=LOCAL_TIMEOUT) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
        )
        response.raise_for_status()
        return response.json()["response"]


def call_local_sync(system_prompt: str, input_text: str, anchor_str: str) -> str:
    """Synchronous wrapper. Use only in non-async contexts (e.g. tests)."""
    return asyncio.run(call_local_async(system_prompt, input_text, anchor_str))


async def check_ollama_connection(model: str = LOCAL_MODEL) -> bool:
    """
    Returns True if Ollama is reachable and the given model is available.
    Used at startup to warn the user if the required model is not pulled.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            return any(model in m for m in models)
    except Exception:
        return False
