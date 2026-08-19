#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_toys — 桌面工具与宠物页（v3.1）。

工具：联网下载并安装 Windows 7 经典桌面小工具（.gadget）。
      打开 = mshta 以独立程序窗口运行（非浏览器），Win10/11 无侧边栏平台故用兼容方式。
宠物：宠物库（默认 FeibiPet + 用户导入），以中等图标网格展示供选择；
      打开·关闭·开机自启动针对当前选中的宠物。
"""

import os
import re
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
PET_GRID_COLS = 5


def _gadgets_dir():
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    d = os.path.join(local, "WindowsPP", "gadgets")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _gadget_state(key):
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
    for root, dirs, files in os.walk(extract):
        for fn in files:
            if fn.lower().endswith((".html", ".htm")):
                return os.path.join(root, fn)
    return None


def _mshta_path():
    windir = os.environ.get("WINDIR") or r"C:\Windows"
    return os.path.join(windir, "System32", "mshta.exe")


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


def _pet_name(path):
    return os.path.splitext(os.path.basename(path))[0]


class PageToys(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg="#FFFFFF")
        self.app = app
        self.root = app.root
        self._gadget_btns = {}
        self._pet_btns = {}
        self._pet_selected = ""
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
                       "「打开」以独立程序窗口运行（mshta，非浏览器）。Win10/11 已移除侧边栏平台，"
                       "故以兼容方式显示小工具内容。",
                  foreground="#555", wraplength=1000).pack(anchor="w", pady=(0, 6))
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
            self._gadget_btns[key] = {"name": name, "install": install_btn, "open": open_btn,
                                      "remove": rm_btn, "var": var, "status": st}

        # 宠物区：库 + 中等图标网格
        f2 = ttk.LabelFrame(self, text="🐾 桌面宠物库（点击图标选择，可导入多个）", padding=8)
        f2.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._pet_grid = ttk.Frame(f2)
        self._pet_grid.pack(fill="both", expand=True, anchor="w")
        row = ttk.Frame(f2)
        row.pack(anchor="w", pady=(8, 2))
        self.pet_open_btn = ttk.Button(row, text="🐾 打开宠物", command=self._pet_open)
        self.pet_open_btn.pack(side="left", padx=(0, 6))
        self.pet_close_btn = ttk.Button(row, text="⏹ 关闭宠物", command=self._pet_close, state="disabled")
        self.pet_close_btn.pack(side="left", padx=(0, 6))
        self.pet_auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="开机自启动所选宠物", variable=self.pet_auto_var,
                        command=self._pet_autostart).pack(side="left", padx=10)
        row2 = ttk.Frame(f2)
        row2.pack(anchor="w", pady=2)
        ttk.Button(row2, text="📥 导入宠物（exe）", command=self._pet_import).pack(side="left", padx=(0, 6))
        ttk.Button(row2, text="🗑 移除所选宠物", command=self._pet_remove).pack(side="left")
        self.pet_hint = ttk.Label(f2, text="", foreground="#888", wraplength=1000,
                                  font=("Microsoft YaHei UI", 9))
        self.pet_hint.pack(anchor="w", pady=(6, 0))

    # ---------- 工具 ----------
    def refresh(self):
        for key, info in self._gadget_btns.items():
            installed, html = _gadget_state(key)
            info["open"].configure(state="normal" if installed else "disabled")
            info["remove"].configure(state="normal" if installed else "disabled")
            info["status"].configure(text="已安装" if installed else "未安装",
                                     foreground="#16A34A" if installed else "#9CA3AF")
            info["var"].set(bool(C.get_autostart_cmd(GADGET_RUN_PREFIX + key)))
        self._refresh_pet_grid()

    # ---------- Win7 小工具：安装 / 打开 / 卸载 / 自启动 ----------
    def _install(self, key, url):
        info = self._gadget_btns[key]
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
        info = self._gadget_btns[key]
        info["install"].configure(state="normal", text="📥 安装")
        if ok:
            info["status"].configure(text="已安装", foreground="#16A34A")
            info["open"].configure(state="normal")
            info["remove"].configure(state="normal")
            self.app.set_status(f"「{info['name']}」安装成功")
            messagebox.showinfo(
                C.APP_NAME,
                f"Win7 小工具「{info['name']}」已安装到本地。\n\n"
                f"提示：Windows 10/11 已移除侧边栏平台，点击「▶ 打开」将以独立窗口显示小工具内容（兼容方式）。")
        else:
            info["status"].configure(text="安装失败", foreground="#DC2626")
            self.app.set_status(f"「{info['name']}」安装失败")
            messagebox.showerror(C.APP_NAME, f"安装失败：{html_or_err}")

    def _open(self, key):
        installed, html = _gadget_state(key)
        if not installed:
            messagebox.showinfo(C.APP_NAME, "请先安装该小工具")
            return
        mshta = _mshta_path()
        if html:
            try:
                if os.path.isfile(mshta):
                    # 以独立程序窗口运行（mshta HTA），小工具内容直接显示在桌面窗口
                    subprocess.Popen([mshta, html], startupinfo=C._startupinfo())
                    self.app.set_status(f"已打开小工具「{key}」（独立窗口）")
                    return
                os.startfile(html)
                return
            except Exception as e:
                messagebox.showerror(C.APP_NAME, f"打开失败: {e}")
        try:
            os.startfile(os.path.join(_gadgets_dir(), key))
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
            messagebox.showwarning(C.APP_NAME, "未找到小工具的可运行文件，无法自启动。")
            var.set(False)
            return
        mshta = _mshta_path()
        cmd = f'"{mshta}" "{html}"' if os.path.isfile(mshta) else f'"{html}"'
        C._sync_autostart(v, GADGET_RUN_PREFIX + key, raw_cmd=cmd)
        self.app.set_status(f"小工具「{key}」开机自启动已{'开启' if v else '关闭'}")

    # ---------- 宠物库 ----------
    def _load_pets(self):
        """返回 [(path, name)]：用户导入 + 默认 FeibiPet（存在且去重）。"""
        seen, out = set(), []
        for p in self.app.settings.get("pets") or []:
            if p and os.path.isfile(p) and p not in seen:
                seen.add(p)
                out.append((p, _pet_name(p)))
        default = _find_pet_exe(DEFAULT_PET_DIR)
        if default and default not in seen:
            out.insert(0, (default, _pet_name(default)))
        if not out:
            # 兼容旧配置 pet_path
            old = self.app.settings.get("pet_path") or ""
            if old and os.path.isfile(old):
                out.append((old, _pet_name(old)))
        return out

    def _refresh_pet_grid(self):
        for w in self._pet_grid.winfo_children():
            w.destroy()
        self._pet_btns = {}
        pets = self._load_pets()
        selected = self.app.settings.get("pet_selected") or ""
        if not selected or not any(p == selected for p, _ in pets):
            selected = pets[0][0] if pets else ""
        self._pet_selected = selected
        accent = self.app._theme if hasattr(self.app, "_theme") else "#0078D4"
        for i, (path, name) in enumerate(pets):
            b = tk.Button(self._pet_grid, text=f"🐾\n{name}", font=("Microsoft YaHei UI", 9),
                          width=13, height=3, relief="ridge",
                          bg=accent if path == selected else "#F9FAFB",
                          fg="#FFFFFF" if path == selected else "#374151",
                          activebackground=accent,
                          command=lambda p=path: self._pet_select(p))
            b.grid(row=i // PET_GRID_COLS, column=i % PET_GRID_COLS,
                   padx=4, pady=4, sticky="w")
            self._pet_btns[path] = b
        if selected:
            self.pet_path_lbl_hint = self.pet_hint
            self.pet_hint.configure(
                text=f"当前选中：{_pet_name(selected)}（{selected}）\n"
                     f"点击上方图标切换宠物；导入的宠物已保存到库中，重启后仍可选择。")
        else:
            self.pet_hint.configure(text="未找到任何宠物程序。默认目录不存在：\n"
                                         f"{DEFAULT_PET_DIR}\n点击「📥 导入宠物」选择 .exe。")
        self.pet_open_btn.configure(state="normal" if selected else "disabled")
        self.pet_auto_var.set(bool(C.get_autostart_cmd(PET_RUN_NAME)))

    def _pet_select(self, path):
        self._pet_selected = path
        self.app.settings = C.save_settings(pet_selected=path)
        self._refresh_pet_grid()
        self.app.set_status(f"已选择宠物：{_pet_name(path)}")

    def _save_pets(self, pets, selected):
        paths = [p for p, _ in pets]
        self.app.settings = C.save_settings(pets=paths, pet_selected=selected)

    def _pet_import(self):
        path = filedialog.askopenfilename(title="导入自定义桌面宠物（exe 程序）",
                                          filetypes=[("程序", "*.exe"), ("所有文件", "*.*")])
        if not path:
            return
        pets = self._load_pets()
        if not any(p == path for p, _ in pets):
            pets.append((path, _pet_name(path)))
        self._save_pets(pets, path)
        self._refresh_pet_grid()
        self.app.set_status(f"已导入宠物：{_pet_name(path)}")
        messagebox.showinfo(C.APP_NAME,
                            f"已导入宠物「{_pet_name(path)}」。\n点击「🐾 打开宠物」即可在桌面显示。")

    def _pet_remove(self):
        if not self._pet_selected:
            return
        name = _pet_name(self._pet_selected)
        if not messagebox.askyesno(C.APP_NAME, f"确定从宠物库移除「{name}」？（不删除文件本身）"):
            return
        pets = [x for x in self._load_pets() if x[0] != self._pet_selected]
        self._save_pets(pets, pets[0][0] if pets else "")
        C._sync_autostart(False, PET_RUN_NAME)
        self._refresh_pet_grid()
        self.app.set_status(f"已从库中移除宠物「{name}」")

    def _pet_open(self):
        if not self._pet_selected:
            messagebox.showwarning(C.APP_NAME, "请先选择一个宠物。")
            return
        try:
            self._pet_proc = subprocess.Popen([self._pet_selected])
            self.pet_close_btn.configure(state="normal")
            self.app.set_status(f"宠物已启动: {_pet_name(self._pet_selected)}")
        except Exception as e:
            messagebox.showerror(C.APP_NAME, f"启动宠物失败: {e}")

    def _pet_close(self):
        if self._pet_selected:
            subprocess.run(f'taskkill /F /T /IM "{os.path.basename(self._pet_selected)}"',
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
        if v and not self._pet_selected:
            messagebox.showwarning(C.APP_NAME, "请先选择一个宠物。")
            self.pet_auto_var.set(False)
            return
        C._sync_autostart(v, PET_RUN_NAME,
                          raw_cmd=f'"{self._pet_selected}"' if self._pet_selected else None)
        self.app.set_status("所选宠物开机自启动已" + ("开启" if v else "关闭"))
