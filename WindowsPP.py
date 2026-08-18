#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows++ — 一键识别电脑上安装的所有软件是否最新版本，并启动自动更新
依赖：Windows 10/11 + winget（Windows 包管理器，系统自带）+ Python 3.7+（含 tkinter）

功能：扫描已装软件 / 一键更新 / 暂停·继续 / 取消全部 / 跳过当前 / 取消当前 /
      实时状态（等待·进行中·成功·超时·失败·已跳过·已取消）/ 右键取消勾选 / 导出报告

用法：
    python WindowsPP.py        # 打开图形界面
    python WindowsPP.py --scan # 命令行模式：仅扫描并输出报告，不更新
"""

import os
import sys
import re
import time
import subprocess
import threading
import queue
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ============================================================
# 常量
# ============================================================
APP_NAME = "Windows++"
APP_TITLE = "Windows++ — 软件版本检查 & 一键更新"

# 微软四色格子图标（每个颜色块的十六进制值）
MS_RED = "#F25022"    # 左上 红
MS_GREEN = "#7FBA00"  # 右上 绿
MS_BLUE = "#00A4EF"   # 左下 蓝
MS_YELLOW = "#FFB900" # 右下 黄

# winget 列表的解析正则：名称（可含空格） ID 版本 可用版本 源
_WINGET_ROW_RE = re.compile(r"^(.+?)\s{2,}(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")

# 单个软件更新的超时上限（秒）
UPDATE_TIMEOUT = 1800

# 更新状态 -> 展示文案 / 颜色标签
UPD_STATE_TEXT = {
    "pending": "等待", "running": "进行中", "success": "成功",
    "failed": "失败", "timeout": "超时",
    "cancelled": "已取消", "skipped": "已跳过",
}
UPD_STATE_TAG = {
    "running": "st_running", "success": "st_success", "failed": "st_failed",
    "timeout": "st_timeout", "cancelled": "st_cancelled", "skipped": "st_skipped",
}
UPD_STATE_COLOR = {
    "st_running": "#2563EB", "st_success": "#16A34A", "st_failed": "#DC2626",
    "st_timeout": "#EA580C", "st_cancelled": "#6B7280", "st_skipped": "#6B7280",
}


# ============================================================
# 底层：命令执行
# ============================================================
def _startupinfo():
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def run_cmd(cmd, timeout=600):
    """执行命令，返回 (stdout, stderr, returncode)。"""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="ignore",
            timeout=timeout, shell=True, startupinfo=_startupinfo(),
        )
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "命令超时", -1
    except Exception as e:
        return "", str(e), -1


def has_winget():
    out, err, rc = run_cmd("winget --version", timeout=30)
    return rc == 0


# ============================================================
# 数据获取：注册表已装软件
# ============================================================
def get_installed_from_registry():
    """从 Windows 注册表枚举所有已安装软件。"""
    try:
        import winreg
    except ImportError:
        return []

    results = {}
    roots = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    def _reg_get(key, name):
        try:
            val, _ = winreg.QueryValueEx(key, name)
            return str(val) if val is not None else ""
        except OSError:
            return ""

    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        count = winreg.QueryInfoKey(key)[0]
        for i in range(count):
            try:
                sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
            except OSError:
                continue
            name = _reg_get(sub, "DisplayName")
            if not name:
                continue
            # 跳过系统组件、补丁、安全更新
            if _reg_get(sub, "SystemComponent") == "1":
                continue
            rt = _reg_get(sub, "ReleaseType")
            if rt in ("Security Update", "Update Rollup", "Hotfix", "Service Pack"):
                continue
            entry = {
                "name": name.strip(),
                "version": _reg_get(sub, "DisplayVersion").strip(),
                "publisher": _reg_get(sub, "Publisher").strip(),
                "install_loc": _reg_get(sub, "InstallLocation").strip(),
                "uninstall": _reg_get(sub, "UninstallString").strip(),
            }
            k = name.lower()
            if k not in results:
                results[k] = entry
    return list(results.values())


# ============================================================
# 数据获取：winget 可更新列表
# ============================================================
def get_winget_upgrades():
    """解析 `winget upgrade` 输出，返回可更新的软件列表。"""
    out, err, rc = run_cmd(
        "winget upgrade --accept-source-agreements --disable-interactivity",
        timeout=300,
    )
    if rc != 0:
        return [], err or "winget upgrade 执行失败"

    upgrades = []
    started = False
    for line in out.splitlines():
        s = line.rstrip()
        if not started:
            # 表头行：中英文都兼容
            if ("名称" in s or "Name" in s) and ("ID" in s or "Id" in s):
                started = True
            continue
        if not s.strip() or set(s.strip()) <= set("-─ "):
            continue
        # 末尾统计行（如"26 升级可用"）
        if "升级" in s or "upgrade" in s.lower():
            continue
        m = _WINGET_ROW_RE.match(s)
        if not m:
            continue
        name, pid, ver, avail, src = [x.strip() for x in m.groups()]
        upgrades.append({
            "name": name, "id": pid,
            "version": ver, "available": avail, "source": src,
        })
    return upgrades, None


# ============================================================
# 合并数据：给每个已装软件标注状态
# ============================================================
def _norm(s):
    return re.sub(r"[\s\u00a0]+", "", s).lower()


def merge_status(installed, upgrades):
    """返回合并后的行列表：installed 全部行 + 仅 winget 可见但注册表缺失的行。"""
    # 以 winget upgrade 的 name 匹配注册表 DisplayName
    up_by_norm = {}
    for u in upgrades:
        up_by_norm.setdefault(_norm(u["name"]), []).append(u)

    rows = []
    used_upgrade_keys = set()

    def _best_fuzzy(key):
        """找相似度最高的包含式匹配；要求短串长度≥长串的60%，避免 'Git'→'GitHub Desktop' 误配。"""
        best_k, best_score = None, 0.0
        for k in up_by_norm:
            if len(k) < 5 or k == key:
                continue
            if k in key or key in k:
                shorter, longer = sorted((len(k), len(key)))
                score = shorter / longer
                if score > best_score:
                    best_score, best_k = score, k
        return best_k if best_score >= 0.6 else None

    for app in sorted(installed, key=lambda x: x["name"].lower()):
        key = _norm(app["name"])
        matched = None
        if key in up_by_norm:
            matched = up_by_norm[key][0]
        else:
            fk = _best_fuzzy(key)
            if fk:
                matched = up_by_norm[fk][0]
        if matched:
            used_upgrade_keys.add(_norm(matched["name"]))
            rows.append({
                "name": app["name"],
                "version": app["version"] or matched["version"],
                "available": matched["available"],
                "source": matched["source"],
                "id": matched["id"],
                "publisher": app["publisher"],
                "status": "updatable",
                "upd_state": "pending",
            })
        else:
            rows.append({
                "name": app["name"],
                "version": app["version"],
                "available": "",
                "source": "",
                "id": "",
                "publisher": app["publisher"],
                "status": "unknown",  # winget 未报告更新
                "upd_state": "pending",
            })

    # winget 里能升级、但注册表没抓到的（比如 Store 应用）
    for u in upgrades:
        if _norm(u["name"]) in used_upgrade_keys:
            continue
        rows.append({
            "name": u["name"],
            "version": u["version"],
            "available": u["available"],
            "source": u["source"],
            "id": u["id"],
            "publisher": "",
            "status": "updatable",
            "upd_state": "pending",
        })

    # 排序：可更新 > 未知
    order = {"updatable": 0, "unknown": 1}
    rows.sort(key=lambda r: (order.get(r["status"], 9), _norm(r["name"])))
    return rows


# ============================================================
# 执行更新（可中断）
# ============================================================
def upgrade_one(pkg_id, control=None, timeout=UPDATE_TIMEOUT):
    """用 winget 升级一个包，支持取消/跳过/超时。

    control 提供属性: skip_current / cancel_current（threading.Event），
    以及 proc（当前 Popen 引用）。
    返回 (result, 输出信息)，result ∈ success|failed|timeout|cancelled|skipped。
    """
    flags = "--accept-package-agreements --accept-source-agreements --disable-interactivity"
    cmd = f'winget upgrade --id "{pkg_id}" -e {flags}'
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="ignore",
            shell=True, startupinfo=_startupinfo(),
        )
    except Exception as e:
        return "failed", f"启动 winget 失败: {e}"

    if control:
        control.proc = proc

    def _kill_tree():
        try:
            subprocess.run(f"taskkill /F /T /PID {proc.pid}",
                           capture_output=True, shell=True, startupinfo=_startupinfo())
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    start = time.time()
    while proc.poll() is None:
        if control and control.skip_current.is_set():
            _kill_tree()
            return "skipped", "用户跳过当前更新"
        if control and control.cancel_current.is_set():
            _kill_tree()
            return "cancelled", "用户取消当前更新"
        if time.time() - start > timeout:
            _kill_tree()
            return "timeout", f"更新超过 {timeout} 秒，已超时终止"
        time.sleep(0.3)

    out, err = "", ""
    try:
        out, err = proc.communicate()
    except Exception:
        pass
    rc = proc.returncode
    combined = (out or "") + "\n" + (err or "")
    return ("success" if rc == 0 else "failed"), combined.strip()


# ============================================================
# 报告导出
# ============================================================
def export_report(rows, path):
    lines = [
        f"{APP_NAME} 软件版本检查报告",
        f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"总计: {len(rows)} 个软件",
        "=" * 80,
    ]
    updatable = [r for r in rows if r["status"] == "updatable"]
    lines.append(f"可更新: {len(updatable)} 个")
    lines.append("")
    for r in updatable:
        lines.append(f"  [可更新] {r['name']}")
        lines.append(f"           当前 {r['version']} → 最新 {r['available']}  (ID: {r['id']}, 来源: {r['source']})")
    lines.append("")
    lines.append(f"未报告更新/无法检查: {len(rows) - len(updatable)} 个")
    for r in rows:
        if r["status"] != "updatable":
            lines.append(f"  [—] {r['name']}  {r['version']}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ============================================================
# 图形界面
# ============================================================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1080x680")
        self.root.minsize(920, 560)

        self.rows = []            # 合并后的数据行
        self.item_row = {}        # treeview item -> row dict
        self.busy = False

        # 更新控制（线程事件）
        self.pause_evt = threading.Event()       # set = 暂停
        self.cancel_all = threading.Event()      # set = 取消全部
        self.cancel_current = threading.Event()  # set = 取消当前
        self.skip_current = threading.Event()    # set = 跳过当前/下一个
        self.proc = None                          # 当前 winget 子进程（worker 线程写）
        self._queue = queue.Queue()

        self._set_icon()
        self._build_ui()

    # ---------- 微软四色图标 ----------
    def _set_icon(self):
        try:
            size = 32
            img = tk.PhotoImage(width=size, height=size)
            half = size // 2
            gap = 1
            img.put(MS_RED,    to=(0, 0, half - gap, half - gap))
            img.put(MS_GREEN,  to=(half + 1, 0, size, half - gap))
            img.put(MS_BLUE,   to=(0, half + 1, half - gap, size))
            img.put(MS_YELLOW, to=(half + 1, half + 1, size, size))
            self._icon_img = img  # 防止被 GC
            self.root.iconphoto(True, img)
        except Exception:
            pass  # 图标失败不影响功能

    # ---------- UI ----------
    def _build_ui(self):
        # 顶部说明
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(
            top,
            text="① 扫描 → ② 勾选可更新项（可右键取消勾选）→ ③ 开始更新，可暂停/跳过/取消",
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left")
        self.status_lbl = ttk.Label(top, text="就绪", foreground="#555")
        self.status_lbl.pack(side="right")

        # 按钮区
        btns = ttk.Frame(self.root, padding=(10, 0))
        btns.pack(fill="x")
        self.scan_btn = ttk.Button(btns, text="🔄 扫描并检查更新", command=self.on_scan)
        self.scan_btn.pack(side="left", padx=(0, 6))
        self.update_btn = ttk.Button(btns, text="⬆ 开始更新（选中项）", command=self.on_update, state="disabled")
        self.update_btn.pack(side="left", padx=(0, 6))
        self.selall_btn = ttk.Button(btns, text="☑ 全选可更新项", command=self.on_select_updatable, state="disabled")
        self.selall_btn.pack(side="left", padx=(0, 6))
        self.export_btn = ttk.Button(btns, text="📄 导出报告", command=self.on_export, state="disabled")
        self.export_btn.pack(side="left", padx=(0, 6))

        # 更新控制按钮（运行时启用）
        self.pause_btn = ttk.Button(btns, text="⏸ 暂停更新", command=self.on_pause_toggle, state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 6))
        self.skip_btn = ttk.Button(btns, text="⏭ 跳过当前", command=self.on_skip_current, state="disabled")
        self.skip_btn.pack(side="left", padx=(0, 6))
        self.cancelcur_btn = ttk.Button(btns, text="✖ 取消当前", command=self.on_cancel_current, state="disabled")
        self.cancelcur_btn.pack(side="left", padx=(0, 6))
        self.cancelall_btn = ttk.Button(btns, text="⏹ 取消全部", command=self.on_cancel_all, state="disabled")
        self.cancelall_btn.pack(side="left", padx=(0, 6))

        # 表格
        columns = ("chk", "name", "version", "available", "status", "source", "publisher")
        headers = {
            "chk": "✔", "name": "软件名称", "version": "当前版本",
            "available": "最新版本", "status": "状态",
            "source": "来源", "publisher": "发布者",
        }
        widths = {"chk": 36, "name": 280, "version": 110, "available": 110,
                  "status": 70, "source": 70, "publisher": 150}

        frame = ttk.Frame(self.root, padding=(10, 4))
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

        # 行标签
        self.tree.tag_configure("updatable", foreground="#B45309")
        self.tree.tag_configure("unknown", foreground="#6B7280")
        for tag, color in UPD_STATE_COLOR.items():
            self.tree.tag_configure(tag, foreground=color)

        # 点击 ✔ 列切换勾选；右键菜单
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Button-3>", self._on_right_click)
        self._ctx_item = None
        self.ctx_menu = tk.Menu(self.root, tearoff=0)
        self.ctx_menu.add_command(label="☐ 取消勾选（不更新）", command=self._ctx_uncheck)
        self.ctx_menu.add_command(label="☑ 重新勾选", command=self._ctx_check)

        # 日志区
        logf = ttk.LabelFrame(self.root, text="执行日志", padding=(6, 2))
        logf.pack(fill="both", padx=10, pady=(4, 10))
        self.log_text = tk.Text(logf, height=8, state="disabled",
                                font=("Consolas", 9), bg="#FAFAFA")
        logvsb = ttk.Scrollbar(logf, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=logvsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        logvsb.pack(side="right", fill="y")

    # ---------- 工具 ----------
    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, text):
        self.status_lbl.configure(text=text)

    def set_busy(self, busy):
        self.busy = busy
        if busy:
            self.scan_btn.configure(state="disabled")
            self.update_btn.configure(state="disabled")
            self.selall_btn.configure(state="disabled")
            self.export_btn.configure(state="disabled")
            self.pause_btn.configure(state="normal")
            self.skip_btn.configure(state="normal")
            self.cancelcur_btn.configure(state="normal")
            self.cancelall_btn.configure(state="normal")
        else:
            self.scan_btn.configure(state="normal")
            self.update_btn.configure(state="normal" if self.rows else "disabled")
            self.selall_btn.configure(state="normal" if self.rows else "disabled")
            self.export_btn.configure(state="normal" if self.rows else "disabled")
            self.pause_btn.configure(state="disabled", text="⏸ 暂停更新")
            self.skip_btn.configure(state="disabled")
            self.cancelcur_btn.configure(state="disabled")
            self.cancelall_btn.configure(state="disabled")

    # ---------- 勾选交互 ----------
    def _on_click(self, event):
        if self.busy:
            return
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#1":  # 只响应第一列（✔）
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        row = self.item_row.get(item)
        if row and row["status"] == "updatable":
            self._set_checked(item, row, not row.get("checked", False))

    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        row = self.item_row.get(item)
        if not row or row["status"] != "updatable":
            return
        self.tree.selection_set(item)
        self._ctx_item = item
        try:
            self.ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.ctx_menu.grab_release()

    def _ctx_uncheck(self):
        item = self._ctx_item
        row = self.item_row.get(item)
        if item and row:
            self._set_checked(item, row, False)
            self.log(f"已取消勾选: {row['name']}")

    def _ctx_check(self):
        item = self._ctx_item
        row = self.item_row.get(item)
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
        self.set_status("正在扫描…")
        self.log("开始扫描：读取注册表 + winget upgrade …")

        def worker():
            installed = get_installed_from_registry()
            upgrades, err = get_winget_upgrades()
            self.root.after(0, lambda: self._scan_done(installed, upgrades, err))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_done(self, installed, upgrades, err):
        if err:
            self.log(f"winget 检查失败: {err}")
        rows = merge_status(installed, upgrades)
        self.rows = rows
        self.item_row.clear()

        # 清空表格
        for i in self.tree.get_children():
            self.tree.delete(i)

        for r in rows:
            if r["status"] == "updatable":
                r["checked"] = True  # 默认全选可更新项
                chk = "✔"
            else:
                r["checked"] = False
                chk = ""
            avail = r["available"] or ("—" if r["status"] == "unknown" else "")
            st_text = "可更新" if r["status"] == "updatable" else "—"
            item = self.tree.insert("", "end", values=(
                chk, r["name"], r["version"] or "—", avail, st_text,
                r["source"] or "—", r["publisher"] or "—",
            ), tags=(r["status"],))
            self.item_row[item] = r

        n_up = sum(1 for r in rows if r["status"] == "updatable")
        self.set_status(f"共 {len(rows)} 个软件，{n_up} 个可更新")
        self.log(f"扫描完成：共 {len(rows)} 个软件，可更新 {n_up} 个"
                 f"（可更新项已默认勾选；点击 ✔ 或右键可取消勾选）")
        self.set_busy(False)

    def on_select_updatable(self):
        for item, row in self.item_row.items():
            if row["status"] == "updatable":
                self._set_checked(item, row, True)
        self.log("已全选所有可更新项")

    # ---------- 更新控制 ----------
    def on_update(self):
        if self.busy:
            return
        targets = [r for r in self.rows if r.get("checked") and r["status"] == "updatable"]
        if not targets:
            messagebox.showinfo(APP_NAME, "请先勾选至少一个可更新的软件（点击第一列 ✔）")
            return
        names = "\n".join(f"· {r['name']}  {r['version']} → {r['available']}" for r in targets)
        if not messagebox.askyesno(
            APP_NAME,
            f"即将通过 winget 更新以下 {len(targets)} 个软件：\n\n{names}\n\n"
            f"更新过程可能需要几分钟到十几分钟，部分软件更新完可能要求重启。\n"
            f"期间可随时暂停 / 跳过 / 取消。\n确定继续？",
            icon="warning",
        ):
            return

        # 重置控制状态
        for r in targets:
            r["upd_state"] = "pending"
        self.pause_evt.clear()
        self.cancel_all.clear()
        self.cancel_current.clear()
        self.skip_current.clear()

        self.set_busy(True)
        self.set_status(f"正在更新 0/{len(targets)} …（可暂停/跳过/取消）")
        self.log(f"开始更新 {len(targets)} 个软件…")

        threading.Thread(target=self._update_worker, args=(targets,), daemon=True).start()
        self.root.after(200, self._poll_update)

    def on_pause_toggle(self):
        if self.pause_evt.is_set():
            self.pause_evt.clear()
            self.pause_btn.configure(text="⏸ 暂停更新")
            self.set_status("已继续，正在更新…")
            self.log("▶ 继续更新")
        else:
            self.pause_evt.set()
            self.pause_btn.configure(text="▶ 继续更新")
            self.set_status("已暂停（等待中的软件不会开始）")
            self.log("⏸ 已暂停：当前正在下载/安装的会跑完，等待中的暂停")

    def on_skip_current(self):
        """跳过当前：优先终止正在运行的包（标记为已跳过）；无运行中则跳过下一个待更新。"""
        if self.proc is not None:
            self.skip_current.set()
            self.log("⏭ 正在跳过当前软件…")
            return
        # 无运行中进程：直接跳过下一个待启动的
        self.skip_current.set()
        self.log("⏭ 已设置：将跳过下一个待更新的软件")

    def on_cancel_current(self):
        if self.proc is None:
            self.log("当前没有正在更新的软件，无需取消")
            messagebox.showinfo(APP_NAME, "当前没有正在更新的软件")
            return
        self.cancel_current.set()
        self.log("✖ 正在取消当前软件更新…")

    def on_cancel_all(self):
        if not messagebox.askyesno(
            APP_NAME, "确定取消全部剩余更新？\n当前正在进行的更新也会被终止。", icon="warning"
        ):
            return
        self.cancel_all.set()
        self.cancel_current.set()   # 让正在跑的立即退出
        self.pause_evt.clear()      # 解除暂停，让 worker 能走到退出检查
        self.log("⏹ 已请求取消全部剩余更新…")

    # ---------- 更新线程 ----------
    def _update_worker(self, targets):
        stats = {"success": 0, "failed": 0, "timeout": 0,
                 "cancelled": 0, "skipped": 0}
        total = len(targets)
        for i, t in enumerate(targets, 1):
            if self.cancel_all.is_set():
                self._queue.put(("log", f"⏹ 已取消，剩余 {total - i + 1} 个未更新"))
                break

            # 包开始前的“跳过当前”处理（无运行中进程时点跳过）
            if self.skip_current.is_set():
                self.skip_current.clear()
                self._mark(t, "skipped")
                stats["skipped"] += 1
                self._queue.put(("log", f"⏭ [{i}/{total}] {t['name']} 已跳过"))
                continue

            # 暂停等待
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

            result, output = upgrade_one(t["id"], control=self, timeout=UPDATE_TIMEOUT)
            tail = (output[-600:] if output else "")
            if result == "success":
                stats["success"] += 1
                self._mark(t, "success")
                self._queue.put(("done", t["name"]))
                self._queue.put(("log", f"✔ [{i}/{total}] {t['name']} 更新成功"))
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
        self._queue.put(("finish", stats, total))

    def _mark(self, row, state):
        """标记某行的更新状态（worker 线程调用，经队列回 GUI 更新表格）。"""
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
                    self.set_status(f"正在更新 {i}/{total} …（可暂停/跳过/取消）")
                elif kind == "status":
                    name, state = msg[1], msg[2]
                    for item, row in self.item_row.items():
                        if row["name"] == name:
                            self.tree.set(item, "status", UPD_STATE_TEXT[state])
                            self.tree.item(item, tags=(UPD_STATE_TAG[state],))
                elif kind == "done":
                    name = msg[1]
                    for item, row in self.item_row.items():
                        if row["name"] == name:
                            # 更新成功后：当前版本列显示新版本
                            self.tree.set(item, "version", row["available"])
                elif kind == "finish":
                    stats, total = msg[1], msg[2]
                    self._finish_update(stats, total)
                    return
        except queue.Empty:
            pass
        if self.busy:
            self.root.after(200, self._poll_update)

    def _finish_update(self, stats, total):
        parts = []
        if stats["success"]:
            parts.append(f"成功 {stats['success']}")
        if stats["failed"]:
            parts.append(f"失败 {stats['failed']}")
        if stats["timeout"]:
            parts.append(f"超时 {stats['timeout']}")
        if stats["cancelled"]:
            parts.append(f"已取消 {stats['cancelled']}")
        if stats["skipped"]:
            parts.append(f"已跳过 {stats['skipped']}")
        summary = "、".join(parts) if parts else "无"
        self.log(f"更新流程结束：{summary}（共处理 {total} 项）")
        self.set_status(f"更新结束：{summary}")
        self.set_busy(False)
        if stats["failed"] or stats["timeout"]:
            messagebox.showwarning(
                APP_NAME,
                f"更新完成，结果：{summary}。\n失败的软件详见下方日志（可能需手动重试或重启后重试）。")
        elif stats["cancelled"] or stats["skipped"]:
            messagebox.showinfo(APP_NAME, f"更新已中断，结果：{summary}。")
        else:
            messagebox.showinfo(APP_NAME, f"全部 {stats['success']} 个软件更新成功！")

    # ---------- 导出 ----------
    def on_export(self):
        if not self.rows:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"WindowsPP_报告_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            filetypes=[("文本文件", "*.txt")],
        )
        if not path:
            return
        try:
            export_report(self.rows, path)
            self.log(f"报告已导出: {path}")
            messagebox.showinfo(APP_NAME, f"报告已保存到:\n{path}")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"导出失败: {e}")

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno(APP_NAME, "正在更新中，确定要退出吗？", icon="warning"):
                return
        self.root.destroy()


# ============================================================
# 命令行模式
# ============================================================
def cli_scan():
    print(f"{APP_NAME} 扫描模式（只读，不执行更新）\n")
    if not has_winget():
        print("✘ 未检测到 winget，无法检查更新。")
        sys.exit(1)
    print("正在读取注册表…")
    installed = get_installed_from_registry()
    print(f"  已安装: {len(installed)} 个")
    print("正在调用 winget upgrade 检查可更新项（可能需要 1-2 分钟）…")
    upgrades, err = get_winget_upgrades()
    if err:
        print(f"  winget 出错: {err}")
    rows = merge_status(installed, upgrades)
    updatable = [r for r in rows if r["status"] == "updatable"]
    print(f"\n{'='*70}")
    print(f"可更新软件 ({len(updatable)} 个):")
    for r in updatable:
        print(f"  {r['name']:<45} {r['version']} → {r['available']}")
    print(f"{'='*70}")
    print(f"未报告更新/无法检查: {len(rows) - len(updatable)} 个")
    print(f"\n如需更新全部，可执行:  winget upgrade --all")
    print(f"如需更新单个，可执行:  winget upgrade --id <ID> -e")


# ============================================================
# 入口
# ============================================================
def main():
    if "--scan" in sys.argv:
        cli_scan()
        return
    if not has_winget():
        # 无 GUI 环境也提示
        print("未检测到 winget（Windows 包管理器）。")
        print("请安装「应用安装程序」: https://aka.ms/getwinget")
        sys.exit(1)
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
