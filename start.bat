@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 全国大学数据分析大屏

echo ============================================================
echo   全国大学数据分析大屏 - 一键启动
echo   数据库配置：config.py（无需再设置环境变量）
echo ============================================================
echo.

python app.py --open
if errorlevel 1 (
  echo.
  echo [启动失败] 请检查：
  echo   1. 是否已安装依赖： pip install -r requirements.txt
  echo   2. MySQL 服务是否已启动
  echo   3. config.py 中的账号密码是否正确
  echo.
  pause
)
