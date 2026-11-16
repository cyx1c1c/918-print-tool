"""上传文件存储与「按需转换」缓存。

新流程：上传只落盘原始文件、不转换（省时间）；只有在用户点预览或打印时，
才把该文件转成 PDF，并缓存结果——同一文件转过一次后不再重复转。

Office COM 不可并发，转换统一用 _convert_lock 串行化（预览线程与打印 worker
共享同一把锁，互不冲突）。
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from . import config
from .converters.dispatch import convert_to_pdf
from .printing.pdfutil import page_count


class UploadEntry:
    """一个已上传文件的记录。"""

    def __init__(self, file_id: str, src: Path, filename: str) -> None:
        self.id = file_id
        self.src = Path(src)
        self.filename = filename
        self.pdf: Optional[str] = None       # 转换后的 PDF 路径（按需生成）
        self.pages: Optional[int] = None     # PDF 页数（转换后才知道）
        self.created_at = time.time()


class UploadStore:
    def __init__(self) -> None:
        self._items: dict[str, UploadEntry] = {}
        self._lock = threading.Lock()
        self._convert_lock = threading.Lock()  # 串行化 Office COM 转换

    def register(self, file_id: str, src: Path, filename: str) -> UploadEntry:
        entry = UploadEntry(file_id, src, filename)
        with self._lock:
            self._items[file_id] = entry
        return entry

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def get(self, file_id: str) -> Optional[UploadEntry]:
        with self._lock:
            return self._items.get(file_id)

    def ensure_pdf(self, file_id: str) -> UploadEntry:
        """确保该文件已转成 PDF（已转过则直接返回缓存）。失败抛异常。"""
        entry = self.get(file_id)
        if entry is None:
            raise KeyError(file_id)
        with self._convert_lock:
            if entry.pdf and Path(entry.pdf).exists():
                return entry  # 命中缓存
            pdf = convert_to_pdf(entry.src, config.UPLOAD_DIR)
            entry.pdf = str(pdf)
            entry.pages = page_count(pdf)
        return entry

    def purge(self, file_id: str) -> None:
        """删除该文件的原文件与转换 PDF，并移除记录。"""
        with self._lock:
            entry = self._items.pop(file_id, None)
        if entry is None:
            return
        for p in (entry.src, Path(entry.pdf) if entry.pdf else None):
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass

    def snapshot(self) -> list[UploadEntry]:
        with self._lock:
            return list(self._items.values())


store = UploadStore()
