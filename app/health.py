"""服务健康自检：供维护者在任意电脑上快速定位问题。

默认只做轻量检查，不启动 Office；访问 `/api/health?deep=1` 时会额外尝试
启动 Word / Excel / PowerPoint，验证 COM 是否真的可用。
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import config
from .models import JobStatus
from .printing import printers
from .printing.jobqueue import manager

_STARTED_AT = time.time()
_STUCK_SECONDS = 600  # 任务超过 10 分钟仍未结束，标记为长时间运行

_OFFICE_APPS = (
    ("Word", "Word.Application"),
    ("Excel", "Excel.Application"),
    ("PowerPoint", "PowerPoint.Application"),
)

# 健康自检只关心实体打印机；这些虚拟打印机不作为“打印机在线”的依据
_VIRTUAL_PRINTER_HINTS = (
    "microsoft print to pdf",
    "microsoft xps document writer",
    "onenote",
    "fax",
    "导出为wps pdf",
    "adobe pdf",
    "cutepdf",
    "pdfcreator",
    "pdf creator",
)


def _is_virtual_printer(name: str) -> bool:
    lower = str(name or "").lower()
    return any(hint in lower for hint in _VIRTUAL_PRINTER_HINTS)


def _office_registered(prog_id: str) -> bool:
    """检查 Office ProgID 是否在注册表中注册（不启动 Office）。"""
    try:
        import winreg
    except ImportError:
        return False

    paths = (
        (winreg.HKEY_CLASSES_ROOT, prog_id),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Classes\{prog_id}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Classes\{prog_id}"),
    )
    for root, path in paths:
        try:
            key = winreg.OpenKey(root, path)
            key.Close()
            return True
        except OSError:
            continue
    return False


def _office_info(deep: bool) -> dict:
    try:
        has_pywin32 = importlib.util.find_spec("win32com") is not None
    except Exception:  # noqa: BLE001
        has_pywin32 = False

    apps = {label: _office_registered(prog_id) for label, prog_id in _OFFICE_APPS}
    started: dict[str, str] = {}

    if deep and has_pywin32:
        from .converters.office import _com, _dispatch

        for label, prog_id in _OFFICE_APPS:
            if not apps.get(label):
                started[label] = "未注册"
                continue
            try:
                with _com():
                    app = _dispatch(prog_id)
                    try:
                        if label != "PowerPoint":
                            try:
                                app.Visible = False
                            except Exception:  # noqa: BLE001
                                pass
                        started[label] = "可启动"
                    finally:
                        try:
                            app.Quit()
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as e:  # noqa: BLE001
                started[label] = f"启动失败：{e}"

    ok = has_pywin32 and all(apps.values())
    if deep and started:
        ok = ok and all(value == "可启动" for value in started.values())

    missing = [label for label, present in apps.items() if not present]
    if not has_pywin32:
        detail = "未安装 pywin32，无法使用 Office COM"
    elif missing:
        detail = "未注册：" + " / ".join(missing)
    else:
        detail = "Word / Excel / PowerPoint COM 已注册"
    if deep:
        detail += "；深度检测：" + "，".join(f"{k}={v}" for k, v in started.items())

    return {
        "ok": ok,
        "pywin32": has_pywin32,
        "apps": apps,
        "deep": bool(deep),
        "started": started,
        "detail": detail,
    }


def _print_engine_info() -> dict:
    path = Path(config.SUMATRA_PATH)
    exists = path.is_file()
    size = 0
    if exists:
        try:
            size = path.stat().st_size
        except OSError:
            exists = False
    return {
        "ok": exists,
        "path": str(path),
        "size_bytes": size,
        "detail": "SumatraPDF 可用" if exists else "找不到 SumatraPDF",
    }


def _uploads_info() -> dict:
    path = config.UPLOAD_DIR
    exists = path.is_dir()
    writable = False
    error = ""

    if exists:
        probe = path / f".health_probe_{os.getpid()}_{time.time_ns()}"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            writable = True
        except OSError as e:
            error = str(e)
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass

    free_mb = None
    try:
        free_mb = round(shutil.disk_usage(path).free / 1024 / 1024)
    except OSError:
        pass

    ok = exists and writable
    if not exists:
        detail = "上传目录不存在"
    elif not writable:
        detail = f"上传目录不可写：{error}"
    else:
        detail = "上传目录可写"

    return {
        "ok": ok,
        "path": str(path),
        "free_mb": free_mb,
        "detail": detail,
    }


def _printer_info() -> dict:
    all_names = printers.list_printers()
    names = [name for name in all_names if not _is_virtual_printer(name)]
    ignored = len(all_names) - len(names)

    items: list[dict] = []
    for name in names:
        q = printers.query_printer(name)
        items.append(
            {
                "name": name,
                "available": bool(q.get("available")),
                "pending": int(q.get("pending", 0) or 0),
                "problems": list(q.get("problems", []) or []),
            }
        )

    if not items:
        detail = "未检测到实体打印机"
        if ignored:
            detail += f"（已忽略 {ignored} 个虚拟打印机）"
    elif not any(item["available"] for item in items):
        detail = "所有打印机当前不可用"
    elif any(not item["available"] for item in items):
        detail = "部分打印机不可用"
    else:
        detail = "打印机在线"

    return {
        "ok": bool(items) and any(item["available"] for item in items),
        "items": items,
        "ignored_virtual": ignored,
        "detail": detail,
    }


def _jobs_info() -> dict:
    active_states = {
        JobStatus.QUEUED,
        JobStatus.CONVERTING,
        JobStatus.PRINTING,
        JobStatus.WAITING,
        JobStatus.WAITING_FLIP,
    }
    now = time.time()
    jobs = manager.all_jobs()
    active = [job for job in jobs if job.status in active_states]
    waiting_flip = sum(1 for job in active if job.status == JobStatus.WAITING_FLIP)
    long_running = [
        job
        for job in active
        if job.status in (JobStatus.PRINTING, JobStatus.WAITING)
        and job.printing_since
        and now - job.printing_since > _STUCK_SECONDS
    ]

    if long_running:
        detail = f"有 {len(long_running)} 个任务运行超过 10 分钟"
    elif active:
        detail = f"{len(active)} 个任务处理中"
    else:
        detail = "队列空闲"

    return {
        "ok": not long_running,
        "active": len(active),
        "waiting_flip": waiting_flip,
        "long_running": len(long_running),
        "long_running_jobs": [
            {
                "id": job.id,
                "filename": job.filename,
                "status": job.status.value,
                "seconds": int(now - (job.printing_since or job.created_at)),
            }
            for job in long_running
        ],
        "detail": detail,
    }


def snapshot(deep: bool = False) -> dict:
    """返回当前服务健康快照；deep=True 时额外启动 Office 组件。"""
    is_windows = platform.system() == "Windows"
    windows = {
        "ok": is_windows,
        "detail": platform.platform(),
    }
    engine = _print_engine_info()
    office = _office_info(deep)
    uploads = _uploads_info()
    printer_info = _printer_info()
    jobs = _jobs_info()

    fails: list[str] = []
    warnings: list[str] = []

    if not is_windows:
        fails.append("当前不是 Windows，无法真正打印")
    if not engine["ok"]:
        fails.append(engine["detail"])
    if not uploads["ok"]:
        fails.append(uploads["detail"])
    if not printer_info["items"]:
        fails.append(printer_info["detail"])
    elif not printer_info["ok"]:
        fails.append("所有打印机当前不可用")
    else:
        for item in printer_info["items"]:
            if not item["available"]:
                warnings.append(f"{item['name']} 不可用")
            elif item["problems"]:
                warnings.append(f"{item['name']}：" + "、".join(item["problems"]))

    if not office["ok"]:
        warnings.append(office["detail"])
    if jobs["long_running"]:
        warnings.append(jobs["detail"])

    status = "fail" if fails else ("warn" if warnings else "ok")

    return {
        "ok": status == "ok",
        "status": status,
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "deep": bool(deep),
        "service": {
            "name": "918实验室网页打印系统",
            "uptime_seconds": int(time.time() - _STARTED_AT),
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "checks": {
            "windows": windows,
            "print_engine": engine,
            "office_com": office,
            "uploads": uploads,
            "printers": printer_info,
            "queue": jobs,
        },
        "config": {
            "auth_enabled": bool(config.AUTH_ENABLED),
            "port": config.PORT,
            "retention_minutes": config.RETENTION_MINUTES,
            "max_upload_mb": config.MAX_UPLOAD_BYTES // 1024 // 1024,
        },
        "fails": fails,
        "warnings": warnings,
    }
