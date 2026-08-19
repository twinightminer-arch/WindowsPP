#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_toys — 桌面工具与宠物页。

工具：联网下载并安装 Windows 7 自带经典桌面小工具（.gadget）：
      时钟 / 日历 / CPU 仪表盘 / 天气 / 货币 / 资讯 / 幻灯片 / 拼图。
      Win10/11 已移除侧边栏平台，小工具以“兼容方式”（默认浏览器）打开。
宠物：默认 FeibiPet（可指定路径），打开·关闭·开机自启动·自定义导入。
"""

import os
import re
import sys
import zipfile
import shutil
import urllib.request
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from wpp import common as C

# Win7 自带小工具（Windows 7 官方侧边栏小工具存档，GitHub Pages 直链）
GADGET_BASE = "https://lelegofrog.github.io/lelegodlex/win/7"
GADGETS = [
    ("Clock", "时钟", "经典指针时钟，可显示任意城市时间", f"{GADGET_BASE}/Clock.gadget"),
    ("Calendar", "日历", "浏览当月与全年的日历", f"{GADGET_BASE}/Calendar.gadget"),
    ("CPU Meter", "CPU 仪表盘", "实时显示 CPU 与内存占用", f"{GADGET_BASE}/CPU.gadget"),
    ("Weather", "天气", "查看全球天气（需网络）", f"{GADGET_BASE}/Weather.gadget"),
    ("Currency", "货币汇率", "货币换算（在线服务已停用，可能不可用）", f"{GADGET_BASE}/Currency.gadget"),
    ("RSS Feeds", "资讯头条", "跟踪新闻、体育、娱乐头条", f"{GADGET_BASE}/RSSFeeds.gadget"),
    ("Slide Show", "幻灯片", "循环播放你的图片", f"{GADGET_BASE}/SlideShow.gadget"),
    ("Picture Puzzle", "拼图游戏", "拖动拼块还原图片", f"{GADGET_BASE}/PicturePuzzle.gadget"),
]
GADGET_RUN_PREFIX = "WindowsPP_Gadget_"

DEFAULT_PET_DIR = r"C:\Users\李忠浩\OneDrive\Desktop(1)\my file\FeibiPet_v0.0.1"
PET_RUN_NAME = "FeibiPet"


def _gadgets_dir():
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    d = os.path.join(local, "WindowsPP", "gadgets")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _gadget_state(key):
    """返回 (installed, html_path)。"""
    base = os.path.join(_gadgets_dir(), key)
    app = os.path.join(base, "app")
    html = _find_main_html(app) if os.path.isdir(app) else None
    return os.path.isdir(app), html


def _find_main_html(extract):
    """递归查找小工具主 html（兼容多种 gadget.xml 格式）。"""
    xml_candidates = []
    for root, dirs, files in os.walk(extract):
        for fn in files:
            if fn.lower() == "gadget.xml":
                xml_candidates.append(os.path.join(root, fn))
    patterns = [
        r'<html[^>]*src=["\']([^"\']+)["\']',
        r'<base[^>]*type=["\']html["\'][^>]*src=["\']([^"\']+)["\']',
        r'<base[^>]*src=["\']([^"\']+)["\'][^>]*type=["\']html["\']',
    ]
    for xml in xml_candidates:
        try:
            txt = open(xml, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for pat in patterns:
            m = re.search(pat, txt, re.I)
            if m:
                p = os.path.join(os.path.dirname(xml), m.group(1))
                if os.path.isfile(p):
                    return p
    # 兜底：目录下第一个 html
    for root, dirs, files in os.walk(extract):
        for fn in files:
            if fn.lower().endswith((".html", ".htm")):
                return os.path.join(root, fn)
    return None


def _find_pet_exe(dir_path):
    if not dir_path or not os.path.isdir(dir_path):
        return None
    try:
        for f in sorted(os.listdir(dir_path)):
            if f.lower().endswith(".exe"):
                low = f.lower()
                if any(x in low for x in ("uninstall", "卸载", "helper", "update")):
                    continue
                return os.path.join(dir_path, f)
    except OSError:
        pass
    return None


class PageToys(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg="#FFFFFF")
        self.app = app
        self.root = app.root
        self._gadget_btns = {}
        self._pet_proc = None
        self._build_ui()
        self.refresh()

    # ---------- UI ----------
    def _build_ui(self):
        # 工具区：Win7 经典小工具
        f1 = ttk.LabelFrame(self, text="🧰 桌面工具（Windows 7 经典小工具，联网安装）", padding=8)
        f1.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        ttk.Label(f1,
                  text="以下为 Windows 7 系统自带经典小工具，点击「安装」从网络下载并解压到本地；"
                       "「打开」以兼容方式运行（Win10/11 已移除侧边栏平台，将用默认浏览器显示小工具内容）。",
                  foreground="#555", wraplength=980).pack(anchor="w", pady=(0, 6))
        self._tool_rows = {}
        for key, name, desc, url in GADGETS:
            row = ttk.Frame(f1)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"● {name}", width=16, font=("Microsoft YaHei UI", 10)).pack(side="left")
            ttk.Label(row, text=desc, foreground="#888", width=44, anchor="w").pack(side="left")
            install_btn = ttk.Button(row, text="📥 安装", width=7,
                                     command=lambda k=key, u=url: self._install(k, u))
            install_btn.pack(side="left", padx=2)
            open_btn = ttk.Button(row, text="▶ 打开", width=7, state="disabled",
                                  command=lambda k=key: self._open(k))
            open_btn.pack(side="left", padx=2)
            rm_btn = ttk.Button(row, text="🗑 卸载", width=7, state="disabled",
                                command=lambda k=key: self._remove(k))
            rm_btn.pack(side="left", padx=2)
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(row, text="开机自启动", variable=var,
                                 command=lambda k=key, v=var: self._gadget_autostart(k, v))
            cb.pack(side="left", padx=6)
            st = ttk.Label(row, text="未安装", foreground="#9CA3AF", width=10)
            st.pack(side="left")
            self._tool_rows[key] = {"name": name, "install": install_btn, "open": open_btn,
                                    "remove": rm_btn, "var": var, "status": st}

        # 宠物区
        f2 = ttk.LabelFrame(self, text="🐾 桌面宠物", padding=8)
        f2.pack(fill="x", padx=10, pady=(0, 10))
        self.pet_path_lbl = ttk.Label(f2, text="", foreground="#555", wraplength=960)
        self.pet_path_lbl.pack(anchor="w")
        row = ttk.Frame(f2)
        row.pack(anchor="w", pady=(8, 2))
        self.pet_open_btn = ttk.Button(row, text="🐾 打开宠物", command=self._pet_open)
        self.pet_open_btn.pack(side="left", padx=(0, 6))
        self.pet_close_btn = ttk.Button(row, text="⏹ 关闭宠物", command=self._pet_close, state="disabled")
        self.pet_close_btn.pack(side="left", padx=(0, 6))
        self.pet_auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="开机自启动宠物", variable=self.pet_auto_var,
                        command=self._pet_autostart).pack(side="left", padx=10)
        row2 = ttk.Frame(f2)
        row2.pack(anchor="w", pady=2)
        ttk.Button(row2, text="📂 指定宠物程序", command=self._pet_specify).pack(side="left", padx=(0, 6))
        ttk.Button(row2, text="📥 导入自定义宠物（exe）", command=self._pet_import).pack(side="left")
        self.pet_hint = ttk.Label(f2, text="", foreground="#888", wraplength=960,
                                  font=("Microsoft YaHei UI", 9))
        self.pet_hint.pack(anchor="w", pady=(8, 0))

    def refresh(self):
        for key, url_item in self._tool_rows.items():
            installed, html = _gadget_state(key)
            self._tool_rows[key]["open"].configure(state="normal" if installed else "disabled")
            self._tool_rows[key]["remove"].configure(state="normal" if installed else "disabled")
            self._tool_rows[key]["status"].configure(
                text="已安装" if installed else "未安装",
                foreground="#16A34A" if installed else "#9CA3AF")
            self._tool_rows[key]["var"].set(bool(C.get_autostart_cmd(GADGET_RUN_PREFIX + key)))
        exe = self.app.settings.get("pet_path") or ""
        if not exe or not os.path.isfile(exe):
            exe = _find_pet_exe(DEFAULT_PET_DIR) or ""
        if exe:
            self.pet_path_lbl.configure(text=f"宠物程序：{exe}")
            self.pet_hint.configure(text="点击「打开宠物」即可在桌面显示宠物；关闭仅结束宠物进程，不影响数据。")
        else:
            self.pet_path_lbl.configure(text=f"默认宠物目录不存在：{DEFAULT_PET_DIR}")
            self.pet_hint.configure(text="未找到宠物程序。可点击「📂 指定宠物程序」选择 .exe，或「📥 导入自定义宠物」。")
        self.pet_auto_var.set(bool(C.get_autostart_cmd(PET_RUN_NAME)))
        self.pet_open_btn.configure(state="normal" if exe else "disabled")

    # ---------- Win7 小工具：安装 / 打开 / 卸载 / 自启动 ----------
    def _install(self, key, url):
        info = self._tool_rows[key]
        if info["install"]["text"] == "下载中…":
            return
        info["install"].configure(state="disabled", text="下载中…")
        info["status"].configure(text="下载中…", foreground="#B45309")
        self.app.set_status(f"正在下载安装 Win7 小工具「{info['name']}」…")

        def worker():
            try:
                dst_dir = os.path.join(_gadgets_dir(), key)
                os.makedirs(dst_dir, exist_ok=True)
                gadget_file = os.path.join(dst_dir, f"{key}.gadget")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=90) as resp, open(gadget_file, "wb") as f:
                    shutil.copyfileobj(resp, f)
                extract = os.path.join(dst_dir, "app")
                if os.path.isdir(extract):
                    shutil.rmtree(extract)
                with zipfile.ZipFile(gadget_file) as z:
                    for m in z.infolist():
                        fn = m.filename.replace("\\", "/")
                        if fn.startswith("/") or ".." in fn.split("/"):
                            continue
                        z.extract(m, extract)
                html = _find_main_html(extract)
                self.root.after(0, lambda: self._install_done(key, True, html))
            except Exception as e:
                self.root.after(0, lambda: self._install_done(key, False, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _install_done(self, key, ok, html_or_err):
        info = self._tool_rows[key]
        info["install"].configure(state="normal", text="📥 安装")
        if ok:
            info["status"].configure(text="已安装", foreground="#16A34A")
            info["open"].configure(state="normal")
            info["remove"].configure(state="normal")
            self.app.set_status(f"「{info['name']}」安装成功")
            messagebox.showinfo(
                C.APP_NAME,
                f"Win7 小工具「{info['name']}」已安装到本地。\n\n"
                f"提示：Windows 10/11 已移除侧边栏平台，点击「▶ 打开」将以默认浏览器显示小工具内容（兼容方式）。")
        else:
            info["status"].configure(text="安装失败", foreground="#DC2626")
            self.app.set_status(f"「{info['name']}」安装失败")
            messagebox.showerror(C.APP_NAME, f"安装失败：{html_or_err}")

    def _open(self, key):
        installed, html = _gadget_state(key)
        if not installed:
            messagebox.showinfo(C.APP_NAME, "请先安装该小工具")
            return
        if html:
            try:
                os.startfile(html)
                self.app.set_status(f"已以兼容方式打开小工具「{key}」（浏览器显示）")
                return
            except Exception as e:
                messagebox.showerror(C.APP_NAME, f"打开失败: {e}")
        base = os.path.join(_gadgets_dir(), key)
        try:
            os.startfile(base)
        except Exception as e:
            messagebox.showerror(C.APP_NAME, f"打开失败: {e}")

    def _remove(self, key):
        if not messagebox.askyesno(C.APP_NAME, f"确定卸载小工具「{key}」？（删除本地下载文件）"):
            return
        C._sync_autostart(False, GADGET_RUN_PREFIX + key)
        try:
            shutil.rmtree(os.path.join(_gadgets_dir(), key))
        except Exception as e:
            messagebox.showerror(C.APP_NAME, f"卸载失败: {e}")
        self.refresh()
        self.app.set_status(f"已卸载小工具「{key}」")

    def _gadget_autostart(self, key, var):
        v = var.get()
        installed, html = _gadget_state(key)
        if v and not installed:
            messagebox.showwarning(C.APP_NAME, "该小工具尚未安装，无法开启自启动。")
            var.set(False)
            return
        if v and not html:
            messagebox.showwarning(C.APP_NAME, "未找到小工具的兼容打开文件，无法自启动。")
            var.set(False)
            return
        C._sync_autostart(v, GADGET_RUN_PREFIX + key, raw_cmd=f'"{html}"' if html else None)
        self.app.set_status(f"小工具「{key}」开机自启动已{'开启' if v else '关闭'}")

    # ---------- 宠物 ----------
    def _resolve_pet_exe(self):
        exe = self.app.settings.get("pet_path") or ""
        if not exe or not os.path.isfile(exe):
            exe = _find_pet_exe(DEFAULT_PET_DIR) or ""
        return exe

    def _pet_open(self):
        exe = self._resolve_pet_exe()
        if not exe:
            messagebox.showwarning(C.APP_NAME, "未找到宠物程序，请先指定或导入。")
            return
        try:
            self._pet_proc = subprocess.Popen([exe])
            self.pet_close_btn.configure(state="normal")
            self.app.set_status(f"宠物已启动: {os.path.basename(exe)}")
        except Exception as e:
            messagebox.showerror(C.APP_NAME, f"启动宠物失败: {e}")

    def _pet_close(self):
        exe = self._resolve_pet_exe()
        if exe:
            subprocess.run(f'taskkill /F /T /IM "{os.path.basename(exe)}"',
                           capture_output=True, shell=True, startupinfo=C._startupinfo())
        if self._pet_proc:
            try:
                self._pet_proc.kill()
            except Exception:
                pass
            self._pet_proc = None
        self.pet_close_btn.configure(state="disabled")
        self.app.set_status("宠物已关闭")

    def _pet_autostart(self):
        v = self.pet_auto_var.get()
        exe = self._resolve_pet_exe()
        C._sync_autostart(v, PET_RUN_NAME, raw_cmd=f'"{exe}"' if exe else None)
        self.app.set_status("宠物开机自启动已" + ("开启" if v else "关闭"))

    def _pet_specify(self):
        path = filedialog.askopenfilename(title="选择宠物程序",
                                          filetypes=[("程序", "*.exe"), ("所有文件", "*.*")])
        if not path:
            return
        self.app.settings = C.save_settings(pet_path=path)
        self.refresh()
        self.app.set_status(f"宠物程序已指定: {os.path.basename(path)}")

    def _pet_import(self):
        path = filedialog.askopenfilename(title="导入自定义桌面宠物（exe 程序）",
                                          filetypes=[("程序", "*.exe"), ("所有文件", "*.*")])
        if not path:
            return
        self.app.settings = C.save_settings(pet_path=path)
        self.refresh()
        self.app.set_status(f"已导入宠物: {os.path.basename(path)}")
