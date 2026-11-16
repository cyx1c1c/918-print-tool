"""后台监控打印机真实状态：把"已送进队列"的任务跟踪到真正打印完成。

SumatraPDF 把任务交给系统打印队列就返回成功了，但"交到队列"≠"真打出来"——
打印机休眠/离线时任务会卡在队列里。本监控读取 Windows 打印队列与打印机状态，
据此把任务标为「已完成」或「等待打印机（可能休眠，请按唤醒键）」。

无法查询时（非 Windows / 驱动不支持）自动退回旧行为：直接判为已完成，不卡住。
"""
from __future__ import annotations

import threading
import time

from .. import config
from ..models import JobStatus
from . import printers
from .jobqueue import manager

# job_id -> {"pages": 已打印页数, "t": 上次有进展时间, "seen": 是否曾见到队列中有任务}
_progress: dict[str, dict] = {}


def _evaluate(job) -> None:
    q = printers.query_printer(job.printer_name)

    # 无法查询 → 退回"送到即完成"，避免任务卡住
    if not q.get("available"):
        manager.set_state(job, JobStatus.DONE, note="已送至打印队列", assumed=True)
        _progress.pop(job.id, None)
        return

    pending = q.get("pending", 0)
    problems = q.get("problems", [])
    pages = q.get("pages_printed", 0)
    active = q.get("active_printing", False)
    now = time.time()
    prog = _progress.setdefault(job.id, {"pages": pages, "t": now, "seen": False})
    if pending > 0:
        prog["seen"] = True

    # 打印机报告了明确问题（离线/休眠/缺纸/出错…）
    if problems:
        manager.set_state(
            job, JobStatus.WAITING,
            note="打印机" + "、".join(problems) + "，请检查（休眠请按唤醒键）",
        )
        return

    # 队列已清空：若之前确实见过任务（或已过短暂的入队窗口）→ 判为完成
    if pending == 0:
        spooled_ok = prog["seen"] or (
            job.printing_since and now - job.printing_since > 8
        )
        if spooled_ok:
            manager.set_state(job, JobStatus.DONE, note="")
            _progress.pop(job.id, None)
        else:
            manager.set_state(job, JobStatus.PRINTING, note="正在送往打印机…")
        return

    # 队列里还有任务：看是否在推进
    if active or pages > prog["pages"]:
        prog["pages"] = pages
        prog["t"] = now
        manager.set_state(job, JobStatus.PRINTING, note="正在打印…")
    elif now - prog["t"] > config.PRINT_STUCK_SECONDS:
        manager.set_state(
            job, JobStatus.WAITING,
            note="打印机较长时间无响应，若在休眠请按唤醒键",
        )
    else:
        manager.set_state(job, JobStatus.PRINTING, note="正在打印…")


def _loop() -> None:
    while True:
        try:
            for job in manager.monitored_jobs():
                try:
                    _evaluate(job)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(config.PRINT_MONITOR_INTERVAL)


def start() -> None:
    """启动后台监控线程（守护线程）。"""
    threading.Thread(target=_loop, name="print-monitor", daemon=True).start()
