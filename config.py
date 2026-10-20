# -*- coding: utf-8 -*-
"""
项目配置（本地开发环境）

按使用者要求：MySQL 账号密码直接保存在项目内，启动时无需再设置环境变量。
如需临时覆盖，仍可用环境变量 MYSQL_HOST / MYSQL_PORT / MYSQL_USER /
MYSQL_PASSWORD / MYSQL_DATABASE（环境变量优先级更高）。

⚠️ 安全提示：本文件含明文密码，仅用于本机实训项目。
   若后续要推到 GitHub / 公网，请先改成环境变量或删除本文件中的密码。
"""

import os

DB_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", "123456"),
    "database": os.environ.get("MYSQL_DATABASE", "university"),
}

APP_HOST = os.environ.get("FLASK_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("FLASK_PORT", "5000"))
