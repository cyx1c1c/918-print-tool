"""打印任务的数据结构与状态定义。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    """任务生命周期状态。"""

    QUEUED = "queued"        # 排队中
    CONVERTING = "converting"  # 转换中
    PRINTING = "printing"    # 打印中
    WAITING = "waiting"      # 已送到打印机，等待其真正打印（可能休眠/离线）
    WAITING_FLIP = "waiting_flip"  # 手动双面：等待用户翻面后继续
    DONE = "done"            # 完成
    FAILED = "failed"        # 失败
    CANCELED = "canceled"    # 已取消

    @property
    def label(self) -> str:
        """中文展示文案。"""
        return {
            "queued": "排队中",
            "converting": "转换中",
            "printing": "打印中",
            "waiting": "等待打印机",
            "waiting_flip": "等待翻面",
            "done": "已完成",
            "failed": "失败",
            "canceled": "已取消",
        }[self.value]


# 颜色模式
COLOR = "color"
MONOCHROME = "monochrome"

# 双面模式
SIMPLEX = "simplex"          # 单面
DUPLEX_LONG = "duplexlong"   # 双面长边翻页
DUPLEX_SHORT = "duplexshort"  # 双面短边翻页


@dataclass
class PrintOptions:
    """一次打印任务的配置项。"""

    printer: str = ""                 # 打印机名称（空=系统默认）
    color: str = MONOCHROME           # color / monochrome
    copies: int = 1                   # 份数
    page_range: str = ""              # 页码范围，如 "1-5,8"；空=全部
    duplex: str = SIMPLEX             # simplex / duplexlong / duplexshort
    paper: str = ""                   # 纸张，如 "A4"/"A3"；空=驱动默认
    pages_per_sheet: int = 1          # 每张纸多页：1/2/4/6/9/16
    scaling: str = "shrink"           # noscale / shrink / fit（默认适当缩小：
    #                                   超过纸张可打印区的页面缩小贴合，正常页不动）

    def normalized(self) -> "PrintOptions":
        """做一些基础的范围约束，避免非法值。"""
        self.copies = max(1, min(int(self.copies or 1), 99))
        if self.color not in (COLOR, MONOCHROME):
            self.color = MONOCHROME
        if self.duplex not in (SIMPLEX, DUPLEX_LONG, DUPLEX_SHORT):
            self.duplex = SIMPLEX
        if self.pages_per_sheet not in (1, 2, 4, 6, 9, 16):
            self.pages_per_sheet = 1
        if self.scaling not in ("fit", "shrink", "noscale"):
            self.scaling = "shrink"
        return self


@dataclass
class PrintJob:
    """一个打印任务的完整记录（保存在内存任务表中）。"""

    id: str
    file_id: str                       # 关联的上传文件 id（转换/打印时按需取 PDF）
    filename: str                      # 原始文件名（展示用）
    options: PrintOptions
    status: JobStatus = JobStatus.QUEUED
    error: str = ""                    # 失败原因
    note: str = ""                     # 状态提示（如"打印机休眠，请按唤醒键"）
    printer_name: str = ""             # 实际打印机名（供状态监控）
    printing_since: Optional[float] = None  # 送入打印队列的时间
    spool_job_ids: list[int] = field(default_factory=list)  # Windows 队列作业 id
    cancel_requested: bool = False     # 用户是否已请求取消
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None  # 完成/失败时间，用于清理倒计时

    @property
    def cancellable(self) -> bool:
        """任务是否还能取消（终态或取消中的任务不再显示取消按钮）。"""
        return not self.cancel_requested and self.status in (
            JobStatus.QUEUED,
            JobStatus.CONVERTING,
            JobStatus.PRINTING,
            JobStatus.WAITING,
            JobStatus.WAITING_FLIP,
        )

    @property
    def resumable(self) -> bool:
        """手动双面任务是否正在等待用户点「继续打印」。"""
        return self.status == JobStatus.WAITING_FLIP

    def to_public(self) -> dict:
        """转成前端可消费的精简字典。"""
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status.value,
            "status_label": self.status.label,
            "error": self.error,
            "note": self.note,
            "copies": self.options.copies,
            "created_at": self.created_at,
            "cancellable": self.cancellable,
            "resumable": self.resumable,
        }
