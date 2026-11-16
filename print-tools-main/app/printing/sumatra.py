"""调用 SumatraPDF 命令行打印 PDF。

SumatraPDF 的 -print-settings 支持：页码范围、color/monochrome、双面、缩放。
它**不支持**份数与 N-up，因此：
  - 份数：循环调用打印命令 N 次（每次打印一整份，天然 collate）。
  - 每张多页(N-up)：打印前用 pypdf 拼版（见 nup.py）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import config
from ..models import PrintOptions
from . import nup, pdfutil

# Windows 下隐藏弹出的控制台窗口
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PRINT_TIMEOUT = 180  # 单次打印命令超时（秒）


class PrintError(Exception):
    """打印失败。"""


def _build_settings(opts: PrintOptions, page_range: str) -> str:
    """拼装 -print-settings 字符串。"""
    tokens: list[str] = []
    if page_range.strip():
        tokens.append(page_range.strip())
    tokens.append(opts.color)        # color / monochrome
    tokens.append(opts.duplex)       # simplex / duplexlong / duplexshort
    tokens.append(opts.scaling)      # fit / shrink / noscale
    if opts.paper.strip():
        # 纸张尺寸是否生效取决于 SumatraPDF 版本与打印机驱动，未知则被忽略
        tokens.append(f"paper={opts.paper.strip()}")
    return ",".join(tokens)


def _prepare_pdf(pdf_path: Path, opts: PrintOptions) -> tuple[Path, str, list[Path]]:
    """根据选项预处理 PDF（页码抽取 / N-up / 方向归一）。

    返回 (要打印的PDF, 交给SumatraPDF的页码范围, 需要清理的临时文件列表)。
    N-up 模式下页码范围在拼版前已处理，故返回空串。
    """
    temps: list[Path] = []
    work = pdf_path
    page_range = opts.page_range

    if opts.pages_per_sheet > 1:
        # 若指定了页码范围，先抽取这些页，再拼版
        if opts.page_range.strip():
            total = pdfutil.page_count(pdf_path)
            pages = pdfutil.parse_page_range(opts.page_range, total)
            if pages:
                subset = pdf_path.with_name(pdf_path.stem + "_sub.pdf")
                pdfutil.extract_pages(pdf_path, subset, pages)
                temps.append(subset)
                work = subset
        nup_out = pdf_path.with_name(pdf_path.stem + "_nup.pdf")
        try:
            nup.make_nup(work, nup_out, opts.pages_per_sheet)
            temps.append(nup_out)
            work, page_range = nup_out, ""  # 拼版后打印全部页
        except Exception:
            work, page_range = pdf_path, opts.page_range  # 拼版失败则回退

    # 方向归一：把横版页旋转成竖版，匹配竖版纸张（解决横版打成竖版的问题）
    rot_out = work.with_name(work.stem + "_rot.pdf")
    try:
        if pdfutil.normalize_orientation(work, rot_out):
            temps.append(rot_out)
            work = rot_out
    except Exception:
        pass  # 旋转失败则用原样，不影响打印

    return work, page_range, temps


def print_pdf(pdf_path: Path, opts: PrintOptions) -> None:
    """按选项打印 PDF；失败抛 PrintError。"""
    pdf_path = Path(pdf_path)
    opts = opts.normalized()

    if not config.SUMATRA_PATH.exists():
        raise PrintError(
            f"找不到打印引擎 SumatraPDF：{config.SUMATRA_PATH}。"
            "请确认 vendor/SumatraPDF.exe 存在（或设置 SUMATRA_PATH）。"
        )

    work_pdf, page_range, temps = _prepare_pdf(pdf_path, opts)
    settings = _build_settings(opts, page_range)

    # 打印机参数：空=系统默认打印机
    if opts.printer.strip():
        target = ["-print-to", opts.printer.strip()]
    else:
        target = ["-print-to-default"]

    cmd = (
        [str(config.SUMATRA_PATH)]
        + target
        + ["-print-settings", settings, "-silent", str(work_pdf)]
    )

    try:
        for i in range(opts.copies):
            proc = subprocess.run(
                cmd,
                timeout=_PRINT_TIMEOUT,
                creationflags=_NO_WINDOW,
                capture_output=True,
            )
            if proc.returncode != 0:
                msg = (proc.stderr or b"").decode("utf-8", "ignore").strip()
                raise PrintError(
                    f"SumatraPDF 打印失败（第 {i + 1} 份，返回码 "
                    f"{proc.returncode}）：{msg or '未知错误'}"
                )
    except subprocess.TimeoutExpired as e:
        raise PrintError(f"打印超时（>{_PRINT_TIMEOUT}s）：{pdf_path.name}") from e
    except FileNotFoundError as e:
        raise PrintError(f"无法启动 SumatraPDF：{e}") from e
    finally:
        for t in temps:
            try:
                t.unlink(missing_ok=True)
            except Exception:
                pass
