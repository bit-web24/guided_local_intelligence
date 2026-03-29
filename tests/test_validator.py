"""Tests for adp/engine/validator.py — anchor extraction and output validation."""
import pytest

from adp.engine.validator import extract_after_anchor, validate
from adp.models.task import AnchorType


class TestExtractAfterAnchor:
    def test_anchor_present(self):
        raw = "Some preamble\nJSON: {\"key\": \"value\"}"
        result = extract_after_anchor(raw, AnchorType.JSON)
        assert result == '{"key": "value"}'

    def test_anchor_absent_returns_stripped(self):
        raw = "  just some text  "
        result = extract_after_anchor(raw, AnchorType.JSON)
        assert result == "just some text"

    def test_uses_last_occurrence(self):
        raw = "JSON: bad\nJSON: {\"good\": true}"
        result = extract_after_anchor(raw, AnchorType.JSON)
        assert result == '{"good": true}'

    def test_code_anchor(self):
        raw = "Here is the code:\nCode: def foo(): pass"
        result = extract_after_anchor(raw, AnchorType.CODE)
        assert result == "def foo(): pass"


class TestValidateJSON:
    def test_valid_object(self):
        ok, clean = validate('{"name": "adp"}', AnchorType.JSON)
        assert ok is True
        assert '"name"' in clean

    def test_valid_array(self):
        ok, clean = validate('[1, 2, 3]', AnchorType.JSON)
        assert ok is True

    def test_invalid_json(self):
        ok, _ = validate('{broken json', AnchorType.JSON)
        assert ok is False

    def test_empty_string(self):
        ok, _ = validate("", AnchorType.JSON)
        assert ok is False

    def test_with_markdown_fences(self):
        raw = "```json\n{\"key\": \"val\"}\n```"
        ok, clean = validate(raw, AnchorType.JSON)
        assert ok is True
        assert "```" not in clean

    def test_with_trailing_explanation(self):
        raw = '{"key": "val"} This is the JSON output.'
        ok, clean = validate(raw, AnchorType.JSON)
        assert ok is True
        assert "This is" not in clean


class TestValidateCode:
    def test_valid_code(self):
        ok, clean = validate("def add(a, b):\n    return a + b", AnchorType.CODE)
        assert ok is True

    def test_code_too_short(self):
        ok, _ = validate("x = 1", AnchorType.CODE)
        assert ok is False

    def test_code_with_fences(self):
        raw = "```python\ndef foo():\n    pass\n```"
        ok, clean = validate(raw, AnchorType.CODE)
        assert ok is True
        assert "```" not in clean

    def test_empty_code(self):
        ok, _ = validate("", AnchorType.CODE)
        assert ok is False


class TestValidateTOML:
    def test_valid_toml(self):
        toml = '[project]\nname = "adp"\nversion = "0.1.0"'
        ok, clean = validate(toml, AnchorType.TOML)
        assert ok is True

    def test_invalid_toml(self):
        ok, _ = validate("this is not toml !!!!", AnchorType.TOML)
        assert ok is False


class TestValidateOutput:
    def test_nonempty_passes(self):
        ok, clean = validate("some plain text output", AnchorType.OUTPUT)
        assert ok is True
        assert clean == "some plain text output"

    def test_empty_fails(self):
        ok, _ = validate("  ", AnchorType.OUTPUT)
        assert ok is False


class TestValidateMarkdown:
    def test_nonempty_passes(self):
        ok, clean = validate("# Title\n\nContent here.", AnchorType.MARKDOWN)
        assert ok is True

    def test_empty_fails(self):
        ok, _ = validate("", AnchorType.MARKDOWN)
        assert ok is False
