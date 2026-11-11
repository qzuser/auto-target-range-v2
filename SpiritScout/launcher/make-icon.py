"""把网页标签页的图标（static/favicon.svg）做成 Windows 的 .ico。

桌面版的窗口图标、任务栏图标、资源管理器图标都取 exe 里嵌的那一个，
所以桌面版和浏览器里看到的必须是同一个标志——不然用户会以为是两个软件。

用法（只在改了 favicon.svg 之后需要跑）：

    python launcher/make-icon.py

做法：不拉浏览器，直接按 SVG 里的几何（圆角方块 + 三条连线 + 四个圆点）
用 Pillow 画，放大 8 倍画完再缩下来，边缘比直接画干净。SVG 里出现这个
小程序读不懂的写法时会直接报错，提醒你同步改这里——不会悄悄画歪。
产物 launcher/icon.ico 要提交进仓库；build-desktop.ps1 直接用，日常构建
不需要 Pillow。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SVG = Path(__file__).resolve().parents[1] / "src" / "spiritscout" / "web" / "static" / "favicon.svg"
ICO = Path(__file__).resolve().parent / "icon.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

BASE = 256          # 实际画布边长（再乘以 SCALE 画，最后缩回来）
SCALE = 8
UNIT = BASE * SCALE / 32.0   # SVG 的 1 个单位对应多少像素


class SvgShapeError(SystemExit):
    """SVG 里出现了超出这个小渲染器能力范围的写法。"""


def _numbers(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]


def _attr(tag: str, name: str) -> str:
    match = re.search(rf'{name}="([^"]+)"', tag)
    if not match:
        raise SvgShapeError(f"图标里少了 {name} 属性：{tag}")
    return match.group(1)


def parse(svg: str) -> dict[str, object]:
    """读 favicon.svg 里用到的几样东西：底色方块、连线、圆点、配色。"""
    rect = re.search(r"<rect[^>]*>", svg)
    if not rect:
        raise SvgShapeError("favicon.svg 里没有 <rect> 底色方块")
    shapes: dict[str, object] = {
        "radius": _numbers(_attr(rect.group(0), "rx"))[0],
        "bg": _attr(rect.group(0), "fill"),
    }

    group = re.search(r"<g[^>]*stroke[^>]*>(.*?)</g>", svg, re.S)
    if not group:
        raise SvgShapeError("favicon.svg 里没有描边的 <g>")
    shapes["stroke"] = _attr(group.group(0)[: group.group(0).index(">")], "stroke")
    shapes["stroke_width"] = _numbers(_attr(group.group(0)[: group.group(0).index(">")], "stroke-width"))[0]

    lines: list[tuple[float, float, float, float]] = []
    for path in re.findall(r'<path\s+d="([^"]+)"', group.group(1)):
        # M x y V y2  → 竖线
        vertical = re.fullmatch(r"M\s*([\d.]+)\s+([\d.]+)\s*V\s*([\d.]+)", path.strip())
        if vertical:
            x, y, y2 = (float(v) for v in vertical.groups())
            lines.append((x, y, x, y2))
            continue
        # M x y l dx dy  → 斜线
        diagonal = re.fullmatch(r"M\s*([\d.]+)\s+([\d.]+)\s*l\s*(-?[\d.]+)\s+(-?[\d.]+)", path.strip())
        if diagonal:
            x, y, dx, dy = (float(v) for v in diagonal.groups())
            lines.append((x, y, x + dx, y + dy))
            continue
        raise SvgShapeError(f"这条 path 这个脚本读不懂，去 make-icon.py 里补一下：{path}")
    if not lines:
        raise SvgShapeError("favicon.svg 的描边组里没有连线")
    shapes["lines"] = lines

    # 圆点常常由外层 <g fill="..."> 统一上色，自己不带 fill，这里兜住
    fills = [f for f in re.findall(r'<g[^>]*fill="([^"]+)"', svg) if f not in ("none", "transparent")]
    default_fill = fills[0] if fills else str(shapes["stroke"])
    dots: list[tuple[float, float, float, str]] = []
    for tag in re.findall(r"<circle[^>]*>", svg):
        cx, cy = (_numbers(_attr(tag, "cx")) or [0.0])[0], (_numbers(_attr(tag, "cy")) or [0.0])[0]
        radius = _numbers(_attr(tag, "r"))[0]
        own = re.search(r'fill="([^"]+)"', tag)
        dots.append((cx, cy, radius, own.group(1) if own else default_fill))
    if not dots:
        raise SvgShapeError("favicon.svg 里没有圆点")
    shapes["dots"] = dots
    return shapes


def draw(shapes: dict[str, object]):
    from PIL import Image, ImageDraw

    canvas = BASE * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    def px(value: float) -> float:
        return float(value) * UNIT

    pen.rounded_rectangle(
        [0, 0, canvas - 1, canvas - 1],
        radius=px(float(shapes["radius"])),
        fill=str(shapes["bg"]),
    )

    width = max(1, round(px(float(shapes["stroke_width"]))))
    for x1, y1, x2, y2 in shapes["lines"]:  # type: ignore[misc]
        pen.line([px(x1), px(y1), px(x2), px(y2)], fill=str(shapes["stroke"]), width=width)
        # 圆头线帽：两端各补一个圆
        for cx, cy in ((x1, y1), (x2, y2)):
            pen.ellipse(
                [px(cx) - width / 2, px(cy) - width / 2, px(cx) + width / 2, px(cy) + width / 2],
                fill=str(shapes["stroke"]),
            )

    for cx, cy, radius, fill in shapes["dots"]:  # type: ignore[misc]
        pen.ellipse(
            [px(cx - radius), px(cy - radius), px(cx + radius), px(cy + radius)],
            fill=str(fill),
        )
    return image


def main() -> int:
    if not SVG.exists():
        raise SystemExit(f"找不到 {SVG}")
    try:
        from PIL import Image
    except ModuleNotFoundError:
        raise SystemExit("需要 Pillow：pip install pillow") from None

    big = draw(parse(SVG.read_text(encoding="utf-8"))).resize((BASE, BASE), Image.LANCZOS)
    frames = [big.resize(size, Image.LANCZOS) for size in SIZES]
    frames[-1].save(ICO, format="ICO", sizes=SIZES)
    saved = Image.open(ICO)
    print(f"写好 {ICO}（{ICO.stat().st_size} 字节，帧 {sorted(saved.info.get('sizes', []))}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
