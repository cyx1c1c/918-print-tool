@echo off
chcp 65001 >nul
cd /d %~dp0
echo === 安装依赖（首次使用时运行一次） ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo === 下载打印引擎 SumatraPDF（需联网） ===
python download_sumatra.py
echo.
echo 安装完成！双击 start.bat 即可启动打印系统。
pause
