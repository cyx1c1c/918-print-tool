"""每张纸多页（N-up）拼版。

SumatraPDF 命令行不支持 N-up，改为打印前用 pypdf 把多页缩放排到一页，
与打印机驱动无关，效果稳定。支持 2/4/6/9/16。
"""
from __future__ import annotations

from pathlib import Path

# n -> (行数, 列数)，按阅读顺序从左上到右下排列
_LAYOUT = {
    2: (1, 2),
    4: (2, 2),
    6: (2, 3),
    9: (3, 3),
    16: (4, 4),
}


def make_nup(src_pdf: Path, out_pdf: Path, n: int) -> Path:
    """把 src_pdf 每 n 页拼到一页，输出到 out_pdf。

    失败时抛异常，由调用方决定是否回退到原 PDF。
    """
    if n not in _LAYOUT:
        raise ValueError(f"不支持的每张页数：{n}")

    from pypdf import PdfReader, PdfWriter, Transformation

    rows, cols = _LAYOUT[n]
    reader = PdfReader(str(src_pdf))
    writer = PdfWriter()

    pages = reader.pages
    if not pages:
        raise ValueError("源 PDF 没有页面")

    # 输出页尺寸取源第一页尺寸
    first = pages[0]
    out_w = float(first.mediabox.width)
    out_h = float(first.mediabox.height)
    cell_w = out_w / cols
    cell_h = out_h / rows

    dest = None
    for idx, page in enumerate(pages):
        pos = idx % n
        if pos == 0:
            dest = writer.add_blank_page(width=out_w, height=out_h)

        r = pos // cols
        c = pos % cols
        sw = float(page.mediabox.width)
        sh = float(page.mediabox.height)
        if sw <= 0 or sh <= 0:
            continue
        scale = min(cell_w / sw, cell_h / sh)
        tx = c * cell_w + (cell_w - sw * scale) / 2
        # PDF 坐标原点在左下；第 r 行（从上数）对应的 cell 左下 y
        ty = out_h - (r + 1) * cell_h + (cell_h - sh * scale) / 2
        transform = Transformation().scale(scale).translate(tx, ty)
        dest.merge_transformed_page(page, transform)

    with open(out_pdf, "wb") as f:
        writer.write(f)
    return out_pdf
