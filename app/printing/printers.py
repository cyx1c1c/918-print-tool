"""打印机枚举：列出系统打印机、获取默认打印机。

仅在 Windows（pywin32）可用；其它平台返回空列表，便于在非 Windows 上
也能启动服务做界面调试（只是无法真正打印）。
"""
from __future__ import annotations


# 同一台设备在 Windows 里可能出现多个驱动名称，合并成一个对用户显示的名称。
# 打印/监控/取消时再解析成当前实际安装的原始名称。
_PRINTER_ALIASES = (
    (
        "HP Color LaserJet Pro MFP M176",
        (
            "HP Color LaserJet Pro MFP M176 PCLmS",
            "Hewlett-Packard HP Color LaserJet Pro MFP M176n",
        ),
    ),
)


def _norm(name: str) -> str:
    """打印机名比较用：忽略大小写和多余空格。"""
    return " ".join(str(name or "").strip().lower().split())


def _alias_for(name: str):
    """按显示名或任一驱动名查找别名组。"""
    target = _norm(name)
    if not target:
        return None
    for display, raws in _PRINTER_ALIASES:
        if target == _norm(display) or any(target == _norm(raw) for raw in raws):
            return display, raws
    return None


def display_name(name: str) -> str:
    """把原始驱动名称转换成对用户友好的显示名。"""
    alias = _alias_for(name)
    return alias[0] if alias else name


def _raw_printers() -> list[str]:
    """返回 Windows 里的原始打印机名称列表。"""
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


def _raw_default_printer() -> str:
    """返回系统默认打印机的原始名称；取不到返回空串。"""
    try:
        import win32print
    except ImportError:
        return ""
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return ""


def list_printers() -> list[str]:
    """返回去重后的打印机显示名列表（同一设备的多个驱动名合并）。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in _raw_printers():
        shown = display_name(raw)
        if shown not in seen:
            seen.add(shown)
            result.append(shown)
    return result


def default_printer() -> str:
    """返回系统默认打印机显示名；取不到返回空串。"""
    raw = _raw_default_printer()
    return display_name(raw) if raw else ""


def resolve_printer(name: str) -> str:
    """把显示名或任一驱动名解析成当前实际安装的 Windows 原始打印机名。

    - 调用方传的是某个具体驱动名时，优先保留该名称（保证队列一致）；
    - 传的是显示名时，优先系统默认驱动，其次第一个已安装的驱动；
    - 未配置别名的打印机原样返回。
    """
    if not name:
        return ""
    alias = _alias_for(name)
    if alias is None:
        return name

    _display, raws = alias
    installed = _raw_printers()
    installed_map = {_norm(raw): raw for raw in installed}

    target = _norm(name)
    for raw in raws:
        if target == _norm(raw) and _norm(raw) in installed_map:
            return installed_map[_norm(raw)]

    default_raw = _raw_default_printer()
    default_norm = _norm(default_raw)
    if default_norm and default_norm in {_norm(raw) for raw in raws}:
        if default_norm in installed_map:
            return installed_map[default_norm]

    for raw in raws:
        if _norm(raw) in installed_map:
            return installed_map[_norm(raw)]
    return raws[0]


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
_JOB_PAUSED = 0x00000001
_JOB_PRINTED = 0x00000080
_JOB_DELETED = 0x00000100
_JOB_PRINTING = 0x00000010
_JOB_BLOCKED_DEVQ = 0x00000200
_JOB_USER_INTERVENTION = 0x00000400

# 驱动手动双面暂停时常见的作业状态位
CONTINUE_FLAGS = _JOB_PAUSED | _JOB_BLOCKED_DEVQ | _JOB_USER_INTERVENTION


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
        name = resolve_printer(name) or _raw_default_printer()
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

    job_details = []
    for j in jobs:
        try:
            jid = int(j.get("JobId", 0) or 0)
        except (TypeError, ValueError):
            jid = 0
        job_details.append(
            {
                "id": jid,
                "status": int(j.get("Status", 0) or 0),
                "document": str(j.get("Document") or ""),
            }
        )

    return {
        "available": True,
        "pending": pending,
        "pages_printed": pages,
        "active_printing": active,
        "problems": problems,
        "status": status,
        "jobs": job_details,
    }


def _enum_jobs(printer_name: str) -> list[dict]:
    """枚举打印机队列里的作业（level=1），失败返回空列表。"""
    try:
        import win32print
    except ImportError:
        return []

    name = resolve_printer(printer_name) or _raw_default_printer()
    if not name:
        return []
    try:
        h = win32print.OpenPrinter(name)
        try:
            return list(win32print.EnumJobs(h, 0, 256, 1) or [])
        finally:
            win32print.ClosePrinter(h)
    except Exception:
        return []


def spool_job_ids(printer_name: str = "") -> set[int]:
    """返回打印机队列中当前所有作业 id（用于打印前后对比找新作业）。"""
    ids: set[int] = set()
    for job in _enum_jobs(printer_name):
        try:
            ids.add(int(job.get("JobId")))
        except (TypeError, ValueError):
            continue
    return ids


def new_spool_job_ids(
    printer_name: str, before_ids: set[int], doc_hint: str = ""
) -> list[int]:
    """找出本次打印新增的队列作业 id。

    doc_hint 用于匹配队列里的文档名（上传文件 id 会出现在 PDF 文件名里），
    匹配不到但只新增了一个作业时，也认为它是本次打印的作业。
    """
    new_jobs: list[tuple[int, str]] = []
    for job in _enum_jobs(printer_name):
        try:
            jid = int(job.get("JobId"))
        except (TypeError, ValueError):
            continue
        if jid in before_ids:
            continue
        new_jobs.append((jid, str(job.get("Document") or "")))

    if not new_jobs:
        return []
    if doc_hint:
        hint = doc_hint.lower()
        matched = [jid for jid, doc in new_jobs if hint in doc.lower()]
        if matched:
            return matched
        if len(new_jobs) == 1:
            return [new_jobs[0][0]]
        return []
    return [jid for jid, _ in new_jobs]


def cancel_spool_jobs(
    printer_name: str, job_ids: list[int] | set[int]
) -> tuple[int, list[str]]:
    """取消 Windows 打印队列中的指定作业。

    返回 (成功取消数量, 错误信息列表)。非 Windows 或打印机不可用时
    返回 0，由调用方决定如何提示用户。
    """
    ids = sorted({int(jid) for jid in job_ids})
    if not ids:
        return 0, []

    try:
        import win32print
    except ImportError:
        return 0, ["仅支持 Windows"]

    name = resolve_printer(printer_name) or _raw_default_printer()
    if not name:
        return 0, ["未找到打印机"]

    try:
        h = win32print.OpenPrinter(name)
    except Exception as e:  # noqa: BLE001
        return 0, [f"无法打开打印机：{e}"]

    canceled = 0
    errors: list[str] = []
    delete_cmd = getattr(win32print, "JOB_CONTROL_DELETE", win32print.JOB_CONTROL_CANCEL)
    try:
        for jid in ids:
            try:
                win32print.SetJob(h, jid, 0, None, win32print.JOB_CONTROL_CANCEL)
                canceled += 1
                continue
            except Exception:
                pass
            try:
                win32print.SetJob(h, jid, 0, None, delete_cmd)
                canceled += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"任务 {jid}：{e}")
    finally:
        try:
            win32print.ClosePrinter(h)
        except Exception:
            pass

    return canceled, errors


def job_needs_continue(
    job_details: list[dict], job_ids: list[int] | set[int], doc_hint: str = ""
) -> bool:
    """判断队列里是否有等待用户继续的作业（驱动手动双面暂停）。"""
    ids = {int(jid) for jid in job_ids}
    for job in job_details:
        status = int(job.get("status", 0) or 0)
        if not (status & CONTINUE_FLAGS):
            continue
        try:
            jid = int(job.get("id", 0) or 0)
        except (TypeError, ValueError):
            continue
        doc = str(job.get("document") or "")
        if (ids and jid in ids) or (doc_hint and doc_hint.lower() in doc.lower()):
            return True
    return False


def resume_spool_jobs(
    printer_name: str,
    job_ids: list[int] | set[int],
    doc_hint: str = "",
) -> tuple[int, list[str]]:
    """恢复被驱动暂停的作业（手动双面翻面后的「继续」）。

    只恢复处于暂停/需要用户干预状态的作业，避免误操作正常任务。
    """
    try:
        import win32print
    except ImportError:
        return 0, ["仅支持 Windows"]

    name = resolve_printer(printer_name) or _raw_default_printer()
    if not name:
        return 0, ["未找到打印机"]

    ids = {int(jid) for jid in job_ids}
    try:
        h = win32print.OpenPrinter(name)
    except Exception as e:  # noqa: BLE001
        return 0, [f"无法打开打印机：{e}"]

    targets: list[int] = []
    try:
        jobs = win32print.EnumJobs(h, 0, 256, 1) or []
        for job in jobs:
            status = int(job.get("Status", 0) or 0)
            if not (status & CONTINUE_FLAGS):
                continue
            try:
                jid = int(job.get("JobId"))
            except (TypeError, ValueError):
                continue
            doc = str(job.get("Document") or "")
            if (ids and jid in ids) or (doc_hint and doc_hint.lower() in doc.lower()):
                if jid not in targets:
                    targets.append(jid)
    except Exception:
        pass

    if not targets:
        try:
            win32print.ClosePrinter(h)
        except Exception:
            pass
        return 0, ["没有找到等待继续的打印任务"]

    resumed = 0
    errors: list[str] = []
    resume_cmd = getattr(win32print, "JOB_CONTROL_RESUME", 4)
    try:
        for jid in targets:
            try:
                win32print.SetJob(h, jid, 0, None, resume_cmd)
                resumed += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"任务 {jid}：{e}")
    finally:
        try:
            win32print.ClosePrinter(h)
        except Exception:
            pass

    return resumed, errors


def cancel_jobs_by_document(
    printer_name: str, doc_hint: str
) -> tuple[int, list[str]]:
    """按文档名兜底取消（用于没来得及记录作业 id 的情况）。"""
    if not doc_hint:
        return 0, []
    job_ids: list[int] = []
    for job in _enum_jobs(printer_name):
        if doc_hint.lower() not in str(job.get("Document") or "").lower():
            continue
        try:
            job_ids.append(int(job.get("JobId")))
        except (TypeError, ValueError):
            continue
    return cancel_spool_jobs(printer_name, job_ids)
