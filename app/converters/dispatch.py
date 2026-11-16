"""统一转换入口：按扩展名把任意支持的文件转成 PDF。

对外只暴露 convert_to_pdf(src, out_dir) -> Path。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import config
from .base import ConversionError, looks_like_pdf, text_to_pdf
from .image import image_to_pdf


def convert_to_pdf(src: Path, out_dir: Path) -> Path:
    """把 src 转换成 PDF，输出到 out_dir，返回生成的 PDF 路径。

    PDF：原样校验后复制；图片/文本：本地库转换；Office：COM 转换。
    不支持的扩展名抛 ConversionError。
    """
    src = Path(src)
    ext = src.suffix.lower()
    out_pdf = out_dir / (src.stem + ".pdf")

    if ext in config.PDF_EXTS:
        if not looks_like_pdf(src):
            raise ConversionError(f"文件不是有效的 PDF：{src.name}")
        # 已是 PDF，复制一份作为统一的预览/打印产物
        if src.resolve() != out_pdf.resolve():
            shutil.copyfile(src, out_pdf)
        return out_pdf

    if ext in config.IMAGE_EXTS:
        return image_to_pdf(src, out_pdf)

    if ext in config.TEXT_EXTS:
        return text_to_pdf(src, out_pdf)

    if ext in config.WORD_EXTS:
        from .office import word_to_pdf

        return word_to_pdf(src, out_pdf)

    if ext in config.EXCEL_EXTS:
        from .office import excel_to_pdf

        return excel_to_pdf(src, out_pdf)

    if ext in config.PPT_EXTS:
        from .office import ppt_to_pdf

        return ppt_to_pdf(src, out_pdf)

    raise ConversionError(f"暂不支持的文件类型：{ext or '（无扩展名）'}")
