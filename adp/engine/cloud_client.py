"""Async httpx client for the large Ollama model (decompose + assemble).

Used exclusively by decomposer.py and assembler.py.
Never instantiated elsewhere — this ensures the large model is called
exactly twice per pipeline run.
"""
from __future__ import annotations

import httpx

from adp.config import (
    get_model_config,
    CLOUD_TEMPERATURE,
    CLOUD_TIMEOUT,
    OLLAMA_BASE_URL,
)


async def call_cloud_async(
    system_prompt: str,
    user_message: str,
    temperature: float = CLOUD_TEMPERATURE,
    max_tokens: int = 8192,
) -> str:
    """
    Call the large Ollama model asynchronously.

    Uses the /api/chat endpoint (multi-turn format) so system + user
    messages are correctly separated.

    Returns the raw response string from the model.
    """
    model_config = get_model_config()
    payload = {
        "model": model_config.cloud,
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
        data = response.json()
        return data["message"]["content"]


async def call_cloud_with_history(
    messages: list[dict],
    temperature: float = CLOUD_TEMPERATURE,
    max_tokens: int = 8192,
) -> str:
    """
    Call the large model with a full message history (for retry/self-correction).

    messages format: [{"role": "system"|"user"|"assistant", "content": "..."}]
    """
    model_config = get_model_config()
    payload = {
        "model": model_config.cloud,
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
        data = response.json()
        return data["message"]["content"]
