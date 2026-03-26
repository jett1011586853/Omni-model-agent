from __future__ import annotations

import argparse
import re
import sys

from minimax_agent import AgentApplication, load_app_config


def _configure_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _format_cli_error(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return "发生未知错误。"

    match = re.fullmatch(
        r"Remote model stream failed: (Server|Client) error '([^']+)' for url '([^']+)'(?:\s+For more information check:\s+.+)?",
        text,
    )
    if match:
        return f"远程模型流式调用失败：模型网关返回 {match.group(2)}（{match.group(3)}）"

    if "SSH session not active" in text:
        return "SSH 隧道会话未激活或已断开。"

    return text


def run_cli() -> None:
    _configure_console()
    config = load_app_config()
    with AgentApplication(config) as app:
        print("AgentOS engineering agent is ready. Type 'exit' to quit.")
        print("Use '/image <path-or-url>[,<path-or-url>...] :: <prompt>' for multimodal turns.")
        print(
            "Use '/tasks', '/skills', '/skill <name>', '/skill-files <name>', '/taskfs [task_id]', '/units [task_id]', "
            "'/targets [task_id]', '/unitgraph [task_id]', '/targetgraph [task_id]', '/ps [task_id]', '/events [task_id]', "
            "'/ipc [task_id]', '/checkpoints [task_id]', '/runproc <process_id>', '/restore <checkpoint_id-or-process_id>', "
            "'/resume <task_id>', '/pump [task_id]', or '/mounts' to inspect runtime state."
        )
        while True:
            try:
                user_input = input("\nYou> ").strip()
            except EOFError:
                print("\nInput stream closed. Exiting.")
                break
            except KeyboardInterrupt:
                print("\nInterrupted. Exiting.")
                break
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break
            try:
                app.invoke(user_input)
            except Exception as exc:
                print(f"\n错误> {_format_cli_error(exc)}")


def run_once(
    prompt: str,
    *,
    image_paths: list[str] | None = None,
    image_urls: list[str] | None = None,
) -> None:
    _configure_console()
    config = load_app_config()
    with AgentApplication(config) as app:
        try:
            app.invoke(
                prompt,
                image_paths=image_paths,
                image_urls=image_urls,
            )
        except Exception as exc:
            print(f"\n错误> {_format_cli_error(exc)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", help="Run a single prompt and exit.")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Attach a local image path. May be passed multiple times.",
    )
    parser.add_argument(
        "--image-url",
        action="append",
        default=[],
        help="Attach a remote image URL. May be passed multiple times.",
    )
    args = parser.parse_args()

    if args.prompt:
        run_once(
            args.prompt,
            image_paths=args.image,
            image_urls=args.image_url,
        )
    else:
        run_cli()
