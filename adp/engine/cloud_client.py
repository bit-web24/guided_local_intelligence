"""Async httpx client for the large Ollama model (decompose + assemble).

Used exclusively by decomposer.py and assembler.py.
Never instantiated elsewhere — this ensures the large model is called
exactly twice per pipeline run.
"""
from __future__ import annotations

import httpx

from adp.config import (
    get_model_config,
    resolve_stage_model,
    CLOUD_TEMPERATURE,
    CLOUD_TIMEOUT,
    OLLAMA_BASE_URL,
)
from adp.engine.call_stats import record_model_call


async def call_cloud_async(
    system_prompt: str,
    user_message: str,
    temperature: float = CLOUD_TEMPERATURE,
    max_tokens: int = 8192,
    stage_name: str = "cloud",
) -> str:
    """
    Call the large Ollama model asynchronously.

    Uses the /api/chat endpoint (multi-turn format) so system + user
    messages are correctly separated.

    Returns the raw response string from the model.
    """
    model_config = get_model_config()
    model_name = resolve_stage_model(stage_name, model_config.cloud)
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    async with httpx.AsyncClient(timeout=CLOUD_TIMEOUT) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        record_model_call(model_name, stage_name=stage_name)
        data = response.json()
        return data["message"]["content"]


async def call_cloud_with_history(
    messages: list[dict],
    temperature: float = CLOUD_TEMPERATURE,
    max_tokens: int = 8192,
    stage_name: str = "cloud",
) -> str:
    """
    Call the large model with a full message history (for retry/self-correction).

    messages format: [{"role": "system"|"user"|"assistant", "content": "..."}]
    """
    model_config = get_model_config()
    model_name = resolve_stage_model(stage_name, model_config.cloud)
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    async with httpx.AsyncClient(timeout=CLOUD_TIMEOUT) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        record_model_call(model_name, stage_name=stage_name)
        data = response.json()
        return data["message"]["content"]
