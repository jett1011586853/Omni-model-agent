from __future__ import annotations

import math
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .config import AppConfig
from .model_client import ModelResponse, OpenAICompatibleModelClient, UsageRecord
from .rendering import ConsoleRenderer, TurnSummary
from .tools import ToolRegistry


def _add_messages(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return left + right


def _add_usage_records(left: list[UsageRecord], right: list[UsageRecord]) -> list[UsageRecord]:
    return left + right


class AgentState(TypedDict):
    messages: Annotated[list[dict[str, Any]], _add_messages]
    pending_tool_calls: list[dict[str, Any]]
    tool_round: int
    usage_records: Annotated[list[UsageRecord], _add_usage_records]
    last_finish_reason: str
    last_allow_tools: bool


class GraphAgent:
    def __init__(
        self,
        config: AppConfig,
        client: OpenAICompatibleModelClient,
        tools: ToolRegistry,
        renderer: ConsoleRenderer,
    ) -> None:
        self._config = config
        self._client = client
        self._tools = tools
        self._renderer = renderer
        self._history: list[dict[str, Any]] = []
        self._graph = self._build_graph().compile()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)
        graph.add_node("model", self._model_node)
        graph.add_node("tools", self._tools_node)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", self._route_after_model, ["tools", END])
        graph.add_edge("tools", "model")
        return graph

    def _route_after_model(self, state: AgentState) -> str:
        return "tools" if state["pending_tool_calls"] else END

    def _model_node(self, state: AgentState) -> dict[str, Any]:
        allow_tools = state["tool_round"] < self._config.agent.max_tool_rounds
        response: ModelResponse = self._client.stream_chat(
            messages=state["messages"],
            tools=self._tools.openai_tools,
            renderer=self._renderer,
            allow_tools=allow_tools,
        )
        pending_tool_calls = [
            {
                "id": item.id,
                "name": item.name,
                "arguments": item.arguments,
                "arguments_json": item.arguments_json,
            }
            for item in response.tool_calls
        ]
        return {
            "messages": [response.assistant_message],
            "pending_tool_calls": pending_tool_calls,
            "usage_records": [response.usage],
            "last_finish_reason": response.finish_reason,
            "last_allow_tools": allow_tools,
        }

    def _tools_node(self, state: AgentState) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        for tool_call in state["pending_tool_calls"]:
            self._renderer.on_tool_call(
                name=tool_call["name"],
                arguments=tool_call["arguments_json"],
            )
            result = self._tools.call(tool_call["name"], tool_call["arguments"])
            self._renderer.on_tool_result(tool_call["name"], result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                }
            )
        return {
            "messages": messages,
            "pending_tool_calls": [],
            "tool_round": state["tool_round"] + 1,
        }

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self._config.model.chars_per_token_estimate))

    def _estimate_message_tokens(self, message: dict[str, Any]) -> int:
        total = 4
        total += self._estimate_tokens(str(message.get("content", "")))
        for tool_call in message.get("tool_calls", []):
            total += self._estimate_tokens(str(tool_call))
        return total

    def _trim_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        trimmed = history[-self._config.agent.max_history_messages :]
        budget = (
            self._config.model.context_window_tokens
            - self._config.model.max_output_tokens
            - self._config.model.history_safety_margin_tokens
        )
        while trimmed and sum(self._estimate_message_tokens(msg) for msg in trimmed) > budget:
            trimmed = trimmed[2:]
        return trimmed

    def _current_context(self, user_input: str) -> list[dict[str, Any]]:
        messages = [{"role": "system", "content": self._config.agent.system_prompt}]
        trimmed_history = self._trim_history(self._history)
        messages.extend(trimmed_history)
        messages.append({"role": "user", "content": user_input})
        return messages

    def _summarize_usage(self, usage_records: list[UsageRecord]) -> TurnSummary:
        prompt_tokens = sum(item.prompt_tokens for item in usage_records)
        completion_tokens = sum(item.completion_tokens for item in usage_records)
        total_tokens = sum(item.total_tokens for item in usage_records)
        generation_seconds = sum(item.generation_seconds for item in usage_records)
        return TurnSummary(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            generation_seconds=generation_seconds,
        )

    def run_messages_detailed(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[str, TurnSummary, list[dict[str, Any]], dict[str, Any]]:
        self._renderer.start_turn()
        initial_state: AgentState = {
            "messages": messages,
            "pending_tool_calls": [],
            "tool_round": 0,
            "usage_records": [],
            "last_finish_reason": "",
            "last_allow_tools": True,
        }
        result = self._graph.invoke(initial_state)
        summary = self._summarize_usage(result["usage_records"])
        self._renderer.finish_turn(summary)

        final_assistant = ""
        for message in reversed(result["messages"]):
            if message.get("role") == "assistant" and message.get("content"):
                final_assistant = str(message["content"]).strip()
                if final_assistant:
                    break

        metadata = {
            "finish_reason": str(result.get("last_finish_reason", "")).strip(),
            "last_allow_tools": bool(result.get("last_allow_tools", True)),
            "tool_rounds_used": int(result.get("tool_round", 0)),
            "max_tool_rounds_reached": int(result.get("tool_round", 0))
            >= self._config.agent.max_tool_rounds,
        }

        return final_assistant, summary, result["messages"], metadata

    def run_messages(self, messages: list[dict[str, Any]]) -> tuple[str, TurnSummary]:
        final_assistant, summary, _messages, _metadata = self.run_messages_detailed(messages)
        return final_assistant, summary

    def invoke(self, user_input: str) -> str:
        final_assistant, _ = self.run_messages(self._current_context(user_input))

        if final_assistant:
            self._history.extend(
                [
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": final_assistant},
                ]
            )
            self._history = self._trim_history(self._history)

        return final_assistant
