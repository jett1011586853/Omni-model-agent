from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class AttachmentRef:
    kind: str
    source: str
    transport: str


@dataclass(frozen=True)
class AttachmentPayload:
    ref: AttachmentRef
    content_part: dict


def _is_remote_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _to_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_attachment_payloads(
    image_paths: list[str] | None = None,
    image_urls: list[str] | None = None,
) -> list[AttachmentPayload]:
    payloads: list[AttachmentPayload] = []

    for raw_path in image_paths or []:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"Image file not found: {raw_path}")
        payloads.append(
            AttachmentPayload(
                ref=AttachmentRef(kind="image", source=str(path), transport="local_path"),
                content_part={
                    "type": "image_url",
                    "image_url": {"url": _to_data_url(path)},
                },
            )
        )

    for raw_url in image_urls or []:
        if not _is_remote_url(raw_url):
            raise RuntimeError(f"Invalid image URL: {raw_url}")
        payloads.append(
            AttachmentPayload(
                ref=AttachmentRef(kind="image", source=raw_url, transport="remote_url"),
                content_part={
                    "type": "image_url",
                    "image_url": {"url": raw_url},
                },
            )
        )

    return payloads


def build_attachment_payloads_from_refs(
    refs: list[dict[str, Any]] | None,
) -> list[AttachmentPayload]:
    image_paths: list[str] = []
    image_urls: list[str] = []

    for ref in refs or []:
        kind = str(ref.get("kind", ""))
        source = str(ref.get("source", ""))
        transport = str(ref.get("transport", ""))
        if kind != "image" or not source:
            continue
        if transport == "remote_url":
            image_urls.append(source)
        else:
            image_paths.append(source)

    return build_attachment_payloads(image_paths=image_paths, image_urls=image_urls)


def summarize_attachment_refs(refs: list[dict[str, Any]] | None) -> str:
    if not refs:
        return "None"

    lines: list[str] = []
    for index, ref in enumerate(refs, start=1):
        kind = str(ref.get("kind", "attachment")) or "attachment"
        transport = str(ref.get("transport", "unknown")) or "unknown"
        source = str(ref.get("source", "")) or "<missing>"
        lines.append(f"- {index}. {kind} via {transport}: {source}")
    return "\n".join(lines)


def parse_inline_image_command(
    user_input: str,
) -> tuple[str, list[str], list[str]] | None:
    stripped = user_input.strip()
    if not stripped.startswith("/image "):
        return None

    body = stripped[len("/image ") :]
    if "::" not in body:
        raise RuntimeError("Use '/image <path-or-url>[,<path-or-url>...] :: <prompt>'")

    refs_part, prompt = body.split("::", 1)
    refs = [item.strip() for item in refs_part.split(",") if item.strip()]
    if not refs:
        raise RuntimeError("Missing image path or URL")

    image_paths: list[str] = []
    image_urls: list[str] = []
    for ref in refs:
        if _is_remote_url(ref):
            image_urls.append(ref)
        else:
            image_paths.append(ref)

    return prompt.strip(), image_paths, image_urls
