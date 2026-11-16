"""图片转 PDF。

关键：统一把图片铺到一张 **A4 页面**上（按比例缩放、居中），让图片页 = 纸张。
否则 img2pdf 默认会按「图片像素 ÷ DPI」生成页面，手机照片/截图往往得到远大于
A4 的巨型页，配上「原始大小(noscale)」打印时只截取左上角一小块 → 打出来是白纸。
统一成 A4 后，无论哪种缩放设置都能像普通文档一样正常打印。

优先用 img2pdf（无损嵌入，不二次压缩）；遇到带透明/调色板/CMYK 等 img2pdf
不接受的图，用 Pillow 压平为 RGB 再交给 img2pdf。
"""
from __future__ import annotations

import io
from pathlib import Path

from .base import ConversionError

# A4 纸张尺寸（pt）：210mm × 297mm
A4_PT = (595.28, 841.89)


def image_to_pdf(src: Path, out_pdf: Path) -> Path:
    import img2pdf

    # 把图片按比例缩放居中放到 A4 页面
    layout = img2pdf.get_layout_fun(A4_PT)

    # 1) 直接用 img2pdf
    try:
        data = img2pdf.convert(str(src), layout_fun=layout)
        with open(out_pdf, "wb") as f:
            f.write(data)
        if out_pdf.exists() and out_pdf.stat().st_size > 0:
            return out_pdf
    except Exception:
        pass  # 落到 Pillow 兜底

    # 2) Pillow 兜底：压平为 RGB（白底）后再交给 img2pdf，仍铺到 A4
    try:
        from PIL import Image

        img = Image.open(src)
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=92)
        data = img2pdf.convert(buf.getvalue(), layout_fun=layout)
        with open(out_pdf, "wb") as f:
            f.write(data)
    except Exception as e:  # noqa: BLE001
        raise ConversionError(f"图片转 PDF 失败：{src.name}（{e}）") from e

    if not out_pdf.exists() or out_pdf.stat().st_size == 0:
        raise ConversionError(f"图片转 PDF 失败：{src.name}")
    return out_pdf
