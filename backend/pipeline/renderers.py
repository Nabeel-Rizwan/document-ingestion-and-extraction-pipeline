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

# `csv` builds RFC-4180 output for the CSV renderer.
import csv
# `_html` escapes text so renderers emit safe, embeddable HTML.
import html as _html
# `StringIO` gives csv.writer an in-memory file-like buffer.
from io import StringIO

# The Block model each renderer consumes.
from .schema import Block

# Markdown template for a page boundary comment (n replaced by the page number).
_PAGE_COMMENT = "<!-- page {n} -->"


# Normalise a heading level to a valid HTML h1..h6 integer.
def _clamp_level(level: object) -> int:
    try:
        # Coerce to int and clamp into the 1..6 range HTML headings support.
        return max(1, min(6, int(level)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        # Non-numeric/None levels fall back to the lowest valid heading level.
        return 1


# Escape pipe/newline characters so a cell stays valid inside a Markdown table.
def _escaped_cell(text: str) -> str:
    # Replace "|" with "\|" (escapes table delimiters) and newlines with spaces.
    return text.replace("|", "\\|").replace("\n", " ")


def _strip(text: str) -> str:
    """Collapse internal newlines so a block stays a single output line."""
    # split() on whitespace then rejoin, collapsing runs of whitespace to one space.
    return " ".join(text.split())


# Render all blocks as Markdown flowing text with horizontal-rule page breaks.
def render_markdown(blocks: list[Block]) -> str:
    # The output lines assembled so far.
    lines: list[str] = []
    # Track the last page emitted so we only insert a break on page changes.
    current_page: int | None = None

    for block in blocks:
        # Detect a page transition (only meaningful for page-aware formats like PDF).
        if block.page is not None and block.page != current_page:
            current_page = block.page
            # Insert a blank separator before the page marker unless at the very start.
            if lines and lines[-1] != "":
                lines.append("")
            # Emit the HTML-comment page marker for downstream pagination tooling.
            lines.append(_PAGE_COMMENT.format(n=current_page))
            lines.append("")
            # Horizontal rule visually separates the new page in Markdown.
            lines.append("---")
            lines.append("")

        # Heading blocks become N hash marks followed by the stripped text.
        if block.type == "heading":
            lines.append(f"{'#' * _clamp_level(block.metadata.get('level', 1))} {_strip(block.text)}")
        elif block.type == "list_item":
            # List items become Markdown unordered-list bullets.
            lines.append(f"- {_strip(block.text)}")
        elif block.type == "table":
            # Pull the raw cell grid from the block metadata (defaults to empty).
            rows: list[list[str]] = block.metadata.get("rows") or []
            if rows:
                # Table width is the widest row; used for header padding and separators.
                width = max(len(r) for r in rows)
                # Pad the header row to `width` so its cells line up with the data.
                header = list(rows[0]) + [""] * (width - len(rows[0]))
                # Render the header row as pipe-delimited cells.
                lines.append("| " + " | ".join(_escaped_cell(c) for c in header) + " |")
                # Render the Markdown delimiter row under the header.
                lines.append("| " + " | ".join(["---"] * width) + " |")
                for row in rows[1:]:
                    # Pad every data row to the same width as the header.
                    padded = list(row) + [""] * (width - len(row))
                    # Render the padded data row as pipe-delimited cells.
                    lines.append("| " + " | ".join(_escaped_cell(c) for c in padded) + " |")
        else:
            # Any other block type falls back to plain body text.
            lines.append(_strip(block.text))

        # Blank line after every block keeps the Markdown readable.
        lines.append("")

    # Join lines, strip trailing whitespace, and guarantee a single trailing newline.
    return "\n".join(lines).rstrip() + "\n"


# Render all blocks as plain text with simple heading/list prefixes.
def render_text(blocks: list[Block]) -> str:
    # The output lines assembled so far.
    lines: list[str] = []
    for block in blocks:
        if block.type == "heading":
            # Prefix the heading with its level expressed as hash marks.
            prefix = "#" * _clamp_level(block.metadata.get("level", 1))
            lines.append(f"{prefix} {block.text}")
        elif block.type == "list_item":
            # Prefix list items with an asterisk.
            lines.append(f"* {block.text}")
        elif block.type == "table":
            # Pull the raw cell grid (rows) from the block metadata.
            rows: list[list[str]] = block.metadata.get("rows") or []
            for row in rows:
                # Emit each table row as tab-separated cells.
                lines.append("\t".join(row))
        else:
            # Any other block renders as its raw text.
            lines.append(block.text)
        # Blank line after every block keeps plain output readable.
        lines.append("")
    # Join lines, strip trailing whitespace, and add one trailing newline.
    return "\n".join(lines).rstrip() + "\n"


def render_html(blocks: list[Block]) -> str:
    """Render blocks to semantic, fully-escaped HTML.

    Returns only a fragment (no ``<html>`` wrapper) so it can be embedded.
    Consecutive list items are grouped into a single ``<ul>``.
    """
    # HTML fragment pieces to be joined at the end.
    parts: list[str] = []
    # Track the last page emitted so we only insert a break on page changes.
    current_page: int | None = None
    # Track whether we are inside an open <ul> so we can close it correctly.
    in_list = False

    def close_list() -> None:
        # Bind to the enclosing `in_list` so close_list can mutate it.
        nonlocal in_list
        if in_list:
            # Close the currently open <ul> and clear the open-list flag.
            parts.append("</ul>")
            in_list = False

    for block in blocks:
        # Detect a page change; page-aware formats get an <hr> page-break marker.
        if block.page is not None and block.page != current_page:
            # A list must not span across a page boundary, so close it first.
            close_list()
            current_page = block.page
            parts.append(f'<hr class="page-break" data-page="{current_page}" />')

        if block.type == "heading":
            # Heading block: close any open list, then emit <hN> with escaped text.
            close_list()
            level = _clamp_level(block.metadata.get("level", 1))
            parts.append(f"<h{level}>{_html.escape(block.text)}</h{level}>")
        elif block.type == "list_item":
            # Open a new <ul> on the first item; subsequent items append <li>s.
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_html.escape(block.text)}</li>")
        elif block.type == "table":
            # Table block: close any open list before emitting the table markup.
            close_list()
            rows: list[list[str]] = block.metadata.get("rows") or []
            if not rows:
                # A table with no rows renders nothing; skip to the next block.
                continue
            # Table width is the widest row, used to pad the header row.
            width = max(len(r) for r in rows)
            # Pad the header row to `width` so its cells line up with the data.
            head = list(rows[0]) + [""] * (width - len(rows[0]))
            # Fresh list to assemble the full <table> element piece by piece.
            out = ['<table class="block-table">', "<thead><tr>"]
            # Emit one escaped <th> per header cell.
            out += [f"<th>{_html.escape(c)}</th>" for c in head]
            out.append("</tr></thead><tbody>")
            for row in rows[1:]:
                # Pad every data row to the same width as the header.
                padded = list(row) + [""] * (width - len(row))
                out.append("<tr>")
                # Emit one escaped <td> per padded data cell.
                out += [f"<td>{_html.escape(c)}</td>" for c in padded]
                out.append("</tr>")
            out.append("</tbody></table>")
            # Append the assembled table as a single part.
            parts.append("".join(out))
        else:
            # Any other block becomes a <p> paragraph; close any open list first.
            close_list()
            parts.append(f"<p>{_html.escape(block.text)}</p>")

    # Make sure any trailing open <ul> is closed before returning.
    close_list()
    # Join the fragment lines and end with a single trailing newline.
    return "\n".join(parts) + "\n"


def render_csv(blocks: list[Block]) -> str:
    """One row per block, useful for spreadsheets / downstream tooling."""
    # In-memory buffer to capture the CSV writer's output.
    buffer = StringIO()
    # Writer emits "\n" line terminators (CSV spec) regardless of platform.
    writer = csv.writer(buffer, lineterminator="\n")
    # Header row describing each column of the spooled CSV.
    writer.writerow(["idx", "type", "page", "method", "confidence", "text"])
    for idx, block in enumerate(blocks):
        # Confidence is stored in metadata; may be absent for some block types.
        confidence = block.metadata.get("confidence")
        writer.writerow(
            [
                idx,
                block.type,
                # Blank string stands in for blocks with no page number.
                block.page if block.page is not None else "",
                block.metadata.get("method", ""),
                # Format numerics to two decimals; blanks hold non-numeric confidence.
                f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "",
                block.text,
            ]
        )
    # Return the complete CSV text written into the buffer.
    return buffer.getvalue()
