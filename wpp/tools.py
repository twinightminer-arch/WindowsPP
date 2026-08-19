#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.tools — 内置桌面迷你工具：时钟 / 日历 / CPU 仪表盘。

既可被主程序以 Toplevel 打开，也可独立运行：
    python wpp_tools.py --clock / --calendar / --cpu
"""

import ctypes
import datetime
import time
import calendar
import tkinter as tk
from tkinter import ttk


# ------------------------------------------------------------
# CPU 占用率（NtQuerySystemInformation，标准库实现）
# ------------------------------------------------------------
class _ULARGE_INTEGER(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_ulong)]

    def value(self):
        return (self.HighPart << 32) | self.LowPart


class _SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION(ctypes.Structure):
    _pack_ = 8  # 与 Windows 对齐（48 字节）
    _fields_ = [("IdleTime", _ULARGE_INTEGER),
                ("KernelTime", _ULARGE_INTEGER),
                ("UserTime", _ULARGE_INTEGER),
                ("DpcTime", _ULARGE_INTEGER),
                ("InterruptTime", _ULARGE_INTEGER),
                ("InterruptCount", ctypes.c_ulong)]


def _cpu_times():
    """返回 (idle, kernel, user) 累计值；失败返回 None。"""
    try:
        nt = ctypes.windll.ntdll.NtQuerySystemInformation
        nt.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
                       ctypes.POINTER(ctypes.c_ulong)]
        nt.restype = ctypes.c_long
        size = ctypes.sizeof(_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION) * 64
        buf = ctypes.create_string_buffer(size)
        needed = ctypes.c_ulong()
        st = nt(8, buf, size, ctypes.byref(needed))
        if st != 0 and needed.value > 0:
            size = needed.value
            buf = ctypes.create_string_buffer(size)
            st = nt(8, buf, size, ctypes.byref(needed))
        if st != 0:
            return None
        n = needed.value // ctypes.sizeof(_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION)
        arr = ctypes.cast(buf, ctypes.POINTER(_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION))
        idle = kern = user = 0
        for i in range(n):
            idle += arr[i].IdleTime.value()
            kern += arr[i].KernelTime.value()
            user += arr[i].UserTime.value()
        return idle, kern, user
    except Exception:
        return None


def get_cpu_usage():
    """返回 0-100 的 CPU 占用率；失败返回 None。"""
    a = _cpu_times()
    if a is None:
        return None
    time.sleep(0.8)
    b = _cpu_times()
    if b is None:
        return None
    idle = b[0] - a[0]
    kern = b[1] - a[1]
    user = b[2] - a[2]
    total = kern + user
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (total - idle) * 100.0 / total))


# ------------------------------------------------------------
# 工具窗口
# ------------------------------------------------------------
def _clock_window(master):
    f = tk.Frame(master, bg="#1E1E2E", padx=24, pady=20)
    lbl_time = tk.Label(f, text="--:--:--", font=("Consolas", 42, "bold"),
                        fg="#7FBA00", bg="#1E1E2E")
    lbl_date = tk.Label(f, text="", font=("Microsoft YaHei UI", 12),
                        fg="#CCCCCC", bg="#1E1E2E")
    lbl_time.pack()
    lbl_date.pack(pady=(6, 0))

    def tick():
        now = datetime.datetime.now()
        lbl_time.configure(text=now.strftime("%H:%M:%S"))
        lbl_date.configure(text=now.strftime("%Y年%m月%d日 %A"))
        f.after(200, tick)

    tick()
    return f


def _calendar_window(master):
    f = tk.Frame(master, bg="#FAFAFA", padx=12, pady=12)
    now = datetime.date.today()
    lbl = tk.Label(f, text=now.strftime("%Y年%m月"), font=("Microsoft YaHei UI", 13, "bold"))
    lbl.pack(pady=(0, 6))
    grid = tk.Frame(f)
    grid.pack()
    week = ["一", "二", "三", "四", "五", "六", "日"]
    for j, wd in enumerate(week):
        tk.Label(grid, text=wd, width=4, font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#00A4EF").grid(row=0, column=j, padx=1, pady=1)
    cal = calendar.monthcalendar(now.year, now.month)
    for i, wk in enumerate(cal, 1):
        for j, day in enumerate(wk):
            if day == 0:
                tk.Label(grid, text="", width=4).grid(row=i, column=j, padx=1, pady=1)
            else:
                fg = "#DC2626" if j == 6 else "#333333"
                bg = "#FFD54D" if (now.year, now.month, day) == (now.year, now.month, now.day) else "#FAFAFA"
                tk.Label(grid, text=str(day), width=4, fg=fg, bg=bg,
                         font=("Microsoft YaHei UI", 10, "bold")).grid(
                    row=i, column=j, padx=1, pady=1)
    return f


def _cpu_window(master):
    f = tk.Frame(master, bg="#0B1026", padx=20, pady=20)
    lbl = tk.Label(f, text="CPU 占用", font=("Microsoft YaHei UI", 11),
                   fg="#00A4EF", bg="#0B1026")
    lbl.pack()
    canvas = tk.Canvas(f, width=160, height=160, bg="#0B1026", highlightthickness=0)
    canvas.pack(pady=4)
    pct = tk.Label(f, text="--%", font=("Consolas", 26, "bold"), fg="#7FBA00", bg="#0B1026")
    pct.pack()
    state = {"last": None}

    def draw(usage):
        canvas.delete("all")
        cx, cy, r = 80, 80, 62
        canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=0, extent=359.9,
                          style="arc", width=12, outline="#2A2F4A")
        color = "#7FBA00" if usage < 60 else ("#FFB900" if usage < 85 else "#DC2626")
        canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-usage * 3.6,
                          style="arc", width=12, outline=color)
        canvas.create_text(cx, cy, text=f"{usage:.0f}%", fill="#FFFFFF",
                           font=("Consolas", 20, "bold"))

    def tick():
        u = get_cpu_usage()
        if u is None:
            pct.configure(text="N/A")
            canvas.delete("all")
            canvas.create_text(80, 80, text="N/A", fill="#888888", font=("Consolas", 18, "bold"))
        else:
            pct.configure(text=f"{u:.0f}%")
            draw(u)
        f.after(1200, tick)

    tick()
    return f


def make_tool_window(master, name):
    """在 master 下构建工具内容。返回 Frame。"""
    name = (name or "").lower()
    if name == "clock":
        return _clock_window(master)
    if name == "calendar":
        return _calendar_window(master)
    if name == "cpu":
        return _cpu_window(master)
    return None


def run_tool(args=None):
    import sys
    argv = args if args is not None else sys.argv[1:]
    tool = None
    for a in argv:
        if a.startswith("--"):
            tool = a[2:]
    if tool not in ("clock", "calendar", "cpu"):
        print("用法: python wpp_tools.py --clock|--calendar|--cpu")
        sys.exit(1)
    root = tk.Tk()
    root.title({"clock": "时钟", "calendar": "日历", "cpu": "CPU 仪表盘"}[tool])
    root.configure(bg="#1E1E2E")
    make_tool_window(root, tool).pack()
    root.mainloop()


if __name__ == "__main__":
    run_tool()
