"""定时清理：删除超过保留期的上传文件，回收磁盘、保护隐私。

新模型下文件由 store 管理（上传即登记，按需转换缓存 PDF）：
- 上传超过保留期的文件整体删除（含原文件与缓存 PDF），但避开仍在排队/打印中的。
- 终态打印任务记录超过保留期后移除。
- 兜底再扫一遍上传目录里的孤儿文件。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import config
from .models import JobStatus
from .printing.jobqueue import manager
from .store import store


def _sweep_once() -> None:
    now = time.time()
    retention = config.RETENTION_MINUTES * 60
    active = manager.active_file_ids()

    # 1) 按上传文件清理（避开仍在处理中的文件）
    for entry in store.snapshot():
        if entry.id in active:
            continue
        if now - entry.created_at >= retention:
            store.purge(entry.id)

    # 2) 清理终态且超期的任务记录
    for job in manager.all_jobs():
        if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED) and job.finished_at:
            if now - job.finished_at >= retention:
                manager.remove(job.id)

    # 3) 兜底：删除上传目录里 mtime 远超保留期的孤儿文件
    try:
        for f in config.UPLOAD_DIR.iterdir():
            if f.is_file() and now - f.stat().st_mtime >= retention * 2:
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass


def _loop() -> None:
    while True:
        try:
            _sweep_once()
        except Exception:
            pass
        time.sleep(config.CLEANUP_INTERVAL_SECONDS)


def start() -> None:
    """启动后台清理线程（守护线程）。"""
    threading.Thread(target=_loop, name="cleanup", daemon=True).start()
