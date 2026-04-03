"""Tests for runtime model configuration and routing."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from adp.config import (
    DEFAULT_CLOUD_MODEL,
    DEFAULT_LOCAL_CODER_MODEL,
    DEFAULT_LOCAL_GENERAL_MODEL,
    get_model_config,
    set_model_config,
)
from adp.engine.cloud_client import call_cloud_async
from adp.models.task import AnchorType, MicroTask, TaskStatus
from adp.stages.executor import execute_task
from adp.tui.panels import render_header


def _noop(_task) -> None:
    pass


class TestModelConfig:
    def test_defaults_resolve_from_single_place(self, monkeypatch):
        monkeypatch.delenv("CLOUD_MODEL", raising=False)
        monkeypatch.delenv("LOCAL_CODER_MODEL", raising=False)
        monkeypatch.delenv("LOCAL_GENERAL_MODEL", raising=False)

        models = get_model_config()

        assert models.cloud == DEFAULT_CLOUD_MODEL
        assert models.local_coder == DEFAULT_LOCAL_CODER_MODEL
        assert models.local_general == DEFAULT_LOCAL_GENERAL_MODEL

    def test_set_model_config_supports_shared_and_split_local_overrides(self, monkeypatch):
        monkeypatch.delenv("CLOUD_MODEL", raising=False)
        monkeypatch.delenv("LOCAL_CODER_MODEL", raising=False)
        monkeypatch.delenv("LOCAL_GENERAL_MODEL", raising=False)

        models = set_model_config(cloud="cloud-a", local="local-a")
        assert models.cloud == "cloud-a"
        assert models.local_coder == "local-a"
        assert models.local_general == "local-a"

        models = set_model_config(local_coder="coder-b", local_general="general-b")
        assert models.local_coder == "coder-b"
        assert models.local_general == "general-b"


class TestRuntimeModelUsage:
    @pytest.mark.asyncio
    async def test_executor_uses_runtime_local_model_overrides(self, monkeypatch):
        monkeypatch.setenv("LOCAL_CODER_MODEL", "coder-runtime")
        monkeypatch.setenv("LOCAL_GENERAL_MODEL", "general-runtime")

        task = MicroTask(
            id="t1",
            description="Write code",
            system_prompt_template="EXAMPLES:\nInput: a\nCode: b\n---\nInput: {input_text}\nCode:",
            input_text="run this",
            output_key="code",
            depends_on=[],
            anchor=AnchorType.CODE,
            parallel_group=0,
            model_type="coder",
        )

        with patch("adp.stages.executor.call_local_async", return_value="Code: print('ok')") as mock_call:
            context = {}
            await execute_task(task, context, _noop, _noop, _noop)

        assert task.status == TaskStatus.DONE
        assert context["code"] == "print('ok')"
        assert mock_call.await_args.kwargs["model_name"] == "coder-runtime"

    @pytest.mark.asyncio
    async def test_cloud_client_uses_runtime_cloud_override(self, monkeypatch):
        monkeypatch.setenv("CLOUD_MODEL", "cloud-runtime")

        captured_payload: dict = {}

        class DummyClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, _url, json):
                captured_payload.update(json)
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"message": {"content": "ok"}},
                )

        with patch("adp.engine.cloud_client.httpx.AsyncClient", DummyClient):
            result = await call_cloud_async("system", "user")

        assert result == "ok"
        assert captured_payload["model"] == "cloud-runtime"

    def test_tui_header_reads_runtime_models(self, monkeypatch):
        monkeypatch.setenv("CLOUD_MODEL", "cloud-header")
        monkeypatch.setenv("LOCAL_CODER_MODEL", "coder-header")
        monkeypatch.setenv("LOCAL_GENERAL_MODEL", "general-header")

        panel = render_header("IDLE", ollama_ok=True)
        header_text = panel.renderable.plain

        assert "cloud-header" in header_text
        assert "coder-header | general-header" in header_text
