from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import AppConfig
from .model_client import OpenAICompatibleModelClient, UsageRecord
from .rendering import NullRenderer
from .task_store import MemoryRecord, TaskRecord


@dataclass(frozen=True)
class PlannedStep:
    title: str
    description: str


@dataclass(frozen=True)
class TaskPlan:
    title: str
    goal: str
    steps: list[PlannedStep]
    memory_summary: str
    raw_plan: str


def _extract_numbered_steps_from_request(user_request: str) -> list[PlannedStep]:
    pattern = re.compile(r"(?:(?<=^)|(?<=[；;\n]))\s*(\d+)[\.\、:：]\s*")
    matches = list(pattern.finditer(user_request))
    if len(matches) < 2:
        return []

    steps: list[PlannedStep] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(user_request)
        content = user_request[start:end].strip(" \n；;。")
        if not content:
            continue
        title = re.split(r"[，,:：]", content, maxsplit=1)[0].strip()[:48] or f"Step {index + 1}"
        steps.append(
            PlannedStep(
                title=title,
                description=content,
            )
        )
    return steps[:12]


def _extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") and part.endswith("}"):
                return json.loads(part)
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        return json.loads(stripped[first : last + 1])
    raise ValueError("Planner did not return a JSON object")


_GENERIC_PLAN_TITLES = {
    "",
    "task",
    "request",
    "complete request",
    "handle request",
    "fulfill request",
    "execute task",
    "generic task",
    "任务",
    "请求",
    "完成请求",
    "处理请求",
    "执行任务",
}


def _normalize_plan_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def _contains_any_marker(*texts: str, markers: list[str]) -> bool:
    for marker in markers:
        if not marker:
            continue
        for text in texts:
            if marker in text:
                return True
    return False


def _derive_task_title(user_request: str) -> str:
    for line in user_request.splitlines():
        candidate = line.strip(" -*\t")
        if candidate:
            return candidate[:48]
    normalized = " ".join(user_request.split()).strip()
    return normalized[:48] or "Task"


def _is_generic_plan_title(title: str) -> bool:
    return _normalize_plan_text(title) in _GENERIC_PLAN_TITLES


def _is_generic_step(step: PlannedStep, user_request: str) -> bool:
    title = _normalize_plan_text(step.title)
    description = _normalize_plan_text(step.description)
    request = _normalize_plan_text(user_request)
    if title in _GENERIC_PLAN_TITLES:
        return True
    if description in {"", request}:
        return True
    return False


def _looks_substantial_request(user_request: str) -> bool:
    request = user_request.strip()
    request_lower = request.lower()
    if len(request) >= 80:
        return True
    markers = [
        "开发",
        "实现",
        "设计",
        "构建",
        "搭建",
        "创建",
        "制作",
        "编写",
        "重构",
        "修复",
        "项目",
        "系统",
        "应用",
        "网站",
        "游戏",
        "接口",
        "前端",
        "后端",
        "架构",
        "workflow",
        "project",
        "system",
        "application",
        "website",
        "game",
        "implement",
        "develop",
        "design",
        "build",
        "refactor",
        "fix",
    ]
    return _contains_any_marker(request, request_lower, markers=markers)


def _build_substantial_fallback_steps(user_request: str) -> list[PlannedStep]:
    title = _derive_task_title(user_request)
    request = user_request.strip()
    request_lower = request.lower()

    is_software_like = _contains_any_marker(
        request,
        request_lower,
        markers=[
            "开发",
            "实现",
            "编写",
            "代码",
            "项目",
            "系统",
            "应用",
            "网站",
            "游戏",
            "程序",
            "接口",
            "功能",
            "agent",
            "project",
            "system",
            "app",
            "website",
            "game",
            "code",
            "feature",
        ],
    )
    if not is_software_like:
        return [
            PlannedStep(title="理解目标", description=f"明确“{title}”的目标、范围和关键约束。"),
            PlannedStep(title="拆分重点", description=f"将“{title}”拆成若干关键组成部分并确定优先级。"),
            PlannedStep(title="完成主体", description="围绕最高优先级部分给出完整、可执行的主体结果。"),
            PlannedStep(title="校验收尾", description="检查遗漏、补足风险点，并整理最终可交付结果。"),
        ]

    return [
        PlannedStep(title="梳理需求与边界", description=f"明确“{title}”的目标、约束、平台和成功标准。"),
        PlannedStep(title="设计核心方案", description=f"拆解“{title}”的核心流程、模块和关键机制。"),
        PlannedStep(title="搭建基础骨架", description="建立项目结构、主要模块分工和最小可运行入口。"),
        PlannedStep(title="实现核心功能", description="优先完成最关键的功能路径，确保主流程能够跑通。"),
        PlannedStep(title="补充验证与收尾", description="补齐必要内容、验证结果质量，并整理最终交付说明。"),
    ]


class TaskPlanner:
    def __init__(self, config: AppConfig, client: OpenAICompatibleModelClient) -> None:
        self._config = config
        self._client = client
        self._silent_renderer = NullRenderer()

    def _format_memories(self, memories: list[MemoryRecord]) -> str:
        if not memories:
            return "None"
        return "\n".join(
            [
                f"- [{item.kind}] {item.summary} (task={item.source_task_id or 'n/a'})"
                for item in memories
            ]
        )

    def _format_recent_tasks(self, recent_tasks: list[TaskRecord]) -> str:
        if not recent_tasks:
            return "None"
        return "\n".join(
            [f"- {task.task_id}: {task.title} [{task.status}]" for task in recent_tasks]
        )

    def _build_messages(
        self,
        *,
        user_request: str,
        memories: list[MemoryRecord],
        recent_tasks: list[TaskRecord],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                "You are a strict task planner. Break the request into a short, actionable "
                "plan. Return JSON only with this schema: "
                "{\"title\": string, \"goal\": string, \"memory_summary\": string, "
                "\"steps\": [{\"title\": string, \"description\": string}]}. "
                "Limit steps to 1-12. Prefer 1 step for straightforward requests and only "
                "use multiple steps when the task truly has separate stages. If the user "
                "explicitly asks for phases, stages, or numbered steps, preserve them as "
                "separate plan steps instead of collapsing them into one. For substantial "
                "software or game-development requests, prefer 4-12 staged steps. Keep titles concise. "
                "Do not include markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User request:\n{user_request}\n\n"
                    f"Relevant memories:\n{self._format_memories(memories)}\n\n"
                    f"Recent tasks:\n{self._format_recent_tasks(recent_tasks)}"
                ),
            },
        ]

    def _parse_plan(self, *, user_request: str, raw_plan: str) -> TaskPlan:
        try:
            data = _extract_json_object(raw_plan)
            steps = data.get("steps") or []
            normalized_steps = [
                PlannedStep(
                    title=str(step.get("title", f"Step {index + 1}")).strip()
                    or f"Step {index + 1}",
                    description=str(step.get("description", "")).strip()
                    or str(step.get("title", f"Step {index + 1}")).strip(),
                )
                for index, step in enumerate(steps[: self._config.planner.max_steps])
            ]
            explicit_steps = _extract_numbered_steps_from_request(user_request)
            if len(normalized_steps) <= 1 and len(explicit_steps) > 1:
                normalized_steps = explicit_steps
            if (
                len(normalized_steps) <= 1
                and _looks_substantial_request(user_request)
                and (
                    not normalized_steps
                    or _is_generic_step(normalized_steps[0], user_request)
                    or _is_generic_plan_title(str(data.get("title", "")))
                )
            ):
                normalized_steps = _build_substantial_fallback_steps(user_request)
            if not normalized_steps:
                raise ValueError("Planner returned no steps")
            title = str(data.get("title", "Task")).strip() or "Task"
            if _is_generic_plan_title(title):
                title = _derive_task_title(user_request)
            return TaskPlan(
                title=title,
                goal=str(data.get("goal", user_request)).strip() or user_request,
                steps=normalized_steps,
                memory_summary=str(data.get("memory_summary", "")).strip(),
                raw_plan=raw_plan,
            )
        except Exception:
            explicit_steps = _extract_numbered_steps_from_request(user_request)
            fallback_steps = explicit_steps
            if not fallback_steps and _looks_substantial_request(user_request):
                fallback_steps = _build_substantial_fallback_steps(user_request)
            return TaskPlan(
                title=_derive_task_title(user_request),
                goal=user_request,
                steps=fallback_steps
                or [PlannedStep(title="Complete request", description=user_request)],
                memory_summary=user_request[:200],
                raw_plan=raw_plan,
            )

    def plan_with_usage(
        self,
        *,
        user_request: str,
        memories: list[MemoryRecord],
        recent_tasks: list[TaskRecord],
    ) -> tuple[TaskPlan, UsageRecord]:
        response = self._client.stream_chat(
            messages=self._build_messages(
                user_request=user_request,
                memories=memories,
                recent_tasks=recent_tasks,
            ),
            tools=[],
            renderer=self._silent_renderer,
            allow_tools=False,
            max_tokens_override=self._config.planner.max_output_tokens,
            temperature_override=self._config.planner.temperature,
            top_p_override=0.9,
        )
        raw_plan = response.assistant_message.get("content", "").strip()
        return (
            self._parse_plan(user_request=user_request, raw_plan=raw_plan),
            response.usage,
        )

    def plan(
        self,
        *,
        user_request: str,
        memories: list[MemoryRecord],
        recent_tasks: list[TaskRecord],
    ) -> TaskPlan:
        plan, _usage = self.plan_with_usage(
            user_request=user_request,
            memories=memories,
            recent_tasks=recent_tasks,
        )
        return plan
