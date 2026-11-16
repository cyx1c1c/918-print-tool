# 🖨️ 办公室云打印系统（print-tools）

让办公室里那台「只连着一台 Windows 电脑、又不联网」的打印机，变成人人可用的**网页打印服务**。
同事在自己电脑浏览器打开网址、或手机扫码，就能上传文件、预览、选配置、一键打印——再也不用排队插 U 盘。

---

## ✨ 功能

- 浏览器 / 手机扫码上传，**统一转成 PDF 预览**（所见即所得）
- 支持 **图片 / PDF / Word / Excel / PPT / 文本** 等常见办公文件
- 打印配置：黑白·彩色、份数、页码范围、双面、纸张尺寸、每张多页(N-up)、缩放
- **打印队列**：多人同时提交自动排队，页面实时显示「排队 / 转换 / 打印 / 完成 / 失败」
- 打印完成后文件**保留约 30 分钟自动删除**，保护隐私
- 开机自启，放在那台电脑长期当打印站

## 🧩 工作原理

```
浏览器/手机 ──HTTP──> 本机 FastAPI 服务
  上传 → 转 PDF（Office 文档用本机 Office COM，图片用 img2pdf）
       → 浏览器原生预览 PDF → 选配置 → 排队 → SumatraPDF 精确打印 → 定时清理
```

## 💻 运行环境要求

- **必须**是连着打印机的那台 **Windows** 电脑（打印、Office 转换都依赖 Windows）。
- 已安装 **Microsoft Office**（Word/Excel/PowerPoint）——用于把 Office 文档转 PDF。
- **Python 3.10+**（若用打包好的 exe 则无需 Python）。
- 打印引擎 **SumatraPDF**（免费绿色，随项目携带，见下文）。

> ⚠️ 注意：本项目用到 Windows 专有能力（Office COM、win32print、SumatraPDF），
> **无法在 Linux/WSL/Mac 上真正打印**，请在目标 Windows 电脑上运行与验证。

## 🚀 快速开始（源码运行，最简单）

在那台 Windows 电脑上：

1. 安装 [Python](https://www.python.org/downloads/)（勾选 *Add to PATH*）。
2. 把本项目文件夹拷贝过去。
3. 双击 **`install.bat`**（联网，自动装依赖 + 下载 SumatraPDF）。
   - 若那台电脑不联网：在**有网的电脑**上先 `python download_sumatra.py` 下好 `vendor/SumatraPDF.exe`，
     连同项目一起拷过去；依赖也可在有网机 `pip download` 后离线安装。
4. 双击 **`start.bat`** 启动。窗口里会显示访问网址和二维码。
5. 同事电脑浏览器访问那个网址，或手机连**同一 WiFi** 扫码即可打印。

## 📦 打包成单个 exe（免装 Python，推荐长期部署）

在一台有网的 Windows 开发机上：

```bat
pip install -r requirements.txt pyinstaller
python download_sumatra.py        :: 准备 vendor\SumatraPDF.exe
python build.py                   :: 产出 dist\PrintTools.exe
```

把 `dist\PrintTools.exe` 拷到打印机电脑，双击即用（无需 Python 环境）。

### 设置开机自启

```bat
python install_autostart.py --target "C:\路径\PrintTools.exe"
:: 取消自启：
python install_autostart.py --uninstall
```

自启采用「登录后从启动文件夹运行」，保证有桌面会话，Office COM 才能正常转换。

## 🖨️ 打印参数说明

| 选项 | 说明 |
|------|------|
| 颜色 | 黑白 / 彩色（交给打印机驱动） |
| 份数 | 1–99，通过多次调用打印保证生效 |
| 页码范围 | 如 `1-5,8`，留空=全部 |
| 双面 | 单面 / 双面长边 / 双面短边（需打印机支持） |
| 纸张 | A4/A3/Letter（是否生效取决于驱动与 SumatraPDF 版本） |
| 每张多页 | 1/2/4/6/9/16，由本程序用 pypdf 拼版，效果与驱动无关 |
| 缩放 | **默认「适当缩小」**：比纸大的页面自动缩小贴合纸张（如 A3 内容打到 A4）；另有「铺满页面」「原始大小」可选 |

> 不同打印机驱动对「双面、纸张」支持度不一，建议首次部署时实测一遍校准。

## 🔐 登录与防暴力破解

系统支持**用户名密码登录**，可有效避免「同一局域网里任何人都能随意上传打印、翻看别人刚传的文件」。
该功能**默认关闭**（开箱即用、不挡人）；需要时把 `config.ini` 里的 `enabled` 改成 `true` 即可开启。

- **配置文件**：凭据放在程序旁边的 **`config.ini`**（源码运行时在项目根目录；打包后在 `PrintTools.exe` 同目录）。用记事本编辑、保存后**重启**生效。
- **首次运行**：若没有 `config.ini`，程序会自动生成一份，且**默认 `enabled = false`（不需要登录）**；启动窗口会提示如何开启验证。
- **开启登录**：把 `enabled` 改成 `true`、设置好 `username` / `password` 后重启。若开启后首次运行才生成配置，启动窗口会打印自动生成的初始密码（用户名默认 `admin`）。
- 可参考随仓库附带的 [`config.example.ini`](config.example.ini)。

`config.ini` 的 `[auth]` 各项：

| 配置项 | 默认 | 说明 |
|------|------|------|
| `enabled` | **false** | 是否开启登录；默认关闭（不挡人），改 `true` 才启用用户名密码验证 |
| `username` | admin | 登录用户名 |
| `password` | （随机生成） | 明文密码；或填 `pbkdf2_sha256$...` 哈希 |
| `session_hours` | 12 | 登录后免登录小时数（重启服务需重新登录） |
| `max_attempts` | 5 | 同一 IP 连续失败多少次后锁定 |
| `lockout_minutes` | 10 | 锁定时长（分钟） |

**用哈希密码（不在文件里留明文）**：运行 `python -m app.auth`，按提示输入密码，把它打印出来的 `pbkdf2_sha256$...` 整行粘到 `password =` 后面即可。

> ⚠️ **安全提示**：局域网为纯 HTTP（无 HTTPS），密码在内网明文传输。请仅在**可信局域网**使用，并定期更换密码。每次登录失败都会有短暂延迟、连续失败会锁定来源 IP，以拖慢脚本爆破。

## ⚙️ 可调配置（环境变量）

> 下列环境变量优先级高于 `config.ini`，方便临时覆盖；认证项也有对应的
> `PRINT_TOOLS_AUTH_ENABLED / _USERNAME / _PASSWORD / _SESSION_HOURS / _MAX_ATTEMPTS / _LOCKOUT_MINUTES`。

| 变量 | 默认 | 说明 |
|------|------|------|
| `PRINT_TOOLS_PORT` | 8000 | 服务端口 |
| `PRINT_TOOLS_RETENTION` | 30 | 文件保留分钟数 |
| `PRINT_TOOLS_MAX_MB` | 100 | 单文件上传上限(MB) |
| `SUMATRA_PATH` | vendor/SumatraPDF.exe | 打印引擎路径 |

## 🐛 常见问题

- **预览空白 / 手机不显示 PDF**：用 Chrome/Edge 效果最佳；部分手机浏览器会下载而非内联，
  可在新标签打开预览链接查看。
- **Office 文档转换失败**：确认装了正版 Office；服务需在「已登录的桌面会话」中运行（别注册成无人会话的服务）。
- **打印没反应**：确认 `vendor/SumatraPDF.exe` 存在、打印机已连好且能正常打印测试页。
- **份数=多份但只出一份**：本程序对份数采用多次打印，若仍异常请检查打印机驱动队列。
- **打印出来文字超大 / 每页只印出左上角一块**：多半是这个 PDF 的页面尺寸比 A4 大很多（常见于按大版心/A3 导出的 PDF）。预览正常是因为浏览器会自适应缩放显示。本程序**默认用「适当缩小」**把超大页缩小贴合纸张，正常已解决；若你在「更多设置」里手动选了**「原始大小」**就会复现——改回「适当缩小」或「铺满页面」即可。
- **显示「等待打印机」**：程序会读取 Windows 打印队列与打印机状态——只有真正打印出来才显示「已完成」。
  若任务卡在队列里（打印机离线/缺纸/**休眠**等），会显示「等待打印机」并给出原因提示。
  注意：软件**无法自动唤醒**休眠的 USB 打印机（没有通用接口），请去打印机上按一下唤醒键；
  想根治可把打印机的「睡眠/自动关机」时间调长或关闭（在打印机属性/厂商工具/打印机面板里）。

## 📁 目录结构

```
app/            后端：转换器 / 打印 / 队列 / 清理 / 配置
web/            前端：单页 上传·预览·选项·状态
vendor/         SumatraPDF.exe（自行下载）
run.py          入口
build.py        PyInstaller 打包
install.bat / start.bat   一键安装 / 启动
download_sumatra.py       下载打印引擎
install_autostart.py      开机自启
```
