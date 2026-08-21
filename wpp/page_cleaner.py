#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_cleaner — 扫描清理旧软件页。

全盘扫描两类垃圾：软件旧版本残留目录、下载但未清理的安装包。
带进度条 / 勾选列表 / 全选·全不选 / 清理选中（确认后执行）。
"""

import os
import time
import queue
import threading
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from wpp import common as C


class PageCleaner(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        try:
            self.configure(bg="systemTransparent")
        except Exception:
            self.configure(bg="#FFFFFF")
        self.app = app
        self.root = app.root
        self.busy = False
        self.results = []          # [{type, name, path, size, extra}]
        self._queue = queue.Queue()
        self._build_ui()
        self.root.after(200, self._poll)

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        self.scan_btn = ttk.Button(top, text="🔍 开始扫描", command=self.on_scan)
        self.scan_btn.pack(side="left", padx=(0, 6))
        self.selall_btn = ttk.Button(top, text="☑ 全选", command=self.on_sel_all, state="disabled")
        self.selall_btn.pack(side="left", padx=(0, 6))
        self.selnone_btn = ttk.Button(top, text="☐ 全不选", command=self.on_sel_none, state="disabled")
        self.selnone_btn.pack(side="left", padx=(0, 6))
        self.clean_btn = ttk.Button(top, text="🗑 清理选中（勾选项）", command=self.on_clean, state="disabled")
        self.clean_btn.pack(side="left", padx=(0, 6))
        self.progress = ttk.Progressbar(top, length=260, mode="determinate", maximum=100)
        self.progress.pack(side="right", padx=6)
        self.pct_lbl = ttk.Label(top, text="0%")
        self.pct_lbl.pack(side="right")

        frame = ttk.Frame(self, padding=(10, 4))
        frame.pack(fill="both", expand=True)
        columns = ("chk", "type", "name", "size", "path")
        headers = {"chk": "✔", "type": "类型", "name": "名称", "size": "大小", "path": "位置"}
        widths = {"chk": 36, "type": 90, "name": 260, "size": 90, "path": 520}
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        for c in columns:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="w", stretch=(c == "path"))
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("oldver", foreground="#B45309")
        self.tree.tag_configure("installer", foreground="#2563EB")
        self.tree.bind("<Button-1>", self._on_click)

        hint = ttk.Label(self,
                         text="旧版本残留：仅检测“同目录并存多版本”的旧程序目录（保留最新，不碰登录/数据）。"
                              "安装包：下载/临时目录中的 .exe/.msi 等。均需勾选确认后才会删除。",
                         foreground="#888", padding=(10, 4))
        hint.pack(fill="x")

    # ---------- 扫描 ----------
    def on_scan(self):
        if self.busy:
            return
        self.busy = True
        self.scan_btn.configure(state="disabled")
        self.progress.configure(value=0)
        self.pct_lbl.configure(text="0%")
        self._clear_table()
        self.app.set_status("正在扫描旧版本残留与安装包…")

        def worker():
            # 阶段1：旧版本残留（0-70%）
            installed = C.get_installed_from_registry()
            rows = [{"name": a["name"], "install_loc": a["install_loc"],
                     "uninstall": a["uninstall"], "version": a["version"]} for a in installed]
            self._queue.put(("prog", 20))
            findings = C.scan_old_version_dirs(rows)
            old_items = [{"type": "旧版本", "name": app, "path": full,
                          "size": _dir_size(full), "extra": ver,
                          "tag": "oldver", "checked": True}
                         for app, parent, full, ver in findings]
            self._queue.put(("prog", 70))
            # 阶段2：安装包（70-100%）
            pkgs = C.scan_installers()
            inst_items = [{"type": "安装包", "name": os.path.basename(p["path"]),
                           "path": p["path"], "size": p["size"], "extra": "",
                           "tag": "installer", "checked": True} for p in pkgs]
            self._queue.put(("prog", 100))
            self._queue.put(("done", old_items, inst_items))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_table(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.results = []

    def _on_click(self, event):
        if self.busy:
            return
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        row = self.tree.item(item)
        vals = row["values"]
        for r in self.results:
            if r["path"] == vals[4]:
                r["checked"] = not r["checked"]
                self.tree.set(item, "chk", "✔" if r["checked"] else "")
                break
        # 同步“清理选中”按钮状态：只要有勾选项即可点击
        self.clean_btn.configure(
            state="normal" if any(r["checked"] for r in self.results) else "disabled")

    def _poll(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "prog":
                    v = msg[1]
                    self.progress.configure(value=v)
                    self.pct_lbl.configure(text=f"{int(v)}%")
                elif kind == "done":
                    old_items, inst_items = msg[1], msg[2]
                    self.results = old_items + inst_items
                    self._render()
                    total_mb = sum(r["size"] for r in self.results) / 1048576
                    self.app.set_status(
                        f"扫描完成：旧版本 {len(old_items)} 项，安装包 {len(inst_items)} 项，共 {total_mb:.1f} MB")
                    self.busy = False
                    self.scan_btn.configure(state="normal")
                elif kind == "log":
                    self.app.set_status(msg[1][:60])
                elif kind == "cleaned":
                    ok, fail, freed = msg[1], msg[2], msg[3]
                    self.app.set_status(f"清理完成：删除 {ok} 个，失败 {fail} 个，释放 {freed/1048576:.1f} MB")
                    self.busy = False
                    self.on_scan()   # 清理后重新扫描刷新列表
        except queue.Empty:
            pass
        self.root.after(200, self._poll)

    def _render(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in self.results:
            chk = "✔" if r["checked"] else ""
            size_txt = f"{r['size']/1048576:.1f} MB" if r["size"] else "—"
            name_txt = r["name"]
            if r["type"] == "旧版本":
                name_txt += f"（旧版本 {r['extra']}）"
            self.tree.insert("", "end", values=(chk, r["type"], name_txt, size_txt, r["path"]),
                             tags=(r["tag"],))
        has = bool(self.results)
        self.selall_btn.configure(state="normal" if has else "disabled")
        self.selnone_btn.configure(state="normal" if has else "disabled")
        self.clean_btn.configure(state="normal" if any(r["checked"] for r in self.results) else "disabled")

    # ---------- 选择 / 清理 ----------
    def on_sel_all(self):
        for r in self.results:
            r["checked"] = True
        self._render()

    def on_sel_none(self):
        for r in self.results:
            r["checked"] = False
        self._render()

    def on_clean(self):
        if self.busy:
            return
        chosen = [r for r in self.results if r["checked"]]
        if not chosen:
            messagebox.showinfo(C.APP_NAME, "请先勾选要清理的项目")
            return
        total_mb = sum(r["size"] for r in chosen) / 1048576
        names = "\n".join(f"· [{r['type']}] {r['name']}\n    {r['path']}" for r in chosen[:20])
        if len(chosen) > 20:
            names += f"\n  … 等共 {len(chosen)} 项"
        if not messagebox.askyesno(
                C.APP_NAME,
                f"即将删除以下 {len(chosen)} 项（共 {total_mb:.1f} MB）：\n\n{names}\n\n"
                f"⚠️ 删除后不可恢复；旧版本清理不会触碰登录与使用数据。\n确定继续？",
                icon="warning"):
            return
        self.busy = True
        self.clean_btn.configure(state="disabled")
        self.app.set_status("正在清理…")

        def worker():
            ok = fail = 0
            freed = 0
            for r in chosen:
                okk, msg = C.safe_delete_path(r["path"])
                ok += okk
                fail += (not okk)
                freed += r["size"] if okk else 0
                self._queue.put(("log", msg))
            self._queue.put(("cleaned", ok, fail, freed))

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        pass


def _dir_size(path):
    """粗略估算目录大小（MB 单位换算为字节）；失败返回 0。"""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total
