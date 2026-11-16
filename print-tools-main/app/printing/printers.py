"""打印机枚举：列出系统打印机、获取默认打印机。

仅在 Windows（pywin32）可用；其它平台返回空列表，便于在非 Windows 上
也能启动服务做界面调试（只是无法真正打印）。
"""
from __future__ import annotations


def list_printers() -> list[str]:
    """返回本机所有已安装打印机的名称列表。"""
    try:
        import win32print
    except ImportError:
        return []

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        printers = win32print.EnumPrinters(flags, None, 1)
    except Exception:
        return []
    # level=1 时每项为 (flags, description, name, comment)
    return [p[2] for p in printers]


def default_printer() -> str:
    """返回系统默认打印机名称；取不到返回空串。"""
    try:
        import win32print
    except ImportError:
        return ""
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return ""


# 打印机状态旗标 -> 中文（仅取关心的几种）
_STATUS_FLAGS = (
    ("PRINTER_STATUS_OFFLINE", "离线"),
    ("PRINTER_STATUS_POWER_SAVE", "休眠"),
    ("PRINTER_STATUS_PAPER_OUT", "缺纸"),
    ("PRINTER_STATUS_PAPER_JAM", "卡纸"),
    ("PRINTER_STATUS_DOOR_OPEN", "机盖打开"),
    ("PRINTER_STATUS_NO_TONER", "无墨粉/硒鼓"),
    ("PRINTER_STATUS_ERROR", "出错"),
    ("PRINTER_STATUS_NOT_AVAILABLE", "不可用"),
    ("PRINTER_STATUS_PAUSED", "已暂停"),
)

# 作业状态位
_JOB_PRINTED = 0x00000080
_JOB_DELETED = 0x00000100
_JOB_PRINTING = 0x00000010


def query_printer(name: str) -> dict:
    """查询打印机真实状态与队列。

    返回 {available, pending, pages_printed, active_printing, problems[], status}。
    非 Windows 或查询失败时返回 {"available": False}，调用方据此退回旧行为。
    """
    try:
        import win32print
    except ImportError:
        return {"available": False}

    try:
        if not name:
            name = win32print.GetDefaultPrinter()
        h = win32print.OpenPrinter(name)
        try:
            info = win32print.GetPrinter(h, 2)
            status = info.get("Status", 0) if isinstance(info, dict) else 0
            try:
                jobs = win32print.EnumJobs(h, 0, 256, 1)
            except Exception:
                jobs = []
        finally:
            win32print.ClosePrinter(h)
    except Exception:
        return {"available": False}

    pending = pages = 0
    active = False
    for j in jobs:
        st = j.get("Status", 0)
        if st & (_JOB_PRINTED | _JOB_DELETED):
            continue
        pending += 1
        pages += int(j.get("PagesPrinted", 0) or 0)
        if st & _JOB_PRINTING:
            active = True

    problems = []
    for cname, label in _STATUS_FLAGS:
        bit = getattr(win32print, cname, 0)
        if bit and (status & bit):
            problems.append(label)

    return {
        "available": True,
        "pending": pending,
        "pages_printed": pages,
        "active_printing": active,
        "problems": problems,
        "status": status,
    }
