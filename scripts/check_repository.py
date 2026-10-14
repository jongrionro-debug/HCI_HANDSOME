#!/usr/bin/env python3
"""Run lightweight, dependency-free checks for this document-first repository.

The checks intentionally cover repository wiring rather than product behavior:
local Markdown links, generated HTML/source pairs, and workflow templates.
External links are reported only as external and are not fetched.

Markdown link validation covers inline links outside fenced code blocks. It does
not parse reference-style links, raw HTML links, or links embedded in code.
Anchor checks cover GitHub-style Markdown heading slugs; anchors in HTML or
other local file types are not interpreted.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


# These are local or sensitive paths named by this repository's .gitignore and
# workspace layout. Compare them to paths relative to the repository root so a
# parent directory such as ~/.codex does not accidentally exclude the checkout.
EXCLUDED_DIRS = {
    ".agents",
    ".aws",
    ".codex",
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "private",
    "secrets",
    "venv",
}
EXCLUDED_PATH_PREFIXES = {
    ("data", "private"),
    ("data", "raw"),
}
ISSUE_FORMS = {
    "feature_request.yml": (
        "Background",
        "Goal",
        "Requirements",
        "Acceptance Criteria",
        "Out of Scope",
        "References",
    ),
    "bug_report.yml": (
        "Problem Description",
        "Steps to Reproduce",
        "Expected Behavior",
        "Actual Behavior",
        "Environment",
        "Acceptance Criteria",
    ),
}
INLINE_LINK_RE = re.compile(
    r"(?<!!)\[[^\]]+\]\(\s*(?P<target><[^>]*>|[^\s)]+)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
HTML_SOURCE_RE = re.compile(
    r'<textarea\b[^>]*\bid=["\']am-source["\'][^>]*>(.*?)</textarea>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Problem:
    path: Path
    message: str
    line: int | None = None

    def render(self, root: Path) -> str:
        try:
            shown = self.path.relative_to(root)
        except ValueError:
            shown = self.path
        location = f":{self.line}" if self.line else ""
        return f"- {shown}{location}: {self.message}"


def iter_files(root: Path, suffix: str) -> list[Path]:
    """Return repository files with *suffix*, excluding generated environments."""

    files: list[Path] = []
    for path in root.rglob(f"*{suffix}"):
        relative_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in relative_parts):
            continue
        if any(relative_parts[: len(prefix)] == prefix for prefix in EXCLUDED_PATH_PREFIXES):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def lines_without_fences(text: str) -> list[tuple[int, str]]:
    """Yield source lines outside fenced code blocks with their original numbers."""

    result: list[tuple[int, str]] = []
    fence_char: str | None = None
    fence_length = 0
    for number, line in enumerate(text.splitlines(), start=1):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            char = marker[0]
            if fence_char is None:
                fence_char, fence_length = char, len(marker)
            elif char == fence_char and len(marker) >= fence_length:
                fence_char, fence_length = None, 0
            continue
        if fence_char is None:
            result.append((number, line))
    return result


def github_heading_anchors(markdown: str) -> set[str]:
    """Build the practical subset of GitHub heading slugs used by this repository."""

    anchors: set[str] = set()
    used: dict[str, int] = {}
    for _, line in lines_without_fences(markdown):
        match = HEADING_RE.match(line)
        if not match:
            continue
        heading = html.unescape(match.group(2))
        heading = re.sub(r"`([^`]*)`", r"\1", heading)
        heading = re.sub(r"!\[[^]]*\]\([^)]*\)", "", heading)
        heading = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", heading)
        heading = re.sub(r"<[^>]+>", "", heading)
        # Keep composed Unicode characters (especially Hangul) intact. GitHub's
        # heading slugs preserve these characters instead of decomposing them.
        normalized = unicodedata.normalize("NFC", heading)
        slug = re.sub(r"[^\w\s-]", "", normalized.casefold(), flags=re.UNICODE)
        slug = re.sub(r"\s+", "-", slug).strip("-")
        if not slug:
            continue
        occurrence = used.get(slug, 0)
        used[slug] = occurrence + 1
        anchors.add(slug if occurrence == 0 else f"{slug}-{occurrence}")
    return anchors


def check_markdown_links(root: Path, problems: list[Problem]) -> int:
    checked = 0
    for source in iter_files(root, ".md"):
        text = source.read_text(encoding="utf-8")
        for line_number, line in lines_without_fences(text):
            for match in INLINE_LINK_RE.finditer(line):
                checked += 1
                target = match.group("target").strip()
                if target.startswith("<") and target.endswith(">"):
                    target = target[1:-1]
                target = html.unescape(target)
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith("//"):
                    # Network verification is intentionally outside this checker.
                    continue

                raw_path = unquote(parsed.path)
                fragment = unquote(parsed.fragment)
                destination = (source.parent / raw_path).resolve() if raw_path else source
                try:
                    destination.relative_to(root)
                except ValueError:
                    problems.append(
                        Problem(
                            source,
                            f"local link resolves outside the repository: {target}",
                            line_number,
                        )
                    )
                    continue
                if not destination.exists():
                    problems.append(
                        Problem(source, f"local link target does not exist: {target}", line_number)
                    )
                    continue
                if fragment and destination.suffix.casefold() == ".md":
                    anchors = github_heading_anchors(destination.read_text(encoding="utf-8"))
                    if fragment.casefold() not in anchors:
                        problems.append(
                            Problem(
                                source,
                                f"anchor '#{fragment}' was not found in {destination.relative_to(root)}",
                                line_number,
                            )
                        )
    return checked


def first_difference(left: str, right: str) -> tuple[int, int] | None:
    """Return (line, column) for the first differing character, if any."""

    left_lines = left.splitlines(keepends=True)
    right_lines = right.splitlines(keepends=True)
    for line_number, (left_line, right_line) in enumerate(
        zip(left_lines, right_lines), start=1
    ):
        if left_line != right_line:
            for column, (left_char, right_char) in enumerate(
                zip(left_line, right_line), start=1
            ):
                if left_char != right_char:
                    return line_number, column
            return line_number, min(len(left_line), len(right_line)) + 1
    if len(left_lines) != len(right_lines):
        return min(len(left_lines), len(right_lines)) + 1, 1
    return None


def check_html_sources(root: Path, problems: list[Problem]) -> int:
    """Compare generated HTML's am-source textarea with its sibling Markdown source."""

    pairs = 0
    for html_path in iter_files(root, ".html"):
        matches = list(HTML_SOURCE_RE.finditer(html_path.read_text(encoding="utf-8")))
        if not matches:
            continue
        source_path = html_path.with_suffix(".md")
        if not source_path.is_file():
            problems.append(
                Problem(html_path, "embedded am-source has no sibling Markdown source")
            )
            continue
        if len(matches) != 1:
            problems.append(
                Problem(html_path, f"expected one am-source textarea, found {len(matches)}")
            )
            continue
        pairs += 1
        embedded = html.unescape(matches[0].group(1))
        markdown = source_path.read_text(encoding="utf-8")
        if embedded != markdown:
            difference = first_difference(embedded, markdown)
            detail = "embedded Markdown differs from sibling source"
            if difference:
                detail += f" (first difference at source line {difference[0]}, column {difference[1]})"
            problems.append(Problem(html_path, detail))
    return pairs


def has_required_validation_block(text: str, label: str) -> bool:
    """Check that a form label is followed by a required validation in its item."""

    label_match = re.search(rf"^\s+label:\s*{re.escape(label)}\s*$", text, re.MULTILINE)
    if not label_match:
        return False
    next_item = re.search(r"^\s+- type:\s+", text[label_match.end() :], re.MULTILINE)
    item_text = text[label_match.end() : label_match.end() + next_item.start()] if next_item else text[label_match.end() :]
    return bool(re.search(r"^\s+validations:\s*$", item_text, re.MULTILINE)) and bool(
        re.search(r"^\s+required:\s+true\s*$", item_text, re.MULTILINE)
    )


def check_templates(root: Path, problems: list[Problem]) -> tuple[int, int]:
    forms_checked = 0
    for filename, labels in ISSUE_FORMS.items():
        path = root / ".github" / "ISSUE_TEMPLATE" / filename
        if not path.is_file():
            problems.append(Problem(path, "required Issue Form is missing"))
            continue
        forms_checked += 1
        text = path.read_text(encoding="utf-8")
        for key in ("name:", "description:", "body:"):
            if not re.search(rf"^\s*{re.escape(key)}", text, re.MULTILINE):
                problems.append(Problem(path, f"Issue Form is missing top-level {key[:-1]}"))
        found_labels = re.findall(r"^\s+label:\s*(.+?)\s*$", text, re.MULTILINE)
        for label in labels:
            if label not in found_labels:
                problems.append(Problem(path, f"Issue Form is missing '{label}' section"))
            elif not has_required_validation_block(text, label):
                problems.append(Problem(path, f"'{label}' must be required"))

    pr_path = root / ".github" / "pull_request_template.md"
    # PR guidance is optional; neither headings nor review checkboxes are
    # required. If a reusable template includes checkboxes, keep them unchecked
    # so it does not imply verification before a contributor has done the work.
    if pr_path.is_file():
        text = pr_path.read_text(encoding="utf-8")
        if re.search(r"^\s*-\s*\[[xX]\]", text, re.MULTILINE):
            problems.append(Problem(pr_path, "Pull Request template contains a pre-checked checkbox"))

    return forms_checked, int(pr_path.is_file())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(f"repository root does not exist: {root}", file=sys.stderr)
        return 2

    problems: list[Problem] = []
    markdown_links = check_markdown_links(root, problems)
    html_pairs = check_html_sources(root, problems)
    forms_checked, pr_checked = check_templates(root, problems)

    if problems:
        print("repository-checks: FAILED")
        for problem in problems:
            print(problem.render(root))
        print(
            f"Checked {markdown_links} local/external Markdown links, "
            f"{html_pairs} HTML source pair(s), and {forms_checked} Issue Form(s)."
        )
        return 1

    print(
        "repository-checks: PASS — "
        f"{markdown_links} Markdown links, {html_pairs} HTML source pair(s), "
        f"{forms_checked} Issue Form(s), and {pr_checked} PR template checked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
