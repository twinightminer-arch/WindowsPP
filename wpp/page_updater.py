#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_updater — 软件更新页（v2.0 全部功能迁移）。

扫描 / 批量更新（暂停·继续·跳过当前·取消当前·取消全部）/
实时状态 / 右键取消勾选 / 导出报告 / 旧版文件扫描·杀出 / 清除安装包。
"""

import os
import re
import time
import queue
import threading
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from wpp import common as C


class PageUpdater(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg="systemTransparent")
        self.app = app
        self.root = app.root

        self.rows = []
        self.item_row = {}
        self.busy = False
        self.pause_evt = threading.Event()
        self.cancel_all = threading.Event()
        self.cancel_current = threading.Event()
        self.skip_current = threading.Event()
        self.proc = None
        self._queue = queue.Queue()
        self.clean_old_opt = False
        self.clean_inst_opt = False

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 6))
        top.pack(fill="x")
        ttk.Label(top, text="扫描 → 勾选可更新项（右键可取消）→ 开始更新，可暂停/跳过/取消",
                  font=("Microsoft YaHei UI", 9)).pack(side="left")

        btns = ttk.Frame(self, padding=(10, 0))
        btns.pack(fill="x")
        self.scan_btn = ttk.Button(btns, text="🔄 扫描并检查更新", command=self.on_scan)
        self.scan_btn.pack(side="left", padx=(0, 5))
        self.update_btn = ttk.Button(btns, text="⬆ 开始更新（选中项）", command=self.on_update, state="disabled")
        self.update_btn.pack(side="left", padx=(0, 5))
        self.selall_btn = ttk.Button(btns, text="☑ 全选可更新项", command=self.on_select_updatable, state="disabled")
        self.selall_btn.pack(side="left", padx=(0, 5))
        self.export_btn = ttk.Button(btns, text="📄 导出报告", command=self.on_export, state="disabled")
        self.export_btn.pack(side="left", padx=(0, 5))

        btns2 = ttk.Frame(self, padding=(10, 2))
        btns2.pack(fill="x")
        ttk.Label(btns2, text="更新控制：", foreground="#555").pack(side="left")
        self.pause_btn = ttk.Button(btns2, text="⏸ 暂停更新", command=self.on_pause_toggle, state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 5))
        self.skip_btn = ttk.Button(btns2, text="⏭ 跳过当前", command=self.on_skip_current, state="disabled")
        self.skip_btn.pack(side="left", padx=(0, 5))
        self.cancelcur_btn = ttk.Button(btns2, text="✖ 取消当前", command=self.on_cancel_current, state="disabled")
        self.cancelcur_btn.pack(side="left", padx=(0, 5))
        self.cancelall_btn = ttk.Button(btns2, text="⏹ 取消全部", command=self.on_cancel_all, state="disabled")
        self.cancelall_btn.pack(side="left", padx=(0, 5))
        self.clean_old_btn = ttk.Button(btns2, text="🧹 清理旧版本文件", command=self.on_clean_old, state="disabled")
        self.clean_old_btn.pack(side="left", padx=(5, 0))
        self.scan_old_btn = ttk.Button(btns2, text="🔍 扫描旧版文件", command=self.on_scan_old, state="disabled")
        self.scan_old_btn.pack(side="left", padx=(5, 0))
        self.clean_inst_btn = ttk.Button(btns2, text="🗑 清除安装包", command=self.on_clean_installers)
        self.clean_inst_btn.pack(side="left", padx=(5, 0))

        columns = ("chk", "name", "version", "available", "status", "source", "publisher")
        headers = {"chk": "✔", "name": "软件名称", "version": "当前版本",
                   "available": "最新版本", "status": "状态",
                   "source": "来源", "publisher": "发布者"}
        widths = {"chk": 36, "name": 300, "version": 110, "available": 110,
                  "status": 90, "source": 70, "publisher": 140}
        frame = ttk.Frame(self, padding=(10, 4))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        for c in columns:
            self.tree.heading(c, text=headers[c])
            anchor = "center" if c in ("chk", "version", "available", "status", "source") else "w"
            self.tree.column(c, width=widths[c], anchor=anchor, stretch=(c == "name"))
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("updatable", foreground="#B45309")
        self.tree.tag_configure("latest", foreground="#16A34A")
        self.tree.tag_configure("unknown", foreground="#6B7280")
        for tag, color in C.UPD_STATE_COLOR.items():
            self.tree.tag_configure(tag, foreground=color)

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self._ctx_item = None
        self.ctx_menu = tk.Menu(self, tearoff=0)
        self.ctx_menu.add_command(label="☐ 取消勾选（不更新）", command=self._ctx_uncheck)
        self.ctx_menu.add_command(label="☑ 重新勾选", command=self._ctx_check)

        logf = ttk.LabelFrame(self, text="执行日志", padding=(6, 2))
        logf.pack(fill="both", padx=10, pady=(4, 8))
        self.log_text = tk.Text(logf, height=6, state="disabled",
                                font=("Consolas", 9), bg="#FAFAFA")
        logvsb = ttk.Scrollbar(logf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=logvsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        logvsb.pack(side="right", fill="y")

    # ---------- 工具 ----------
    def refresh(self):
        pass

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.scan_btn.configure(state=state)
        self.export_btn.configure(state=state if self.rows else "disabled")
        if busy:
            self.update_btn.configure(state="disabled")
            self.selall_btn.configure(state="disabled")
            self.clean_old_btn.configure(state="disabled")
            self.scan_old_btn.configure(state="disabled")
            self.clean_inst_btn.configure(state="disabled")
            self.pause_btn.configure(state="normal")
            self.skip_btn.configure(state="normal")
            self.cancelcur_btn.configure(state="normal")
            self.cancelall_btn.configure(state="normal")
        else:
            self.update_btn.configure(state="normal" if self.rows else "disabled")
            self.selall_btn.configure(state="normal" if self.rows else "disabled")
            self.clean_old_btn.configure(state="normal" if self.rows else "disabled")
            self.scan_old_btn.configure(state="normal" if self.rows else "disabled")
            self.clean_inst_btn.configure(state="normal")
            self.pause_btn.configure(state="disabled", text="⏸ 暂停更新")
            self.skip_btn.configure(state="disabled")
            self.cancelcur_btn.configure(state="disabled")
            self.cancelall_btn.configure(state="disabled")

    # ---------- 勾选交互 ----------
    def _on_click(self, event):
        if self.busy:
            return
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        row = self.item_row.get(item) if item else None
        if row and row["status"] == "updatable":
            self._set_checked(item, row, not row.get("checked", False))

    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        row = self.item_row.get(item) if item else None
        if not row or row["status"] != "updatable":
            return
        self.tree.selection_set(item)
        self._ctx_item = item
        try:
            self.ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.ctx_menu.grab_release()

    def _ctx_uncheck(self):
        item, row = self._ctx_item, None
        if item:
            row = self.item_row.get(item)
        if item and row:
            self._set_checked(item, row, False)
            self.log(f"已取消勾选: {row['name']}")

    def _ctx_check(self):
        item = self._ctx_item
        row = self.item_row.get(item) if item else None
        if item and row:
            self._set_checked(item, row, True)

    def _set_checked(self, item, row, value):
        row["checked"] = value
        self.tree.set(item, "chk", "✔" if value else "")

    # ---------- 扫描 ----------
    def on_scan(self):
        if self.busy:
            return
        self.set_busy(True)
        self.app.set_status("正在扫描…")
        self.log("开始扫描：读取注册表 + winget upgrade …")

        def worker():
            installed = C.get_installed_from_registry()
            upgrades, err = C.get_winget_upgrades()
            self.root.after(0, lambda: self._scan_done(installed, upgrades, err))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_done(self, installed, upgrades, err):
        if err:
            self.log(f"winget 检查失败: {err}")
        rows = C.merge_status(installed, upgrades)
        self.rows = rows
        self.item_row.clear()
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in rows:
            if r["status"] == "updatable":
                r["checked"] = True
                chk, st_text = "✔", "可更新"
            elif r["status"] == "latest":
                r["checked"] = False
                chk, st_text = "", "已是最新"
            else:
                r["checked"] = False
                chk, st_text = "", "—"
            avail = r["available"] or ("—" if r["status"] == "unknown" else "")
            item = self.tree.insert("", "end", values=(
                chk, r["name"], r["version"] or "—", avail, st_text,
                r["source"] or "—", r["publisher"] or "—"), tags=(r["status"],))
            self.item_row[item] = r
        n_up = sum(1 for r in rows if r["status"] == "updatable")
        n_latest = sum(1 for r in rows if r["status"] == "latest")
        self.app.set_status(f"共 {len(rows)} 个软件，{n_up} 个可更新，{n_latest} 个已是最新")
        self.log(f"扫描完成：可更新 {n_up} 个，已是最新 {n_latest} 个")
        self.set_busy(False)

    def on_select_updatable(self):
        for item, row in self.item_row.items():
            if row["status"] == "updatable":
                self._set_checked(item, row, True)
        self.log("已全选所有可更新项")

    # ---------- 更新 ----------
    def on_update(self):
        if self.busy:
            return
        targets = [r for r in self.rows if r.get("checked") and r["status"] == "updatable"]
        if not targets:
            messagebox.showinfo(C.APP_NAME, "请先勾选至少一个可更新的软件（点击第一列 ✔）")
            return
        opts = self._ask_update_options(targets)
        if opts is None:
            return
        self.clean_old_opt, self.clean_inst_opt = opts
        for r in targets:
            r["upd_state"] = "pending"
        self.pause_evt.clear()
        self.cancel_all.clear()
        self.cancel_current.clear()
        self.skip_current.clear()
        self.set_busy(True)
        self.app.set_status(f"正在更新 0/{len(targets)} …")
        self.log(f"开始更新 {len(targets)} 个软件…")
        threading.Thread(target=self._update_worker, args=(targets,), daemon=True).start()
        self.root.after(200, self._poll_update)

    def _ask_update_options(self, targets):
        dlg = tk.Toplevel(self.root)
        dlg.title("确认更新")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 60, self.root.winfo_rooty() + 60))
        result = {"v": None}
        head = ttk.LabelFrame(dlg, text=f"即将通过 winget 更新 {len(targets)} 个软件", padding=8)
        head.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        txt = tk.Text(head, height=8, width=72, font=("Microsoft YaHei UI", 9))
        for r in targets:
            txt.insert("end", f"· {r['name']}  {r['version']} → {r['available']}\n")
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)
        optf = ttk.LabelFrame(dlg, text="更新后处理（可勾选）", padding=8)
        optf.pack(fill="x", padx=10, pady=4)
        v1 = tk.BooleanVar(value=True)
        v2 = tk.BooleanVar(value=False)
        ttk.Checkbutton(optf, text="✔ 清理旧版本文件残留（保留登录与使用数据）", variable=v1).pack(anchor="w")
        ttk.Checkbutton(optf, text="✔ 扫描并清除下载目录中的安装包", variable=v2).pack(anchor="w")
        ttk.Label(optf, text="更新可能需几分钟到十几分钟，部分软件更新完可能要求重启。",
                  foreground="#888", font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(4, 0))
        btns = ttk.Frame(dlg, padding=(10, 8))
        btns.pack(fill="x")

        def ok():
            result["v"] = (v1.get(), v2.get())
            dlg.destroy()

        def cancel():
            result["v"] = None
            dlg.destroy()

        ttk.Button(btns, text="开始更新", command=ok).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="取消", command=cancel).pack(side="right")
        dlg.bind("<Escape>", lambda e: cancel())
        dlg.wait_window()
        return result["v"]

    def on_pause_toggle(self):
        if self.pause_evt.is_set():
            self.pause_evt.clear()
            self.pause_btn.configure(text="⏸ 暂停更新")
            self.app.set_status("已继续，正在更新…")
        else:
            self.pause_evt.set()
            self.pause_btn.configure(text="▶ 继续更新")
            self.app.set_status("已暂停（等待中的软件不会开始）")

    def on_skip_current(self):
        if self.proc is not None:
            self.skip_current.set()
            self.log("⏭ 正在跳过当前软件…")
            return
        self.skip_current.set()
        self.log("⏭ 已设置：将跳过下一个待更新的软件")

    def on_cancel_current(self):
        if self.proc is None:
            messagebox.showinfo(C.APP_NAME, "当前没有正在更新的软件")
            return
        self.cancel_current.set()
        self.log("✖ 正在取消当前软件更新…")

    def on_cancel_all(self):
        if not messagebox.askyesno(C.APP_NAME, "确定取消全部剩余更新？", icon="warning"):
            return
        self.cancel_all.set()
        self.cancel_current.set()
        self.pause_evt.clear()
        self.log("⏹ 已请求取消全部剩余更新…")

    # ---------- 更新线程 ----------
    def _update_worker(self, targets):
        stats = {"success": 0, "failed": 0, "timeout": 0, "cancelled": 0, "skipped": 0}
        total = len(targets)
        for i, t in enumerate(targets, 1):
            if self.cancel_all.is_set():
                self._queue.put(("log", f"⏹ 已取消，剩余 {total - i + 1} 个未更新"))
                break
            if self.skip_current.is_set():
                self.skip_current.clear()
                self._mark(t, "skipped")
                stats["skipped"] += 1
                self._queue.put(("log", f"⏭ [{i}/{total}] {t['name']} 已跳过"))
                continue
            while self.pause_evt.is_set():
                if self.cancel_all.is_set():
                    break
                time.sleep(0.2)
            if self.cancel_all.is_set():
                self._queue.put(("log", f"⏹ 已取消，剩余 {total - i + 1} 个未更新"))
                break
            self.cancel_current.clear()
            self._mark(t, "running")
            self._queue.put(("log", f"[{i}/{total}] 正在更新 {t['name']} → {t['available']} …"))
            self._queue.put(("progress", i, total))
            result, output = self._upgrade_one(t["id"])
            tail = output[-600:] if output else ""
            if result == "success":
                stats["success"] += 1
                self._mark(t, "success")
                real = C.query_installed_version(t["id"])
                if real:
                    t["version"] = real
                    if C._cmp_ver(real, t["available"]) >= 0:
                        self._queue.put(("latest", t["name"]))
                self._queue.put(("done", t["name"]))
                self._queue.put(("log", f"✔ [{i}/{total}] {t['name']} 更新成功（当前 {real or '?'}）"))
            elif result == "skipped":
                stats["skipped"] += 1
                self._mark(t, "skipped")
                self._queue.put(("log", f"⏭ [{i}/{total}] {t['name']} 已跳过"))
            elif result == "cancelled":
                stats["cancelled"] += 1
                self._mark(t, "cancelled")
                self._queue.put(("log", f"✖ [{i}/{total}] {t['name']} 更新已取消"))
            elif result == "timeout":
                stats["timeout"] += 1
                self._mark(t, "timeout")
                self._queue.put(("log", f"⏱ [{i}/{total}] {t['name']} 更新超时:\n{tail}"))
            else:
                stats["failed"] += 1
                self._mark(t, "failed")
                self._queue.put(("log", f"✘ [{i}/{total}] {t['name']} 更新失败:\n{tail}"))
        self.proc = None
        if not self.cancel_all.is_set():
            if self.clean_old_opt:
                self._post_clean_old(targets)
            if self.clean_inst_opt:
                self._post_clean_installers()
        self._queue.put(("finish", stats, total))

    def _upgrade_one(self, pkg_id, timeout=C.UPDATE_TIMEOUT):
        flags = "--accept-package-agreements --accept-source-agreements --disable-interactivity"
        cmd = f'winget upgrade --id "{pkg_id}" -e {flags}'
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="ignore",
                shell=True, startupinfo=C._startupinfo())
        except Exception as e:
            return "failed", f"启动 winget 失败: {e}"
        self.proc = proc

        def kill():
            try:
                subprocess.run(f"taskkill /F /T /PID {proc.pid}",
                               capture_output=True, shell=True, startupinfo=C._startupinfo())
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        start = time.time()
        while proc.poll() is None:
            if self.skip_current.is_set():
                kill()
                return "skipped", "用户跳过当前更新"
            if self.cancel_current.is_set():
                kill()
                return "cancelled", "用户取消当前更新"
            if time.time() - start > timeout:
                kill()
                return "timeout", f"更新超过 {timeout} 秒，已超时终止"
            time.sleep(0.3)
        try:
            out, err = proc.communicate()
        except Exception:
            out, err = "", ""
        combined = (out or "") + "\n" + (err or "")
        return ("success" if proc.returncode == 0 else "failed"), combined.strip()

    def _post_clean_old(self, targets):
        succ = [t for t in targets if t.get("upd_state") == "success"]
        if not succ:
            return
        self._queue.put(("log", "🧹 开始检查旧版本文件残留…"))
        findings = C.scan_old_version_dirs(succ)
        if not findings:
            self._queue.put(("log", "🧹 未发现旧版本残留"))
            return
        ok = fail = 0
        for app, parent, full, ver in findings:
            okk, msg = C.safe_delete_path(full)
            ok += okk
            fail += (not okk)
            self._queue.put(("log", f"🧹 {msg}"))
        self._queue.put(("log", f"🧹 旧文件清理完成：删除 {ok} 个，失败 {fail} 个"))

    def _post_clean_installers(self):
        self._queue.put(("log", "🗑 开始扫描下载目录中的安装包…"))
        pkgs = C.scan_installers()
        if not pkgs:
            self._queue.put(("log", "🗑 未发现安装包"))
            return
        ok = fail = 0
        freed = 0
        for p in pkgs:
            okk, msg = C.safe_delete_path(p["path"])
            ok += okk
            fail += (not okk)
            freed += p["size"] if okk else 0
            self._queue.put(("log", f"🗑 {msg}"))
        self._queue.put(("log", f"🗑 安装包清理完成：删除 {ok} 个，失败 {fail} 个，释放 {freed/1048576:.1f} MB"))

    def _mark(self, row, state):
        row["upd_state"] = state
        self._queue.put(("status", row["name"], state))

    # ---------- GUI 轮询 ----------
    def _poll_update(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.log(msg[1])
                elif kind == "progress":
                    i, total = msg[1], msg[2]
                    self.app.set_status(f"正在更新 {i}/{total} …")
                elif kind == "status":
                    name, state = msg[1], msg[2]
                    for item, row in self.item_row.items():
                        if row["name"] == name:
                            self.tree.set(item, "status", C.UPD_STATE_TEXT[state])
                            self.tree.item(item, tags=(C.UPD_STATE_TAG[state],))
                elif kind == "latest":
                    name = msg[1]
                    for item, row in self.item_row.items():
                        if row["name"] == name:
                            row["status"] = "latest"
                            row["checked"] = False
                            self.tree.set(item, "chk", "")
                            self.tree.set(item, "version", row["version"])
                            self.tree.set(item, "status", "已是最新")
                            self.tree.item(item, tags=("latest",))
                elif kind == "done":
                    name = msg[1]
                    for item, row in self.item_row.items():
                        if row["name"] == name:
                            self.tree.set(item, "version", row["available"])
                elif kind == "finish":
                    self._finish_update(msg[1], msg[2])
                    return
        except queue.Empty:
            pass
        if self.busy:
            self.root.after(200, self._poll_update)

    def _finish_update(self, stats, total):
        parts = []
        for k, label in (("success", "成功"), ("failed", "失败"), ("timeout", "超时"),
                         ("cancelled", "已取消"), ("skipped", "已跳过")):
            if stats[k]:
                parts.append(f"{label} {stats[k]}")
        summary = "、".join(parts) if parts else "无"
        self.log(f"更新流程结束：{summary}（共处理 {total} 项）")
        self.app.set_status(f"更新结束：{summary}")
        self.set_busy(False)
        if stats["failed"] or stats["timeout"]:
            messagebox.showwarning(C.APP_NAME, f"更新完成，结果：{summary}。失败的详见日志。")
        elif stats["cancelled"] or stats["skipped"]:
            messagebox.showinfo(C.APP_NAME, f"更新已中断，结果：{summary}。")
        else:
            messagebox.showinfo(C.APP_NAME, f"全部 {stats['success']} 个软件更新成功！")

    # ---------- 旧文件扫描 / 杀出 ----------
    def on_clean_old(self):
        if self.busy or not self.rows:
            return
        self.app.set_status("正在扫描旧版本文件…")
        self.log("🧹 开始扫描旧版本文件残留…")

        def worker():
            findings = C.scan_old_version_dirs(self.rows)
            self.root.after(0, lambda: self._clean_old_done(findings))

        threading.Thread(target=worker, daemon=True).start()

    def _clean_old_done(self, findings):
        if not findings:
            self.log("🧹 未发现旧版本文件残留")
            self.app.set_status("无旧版本残留")
            messagebox.showinfo(C.APP_NAME, "未发现旧版本文件残留 🎉")
            return
        items = [{"desc": f"【{app}】旧版本 {ver}\n    {full}",
                  "path": full} for app, _, full, ver in findings]
        chosen = self._ask_delete_list(
            "清理旧版本文件", items,
            f"发现 {len(findings)} 个疑似旧版本目录（保留最新）。\n删除仅移除程序文件，不触碰登录与使用数据。")
        if chosen is None:
            return
        ok = fail = 0
        for item in chosen:
            okk, msg = C.safe_delete_path(item["path"])
            ok += okk
            fail += (not okk)
            self.log(msg)
        self.log(f"🧹 清理完成：删除 {ok} 个，失败 {fail} 个")
        self.app.set_status(f"清理完成：删除 {ok} 个，失败 {fail} 个")

    def on_scan_old(self):
        if self.busy or not self.rows:
            return
        self.app.set_status("正在扫描旧版文件…")
        self.log("🔍 开始扫描旧版文件残留（只读）…")

        def worker():
            findings = C.scan_old_version_dirs(self.rows)
            self.root.after(0, lambda: self._scan_old_done(findings))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_old_done(self, findings):
        if not findings:
            self.log("🔍 未发现旧版文件残留")
            messagebox.showinfo(C.APP_NAME, "未发现旧版本文件残留 🎉")
            return
        items = [{"desc": f"【{app}】旧版本 {ver}\n    {full}",
                  "path": full} for app, _, full, ver in findings]
        self._show_list_only("扫描结果：旧版文件残留（只读）", items,
                             f"发现 {len(findings)} 个疑似旧版本目录。此处仅列出，不删除。")

    # ---------- 清除安装包 ----------
    def on_clean_installers(self):
        if self.busy:
            return
        self.app.set_status("正在扫描安装包…")
        self.log("🗑 开始扫描下载目录中的安装包…")

        def worker():
            pkgs = C.scan_installers()
            self.root.after(0, lambda: self._clean_inst_done(pkgs))

        threading.Thread(target=worker, daemon=True).start()

    def _clean_inst_done(self, pkgs):
        if not pkgs:
            self.log("🗑 未发现安装包")
            messagebox.showinfo(C.APP_NAME, "下载目录中没有发现安装包 🎉")
            return
        total_mb = sum(p["size"] for p in pkgs) / 1048576
        items = [{"desc": f"{os.path.basename(p['path'])}  ({p['size']/1048576:.1f} MB，"
                          f"{datetime.datetime.fromtimestamp(p['mtime']).strftime('%Y-%m-%d')})\n    {p['path']}",
                  "path": p["path"]} for p in pkgs]
        chosen = self._ask_delete_list(
            "清除下载的安装包", items,
            f"发现 {len(pkgs)} 个安装包，共 {total_mb:.1f} MB。删除后不可恢复；正在使用的会自动跳过。")
        if chosen is None:
            return
        ok = fail = 0
        freed = 0
        for item in chosen:
            okk, msg = C.safe_delete_path(item["path"])
            ok += okk
            fail += (not okk)
            if okk:
                try:
                    freed += os.path.getsize(item["path"]) if os.path.exists(item["path"]) else 0
                except OSError:
                    pass
            self.log(msg)
        self.log(f"🗑 清除完成：删除 {ok} 个，失败 {fail} 个，释放 {freed/1048576:.1f} MB")
        self.app.set_status(f"清除完成：删除 {ok} 个，失败 {fail} 个")

    # ---------- 对话框 ----------
    def _ask_delete_list(self, title, items, note):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 80, self.root.winfo_rooty() + 80))
        result = {"v": None}
        ttk.Label(dlg, text=note, wraplength=620, justify="left",
                  foreground="#555").pack(anchor="w", padx=10, pady=(10, 4))
        frame = ttk.Frame(dlg, padding=(10, 4))
        frame.pack(fill="both", expand=True)
        lb = tk.Listbox(frame, selectmode="multiple", height=min(len(items), 12),
                        font=("Microsoft YaHei UI", 9), width=90)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=vsb.set)
        lb.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        for it in items:
            lb.insert("end", it["desc"])
        for i in range(len(items)):
            lb.selection_set(i)
        btns = ttk.Frame(dlg, padding=(10, 8))
        btns.pack(fill="x")

        def ok():
            result["v"] = [items[i] for i in lb.curselection()]
            dlg.destroy()

        def cancel():
            result["v"] = None
            dlg.destroy()

        def all_():
            for i in range(len(items)):
                lb.selection_set(i)

        def none_():
            for i in range(len(items)):
                lb.selection_clear(i)

        ttk.Button(btns, text="全选", command=all_).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="全不选", command=none_).pack(side="left")
        ttk.Button(btns, text="确认删除", command=ok).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="取消", command=cancel).pack(side="right")
        dlg.bind("<Escape>", lambda e: cancel())
        dlg.wait_window()
        return result["v"]

    def _show_list_only(self, title, items, note):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 80, self.root.winfo_rooty() + 80))
        ttk.Label(dlg, text=note, wraplength=620, justify="left",
                  foreground="#555").pack(anchor="w", padx=10, pady=(10, 4))
        frame = ttk.Frame(dlg, padding=(10, 4))
        frame.pack(fill="both", expand=True)
        lb = tk.Listbox(frame, height=min(len(items), 14),
                        font=("Microsoft YaHei UI", 9), width=92)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=vsb.set)
        lb.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        for it in items:
            lb.insert("end", it["desc"])
        bf = ttk.Frame(dlg, padding=(10, 8))
        bf.pack(fill="x")
        ttk.Button(bf, text="关闭", command=dlg.destroy).pack(side="right")

    # ---------- 导出 ----------
    def on_export(self):
        if not self.rows:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"WindowsPP_报告_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            filetypes=[("文本文件", "*.txt")])
        if not path:
            return
        try:
            lines = [f"{C.APP_NAME} 软件版本检查报告",
                     f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
            upd = [r for r in self.rows if r["status"] == "updatable"]
            lines.append(f"可更新: {len(upd)} 个")
            for r in upd:
                lines.append(f"  [可更新] {r['name']}  {r['version']} → {r['available']} (ID: {r['id']})")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.log(f"报告已导出: {path}")
            messagebox.showinfo(C.APP_NAME, f"报告已保存到:\n{path}")
        except Exception as e:
            messagebox.showerror(C.APP_NAME, f"导出失败: {e}")
