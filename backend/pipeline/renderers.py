"""Renderers: turn blocks into markdown or plain text.

For PDFs we insert a ``<!-- page N -->`` comment and a horizontal rule whenever
the page changes, so downstream consumers can reason about pagination.
"""

from __future__ import annotations

from .schema import Block

_PAGE_COMMENT = "<!-- page {n} -->"


def _escaped(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(blocks: list[Block]) -> str:
    lines: list[str] = []
    current_page: int | None = None

    for block in blocks:
        if block.page is not None and block.page != current_page:
            current_page = block.page
            if lines and lines[-1] not in ("", "---"):
                lines.append("")
            lines.append(_PAGE_COMMENT.format(n=current_page))
            lines.append("")
            lines.append("---")
            lines.append("")

        if block.type == "heading":
            level = block.metadata.get("level", 1)
            level = max(1, min(6, int(level)))
            lines.append(f"{'#' * level} {block.text}")
        elif block.type == "list_item":
            lines.append(f"- {block.text}")
        elif block.type == "table":
            rows: list[list[str]] = block.metadata.get("rows") or []
            if rows:
                header = rows[0]
                lines.append("| " + " | ".join(_escaped(c) for c in header) + " |")
                lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                for row in rows[1:]:
                    lines.append("| " + " | ".join(_escaped(c) for c in row) + " |")
        else:
            lines.append(block.text)

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_text(blocks: list[Block]) -> str:
    lines: list[str] = []
    for block in blocks:
        if block.type == "heading":
            level = block.metadata.get("level", 1)
            prefix = "".join("#" for _ in range(max(1, min(6, int(level)))))
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