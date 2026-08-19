#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows++ 内置工具独立入口（供开机自启动调用）。

用法: python wpp_tools.py --clock | --calendar | --cpu
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from wpp.tools import run_tool
    run_tool(sys.argv[1:])


if __name__ == "__main__":
    main()
