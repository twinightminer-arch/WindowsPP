#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.app — Windows++ v3.0 主框架：左侧导航栏 + 页面切换 + 统一状态栏 + 主题/背景。

页面：软件更新 / 软件卸载 / 扫描清理 / 桌面锁定 / 设置 / 工具与宠物。
"""

import os
import sys
import time
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from wpp import common as C

# 预设主题色（Windows 10/11 个性化色板）
THEME_COLORS = C.THEME_COLORS


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{C.APP_NAME} v{C.VERSION} — 软件管家")
        root.geometry("1200x740")
        root.minsize(1024, 640)

        self.settings = C.load_settings()
        self._queue = queue.Queue()
        self._monitor = None
        self._last_monitor_prompt = 0.0

        # 透明哨兵色：主窗口用此色「挖空」，露出背后独立的背景窗口
        # （Tk 无 systemTransparent，正确做法是窗口级 -transparentcolor）
        self._sentinel = "#0a0a12"
        self._transparent = False
        try:
            self.root.attributes("-transparentcolor", self._sentinel)
            self._transparent = True
        except Exception:
            self._transparent = False
        self.root.configure(bg=self._sentinel if self._transparent else "#F0F0F0")

        # 背景视频 / 音乐状态
        self._bg_win = None
        self._bg_canvas = None
        self._bg_image_id = None
        self._bg_img = None
        self._bg_base_color = "#F0F0F0"
        self._music_on = False

        # 桌面拖拽拦截引擎
        self.drag_guard = C.DesktopDragGuard()
        self.drag_guard.start()
        self.update_drag_guard()

        self._set_icon()
        self._init_bg_window()
        self._build_ui()
        self.apply_theme(self.settings.get("theme") or "#0078D4", save=False)
        self._bg_apply()
        self._music_apply()
        self._start_monitor()
        self._poll_queue()

    # ---------- 图标 ----------
    def _set_icon(self):
        try:
            img = tk.PhotoImage(width=32, height=32)
            half, gap = 16, 1
            img.put("#F25022", to=(0, 0, half - gap, half - gap))
            img.put("#7FBA00", to=(half + 1, 0, 32, half - gap))
            img.put("#00A4EF", to=(0, half + 1, half - gap, 32))
            img.put("#FFB900", to=(half + 1, half + 1, 32, 32))
            self._icon_img = img
            self.root.iconphoto(True, img)
        except Exception:
            pass

    # ---------- 背景窗口（独立于主窗口，置于其后） ----------
    def _init_bg_window(self):
        """创建位于主窗口背后的专用背景窗口，承载图片/视频/主题色调。

        主窗口用哨兵色「挖空」透明，背景窗口恰好落在其后，于是主窗口的
        透明区域会露出背景窗口里的内容（图片/视频/纯色）。这是 Tk 8.6 下
        实现「控件背后显示背景」的可靠方案（无 systemTransparent）。
        不支持透明时（self._transparent=False）不创建，降级为纯色窗口。
        """
        self._bg_win = None
        self._bg_canvas = None
        self._bg_image_id = None
        self._bg_img = None
        if not self._transparent:
            return
        try:
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)          # 去掉边框/标题栏，作为纯背景
            w.attributes("-topmost", False)
            cv = tk.Canvas(w, highlightthickness=0, bd=0, bg=self._sentinel)
            cv.place(relwidth=1, relheight=1)
            self._bg_win = w
            self._bg_canvas = cv
            self._lower_bg_win()
        except Exception:
            self._bg_win = None
            self._bg_canvas = None

    def _lower_bg_win(self):
        if self._bg_win:
            try:
                self._bg_win.lower(self.root)
            except Exception:
                pass

    def _sync_bg_win(self):
        """让背景窗口与主窗口完全重合（位置/尺寸同步）。"""
        if not self._bg_win:
            return
        try:
            x = self.root.winfo_rootx()
            y = self.root.winfo_rooty()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            self._bg_win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _on_root_configure(self):
        self._sync_bg_win()
        if self.settings.get("bg_image") or self.settings.get("bg_video"):
            self._on_bg_resize()

    def _on_root_map(self):
        if self._bg_win:
            try:
                self._bg_win.deiconify()
            except Exception:
                pass
            self._lower_bg_win()
            self._sync_bg_win()

    def _on_root_unmap(self):
        if self._bg_win:
            try:
                self._bg_win.withdraw()
            except Exception:
                pass

    def wtransparent(self, w):
        """把控件设为「透明哨兵色」或降级白底（不支持透明时）。"""
        try:
            w.configure(bg=self._sentinel if self._transparent else "#FFFFFF")
        except Exception:
            try:
                w.configure(bg="#FFFFFF")
            except Exception:
                pass

    def _tint(self, hex_color, ratio):
        """把颜色按 ratio 与白色混合（0=纯白，1=原色），得到浅色调。"""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            r = int(r * ratio + 255 * (1 - ratio))
            g = int(g * ratio + 255 * (1 - ratio))
            b = int(b * ratio + 255 * (1 - ratio))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#F0F0F0"

    # ---------- UI 骨架 ----------
    def _build_ui(self):
        main = tk.Frame(self.root)
        self.wtransparent(main)
        main.pack(fill="both", expand=True)

        # 左侧导航
        nav = tk.Frame(main, width=185, bg="#F3F3F3", relief="ridge", bd=0)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)

        tk.Label(nav, text="Window++", font=("Microsoft YaHei UI", 14, "bold"),
                 bg="#F3F3F3", fg="#1F2937").pack(pady=(16, 4))
        tk.Label(nav, text=f"v{C.VERSION}", font=("Microsoft YaHei UI", 8),
                 bg="#F3F3F3", fg="#9CA3AF").pack(pady=(0, 12))

        self._nav_btns = {}
        entries = [
            ("updater", "⬆ 软件更新"),
            ("uninstall", "🗑 软件卸载"),
            ("cleaner", "🧹 扫描清理"),
            ("desklock", "🔒 桌面锁定"),
            ("recorder", "📹 录屏"),
            ("settings", "⚙ 设置"),
            ("toys", "🧸 工具与宠物"),
        ]
        for key, text in entries:
            b = tk.Button(nav, text=text, anchor="w", padx=16, pady=10,
                          font=("Microsoft YaHei UI", 10), bd=0, relief="flat",
                          bg="#F3F3F3", fg="#374151", activebackground="#E5E7EB",
                          command=lambda k=key: self.show_page(k))
            b.pack(fill="x", padx=8, pady=2)
            self._nav_btns[key] = b

        self._nav = nav
        self._theme = "#0078D4"

        # 右侧：透明容器，露出背后背景窗口里的图片/视频/主题色
        right = tk.Frame(main)
        self.wtransparent(right)
        right.pack(side="left", fill="both", expand=True)

        self.page_holder = tk.Frame(right)
        self.wtransparent(self.page_holder)
        self.page_holder.place(relwidth=1, relheight=1)

        # 主窗口移动/缩放/最小化时同步背景窗口几何，并防抖重铺背景图
        self.root.bind("<Configure>", lambda e: self._on_root_configure())
        self.root.bind("<Map>", lambda e: self._on_root_map())
        self.root.bind("<Unmap>", lambda e: self._on_root_unmap())
        self.root.bind("<FocusIn>", lambda e: self._lower_bg_win())
        self._resize_job = None

        # 状态栏
        status = ttk.Frame(right)
        status.pack(side="bottom", fill="x")
        self.status_lbl = ttk.Label(status, text="就绪", foreground="#555", padding=(10, 4))
        self.status_lbl.pack(side="left")
        self._nav_lbl = ttk.Label(status, text="", foreground="#9CA3AF", padding=(10, 4))
        self._nav_lbl.pack(side="right")

        # 页面实例（延迟创建）
        from wpp.page_updater import PageUpdater
        from wpp.page_uninstall import PageUninstall
        from wpp.page_cleaner import PageCleaner
        from wpp.page_desklock import PageDeskLock
        from wpp.page_recorder import PageRecorder
        from wpp.page_settings import PageSettings
        from wpp.page_toys import PageToys
        self.pages = {
            "updater": PageUpdater(self.page_holder, self),
            "uninstall": PageUninstall(self.page_holder, self),
            "cleaner": PageCleaner(self.page_holder, self),
            "desklock": PageDeskLock(self.page_holder, self),
            "recorder": PageRecorder(self.page_holder, self),
            "settings": PageSettings(self.page_holder, self),
            "toys": PageToys(self.page_holder, self),
        }
        for p in self.pages.values():
            p.place_forget()
            self.wtransparent(p)
        self.show_page("updater")
        # 首次对齐背景窗口（之后靠 <Configure>/<Map> 维持）
        self._sync_bg_win()

    # ---------- 导航 ----------
    def show_page(self, key):
        for k, p in self.pages.items():
            if k == key:
                p.place(relwidth=1, relheight=1)
                p.refresh()
            else:
                p.place_forget()
        for k, b in self._nav_btns.items():
            if k == key:
                b.configure(bg=self._theme, fg="#FFFFFF", activebackground=self._theme)
            else:
                b.configure(bg="#F3F3F3", fg="#374151", activebackground="#E5E7EB")
        names = {"updater": "软件更新", "uninstall": "软件卸载", "cleaner": "扫描清理",
                 "desklock": "桌面锁定", "recorder": "录屏", "settings": "设置",
                 "toys": "工具与宠物"}
        self._nav_lbl.configure(text=names.get(key, ""))

    # ---------- 主题 ----------
    def apply_theme(self, color_hex, save=True):
        color_hex = (color_hex or "").strip()
        if not re_hex(color_hex):
            return
        self._theme = color_hex
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        # 基础控件：支持透明时，让面板/标签「透明」，露出背后背景窗口的
        # 图片/视频/主题色；不支持时退回白底（保证可读）。
        base_bg = self._sentinel if self._transparent else "#FFFFFF"
        style.configure(".", background=base_bg)
        style.configure("TFrame", background=base_bg)
        style.configure("TLabel", background=base_bg, foreground="#1F2937")
        style.configure("TLabelframe", background=base_bg, foreground="#1F2937")
        style.configure("TLabelframe.Label", background=base_bg, foreground="#1F2937")
        # 按钮
        style.configure("TButton", padding=5)
        style.configure("Accent.TButton", background=color_hex, foreground="#FFFFFF")
        style.configure("Accent.Hover.TButton", background=color_hex)
        style.map("Accent.TButton", background=[("active", color_hex)])
        # 进度条
        style.configure("Horizontal.TProgressbar", troughcolor="#E5E7EB",
                        background=color_hex)
        # 复选/单选 indicator
        style.map("TCheckbutton",
                  background=[("active", color_hex)],
                  indicatorcolor=[("selected", color_hex)])
        style.map("TRadiobutton",
                  background=[("active", color_hex)],
                  indicatorcolor=[("selected", color_hex)])
        # 滚动条
        style.configure("Vertical.TScrollbar", background=color_hex, troughcolor="#F3F4F6")
        style.configure("Horizontal.TScrollbar", background=color_hex, troughcolor="#F3F4F6")
        # Treeview 选中行用主题色，主题切换效果更明显
        style.map("Treeview",
                  background=[("selected", color_hex)],
                  foreground=[("selected", "#FFFFFF")])
        for k, b in self._nav_btns.items():
            if b.cget("bg") == self._theme:
                b.configure(bg=color_hex, activebackground=color_hex)
        # 背景窗口的浅色基调随主题色变化（无图片/视频时，整窗背景即为主题的浅色调）
        if self._transparent and self._bg_canvas:
            self._bg_base_color = self._tint(color_hex, 0.82)
            if not (self.settings.get("bg_image") or self.settings.get("bg_video")):
                try:
                    self._bg_canvas.configure(bg=self._bg_base_color)
                except Exception:
                    pass
        if save:
            self.settings = C.save_settings(theme=color_hex)

    # ---------- 背景（图片/视频）与音乐 ----------
    def _mci(self, cmd):
        try:
            import ctypes
            buf = ctypes.create_string_buffer(512)
            return ctypes.windll.winmm.mciSendStringW(cmd, buf, 512, 0)
        except Exception:
            return -1

    def _bg_apply(self):
        # 不支持透明（无背景窗口）时，背景图无法露出，直接返回避免报错
        if not self._bg_canvas:
            return
        s = self.settings
        # 每次都重新处理（去掉旧缓存），确保不透明度/视频静音等调节立即生效
        try:
            self._mci("close bgvideo")
        except Exception:
            pass
        # 清掉旧图片
        if self._bg_image_id is not None:
            try:
                self._bg_canvas.delete(self._bg_image_id)
            except Exception:
                pass
            self._bg_image_id = None
        # 图片背景
        img_path = s.get("bg_image") or ""
        if img_path and os.path.isfile(img_path):
            loaded = False
            try:
                from PIL import Image, ImageTk
                opacity = max(0, min(100, int(s.get("bg_opacity", 35)))) / 100.0
                im = Image.open(img_path)
                # 按 canvas 实际尺寸缩放（窗口可能不是 1200x740）
                cw = max(1, self._bg_canvas.winfo_width())
                ch = max(1, self._bg_canvas.winfo_height())
                im = im.resize((cw, ch))
                if opacity < 1.0:
                    overlay = Image.new("RGBA", (cw, ch), (255, 255, 255, int(255 * (1 - opacity))))
                    im = im.convert("RGBA")
                    im = Image.alpha_composite(im, overlay)
                self._bg_img = ImageTk.PhotoImage(im)
                self._bg_image_id = self._bg_canvas.create_image(
                    cw // 2, ch // 2, image=self._bg_img, anchor="center")
                loaded = True
            except Exception:
                # PIL 不可用或图片格式不支持时，尝试用 tk.PhotoImage 兜底（仅 png/gif）
                try:
                    self._bg_img = tk.PhotoImage(file=img_path)
                    cw = max(1, self._bg_canvas.winfo_width())
                    ch = max(1, self._bg_canvas.winfo_height())
                    self._bg_image_id = self._bg_canvas.create_image(
                        cw // 2, ch // 2, image=self._bg_img, anchor="center")
                    loaded = True
                except Exception:
                    pass
            if not loaded:
                self._bg_img = None
        else:
            # 无图片时按主题浅色调填充背景窗口（让「界面颜色」直接可见）
            try:
                self._bg_canvas.configure(bg=self._bg_base_color)
            except Exception:
                pass
        # 视频背景（MCI 播放到背景窗口画布，透过主窗口透明区可见）
        video = s.get("bg_video") or ""
        if video and os.path.isfile(video):
            self._mci(f'open "{video}" alias bgvideo type mpegvideo')
            self._mci(f'window bgvideo handle {self._bg_canvas.winfo_id()}')
            vol = 0 if s.get("bg_mute") else 1000
            self._mci(f"setaudio bgvideo volume to {vol}")
            self._mci("play bgvideo")
            self._schedule_video_loop()
        # 音乐（若视频未静音则优先视频音轨；否则播放独立音乐）
        if s.get("bg_music") and s.get("bg_mute"):
            self._music_apply()

    def _schedule_video_loop(self):
        def check():
            try:
                out = self._mci("status bgvideo mode")
                mode = out.decode("utf-8", "ignore").strip() if isinstance(out, bytes) else str(out).strip()
                if mode.lower() in ("stopped", "not ready"):
                    self._mci("play bgvideo")
            except Exception:
                pass
            if self._music_on:
                self.root.after(1500, check)
        self._music_on = True
        check()

    def _music_apply(self):
        try:
            self._mci("close bgmusic")
        except Exception:
            pass
        self._music_on = False
        path = self.settings.get("bg_music") or ""
        if path and os.path.isfile(path):
            self._mci(f'open "{path}" alias bgmusic type mpegvideo')
            self._mci("setaudio bgmusic volume to 1000")
            self._mci("play bgmusic")
            self._music_on = True
            self.root.after(500, self._music_loop)

    def _on_bg_resize(self):
        """窗口大小变化时延迟重铺背景图/视频（防抖）。"""
        if self._resize_job is not None:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
        if not (self.settings.get("bg_image") or self.settings.get("bg_video")):
            return
        self._resize_job = self.root.after(250, self._bg_apply)

    def _music_loop(self):
        if not self._music_on:
            return
        try:
            out = self._mci("status bgmusic mode")
            mode = out.decode("utf-8", "ignore").strip() if isinstance(out, bytes) else str(out).strip()
            if mode.lower() in ("stopped", "not ready"):
                self._mci("play bgmusic")
        except Exception:
            pass
        self.root.after(1500, self._music_loop)

    # ---------- 状态栏 ----------
    def update_drag_guard(self):
        """按当前配置启停桌面图标拖拽拦截（锁定图标非空 或 全局锁定开启）。"""
        s = self.settings
        locked = bool(s.get("desk_locked_icons")) or bool(s.get("icon_lock"))
        self.drag_guard.set_enabled(locked)

    def set_status(self, text):
        self.status_lbl.configure(text=text)

    # ---------- 桌面监控（锁定提示） ----------
    def _start_monitor(self):
        if self._monitor is not None:
            return
        path = C.desktop_path()
        if not os.path.isdir(path):
            return
        self._monitor = C.DesktopMonitor(path, self._on_desktop_event)
        self._monitor.start()

    def _on_desktop_event(self, action, name):
        now = time.time()
        if now - self._last_monitor_prompt < 15:
            return
        self._last_monitor_prompt = now
        self._queue.put(("desktop_event", action, name))

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "desktop_event":
                    self._on_desktop_msg(msg[1], msg[2])
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _on_desktop_msg(self, action, name):
        s = self.settings
        locked = s.get("icon_lock") or bool(s.get("desk_locked_icons"))
        if not locked:
            return
        base = os.path.basename((name or "").lower())
        if base.startswith("~$") or base.endswith((".tmp", ".temp")):
            return
        # 检查是否锁定图标被改动
        locked_icons = s.get("desk_locked_icons") or []
        hit = any(li and li.lower() in (name or "").lower() for li in locked_icons)
        if hit and messagebox.askyesno(
            C.APP_NAME,
            f"桌面图标「{name}」被{action}。\n\n该图标已锁定，如需移动请先关闭锁定。\n是否前往解锁？",
            icon="question",
        ):
            self.show_page("desklock")

    # ---------- 关闭 ----------
    def on_close(self):
        busy_pages = [p for p in self.pages.values()
                      if getattr(p, "busy", False) or getattr(p, "uninstalling", False)]
        if busy_pages and not messagebox.askyesno(
                C.APP_NAME, "有任务正在进行中，确定要退出吗？", icon="warning"):
            return
        try:
            self._mci("close bgvideo")
            self._mci("close bgmusic")
        except Exception:
            pass
        try:
            if self._bg_win:
                self._bg_win.destroy()
        except Exception:
            pass
        self.root.destroy()


def re_hex(s):
    return len(s) == 7 and s[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in s[1:])


# ============================================================
# CLI 扫描（只读）
# ============================================================
def cli_scan():
    print(f"{C.APP_NAME} v{C.VERSION} 扫描模式（只读，不执行更新）\n")
    if not C.has_winget():
        print("✘ 未检测到 winget，无法检查更新。")
        sys.exit(1)
    print("正在读取注册表…")
    installed = C.get_installed_from_registry()
    print(f"  已安装: {len(installed)} 个")
    print("正在调用 winget upgrade 检查可更新项（可能需要 1-2 分钟）…")
    upgrades, err = C.get_winget_upgrades()
    if err:
        print(f"  winget 出错: {err}")
    rows = C.merge_status(installed, upgrades)
    updatable = [r for r in rows if r["status"] == "updatable"]
    latest = [r for r in rows if r["status"] == "latest"]
    print(f"\n{'='*70}")
    print(f"可更新软件 ({len(updatable)} 个):")
    for r in updatable:
        print(f"  {r['name']:<45} {r['version']} → {r['available']}")
    print(f"{'='*70}")
    print(f"已是最新（注册表版本已达标）: {len(latest)} 个")
    print(f"未报告更新/无法检查: {len(rows) - len(updatable) - len(latest)} 个")
    print("\n如需更新全部: winget upgrade --all")


def main():
    args = sys.argv[1:]
    if "--scan" in args:
        cli_scan()
        return
    if not C.has_winget():
        print("未检测到 winget（Windows 包管理器）。")
        print("请安装「应用安装程序」: https://aka.ms/getwinget")
        sys.exit(1)
    root = tk.Tk()
    app = App(root)
    if "--tray" in args:
        root.after(400, root.iconify)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
