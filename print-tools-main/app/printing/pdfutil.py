"""PDF 小工具：页数统计、页码范围解析、按范围抽取页面。"""
from __future__ import annotations

from pathlib import Path


def page_count(pdf: Path) -> int:
    """返回 PDF 总页数；失败返回 0。"""
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf)).pages)
    except Exception:
        return 0


def parse_page_range(spec: str, total: int) -> list[int]:
    """把 "1-5,8,10-" 解析为 1-based 页码列表（去重、有序、过滤越界）。

    空串表示全部页。"a-" 表示从 a 到末尾。
    """
    spec = (spec or "").strip()
    if not spec:
        return list(range(1, total + 1))

    result: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            start = int(a) if a.strip().isdigit() else 1
            end = int(b) if b.strip().isdigit() else total
        else:
            if not part.isdigit():
                continue
            start = end = int(part)
        if start > end:
            start, end = end, start
        for p in range(start, end + 1):
            if 1 <= p <= total:
                result.add(p)
    return sorted(result)


def extract_pages(src: Path, out: Path, pages_1based: list[int]) -> Path:
    """按 1-based 页码列表抽取页面，写到 out。"""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(src))
    writer = PdfWriter()
    total = len(reader.pages)
    for p in pages_1based:
        if 1 <= p <= total:
            writer.add_page(reader.pages[p - 1])
    with open(out, "wb") as f:
        writer.write(f)
    return out


def _is_landscape(page) -> bool:
    """该页的【有效】方向是否为横版（考虑已有的 /Rotate）。"""
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)
    rot = int(page.get("/Rotate", 0) or 0) % 360
    if rot in (90, 270):
        w, h = h, w
    return w > h


def normalize_orientation(src: Path, out: Path) -> bool:
    """把所有【横版】页旋转 90° 变成竖版尺寸，匹配竖版纸张打印。

    逐页判断：有横版页才写出 out 并返回 True；全是竖版则不动、返回 False
    （调用方据此跳过，避免无谓开销）。90° 旋转不会让内容上下颠倒。
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(src))
    writer = PdfWriter()
    changed = False
    for page in reader.pages:
        if _is_landscape(page):
            page.rotate(90)  # 顺时针 90°：横版内容转到竖版纸上
            changed = True
        writer.add_page(page)
    if not changed:
        return False
    with open(out, "wb") as f:
        writer.write(f)
    return True
