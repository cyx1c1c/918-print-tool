"""下载 SumatraPDF 便携版到 vendor/SumatraPDF.exe（需在有网环境运行）。

办公室电脑不联网，请在**有网的开发机**上运行本脚本下载好 exe，
随项目一起拷贝到打印机电脑即可。

    python download_sumatra.py

若下载失败，请手动到 https://www.sumatrapdfreader.org/download-free-pdf-viewer
下载 64 位「便携版(portable)」exe，重命名为 SumatraPDF.exe 放到 vendor/ 下。
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
TARGET = VENDOR / "SumatraPDF.exe"

# 官方发布的 64 位便携版压缩包（如版本失效，请按文件顶部说明手动下载）
VERSION = "3.5.2"
ZIP_URL = (
    f"https://www.sumatrapdfreader.org/dl/rel/{VERSION}/"
    f"SumatraPDF-{VERSION}-64.zip"
)


def main() -> int:
    VENDOR.mkdir(parents=True, exist_ok=True)
    if TARGET.exists():
        print(f"✅ 已存在：{TARGET}")
        return 0

    print(f"正在下载 SumatraPDF {VERSION} …\n  {ZIP_URL}")
    try:
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            blob = resp.read()
    except Exception as e:  # noqa: BLE001
        print(f"❌ 下载失败：{e}")
        print("   请按本文件顶部说明手动下载并放置到 vendor/SumatraPDF.exe")
        return 1

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            # 压缩包内 exe 名形如 SumatraPDF-3.5.2-64.exe
            exe_name = next(
                n for n in zf.namelist() if n.lower().endswith(".exe")
            )
            with zf.open(exe_name) as src, open(TARGET, "wb") as out:
                out.write(src.read())
    except StopIteration:
        # 有时直链本身就是 exe（非 zip）
        TARGET.write_bytes(blob)
    except Exception as e:  # noqa: BLE001
        print(f"❌ 解压失败：{e}")
        return 1

    print(f"✅ 完成：{TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
