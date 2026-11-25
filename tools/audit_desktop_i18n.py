"""Report static Chinese UI strings that are not covered by the English catalog."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src/spiritscout/web/static/js/i18n.en.js"
DESKTOP_CATALOG = ROOT / "desktop/src/main/resources/i18n/desktop-en.json"
SOURCE_DIR = ROOT / "desktop/src/main/kotlin/com/spiritscout/desktop"
BUILD_DIR = ROOT / "build"

STRING_RE = re.compile(r'"([^"\r\n]*[\u4e00-\u9fff][^"\r\n]*)"')
CATALOG_RE = re.compile(r'"((?:\\.|[^"\\])*)"\s*:\s*"((?:\\.|[^"\\])*)"')


def main() -> int:
    catalog = {
        match.group(1): match.group(2)
        for match in CATALOG_RE.finditer(CATALOG.read_text(encoding="utf-8"))
    }
    desktop_catalog = json.loads(DESKTOP_CATALOG.read_text(encoding="utf-8"))
    catalog.update(desktop_catalog)
    values: set[str] = set()
    for path in SOURCE_DIR.rglob("*.kt"):
        values.update(STRING_RE.findall(path.read_text(encoding="utf-8")))
    missing = sorted(
        value
        for value in values
        if "$" not in value and value not in catalog
    )
    print(f"ui_unique={len(values)} missing={len(missing)}")
    for value in missing:
        print(value)
    translated_chinese = sorted(
        f"{value} -> {catalog[value]}"
        for value in values
        if value in catalog and re.search(r"[\u4e00-\u9fff]", catalog[value])
    )
    BUILD_DIR.mkdir(exist_ok=True)
    (BUILD_DIR / "desktop-i18n-missing-all.txt").write_text(
        "\n".join(missing) + ("\n" if missing else ""),
        encoding="utf-8",
    )
    (BUILD_DIR / "desktop-i18n-audit.txt").write_text(
        "\n".join(
            [
                f"ui_unique={len(values)} missing={len(missing)}",
                *missing,
                *([f"translated_values_with_chinese={len(translated_chinese)}"] if translated_chinese else []),
                *translated_chinese,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    if translated_chinese:
        print(f"translated_values_with_chinese={len(translated_chinese)}")
        for value in translated_chinese:
            print(value)
    return 1 if missing or translated_chinese else 0


if __name__ == "__main__":
    raise SystemExit(main())
