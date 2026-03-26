from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from minimax_agent import AgentApplication, load_app_config
from minimax_agent.task_store import TaskStore


def _configure_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class ValidationScenario:
    name: str
    description: str
    prompt: str


def _default_scenarios() -> list[ValidationScenario]:
    return [
        ValidationScenario(
            name="tool_file_chain",
            description="工具调用、文件写入和读取确认链路。",
            prompt=(
                "请严格按三个阶段完成："
                "1. 必须调用 calculator 工具计算 ((23×7)-5)÷2；"
                "2. 在 .agent_state/validation_workspace/control_result.txt 写入 result=<结果>；"
                "3. 读取该文件并确认内容，最后用一句话总结。"
            ),
        ),
        ValidationScenario(
            name="repo_structure_long_task",
            description="多阶段仓库分析任务，用来观察 planner、compressor 和持久化行为。",
            prompt=(
                "请严格按四个阶段完成："
                "1. 列出 minimax_agent 目录下所有 Python 文件；"
                "2. 读取 minimax_agent/agentos.py、minimax_agent/task_agent.py、minimax_agent/task_store.py 的关键结构；"
                "3. 用不超过 8 条要点总结当前 AgentOS 的内核、进程、checkpoint 和持久化设计；"
                "4. 把总结写入 .agent_state/validation_workspace/agentos_summary.md 并再次读取确认。"
            ),
        ),
        ValidationScenario(
            name="gan_stability_review",
            description="结合 GAN 的 generator-discriminator 思路做长时稳定性审查。",
            prompt=(
                "请严格按四个阶段完成："
                "1. 借鉴 GAN 的 generator-discriminator 思想，把 executor 看作 generator、critic 看作 discriminator、verifier 看作最终裁判；"
                "2. 分析当前 AgentOS 在复杂长时任务下的 3 个稳定性风险和 3 个改进建议；"
                "3. 将结果写入 .agent_state/validation_workspace/gan_stability_report.md；"
                "4. 再读取该文件并用一句话确认。"
            ),
        ),
    ]


def _recent_task_ids(store: TaskStore, limit: int = 20) -> set[str]:
    return {task.task_id for task in store.list_recent_tasks(limit)}


def _detect_new_task_id(store: TaskStore, previous_ids: set[str]) -> str:
    recent_tasks = store.list_recent_tasks(20)
    for task in recent_tasks:
        if task.task_id not in previous_ids:
            return task.task_id
    if not recent_tasks:
        raise RuntimeError("No task was persisted")
    return recent_tasks[0].task_id


def _summarize_scenario(
    store: TaskStore,
    scenario: ValidationScenario,
    task_id: str,
    duration_seconds: float,
) -> dict:
    task = store.get_task(task_id)
    processes = store.list_processes(task_id, limit=500)
    events = store.list_events(task_id, limit=500)
    checkpoints = store.list_checkpoints(task_id, limit=500)
    units = store.list_units(task_id, limit=500)
    targets = store.list_targets(task_id, limit=500)
    process_counter = Counter(process.agent_type for process in processes)
    unit_state_counter = Counter(unit.state for unit in units)
    target_state_counter = Counter(target.state for target in targets)
    failed_processes = [process.process_id for process in processes if process.state == "failed"]
    critic_rejections = sum(
        1
        for process in processes
        if process.agent_type == "critic" and '"approved": false' in process.output_preview.lower()
    )
    verifier_rejections = sum(
        1
        for process in processes
        if process.agent_type == "verifier" and '"approved": false' in process.output_preview.lower()
    )
    return {
        "scenario": asdict(scenario),
        "task_id": task_id,
        "duration_seconds": round(duration_seconds, 2),
        "task_status": task.status,
        "step_count": len(task.steps),
        "final_summary": task.final_summary,
        "process_counts": dict(process_counter),
        "failed_processes": failed_processes,
        "critic_rejections": critic_rejections,
        "verifier_rejections": verifier_rejections,
        "event_count": len(events),
        "checkpoint_count": len(checkpoints),
        "unit_count": len(units),
        "unit_state_counts": dict(unit_state_counter),
        "target_count": len(targets),
        "target_state_counts": dict(target_state_counter),
        "artifact_counts": store.count_task_artifacts(task_id),
        "artifact_paths": store.describe_task_artifacts(task_id),
        "executor_retry_count": max(0, process_counter.get("executor", 0) - len(task.steps)),
        "compression_runs": process_counter.get("compressor", 0),
    }


def _write_report(workspace_root: Path, report: dict) -> Path:
    target_dir = workspace_root / ".agent_state" / "validation_reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = target_dir / f"agentos_validation_{timestamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    _configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Run only the named scenario. May be passed multiple times.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List built-in scenarios and exit.",
    )
    args = parser.parse_args()

    scenarios = _default_scenarios()
    if args.list:
        for scenario in scenarios:
            print(f"{scenario.name}: {scenario.description}")
        return

    selected = scenarios
    if args.scenario:
        allowed = set(args.scenario)
        selected = [scenario for scenario in scenarios if scenario.name in allowed]
        if not selected:
            raise SystemExit("No matching validation scenarios were found.")

    config = load_app_config()
    store = TaskStore(config)
    suite_start = time.perf_counter()
    scenario_reports: list[dict] = []

    with AgentApplication(config) as app:
        for scenario in selected:
            print(f"\n=== Running scenario: {scenario.name} ===", flush=True)
            previous_ids = _recent_task_ids(store)
            start = time.perf_counter()
            scenario_report: dict
            try:
                app.invoke(scenario.prompt)
                duration_seconds = time.perf_counter() - start
                task_id = _detect_new_task_id(store, previous_ids)
                scenario_report = _summarize_scenario(
                    store,
                    scenario,
                    task_id,
                    duration_seconds,
                )
            except Exception as exc:
                duration_seconds = time.perf_counter() - start
                task_id = None
                try:
                    task_id = _detect_new_task_id(store, previous_ids)
                except Exception:
                    task_id = ""
                scenario_report = {
                    "scenario": asdict(scenario),
                    "task_id": task_id,
                    "duration_seconds": round(duration_seconds, 2),
                    "task_status": "validation_error",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                if task_id:
                    scenario_report["partial_task"] = _summarize_scenario(
                        store,
                        scenario,
                        task_id,
                        duration_seconds,
                    )
            scenario_reports.append(scenario_report)
            print(
                f"ScenarioDone> {scenario.name} | "
                f"status={scenario_report['task_status']} | "
                f"duration={scenario_report['duration_seconds']}s",
                flush=True,
            )

    suite_duration = time.perf_counter() - suite_start
    report = {
        "generated_at": datetime.now().isoformat(),
        "suite_duration_seconds": round(suite_duration, 2),
        "scenario_count": len(scenario_reports),
        "reports": scenario_reports,
    }
    report_path = _write_report(config.workspace_root, report)
    print(f"\nValidationReport> {report_path}", flush=True)


if __name__ == "__main__":
    main()
