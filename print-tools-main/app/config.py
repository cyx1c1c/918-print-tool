"""全局配置与路径处理。

兼顾两种运行形态：
1. 开发态：直接 `python -m app.main` 运行，资源在源码目录。
2. 打包态：PyInstaller 打成 exe 后，只读资源被解压到临时目录 `sys._MEIPASS`，
   而可写数据（上传文件）必须放在 exe 旁边的目录，不能写进只读临时目录。
"""
from __future__ import annotations

import configparser
import os
import secrets
import sys
from pathlib import Path


def _is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的 exe 里。"""
    return getattr(sys, "frozen", False)


def resource_path(*parts: str) -> Path:
    """只读资源路径（前端静态文件、随包携带的 SumatraPDF.exe 等）。

    打包态下从 `sys._MEIPASS` 取；开发态下从项目根目录取。
    """
    if _is_frozen():
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return base.joinpath(*parts)


def writable_dir() -> Path:
    """可写数据根目录（存放 uploads）。

    打包态：exe 所在目录；开发态：项目根目录。
    """
    if _is_frozen():
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base


# ---- 网络 ----
HOST = "0.0.0.0"
PORT = int(os.environ.get("PRINT_TOOLS_PORT", "8000"))

# ---- 目录 ----
WEB_DIR = resource_path("web")                 # 前端静态资源
UPLOAD_DIR = writable_dir() / "uploads"        # 运行时临时文件
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---- SumatraPDF 打印引擎路径 ----
# 随包携带于 vendor/SumatraPDF.exe；允许用环境变量覆盖。
SUMATRA_PATH = Path(
    os.environ.get("SUMATRA_PATH", str(resource_path("vendor", "SumatraPDF.exe")))
)

# ---- 文件保留与清理 ----
RETENTION_MINUTES = int(os.environ.get("PRINT_TOOLS_RETENTION", "30"))
CLEANUP_INTERVAL_SECONDS = 300  # 每 5 分钟扫一次过期文件
POST_PRINT_PURGE_SECONDS = 30   # 打印任务 DONE/FAILED 后，延迟多少秒自动清理源文件（兜底仍由 RETENTION_MINUTES 负责）

# ---- 打印机状态监控 ----
PRINT_MONITOR_INTERVAL = 3   # 监控轮询间隔（秒）
PRINT_STUCK_SECONDS = 45     # 任务在队列中无进展多久判定"疑似休眠/无响应"

# ---- 上传限制 ----
MAX_UPLOAD_BYTES = int(os.environ.get("PRINT_TOOLS_MAX_MB", "100")) * 1024 * 1024

# 支持的文件扩展名（小写，含点）
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
WORD_EXTS = {".doc", ".docx", ".rtf"}
EXCEL_EXTS = {".xls", ".xlsx", ".csv"}
PPT_EXTS = {".ppt", ".pptx"}
PDF_EXTS = {".pdf"}
TEXT_EXTS = {".txt"}

ALLOWED_EXTS = (
    IMAGE_EXTS | WORD_EXTS | EXCEL_EXTS | PPT_EXTS | PDF_EXTS | TEXT_EXTS
)

# ============================ 登录认证配置 ============================
# 凭据放在 exe 旁边的 config.ini（可写目录），管理员可用记事本直接编辑。
# 不能放进只读资源目录：打包后那是临时只读目录，且凭据本就该由部署者维护。
CONFIG_PATH = writable_dir() / "config.ini"

# 首次自动生成密码时填入，供启动横幅打印一次（之后置空）。
AUTH_FIRST_RUN_PASSWORD: str | None = None


def _default_config_text(password: str) -> str:
    """首次运行时写入的默认 config.ini 文本（含中文注释）。"""
    return (
        "; 918实验室云打印 - 配置文件（用记事本编辑，改完重启生效）\n"
        "[auth]\n"
        "; 是否开启登录；默认 false（不需要登录，任何同网用户可直接访问）\n"
        "; 想启用用户名密码验证就改成 true（并设置好下面的密码）\n"
        "enabled = false\n"
        "username = admin\n"
        "; 密码可直接写明文；想更安全可填 pbkdf2_sha256$... 哈希\n"
        "; （运行  python -m app.auth  生成哈希）\n"
        f"password = {password}\n"
        "; 登录后多少小时内免登录\n"
        "session_hours = 12\n"
        "; 连续失败多少次后锁定该 IP\n"
        "max_attempts = 5\n"
        "; 锁定时长（分钟）\n"
        "lockout_minutes = 10\n"
    )


def _load_auth() -> dict:
    """读取 [auth] 配置；文件缺失则生成默认（随机强密码）。环境变量优先级最高。"""
    global AUTH_FIRST_RUN_PASSWORD

    parser = configparser.ConfigParser()
    if not CONFIG_PATH.exists():
        # 首次运行：生成随机强密码并落盘，记下来供横幅打印
        pwd = secrets.token_urlsafe(12)
        AUTH_FIRST_RUN_PASSWORD = pwd
        try:
            CONFIG_PATH.write_text(_default_config_text(pwd), encoding="utf-8")
        except OSError:
            # 极端情况下目录不可写：仍能用内存里的随机密码跑起来
            pass
    else:
        try:
            parser.read(CONFIG_PATH, encoding="utf-8")
        except (configparser.Error, OSError):
            pass

    sec = parser["auth"] if parser.has_section("auth") else {}

    def _get(key: str, default: str) -> str:
        return str(sec.get(key, default)) if hasattr(sec, "get") else default

    enabled_raw = os.environ.get("PRINT_TOOLS_AUTH_ENABLED", _get("enabled", "false"))
    username = os.environ.get("PRINT_TOOLS_AUTH_USERNAME", _get("username", "admin"))
    password = os.environ.get(
        "PRINT_TOOLS_AUTH_PASSWORD",
        AUTH_FIRST_RUN_PASSWORD if AUTH_FIRST_RUN_PASSWORD else _get("password", ""),
    )
    session_hours = os.environ.get(
        "PRINT_TOOLS_AUTH_SESSION_HOURS", _get("session_hours", "12")
    )
    max_attempts = os.environ.get(
        "PRINT_TOOLS_AUTH_MAX_ATTEMPTS", _get("max_attempts", "5")
    )
    lockout_minutes = os.environ.get(
        "PRINT_TOOLS_AUTH_LOCKOUT_MINUTES", _get("lockout_minutes", "10")
    )

    def _int(val: str, fallback: int) -> int:
        try:
            return int(str(val).strip())
        except (TypeError, ValueError):
            return fallback

    return {
        "enabled": str(enabled_raw).strip().lower() in ("1", "true", "yes", "on"),
        "username": username.strip(),
        "password": password,
        "session_hours": max(1, _int(session_hours, 12)),
        "max_attempts": max(1, _int(max_attempts, 5)),
        "lockout_minutes": max(1, _int(lockout_minutes, 10)),
    }


_auth = _load_auth()
AUTH_ENABLED = _auth["enabled"]
AUTH_USERNAME = _auth["username"]
AUTH_PASSWORD = _auth["password"]
SESSION_HOURS = _auth["session_hours"]
MAX_ATTEMPTS = _auth["max_attempts"]
LOCKOUT_MINUTES = _auth["lockout_minutes"]
