#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_desklock — 桌面锁定页。

一键扫描桌面图标 / 逐图标锁定开关（配置持久化）/
全局锁定（自动排列，禁止拖乱）/ 被锁图标被移动·删除时弹窗提示（主框架负责）。
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox

from wpp import common as C


class PageDeskLock(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg="systemTransparent")
        self.app = app
        self.root = app.root
        self.icons = []            # [(name, is_dir, path)]
        self.locked = set()        # 已锁定图标名
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        self.global_var = tk.BooleanVar(value=self.app.settings.get("icon_lock", False))
        self.global_cb = ttk.Checkbutton(top, text="🔒 全局锁定（图标自动对齐网格，禁止拖乱）",
                                         variable=self.global_var, command=self._on_global)
        self.global_cb.pack(side="left", padx=(0, 12))
        self.scan_btn = ttk.Button(top, text="🔍 一键扫描桌面图标", command=self.on_scan)
        self.scan_btn.pack(side="left", padx=(0, 6))
        self.all_btn = ttk.Button(top, text="☑ 全部锁定", command=self.on_lock_all, state="disabled")
        self.all_btn.pack(side="left", padx=(0, 6))
        self.none_btn = ttk.Button(top, text="☐ 全部解锁", command=self.on_unlock_all, state="disabled")
        self.none_btn.pack(side="left")

        frame = ttk.Frame(self, padding=(10, 4))
        frame.pack(fill="both", expand=True)
        columns = ("chk", "name", "type", "path")
        headers = {"chk": "🔒", "name": "图标名称", "type": "类型", "path": "位置"}
        widths = {"chk": 44, "name": 240, "type": 90, "path": 520}
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        for c in columns:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="w", stretch=(c == "path"))
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.tag_configure("locked", foreground="#B45309")
        self.tree.tag_configure("free", foreground="#333333")

        hint = ttk.Label(self,
                         text="点击「🔒」列可单独锁定/解锁某个图标；锁定任意图标后，桌面进入锁定模式："
                              "图标无法被选中与拖动（从根本上阻止移动），双击仍可正常打开软件，"
                              "解锁全部图标即恢复。\n"
                              "顶部「全局锁定」开关：同时启用桌面图标自动排列。",
                         foreground="#888", padding=(10, 4), wraplength=1000)
        hint.pack(fill="x")

    def refresh(self):
        self.locked = set(self.app.settings.get("desk_locked_icons") or [])
        self.global_var.set(self.app.settings.get("icon_lock", False))
        self.on_scan()

    # ---------- 扫描 ----------
    def on_scan(self):
        self.app.set_status("正在扫描桌面图标…")
        icons = C.list_desktop_icons()
        self.icons = icons
        self._render()
        self.app.set_status(f"桌面共 {len(icons)} 个图标，已锁定 {len(self.locked)} 个")
        self.all_btn.configure(state="normal" if icons else "disabled")
        self.none_btn.configure(state="normal" if icons else "disabled")

    def _render(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for name, is_dir, path in self.icons:
            locked = name in self.locked
            chk = "🔒" if locked else ""
            typ = "文件夹" if is_dir else ("快捷方式" if name.lower().endswith((".lnk", ".url")) else "文件")
            self.tree.insert("", "end", values=(chk, name, typ, path),
                             tags=("locked" if locked else "free",))

    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        name = self.tree.set(item, "name")
        if name in self.locked:
            self.locked.discard(name)
        else:
            self.locked.add(name)
        self._save()
        self._render()
        self.app.set_status(f"桌面图标「{name}」已{'锁定' if name in self.locked else '解锁'}")

    def on_lock_all(self):
        for name, _, _ in self.icons:
            self.locked.add(name)
        self._save()
        self._render()

    def on_unlock_all(self):
        self.locked.clear()
        self._save()
        self._render()

    def _save(self):
        self.app.settings = C.save_settings(desk_locked_icons=sorted(self.locked))
        self.app.update_drag_guard()
        if self.locked:
            self.app.set_status(f"桌面图标锁定模式已启用：已锁定 {len(self.locked)} 个图标，图标不可拖动")
        else:
            self.app.set_status("已解锁全部图标，桌面恢复可拖动")

    # ---------- 全局锁定 ----------
    def _on_global(self):
        v = self.global_var.get()
        ok, msg = C.set_desktop_icon_lock(v)
        self.app.settings = C.save_settings(icon_lock=v)
        self.app.update_drag_guard()
        self.app.set_status(msg)
        if ok:
            messagebox.showinfo(
                C.APP_NAME,
                msg + "\n\n提示：若桌面图标未立即变化，请右键桌面 → 查看 → 勾选「自动排列图标」，"
                      "或重启资源管理器 / 重启电脑后生效。")
