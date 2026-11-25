"""Check local Markdown links without requiring a built frontend or network."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_SCHEMES = {"http", "https", "mailto", "data", "codex"}


def markdown_files() -> list[Path]:
    files = list(ROOT.glob("*.md"))
    for directory in ("docs", "frontend", "packaging", "tools"):
        files.extend((ROOT / directory).rglob("*.md"))
    excluded = {".git", "build", "dist", "node_modules"}
    return sorted(
        file for file in set(files)
        if not excluded.intersection(file.parts)
    )


class DocumentationLinkTests(unittest.TestCase):
    def test_local_markdown_links_resolve(self) -> None:
        broken: list[str] = []
        for document in markdown_files():
            text = document.read_text(encoding="utf-8-sig")
            for raw_target in LINK.findall(text):
                target = raw_target.strip().strip("<>")
                if not target or target.startswith("#"):
                    continue
                parsed = urlparse(target)
                if parsed.scheme.lower() in EXTERNAL_SCHEMES:
                    continue
                local_path = unquote(parsed.path)
                if not local_path:
                    continue
                base = ROOT if local_path.startswith("/") else document.parent
                candidate = (base / local_path.lstrip("/")).resolve()
                if not candidate.exists():
                    broken.append(
                        f"{document.relative_to(ROOT)} -> {raw_target}"
                    )
        self.assertEqual(broken, [], "\n".join(broken))

    def test_known_legacy_source_paths_are_not_documented(self) -> None:
        stale = (
            "tools/builtin.py",
            "tools/chrome_mcp.py",
            "tools/executor.py",
            "tools/http_transport.py",
            "tools/journal.py",
            "tools/mcp_client.py",
            "tools/registry.py",
            "tools/run_lock.py",
            "tools/sandbox.py",
            "tools/spec.py",
            "src/spiritscout/knowledge/sync.py",
            "tests/process_budget.py",
        )
        problems: list[str] = []
        for document in markdown_files():
            if document.name == "CHANGELOG.md":
                continue
            text = document.read_text(encoding="utf-8-sig")
            for path in stale:
                if re.search(rf"(?<!src/spiritscout/){re.escape(path)}", text):
                    problems.append(f"{document.relative_to(ROOT)} -> {path}")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
