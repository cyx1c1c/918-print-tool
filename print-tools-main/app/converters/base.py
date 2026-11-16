"""转换器通用工具：异常、PDF 校验、纯文本转 PDF。"""
from __future__ import annotations

from pathlib import Path


class ConversionError(Exception):
    """文件转 PDF 失败时抛出。"""


def looks_like_pdf(path: Path) -> bool:
    """粗略校验是否为合法 PDF（检查文件头 %PDF）。"""
    try:
        with open(path, "rb") as f:
            return f.read(5).startswith(b"%PDF")
    except OSError:
        return False


def text_to_pdf(src: Path, out_pdf: Path) -> Path:
    """把纯文本 .txt 转成 PDF。

    使用 reportlab 内置的 CID 中文字体 STSong-Light，无需外部字体文件即可
    正确渲染中文，避免乱码。
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    font_name = "STSong-Light"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    except Exception:
        font_name = "Helvetica"  # 极端兜底（中文可能丢失）

    # 读文本，宽容编码
    raw = src.read_bytes()
    for enc in ("utf-8", "gbk", "gb18030", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    c = canvas.Canvas(str(out_pdf), pagesize=A4)
    width, height = A4
    margin = 18 * mm
    font_size = 11
    leading = font_size * 1.5
    max_chars = int((width - 2 * margin) / (font_size * 0.6))  # 粗略每行字数

    x = margin
    y = height - margin
    c.setFont(font_name, font_size)

    def wrap(line: str):
        if not line:
            return [""]
        return [line[i : i + max_chars] for i in range(0, len(line), max_chars)]

    for raw_line in text.splitlines() or [""]:
        for chunk in wrap(raw_line.rstrip("\r")):
            if y < margin:
                c.showPage()
                c.setFont(font_name, font_size)
                y = height - margin
            c.drawString(x, y, chunk)
            y -= leading

    c.save()
    if not out_pdf.exists():
        raise ConversionError(f"文本转 PDF 失败：{src.name}")
    return out_pdf
