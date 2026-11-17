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
from .printers import (
    cancel_jobs_by_document,
    cancel_spool_jobs,
    default_printer,
    resume_spool_jobs,
)
from .sumatra import print_pdf

# 任务终态：不再接受取消，也不再被状态监控
_TERMINAL = {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELED}


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
            JobStatus.PRINTING, JobStatus.WAITING, JobStatus.WAITING_FLIP,
        }
        with self._lock:
            return {j.file_id for j in self._jobs.values() if j.status in active}

    def monitored_jobs(self) -> list[PrintJob]:
        """仍在打印、等待打印机或等待翻面的任务（供状态监控线程跟踪）。"""
        watch = {JobStatus.PRINTING, JobStatus.WAITING, JobStatus.WAITING_FLIP}
        with self._lock:
            return [j for j in self._jobs.values() if j.status in watch]

    def remove(self, job_id: str) -> Optional[PrintJob]:
        """从任务表移除并返回该任务（供清理模块调用）。"""
        with self._lock:
            return self._jobs.pop(job_id, None)

    def cancel(self, job_id: str) -> tuple[bool, str]:
        """取消任务：排队/转换中直接标记；已送打印机则尽量撤销队列作业。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False, "任务不存在"
            if job.status in _TERMINAL:
                return False, "任务已结束，无法取消"

            job.cancel_requested = True
            status = job.status
            printer = job.printer_name or job.options.printer or default_printer()
            job_ids = list(job.spool_job_ids)

        # 还没开始打印：worker 会在下一个检查点跳过
        if status in (JobStatus.QUEUED, JobStatus.CONVERTING):
            self.set_state(job, JobStatus.CANCELED, note="已取消")
            return True, "已取消"

        canceled, errors = cancel_spool_jobs(printer, job_ids)
        if canceled == 0:
            # 可能还没来得及记录作业 id，按文档名兜底找一次
            by_doc, doc_errors = cancel_jobs_by_document(printer, job.file_id)
            canceled += by_doc
            errors.extend(doc_errors)

        if canceled > 0:
            note = "已取消"
            if errors:
                note = "已取消部分任务；若打印机仍在出纸，请按打印机面板的取消键"
            self.set_state(job, JobStatus.CANCELED, note=note)
            return True, note

        # 队列里找不到：页面可能已经进入打印机内存，只能提示手动取消
        note = "已取消；若打印机仍在出纸，请按打印机面板的取消键（页面可能已进入打印机内存）"
        self.set_state(job, JobStatus.CANCELED, note=note)
        return True, note

    def resume_duplex(self, job_id: str) -> tuple[bool, str]:
        """手动双面：翻面后恢复被驱动暂停的打印作业。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False, "任务不存在"
            if not job.resumable:
                return False, "任务当前不需要继续"
            printer = job.printer_name or job.options.printer or default_printer()
            job_ids = list(job.spool_job_ids)
            file_id = job.file_id

        resumed, _errors = resume_spool_jobs(printer, job_ids, file_id)
        if resumed > 0:
            self.set_state(job, JobStatus.PRINTING, note="已继续打印，确认打印中…")
            return True, "已继续打印"
        return False, "没有找到等待继续的打印任务，请到打印站电脑点「继续」"

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
            # 用户已请求取消时，不再让监控/worker 把状态改回打印中
            if job.cancel_requested and status not in _TERMINAL:
                status = JobStatus.CANCELED
                note = note or "已取消"
            job.status = status
            if error:
                job.error = error
            if note is not None:
                job.note = note
            if status in _TERMINAL:
                job.finished_at = time.time()
        # 终态触发延迟清理（放在锁外，避免持锁启动 Timer）
        if status in _TERMINAL:
            self._schedule_post_print_purge(job.file_id, assumed=assumed)

    def _schedule_post_print_purge(self, file_id: str, assumed: bool = False) -> None:
        """打印/转换任务终态后，延迟 N 秒清理该文件。

        - confirmed done（monitor 确认队列已空）：POST_PRINT_PURGE_SECONDS 后清理
        - assumed done（无法查询打印机，假设完成）：跳过快速清理，
          交给兜底的 RETENTION_MINUTES 过期清理，避免打印机还在打就删文件
        - FAILED：文件没在打印，安全地快速清理
        - CANCELED：已取消，按失败同样快速清理
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

        timer = threading.Timer(delay, _do)
        timer.daemon = True
        timer.start()

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
                if job.cancel_requested:
                    self.set_state(job, JobStatus.CANCELED, note="已取消")
                else:
                    self.set_state(job, JobStatus.FAILED, f"处理异常：{e}")
            finally:
                self._queue.task_done()

    def _process(self, job: PrintJob) -> None:
        if job.cancel_requested:
            self.set_state(job, JobStatus.CANCELED, note="已取消")
            return

        # 1) 按需转换为 PDF（已转过则命中缓存，不重复转）
        self.set_state(job, JobStatus.CONVERTING)
        try:
            entry = store.ensure_pdf(job.file_id)
        except KeyError:
            if job.cancel_requested:
                self.set_state(job, JobStatus.CANCELED, note="已取消")
            else:
                self.set_state(job, JobStatus.FAILED, error="文件不存在或已过期")
            return
        except Exception as e:  # noqa: BLE001
            if job.cancel_requested:
                self.set_state(job, JobStatus.CANCELED, note="已取消")
            else:
                self.set_state(job, JobStatus.FAILED, error=f"转换失败：{e}")
            return

        if job.cancel_requested:
            self.set_state(job, JobStatus.CANCELED, note="已取消")
            return

        # 2) 送入打印队列（SumatraPDF 返回即表示已交给系统打印队列）
        job.printer_name = job.options.printer or default_printer()
        self.set_state(job, JobStatus.PRINTING)
        if job.cancel_requested:
            return

        def _record_jobs(ids: list[int]) -> None:
            """记录本次打印新增的 Windows 队列作业 id，供取消使用。"""
            with self._lock:
                for jid in ids:
                    if jid not in job.spool_job_ids:
                        job.spool_job_ids.append(jid)

        try:
            print_pdf(
                Path(entry.pdf),
                job.options,
                on_jobs_submitted=_record_jobs,
                should_cancel=lambda: job.cancel_requested,
            )
        except Exception as e:  # noqa: BLE001
            if job.cancel_requested:
                cancel_spool_jobs(job.printer_name, job.spool_job_ids)
                self.set_state(job, JobStatus.CANCELED, note="已取消")
            else:
                self.set_state(job, JobStatus.FAILED, error=f"打印失败：{e}")
            return

        if job.cancel_requested:
            # 取消请求可能在 SumatraPDF 执行期间到达，补一次队列撤销
            cancel_spool_jobs(job.printer_name, job.spool_job_ids)
            self.set_state(job, JobStatus.CANCELED, note="已取消")
            return

        # 已送入打印队列；是否真正打印出来交给 monitor 跟踪后判定完成/等待
        job.printing_since = time.time()
        self.set_state(job, JobStatus.PRINTING, note="已送到打印机，确认打印中…")


# 全局单例
manager = JobManager()
