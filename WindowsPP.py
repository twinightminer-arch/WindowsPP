#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows++ v3.0 — 入口（薄壳，兼容旧快捷方式 / 启动脚本 / 命令行参数）。

    python WindowsPP.py            # 打开图形界面（默认：软件更新页）
    python WindowsPP.py --scan     # 命令行只读扫描
    python WindowsPP.py --tray     # 后台最小化运行（开机启动场景）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from wpp.app import main as app_main
    app_main()


if __name__ == "__main__":
    main()
