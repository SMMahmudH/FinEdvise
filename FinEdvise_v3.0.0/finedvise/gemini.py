"""Thin client for the Gemini API (generateContent with function calling).

Standard library only. The API key is read from the environment, sent in the
x-goog-api-key header and never logged or sent to the browser. The model's
turns are appended back to the conversation exactly as received, so Gemini 3
thought signatures on function-call parts are preserved.

A transport can be injected for tests (see tests/test_agent.py).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
# Free-tier models checked on 2026-10-20 (ai.google.dev pricing page); tried in this order.
DEFAULT_MODEL = "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash"

Transport = Callable[[str, Dict[str, str], bytes, float], Tuple[int, str]]


class GeminiError(Exception):
    def __init__(self, message: str, status: int = 0, retry_next_model: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retry_next_model = retry_next_model


def urllib_transport(url: str, headers: Dict[str, str], body: bytes, timeout: float) -> Tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GeminiError(f"network error: {exc}", 0, retry_next_model=False) from exc


class GeminiClient:
    def __init__(self, api_key: str, models: Optional[List[str]] = None, thinking_level: Optional[str] = "low",
                 timeout: float = 40.0, transport: Optional[Transport] = None) -> None:
        if not api_key:
            raise ValueError("missing API key")
        self._key = api_key
        self.models = [m.strip() for m in (models or DEFAULT_MODEL.split(",")) if m.strip()]
        self.thinking_level = thinking_level or None
        self.timeout = timeout
        self.transport = transport or urllib_transport
        self.last_model: Optional[str] = None
        self.requests_made = 0

    @classmethod
    def from_env(cls) -> Optional["GeminiClient"]:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            return None
        models = os.environ.get("FINEDVISE_GEMINI_MODEL", DEFAULT_MODEL).split(",")
        level = os.environ.get("FINEDVISE_THINKING_LEVEL", "low")
        return cls(key, models, level)

    @property
    def model(self) -> str:
        return self.last_model or self.models[0]

    def _body(self, contents: List[Dict[str, Any]], system: str, tools: List[Dict[str, Any]], with_thinking: bool) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": [{"functionDeclarations": tools}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {"maxOutputTokens": 2048},
        }
        if with_thinking and self.thinking_level:
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        return body

    def generate(self, contents: List[Dict[str, Any]], system: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """One generateContent call; tries the next configured model on quota or availability errors."""
        last_error: Optional[GeminiError] = None
        for model in self.models:
            for with_thinking in (True, False):
                url = f"{API_ROOT}/models/{model}:generateContent"
                headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}
                payload = json.dumps(self._body(contents, system, tools, with_thinking)).encode("utf-8")
                self.requests_made += 1
                status, text = self.transport(url, headers, payload, self.timeout)
                if status == 200:
                    self.last_model = model
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise GeminiError("invalid JSON from the API", status) from exc
                message = _error_message(text)
                if status == 400 and with_thinking and "thinking" in message.lower():
                    continue  # this model does not accept the thinking setting; retry without it
                if status in (404, 429, 500, 503):
                    last_error = GeminiError(f"{model}: HTTP {status}: {message}", status, retry_next_model=True)
                    break
                raise GeminiError(f"{model}: HTTP {status}: {message}", status)
        raise last_error or GeminiError("no model configured")

    def list_models(self) -> List[str]:
        status, text = self.transport(f"{API_ROOT}/models?pageSize=200", {"x-goog-api-key": self._key}, b"", self.timeout)
        if status != 200:
            raise GeminiError(f"HTTP {status}: {_error_message(text)}", status)
        data = json.loads(text)
        return [m["name"].split("/", 1)[1] for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]


def _error_message(text: str) -> str:
    try:
        return json.loads(text).get("error", {}).get("message", text[:200])
    except (json.JSONDecodeError, AttributeError):
        return text[:200]


def extract(response: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, str]:
    """Return (model_content, function_calls, answer_text, finish_reason)."""
    candidates = response.get("candidates") or []
    if not candidates:
        reason = (response.get("promptFeedback") or {}).get("blockReason", "NO_CANDIDATES")
        raise GeminiError(f"no answer from the model ({reason})")
    cand = candidates[0]
    content = cand.get("content") or {"role": "model", "parts": []}
    parts = content.get("parts") or []
    calls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought") and "text" in p)
    return content, calls, text.strip(), cand.get("finishReason", "")
