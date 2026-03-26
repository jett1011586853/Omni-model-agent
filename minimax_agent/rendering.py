from __future__ import annotations

import re
import sys
import textwrap
from dataclasses import dataclass
from typing import Literal

from .config import StreamingConfig


Section = Literal["reasoning", "answer", "tool", "stats", None]

_WRAP_WIDTH = 96

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

_CHECKPOINT_PHASE_LABELS = {
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


def _safe_text(value: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(value).encode(encoding, errors="replace").decode(encoding, errors="replace")


def _emit(value: str = "", *, end: str = "\n", flush: bool = True) -> None:
    print(_safe_text(value), end=end, flush=flush)


def _translate_agent_type(agent_type: str) -> str:
    value = str(agent_type).strip()
    return _AGENT_TYPE_LABELS.get(value, value or "智能体")


def _translate_priority(priority: str) -> str:
    value = str(priority).strip()
    return _PRIORITY_LABELS.get(value, value or "未知")


def _translate_state(state: str) -> str:
    value = str(state).strip()
    return _STATE_LABELS.get(value, value or "未知")


def _translate_phase(phase: str) -> str:
    value = str(phase).strip()
    return _CHECKPOINT_PHASE_LABELS.get(value, value or "阶段")


def _translate_bool(value: str) -> str:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return "是"
    if text in {"false", "0", "no"}:
        return "否"
    return str(value).strip()


def _translate_route(route: str) -> str:
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


def _format_unit_name(unit_name: str) -> str:
    raw = str(unit_name).strip()
    if not raw:
        return "未命名单元"
    base = raw.removesuffix(".service")
    role, _, instance = base.partition("@")
    role_label = _translate_agent_type(role)
    suffix = _describe_runtime_suffix(instance)
    if suffix:
        return f"{role_label}（{suffix}） [{raw}]"
    return f"{role_label} [{raw}]"


def _format_target_name(target_name: str) -> str:
    raw = str(target_name).strip()
    if not raw:
        return "未命名目标"
    base = raw.removesuffix(".target")
    role, _, instance = base.partition("@")
    role_label = _TARGET_LABELS.get(role, f"{role} 目标")
    suffix = _describe_runtime_suffix(instance)
    if suffix:
        return f"{role_label}（{suffix}） [{raw}]"
    return f"{role_label} [{raw}]"


def _translate_detail(detail: str) -> str:
    text = str(detail).strip()
    if not text:
        return ""

    match = re.fullmatch(
        r"Remote model stream failed: (Server|Client) error '([^']+)' for url '([^']+)'(?:\s+For more information check:\s+.+)?",
        text,
    )
    if match:
        return f"远程模型流式调用失败：模型网关返回 {match.group(2)}（{match.group(3)}）"

    match = re.fullmatch(r"Spawned ([a-z_]+)", text)
    if match:
        return f"已创建{_translate_agent_type(match.group(1))}进程"

    match = re.fullmatch(r"Starting ([a-z_]+)", text)
    if match:
        return f"开始执行{_translate_agent_type(match.group(1))}"

    match = re.fullmatch(r"Planned (\d+) step\(s\) for '(.+)'", text)
    if match:
        return f"已为“{match.group(2)}”生成 {int(match.group(1))} 个执行步骤"

    match = re.fullmatch(r"Route=([^|]+)\s+\|\s+web=(True|False)\s+\|\s+files=(True|False)", text)
    if match:
        return (
            f"路由结果：{_translate_route(match.group(1).strip())}；"
            f"联网：{_translate_bool(match.group(2))}；"
            f"文件访问：{_translate_bool(match.group(3))}"
        )

    match = re.fullmatch(r"dependency ([a-z0-9]+) resolved", text)
    if match:
        return f"依赖进程 {match.group(1)} 已满足"

    match = re.fullmatch(r"ipc ([a-z0-9]+) delivered on (.+)", text)
    if match:
        return f"IPC 消息 {match.group(1)} 已送达（通道：{match.group(2)}）"

    match = re.fullmatch(r"([a-z_]+) waiting for dependencies", text)
    if match:
        return f"{_translate_agent_type(match.group(1))}正在等待依赖完成"

    return text


def _translate_kernel_message(message: str) -> str:
    text = str(message).strip()
    if not text:
        return ""

    if text == "agentd opened task session":
        return "agentd 已打开任务会话"

    match = re.fullmatch(r"registered unit (.+)", text)
    if match:
        return f"已注册执行单元：{_format_unit_name(match.group(1))}"

    match = re.fullmatch(r"unit (.+) -> ([a-z_]+)", text)
    if match:
        return f"执行单元状态更新：{_format_unit_name(match.group(1))} -> {_translate_state(match.group(2))}"

    match = re.fullmatch(r"registered target (.+)", text)
    if match:
        return f"已注册目标：{_format_target_name(match.group(1))}"

    match = re.fullmatch(r"target (.+) -> ([a-z_]+)", text)
    if match:
        return f"目标状态更新：{_format_target_name(match.group(1))} -> {_translate_state(match.group(2))}"

    match = re.fullmatch(r"spawned ([a-z_]+) process ([a-z0-9]+)", text)
    if match:
        return f"已启动{_translate_agent_type(match.group(1))}进程（ID: {match.group(2)}）"

    match = re.fullmatch(r"running ([a-z_]+) process ([a-z0-9]+)", text)
    if match:
        return f"{_translate_agent_type(match.group(1))}进程开始运行（ID: {match.group(2)}）"

    match = re.fullmatch(r"completed ([a-z_]+) process ([a-z0-9]+)", text)
    if match:
        return f"{_translate_agent_type(match.group(1))}进程已完成（ID: {match.group(2)}）"

    match = re.fullmatch(r"restored ([a-z_]+) from checkpoint ([a-z0-9]+)", text)
    if match:
        return f"已从检查点 {match.group(2)} 恢复{_translate_agent_type(match.group(1))}"

    match = re.fullmatch(r"router selected ([a-z_]+)", text)
    if match:
        return f"路由完成：当前任务被判定为“{_translate_route(match.group(1))}”类型"

    match = re.fullmatch(r"queued on-failure unit (.+)", text)
    if match:
        return f"已排队失败回调单元：{_format_unit_name(match.group(1))}"

    match = re.fullmatch(r"queued on-success unit (.+)", text)
    if match:
        return f"已排队成功回调单元：{_format_unit_name(match.group(1))}"

    match = re.fullmatch(r"on-failure unit (.+) failed for (.+)", text)
    if match:
        return f"失败回调单元 {match.group(1)} 在处理 {_format_unit_name(match.group(2))} 时失败"

    match = re.fullmatch(r"on-success unit (.+) failed for (.+)", text)
    if match:
        return f"成功回调单元 {match.group(1)} 在处理 {_format_unit_name(match.group(2))} 时失败"

    match = re.fullmatch(r"restarting unit (.+)", text)
    if match:
        return f"准备重启执行单元：{_format_unit_name(match.group(1))}"

    match = re.fullmatch(r"step (\d+) waiting: (.+)", text)
    if match:
        return f"步骤 {int(match.group(1))} 正在等待：{_translate_detail(match.group(2))}"

    match = re.fullmatch(r"retrying step (\d+) after incomplete executor output: (.+)", text)
    if match:
        return f"步骤 {int(match.group(1))} 的执行结果不完整，准备重试：{_translate_detail(match.group(2))}"

    match = re.fullmatch(r"(critic|verifier) requested retry for step (\d+): (.+)", text)
    if match:
        return (
            f"{_translate_agent_type(match.group(1))}要求步骤 {int(match.group(2))} 重试："
            f"{_translate_detail(match.group(3))}"
        )

    match = re.fullmatch(r"unit (.+) timed out after ([0-9.]+)s \(limit ([0-9.]+)s\)", text)
    if match:
        return (
            f"执行单元超时：{_format_unit_name(match.group(1))}，"
            f"耗时 {match.group(2)} 秒，限制 {match.group(3)} 秒"
        )

    match = re.fullmatch(r"unit (.+) timed out", text)
    if match:
        return f"执行单元超时：{_format_unit_name(match.group(1))}"

    match = re.fullmatch(r"unit (.+) exceeded timeout but completed successfully", text)
    if match:
        return f"执行单元较慢但已成功完成：{_format_unit_name(match.group(1))}"

    match = re.fullmatch(
        r"Supervisor cycle (\d+): ([a-z_]+) at step (\d+)\. Reason: (.+?)\. Scheduler drain: (.+)\.",
        text,
    )
    if match:
        return (
            f"监督恢复第 {int(match.group(1))} 轮：步骤 {int(match.group(3))} 当前状态为"
            f"“{_translate_state(match.group(2))}”。原因：{_translate_detail(match.group(4))}。"
            f"调度器处理结果：{match.group(5)}。"
        )

    return _translate_detail(text)


def _emit_wrapped(label: str, text: str) -> None:
    value = str(text).strip()
    if not value:
        return
    lines = value.splitlines() or [""]
    first_prefix = label
    next_prefix = " " * len(label)
    for raw_line in lines:
        wrapped = textwrap.wrap(
            raw_line,
            width=_WRAP_WIDTH,
            break_long_words=False,
            replace_whitespace=False,
        )
        if not wrapped:
            wrapped = [""]
        for line in wrapped:
            _emit(f"{first_prefix}{line}")
            first_prefix = next_prefix


@dataclass(frozen=True)
class TurnSummary:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    generation_seconds: float

    @property
    def tokens_per_second(self) -> float:
        if self.generation_seconds <= 0:
            return 0.0
        return self.completion_tokens / self.generation_seconds


class ConsoleRenderer:
    def __init__(self, settings: StreamingConfig) -> None:
        self.settings = settings
        self._current_section: Section = None
        self._reasoning_started = False
        self._answer_started = False

    def start_turn(self) -> None:
        self._current_section = None

    def start_model_call(self) -> None:
        if self._current_section in {"reasoning", "answer"}:
            _emit()
        self._current_section = None
        self._reasoning_started = False
        self._answer_started = False

    def _switch_section(self, label: str, section: Section) -> None:
        if self._current_section == section:
            return
        if self._current_section in {"reasoning", "answer"}:
            _emit()
        _emit(label, end="")
        self._current_section = section

    def _start_structured_event(self) -> None:
        if self._current_section in {"reasoning", "answer"}:
            _emit()
        self._current_section = None

    def on_reasoning(self, text: str) -> None:
        if not text or not self.settings.show_reasoning:
            return
        if not self._reasoning_started:
            text = text.lstrip()
            if not text:
                return
            self._reasoning_started = True
        self._switch_section("思考> ", "reasoning")
        _emit(text, end="")

    def on_answer(self, text: str) -> None:
        if not text or not self.settings.show_answer:
            return
        if not self._answer_started:
            text = text.lstrip()
            if not text:
                return
            self._answer_started = True
        self._switch_section("结果> ", "answer")
        _emit(text, end="")

    def on_tool_call(self, name: str, arguments: str) -> None:
        if not self.settings.show_tool_events:
            return
        if self._current_section in {"reasoning", "answer"}:
            _emit()
        _emit(f"工具调用[{name}]> {arguments}")
        self._current_section = "tool"

    def on_tool_result(self, name: str, result: str) -> None:
        if not self.settings.show_tool_events:
            return
        _emit(f"工具结果[{name}]> {result}")
        self._current_section = "tool"

    def finish_turn(self, summary: TurnSummary) -> None:
        if self._current_section in {"reasoning", "answer"}:
            _emit()
        if self.settings.show_usage:
            _emit(
                "统计> "
                f"输入Token={summary.prompt_tokens} "
                f"输出Token={summary.completion_tokens} "
                f"总Token={summary.total_tokens} "
                f"生成速度={summary.tokens_per_second:.2f} token/s"
            )
        self._current_section = "stats"

    def on_task_created(self, task_id: str, title: str, steps: list[str]) -> None:
        self._start_structured_event()
        _emit(f"任务> {title}")
        _emit(f"  任务ID: {task_id}")
        total_steps = len(steps)
        for index, step in enumerate(steps, start=1):
            _emit(f"计划[{index}/{total_steps}]> {step}")

    def on_step_start(self, task_id: str, step_index: int, total_steps: int, title: str) -> None:
        self._start_structured_event()
        _emit(f"步骤[{step_index}/{total_steps}]> {title}")
        _emit(f"  所属任务: {task_id}")

    def on_task_complete(self, task_id: str, summary: str) -> None:
        self._start_structured_event()
        _emit(f"任务完成> {task_id}")
        _emit_wrapped("  总结: ", summary)

    def on_process_spawn(self, process_id: str, agent_type: str, priority: str) -> None:
        self._start_structured_event()
        _emit(
            "进程启动> "
            f"{_translate_agent_type(agent_type)} | ID={process_id} | 优先级={_translate_priority(priority)}"
        )

    def on_process_state(
        self,
        process_id: str,
        state: str,
        *,
        detail: str = "",
    ) -> None:
        self._start_structured_event()
        _emit(f"进程状态> ID={process_id} | 状态={_translate_state(state)}")
        translated_detail = _translate_detail(detail)
        if translated_detail:
            _emit_wrapped("  说明: ", translated_detail)

    def on_checkpoint(self, process_id: str, phase: str, summary: str) -> None:
        self._start_structured_event()
        _emit(f"检查点> ID={process_id} | 阶段={_translate_phase(phase)}")
        translated_summary = _translate_detail(summary)
        if translated_summary:
            _emit_wrapped("  摘要: ", translated_summary)

    def on_kernel_event(self, message: str) -> None:
        self._start_structured_event()
        _emit_wrapped("内核> ", _translate_kernel_message(message))


class NullRenderer:
    def start_turn(self) -> None:
        return

    def start_model_call(self) -> None:
        return

    def on_reasoning(self, text: str) -> None:
        return

    def on_answer(self, text: str) -> None:
        return

    def on_tool_call(self, name: str, arguments: str) -> None:
        return

    def on_tool_result(self, name: str, result: str) -> None:
        return

    def finish_turn(self, summary: TurnSummary) -> None:
        return

    def on_process_spawn(self, process_id: str, agent_type: str, priority: str) -> None:
        return

    def on_process_state(self, process_id: str, state: str, *, detail: str = "") -> None:
        return

    def on_checkpoint(self, process_id: str, phase: str, summary: str) -> None:
        return

    def on_kernel_event(self, message: str) -> None:
        return
