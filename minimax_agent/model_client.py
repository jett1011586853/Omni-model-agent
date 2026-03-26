from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from .config import AppConfig
from .rendering import ConsoleRenderer


@dataclass(frozen=True)
class UsageRecord:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    generation_seconds: float


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    arguments_json: str


@dataclass(frozen=True)
class ModelResponse:
    assistant_message: dict[str, Any]
    tool_calls: list[ToolCall]
    usage: UsageRecord
    finish_reason: str = ""


@dataclass
class _ToolCallAccumulator:
    id: str = ""
    name: str = ""
    arguments_json: str = ""


class _ThinkingStreamParser:
    def __init__(self) -> None:
        self._inside_thinking = False
        self._buffer = ""
        self._open_tag = "<think>"
        self._close_tag = "</think>"

    def feed(self, text: str) -> list[tuple[str, str]]:
        self._buffer += text
        events: list[tuple[str, str]] = []
        while True:
            if self._inside_thinking:
                close_index = self._buffer.find(self._close_tag)
                if close_index >= 0:
                    if close_index > 0:
                        events.append(("reasoning", self._buffer[:close_index]))
                    self._buffer = self._buffer[close_index + len(self._close_tag) :]
                    self._inside_thinking = False
                    continue
                safe_length = max(0, len(self._buffer) - (len(self._close_tag) - 1))
                if safe_length > 0:
                    events.append(("reasoning", self._buffer[:safe_length]))
                    self._buffer = self._buffer[safe_length:]
                break

            open_index = self._buffer.find(self._open_tag)
            if open_index >= 0:
                if open_index > 0:
                    events.append(("answer", self._buffer[:open_index]))
                self._buffer = self._buffer[open_index + len(self._open_tag) :]
                self._inside_thinking = True
                continue
            safe_length = max(0, len(self._buffer) - (len(self._open_tag) - 1))
            if safe_length > 0:
                events.append(("answer", self._buffer[:safe_length]))
                self._buffer = self._buffer[safe_length:]
            break
        return [(kind, chunk) for kind, chunk in events if chunk]

    def finalize(self) -> list[tuple[str, str]]:
        if not self._buffer:
            return []
        kind = "reasoning" if self._inside_thinking else "answer"
        data = self._buffer
        self._buffer = ""
        return [(kind, data)]


class OpenAICompatibleModelClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._client = httpx.Client(timeout=config.model.request_timeout_seconds)
        self._connection_guard: Callable[..., None] | None = None

    def close(self) -> None:
        self._client.close()

    def set_connection_guard(self, guard: Callable[..., None] | None) -> None:
        self._connection_guard = guard

    def _ensure_connection(self, *, force_reconnect: bool = False) -> None:
        if self._connection_guard is None:
            return
        self._connection_guard(force_reconnect=force_reconnect)

    def _uses_local_ssh_tunnel(self) -> bool:
        if self._config.ssh is None:
            return False
        base_url = self._config.model_base_url.rstrip("/")
        expected_prefix = f"http://{self._config.ssh.local_host}:{self._config.ssh.local_port}"
        return base_url.startswith(expected_prefix)

    def _is_transient_stream_error(self, exc: httpx.HTTPError) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {502, 503, 504}
        return False

    def _is_tunnel_transport_error(self, exc: httpx.HTTPError) -> bool:
        if not self._uses_local_ssh_tunnel():
            return False
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {502, 503, 504}
        return isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ReadError,
                httpx.WriteError,
                httpx.RemoteProtocolError,
                httpx.ProtocolError,
            ),
        )

    def _usage_from_payload(
        self,
        usage_payload: dict[str, Any] | None,
        *,
        timings: dict[str, Any] | None = None,
    ) -> UsageRecord:
        usage_payload = usage_payload or {}
        timings = timings or {}
        return UsageRecord(
            prompt_tokens=int(usage_payload.get("prompt_tokens", 0)),
            completion_tokens=int(usage_payload.get("completion_tokens", 0)),
            total_tokens=int(usage_payload.get("total_tokens", 0)),
            generation_seconds=float(timings.get("predicted_ms", 0.0)) / 1000.0,
        )

    def _normalize_tool_calls(
        self,
        raw_tool_calls: list[dict[str, Any]] | None,
    ) -> list[ToolCall]:
        normalized: list[ToolCall] = []
        for raw_tool_call in raw_tool_calls or []:
            function_payload = raw_tool_call.get("function", {}) or {}
            raw_arguments = str(function_payload.get("arguments", "")).strip() or "{}"
            try:
                parsed_arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                parsed_arguments = {"raw_arguments": raw_arguments}
            normalized.append(
                ToolCall(
                    id=str(raw_tool_call.get("id", "")),
                    name=str(function_payload.get("name", "")),
                    arguments=parsed_arguments,
                    arguments_json=json.dumps(parsed_arguments, ensure_ascii=False),
                )
            )
        return normalized

    def _fallback_non_stream_chat(
        self,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> ModelResponse:
        fallback_payload = dict(payload)
        fallback_payload.pop("stream", None)
        fallback_payload.pop("stream_options", None)
        self._ensure_connection()
        try:
            response = self._client.post(
                f"{self._config.model_base_url}/chat/completions",
                headers=headers,
                json=fallback_payload,
            )
        except httpx.HTTPError as exc:
            if not self._is_tunnel_transport_error(exc):
                raise
            self._ensure_connection(force_reconnect=True)
            response = self._client.post(
                f"{self._config.model_base_url}/chat/completions",
                headers=headers,
                json=fallback_payload,
            )
        response.raise_for_status()
        body = response.json()
        choice = next(iter(body.get("choices", [])), None)
        if not isinstance(choice, dict):
            raise RuntimeError("Remote model fallback returned no choices")

        assistant_message = dict(choice.get("message", {}) or {})
        assistant_message["role"] = str(assistant_message.get("role", "assistant"))
        assistant_message["content"] = str(assistant_message.get("content", "") or "")

        normalized_tool_calls = self._normalize_tool_calls(
            assistant_message.get("tool_calls", []),
        )
        if normalized_tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": item.id,
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": item.arguments_json,
                    },
                }
                for item in normalized_tool_calls
            ]

        return ModelResponse(
            assistant_message=assistant_message,
            tool_calls=normalized_tool_calls,
            usage=self._usage_from_payload(body.get("usage")),
            finish_reason=str(choice.get("finish_reason", "") or "").strip(),
        )

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        renderer: ConsoleRenderer,
        allow_tools: bool,
        *,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        top_p_override: float | None = None,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self._config.model_name,
            "messages": messages,
            "temperature": (
                self._config.model.temperature
                if temperature_override is None
                else temperature_override
            ),
            "top_p": self._config.model.top_p if top_p_override is None else top_p_override,
            "max_tokens": (
                self._config.model.max_output_tokens
                if max_tokens_override is None
                else max_tokens_override
            ),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if allow_tools and tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self._config.model_api_key}",
            "Content-Type": "application/json",
        }
        self._ensure_connection()
        parser = _ThinkingStreamParser()
        renderer.start_model_call()

        answer_chunks: list[str] = []
        tool_calls: dict[int, _ToolCallAccumulator] = {}
        usage = UsageRecord(0, 0, 0, 0.0)
        finish_reason = ""
        max_attempts = 3
        last_transient_error: httpx.HTTPError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with self._client.stream(
                    "POST",
                    f"{self._config.model_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        if raw == "[DONE]":
                            break

                        event = json.loads(raw)
                        if event.get("usage") and not event.get("choices"):
                            usage = self._usage_from_payload(
                                event.get("usage"),
                                timings=event.get("timings", {}),
                            )
                            continue

                        for choice in event.get("choices", []):
                            if choice.get("finish_reason") is not None:
                                finish_reason = str(choice.get("finish_reason") or "").strip()
                            delta = choice.get("delta", {})
                            content = delta.get("content")
                            if content:
                                for kind, chunk in parser.feed(content):
                                    if kind == "reasoning":
                                        renderer.on_reasoning(chunk)
                                    else:
                                        answer_chunks.append(chunk)
                                        renderer.on_answer(chunk)

                            for tool_call_chunk in delta.get("tool_calls", []):
                                index = int(tool_call_chunk.get("index", 0))
                                accumulator = tool_calls.setdefault(
                                    index, _ToolCallAccumulator()
                                )
                                if tool_call_chunk.get("id"):
                                    accumulator.id = tool_call_chunk["id"]
                                function_payload = tool_call_chunk.get("function", {})
                                if function_payload.get("name"):
                                    accumulator.name = function_payload["name"]
                                if function_payload.get("arguments"):
                                    accumulator.arguments_json += function_payload["arguments"]
                break
            except httpx.HTTPError as exc:
                has_started_output = bool(answer_chunks or tool_calls or finish_reason)
                if (
                    attempt < max_attempts
                    and not has_started_output
                    and self._is_tunnel_transport_error(exc)
                ):
                    self._ensure_connection(force_reconnect=True)
                    time.sleep(0.5 * attempt)
                    continue
                if (
                    attempt < max_attempts
                    and not has_started_output
                    and self._is_transient_stream_error(exc)
                ):
                    time.sleep(0.5 * attempt)
                    continue
                if not has_started_output and self._is_transient_stream_error(exc):
                    last_transient_error = exc
                    break
                raise RuntimeError(f"Remote model stream failed: {exc}") from exc

        if last_transient_error is not None:
            try:
                fallback_response = self._fallback_non_stream_chat(
                    payload=payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                raise RuntimeError(
                    "Remote model stream failed after retries: "
                    f"{last_transient_error}. Fallback non-stream request also failed: {exc}"
                ) from exc
            fallback_content = str(
                fallback_response.assistant_message.get("content", "") or ""
            )
            if fallback_content:
                renderer.on_answer(fallback_content)
            return fallback_response

        for kind, chunk in parser.finalize():
            if kind == "reasoning":
                renderer.on_reasoning(chunk)
            else:
                answer_chunks.append(chunk)
                renderer.on_answer(chunk)

        normalized_tool_calls: list[ToolCall] = []
        for index in sorted(tool_calls):
            accumulator = tool_calls[index]
            raw_arguments = accumulator.arguments_json.strip() or "{}"
            normalized_tool_calls.extend(
                self._normalize_tool_calls(
                    [
                        {
                            "id": accumulator.id,
                            "function": {
                                "name": accumulator.name,
                                "arguments": raw_arguments,
                            },
                        }
                    ]
                )
            )

        answer_content = "".join(answer_chunks).strip()
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": answer_content,
        }
        if normalized_tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": item.id,
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": item.arguments_json,
                    },
                }
                for item in normalized_tool_calls
            ]

        return ModelResponse(
            assistant_message=assistant_message,
            tool_calls=normalized_tool_calls,
            usage=usage,
            finish_reason=finish_reason,
        )
