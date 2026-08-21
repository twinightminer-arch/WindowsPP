#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_settings — 设置页。

颜色主题（Windows 色板）/ 背景图片·视频（含不透明度滑块、视频静音）/
背景音乐（独立音轨，视频未静音时优先视频音轨）。
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from wpp import common as C


def _has_pil():
    try:
        import PIL  # noqa
        return True
    except Exception:
        return False


class PageSettings(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        try:
            self.configure(bg="systemTransparent")
        except Exception:
            self.configure(bg="#FFFFFF")
        self.app = app
        self.root = app.root
        self._build_ui()

    def refresh(self):
        s = self.app.settings
        self.autostart_var.set(bool(s.get("autostart", False)))
        self.opacity_var.set(int(s.get("bg_opacity", 35)))
        self.opacity_lbl.configure(text=f"{self.opacity_var.get()}%")
        self.mute_var.set(bool(s.get("bg_mute", False)))
        self.bg_image_lbl.configure(text=os.path.basename(s.get("bg_image") or "") or "未设置")
        self.bg_video_lbl.configure(text=os.path.basename(s.get("bg_video") or "") or "未设置")
        self.music_lbl.configure(text=os.path.basename(s.get("bg_music") or "") or "未设置")
        self._highlight_theme()

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # 开机自启动
        f0 = ttk.LabelFrame(self, text="🚀 开机自启动", padding=8)
        f0.pack(fill="x", **pad)
        self.autostart_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f0, text="开机自动启动 Windows++（后台最小化运行，监控桌面）",
                        variable=self.autostart_var,
                        command=self._on_autostart).pack(anchor="w")
        ttk.Label(f0, text="勾选后写入注册表「启动」项，下次开机自动后台运行；取消勾选即移除。",
                  foreground="#888", font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(4, 0))

        # 颜色主题
        f1 = ttk.LabelFrame(self, text="🎨 颜色主题（点击即应用）", padding=8)
        f1.pack(fill="x", **pad)
        self._theme_btns = []
        grid = ttk.Frame(f1)
        grid.pack(anchor="w")
        for i, (name, color) in enumerate(C.THEME_COLORS):
            b = tk.Button(grid, text="", width=3, height=1, bg=color, relief="ridge",
                          bd=1, activebackground=color,
                          command=lambda c=color: self._on_theme(c))
            b.grid(row=i // 6, column=i % 6, padx=3, pady=3)
            self._theme_btns.append((b, color))
        self.theme_hint = ttk.Label(f1, text="", foreground="#555")
        self.theme_hint.pack(anchor="w")

        # 背景
        f2 = ttk.LabelFrame(self, text="🖼 背景设置", padding=8)
        f2.pack(fill="x", **pad)
        row1 = ttk.Frame(f2)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="背景图片:").pack(side="left")
        self.bg_image_lbl = ttk.Label(row1, text="未设置", width=26, foreground="#888")
        self.bg_image_lbl.pack(side="left", padx=4)
        ttk.Button(row1, text="选择图片", command=self._pick_image).pack(side="left", padx=2)
        ttk.Button(row1, text="移除", command=self._remove_image).pack(side="left", padx=2)
        row2 = ttk.Frame(f2)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="背景视频:").pack(side="left")
        self.bg_video_lbl = ttk.Label(row2, text="未设置", width=26, foreground="#888")
        self.bg_video_lbl.pack(side="left", padx=4)
        ttk.Button(row2, text="选择视频", command=self._pick_video).pack(side="left", padx=2)
        ttk.Button(row2, text="移除", command=self._remove_video).pack(side="left", padx=2)
        self.mute_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="视频静音（此时可另播背景音乐）",
                        variable=self.mute_var, command=self._on_mute).pack(side="left", padx=8)
        row3 = ttk.Frame(f2)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="背景不透明度:").pack(side="left")
        self.opacity_var = tk.IntVar(value=35)
        self.opacity_scale = ttk.Scale(row3, from_=0, to=100, variable=self.opacity_var,
                                       orient="horizontal", length=220,
                                       command=lambda v: self.opacity_lbl.configure(
                                           text=f"{int(float(v))}%"))
        self.opacity_scale.pack(side="left", padx=6)
        self.opacity_lbl = ttk.Label(row3, text="35%", width=5)
        self.opacity_lbl.pack(side="left")
        self.opacity_scale.bind("<ButtonRelease-1>", lambda e: self._apply_opacity())
        ttk.Label(f2, text="（图片背景需系统 Python 安装 pillow 才能缩放/调透明度）",
                  foreground="#888", font=("Microsoft YaHei UI", 8)).pack(anchor="w")

        # 背景音乐
        f3 = ttk.LabelFrame(self, text="🎵 背景音乐", padding=8)
        f3.pack(fill="x", **pad)
        row4 = ttk.Frame(f3)
        row4.pack(fill="x", pady=2)
        ttk.Label(row4, text="音乐文件:").pack(side="left")
        self.music_lbl = ttk.Label(row4, text="未设置", width=26, foreground="#888")
        self.music_lbl.pack(side="left", padx=4)
        ttk.Button(row4, text="选择音乐", command=self._pick_music).pack(side="left", padx=2)
        ttk.Button(row4, text="移除", command=self._remove_music).pack(side="left", padx=2)
        ttk.Label(f3, text="背景音乐在“背景视频未设置或已静音”时自动播放；设置后立即生效并循环播放。",
                  foreground="#888", font=("Microsoft YaHei UI", 8)).pack(anchor="w")

        ttk.Label(self, text="以上设置自动保存，重启程序后恢复。",
                  foreground="#555", padding=10).pack(anchor="w")

    # ---------- 开机自启动 ----------
    def _on_autostart(self):
        v = self.autostart_var.get()
        self.app.settings = C.save_settings(autostart=v)
        self.app.set_status("开机自启动已" + ("开启" if v else "关闭"))

    # ---------- 主题 ----------
    def _on_theme(self, color):
        self.app.apply_theme(color, save=True)
        self.app.set_status(f"已应用主题色 {color}")
        self.theme_hint.configure(text=f"当前主题色：{color}")
        self._highlight_theme()

    def _highlight_theme(self):
        cur = self.app.settings.get("theme") or "#0078D4"
        for b, color in self._theme_btns:
            b.configure(relief="ridge", bd=2 if color.lower() == cur.lower() else 1)

    # ---------- 背景 ----------
    def _pick_image(self):
        path = filedialog.askopenfilename(
            title="选择背景图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif"), ("所有文件", "*.*")])
        if not path:
            return
        self.app.settings = C.save_settings(bg_image=path)
        self.app._bg_apply()
        self.bg_image_lbl.configure(text=os.path.basename(path))
        if not _has_pil():
            messagebox.showwarning(C.APP_NAME,
                                   "未检测到 pillow 库，图片将以原尺寸显示。\n"
                                   "缩放/透明度功能需要 pillow（pip install pillow）。")
        self.app.set_status(f"背景图片已设置: {os.path.basename(path)}")

    def _remove_image(self):
        self.app.settings = C.save_settings(bg_image="")
        self.app._bg_apply()
        self.bg_image_lbl.configure(text="未设置")
        self.app.set_status("已移除背景图片")

    def _pick_video(self):
        path = filedialog.askopenfilename(
            title="选择背景视频",
            filetypes=[("视频", "*.mp4 *.avi *.wmv *.mov *.mkv *.mpg"), ("所有文件", "*.*")])
        if not path:
            return
        self.app.settings = C.save_settings(bg_video=path)
        self.app._bg_apply()
        self.bg_video_lbl.configure(text=os.path.basename(path))
        self.app.set_status(f"背景视频已设置: {os.path.basename(path)}")

    def _remove_video(self):
        self.app.settings = C.save_settings(bg_video="")
        self.app._bg_apply()
        self.bg_video_lbl.configure(text="未设置")
        self.app.set_status("已移除背景视频")

    def _on_mute(self):
        v = self.mute_var.get()
        self.app.settings = C.save_settings(bg_mute=v)
        self.app._bg_apply()
        if not v:
            self.app._music_apply()
        self.app.set_status("背景视频已静音，可播放独立背景音乐" if v else "背景视频已恢复声音")

    def _apply_opacity(self):
        v = int(self.opacity_var.get())
        self.app.settings = C.save_settings(bg_opacity=v)
        self.app._bg_apply()
        self.app.set_status(f"背景不透明度已设为 {v}%")

    # ---------- 音乐 ----------
    def _pick_music(self):
        path = filedialog.askopenfilename(
            title="选择背景音乐",
            filetypes=[("音频", "*.mp3 *.wav *.mid *.wma *.aac"), ("所有文件", "*.*")])
        if not path:
            return
        self.app.settings = C.save_settings(bg_music=path)
        self.music_lbl.configure(text=os.path.basename(path))
        if self.mute_var.get() or not (self.app.settings.get("bg_video") or ""):
            self.app._music_apply()
        self.app.set_status(f"背景音乐已设置: {os.path.basename(path)}")

    def _remove_music(self):
        self.app.settings = C.save_settings(bg_music="")
        self.music_lbl.configure(text="未设置")
        try:
            self.app._mci("close bgmusic")
        except Exception:
            pass
        self.app._music_on = False
        self.app.set_status("已移除背景音乐")
