"""程序入口：开发态直接运行，也是 PyInstaller 打包的入口脚本。

    python run.py

入口最早处把标准输出切到 UTF-8：Windows 控制台默认 GBK，直接 print
emoji / 二维码方块字符会触发 UnicodeEncodeError 导致闪退，这里统一兜底。
"""
import sys


def _force_utf8_console() -> None:
    # 让 Python 以 UTF-8 输出，编码异常时用替代字符而非崩溃
    for stream in ("stdout", "stderr"):
        s = getattr(sys, stream, None)
        try:
            if s is not None:
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    # 同时把 Windows 控制台代码页设为 UTF-8(65001)，让二维码/中文正常显示
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass


_force_utf8_console()

from app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
