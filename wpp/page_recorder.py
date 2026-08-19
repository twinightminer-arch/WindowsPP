#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_recorder — 录屏页。

- 区域截选：全屏半透明选择框拖拽框选（默认全屏）
- 快捷键：可设置（默认 Ctrl+H），全局热键触发开始/停止录制
- 保存位置：可自定义（默认 用户\\视频）
- 录制：ffmpeg（画面 + 音频 → mp4）
"""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from wpp import common as C
from wpp import recorder as R


class PageRecorder(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg="#FFFFFF")
        self.app = app
        self.root = app.root
        self.rec = R.Recorder()
        self.hotkey = None
        self._elapsed = 0
        self._build_ui()
        self._register_hotkey()

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        f0 = ttk.LabelFrame(self, text="📹 录屏控制", padding=8)
        f0.pack(fill="x", **pad)
        row = ttk.Frame(f0)
        row.pack(fill="x")
        self.start_btn = ttk.Button(row, text="⏺ 开始录制", command=self._toggle, style="Accent.TButton")
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(row, text="⏹ 停止录制", command=self._toggle, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8))
        self.time_lbl = ttk.Label(row, text="空闲", foreground="#555")
        self.time_lbl.pack(side="left", padx=8)
        self.rec_hint = ttk.Label(f0, text="", foreground="#888")
        self.rec_hint.pack(anchor="w", pady=(4, 0))

        f1 = ttk.LabelFrame(self, text="🎯 录制区域（开始录制前可截选）", padding=8)
        f1.pack(fill="x", **pad)
        row1 = ttk.Frame(f1)
        row1.pack(fill="x")
        self.region_lbl = ttk.Label(row1, text="", width=30, foreground="#555")
        self.region_lbl.pack(side="left", padx=(0, 8))
        ttk.Button(row1, text="✂ 截选录制区域", command=self._pick_region).pack(side="left", padx=2)
        ttk.Button(row1, text="🖥 默认全屏", command=self._region_fullscreen).pack(side="left", padx=2)

        f2 = ttk.LabelFrame(self, text="⌨ 全局快捷键（任意界面按下即开始/停止录制）", padding=8)
        f2.pack(fill="x", **pad)
        row2 = ttk.Frame(f2)
        row2.pack(fill="x")
        self.mod_ctrl = tk.BooleanVar(value=True)
        self.mod_alt = tk.BooleanVar(value=False)
        self.mod_shift = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="Ctrl", variable=self.mod_ctrl).pack(side="left", padx=2)
        ttk.Checkbutton(row2, text="Alt", variable=self.mod_alt).pack(side="left", padx=2)
        ttk.Checkbutton(row2, text="Shift", variable=self.mod_shift).pack(side="left", padx=2)
        ttk.Label(row2, text="+ 按键:").pack(side="left", padx=(12, 2))
        self.key_entry = ttk.Entry(row2, width=4)
        self.key_entry.pack(side="left")
        ttk.Button(row2, text="✔ 应用快捷键", command=self._apply_hotkey).pack(side="left", padx=6)

        f3 = ttk.LabelFrame(self, text="💾 保存位置", padding=8)
        f3.pack(fill="x", **pad)
        row3 = ttk.Frame(f3)
        row3.pack(fill="x")
        self.dir_lbl = ttk.Label(row3, text="", width=50, foreground="#555")
        self.dir_lbl.pack(side="left", padx=(0, 8))
        ttk.Button(row3, text="📂 选择保存位置", command=self._pick_dir).pack(side="left")
        ttk.Button(row3, text="📁 打开目录", command=self._open_dir).pack(side="left", padx=4)

        ttk.Label(self,
                  text="录制基于系统 ffmpeg（gdigrab 抓屏 + dshow 音频）。录制中可随时按快捷键停止；"
                       "文件将保存为 MP4。",
                  foreground="#888", padding=10).pack(anchor="w")

        self.refresh()
        self.root.after(500, self._tick)

    def refresh(self):
        s = self.app.settings
        region = s.get("rec_region") or ""
        self.region_lbl.configure(text=f"区域：{region}" if region else "区域：全屏")
        d = s.get("rec_dir") or R.default_videos_dir()
        self.dir_lbl.configure(text=d)
        # 快捷键 UI 回显
        spec = (s.get("rec_hotkey") or "ctrl+h").lower()
        self.mod_ctrl.set("ctrl" in spec)
        self.mod_alt.set("alt" in spec)
        self.mod_shift.set("shift" in spec)
        for ch in "abcdefghijklmnopqrstuvwxyz0123456789":
            if f"+{ch}" in spec:
                self.key_entry.delete(0, "end")
                self.key_entry.insert(0, ch.upper())
                break

    # ---------- 热键 ----------
    def _register_hotkey(self):
        spec = self.app.settings.get("rec_hotkey") or "ctrl+h"
        parsed = R.parse_hotkey(spec)
        if not parsed:
            return
        mods, vk = parsed
        if self.hotkey is not None:
            self.hotkey.stop()
        self.hotkey = R.HotKey(mods, vk, lambda: self.root.after(0, self._on_hotkey))
        self.hotkey.start()

    def _apply_hotkey(self):
        parts = []
        if self.mod_ctrl.get():
            parts.append("ctrl")
        if self.mod_alt.get():
            parts.append("alt")
        if self.mod_shift.get():
            parts.append("shift")
        key = (self.key_entry.get() or "").strip()[:1]
        if not parts or not key:
            messagebox.showwarning(C.APP_NAME, "请至少选择一个修饰键（Ctrl/Alt/Shift）并输入一个按键字母。")
            return
        spec = "+".join(parts) + "+" + key.lower()
        self.app.settings = C.save_settings(rec_hotkey=spec)
        self._register_hotkey()
        self.app.set_status(f"录屏快捷键已设置为 {spec.upper()}")

    def _on_hotkey(self):
        if self.rec.recording:
            self._stop_rec()
        else:
            self._start_rec()

    # ---------- 录制 ----------
    def _toggle(self):
        if self.rec.recording:
            self._stop_rec()
        else:
            self._start_rec()

    def _start_rec(self):
        if self.rec.recording:
            return
        if R.find_ffmpeg() is None:
            messagebox.showwarning(C.APP_NAME, "未找到 ffmpeg，无法录制。\n请安装 ffmpeg 并加入 PATH（https://ffmpeg.org）。")
            return
        region = None
        r = (self.app.settings.get("rec_region") or "").strip()
        if r:
            try:
                x, y, w, h = [int(v) for v in r.split(",")]
                region = (x, y, w, h)
            except (ValueError, TypeError):
                region = None
        out_dir = self.app.settings.get("rec_dir") or R.default_videos_dir()
        ok = self.rec.start(region=region, out_dir=out_dir, fps=10, audio=True)
        if not ok:
            messagebox.showerror(C.APP_NAME, f"录制启动失败：{self.rec.error or '未知错误'}")
            return
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.time_lbl.configure(text="录制中 00:00")
        self.rec_hint.configure(text=f"录制中：{os.path.basename(self.rec.out_path or '')}  （再按快捷键或点「停止」结束）")
        self.app.set_status("正在录屏（画面 + 音频）…")
        self._elapsed = 0

    def _stop_rec(self):
        path = self.rec.stop()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.time_lbl.configure(text="空闲")
        self.rec_hint.configure(text="")
        if path:
            self.app.set_status(f"录屏已保存：{path}")
            if messagebox.askyesno(C.APP_NAME,
                                   f"录屏已保存到：\n{path}\n\n是否打开所在文件夹？"):
                try:
                    os.startfile(os.path.dirname(path))
                except Exception:
                    pass
        else:
            messagebox.showwarning(C.APP_NAME, "录制结束，但未生成有效文件（可能录制时间过短或 ffmpeg 出错）。")

    def _tick(self):
        if self.rec.recording:
            self._elapsed += 0.5
            m, s = divmod(int(self._elapsed), 60)
            self.time_lbl.configure(text=f"录制中 {m:02d}:{s:02d}")
        self.root.after(500, self._tick)

    # ---------- 区域截选 ----------
    def _pick_region(self):
        dlg = tk.Toplevel(self.root)
        dlg.overrideredirect(True)
        dlg.attributes("-alpha", 0.25, "-topmost", True)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        dlg.geometry(f"{sw}x{sh}+0+0")
        cv = tk.Canvas(dlg, cursor="cross", bg="#000000", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        state = {"x0": 0, "y0": 0, "rect": None, "done": False}

        def on_down(e):
            state["x0"], state["y0"] = e.x, e.y
            state["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y,
                                                outline="#DC2626", width=2)

        def on_move(e):
            if state["rect"]:
                cv.coords(state["rect"], state["x0"], state["y0"], e.x, e.y)

        def on_up(e):
            if state["done"]:
                return
            state["done"] = True
            x0, x1 = sorted((state["x0"], e.x))
            y0, y1 = sorted((state["y0"], e.y))
            dlg.destroy()
            if (x1 - x0) < 10 or (y1 - y0) < 10:
                self._region_fullscreen()
                return
            self.app.settings = C.save_settings(rec_region=f"{x0},{y0},{x1-x0},{y1-y0}")
            self.refresh()
            self.app.set_status(f"录制区域已设置：({x0},{y0}) {x1-x0}x{y1-y0}")

        def on_esc(e):
            state["done"] = True
            dlg.destroy()
            self._region_fullscreen()

        cv.bind("<ButtonPress-1>", on_down)
        cv.bind("<B1-Motion>", on_move)
        cv.bind("<ButtonRelease-1>", on_up)
        dlg.bind("<Escape>", on_esc)
        dlg.focus_force()

    def _region_fullscreen(self):
        self.app.settings = C.save_settings(rec_region="")
        self.refresh()
        self.app.set_status("录制区域：全屏")

    # ---------- 保存位置 ----------
    def _pick_dir(self):
        d = filedialog.askdirectory(title="选择录屏保存位置",
                                    initialdir=self.app.settings.get("rec_dir") or R.default_videos_dir())
        if not d:
            return
        self.app.settings = C.save_settings(rec_dir=d)
        self.refresh()
        self.app.set_status(f"录屏保存位置已设为：{d}")

    def _open_dir(self):
        d = self.app.settings.get("rec_dir") or R.default_videos_dir()
        try:
            os.startfile(d)
        except Exception as e:
            messagebox.showerror(C.APP_NAME, f"打开目录失败: {e}")
