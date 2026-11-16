"""通过 COM 自动化调用本机正版 Office，把 Word/Excel/PPT 转成 PDF。

设计要点：
- 用 DispatchEx 启动**独立的** Office 进程实例，不干扰用户当前正在用的 Office。
- 应用实例不可见、禁用弹窗；用完务必 Close + Quit 释放，避免残留进程。
- 每次调用自行 CoInitialize / CoUninitialize（pywin32 引用计数，可安全嵌套）。
- 仅在 Windows 且已安装对应 Office 组件时可用；否则抛 ConversionError。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from .base import ConversionError

# Office 导出常量
_WD_FORMAT_PDF = 17       # Word: wdFormatPDF
_XL_TYPE_PDF = 0          # Excel: xlTypePDF
_PP_SAVE_AS_PDF = 32      # PowerPoint: ppSaveAsPDF
_WD_ALERTS_NONE = 0       # Word: wdAlertsNone


@contextmanager
def _com():
    """线程内 COM 初始化的上下文管理器。"""
    try:
        import pythoncom
    except ImportError as e:  # 非 Windows
        raise ConversionError(
            "当前环境没有 pywin32/Office COM，无法转换 Office 文档"
            "（请在装有 Office 的 Windows 上运行）。"
        ) from e
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def _dispatch(prog_id: str):
    """启动独立 Office 进程实例。"""
    import win32com.client

    try:
        return win32com.client.DispatchEx(prog_id)
    except Exception as e:  # noqa: BLE001
        raise ConversionError(
            f"无法启动 {prog_id}（请确认已安装对应 Office 组件）：{e}"
        ) from e


def word_to_pdf(src: Path, out_pdf: Path) -> Path:
    """Word(.doc/.docx/.rtf) → PDF。"""
    src, out_pdf = src.resolve(), out_pdf.resolve()
    with _com():
        app = _dispatch("Word.Application")
        doc = None
        try:
            app.Visible = False
            try:
                app.DisplayAlerts = _WD_ALERTS_NONE
            except Exception:
                pass
            doc = app.Documents.Open(str(src), ReadOnly=True)
            doc.SaveAs(str(out_pdf), FileFormat=_WD_FORMAT_PDF)
        except Exception as e:  # noqa: BLE001
            raise ConversionError(f"Word 转 PDF 失败：{src.name}（{e}）") from e
        finally:
            if doc is not None:
                try:
                    doc.Close(False)
                except Exception:
                    pass
            try:
                app.Quit()
            except Exception:
                pass
    return _ensure(out_pdf, src)


def excel_to_pdf(src: Path, out_pdf: Path) -> Path:
    """Excel(.xls/.xlsx/.csv) → PDF。"""
    src, out_pdf = src.resolve(), out_pdf.resolve()
    with _com():
        app = _dispatch("Excel.Application")
        wb = None
        try:
            app.Visible = False
            app.DisplayAlerts = False
            wb = app.Workbooks.Open(str(src), ReadOnly=True)
            wb.ExportAsFixedFormat(_XL_TYPE_PDF, str(out_pdf))
        except Exception as e:  # noqa: BLE001
            raise ConversionError(f"Excel 转 PDF 失败：{src.name}（{e}）") from e
        finally:
            if wb is not None:
                try:
                    wb.Close(False)
                except Exception:
                    pass
            try:
                app.Quit()
            except Exception:
                pass
    return _ensure(out_pdf, src)


def ppt_to_pdf(src: Path, out_pdf: Path) -> Path:
    """PowerPoint(.ppt/.pptx) → PDF。

    注意：PowerPoint.Application 不允许设 Visible=False（会报错），
    改为打开演示文稿时不显示窗口（WithWindow=False）。
    """
    src, out_pdf = src.resolve(), out_pdf.resolve()
    with _com():
        app = _dispatch("PowerPoint.Application")
        pres = None
        try:
            pres = app.Presentations.Open(
                str(src), ReadOnly=True, WithWindow=False
            )
            pres.SaveAs(str(out_pdf), _PP_SAVE_AS_PDF)
        except Exception as e:  # noqa: BLE001
            raise ConversionError(f"PPT 转 PDF 失败：{src.name}（{e}）") from e
        finally:
            if pres is not None:
                try:
                    pres.Close()
                except Exception:
                    pass
            try:
                app.Quit()
            except Exception:
                pass
    return _ensure(out_pdf, src)


def _ensure(out_pdf: Path, src: Path) -> Path:
    if not out_pdf.exists() or out_pdf.stat().st_size == 0:
        raise ConversionError(f"转换后未生成有效 PDF：{src.name}")
    return out_pdf
