"""Async httpx client for the small Ollama model (micro-task execution).

Temperature is always 0.0 — hardcoded, never accepted as a parameter.
"""
from __future__ import annotations

import asyncio

import httpx

from adp.config import (
    get_model_config,
    LOCAL_TEMPERATURE,
    LOCAL_TIMEOUT,
    OLLAMA_BASE_URL,
)


async def call_local_async(
    system_prompt: str,
    input_text: str,
    anchor_str: str,
    model_name: str,
    temperature_override: float | None = None,
) -> str:
    """
    Call the small Ollama model asynchronously.

    The full user-facing prompt is: "Input: {input_text}\\n{anchor_str}"
    The system prompt is passed as the 'system' field (already filled with
    upstream context before this function is called).

    temperature_override: if set, overrides LOCAL_TEMPERATURE for this call.
    Used by the retry strategy to bump temperature on retries (0.0 → 0.1 → 0.2).
    Default behaviour (None) uses LOCAL_TEMPERATURE (0.0).

    Returns the raw model output string (may include preamble before anchor).
    """
    effective_temp = temperature_override if temperature_override is not None else LOCAL_TEMPERATURE
    full_prompt = f"Input: {input_text}\n{anchor_str}"
    payload = {
        "model": model_name,
        "system": system_prompt,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": effective_temp,
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


def call_local_sync(
    system_prompt: str,
    input_text: str,
    anchor_str: str,
    model_name: str,
) -> str:
    """Synchronous wrapper. Use only in non-async contexts (e.g. tests)."""
    return asyncio.run(call_local_async(system_prompt, input_text, anchor_str, model_name))


async def check_ollama_connection() -> bool:
    """
    Returns True if Ollama is reachable and both required local models are available.
    """
    models = get_model_config()
    required_models = {models.local_coder, models.local_general}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            data = response.json()
            available = {m["name"] for m in data.get("models", [])}
            # Check if each required model name is contained within the available models list
            # We use `any` to allow "qwen2.5-coder:1.5b" to match "qwen2.5-coder:1.5b-latest" etc.
            return all(any(req in avail for avail in available) for req in required_models)
    except Exception:
        return False
