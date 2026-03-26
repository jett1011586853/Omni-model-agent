from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .agentos import AgentKernel, KernelSession, PriorityClass, ProcessResult, UnitRunSpec
from .config import AppConfig
from .graph_agent import GraphAgent
from .multimodal import (
    AttachmentPayload,
    build_attachment_payloads,
    build_attachment_payloads_from_refs,
    parse_inline_image_command,
    summarize_attachment_refs,
)
from .planner import PlannedStep, TaskPlan, TaskPlanner
from .rendering import ConsoleRenderer
from .skills import SkillCatalog
from .task_store import (
    MemoryRecord,
    TaskCheckpointRecord,
    TaskEventRecord,
    TaskIpcMessageRecord,
    TaskProcessRecord,
    TaskRecord,
    TaskStore,
    TaskTargetRecord,
    TaskUnitRecord,
)


_DISPLAY_WRAP_WIDTH = 96

_AGENT_TYPE_LABELS = {
    "agent": "智能体",
    "agentd": "监督器",
    "router": "路由器",
    "planner": "规划器",
    "retriever": "检索器",
    "coder": "编码器",
    "executor": "执行器",
    "critic": "评审器",
    "verifier": "验证器",
    "compressor": "压缩器",
    "archivist": "归档器",
    "negotiator": "协调器",
}

_PRIORITY_LABELS = {
    "realtime": "实时",
    "high": "高",
    "normal": "普通",
    "background": "后台",
}

_STATE_LABELS = {
    "pending": "待执行",
    "in_progress": "进行中",
    "ready": "就绪",
    "running": "执行中",
    "waiting": "等待中",
    "completed": "已完成",
    "failed": "失败",
    "zombie": "僵尸",
    "inactive": "未激活",
    "activating": "启动中",
    "blocked": "阻塞中",
}

_LEVEL_LABELS = {
    "info": "信息",
    "warning": "警告",
    "error": "错误",
}

_PHASE_LABELS = {
    "spawned": "已创建",
    "before_execute": "执行前",
    "after_execute": "执行后",
    "waiting": "等待中",
    "failed": "失败",
    "restored": "已恢复",
}

_TARGET_LABELS = {
    "planning": "规划阶段目标",
    "step": "步骤目标",
    "completion": "收尾阶段目标",
    "task": "任务总目标",
}

_ARTIFACT_COUNT_LABELS = {
    "task_snapshot": "任务快照",
    "event_records": "事件记录",
    "ipc_records": "IPC 消息",
    "process_files": "进程快照",
    "unit_files": "执行单元快照",
    "unit_graph_files": "单元图文件",
    "target_files": "目标快照",
    "target_graph_files": "目标图文件",
    "checkpoint_files": "检查点文件",
    "tool_trace_files": "工具轨迹文件",
    "eval_files": "评测文件",
}

_ARTIFACT_PATH_LABELS = {
    "session_dir": "会话目录",
    "task_json": "任务快照文件",
    "events_jsonl": "事件日志",
    "ipc_dir": "IPC 目录",
    "ipc_jsonl": "IPC 日志",
    "processes_dir": "进程目录",
    "units_dir": "单元目录",
    "targets_dir": "目标目录",
    "unit_graph_json": "单元图 JSON",
    "unit_graph_mermaid": "单元图 Mermaid",
    "target_graph_json": "目标图 JSON",
    "target_graph_mermaid": "目标图 Mermaid",
    "checkpoints_dir": "检查点目录",
    "tools_dir": "工具输出目录",
    "evals_dir": "评测目录",
    "archive_root": "归档根目录",
}

_ROUTE_LABELS = {
    "development": "开发",
    "analysis": "分析",
    "research": "调研",
    "qa": "质量检查",
    "multimodal": "多模态",
    "workspace_execution": "开发",
    "web_research": "调研",
    "task": "通用任务",
}

_EVENT_KIND_LABELS = {
    "session.open": "会话启动",
    "route.selected": "路由决策",
    "process.spawn": "进程启动",
    "process.run": "进程运行",
    "process.wait": "进程等待",
    "process.wake": "进程唤醒",
    "process.complete": "进程完成",
    "process.failed": "进程失败",
    "syscall.tool": "工具调用",
    "ipc.send": "IPC 发送",
    "checkpoint.restore": "检查点恢复",
    "unit.register": "单元注册",
    "unit.state": "单元状态",
    "unit.restart": "单元重启",
    "unit.timeout": "单元超时",
    "unit.slow": "单元较慢",
    "unit.on_failure.queued": "失败回调单元排队",
    "unit.on_failure.failed": "失败回调单元异常",
    "unit.on_success.queued": "成功回调单元排队",
    "unit.on_success.failed": "成功回调单元异常",
    "target.register": "目标注册",
    "target.state": "目标状态",
    "target.on_success.queued": "后继目标排队",
    "task.supervisor.recover": "监督恢复",
    "context.compressed": "上下文压缩",
    "step.waiting": "步骤等待",
    "executor.incomplete_output": "执行器输出不完整",
    "critic.reject": "评审拒绝",
    "verifier.reject": "验证拒绝",
}


def _display_agent_type(agent_type: str) -> str:
    value = str(agent_type).strip()
    return _AGENT_TYPE_LABELS.get(value, value or "智能体")


def _display_priority(priority: str) -> str:
    value = str(priority).strip()
    return _PRIORITY_LABELS.get(value, value or "未知")


def _display_state(state: str) -> str:
    value = str(state).strip()
    return _STATE_LABELS.get(value, value or "未知")


def _display_phase(phase: str) -> str:
    value = str(phase).strip()
    return _PHASE_LABELS.get(value, value or "阶段")


def _display_route(route: str) -> str:
    value = str(route).strip()
    return _ROUTE_LABELS.get(value, value or "未知")


def _describe_runtime_suffix(instance: str) -> str:
    value = str(instance).strip()
    if not value:
        return ""
    match = re.fullmatch(r"step-(\d+)-attempt-(\d+)", value)
    if match:
        return f"步骤 {int(match.group(1))}，第 {int(match.group(2))} 次尝试"
    match = re.fullmatch(r"failure-step-(\d+)", value)
    if match:
        return f"失败恢复：步骤 {int(match.group(1))}"
    match = re.fullmatch(r"success-of-(.+)", value)
    if match:
        return f"成功回调：{match.group(1)}"
    match = re.fullmatch(r"failure-of-(.+)", value)
    if match:
        return f"失败回调：{match.group(1)}"
    return value.replace("-", " ")


def _describe_unit_name(unit_name: str) -> str:
    raw = str(unit_name).strip()
    if not raw:
        return "未命名单元"
    base = raw.removesuffix(".service")
    role, _, instance = base.partition("@")
    role_label = _display_agent_type(role)
    suffix = _describe_runtime_suffix(instance)
    if suffix:
        return f"{role_label}（{suffix}）"
    return role_label


def _describe_target_name(target_name: str) -> str:
    raw = str(target_name).strip()
    if not raw:
        return "未命名目标"
    base = raw.removesuffix(".target")
    role, _, instance = base.partition("@")
    role_label = _TARGET_LABELS.get(role, f"{role} 目标")
    suffix = _describe_runtime_suffix(instance)
    if suffix:
        return f"{role_label}（{suffix}）"
    return role_label


def _display_summary_text(text: str) -> str:
    value = str(text).strip()
    if not value:
        return "无"

    match = re.fullmatch(
        r"Remote model stream failed: (Server|Client) error '([^']+)' for url '([^']+)'(?:\s+For more information check:\s+.+)?",
        value,
    )
    if match:
        return f"远程模型流式调用失败：模型网关返回 {match.group(2)}（{match.group(3)}）"

    match = re.fullmatch(r"Spawned ([a-z_]+)", value)
    if match:
        return f"已创建{_display_agent_type(match.group(1))}进程"

    match = re.fullmatch(r"Starting ([a-z_]+)", value)
    if match:
        return f"开始执行{_display_agent_type(match.group(1))}"

    match = re.fullmatch(r"Route=([^|]+)\s+\|\s+web=(True|False)\s+\|\s+files=(True|False)", value)
    if match:
        web = "是" if match.group(2) == "True" else "否"
        files = "是" if match.group(3) == "True" else "否"
        return f"路由结果：{_display_route(match.group(1).strip())}；联网：{web}；文件访问：{files}"

    match = re.fullmatch(r"Planned (\d+) step\(s\) for '(.+)'", value)
    if match:
        return f"已为“{match.group(2)}”规划 {int(match.group(1))} 个步骤"

    match = re.fullmatch(r"unit (.+) timed out after ([0-9.]+)s \(limit ([0-9.]+)s\)", value)
    if match:
        return (
            f"执行单元超时：{_describe_unit_name(match.group(1))}，"
            f"耗时 {match.group(2)} 秒，限制 {match.group(3)} 秒"
        )

    match = re.fullmatch(r"unit (.+) timed out", value)
    if match:
        return f"执行单元超时：{_describe_unit_name(match.group(1))}"

    match = re.fullmatch(r"registered unit (.+)", value)
    if match:
        return f"已注册执行单元：{_describe_unit_name(match.group(1))}"

    match = re.fullmatch(r"unit (.+) -> ([a-z_]+)", value)
    if match:
        return f"执行单元状态更新：{_describe_unit_name(match.group(1))} -> {_display_state(match.group(2))}"

    match = re.fullmatch(r"registered target (.+)", value)
    if match:
        return f"已注册目标：{_describe_target_name(match.group(1))}"

    match = re.fullmatch(r"([a-z_]+) target (.+)", value)
    if match:
        return f"{_describe_target_name(match.group(2))} 当前状态：{_display_state(match.group(1))}"

    match = re.fullmatch(r"target (.+) -> ([a-z_]+)", value)
    if match:
        return f"目标状态更新：{_describe_target_name(match.group(1))} -> {_display_state(match.group(2))}"

    match = re.fullmatch(r"spawned ([a-z_]+) process ([a-z0-9]+)", value)
    if match:
        return f"已启动{_display_agent_type(match.group(1))}进程（ID: {match.group(2)}）"

    match = re.fullmatch(r"running ([a-z_]+) process ([a-z0-9]+)", value)
    if match:
        return f"{_display_agent_type(match.group(1))}进程开始运行（ID: {match.group(2)}）"

    match = re.fullmatch(r"completed ([a-z_]+) process ([a-z0-9]+)", value)
    if match:
        return f"{_display_agent_type(match.group(1))}进程已完成（ID: {match.group(2)}）"

    match = re.fullmatch(r"failed ([a-z_]+) process ([a-z0-9]+)", value)
    if match:
        return f"{_display_agent_type(match.group(1))}进程执行失败（ID: {match.group(2)}）"

    match = re.fullmatch(r"on-failure unit (.+) failed for (.+)", value)
    if match:
        return f"失败回调单元 {match.group(1)} 在处理 {_describe_unit_name(match.group(2))} 时失败"

    match = re.fullmatch(r"queued on-failure unit (.+)", value)
    if match:
        return f"已排队失败回调单元：{_describe_unit_name(match.group(1))}"

    match = re.fullmatch(r"restarting unit (.+)", value)
    if match:
        return f"准备重启执行单元：{_describe_unit_name(match.group(1))}"

    match = re.fullmatch(r"router selected ([a-z_]+)", value)
    if match:
        return f"路由完成：当前任务被判定为“{_display_route(match.group(1))}”类型"

    if value == "agentd opened task session":
        return "agentd 已打开任务会话"

    return value


def _display_level(level: str) -> str:
    value = str(level).strip()
    return _LEVEL_LABELS.get(value, value or "未知")


def _display_event_kind(kind: str) -> str:
    value = str(kind).strip()
    return _EVENT_KIND_LABELS.get(value, value or "运行时事件")


def _display_wait_detail(process: TaskProcessRecord) -> str:
    if not process.wait_kind and not process.wait_target:
        return "无"
    if process.wait_kind == "process":
        target = process.wait_target or "-"
        return f"等待进程 {target} 完成"
    if process.wait_kind == "ipc":
        channel = str(process.wait_payload.get("channel", "")).strip() or "default"
        recipient = process.wait_target or process.process_id
        return f"等待 IPC 消息（接收方: {recipient}，通道: {channel}）"
    target = process.wait_target or "-"
    return f"{process.wait_kind}:{target}"


def _extract_preview_field(preview: str, field: str) -> str:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"', preview)
    if not match:
        return ""
    try:
        return json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        return match.group(1)


def _display_process_preview(preview: str) -> str:
    value = str(preview).strip()
    if not value:
        return "无"

    route = _extract_preview_field(value, "route")
    if route:
        return f"路由结果：{_display_route(route)}"

    summary = _extract_preview_field(value, "summary")
    if summary:
        return _display_summary_text(summary)

    content = _extract_preview_field(value, "content")
    if content:
        return content

    error = _extract_preview_field(value, "error")
    if error:
        return error

    if '"plan"' in value:
        return "已生成任务规划，包含标题、目标和步骤列表"

    return value


def _display_event_message(event: TaskEventRecord) -> str:
    message = str(event.message).strip()
    if not message:
        return "无说明"

    match = re.fullmatch(r"([a-z_]+) called ([a-z0-9_]+)", message)
    if match:
        return f"{_display_agent_type(match.group(1))}调用了工具 {match.group(2)}"

    match = re.fullmatch(r"(\w+) sent IPC to (\w+)", message)
    if match:
        return f"进程 {match.group(1)} 向进程 {match.group(2)} 发送了 IPC 消息"

    match = re.fullmatch(r"queued on-failure unit (.+)", message)
    if match:
        return f"已排队失败回调单元：{_describe_unit_name(match.group(1))}"

    match = re.fullmatch(r"queued on-success unit (.+)", message)
    if match:
        return f"已排队成功回调单元：{_describe_unit_name(match.group(1))}"

    match = re.fullmatch(r"on-failure unit (.+) failed for (.+)", message)
    if match:
        return f"失败回调单元 {match.group(1)} 在处理 {_describe_unit_name(match.group(2))} 时再次失败"

    match = re.fullmatch(r"on-success unit (.+) failed for (.+)", message)
    if match:
        return f"成功回调单元 {match.group(1)} 在处理 {_describe_unit_name(match.group(2))} 时失败"

    match = re.fullmatch(r"queued successor target (.+)", message)
    if match:
        return f"已排队后继目标：{_describe_target_name(match.group(1))}"

    match = re.fullmatch(r"restarting unit (.+)", message)
    if match:
        return f"准备重启执行单元：{_describe_unit_name(match.group(1))}"

    match = re.fullmatch(r"compressed execution context before step (\d+)", message)
    if match:
        return f"在步骤 {int(match.group(1))} 前完成了执行上下文压缩"

    match = re.fullmatch(r"step (\d+) waiting", message)
    if match:
        return f"步骤 {int(match.group(1))} 进入等待状态"

    match = re.fullmatch(r"executor produced incomplete output for step (\d+)", message)
    if match:
        return f"执行器在步骤 {int(match.group(1))} 产出了不完整结果"

    match = re.fullmatch(r"critic rejected step (\d+) attempt (\d+)", message)
    if match:
        return f"评审器拒绝了步骤 {int(match.group(1))} 的第 {int(match.group(2))} 次尝试"

    match = re.fullmatch(r"verifier rejected step (\d+) attempt (\d+)", message)
    if match:
        return f"验证器拒绝了步骤 {int(match.group(1))} 的第 {int(match.group(2))} 次尝试"

    match = re.fullmatch(r"supervisor recovering task ([a-z0-9]+)", message)
    if match:
        return f"监督器正在恢复任务 {match.group(1)}"

    return _display_summary_text(message)


def _join_or_none(values: list[str], formatter: Callable[[str], str] | None = None) -> str:
    items = [str(value).strip() for value in values if str(value).strip()]
    if not items:
        return "无"
    if formatter is not None:
        items = [formatter(item) for item in items]
    return "、".join(items)


def _wrap_lines(prefix: str, text: str) -> list[str]:
    value = str(text).strip()
    if not value:
        return [prefix.rstrip()]
    first_prefix = prefix
    next_prefix = " " * len(prefix)
    lines: list[str] = []
    for raw_line in value.splitlines():
        wrapped = textwrap.wrap(
            raw_line,
            width=_DISPLAY_WRAP_WIDTH,
            break_long_words=False,
            replace_whitespace=False,
        )
        if not wrapped:
            wrapped = [""]
        for line in wrapped:
            lines.append(f"{first_prefix}{line}".rstrip())
            first_prefix = next_prefix
    return lines


@dataclass(frozen=True)
class ExecutionContext:
    plan: TaskPlan
    task: TaskRecord
    memories: list[MemoryRecord]
    attachment_payloads: list[AttachmentPayload]
    skill_names: list[str] = field(default_factory=list)
    supervisor_notes: list[str] = field(default_factory=list)
    route_decision: dict[str, Any] | None = None
    session: KernelSession | None = None
    planner_process_id: str = ""


@dataclass(frozen=True)
class TaskRunOutcome:
    status: str
    summary: str
    next_step_index: int
    supervisor_reason: str = ""


class TaskAgent:
    def __init__(
        self,
        config: AppConfig,
        executor: GraphAgent,
        planner: TaskPlanner,
        task_store: TaskStore,
        renderer: ConsoleRenderer,
        kernel: AgentKernel | None = None,
    ) -> None:
        self._config = config
        self._executor = executor
        self._planner = planner
        self._task_store = task_store
        self._renderer = renderer
        self._kernel = kernel
        self._skills = SkillCatalog(config.workspace_root / "skills")

    def handle_input(
        self,
        user_input: str,
        image_paths: list[str] | None = None,
        image_urls: list[str] | None = None,
    ) -> str:
        normalized_input, attachment_payloads = self._normalize_request(
            user_input,
            image_paths=image_paths,
            image_urls=image_urls,
        )
        command_result = self._handle_command(user_input)
        if command_result is not None:
            return command_result

        attachment_refs = [
            {
                "kind": payload.ref.kind,
                "source": payload.ref.source,
                "transport": payload.ref.transport,
            }
            for payload in attachment_payloads
        ]
        planning_request = normalized_input
        recent_tasks = self._task_store.list_recent_tasks(
            self._config.storage.recent_task_limit
        )
        reserved_task_id = self._task_store.new_task_id()
        skill_names = self._skills.recommend(
            normalized_input,
            route_decision={},
            attachment_count=len(attachment_payloads),
        )
        planning_request = self._build_planning_request(
            normalized_input,
            attachment_refs=attachment_refs,
            skill_notes=self._skills.render_compact(skill_names),
            route_notes="None",
        )

        session: KernelSession | None = None
        planner_process_id = ""
        route_decision: dict[str, Any] | None = None
        if self._kernel is not None and self._config.agentos.enabled:
            session = self._kernel.create_session(
                task_id=reserved_task_id,
                root_request=normalized_input,
                attachments=attachment_refs,
            )
            planning_target_name = self._service_target_name("planning")
            router_unit_name = self._service_unit_name("router")
            retriever_unit_name = self._service_unit_name("retriever")
            planner_unit_name = self._service_unit_name("planner")
            if self._config.agentos.router_enabled:
                _router_unit, router_process, router_result = session.run_unit(
                    unit_name=router_unit_name,
                    template_name=router_unit_name,
                    payload={
                        "user_request": normalized_input,
                        "attachments": attachment_refs,
                    },
                    priority=PriorityClass.REALTIME.value,
                    dependencies=[],
                    namespace=session.build_namespace(
                        identity="router",
                        tool_allowlist=[],
                        network_access=False,
                    ),
                )
                route_decision = {
                    key: value
                    for key, value in router_result.payload.items()
                    if key != "usage"
                }
                session.emit_event(
                    kind="route.selected",
                    level="info",
                    message=f"router selected {route_decision.get('route', 'task')}",
                    payload=route_decision,
                    process_id=router_process.process_id,
                )
            else:
                route_decision = {}

            skill_names = self._skills.recommend(
                normalized_input,
                route_decision=route_decision or {},
                attachment_count=len(attachment_payloads),
            )
            planning_request = self._build_planning_request(
                normalized_input,
                attachment_refs=attachment_refs,
                skill_notes=self._skills.render_compact(skill_names),
                route_notes=self._format_route_decision(route_decision or {}),
            )

            if route_decision.get("needs_retrieval", True):
                retriever_dependencies = (
                    [router_unit_name] if self._config.agentos.router_enabled else []
                )
                _retriever_unit, _retriever_process, retriever_result = session.run_unit(
                    unit_name=retriever_unit_name,
                    template_name=retriever_unit_name,
                    payload={
                        "query": planning_request,
                        "limit": self._config.storage.memory_search_limit,
                    },
                    priority=PriorityClass.HIGH.value,
                    dependencies=retriever_dependencies,
                    namespace=session.build_namespace(
                        identity="retriever",
                        tool_allowlist=[],
                        network_access=False,
                    ),
                )
                memories = list(retriever_result.payload.get("memories", []))
            else:
                memories = []
            planner_dependencies = []
            if self._config.agentos.router_enabled:
                planner_dependencies.append(router_unit_name)
            if route_decision.get("needs_retrieval", True):
                planner_dependencies.append(retriever_unit_name)
            _planner_unit, planner_process, planner_result = session.run_unit(
                unit_name=planner_unit_name,
                template_name=planner_unit_name,
                payload={
                    "user_request": planning_request,
                    "memories": memories,
                    "recent_tasks": recent_tasks,
                    "route_notes": self._format_route_decision(route_decision or {}),
                },
                priority=PriorityClass.HIGH.value,
                dependencies=planner_dependencies,
                namespace=session.build_namespace(
                    identity="planner",
                    tool_allowlist=[],
                    network_access=False,
                ),
            )
            planner_process_id = planner_process.process_id
            planning_units = [planner_unit_name]
            if self._config.agentos.router_enabled:
                planning_units.insert(0, router_unit_name)
            if route_decision.get("needs_retrieval", True):
                insert_index = 1 if self._config.agentos.router_enabled else 0
                planning_units.insert(insert_index, retriever_unit_name)
            session.activate_target(
                target_name=planning_target_name,
                template_name=planning_target_name,
                wanted_units=planning_units,
                metadata={
                    "phase": "planning",
                    "route": (route_decision or {}).get("route", "task"),
                },
                requested_by_process_id=planner_process.process_id,
            )
            plan = planner_result.payload.get("plan")
            if not isinstance(plan, TaskPlan):
                plan = self._planner.plan(
                    user_request=planning_request,
                    memories=memories,
                    recent_tasks=recent_tasks,
                )
        else:
            memories = self._task_store.search_memories(
                planning_request,
                self._config.storage.memory_search_limit,
            )
            plan = self._planner.plan(
                user_request=planning_request,
                memories=memories,
                recent_tasks=recent_tasks,
            )

        task = self._task_store.create_task(
            title=plan.title,
            goal=plan.goal,
            user_request=normalized_input,
            attachments=attachment_refs,
            steps=[
                {"title": step.title, "description": step.description}
                for step in plan.steps[: self._config.agent.max_execution_steps]
            ],
            task_id=reserved_task_id,
        )
        context = ExecutionContext(
            plan=plan,
            task=task,
            memories=memories,
            attachment_payloads=attachment_payloads,
            route_decision=route_decision,
            session=session,
            planner_process_id=planner_process_id,
            skill_names=skill_names,
        )
        if session is not None:
            session.activate_target(
                target_name=self._service_target_name("task"),
                template_name=self._service_target_name("task"),
                wanted_targets=[self._service_target_name("planning")],
                metadata={"phase": "task_root"},
                requested_by_process_id=planner_process_id,
            )
        return self._run_task(context, start_step_index=1)

    def _normalize_request(
        self,
        user_input: str,
        *,
        image_paths: list[str] | None,
        image_urls: list[str] | None,
    ) -> tuple[str, list[AttachmentPayload]]:
        normalized_input = user_input
        merged_paths = list(image_paths or [])
        merged_urls = list(image_urls or [])

        inline = parse_inline_image_command(user_input)
        if inline is not None:
            normalized_input, inline_paths, inline_urls = inline
            merged_paths.extend(inline_paths)
            merged_urls.extend(inline_urls)

        attachment_payloads = build_attachment_payloads(
            image_paths=merged_paths,
            image_urls=merged_urls,
        )
        return normalized_input, attachment_payloads

    def _handle_command(self, user_input: str) -> str | None:
        stripped = user_input.strip()

        if stripped == "/skills":
            print("Skills>", flush=True)
            print(self._skills.render_available(), flush=True)
            return ""

        if stripped == "/skill":
            print("Skill>", flush=True)
            print(self._skills.render_available(), flush=True)
            return ""

        if stripped.startswith("/skill "):
            skill_name = stripped.split(" ", 1)[1].strip()
            if not skill_name:
                print("Skill> missing skill name", flush=True)
                return ""
            try:
                print(self._skills.preview(skill_name), flush=True)
            except KeyError:
                print(f"Skill> unknown skill: {skill_name}", flush=True)
            return ""

        if stripped.startswith("/skill-files "):
            skill_name = stripped.split(" ", 1)[1].strip()
            if not skill_name:
                print("Skill> missing skill name", flush=True)
                return ""
            try:
                print(self._skills.list_resource_paths(skill_name), flush=True)
            except KeyError:
                print(f"Skill> unknown skill: {skill_name}", flush=True)
            return ""

        if stripped == "/tasks":
            tasks = self._task_store.list_recent_tasks(self._config.storage.recent_task_limit)
            if not tasks:
                print("Task> No persisted tasks yet.", flush=True)
                return ""
            for task in tasks:
                print(
                    f"Task> {task.task_id} | {task.status} | {task.title}",
                    flush=True,
                )
            return ""

        if stripped == "/mounts":
            mounts = (
                self._config.agentos.vfs_mounts
                if self._config.agentos.enabled
                else {"/workspace/repo": str(self._config.workspace_root)}
            )
            for mount_point, target in mounts.items():
                print(f"Mount> {mount_point} -> {target}", flush=True)
            return ""

        if stripped.startswith("/taskfs"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_task_artifacts(task_id)
            return ""

        if stripped.startswith("/units"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_units(task_id)
            return ""

        if stripped.startswith("/targets"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_targets(task_id)
            return ""

        if stripped.startswith("/unitgraph"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_unit_graph(task_id)
            return ""

        if stripped.startswith("/targetgraph"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_target_graph(task_id)
            return ""

        if stripped.startswith("/ps"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_processes(task_id)
            return ""

        if stripped.startswith("/events"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_events(task_id)
            return ""

        if stripped.startswith("/ipc"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_ipc_messages(task_id)
            return ""

        if stripped.startswith("/checkpoints"):
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            self._print_checkpoints(task_id)
            return ""

        if stripped.startswith("/runproc "):
            if self._kernel is None or not self._config.agentos.enabled:
                print("Kernel> runproc is only available when AgentOS is enabled.", flush=True)
                return ""
            process_id = stripped.split(" ", 1)[1].strip()
            result = self._kernel.run_process(process_id)
            print(f"ProcRun> {process_id} | {result.summary}", flush=True)
            return ""

        if stripped.startswith("/restore "):
            if self._kernel is None or not self._config.agentos.enabled:
                print("Kernel> restore is only available when AgentOS is enabled.", flush=True)
                return ""
            target = stripped.split(" ", 1)[1].strip()
            try:
                restored_process, checkpoint, result = self._kernel.restore_checkpoint(
                    checkpoint_id=target,
                    run_immediately=True,
                )
            except KeyError:
                restored_process, checkpoint, result = self._kernel.restore_checkpoint(
                    process_id=target,
                    run_immediately=True,
                )
            summary = result.summary if result is not None else "queued"
            print(
                f"Restore> {checkpoint.checkpoint_id} -> {restored_process.process_id} | {summary}",
                flush=True,
            )
            return ""

        if stripped.startswith("/pump"):
            if self._kernel is None or not self._config.agentos.enabled:
                print("Kernel> pump is only available when AgentOS is enabled.", flush=True)
                return ""
            task_id = self._resolve_command_task_id(stripped)
            if task_id is None:
                return ""
            result = self._kernel.pump_scheduler(task_id=task_id)
            processed = result.get("processed", [])
            print(
                f"Pump> task={task_id} | status={result.get('status', 'drained')} | "
                f"processed={len(processed)} | remaining_ready={result.get('remaining_ready', 0)}",
                flush=True,
            )
            for item in processed:
                print(
                    "PumpProc> "
                    f"{item.get('process_id', '-')} | {item.get('agent_type', '-')} | "
                    f"{item.get('state', '-')} | {item.get('summary', '')}",
                    flush=True,
                )
            return ""

        if stripped.startswith("/resume "):
            task_id = stripped.split(" ", 1)[1].strip()
            context, first_pending = self._build_resume_context(task_id)
            if first_pending > len(context.task.steps):
                print(f"Task> {context.task.task_id} already completed.", flush=True)
                if context.task.final_summary:
                    print(f"TaskDone> {context.task.final_summary}", flush=True)
                return context.task.final_summary
            return self._run_task(context, start_step_index=first_pending)
        return None

    def _resolve_command_task_id(self, command: str) -> str | None:
        parts = command.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()
        tasks = self._task_store.list_recent_tasks(1)
        if not tasks:
            print("Task> No persisted tasks yet.", flush=True)
            return None
        return tasks[0].task_id

    def _print_wrapped(self, prefix: str, text: str) -> None:
        for line in _wrap_lines(prefix, text):
            print(line, flush=True)

    def _task_skill_profile(self, task_id: str) -> dict[str, Any]:
        task = self._task_store.get_task(task_id)
        route_decision = self._latest_route_decision(task_id) or {}
        skill_names = self._skills.recommend(
            task.user_request or task.goal,
            route_decision=route_decision,
            attachment_count=len(task.attachments),
        )
        entries = []
        for skill_name in skill_names:
            entry = self._skills.resolve(skill_name)
            if entry is not None:
                entries.append(entry)

        available_tools = set(self._kernel.base_tools.tool_names) if self._kernel is not None else set()
        route_tools = [
            str(name)
            for name in route_decision.get("suggested_tool_allowlist", [])
            if str(name).strip() and (not available_tools or str(name) in available_tools)
        ]
        skill_guided_tools = []
        if skill_names:
            skill_guided_tools = sorted(
                name
                for name in self._skills.required_tools(skill_names)
                if not available_tools or name in available_tools
            )
        effective_tools = []
        if self._kernel is not None and self._config.agentos.enabled:
            effective_tools = self._resolve_tool_allowlist(
                route_decision,
                skill_names=skill_names,
            )

        effect_points: list[str] = []
        if skill_names:
            effect_points.extend(["规划请求", "步骤执行提示词"])
            if self._kernel is not None and self._config.agentos.enabled:
                effect_points.append("执行器工具白名单")

        if not skill_names:
            effect_note = "当前任务没有匹配到额外 skills，将按基础 AgentOS 行为执行。"
        elif self._kernel is None or not self._config.agentos.enabled:
            effect_note = "已生效：skills 会写入规划请求和执行提示词，但当前未启用 AgentOS 内核工具白名单。"
        elif effective_tools and available_tools and len(effective_tools) < len(available_tools):
            effect_note = (
                f"已生效：skills 会写入规划请求与执行提示词，并把执行器工具收敛到 "
                f"{len(effective_tools)} 个候选工具。"
            )
        else:
            effect_note = "已生效：skills 会写入规划请求与执行提示词，并参与执行器工具白名单计算。"

        return {
            "task": task,
            "route_decision": route_decision,
            "skill_names": skill_names,
            "entries": entries,
            "route_tools": route_tools,
            "skill_guided_tools": skill_guided_tools,
            "effective_tools": effective_tools,
            "effect_points": effect_points,
            "effect_note": effect_note,
        }

    def _print_processes(self, task_id: str) -> None:
        processes: list[TaskProcessRecord] = self._task_store.list_processes(task_id)
        if not processes:
            print(f"进程视图> 任务 {task_id} 暂无进程记录。", flush=True)
            return
        print(f"进程视图> 任务 {task_id} | 共 {len(processes)} 个进程", flush=True)
        for index, process in enumerate(processes, start=1):
            print(
                f"进程[{index}/{len(processes)}]> {_display_agent_type(process.agent_type)} | ID={process.process_id}",
                flush=True,
            )
            print(
                f"  状态: {_display_state(process.state)} | 优先级: {_display_priority(process.priority)}",
                flush=True,
            )
            print(
                f"  父进程: {process.parent_process_id or '无'}",
                flush=True,
            )
            print(
                f"  等待说明: {_display_wait_detail(process)}",
                flush=True,
            )
            if process.last_error:
                self._print_wrapped("  错误: ", _display_summary_text(process.last_error))
            elif process.output_preview:
                self._print_wrapped("  输出预览: ", _display_process_preview(process.output_preview))

    def _print_task_artifacts(self, task_id: str) -> None:
        paths = self._task_store.describe_task_artifacts(task_id)
        counts = self._task_store.count_task_artifacts(task_id)
        profile = self._task_skill_profile(task_id)
        task: TaskRecord = profile["task"]
        route_decision: dict[str, Any] = profile["route_decision"]

        print(f"任务文件系统> {task_id}", flush=True)
        print(f"  标题: {task.title}", flush=True)
        print(f"  状态: {_display_state(task.status)}", flush=True)
        print(f"  路由: {_display_route(route_decision.get('route', 'task'))}", flush=True)
        print("  产物统计:", flush=True)
        for key, value in counts.items():
            print(f"    - {_ARTIFACT_COUNT_LABELS.get(key, key)}: {value}", flush=True)

        print("  技能状态:", flush=True)
        self._print_wrapped("    - 生效判定: ", profile["effect_note"])
        selected_skills = _join_or_none([entry.name for entry in profile["entries"]])
        print(f"    - 已匹配技能: {selected_skills}", flush=True)
        effect_points = _join_or_none(profile["effect_points"])
        print(f"    - 生效位置: {effect_points}", flush=True)
        print(
            f"    - 路由建议工具: {_join_or_none(profile['route_tools'])}",
            flush=True,
        )
        print(
            f"    - 技能导向工具: {_join_or_none(profile['skill_guided_tools'])}",
            flush=True,
        )
        print(
            f"    - 当前执行器有效工具: {_join_or_none(profile['effective_tools'])}",
            flush=True,
        )
        if profile["entries"]:
            print("    - 技能详情:", flush=True)
            for entry in profile["entries"]:
                self._print_wrapped(
                    "      * ",
                    f"{entry.name}: {entry.description or '无描述'} [{entry.resource_summary}]",
                )

        print("  路径概览:", flush=True)
        for label, path in paths.items():
            print(f"    - {_ARTIFACT_PATH_LABELS.get(label, label)}: {path}", flush=True)

    def _print_units(self, task_id: str) -> None:
        units: list[TaskUnitRecord] = self._task_store.list_units(task_id, limit=200)
        if not units:
            print(f"单元视图> 任务 {task_id} 暂无执行单元记录。", flush=True)
            return
        profile = self._task_skill_profile(task_id)
        print(f"单元视图> 任务 {task_id} | 共 {len(units)} 个单元", flush=True)
        self._print_wrapped(
            "  技能说明: ",
            profile["effect_note"],
        )
        print(
            f"  已匹配技能: {_join_or_none([entry.name for entry in profile['entries']])}",
            flush=True,
        )
        for index, unit in enumerate(units, start=1):
            print(
                f"单元[{index}/{len(units)}]> {_describe_unit_name(unit.unit_name)} [{unit.unit_name}]",
                flush=True,
            )
            print(f"  状态: {_display_state(unit.state)}", flush=True)
            print(
                f"  模板: {unit.template_name} | 类型: {_display_agent_type(unit.agent_type)}",
                flush=True,
            )
            print(
                f"  步骤: {unit.step_index or '无'} | 进程ID: {unit.process_id or '无'}",
                flush=True,
            )
            print(
                f"  重启: {unit.restart_attempts}/{unit.max_restart_attempts} | 超时: "
                f"{f'{unit.timeout_seconds}s' if unit.timeout_seconds else '无'}",
                flush=True,
            )
            print(
                f"  依赖: {_join_or_none(unit.dependencies, _describe_unit_name)}",
                flush=True,
            )
            print(
                f"  后置顺序: {_join_or_none(unit.after_units, _describe_unit_name)}",
                flush=True,
            )
            print(
                f"  前置顺序: {_join_or_none(unit.before_units, _describe_unit_name)}",
                flush=True,
            )
            print(
                f"  失败后触发: {_join_or_none(unit.on_failure_units, _describe_unit_name)}",
                flush=True,
            )
            print(
                f"  成功后触发: {_join_or_none(unit.on_success_units, _describe_unit_name)}",
                flush=True,
            )
            self._print_wrapped("  摘要: ", _display_summary_text(unit.summary or "无"))

    def _print_targets(self, task_id: str) -> None:
        targets: list[TaskTargetRecord] = self._task_store.list_targets(task_id, limit=200)
        if not targets:
            print(f"目标视图> 任务 {task_id} 暂无目标记录。", flush=True)
            return
        print(f"目标视图> 任务 {task_id} | 共 {len(targets)} 个目标", flush=True)
        for index, target in enumerate(targets, start=1):
            print(
                f"目标[{index}/{len(targets)}]> {_describe_target_name(target.target_name)} "
                f"[{target.target_name}]",
                flush=True,
            )
            print(f"  状态: {_display_state(target.state)}", flush=True)
            print(f"  模板: {target.template_name}", flush=True)
            print(
                f"  依赖目标: {_join_or_none(target.dependencies, _describe_target_name)}",
                flush=True,
            )
            print(
                f"  期望单元: {_join_or_none(target.wanted_units, _describe_unit_name)}",
                flush=True,
            )
            print(
                f"  期望子目标: {_join_or_none(target.wanted_targets, _describe_target_name)}",
                flush=True,
            )
            print(
                f"  成功后触发: {_join_or_none(target.on_success_targets, _describe_target_name)}",
                flush=True,
            )
            self._print_wrapped("  摘要: ", _display_summary_text(target.summary or "无"))

    def _print_unit_graph(self, task_id: str) -> None:
        paths = self._task_store.describe_task_artifacts(task_id)
        mermaid_path = paths.get("unit_graph_mermaid", "")
        json_path = paths.get("unit_graph_json", "")
        if not mermaid_path:
            print(f"UnitGraph> No unit graph path recorded for task {task_id}.", flush=True)
            return
        graph_file = Path(mermaid_path)
        if not graph_file.exists():
            print(f"UnitGraph> No unit graph generated yet for task {task_id}.", flush=True)
            return
        print(f"UnitGraph> json={json_path}", flush=True)
        print(f"UnitGraph> mermaid={mermaid_path}", flush=True)
        for line in graph_file.read_text(encoding="utf-8").splitlines():
            print(f"UnitGraph> {line}", flush=True)

    def _print_target_graph(self, task_id: str) -> None:
        paths = self._task_store.describe_task_artifacts(task_id)
        mermaid_path = paths.get("target_graph_mermaid", "")
        json_path = paths.get("target_graph_json", "")
        if not mermaid_path:
            print(f"TargetGraph> No target graph path recorded for task {task_id}.", flush=True)
            return
        graph_file = Path(mermaid_path)
        if not graph_file.exists():
            print(f"TargetGraph> No target graph generated yet for task {task_id}.", flush=True)
            return
        print(f"TargetGraph> json={json_path}", flush=True)
        print(f"TargetGraph> mermaid={mermaid_path}", flush=True)
        for line in graph_file.read_text(encoding="utf-8").splitlines():
            print(f"TargetGraph> {line}", flush=True)

    def _print_events(self, task_id: str) -> None:
        events: list[TaskEventRecord] = self._task_store.list_events(task_id, limit=100)
        if not events:
            print(f"事件流> 任务 {task_id} 暂无事件记录。", flush=True)
            return
        processes = {
            process.process_id: process
            for process in self._task_store.list_processes(task_id, limit=300)
        }
        print(f"事件流> 任务 {task_id} | 共 {len(events)} 条事件", flush=True)
        for index, event in enumerate(reversed(events), start=1):
            print(
                f"事件[{index}/{len(events)}]> {event.created_at} | {_display_level(event.level)} | "
                f"{_display_event_kind(event.kind)}",
                flush=True,
            )
            self._print_wrapped("  说明: ", _display_event_message(event))
            if event.process_id:
                process = processes.get(event.process_id)
                process_label = _display_agent_type(process.agent_type) if process is not None else "未知进程"
                print(
                    f"  关联进程: {process_label} | ID={event.process_id}",
                    flush=True,
                )
            if event.parent_process_id:
                print(f"  父进程: {event.parent_process_id}", flush=True)

    def _print_checkpoints(self, task_id: str) -> None:
        checkpoints: list[TaskCheckpointRecord] = self._task_store.list_checkpoints(
            task_id,
            limit=100,
        )
        if not checkpoints:
            print(f"检查点视图> 任务 {task_id} 暂无检查点记录。", flush=True)
            return
        processes = {
            process.process_id: process
            for process in self._task_store.list_processes(task_id, limit=300)
        }
        print(f"检查点视图> 任务 {task_id} | 共 {len(checkpoints)} 个检查点", flush=True)
        for index, checkpoint in enumerate(reversed(checkpoints), start=1):
            process = processes.get(checkpoint.process_id)
            process_label = _display_agent_type(process.agent_type) if process is not None else "未知进程"
            print(
                f"检查点[{index}/{len(checkpoints)}]> {checkpoint.created_at}",
                flush=True,
            )
            print(
                f"  进程: {process_label} | ID={checkpoint.process_id}",
                flush=True,
            )
            print(
                f"  阶段: {_display_phase(checkpoint.phase)}",
                flush=True,
            )
            self._print_wrapped("  摘要: ", _display_summary_text(checkpoint.summary))

    def _print_ipc_messages(self, task_id: str) -> None:
        messages: list[TaskIpcMessageRecord] = self._task_store.list_ipc_messages(
            task_id,
            limit=100,
        )
        if not messages:
            print(f"IPC> No IPC messages recorded for task {task_id}.", flush=True)
            return
        for message in reversed(messages):
            print(
                "IPC> "
                f"{message.created_at} | {message.channel} | "
                f"{message.sender_process_id or '-'} -> {message.recipient_process_id or '-'} | "
                f"{message.status} | {message.message}",
                flush=True,
            )

    def _format_memories(self, memories: list[MemoryRecord]) -> str:
        if not memories:
            return "None"
        return "\n".join([f"- {item.summary}" for item in memories])

    def _build_planning_request(
        self,
        user_input: str,
        *,
        attachment_refs: list[dict[str, str]],
        skill_notes: str = "",
        route_notes: str = "",
    ) -> str:
        sections = [user_input.strip()]
        if attachment_refs:
            sections.append("Attached inputs:\n" + summarize_attachment_refs(attachment_refs))
        if route_notes.strip() and route_notes.strip() != "None":
            sections.append("Route notes:\n" + route_notes.strip())
        if skill_notes.strip() and skill_notes.strip() != "None":
            sections.append("Selected skills:\n" + skill_notes.strip())
        return "\n\n".join(section for section in sections if section)

    def _format_route_decision(self, route_decision: dict[str, Any]) -> str:
        if not route_decision:
            return "None"
        lines = []
        for key in [
            "route",
            "needs_web",
            "needs_files",
            "requires_multimodal",
            "reason",
            "execution_notes",
        ]:
            if key in route_decision:
                lines.append(f"- {key}: {route_decision[key]}")
        allowlist = route_decision.get("suggested_tool_allowlist")
        if allowlist:
            lines.append(f"- suggested_tool_allowlist: {', '.join(allowlist)}")
        return "\n".join(lines) if lines else "None"

    def _service_unit_name(self, stem: str) -> str:
        return f"{stem}.service"

    def _step_unit_name(self, stem: str, *, step_index: int, attempt: int | None = None) -> str:
        suffix = f"step-{step_index}"
        if attempt is not None:
            suffix += f"-attempt-{attempt}"
        return f"{stem}@{suffix}.service"

    def _service_target_name(self, stem: str) -> str:
        return f"{stem}.target"

    def _step_target_name(self, stem: str, *, step_index: int, attempt: int | None = None) -> str:
        suffix = f"step-{step_index}"
        if attempt is not None:
            suffix += f"-attempt-{attempt}"
        return f"{stem}@{suffix}.target"

    def _latest_route_decision(self, task_id: str) -> dict[str, Any] | None:
        for event in self._task_store.list_events(task_id, limit=200):
            if event.kind != "route.selected":
                continue
            if isinstance(event.payload, dict):
                return dict(event.payload)
        return None

    def _latest_planner_process_id(self, task_id: str) -> str:
        planner_unit = self._task_store.find_unit(task_id, "planner.service")
        if planner_unit is not None and planner_unit.process_id:
            return planner_unit.process_id
        for process in reversed(self._task_store.list_processes(task_id, limit=200)):
            if process.agent_type == "planner":
                return process.process_id
        return ""

    def _build_resume_context(
        self,
        task_id: str,
        *,
        supervisor_notes: list[str] | None = None,
    ) -> tuple[ExecutionContext, int]:
        task = self._task_store.get_task(task_id)
        memories = self._task_store.search_memories(
            task.goal,
            self._config.storage.memory_search_limit,
        )
        attachment_payloads = build_attachment_payloads_from_refs(task.attachments)
        plan = TaskPlan(
            title=task.title,
            goal=task.goal,
            steps=[
                PlannedStep(title=step.title, description=step.description)
                for step in task.steps
            ],
            memory_summary=task.final_summary,
            raw_plan="",
        )
        first_pending = next(
            (step.step_index for step in task.steps if step.status != "completed"),
            len(task.steps) + 1,
        )
        route_decision = self._latest_route_decision(task.task_id)
        planner_process_id = self._latest_planner_process_id(task.task_id)
        session = None
        if self._kernel is not None and self._config.agentos.enabled:
            session = self._kernel.create_session(
                task_id=task.task_id,
                root_request=task.user_request,
                attachments=task.attachments,
            )
        skill_names = self._skills.recommend(
            task.user_request or task.goal,
            route_decision=route_decision or {},
            attachment_count=len(task.attachments),
        )
        context = ExecutionContext(
            plan=plan,
            task=task,
            memories=memories,
            attachment_payloads=attachment_payloads,
            session=session,
            skill_names=skill_names,
            supervisor_notes=list(supervisor_notes or []),
            route_decision=route_decision,
            planner_process_id=planner_process_id,
        )
        return context, first_pending

    def _executor_output_issue(
        self,
        *,
        payload: dict[str, Any],
        final_result: str,
    ) -> str:
        finish_reason = str(payload.get("executor_finish_reason", "")).strip().lower()
        if finish_reason == "length":
            return "the model hit finish_reason=length before completing the step"

        if bool(payload.get("raw_tool_markup_detected")):
            if bool(payload.get("max_tool_rounds_reached")):
                return (
                    "the executor reached the tool-round ceiling "
                    f"({self._config.agent.max_tool_rounds}) and emitted raw tool markup"
                )
            return "the executor emitted raw tool markup instead of a natural-language result"

        if final_result.strip().startswith("<tool_call"):
            return "the executor returned a raw tool call block instead of a finished result"

        return ""

    def _summarize_pump_result(self, result: dict[str, Any]) -> str:
        processed = list(result.get("processed", []))
        if not processed:
            return "no READY processes were drained"
        parts = [
            (
                f"{item.get('agent_type', '-')}"
                f":{item.get('state', '-')}"
            )
            for item in processed[:6]
        ]
        if len(processed) > 6:
            parts.append(f"... (+{len(processed) - 6} more)")
        return ", ".join(parts)

    def _supervise_agentos_task(
        self,
        context: ExecutionContext,
        outcome: TaskRunOutcome,
        *,
        supervisor_cycle: int,
        supervisor_notes: list[str],
    ) -> tuple[ExecutionContext, int, list[str]]:
        if context.session is None or self._kernel is None:
            raise RuntimeError(
                f"AgentOS supervisor cannot continue task {context.task.task_id} without a kernel session"
            )
        if not self._config.agentos.supervisor_enabled:
            raise RuntimeError(
                f"Task {context.task.task_id} requires supervisor recovery but agentos.supervisor_enabled is false"
            )
        if supervisor_cycle > self._config.agentos.supervisor_max_cycles:
            raise RuntimeError(
                f"Task supervisor exceeded {self._config.agentos.supervisor_max_cycles} recovery cycles "
                f"while handling step {outcome.next_step_index}: {outcome.supervisor_reason or outcome.summary}"
            )

        pump_result = self._kernel.pump_scheduler(
            task_id=context.task.task_id,
            limit=self._config.agentos.supervisor_pump_limit,
        )
        pump_summary = self._summarize_pump_result(pump_result)
        note = (
            f"Supervisor cycle {supervisor_cycle}: {outcome.status} at step {outcome.next_step_index}. "
            f"Reason: {outcome.supervisor_reason or outcome.summary}. "
            f"Scheduler drain: {pump_summary}."
        )
        self._renderer.on_kernel_event(note)
        context.session.emit_event(
            kind="task.supervisor.recover",
            level="warning",
            message=f"supervisor recovering task {context.task.task_id}",
            payload={
                "cycle": supervisor_cycle,
                "outcome_status": outcome.status,
                "step_index": outcome.next_step_index,
                "reason": outcome.supervisor_reason or outcome.summary,
                "pump_result": pump_result,
            },
            parent_process_id=context.planner_process_id,
        )

        updated_notes = [*supervisor_notes, note]
        rebuilt_context, first_pending = self._build_resume_context(
            context.task.task_id,
            supervisor_notes=updated_notes[-8:],
        )
        if first_pending > len(rebuilt_context.plan.steps):
            if rebuilt_context.task.final_summary:
                return rebuilt_context, first_pending, updated_notes[-8:]
            raise RuntimeError(
                f"Task {context.task.task_id} has no pending steps after supervisor recovery, "
                "but it did not produce a final summary."
            )
        return rebuilt_context, first_pending, updated_notes[-8:]

    def _format_step_results(self, steps: list[tuple[int, str, str]]) -> str:
        if not steps:
            return "None"
        return "\n".join(
            [f"- Step {index} {title}: {result}" for index, title, result in steps]
        )

    def _should_compress_context(
        self,
        *,
        prior_results: list[tuple[int, str, str]],
        context_summary: str,
    ) -> bool:
        if not self._config.agentos.compressor_enabled:
            return False
        serialized = context_summary + "\n" + self._format_step_results(prior_results)
        return len(serialized) >= self._config.agentos.compressor_trigger_chars

    def _resolve_tool_allowlist(
        self,
        route_decision: dict[str, Any] | None,
        *,
        skill_names: list[str] | None = None,
    ) -> list[str]:
        if self._kernel is None:
            return []
        route_allowlist = []
        if route_decision:
            route_allowlist = [
                str(name)
                for name in route_decision.get("suggested_tool_allowlist", [])
                if str(name) in self._kernel.base_tools.tool_names
            ]
        skill_allowlist = set()
        if skill_names:
            skill_allowlist = self._skills.required_tools(skill_names)
        if route_allowlist:
            merged = sorted(
                {
                    name
                    for name in (*route_allowlist, *sorted(skill_allowlist))
                    if name in self._kernel.base_tools.tool_names
                }
            )
            return merged or route_allowlist
        if skill_allowlist:
            return sorted(
                {
                    name
                    for name in skill_allowlist
                    if name in self._kernel.base_tools.tool_names
                }
            )
        return sorted(self._kernel.base_tools.tool_names)

    def _build_step_messages(
        self,
        *,
        context: ExecutionContext,
        current_step: PlannedStep,
        current_step_index: int,
        prior_results: list[tuple[int, str, str]],
        context_summary: str = "",
    ) -> list[dict[str, Any]]:
        total_steps = len(context.plan.steps)
        plan_lines = [
            f"{index}. {step.title} - {step.description}"
            for index, step in enumerate(context.plan.steps, start=1)
        ]
        task_prompt = (
            f"Task ID: {context.task.task_id}\n"
            f"Task title: {context.plan.title}\n"
            f"Task goal: {context.plan.goal}\n\n"
            f"Plan:\n" + "\n".join(plan_lines) + "\n\n"
            f"Relevant long-term memories:\n{self._format_memories(context.memories)}\n\n"
            f"Route decision:\n{self._format_route_decision(context.route_decision or {})}\n\n"
            f"Selected skills:\n{self._skills.render_compact(context.skill_names)}\n\n"
            f"Supervisor notes:\n"
            + ("\n".join(f"- {note}" for note in context.supervisor_notes) if context.supervisor_notes else "None")
            + "\n\n"
            f"Compressed execution context:\n{context_summary or 'None'}\n\n"
            f"Completed step results:\n{self._format_step_results(prior_results)}\n\n"
            f"Attached inputs:\n{summarize_attachment_refs(context.task.attachments)}\n\n"
            f"Current step ({current_step_index}/{total_steps}): {current_step.title}\n"
            f"Current step description: {current_step.description}\n\n"
            "Instructions:\n"
            "- Focus on completing the current step.\n"
            "- If images are attached, inspect them before answering.\n"
            "- Use selected skills as a light workflow guide and open the full skill doc only when needed.\n"
            "- Use tools when they help.\n"
            "- Never emit literal <tool_call> blocks in the final answer. Use the runtime tool interface instead.\n"
            "- For mathematical formulas or expressions, use plain text or Unicode symbols, never LaTeX.\n"
            "- If you modify files, explicitly mention the paths and what changed.\n"
            "- End with a concise step result for the current step."
        )

        user_content: str | list[dict[str, Any]]
        if context.attachment_payloads:
            user_content = [{"type": "text", "text": task_prompt}]
            user_content.extend(
                payload.content_part for payload in context.attachment_payloads
            )
        else:
            user_content = task_prompt

        return [
            {
                "role": "system",
                "content": self._config.agent.system_prompt,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]

    def _summarize_task(
        self,
        *,
        context: ExecutionContext,
        completed_steps: list[tuple[int, str, str]],
    ) -> str:
        if not completed_steps:
            return context.plan.goal

        if len(completed_steps) == 1:
            single_result = completed_steps[0][2].strip()
            return single_result or context.plan.goal

        def clip_block(text: str, *, limit: int) -> str:
            value = text.strip()
            if len(value) <= limit:
                return value
            clipped = value[:limit].rstrip()
            cut_index = max(
                clipped.rfind("\n\n"),
                clipped.rfind("\n"),
                clipped.rfind("。"),
                clipped.rfind("！"),
                clipped.rfind("？"),
                clipped.rfind(". "),
            )
            if cut_index >= limit // 2:
                clipped = clipped[: cut_index + 1].rstrip()
            return clipped + "\n\n[内容较长，已截断]"

        blocks: list[str] = []
        remaining = 12000
        for index, title, result in completed_steps:
            if remaining <= 200:
                break
            body_budget = min(2000, max(400, remaining - 120))
            body = clip_block(result, limit=body_budget)
            block = f"步骤 {index}：{title}\n{body or '无结果'}"
            blocks.append(block)
            remaining -= len(block) + 2

        combined = "\n\n".join(blocks).strip()
        return combined or context.plan.goal

    def _executor_tool_allowlist(self) -> list[str]:
        if self._kernel is None:
            return []
        return sorted(self._kernel.base_tools.tool_names)

    def _run_task(self, context: ExecutionContext, start_step_index: int) -> str:
        self._task_store.set_task_status(
            task_id=context.task.task_id,
            status="in_progress",
            final_summary=context.task.final_summary,
        )
        try:
            if context.session is not None and self._config.agentos.enabled:
                current_context = context
                current_step_index = start_step_index
                supervisor_notes = list(context.supervisor_notes)
                supervisor_cycles = 0
                announce_task = True
                while True:
                    outcome = self._run_task_agentos(
                        current_context,
                        current_step_index,
                        announce_task=announce_task,
                    )
                    announce_task = False
                    if outcome.status == "completed":
                        return outcome.summary
                    supervisor_cycles += 1
                    current_context, current_step_index, supervisor_notes = (
                        self._supervise_agentos_task(
                            current_context,
                            outcome,
                            supervisor_cycle=supervisor_cycles,
                            supervisor_notes=supervisor_notes,
                        )
                    )
                    if (
                        current_step_index > len(current_context.plan.steps)
                        and current_context.task.final_summary
                    ):
                        self._renderer.on_task_complete(
                            current_context.task.task_id,
                            current_context.task.final_summary,
                        )
                        return current_context.task.final_summary
            outcome = self._run_task_legacy(context, start_step_index, announce_task=True)
            return outcome.summary
        except Exception as exc:
            self._task_store.set_task_status(
                task_id=context.task.task_id,
                status="failed",
                final_summary=str(exc),
            )
            raise

    def _run_task_legacy(
        self,
        context: ExecutionContext,
        start_step_index: int,
        *,
        announce_task: bool = True,
    ) -> TaskRunOutcome:
        planned_steps = context.plan.steps[: self._config.agent.max_execution_steps]
        if announce_task:
            self._renderer.on_task_created(
                context.task.task_id,
                context.plan.title,
                [step.title for step in planned_steps],
            )

        completed_steps: list[tuple[int, str, str]] = [
            (step.step_index, step.title, step.result)
            for step in context.task.steps
            if step.status == "completed" and step.result
        ]

        for step_index in range(start_step_index, len(planned_steps) + 1):
            step = planned_steps[step_index - 1]
            self._task_store.update_step_status(
                task_id=context.task.task_id,
                step_index=step_index,
                status="in_progress",
                result="",
            )
            self._renderer.on_step_start(
                context.task.task_id,
                step_index,
                len(planned_steps),
                step.title,
            )
            messages = self._build_step_messages(
                context=context,
                current_step=step,
                current_step_index=step_index,
                prior_results=completed_steps,
            )
            result, _summary = self._executor.run_messages(messages)
            self._task_store.update_step_status(
                task_id=context.task.task_id,
                step_index=step_index,
                status="completed",
                result=result,
            )
            completed_steps.append((step_index, step.title, result))

        final_summary = self._summarize_task(
            context=context,
            completed_steps=completed_steps,
        )
        self._task_store.set_task_status(
            task_id=context.task.task_id,
            status="completed",
            final_summary=final_summary,
        )
        self._task_store.create_memory(
            kind="task",
            summary=context.plan.memory_summary or context.plan.title,
            content=final_summary,
            tags=[context.plan.title] + [step.title for step in planned_steps],
            source_task_id=context.task.task_id,
        )
        self._renderer.on_task_complete(context.task.task_id, final_summary)
        return TaskRunOutcome(
            status="completed",
            summary=final_summary,
            next_step_index=len(planned_steps) + 1,
        )

    def _run_task_agentos(
        self,
        context: ExecutionContext,
        start_step_index: int,
        *,
        announce_task: bool = True,
    ) -> TaskRunOutcome:
        assert context.session is not None
        planned_steps = context.plan.steps[: self._config.agent.max_execution_steps]
        if announce_task:
            self._renderer.on_task_created(
                context.task.task_id,
                context.plan.title,
                [step.title for step in planned_steps],
            )

        completed_steps: list[tuple[int, str, str]] = [
            (step.step_index, step.title, step.result)
            for step in context.task.steps
            if step.status == "completed" and step.result
        ]
        compressed_context = str(
            (context.route_decision or {}).get("execution_notes", "")
        ).strip()
        route_tool_allowlist = self._resolve_tool_allowlist(
            context.route_decision,
            skill_names=context.skill_names,
        )
        planner_unit_name = self._service_unit_name("planner")
        planning_target_name = self._service_target_name("planning")
        completion_target_name = self._service_target_name("completion")
        task_target_name = self._service_target_name("task")
        step_target_names: list[str] = []

        for step_index in range(start_step_index, len(planned_steps) + 1):
            step = planned_steps[step_index - 1]
            self._task_store.update_step_status(
                task_id=context.task.task_id,
                step_index=step_index,
                status="in_progress",
                result="",
            )
            self._renderer.on_step_start(
                context.task.task_id,
                step_index,
                len(planned_steps),
                step.title,
            )

            if self._should_compress_context(
                prior_results=completed_steps,
                context_summary=compressed_context,
            ):
                compressor_process, compressor_result = context.session.run(
                    agent_type="compressor",
                    payload={
                        "task_goal": context.plan.goal,
                        "route_notes": self._format_route_decision(
                            context.route_decision or {}
                        ),
                        "completed_steps": self._format_step_results(completed_steps),
                        "memories": self._format_memories(context.memories),
                        "existing_summary": compressed_context,
                    },
                    priority=PriorityClass.BACKGROUND.value,
                    parent_process_id=context.planner_process_id,
                    namespace=context.session.build_namespace(
                        identity="compressor",
                        tool_allowlist=[],
                        network_access=False,
                    ),
                )
                compressed_context = str(
                    compressor_result.payload.get("compressed_context", "")
                ).strip()
                context.session.emit_event(
                    kind="context.compressed",
                    level="info",
                    message=f"compressed execution context before step {step_index}",
                    payload={
                        "summary_preview": compressed_context[:200],
                    },
                    process_id=compressor_process.process_id,
                    parent_process_id=context.planner_process_id,
                )

            base_messages = self._build_step_messages(
                context=context,
                current_step=step,
                current_step_index=step_index,
                prior_results=completed_steps,
                context_summary=compressed_context,
            )
            max_attempts = 1 + max(0, self._config.agentos.default_retry_budget)
            final_result = ""
            critic_feedback = ""
            verifier_feedback = ""
            for attempt in range(1, max_attempts + 1):
                step_target_name = self._step_target_name(
                    "step",
                    step_index=step_index,
                    attempt=attempt,
                )
                if step_target_name not in step_target_names:
                    step_target_names.append(step_target_name)
                executor_unit_name = self._step_unit_name(
                    "executor",
                    step_index=step_index,
                    attempt=attempt,
                )
                attempt_messages = list(base_messages)
                if critic_feedback:
                    attempt_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Adversarial critic feedback for the same step:\n"
                                f"{critic_feedback}\n\n"
                                "Revise the step result and make it more concrete and grounded."
                            ),
                        }
                    )
                if verifier_feedback:
                    attempt_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Verifier feedback for the same step:\n"
                                f"{verifier_feedback}\n\n"
                                "Revise the step result. Keep it grounded in tool evidence."
                            ),
                        }
                    )

                context.session.activate_target(
                    target_name=step_target_name,
                    template_name=self._service_target_name("step"),
                    dependencies=[planning_target_name],
                    wanted_units=[executor_unit_name],
                    unit_specs=[
                        UnitRunSpec(
                            unit_name=executor_unit_name,
                            template_name=self._service_unit_name("executor"),
                            payload={
                                "messages": attempt_messages,
                                "step_index": step_index,
                                "step_title": step.title,
                            },
                            priority=PriorityClass.NORMAL.value,
                            parent_process_id=context.planner_process_id,
                            parent_unit_name=planner_unit_name,
                            dependencies=[planner_unit_name],
                            step_index=step_index,
                            metadata={
                                "step_title": step.title,
                                "attempt": attempt,
                            },
                            namespace=context.session.build_namespace(
                                identity="executor",
                                tool_allowlist=route_tool_allowlist,
                                network_access=bool(
                                    (context.route_decision or {}).get("needs_web", True)
                                ),
                            ),
                            quota=context.session.build_quota(
                                retry_budget=self._config.agentos.default_retry_budget
                            ),
                        )
                    ],
                    metadata={
                        "step_index": step_index,
                        "step_title": step.title,
                        "attempt": attempt,
                    },
                    requested_by_process_id=context.planner_process_id,
                )
                context.session.activate_target(
                    target_name=task_target_name,
                    template_name=task_target_name,
                    wanted_targets=[planning_target_name, *step_target_names],
                    metadata={"phase": "task_root"},
                    requested_by_process_id=context.planner_process_id,
                )
                executor_unit = context.session.get_unit(executor_unit_name)
                executor_result = context.session.result_for_unit(executor_unit_name)
                if executor_result is None:
                    executor_result = ProcessResult(payload={}, summary=executor_unit.summary)
                final_result = str(executor_result.payload.get("content", "")).strip()
                if executor_unit.state != "completed":
                    wait_summary = str(executor_result.summary or final_result).strip()
                    wait_summary = wait_summary or "executor waiting for child process or IPC"
                    self._task_store.update_step_status(
                        task_id=context.task.task_id,
                        step_index=step_index,
                        status="waiting",
                        result=wait_summary,
                    )
                    self._task_store.set_task_status(
                        task_id=context.task.task_id,
                        status="waiting",
                        final_summary="",
                    )
                    context.session.emit_event(
                        kind="step.waiting",
                        level="info",
                        message=f"step {step_index} waiting",
                        payload={
                            "step_index": step_index,
                            "wait_summary": wait_summary,
                            "executor_process_id": executor_unit.process_id,
                            "executor_state": executor_unit.state,
                        },
                        process_id=executor_unit.process_id,
                        parent_process_id=context.planner_process_id,
                    )
                    self._renderer.on_kernel_event(
                        f"step {step_index} waiting: {wait_summary}"
                    )
                    return TaskRunOutcome(
                        status="waiting",
                        summary=wait_summary,
                        next_step_index=step_index,
                        supervisor_reason=wait_summary,
                    )

                incomplete_reason = self._executor_output_issue(
                    payload=executor_result.payload,
                    final_result=final_result,
                )
                if incomplete_reason:
                    context.session.emit_event(
                        kind="executor.incomplete_output",
                        level="warning",
                        message=f"executor produced incomplete output for step {step_index}",
                        payload={
                            "step_index": step_index,
                            "reason": incomplete_reason,
                            "finish_reason": executor_result.payload.get(
                                "executor_finish_reason",
                                "",
                            ),
                            "tool_rounds_used": executor_result.payload.get(
                                "tool_rounds_used",
                                0,
                            ),
                            "max_tool_rounds_reached": executor_result.payload.get(
                                "max_tool_rounds_reached",
                                False,
                            ),
                        },
                        process_id=executor_unit.process_id,
                        parent_process_id=context.planner_process_id,
                    )
                    if attempt < max_attempts:
                        verifier_feedback = (
                            "Previous executor attempt ended prematurely. "
                            f"Reason: {incomplete_reason}. "
                            "Resume from the current workspace state, finish any pending work, "
                            "and end with a concise natural-language step result. "
                            "Do not repeat successful writes, and do not emit raw <tool_call> markup."
                        )
                        critic_feedback = ""
                        self._renderer.on_kernel_event(
                            f"retrying step {step_index} after incomplete executor output: {incomplete_reason}"
                        )
                        continue
                    return TaskRunOutcome(
                        status="retry",
                        summary=incomplete_reason,
                        next_step_index=step_index,
                        supervisor_reason=incomplete_reason,
                    )

                critic_result = ProcessResult(payload={}, summary="")
                critic_unit_name = self._step_unit_name(
                    "critic",
                    step_index=step_index,
                    attempt=attempt,
                )
                verifier_unit_name = self._step_unit_name(
                    "verifier",
                    step_index=step_index,
                    attempt=attempt,
                )
                review_specs: list[UnitRunSpec] = []
                if self._config.agentos.critic_enabled:
                    review_specs.append(
                        UnitRunSpec(
                            unit_name=critic_unit_name,
                            template_name=self._service_unit_name("critic"),
                            payload={
                                "task_goal": context.plan.goal,
                                "step_title": step.title,
                                "step_description": step.description,
                                "tool_transcript": str(
                                    executor_result.payload.get("tool_transcript", "")
                                ),
                                "candidate_output": final_result,
                                "prior_results": self._format_step_results(completed_steps),
                            },
                            priority=PriorityClass.HIGH.value,
                            parent_process_id=executor_unit.process_id,
                            parent_unit_name=executor_unit_name,
                            dependencies=[executor_unit_name],
                            step_index=step_index,
                            metadata={
                                "step_title": step.title,
                                "attempt": attempt,
                            },
                            namespace=context.session.build_namespace(
                                identity="critic",
                                tool_allowlist=[],
                                network_access=False,
                            ),
                        )
                    )
                if self._config.agentos.verifier_enabled:
                    review_specs.append(
                        UnitRunSpec(
                            unit_name=verifier_unit_name,
                            template_name=self._service_unit_name("verifier"),
                            payload={
                                "step_title": step.title,
                                "step_description": step.description,
                                "candidate_output": final_result,
                                "prior_results": self._format_step_results(completed_steps),
                            },
                            priority=PriorityClass.HIGH.value,
                            parent_process_id=executor_unit.process_id,
                            parent_unit_name=executor_unit_name,
                            dependencies=[executor_unit_name],
                            step_index=step_index,
                            metadata={
                                "step_title": step.title,
                                "attempt": attempt,
                            },
                            namespace=context.session.build_namespace(
                                identity="verifier",
                                tool_allowlist=[],
                                network_access=False,
                            ),
                        )
                    )
                if review_specs:
                    context.session.activate_target(
                        target_name=step_target_name,
                        template_name=self._service_target_name("step"),
                        dependencies=[planning_target_name],
                        wanted_units=[executor_unit_name, *[spec.unit_name for spec in review_specs]],
                        unit_specs=review_specs,
                        metadata={
                            "step_index": step_index,
                            "step_title": step.title,
                            "attempt": attempt,
                        },
                        requested_by_process_id=executor_unit.process_id,
                    )

                if self._config.agentos.critic_enabled:
                    critic_result = (
                        context.session.result_for_unit(critic_unit_name)
                        or ProcessResult(payload={}, summary="")
                    )
                    critic_unit = context.session.find_unit(critic_unit_name)
                    if critic_unit is not None and critic_unit.state != "completed":
                        wait_summary = str(critic_result.summary or critic_unit.summary).strip()
                        wait_summary = wait_summary or "critic waiting for dependencies"
                        self._task_store.update_step_status(
                            task_id=context.task.task_id,
                            step_index=step_index,
                            status="waiting",
                            result=wait_summary,
                        )
                        self._task_store.set_task_status(
                            task_id=context.task.task_id,
                            status="waiting",
                            final_summary="",
                        )
                        return TaskRunOutcome(
                            status="waiting",
                            summary=wait_summary,
                            next_step_index=step_index,
                            supervisor_reason=wait_summary,
                        )
                    critic_approved = bool(critic_result.payload.get("approved", True))
                    critic_feedback = str(
                        critic_result.payload.get("revision_request")
                        or critic_result.payload.get("summary", "")
                    ).strip()
                    if not critic_approved:
                        context.session.emit_event(
                            kind="critic.reject",
                            level="warning",
                            message=f"critic rejected step {step_index} attempt {attempt}",
                            payload={
                                "risk_score": critic_result.payload.get("risk_score", 0.0),
                                "failure_modes": critic_result.payload.get(
                                    "failure_modes",
                                    [],
                                ),
                                "feedback": critic_feedback,
                            },
                            process_id=critic_unit.process_id if critic_unit is not None else "",
                            parent_process_id=executor_unit.process_id,
                        )
                        if attempt < max_attempts:
                            self._renderer.on_kernel_event(
                                f"critic requested retry for step {step_index}: {critic_feedback or 'needs stronger grounding'}"
                            )
                            verifier_feedback = ""
                            continue
                        if critic_feedback:
                            final_result = f"{final_result}\n\n[Critic note]\n{critic_feedback}"

                if not self._config.agentos.verifier_enabled:
                    break

                verifier_result = (
                    context.session.result_for_unit(verifier_unit_name)
                    or ProcessResult(payload={}, summary="")
                )
                verifier_unit = context.session.find_unit(verifier_unit_name)
                if verifier_unit is not None and verifier_unit.state != "completed":
                    wait_summary = str(verifier_result.summary or verifier_unit.summary).strip()
                    wait_summary = wait_summary or "verifier waiting for dependencies"
                    self._task_store.update_step_status(
                        task_id=context.task.task_id,
                        step_index=step_index,
                        status="waiting",
                        result=wait_summary,
                    )
                    self._task_store.set_task_status(
                        task_id=context.task.task_id,
                        status="waiting",
                        final_summary="",
                    )
                    return TaskRunOutcome(
                        status="waiting",
                        summary=wait_summary,
                        next_step_index=step_index,
                        supervisor_reason=wait_summary,
                    )
                approved = bool(verifier_result.payload.get("approved", True))
                verifier_feedback = str(
                    verifier_result.payload.get("revision_request")
                    or verifier_result.payload.get("summary", "")
                ).strip()
                if approved:
                    break
                if attempt < max_attempts:
                    context.session.emit_event(
                        kind="verifier.reject",
                        level="warning",
                        message=f"verifier rejected step {step_index} attempt {attempt}",
                        payload={"feedback": verifier_feedback},
                        parent_process_id=executor_unit.process_id,
                    )
                    self._renderer.on_kernel_event(
                        f"verifier requested retry for step {step_index}: {verifier_feedback or 'needs revision'}"
                    )
                elif verifier_feedback:
                    final_result = (
                        f"{final_result}\n\n[Verifier note]\n{verifier_feedback}"
                    )

            self._task_store.update_step_status(
                task_id=context.task.task_id,
                step_index=step_index,
                status="completed",
                result=final_result,
            )
            completed_steps.append((step_index, step.title, final_result))

        final_summary = self._summarize_task(
            context=context,
            completed_steps=completed_steps,
        )
        self._task_store.set_task_status(
            task_id=context.task.task_id,
            status="completed",
            final_summary=final_summary,
        )
        archivist_unit_name = self._service_unit_name("archivist")
        context.session.activate_target(
            target_name=completion_target_name,
            template_name=completion_target_name,
            dependencies=[planning_target_name, *step_target_names],
            wanted_units=[archivist_unit_name],
            unit_specs=[
                UnitRunSpec(
                    unit_name=archivist_unit_name,
                    template_name=self._service_unit_name("archivist"),
                    payload={
                        "kind": "task",
                        "summary": context.plan.memory_summary or context.plan.title,
                        "content": final_summary,
                        "tags": [context.plan.title, "agentos"] + [step.title for step in planned_steps],
                        "source_task_id": context.task.task_id,
                    },
                    priority=PriorityClass.BACKGROUND.value,
                    parent_process_id=context.planner_process_id,
                    parent_unit_name=planner_unit_name,
                    dependencies=[planner_unit_name],
                    namespace=context.session.build_namespace(
                        identity="archivist",
                        tool_allowlist=[],
                        network_access=False,
                    ),
                )
            ],
            metadata={"phase": "completion"},
            requested_by_process_id=context.planner_process_id,
        )
        context.session.activate_target(
            target_name=task_target_name,
            template_name=task_target_name,
            wanted_targets=[planning_target_name, *step_target_names, completion_target_name],
            metadata={"phase": "task_root"},
            requested_by_process_id=context.planner_process_id,
        )
        self._renderer.on_task_complete(context.task.task_id, final_summary)
        return TaskRunOutcome(
            status="completed",
            summary=final_summary,
            next_step_index=len(planned_steps) + 1,
        )
