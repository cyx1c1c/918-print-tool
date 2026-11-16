"""配置/取消「开机自启」——在 Windows 启动文件夹创建/删除快捷方式。

用启动文件夹（用户登录后运行）而非系统服务，确保有交互桌面会话，
这样 Office COM 转换才能正常工作。

    python install_autostart.py            # 安装自启（指向 dist/PrintTools.exe）
    python install_autostart.py --target "C:\\path\\PrintTools.exe"
    python install_autostart.py --uninstall  # 取消自启
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SHORTCUT_NAME = "918实验室云打印.lnk"


def startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"


def install(target: Path) -> int:
    if not target.exists():
        print(f"❌ 找不到目标程序：{target}")
        print("   请先用 build.py 打包出 dist/PrintTools.exe，或用 --target 指定。")
        return 1
    try:
        import win32com.client  # type: ignore
    except ImportError:
        print("❌ 需要 pywin32（pip install pywin32），且在 Windows 上运行。")
        return 1

    link = startup_dir() / SHORTCUT_NAME
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortCut(str(link))
    sc.Targetpath = str(target)
    sc.WorkingDirectory = str(target.parent)
    sc.Description = "918实验室网页打印系统"
    sc.save()
    print(f"✅ 已设置开机自启：{link}\n   指向：{target}")
    return 0


def uninstall() -> int:
    link = startup_dir() / SHORTCUT_NAME
    if link.exists():
        link.unlink()
        print(f"✅ 已取消开机自启：{link}")
    else:
        print("ℹ️  未发现自启快捷方式，无需取消。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", default=str(Path("dist/PrintTools.exe").resolve()))
    p.add_argument("--uninstall", action="store_true")
    a = p.parse_args()
    if a.uninstall:
        return uninstall()
    return install(Path(a.target))


if __name__ == "__main__":
    sys.exit(main())
