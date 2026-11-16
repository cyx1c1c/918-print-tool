@echo off
chcp 65001 >nul
cd /d %~dp0
echo 正在启动918实验室云打印系统…（关闭本窗口即停止服务）
python run.py
pause
