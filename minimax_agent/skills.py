from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def _normalize_skill_name(raw: str) -> str:
    return "".join(ch for ch in raw.lower() if ch.isalnum())


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    metadata: dict[str, str] = {}
    index = 1
    while index < len(lines):
        line = lines[index].strip()
        if line == "---":
            index += 1
            break
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip().strip("'\"")
        index += 1
    return metadata, "\n".join(lines[index:])


@dataclass(frozen=True)
class SkillEntry:
    name: str
    description: str
    root: Path
    path: Path
    body: str
    resources: tuple["SkillResource", ...] = ()

    @property
    def normalized_name(self) -> str:
        return _normalize_skill_name(self.name)

    @property
    def slug(self) -> str:
        return _normalize_skill_name(self.path.parent.name)

    @property
    def resource_summary(self) -> str:
        if not self.resources:
            return "resources=0"
        counts: dict[str, int] = {}
        for resource in self.resources:
            counts[resource.kind] = counts.get(resource.kind, 0) + 1
        parts = [f"{kind}={counts[kind]}" for kind in sorted(counts)]
        return ", ".join(parts)


@dataclass(frozen=True)
class SkillResource:
    kind: str
    relative_path: str
    path: Path


_SKILL_TOOL_HINTS: dict[str, tuple[str, ...]] = {
    "skillcreator": ("read_workspace_file", "write_workspace_file", "search_workspace_text"),
    "planningwithfiles": (
        "list_workspace_files",
        "read_workspace_file",
        "search_workspace_text",
        "write_workspace_file",
        "replace_text_in_workspace_file",
    ),
    "uiuxpromaxfrontenddesign": (
        "web_search",
        "browser_fetch",
        "read_workspace_file",
        "write_workspace_file",
    ),
    "frontendpatterns": (
        "read_workspace_file",
        "search_workspace_text",
        "write_workspace_file",
    ),
    "vercelreactbestpractices": (
        "web_search",
        "browser_fetch",
        "read_workspace_file",
    ),
    "backendpatterns": (
        "read_workspace_file",
        "search_workspace_text",
        "write_workspace_file",
    ),
    "clickhouseio": (
        "read_workspace_file",
        "search_workspace_text",
        "web_search",
    ),
    "codingstandards": (
        "read_workspace_file",
        "search_workspace_text",
    ),
    "securityreview": (
        "web_search",
        "browser_fetch",
        "read_workspace_file",
        "search_workspace_text",
    ),
    "tddworkflow": (
        "read_workspace_file",
        "search_workspace_text",
    ),
    "obsidianskills": (
        "read_workspace_file",
        "write_workspace_file",
        "search_workspace_text",
    ),
    "superpowers": (
        "list_workspace_files",
        "read_workspace_file",
        "search_workspace_text",
        "web_search",
    ),
    "notebooklmskill": (
        "web_search",
        "browser_fetch",
        "read_workspace_file",
    ),
    "lightpandabrowser": (
        "browser_fetch",
        "web_search",
    ),
}


class SkillCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._skills: list[SkillEntry] = []
        self._index: dict[str, SkillEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.root.exists():
            return
        for skill_path in sorted(self.root.glob("*/SKILL.md")):
            try:
                text = skill_path.read_text(encoding="utf-8")
            except Exception:
                continue
            metadata, body = _parse_frontmatter(text)
            name = metadata.get("name") or skill_path.parent.name
            description = metadata.get("description") or ""
            skill_root = skill_path.parent
            entry = SkillEntry(
                name=name.strip(),
                description=description.strip(),
                root=skill_root,
                path=skill_path,
                body=body.strip(),
                resources=self._scan_resources(skill_root),
            )
            self._skills.append(entry)
            self._index[entry.normalized_name] = entry
            self._index[entry.slug] = entry

    def _scan_resources(self, skill_root: Path) -> tuple[SkillResource, ...]:
        resources: list[SkillResource] = []
        for kind in ("references", "scripts", "assets", "agents"):
            folder = skill_root / kind
            if not folder.exists():
                continue
            for path in sorted(folder.rglob("*")):
                if not path.is_file():
                    continue
                resources.append(
                    SkillResource(
                        kind=kind,
                        relative_path=path.relative_to(skill_root).as_posix(),
                        path=path,
                    )
                )
        return tuple(resources)

    def list_skills(self) -> list[SkillEntry]:
        return sorted(self._skills, key=lambda item: item.name.lower())

    def has_skill(self, name: str) -> bool:
        return self.resolve(name) is not None

    def resolve(self, name: str) -> SkillEntry | None:
        normalized = _normalize_skill_name(name)
        return self._index.get(normalized)

    def required_tools(self, skill_names: Iterable[str]) -> set[str]:
        tools: set[str] = {"current_time", "calculator", "server_health"}
        for skill_name in skill_names:
            entry = self.resolve(skill_name)
            if entry is None:
                continue
            tools.update(_SKILL_TOOL_HINTS.get(entry.normalized_name, ()))
        return tools

    def recommend(
        self,
        request_text: str,
        *,
        route_decision: dict[str, Any] | None = None,
        attachment_count: int = 0,
    ) -> list[str]:
        request = request_text.lower()
        selected: list[str] = []

        def add(name: str) -> None:
            entry = self.resolve(name)
            if entry is None:
                return
            if entry.name not in selected:
                selected.append(entry.name)

        engineering_markers = [
            "code",
            "implement",
            "fix",
            "patch",
            "refactor",
            "agent",
            "system",
            "workflow",
            "tooling",
            "runtime",
            "代码",
            "实现",
            "修复",
            "重构",
            "架构",
            "系统",
            "工作流",
            "工具",
            "运行时",
            "集成",
        ]
        if any(marker in request for marker in engineering_markers) or attachment_count:
            add("Superpowers")
            add("planning-with-files")
            add("coding-standards")
            add("tdd-workflow")

        if any(marker in request for marker in ["skill", "prompt", "agentos", "catalog", "技能", "目录", "内核"]):
            add("skill-creator")

        if any(marker in request for marker in ["frontend", "ui", "ux", "react", "css", "tailwind", "前端", "界面", "交互", "页面", "设计"]):
            add("ui-ux-pro-max+frontend-design")
            add("frontend-patterns")
            add("vercel-react-best-practices")

        if any(marker in request for marker in ["backend", "api", "service", "endpoint", "database", "sql", "后端", "接口", "服务", "数据库", "存储"]):
            add("backend-patterns")

        if "clickhouse" in request or "columnar" in request or "warehouse" in request or "分析" in request or "报表" in request:
            add("clickhouse-io")

        if any(marker in request for marker in ["security", "threat", "auth", "permission", "review", "vulnerability", "安全", "权限", "威胁", "漏洞", "审查"]):
            add("security-review")

        if any(marker in request for marker in ["obsidian", "notes", "knowledge base", "wiki", "markdown", "笔记", "知识库", "文档"]):
            add("obsidian-skills")

        if any(marker in request for marker in ["notebooklm", "research", "sources", "cite", "brief", "compare", "研究", "来源", "引用", "对比"]):
            add("notebooklm-skill")

        if any(marker in request for marker in ["browser", "browse", "web", "page", "site", "html", "scrape", "浏览器", "网页", "抓取"]):
            add("lightpanda-browser")

        if route_decision:
            if bool(route_decision.get("needs_web")):
                add("lightpanda-browser")
            if bool(route_decision.get("needs_files")):
                add("planning-with-files")

        return selected

    def render_compact(self, skill_names: Iterable[str]) -> str:
        entries = [self.resolve(name) for name in skill_names]
        entries = [entry for entry in entries if entry is not None]
        if not entries:
            return "None"
        lines = []
        for entry in entries:
            lines.append(
                f"- {entry.name}: {entry.description} [{entry.resource_summary}]"
            )
        lines.append(
            "Progressive disclosure: open the selected skill's SKILL.md first, then load references/scripts/assets only when they are relevant."
        )
        return "\n".join(lines)

    def render_available(self, selected: Iterable[str] | None = None) -> str:
        selected_set = {
            _normalize_skill_name(name)
            for name in (selected or [])
        }
        entries = self.list_skills()
        if not entries:
            return "No skills found."
        lines = []
        for entry in entries:
            marker = "*" if entry.normalized_name in selected_set else "-"
            lines.append(
                f"{marker} {entry.name}: {entry.description} [{entry.resource_summary}]"
            )
        return "\n".join(lines)

    def preview(self, name: str, *, max_chars: int = 1200) -> str:
        entry = self.resolve(name)
        if entry is None:
            raise KeyError(f"Unknown skill: {name}")
        header_lines = [
            entry.name,
            str(entry.path),
            f"Root: {entry.root}",
            f"Resources: {entry.resource_summary}",
        ]
        if entry.resources:
            preview_resources = "\n".join(
                f"- {resource.relative_path}"
                for resource in entry.resources[:12]
            )
            if len(entry.resources) > 12:
                preview_resources += f"\n- ... ({len(entry.resources) - 12} more)"
            header_lines.append("Bundled resources:\n" + preview_resources)
        header = "\n".join(header_lines)
        body = entry.body.strip()
        if not body:
            return header
        preview = body[:max_chars].rstrip()
        return f"{header}\n\n{preview}"

    def list_resource_paths(self, name: str) -> str:
        entry = self.resolve(name)
        if entry is None:
            raise KeyError(f"Unknown skill: {name}")
        if not entry.resources:
            return f"{entry.name}\nNo bundled resources."
        lines = [entry.name, f"Root: {entry.root}"]
        for resource in entry.resources:
            lines.append(f"- [{resource.kind}] {resource.relative_path}")
        return "\n".join(lines)

    def full_text(self, name: str) -> str:
        entry = self.resolve(name)
        if entry is None:
            raise KeyError(f"Unknown skill: {name}")
        return entry.path.read_text(encoding="utf-8")
