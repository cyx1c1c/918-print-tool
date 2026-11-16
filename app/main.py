"""FastAPI 应用入口：串联多文件上传、按需转换/预览、打印、状态、清理。

运行：python -m app.main

流程：上传只存原文件（不转换）→ 列表卡片 → 点预览/打印时才按需转换并缓存。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, cleanup, config
from .converters.base import ConversionError
from .models import PrintJob, PrintOptions
from .printing import monitor
from .printing.jobqueue import manager
from .printing.printers import default_printer, list_printers
from .store import store

app = FastAPI(title="918实验室网页打印系统")


# ---------- 数据模型 ----------
class PrintRequest(BaseModel):
    file_id: str
    printer: str = ""
    color: str = "monochrome"
    copies: int = 1
    page_range: str = ""
    duplex: str = "simplex"
    paper: str = ""
    pages_per_sheet: int = 1
    scaling: str = "noscale"


class FileIdRequest(BaseModel):
    file_id: str


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


# ---------- API ----------
@app.get("/api/printers")
def api_printers() -> dict:
    """返回打印机列表与默认打印机。"""
    return {"printers": list_printers(), "default": default_printer()}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)) -> dict:
    """接收单个文件，仅保存原文件、不转换（转换推迟到预览/打印时）。"""
    orig_name = Path(file.filename or "未命名").name
    ext = Path(orig_name).suffix.lower()
    if ext not in config.ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的文件类型：{ext or '（无扩展名）'}")

    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"文件过大，最大 {config.MAX_UPLOAD_BYTES // 1024 // 1024} MB"
        )

    file_id = store.new_id()
    src_path = config.UPLOAD_DIR / f"{file_id}_{orig_name}"
    src_path.write_bytes(data)
    store.register(file_id, src_path, orig_name)

    return {
        "file_id": file_id,
        "filename": orig_name,
        "ext": ext.lstrip("."),
        "size": len(data),
    }


@app.post("/api/preview")
async def api_preview(req: FileIdRequest) -> dict:
    """按需把文件转成 PDF 并返回预览地址（已转过则用缓存）。"""
    def _convert():
        return store.ensure_pdf(req.file_id)

    try:
        entry = await run_in_threadpool(_convert)
    except KeyError:
        raise HTTPException(404, "文件不存在或已过期，请重新上传")
    except ConversionError as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"转换失败：{e}")

    return {
        "file_id": entry.id,
        "pages": entry.pages or 0,
        "preview_url": f"/files/{Path(entry.pdf).name}",
    }


@app.post("/api/convert")
async def api_convert(req: FileIdRequest) -> dict:
    """把文件转成 PDF 并返回下载链接（独立于打印，纯转换用途）。"""
    def _convert():
        return store.ensure_pdf(req.file_id)

    try:
        entry = await run_in_threadpool(_convert)
    except KeyError:
        raise HTTPException(404, "文件不存在或已过期，请重新上传")
    except ConversionError as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"转换失败：{e}")

    orig_stem = Path(entry.filename).stem
    return {
        "file_id": entry.id,
        "pages": entry.pages or 0,
        "filename": f"{orig_stem}.pdf",
        "download_url": f"/files/{Path(entry.pdf).name}",
    }


@app.post("/api/print")
def api_print(req: PrintRequest) -> dict:
    """创建打印任务并入队（实际转换/打印在后台 worker 中串行进行）。"""
    entry = store.get(req.file_id)
    if not entry:
        raise HTTPException(404, "文件不存在或已过期，请重新上传")

    options = PrintOptions(
        printer=req.printer,
        color=req.color,
        copies=req.copies,
        page_range=req.page_range,
        duplex=req.duplex,
        paper=req.paper,
        pages_per_sheet=req.pages_per_sheet,
        scaling=req.scaling,
    ).normalized()

    job = PrintJob(
        id=uuid.uuid4().hex,
        file_id=req.file_id,
        filename=entry.filename,
        options=options,
    )
    manager.submit(job)
    return {"job_id": job.id}


@app.post("/api/delete")
def api_delete(req: FileIdRequest) -> dict:
    """从列表移除并删除该文件（用户在卡片上点删除）。"""
    if req.file_id in manager.active_file_ids():
        return {"ok": False, "reason": "文件正在打印中，无法删除"}
    store.purge(req.file_id)
    return {"ok": True}


@app.get("/api/jobs")
def api_jobs() -> dict:
    return {"jobs": [j.to_public() for j in manager.all_jobs()]}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job.to_public()


# ---------- 登录认证 ----------
# 不需要登录即可访问的路径（登录页本身与登录/登出接口）
_AUTH_WHITELIST = {"/login", "/api/login", "/api/logout", "/favicon.ico"}


@app.middleware("http")
async def require_auth(request: Request, call_next):
    """门卫：未登录的请求一律挡下（API 返 401，页面 302 跳登录页）。

    注册在所有路由与静态挂载之前生效，因此能覆盖 /、/files/*、/app.js 等一切路径。
    """
    if not config.AUTH_ENABLED or request.url.path in _AUTH_WHITELIST:
        return await call_next(request)

    if auth.validate_session(request.cookies.get(auth.COOKIE_NAME)):
        return await call_next(request)

    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
    return RedirectResponse("/login", status_code=302)


@app.get("/login")
def login_page(request: Request):
    """登录页；已登录则直接回首页。"""
    if config.AUTH_ENABLED and auth.validate_session(
        request.cookies.get(auth.COOKIE_NAME)
    ):
        return RedirectResponse("/", status_code=302)
    return FileResponse(config.WEB_DIR / "login.html")


@app.post("/api/login")
async def api_login(req: LoginRequest, request: Request) -> JSONResponse:
    """校验用户名密码：带防爆破（锁定 + 失败延迟）与常量时间比较。"""
    ip = request.client.host if request.client else "unknown"

    remaining = auth.check_locked(ip)
    if remaining > 0:
        minutes = (remaining + 59) // 60
        return JSONResponse(
            {"detail": f"尝试过于频繁，请约 {minutes} 分钟后再试"},
            status_code=429,
        )

    ok_user = auth.verify_username(req.username, config.AUTH_USERNAME)
    ok_pass = auth.verify_password(req.password, config.AUTH_PASSWORD)
    if not (ok_user and ok_pass):
        auth.record_failure(ip, config.MAX_ATTEMPTS, config.LOCKOUT_MINUTES * 60)
        await asyncio.sleep(0.6)  # 固定小延迟，拖慢脚本爆破
        return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)

    auth.record_success(ip)
    token = auth.create_session(config.SESSION_HOURS * 3600)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=config.SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return resp


@app.post("/api/logout")
def api_logout(request: Request) -> JSONResponse:
    """登出：销毁会话并清除 cookie。"""
    auth.destroy_session(request.cookies.get(auth.COOKIE_NAME))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE_NAME, path="/")
    return resp


# ---------- 静态资源（最后挂载，作为兜底） ----------
app.mount("/files", StaticFiles(directory=str(config.UPLOAD_DIR)), name="files")
app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")


def _startup() -> None:
    manager.start()
    monitor.start()
    cleanup.start()


def main() -> None:
    import uvicorn

    from .qrcode_util import print_access_banner

    print_access_banner(config.PORT)
    if config.AUTH_ENABLED and config.AUTH_FIRST_RUN_PASSWORD:
        print("  ⚠️  首次运行，已自动生成登录账号：")
        print(f"      用户名：{config.AUTH_USERNAME}")
        print(f"      密码：  {config.AUTH_FIRST_RUN_PASSWORD}")
        print(f"      （可在 {config.CONFIG_PATH} 中修改，建议尽快改成自己的密码）")
        print("=" * 44 + "\n")
    elif not config.AUTH_ENABLED:
        print("  🔓 登录验证当前未开启，任何同网用户都可直接访问。")
        print(f"      如需开启：编辑 {config.CONFIG_PATH}")
        print("      把 [auth] enabled 改为 true 并设置好用户名密码后重启。")
        print("=" * 44 + "\n")
    _startup()
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
