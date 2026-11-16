"""用 PyInstaller 把项目打包成单个 exe（在 Windows 上运行本脚本）。

    python build.py

产物：dist/PrintTools.exe
打包前请确认 vendor/SumatraPDF.exe 已就位（见 download_sumatra.py 或 README）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEP = ";" if os.name == "nt" else ":"  # PyInstaller --add-data 分隔符


def main() -> int:
    sumatra = ROOT / "vendor" / "SumatraPDF.exe"
    if not sumatra.exists():
        print("⚠️  缺少 vendor/SumatraPDF.exe，打印功能将不可用。")
        print("    请先运行  python download_sumatra.py  或手动放置后再打包。")
        # 不强制中断，允许仅打包（之后补 exe 也行，但推荐先放好）

    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "PrintTools",
        "--noconfirm",
        "--clean",
        # 携带前端静态资源
        "--add-data", f"{ROOT / 'web'}{SEP}web",
        # 携带打印引擎
        "--add-binary", f"{sumatra}{SEP}vendor",
        # uvicorn 动态子模块 + reportlab 数据（内置中文字体）
        "--collect-submodules", "uvicorn",
        "--collect-data", "reportlab",
        # 入口
        str(ROOT / "run.py"),
    ]
    print("执行：\n  " + " ".join(args) + "\n")
    return subprocess.call(args)


if __name__ == "__main__":
    raise SystemExit(main())
