"""跨平台冒烟自检：验证不依赖 Windows 的核心逻辑。

    python selftest.py

在 Linux/Mac 上：转换(图片/文本/PDF)、A4 化、N-up、页码解析、上传/按需预览/打印队列
API 均可测；Office 转换与真实打印依赖 Windows，这里只验证它们会"优雅失败"。
"""
from __future__ import annotations

import io
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

# 给认证模块注入确定的测试凭据（必须在导入任何 app.* 之前设置，
# 因为 app.config 在导入时就会读取这些值）。
os.environ["PRINT_TOOLS_AUTH_ENABLED"] = "true"
os.environ["PRINT_TOOLS_AUTH_USERNAME"] = "test"
os.environ["PRINT_TOOLS_AUTH_PASSWORD"] = "test123"
os.environ["PRINT_TOOLS_AUTH_MAX_ATTEMPTS"] = "3"

PASS, FAIL = "✅", "❌"
fails = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global fails
    print(f"  {PASS if cond else FAIL} {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails += 1


def make_pdf(path: Path, pages: int) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for i in range(pages):
        c.drawString(100, 700, f"测试页 Page {i + 1}")
        c.showPage()
    c.save()


def make_png(path: Path, size=(300, 200)) -> None:
    from PIL import Image

    Image.new("RGB", size, (90, 140, 240)).save(path)


def test_page_range():
    print("[1] 页码范围解析")
    from app.printing.pdfutil import parse_page_range

    check("空串=全部", parse_page_range("", 5) == [1, 2, 3, 4, 5])
    check("区间+单页", parse_page_range("1-3,5", 10) == [1, 2, 3, 5])
    check("开放区间 a-", parse_page_range("8-", 10) == [8, 9, 10])
    check("越界过滤", parse_page_range("3-99", 5) == [3, 4, 5])
    check("乱序去重", parse_page_range("5,1-2,2", 9) == [1, 2, 5])


def test_converters(tmp: Path):
    print("[2] 转换器（图片→A4 / 文本 / PDF）")
    from pypdf import PdfReader

    from app.converters.base import ConversionError
    from app.converters.dispatch import convert_to_pdf

    big = tmp / "big.jpg"
    make_png(big, (4000, 3000))  # 大图，回归测试：必须铺成 A4
    pdf1 = convert_to_pdf(big, tmp)
    pg = PdfReader(str(pdf1)).pages[0]
    w, h = float(pg.mediabox.width), float(pg.mediabox.height)
    check("大图→A4 页面(595x842)", abs(w - 595) < 3 and abs(h - 842) < 3, f"{w:.0f}x{h:.0f}")

    txt = tmp / "note.txt"
    txt.write_text("你好，世界！\nHello world.\n" * 3, encoding="utf-8")
    check("文本→PDF(含中文)", convert_to_pdf(txt, tmp).exists())

    src_pdf = tmp / "doc.pdf"
    make_pdf(src_pdf, 3)
    check("PDF→PDF(校验复制)", convert_to_pdf(src_pdf, tmp).exists())

    fake_doc = tmp / "x.docx"
    fake_doc.write_bytes(b"PK\x03\x04 not really")
    try:
        convert_to_pdf(fake_doc, tmp)
        check("Office 在非Win优雅失败", False, "未抛异常")
    except ConversionError:
        check("Office 在非Win优雅失败", True)
    except Exception as e:  # noqa: BLE001
        check("Office 在非Win优雅失败", False, f"抛了 {type(e).__name__}")


def test_nup(tmp: Path):
    print("[3] N-up 拼版")
    from app.printing.nup import make_nup
    from app.printing.pdfutil import page_count

    src = tmp / "many.pdf"
    make_pdf(src, 8)
    out = tmp / "nup4.pdf"
    make_nup(src, out, 4)
    check("8页@4合1 → 2页", page_count(out) == 2, f"得到 {page_count(out)} 页")


def test_orientation(tmp: Path):
    print("[3b] 横版 PDF 方向归一（打印前旋转成竖版）")
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader

    from app.printing import pdfutil

    def eff(pdf):
        pg = PdfReader(str(pdf)).pages[0]
        w, h = float(pg.mediabox.width), float(pg.mediabox.height)
        if int(pg.get("/Rotate", 0) or 0) % 360 in (90, 270):
            w, h = h, w
        return w, h

    lp = tmp / "land.pdf"
    c = canvas.Canvas(str(lp), pagesize=landscape(A4))
    c.drawString(100, 100, "L")
    c.showPage()
    c.save()
    out = tmp / "land_rot.pdf"
    changed = pdfutil.normalize_orientation(lp, out)
    w, h = eff(out) if changed else eff(lp)
    check("横版→旋转成竖版", changed and h > w, f"{w:.0f}x{h:.0f}")

    pp = tmp / "port.pdf"
    c = canvas.Canvas(str(pp), pagesize=A4)
    c.drawString(100, 100, "P")
    c.showPage()
    c.save()
    check("竖版→不动", pdfutil.normalize_orientation(pp, tmp / "p_rot.pdf") is False)


def test_api(tmp: Path):
    print("[4] HTTP API（多文件上传/按需预览/打印/状态）")
    from fastapi.testclient import TestClient

    from app import auth, config, main
    from app.printing.jobqueue import manager

    manager.start()
    client = TestClient(main.app)

    # 先登录（认证开启后，后续 API 调用都需要会话 cookie）
    auth._attempts.clear()  # 清掉上一组测试可能留下的锁定状态
    lr = client.post(
        "/api/login",
        json={"username": config.AUTH_USERNAME, "password": "test123"},
    )
    check("自检登录成功", lr.status_code == 200 and lr.json().get("ok"))

    r = client.get("/api/printers")
    check("GET /api/printers", r.status_code == 200 and "printers" in r.json())

    # 上传只登记、不转换（应快速返回，无 pages/preview_url）
    png = tmp / "u.png"
    make_png(png)
    with open(png, "rb") as f:
        r = client.post("/api/upload", files={"file": ("u.png", f, "image/png")})
    ok = r.status_code == 200 and r.json().get("file_id")
    check("POST /api/upload（只存不转）", bool(ok) and "preview_url" not in r.json())
    if not ok:
        return
    fid = r.json()["file_id"]

    # 拒绝不支持类型
    r2 = client.post("/api/upload", files={"file": ("a.zip", io.BytesIO(b"x"), "application/zip")})
    check("拒绝不支持类型", r2.status_code == 400)

    # 按需预览：此时才转换
    rp = client.post("/api/preview", json={"file_id": fid})
    pj = rp.json()
    check("POST /api/preview 触发转换", rp.status_code == 200 and (pj.get("pages") or 0) >= 1)
    if rp.status_code == 200:
        rf = client.get(pj["preview_url"])
        check("预览 PDF 可取", rf.status_code == 200 and rf.content[:4] == b"%PDF")

    # 提交打印（无 SumatraPDF → 应走到 failed）
    r3 = client.post("/api/print", json={"file_id": fid, "copies": 2})
    job_id = r3.json().get("job_id")
    check("POST /api/print 入队", r3.status_code == 200 and bool(job_id))

    final = None
    for _ in range(50):
        jr = client.get(f"/api/jobs/{job_id}")
        if jr.json().get("status") in ("done", "failed"):
            final = jr.json()
            break
        time.sleep(0.1)
    check("任务到达终态", final is not None, final and final.get("status"))
    if final:
        check("打印失败有明确提示", final["status"] == "failed" and bool(final["error"]),
              final.get("error", "")[:50])

    # 删除
    rd = client.post("/api/delete", json={"file_id": fid})
    check("POST /api/delete", rd.status_code == 200)


def test_print_scaling(tmp: Path):
    print("[5] 打印缩放默认值（修复超大 PDF 只打出左上角）")
    from reportlab.pdfgen import canvas

    from app.models import PrintOptions
    from app.printing import sumatra

    # 默认应为 shrink：超过纸张可打印区的页面缩小贴合，正常页不动
    check("默认缩放 = shrink", PrintOptions().normalized().scaling == "shrink")
    check("非法缩放值回退 shrink", PrintOptions(scaling="zzz").normalized().scaling == "shrink")
    s = sumatra._build_settings(PrintOptions().normalized(), "")
    check("命令行 settings 含 shrink", "shrink" in s.split(","), s)

    # 构造约 A4 1.88 倍的超大竖版 PDF（复现问题尺寸 1118.5x1583.1），走打印管线
    big = tmp / "oversize.pdf"
    c = canvas.Canvas(str(big), pagesize=(1118.5, 1583.1))
    c.drawString(100, 1400, "oversize page")
    c.showPage()
    c.save()
    opts = PrintOptions(scaling="shrink").normalized()
    work, page_range, temps = sumatra._prepare_pdf(big, opts)
    try:
        check("超大竖版页不被误旋转/拼版（交给引擎 shrink）", work == big)
        check("对超大页的打印命令带 shrink",
              "shrink" in sumatra._build_settings(opts, page_range).split(","))
    finally:
        for t in temps:
            try:
                t.unlink(missing_ok=True)
            except Exception:
                pass


def test_auth():
    print("[6] 登录认证 / 防爆破")
    from fastapi.testclient import TestClient

    from app import auth, config, main

    client = TestClient(main.app)

    # 未登录被挡在门外
    r = client.get("/api/printers")
    check("未登录访问 /api/printers → 401", r.status_code == 401)
    r = client.get("/", follow_redirects=False)
    check("未登录访问 / → 302 跳登录页", r.status_code == 302 and r.headers.get("location") == "/login")
    r = client.get("/login")
    check("登录页可匿名访问", r.status_code == 200)

    # 正确登录
    auth._attempts.clear()
    r = client.post("/api/login", json={"username": config.AUTH_USERNAME, "password": "test123"})
    check("正确密码登录 → 200", r.status_code == 200 and r.json().get("ok"))
    check("拿到会话 cookie", auth.COOKIE_NAME in r.cookies)
    r = client.get("/api/printers")
    check("登录后可访问 /api/printers", r.status_code == 200)

    # 错误密码被拒
    r = client.post("/api/login", json={"username": config.AUTH_USERNAME, "password": "nope"})
    check("错误密码 → 401", r.status_code == 401)

    # 登出后又被挡
    client.post("/api/logout")
    r = client.get("/api/printers")
    check("登出后再访问 → 401", r.status_code == 401)

    # 防爆破：连续失败触发锁定 429
    auth._attempts.clear()
    statuses = [
        client.post("/api/login", json={"username": "x", "password": "bad"}).status_code
        for _ in range(config.MAX_ATTEMPTS + 1)
    ]
    check("连续失败后锁定 → 429", 429 in statuses, f"状态序列={statuses}")

    # 哈希密码也能校验
    h = auth.hash_password("hunter2")
    check("pbkdf2 哈希校验正确密码", auth.verify_password("hunter2", h))
    check("pbkdf2 哈希拒绝错误密码", not auth.verify_password("wrong", h))

    # 清理锁定状态，避免影响后续 test_api 登录
    auth._attempts.clear()


def main():
    print("=== print-tools 冒烟自检 ===\n")
    test_page_range()
    with TemporaryDirectory() as d:
        tmp = Path(d)
        test_converters(tmp)
        test_nup(tmp)
        test_orientation(tmp)
        test_print_scaling(tmp)
        test_auth()
        test_api(tmp)
    print(f"\n{'全部通过 🎉' if fails == 0 else f'有 {fails} 项失败 😢'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
