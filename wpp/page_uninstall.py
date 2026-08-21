#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_uninstall — 软件卸载页。

已装软件列表（搜索 / 按名称·大小·日期排序）/ 调用系统卸载程序 / 进度反馈。
卸载为高风险操作：仅调用系统卸载入口，绝不静默删除。
"""

import os
import re
import time
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from wpp import common as C


def _build_uninstall_cmd(entry):
    """把注册表 UninstallString 转换成真正的卸载命令。
    返回 (cmd, is_silent_hint) 或 None（无卸载入口）。"""
    u = (entry.get("uninstall") or "").strip()
    if not u:
        return None
    # msiexec 安装命令 -> 卸载命令
    m = re.search(r"MsiExec\.exe\s*(?:/i|/I)\s*\{?([0-9A-Fa-f\-]{20,})\}?", u)
    if m:
        return f'msiexec /x {{{m.group(1)}}}', False
    if "MsiExec" in u and "/X" in u:
        return u, False
    return u, False


class PageUninstall(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        try:
            self.configure(bg="systemTransparent")
        except Exception:
            self.configure(bg="#FFFFFF")
        self.app = app
        self.root = app.root
        self.entries = []
        self.busy = False
        self.uninstalling = False
        self._queue = queue.Queue()
        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="搜索:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._apply_filter())
        self.search_entry = ttk.Entry(top, textvariable=self.search_var, width=24)
        self.search_entry.pack(side="left", padx=(4, 12))
        ttk.Label(top, text="排序:").pack(side="left")
        self.sort_var = tk.StringVar(value="按名称")
        self.sort_cb = ttk.Combobox(top, textvariable=self.sort_var, state="readonly", width=12,
                                    values=["按名称", "按大小", "按安装日期"])
        self.sort_cb.pack(side="left", padx=(4, 12))
        self.sort_cb.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())
        self.refresh_btn = ttk.Button(top, text="🔄 刷新列表", command=self.on_refresh)
        self.refresh_btn.pack(side="left", padx=(0, 6))
        self.uninst_btn = ttk.Button(top, text="🗑 卸载选中", command=self.on_uninstall, state="disabled")
        self.uninst_btn.pack(side="left")

        frame = ttk.Frame(self, padding=(10, 4))
        frame.pack(fill="both", expand=True)
        columns = ("name", "publisher", "version", "size", "date")
        headers = {"name": "软件名称", "publisher": "发布者", "version": "版本",
                   "size": "大小(MB)", "date": "安装日期"}
        widths = {"name": 320, "publisher": 180, "version": 120, "size": 90, "date": 100}
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        for c in columns:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="w" if c == "name" else "center",
                             stretch=(c == "name"))
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.on_uninstall())

        hint = ttk.Label(self, text="提示：卸载会调用软件自带的卸载程序，部分会弹出卸载向导。卸载不可恢复，请谨慎操作。",
                         foreground="#888", padding=(10, 4))
        hint.pack(fill="x")

        self._logf = ttk.LabelFrame(self, text="卸载日志", padding=(6, 2))
        self._logf.pack(fill="x", padx=10, pady=(0, 8))
        self.log_text = tk.Text(self._logf, height=4, state="disabled",
                                font=("Consolas", 9), bg="#FAFAFA")
        self.log_text.pack(fill="x")

        self.on_refresh()
        self.root.after(300, self._poll)

    # ---------- 数据 ----------
    def refresh(self):
        if not self.entries:
            self.on_refresh()

    def on_refresh(self):
        if self.busy:
            return
        self.busy = True
        self.app.set_status("正在读取已安装软件…")

        def worker():
            entries = C.get_installed_from_registry()
            self.root.after(0, lambda: self._done(entries))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, entries):
        self.entries = entries
        self._apply_filter()
        self.busy = False
        self.app.set_status(f"共 {len(entries)} 个已安装软件")

    def _fmt_date(self, d):
        if len(d) == 8 and d.isdigit():
            return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        return d

    def _apply_filter(self):
        q = self.search_var.get().strip().lower()
        rows = [e for e in self.entries if not q or q in e["name"].lower() or q in e["publisher"].lower()]
        sort = self.sort_var.get()
        if sort == "按大小":
            rows.sort(key=lambda e: -e["size_mb"])
        elif sort == "按安装日期":
            rows.sort(key=lambda e: e["inst_date"], reverse=True)
        else:
            rows.sort(key=lambda e: e["name"].lower())
        for i in self.tree.get_children():
            self.tree.delete(i)
        for e in rows:
            self.tree.insert("", "end", values=(
                e["name"], e["publisher"] or "—", e["version"] or "—",
                e["size_mb"] or "—", self._fmt_date(e["inst_date"]) or "—"))
        self.uninst_btn.configure(state="normal" if rows else "disabled")

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ---------- 卸载 ----------
    def on_uninstall(self):
        if self.busy or self.uninstalling:
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(C.APP_NAME, "请先选择一个要卸载的软件")
            return
        idx = self.tree.index(sel[0])
        q = self.search_var.get().strip().lower()
        rows = [e for e in self.entries if not q or q in e["name"].lower() or q in e["publisher"].lower()]
        rows.sort(key=lambda e: e["name"].lower())
        entry = rows[idx]
        cmd = _build_uninstall_cmd(entry)
        if cmd is None:
            messagebox.showwarning(C.APP_NAME,
                                   f"「{entry['name']}」没有提供卸载入口（可能为绿色/便携软件）。\n"
                                   f"可尝试手动删除其安装目录: {entry['install_loc'] or '未知'}")
            return
        if not messagebox.askyesno(
                C.APP_NAME,
                f"即将卸载软件：\n\n  {entry['name']}  {entry['version'] or ''}\n"
                f"  发布者：{entry['publisher'] or '未知'}\n\n"
                f"⚠️ 卸载后不可恢复，相关数据可能被清除！\n确定继续？",
                icon="warning"):
            return
        self.uninstalling = True
        self.uninst_btn.configure(state="disabled")
        self.app.set_status(f"正在卸载 {entry['name']} …")
        self._log(f"🗑 开始卸载 {entry['name']}（{cmd[0][:80]}…）")
        threading.Thread(target=self._uninstall_worker, args=(entry, cmd[0]), daemon=True).start()

    def _uninstall_worker(self, entry, cmd):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="ignore",
                                    shell=True, startupinfo=C._startupinfo())
        except Exception as e:
            self._queue.put(("fail", f"启动卸载程序失败: {e}"))
            return
        start = time.time()
        while proc.poll() is None:
            if time.time() - start > 180:
                self._queue.put(("note", "卸载程序运行超过 3 分钟，可能弹出向导等待确认；"
                                         "完成后可点击「🔄 刷新列表」查看结果。"))
                break
            time.sleep(0.5)
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        self._queue.put(("done", entry["name"], (out or "")[-300:], (err or "")[-300:]))

    def _poll(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                if msg[0] == "done":
                    _, name, out, err = msg
                    self._log(f"✅ {name} 的卸载程序已退出，正在刷新列表…")
                    self.app.set_status(f"{name} 卸载程序已退出")
                    if out.strip():
                        self._log("输出: " + out.strip()[-200:])
                    if err.strip():
                        self._log("错误: " + err.strip()[-200:])
                    self.uninstalling = False
                    self.on_refresh()
                elif msg[0] == "fail":
                    self._log("✘ " + msg[1])
                    self.uninstalling = False
                    self.uninst_btn.configure(state="normal")
                    self.app.set_status("卸载启动失败")
                elif msg[0] == "note":
                    self._log(msg[1])
        except queue.Empty:
            pass
        self.root.after(300, self._poll)
