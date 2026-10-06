"""Renderers: turn blocks into the output formats the API exposes.

Formats
-------
``markdown``  human/agent friendly, with ``<!-- page N -->`` markers
``text``      plain text, with simple heading/list prefixes
``html``      semantic, escaped HTML (safe to embed / preview)
``csv``       one row per block (idx, type, page, method, confidence, text)

For PDFs every renderer inserts a page boundary whenever the page changes, so
downstream consumers can reason about pagination.
"""

from __future__ import annotations

import csv
import html as _html
from io import StringIO

from .schema import Block

_PAGE_COMMENT = "<!-- page {n} -->"


def _clamp_level(level: object) -> int:
    try:
        return max(1, min(6, int(level)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


def _escaped_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _strip(text: str) -> str:
    """Collapse internal newlines so a block stays a single output line."""
    return " ".join(text.split())


def render_markdown(blocks: list[Block]) -> str:
    lines: list[str] = []
    current_page: int | None = None

    for block in blocks:
        if block.page is not None and block.page != current_page:
            current_page = block.page
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(_PAGE_COMMENT.format(n=current_page))
            lines.append("")
            lines.append("---")
            lines.append("")

        if block.type == "heading":
            lines.append(f"{'#' * _clamp_level(block.metadata.get('level', 1))} {_strip(block.text)}")
        elif block.type == "list_item":
            lines.append(f"- {_strip(block.text)}")
        elif block.type == "table":
            rows: list[list[str]] = block.metadata.get("rows") or []
            if rows:
                width = max(len(r) for r in rows)
                header = list(rows[0]) + [""] * (width - len(rows[0]))
                lines.append("| " + " | ".join(_escaped_cell(c) for c in header) + " |")
                lines.append("| " + " | ".join(["---"] * width) + " |")
                for row in rows[1:]:
                    padded = list(row) + [""] * (width - len(row))
                    lines.append("| " + " | ".join(_escaped_cell(c) for c in padded) + " |")
        else:
            lines.append(_strip(block.text))

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_text(blocks: list[Block]) -> str:
    lines: list[str] = []
    for block in blocks:
        if block.type == "heading":
            prefix = "#" * _clamp_level(block.metadata.get("level", 1))
            lines.append(f"{prefix} {block.text}")
        elif block.type == "list_item":
            lines.append(f"* {block.text}")
        elif block.type == "table":
            rows: list[list[str]] = block.metadata.get("rows") or []
            for row in rows:
                lines.append("\t".join(row))
        else:
            lines.append(block.text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(blocks: list[Block]) -> str:
    """Render blocks to semantic, fully-escaped HTML.

    Returns only a fragment (no ``<html>`` wrapper) so it can be embedded.
    Consecutive list items are grouped into a single ``<ul>``.
    """
    parts: list[str] = []
    current_page: int | None = None
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            parts.append("</ul>")
            in_list = False

    for block in blocks:
        if block.page is not None and block.page != current_page:
            close_list()
            current_page = block.page
            parts.append(f'<hr class="page-break" data-page="{current_page}" />')

        if block.type == "heading":
            close_list()
            level = _clamp_level(block.metadata.get("level", 1))
            parts.append(f"<h{level}>{_html.escape(block.text)}</h{level}>")
        elif block.type == "list_item":
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_html.escape(block.text)}</li>")
        elif block.type == "table":
            close_list()
            rows: list[list[str]] = block.metadata.get("rows") or []
            if not rows:
                continue
            width = max(len(r) for r in rows)
            head = list(rows[0]) + [""] * (width - len(rows[0]))
            out = ['<table class="block-table">', "<thead><tr>"]
            out += [f"<th>{_html.escape(c)}</th>" for c in head]
            out.append("</tr></thead><tbody>")
            for row in rows[1:]:
                padded = list(row) + [""] * (width - len(row))
                out.append("<tr>")
                out += [f"<td>{_html.escape(c)}</td>" for c in padded]
                out.append("</tr>")
            out.append("</tbody></table>")
            parts.append("".join(out))
        else:
            close_list()
            parts.append(f"<p>{_html.escape(block.text)}</p>")

    close_list()
    return "\n".join(parts) + "\n"


def render_csv(blocks: list[Block]) -> str:
    """One row per block, useful for spreadsheets / downstream tooling."""
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["idx", "type", "page", "method", "confidence", "text"])
    for idx, block in enumerate(blocks):
        confidence = block.metadata.get("confidence")
        writer.writerow(
            [
                idx,
                block.type,
                block.page if block.page is not None else "",
                block.metadata.get("method", ""),
                f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "",
                block.text,
            ]
        )
    return buffer.getvalue()
