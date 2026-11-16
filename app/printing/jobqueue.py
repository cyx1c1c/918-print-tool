"""打印任务队列：单 worker 线程串行处理「转换 PDF → 打印」。

串行设计的好处：
- Office COM 不可并发，串行天然安全。
- 多人同时提交时按提交顺序逐个打印，不会乱。
"""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Optional

from ..models import JobStatus, PrintJob
from ..store import store
from .printers import default_printer
from .sumatra import print_pdf


class JobManager:
    """管理所有打印任务的生命周期。"""

    def __init__(self) -> None:
        self._jobs: dict[str, PrintJob] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None

    # ---- 对外接口 ----
    def start(self) -> None:
        """启动后台 worker 线程（幂等）。"""
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._run, name="print-worker", daemon=True
        )
        self._worker.start()

    def submit(self, job: PrintJob) -> None:
        """登记任务并入队。"""
        with self._lock:
            self._jobs[job.id] = job
        self._queue.put(job.id)

    def get(self, job_id: str) -> Optional[PrintJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def all_jobs(self) -> list[PrintJob]:
        with self._lock:
            return sorted(
                self._jobs.values(), key=lambda j: j.created_at, reverse=True
            )

    def active_file_ids(self) -> set[str]:
        """仍在排队/转换/打印/等待中的任务所引用的文件 id（供清理模块避让）。"""
        active = {
            JobStatus.QUEUED, JobStatus.CONVERTING,
            JobStatus.PRINTING, JobStatus.WAITING,
        }
        with self._lock:
            return {j.file_id for j in self._jobs.values() if j.status in active}

    def monitored_jobs(self) -> list[PrintJob]:
        """正在打印/等待打印机的任务（供状态监控线程跟踪）。"""
        watch = {JobStatus.PRINTING, JobStatus.WAITING}
        with self._lock:
            return [j for j in self._jobs.values() if j.status in watch]

    def remove(self, job_id: str) -> Optional[PrintJob]:
        """从任务表移除并返回该任务（供清理模块调用）。"""
        with self._lock:
            return self._jobs.pop(job_id, None)

    # ---- 内部 worker ----
    def set_state(
        self, job: PrintJob, status: JobStatus, error: str = "", note: Optional[str] = None,
        assumed: bool = False,
    ) -> None:
        """更新任务状态。

        Args:
            assumed: True 表示"假完成"（无法查询打印机，假设已打完）。
                     此时跳过 30 秒快速清理，交给兜底的 30 分钟过期清理，
                     避免打印机还在慢慢打时文件就被删了。
        """
        with self._lock:
            job.status = status
            if error:
                job.error = error
            if note is not None:
                job.note = note
            if status in (JobStatus.DONE, JobStatus.FAILED):
                job.finished_at = time.time()
        # 终态触发延迟清理（放在锁外，避免持锁启动 Timer）
        if status in (JobStatus.DONE, JobStatus.FAILED):
            self._schedule_post_print_purge(job.file_id, assumed=assumed)

    def _schedule_post_print_purge(self, file_id: str, assumed: bool = False) -> None:
        """打印/转换任务终态后，延迟 N 秒清理该文件。

        - confirmed done（monitor 确认队列已空）：POST_PRINT_PURGE_SECONDS 后清理
        - assumed done（无法查询打印机，假设完成）：跳过快速清理，
          交给兜底的 RETENTION_MINUTES 过期清理，避免打印机还在打就删文件
        - FAILED：文件没在打印，安全地快速清理
        """
        if assumed:
            return

        from .. import config

        delay = config.POST_PRINT_PURGE_SECONDS

        def _do() -> None:
            # 清理线程被 daemon 杀掉时，Timer 的 _do 不会跑到；
            # 就算跑到了也要再确认没有活跃任务，避免多任务共用同一文件时误删
            if file_id in self.active_file_ids():
                return
            store.purge(file_id)

        threading.Timer(delay, _do, daemon=True).start()

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.get(job_id)
            if job is None:
                self._queue.task_done()
                continue
            try:
                self._process(job)
            except Exception as e:  # noqa: BLE001  worker 不能崩
                self._set(job, JobStatus.FAILED, f"处理异常：{e}")
            finally:
                self._queue.task_done()

    def _process(self, job: PrintJob) -> None:
        # 1) 按需转换为 PDF（已转过则命中缓存，不重复转）
        self.set_state(job, JobStatus.CONVERTING)
        try:
            entry = store.ensure_pdf(job.file_id)
        except KeyError:
            self.set_state(job, JobStatus.FAILED, error="文件不存在或已过期")
            return
        except Exception as e:  # noqa: BLE001
            self.set_state(job, JobStatus.FAILED, error=f"转换失败：{e}")
            return

        # 2) 送入打印队列（SumatraPDF 返回即表示已交给系统打印队列）
        job.printer_name = job.options.printer or default_printer()
        self.set_state(job, JobStatus.PRINTING)
        try:
            print_pdf(Path(entry.pdf), job.options)
        except Exception as e:  # noqa: BLE001
            self.set_state(job, JobStatus.FAILED, error=f"打印失败：{e}")
            return

        # 已送入打印队列；是否真正打印出来交给 monitor 跟踪后判定完成/等待
        job.printing_since = time.time()
        self.set_state(job, JobStatus.PRINTING, note="已送到打印机，确认打印中…")


# 全局单例
manager = JobManager()
