from __future__ import annotations

import base64
import contextlib
import shutil
import io
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx

try:
    from duckduckgo_search import DDGS
except Exception:  # pragma: no cover - optional dependency
    DDGS = None

from .config import AppConfig


ToolHandler = Callable[[dict[str, Any], "ToolExecutionContext | None"], str]
_SEARCH_TIMEOUT_SECONDS = 20
_SEARCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolExecutionContext:
    process_id: str = ""
    task_id: str = ""
    identity: str = ""
    task_namespace: str = ""
    repo_namespace: tuple[str, ...] = ()
    memory_namespace: tuple[str, ...] = ()
    mounts: dict[str, str] = field(default_factory=dict)

    @property
    def allowed_mounts(self) -> tuple[str, ...]:
        allowed: list[str] = []
        for mount in (*self.repo_namespace, *self.memory_namespace):
            normalized = _normalize_mount_point(str(mount))
            if normalized not in allowed:
                allowed.append(normalized)
        if not allowed:
            for mount in self.mounts:
                normalized = _normalize_mount_point(str(mount))
                if normalized not in allowed:
                    allowed.append(normalized)
        return tuple(allowed)


@dataclass(frozen=True)
class VfsResolvedPath:
    mount_point: str
    mount_root: Path
    host_path: Path
    virtual_path: str


class ToolRegistry:
    def __init__(
        self,
        tools: list[ToolSpec],
        *,
        default_context: ToolExecutionContext | None = None,
    ) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._default_context = default_context

    @property
    def openai_tools(self) -> list[dict[str, Any]]:
        return self.to_openai_tools()

    @property
    def tool_names(self) -> set[str]:
        return set(self._tools)

    def to_openai_tools(self, allowlist: set[str] | None = None) -> list[dict[str, Any]]:
        tools = self._tools.values()
        if allowlist is not None:
            tools = [tool for tool in tools if tool.name in allowlist]
        return [tool.to_openai_tool() for tool in tools]

    def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"tool_error: unknown tool '{name}'"
        try:
            return tool.handler(arguments, context or self._default_context)
        except Exception as exc:
            return f"tool_error: {exc}"


def _normalize_vfs_input(raw_value: str) -> str:
    return raw_value.strip().replace("\\", "/")


def _normalize_mount_point(raw_mount: str) -> str:
    normalized = _normalize_vfs_input(raw_mount)
    if not normalized.startswith("/"):
        normalized = "/" + normalized.lstrip("/")
    normalized = normalized.rstrip("/")
    return normalized or "/"


def _join_virtual_path(mount_point: str, relative_path: str) -> str:
    relative = relative_path.strip("/")
    return mount_point if not relative else f"{mount_point}/{relative}"


def _contains_glob(pattern: str) -> bool:
    return any(character in pattern for character in "*?[")


class AgentVfsView:
    def __init__(self, context: ToolExecutionContext | None) -> None:
        self._context = context or ToolExecutionContext()
        self._mounts = {
            _normalize_mount_point(mount): Path(target).resolve()
            for mount, target in self._context.mounts.items()
        }
        self._allowed_mounts = [
            mount for mount in self._context.allowed_mounts if mount in self._mounts
        ]
        if not self._allowed_mounts and "/workspace/repo" in self._mounts:
            self._allowed_mounts = ["/workspace/repo"]

    def resolve_path(self, raw_path: str) -> VfsResolvedPath:
        normalized = _normalize_vfs_input(raw_path)
        if not normalized:
            raise ValueError("Path is required")
        if normalized.startswith("/"):
            mount_point, relative_path = self._match_mount(normalized)
        else:
            mount_point = self._default_repo_mount()
            relative_path = normalized.lstrip("/")
        return self._resolved_from_relative(mount_point, relative_path)

    def iter_files(self, pattern: str, *, limit: int) -> list[VfsResolvedPath]:
        mount_point, mount_root, glob_pattern = self.resolve_glob(pattern)
        resolved: list[VfsResolvedPath] = []

        if not _contains_glob(glob_pattern):
            exact = self._resolved_from_relative(mount_point, glob_pattern)
            if exact.host_path.exists() and exact.host_path.is_file():
                if not self._is_excluded(exact):
                    return [exact]
                return []
            if exact.host_path.exists() and exact.host_path.is_dir():
                iterator = exact.host_path.rglob("*")
            else:
                return []
        else:
            iterator = mount_root.glob(glob_pattern)

        for path in iterator:
            item = self._resolved_from_host(mount_point, mount_root, path)
            if self._is_excluded(item):
                continue
            if item.host_path.is_file():
                resolved.append(item)
            if len(resolved) >= limit:
                break
        return resolved

    def resolve_glob(self, raw_pattern: str) -> tuple[str, Path, str]:
        normalized = _normalize_vfs_input(raw_pattern) or "**/*"
        if normalized.startswith("/"):
            mount_point, remainder = self._match_mount(normalized)
            glob_pattern = remainder or "**/*"
        else:
            mount_point = self._default_repo_mount()
            glob_pattern = normalized

        for part in PurePosixPath(glob_pattern).parts:
            if part == "..":
                raise ValueError("Glob pattern escapes the allowed Agent VFS mount")
        return mount_point, self._mounts[mount_point], glob_pattern

    def _default_repo_mount(self) -> str:
        for mount in self._context.repo_namespace:
            normalized = _normalize_mount_point(str(mount))
            if normalized in self._allowed_mounts:
                return normalized
        if "/workspace/repo" in self._allowed_mounts:
            return "/workspace/repo"
        if self._allowed_mounts:
            return self._allowed_mounts[0]
        raise ValueError("No allowed Agent VFS mount is available for this process")

    def _match_mount(self, raw_path: str) -> tuple[str, str]:
        for mount_point in sorted(self._allowed_mounts, key=len, reverse=True):
            if raw_path == mount_point:
                return mount_point, ""
            prefix = mount_point + "/"
            if raw_path.startswith(prefix):
                return mount_point, raw_path[len(prefix) :]
        allowed = ", ".join(self._allowed_mounts) or "(none)"
        raise ValueError(
            f"Path is outside the allowed Agent VFS mounts for this process: {allowed}"
        )

    def _resolved_from_relative(
        self,
        mount_point: str,
        relative_path: str,
    ) -> VfsResolvedPath:
        mount_root = self._mounts.get(mount_point)
        if mount_root is None:
            raise ValueError(f"Mount is not configured: {mount_point}")

        parts = [segment for segment in relative_path.split("/") if segment not in {"", "."}]
        host_path = (mount_root.joinpath(*parts)).resolve() if parts else mount_root
        if host_path != mount_root and mount_root not in host_path.parents:
            raise ValueError("Path escapes the allowed Agent VFS mount")
        virtual_path = _join_virtual_path(mount_point, "/".join(parts))
        return VfsResolvedPath(
            mount_point=mount_point,
            mount_root=mount_root,
            host_path=host_path,
            virtual_path=virtual_path,
        )

    def _resolved_from_host(
        self,
        mount_point: str,
        mount_root: Path,
        host_path: Path,
    ) -> VfsResolvedPath:
        resolved_host = host_path.resolve()
        if resolved_host != mount_root and mount_root not in resolved_host.parents:
            raise ValueError("Path escapes the allowed Agent VFS mount")
        relative_path = ""
        if resolved_host != mount_root:
            relative_path = resolved_host.relative_to(mount_root).as_posix()
        return VfsResolvedPath(
            mount_point=mount_point,
            mount_root=mount_root,
            host_path=resolved_host,
            virtual_path=_join_virtual_path(mount_point, relative_path),
        )

    def _is_excluded(self, path: VfsResolvedPath) -> bool:
        if path.host_path == path.mount_root:
            return False
        relative = path.host_path.relative_to(path.mount_root).as_posix()
        return (
            relative == ".git"
            or relative.startswith(".git/")
            or relative == "__pycache__"
            or relative.startswith("__pycache__/")
        )


def _normalize_search_results(
    items: list[dict[str, Any]],
    *,
    source: str,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in items:
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "") or item.get("href", "")).strip()
        snippet = str(item.get("snippet", "") or item.get("body", "")).strip()
        if not title or not url:
            continue
        normalized.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": source,
            }
        )
    return normalized


def _search_with_ddgs(
    query: str,
    *,
    max_results: int,
    region: str,
    safesearch: str,
) -> list[dict[str, str]]:
    if DDGS is None:
        raise RuntimeError(
            "duckduckgo_search is not installed; use the Bing fallback or install duckduckgo-search"
        )
    errors: list[str] = []
    for backend in ("auto", "html", "lite"):
        for attempt in range(2):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with DDGS(timeout=_SEARCH_TIMEOUT_SECONDS) as ddgs:
                            items = list(
                                ddgs.text(
                                    query,
                                    max_results=max_results,
                                    region=region,
                                    safesearch=safesearch,
                                    backend=backend,
                                )
                            )
                normalized = _normalize_search_results(items, source="duckduckgo")
                if normalized:
                    return normalized[:max_results]
                errors.append(f"duckduckgo backend={backend} returned no results")
            except Exception as exc:
                errors.append(
                    f"duckduckgo backend={backend} attempt={attempt + 1} failed: {exc}"
                )
    raise RuntimeError("; ".join(errors[-4:]) or "duckduckgo search failed")


def _decode_bing_redirect_url(url: str) -> str:
    if not url:
        return ""

    parsed = urlparse(url)
    if "bing.com" not in parsed.netloc or not parsed.path.startswith("/ck/a"):
        return url

    raw_value = parse_qs(parsed.query).get("u", [""])[0]
    if not raw_value.startswith("a1"):
        return url

    payload = raw_value[2:]
    try:
        padding = "=" * ((4 - len(payload) % 4) % 4)
        return base64.b64decode(payload + padding).decode("utf-8")
    except Exception:
        return url


def _search_with_bing(query: str, *, max_results: int) -> list[dict[str, str]]:
    with httpx.Client(
        headers={"User-Agent": _SEARCH_USER_AGENT},
        follow_redirects=True,
        timeout=_SEARCH_TIMEOUT_SECONDS,
    ) as client:
        response = client.get(
            "https://www.bing.com/search",
            params={"q": query, "format": "rss", "mkt": "zh-CN", "setlang": "zh-Hans"},
        )
        response.raise_for_status()

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise RuntimeError(f"bing RSS parse failed: {exc}") from exc

    results: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = " ".join((item.findtext("title", "") or "").split())
        url = _decode_bing_redirect_url((item.findtext("link", "") or "").strip())
        snippet = " ".join((item.findtext("description", "") or "").split())
        if not title or not url:
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": "bing",
            }
        )
        if len(results) >= max_results:
            break

    if not results:
        raise RuntimeError("bing returned no parsed results")
    return results


def build_tool_registry(config: AppConfig) -> ToolRegistry:
    default_context = ToolExecutionContext(
        identity="host",
        task_namespace="host",
        repo_namespace=("/workspace/repo",),
        memory_namespace=tuple(
            str(mount_point)
            for mount_point in config.agentos.vfs_mounts
            if str(mount_point).startswith("/memory/")
        ),
        mounts={
            str(mount_point): str(target)
            for mount_point, target in config.agentos.vfs_mounts.items()
        },
    )

    def current_time(_: dict[str, Any], _context: ToolExecutionContext | None) -> str:
        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()

    def calculator(arguments: dict[str, Any], _context: ToolExecutionContext | None) -> str:
        expression = str(arguments.get("expression", "")).strip()
        if not expression:
            return "calculation_error: missing expression"

        allowed_names = {
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "pow": pow,
            "sqrt": math.sqrt,
        }
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)

    def server_health(_: dict[str, Any], _context: ToolExecutionContext | None) -> str:
        return (
            f"base_url={config.model_base_url} "
            f"model={config.model_name} "
            f"context_window_tokens={config.model.context_window_tokens}"
        )

    def list_workspace_files(
        arguments: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> str:
        pattern = str(arguments.get("pattern", "**/*")).strip() or "**/*"
        limit = max(1, min(int(arguments.get("limit", 50)), 200))
        view = AgentVfsView(context)
        results = [item.virtual_path for item in view.iter_files(pattern, limit=limit)]
        return json.dumps(results, ensure_ascii=False, indent=2)

    def read_workspace_file(
        arguments: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> str:
        raw_path = str(arguments.get("path", "")).strip()
        if not raw_path:
            return "file_error: missing path"
        start_line = max(1, int(arguments.get("start_line", 1)))
        end_line = max(start_line, int(arguments.get("end_line", start_line + 199)))
        view = AgentVfsView(context)
        path = view.resolve_path(raw_path)
        if not path.host_path.exists() or not path.host_path.is_file():
            return f"file_error: not found: {raw_path}"

        lines = path.host_path.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = []
        for index in range(start_line - 1, min(end_line, len(lines))):
            selected.append(f"{index + 1}: {lines[index]}")
        return "\n".join(selected) if selected else "file_error: no content in range"

    def search_workspace_text(
        arguments: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> str:
        pattern = str(arguments.get("pattern", "")).strip()
        if not pattern:
            return "search_error: missing pattern"

        glob_pattern = str(arguments.get("glob", "**/*")).strip() or "**/*"
        limit = max(1, min(int(arguments.get("limit", 20)), 100))
        regex = re.compile(pattern)
        view = AgentVfsView(context)
        matches: list[str] = []
        for path in view.iter_files(glob_pattern, limit=2000):
            content = path.host_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line_no, line in enumerate(content, start=1):
                if regex.search(line):
                    matches.append(f"{path.virtual_path}:{line_no}: {line}")
                    if len(matches) >= limit:
                        return "\n".join(matches)
        return "\n".join(matches) if matches else "search_error: no matches found"

    def write_workspace_file(
        arguments: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> str:
        raw_path = str(arguments.get("path", "")).strip()
        content = str(arguments.get("content", ""))
        overwrite = bool(arguments.get("overwrite", False))
        if not raw_path:
            return "file_error: missing path"
        view = AgentVfsView(context)
        path = view.resolve_path(raw_path)
        if path.host_path.exists() and not overwrite:
            return "file_error: file exists and overwrite=false"
        path.host_path.parent.mkdir(parents=True, exist_ok=True)
        path.host_path.write_text(content, encoding="utf-8")
        return f"wrote_file: {path.virtual_path} ({len(content)} chars)"

    def replace_text_in_workspace_file(
        arguments: dict[str, Any],
        context: ToolExecutionContext | None,
    ) -> str:
        raw_path = str(arguments.get("path", "")).strip()
        old_text = str(arguments.get("old_text", ""))
        new_text = str(arguments.get("new_text", ""))
        replace_all = bool(arguments.get("replace_all", False))
        if not raw_path:
            return "file_error: missing path"
        if not old_text:
            return "file_error: missing old_text"
        view = AgentVfsView(context)
        path = view.resolve_path(raw_path)
        if not path.host_path.exists() or not path.host_path.is_file():
            return f"file_error: not found: {raw_path}"
        content = path.host_path.read_text(encoding="utf-8", errors="replace")
        if old_text not in content:
            return "file_error: old_text not found"
        if replace_all:
            updated = content.replace(old_text, new_text)
            replacements = content.count(old_text)
        else:
            updated = content.replace(old_text, new_text, 1)
            replacements = 1
        path.host_path.write_text(updated, encoding="utf-8")
        return f"updated_file: {path.virtual_path} replacements={replacements}"

    class _BrowserHTMLParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.title_parts: list[str] = []
            self.text_parts: list[str] = []
            self.links: list[dict[str, str]] = []
            self._in_title = False
            self._ignore_depth = 0

        @property
        def title(self) -> str:
            return " ".join(part.strip() for part in self.title_parts if part.strip())

        @property
        def text(self) -> str:
            return " ".join(part.strip() for part in self.text_parts if part.strip())

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in {"script", "style", "noscript"}:
                self._ignore_depth += 1
                return
            if tag == "title":
                self._in_title = True
                return
            if tag == "a":
                href = ""
                for key, value in attrs:
                    if key == "href" and value:
                        href = value.strip()
                        break
                if href:
                    self.links.append({"href": href})

        def handle_endtag(self, tag: str) -> None:
            if tag in {"script", "style", "noscript"} and self._ignore_depth > 0:
                self._ignore_depth -= 1
            elif tag == "title":
                self._in_title = False

        def handle_data(self, data: str) -> None:
            if self._ignore_depth > 0:
                return
            text = " ".join(unescape(data).split())
            if not text:
                return
            if self._in_title:
                self.title_parts.append(text)
            else:
                self.text_parts.append(text)

    def _extract_browser_document(html_text: str) -> dict[str, Any]:
        parser = _BrowserHTMLParser()
        parser.feed(html_text)
        parser.close()
        links: list[dict[str, str]] = []
        seen_links: set[str] = set()
        for item in parser.links:
            href = str(item.get("href", "")).strip()
            if not href or href in seen_links:
                continue
            seen_links.add(href)
            links.append({"href": href})
        return {
            "title": parser.title.strip(),
            "text": parser.text.strip(),
            "links": links,
        }

    def _fetch_with_lightpanda(url: str) -> tuple[str, str]:
        binary = shutil.which("lightpanda")
        if not binary:
            raise FileNotFoundError("lightpanda binary not found")
        commands = [
            [binary, "fetch", "--dump", url],
            [binary, "fetch", url],
        ]
        errors: list[str] = []
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=True,
                )
                output = (completed.stdout or completed.stderr or "").strip()
                if output:
                    return output, "lightpanda"
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError("; ".join(errors) or "lightpanda fetch failed")

    def browser_fetch(arguments: dict[str, Any], _context: ToolExecutionContext | None) -> str:
        url = str(arguments.get("url", "")).strip()
        if not url:
            return "browser_error: missing url"
        max_chars = max(1200, min(int(arguments.get("max_chars", 12000)), 50000))
        max_links = max(1, min(int(arguments.get("max_links", 30)), 100))

        source = "httpx"
        status_code = 200
        final_url = url
        raw_text = ""
        try:
            raw_text, source = _fetch_with_lightpanda(url)
        except Exception:
            httpx_errors: list[str] = []
            try:
                response = httpx.get(
                    url,
                    headers={"User-Agent": _SEARCH_USER_AGENT},
                    timeout=30,
                    follow_redirects=True,
                )
                response.raise_for_status()
                final_url = str(response.url)
                status_code = response.status_code
                raw_text = response.text
            except Exception as exc:
                httpx_errors.append(str(exc))
                try:
                    response = httpx.get(
                        url,
                        headers={"User-Agent": _SEARCH_USER_AGENT},
                        timeout=30,
                        follow_redirects=True,
                        verify=False,
                    )
                    response.raise_for_status()
                    final_url = str(response.url)
                    status_code = response.status_code
                    raw_text = response.text
                    source = "httpx-insecure"
                except Exception as insecure_exc:
                    httpx_errors.append(str(insecure_exc))
                    return "browser_error: " + " | ".join(httpx_errors)

        if "<html" in raw_text.lower() or "<body" in raw_text.lower():
            document = _extract_browser_document(raw_text)
        else:
            document = {"title": "", "text": " ".join(raw_text.split()), "links": []}

        links = document.get("links", [])[:max_links]
        text = str(document.get("text", "")).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."

        return json.dumps(
            {
                "url": url,
                "final_url": final_url,
                "status_code": status_code,
                "source": source,
                "title": document.get("title", ""),
                "text": text,
                "links": links,
            },
            ensure_ascii=False,
            indent=2,
        )

    def web_search(arguments: dict[str, Any], _context: ToolExecutionContext | None) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "search_error: missing query"
        max_results = max(
            1,
            min(
                int(arguments.get("max_results", config.web_search.max_results)),
                10,
            ),
        )
        provider_errors: list[str] = []
        try:
            results = _search_with_ddgs(
                query,
                max_results=max_results,
                region=config.web_search.region,
                safesearch=config.web_search.safesearch,
            )
            return json.dumps(results, ensure_ascii=False, indent=2)
        except Exception as exc:
            provider_errors.append(str(exc))

        try:
            results = _search_with_bing(query, max_results=max_results)
            return json.dumps(results, ensure_ascii=False, indent=2)
        except Exception as exc:
            provider_errors.append(str(exc))

        return "search_error: all providers failed | " + " | ".join(provider_errors)

    return ToolRegistry(
        [
            ToolSpec(
                name="current_time",
                description="Return the current Beijing time in ISO 8601 format.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=current_time,
            ),
            ToolSpec(
                name="calculator",
                description="Evaluate a basic arithmetic expression.",
                parameters={
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "A math expression such as sqrt(81) + 4 * 7.",
                        }
                    },
                    "required": ["expression"],
                    "additionalProperties": False,
                },
                handler=calculator,
            ),
            ToolSpec(
                name="server_health",
                description="Describe which remote model endpoint the agent is connected to.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                handler=server_health,
            ),
            ToolSpec(
                name="list_workspace_files",
                description="List files visible inside the current Agent VFS namespace using a glob pattern.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern inside Agent VFS. Use /workspace/repo/... for explicit mounts, or a relative path for the default repo mount.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of paths to return.",
                            "minimum": 1,
                            "maximum": 200,
                        },
                    },
                    "additionalProperties": False,
                },
                handler=list_workspace_files,
            ),
            ToolSpec(
                name="read_workspace_file",
                description="Read a text file inside the current Agent VFS namespace with line numbers.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Agent VFS path such as /workspace/repo/README.md. Relative paths resolve against the default repo mount.",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "1-based start line.",
                            "minimum": 1,
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "1-based end line.",
                            "minimum": 1,
                        },
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                handler=read_workspace_file,
            ),
            ToolSpec(
                name="search_workspace_text",
                description="Search text files visible in the current Agent VFS namespace with a regular expression.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Regular expression to search for.",
                        },
                        "glob": {
                            "type": "string",
                            "description": "Optional Agent VFS glob to limit the searched files.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of matches to return.",
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    "required": ["pattern"],
                    "additionalProperties": False,
                },
                handler=search_workspace_text,
            ),
            ToolSpec(
                name="write_workspace_file",
                description="Write a text file inside the current Agent VFS namespace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Agent VFS path such as /workspace/repo/notes.txt. Relative paths resolve against the default repo mount.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full file content to write.",
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "Whether to overwrite an existing file.",
                        },
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                handler=write_workspace_file,
            ),
            ToolSpec(
                name="replace_text_in_workspace_file",
                description="Replace text inside a text file visible in the current Agent VFS namespace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Agent VFS path such as /workspace/repo/config.json. Relative paths resolve against the default repo mount.",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "The exact text to replace.",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text.",
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "Replace all matches instead of only the first one.",
                        },
                    },
                    "required": ["path", "old_text", "new_text"],
                    "additionalProperties": False,
                },
                handler=replace_text_in_workspace_file,
            ),
            ToolSpec(
                name="web_search",
                description="Search the web and return top results with title, URL, and snippet.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The web search query.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return.",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=web_search,
            ),
            ToolSpec(
                name="browser_fetch",
                description="Fetch a web page with Lightpanda when available, otherwise fall back to HTTP retrieval and text extraction.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The page URL to fetch.",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum number of extracted text characters to return.",
                            "minimum": 1200,
                            "maximum": 50000,
                        },
                        "max_links": {
                            "type": "integer",
                            "description": "Maximum number of links to return.",
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
                handler=browser_fetch,
            ),
        ],
        default_context=default_context,
    )
