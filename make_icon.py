#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Windows++ 用的微软四色格子 .ico 图标（多尺寸，PNG 内嵌式）。"""
import struct
import os
import tkinter as tk

MS_RED    = "#F25022"
MS_GREEN  = "#7FBA00"
MS_BLUE   = "#00A4EF"
MS_YELLOW = "#FFB900"

def make_png(size):
    img = tk.PhotoImage(width=size, height=size)
    h = size // 2
    img.put(MS_RED,    to=(0, 0, h, h))
    img.put(MS_GREEN,  to=(h, 0, size, h))
    img.put(MS_BLUE,   to=(0, h, h, size))
    img.put(MS_YELLOW, to=(h, h, size, size))
    return img

def main():
    root = tk.Tk()
    root.withdraw()
    sizes = [16, 32, 48, 256]
    pngs = []
    for s in sizes:
        img = make_png(s)
        tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"_tmp_{s}.png")
        img.write(tmp, format="png")
        with open(tmp, "rb") as f:
            pngs.append((s, f.read()))
        os.remove(tmp)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "WindowsPP.ico")
    n = len(pngs)
    header = struct.pack("<HHH", 0, 1, n)
    entries = b""
    data = b""
    offset = 6 + 16 * n
    for s, png in pngs:
        w = s if s < 256 else 0
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    with open(out, "wb") as f:
        f.write(header + entries + data)
    root.destroy()
    print(f"OK: {out} ({os.path.getsize(out)} bytes, sizes={sizes})")

if __name__ == "__main__":
    main()
