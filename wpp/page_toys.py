#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.page_toys — 桌面工具与宠物页。

桌面工具：
  复用 Windows 7 经典桌面小工具（gadget）的代码/文件/界面，由 Windows++ 自己的 mshta 窗口承载显示，
  不依赖外部侧边栏。
  - 内置 5 个经典小工具（Clock/Calendar/CPU/PicturePuzzle/SlideShow）随程序分发；
  - 可一键导入本机已装的小工具（照搬 gadget 文件到本模块私有目录）；
  - 打开 = 以独立程序窗口运行（mshta），并注入 Windows 7 Sidebar System 对象兼容 stub。
宠物：
  宠物库（默认 FeibiPet + 用户导入），以中等图标网格展示供选择；
  打开·关闭·开机自启动针对当前选中的宠物。
"""

import os
import re
import sys
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from wpp import common as C

# ---- 路径 ----
def _our_gadgets_dir():
    """本模块私有的小工具库目录（随程序读写）。"""
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    d = os.path.join(local, "WindowsPP", "gadgets")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _builtin_gadgets_dir():
    """随程序分发的 5 个经典小工具（开发态在项目 gadgets/，冻结态在 _MEIPASS/gadgets）。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # WindowsPP/
    cand = os.path.join(base, "gadgets")
    if os.path.isdir(cand):
        return cand
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        cand2 = os.path.join(meipass, "gadgets")
        if os.path.isdir(cand2):
            return cand2
    return None


def _user_gadgets_dir():
    """本机已安装的小工具目录（只读参考，可选导入）。"""
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(local, "Microsoft", "Windows Sidebar", "Gadgets")


DEFAULT_PET_DIR = r"C:\Users\李忠浩\OneDrive\Desktop(1)\my file\FeibiPet_v0.0.1"
PET_RUN_NAME = "FeibiPet"
PET_GRID_COLS = 5


# ---------------------------------------------------------------------------
# 小工具解析
# ---------------------------------------------------------------------------
def _find_main_html(gadget_dir):
    """从 gadget.xml 的 <base src> 或目录内首个 html 解析主页面。"""
    xml_candidates = []
    for root, dirs, files in os.walk(gadget_dir):
        for fn in files:
            if fn.lower() == "gadget.xml":
                xml_candidates.append(os.path.join(root, fn))
    patterns = [
        r'<base[^>]*type=["\']html["\'][^>]*src=["\']([^"\']+)["\']',
        r'<base[^>]*src=["\']([^"\']+)["\'][^>]*type=["\']html["\']',
        r'<html[^>]*src=["\']([^"\']+)["\']',
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
    for root, dirs, files in os.walk(gadget_dir):
        for fn in files:
            if fn.lower().endswith((".html", ".htm")):
                return os.path.join(root, fn)
    return None


def _parse_meta(gadget_dir):
    """返回 (显示名, 图标路径或None, 主html路径或None)。"""
    name = os.path.basename(gadget_dir)
    icon = None
    main = _find_main_html(gadget_dir)
    xml = None
    for root, dirs, files in os.walk(gadget_dir):
        if "gadget.xml" in [f.lower() for f in files]:
            xml = os.path.join(root, "gadget.xml")
            break
    if xml and os.path.isfile(xml):
        try:
            txt = open(xml, encoding="utf-8", errors="ignore").read()
        except OSError:
            txt = ""
        m = re.search(r"<name>(.*?)</name>", txt, re.I | re.S)
        if m:
            nm = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if nm:
                name = nm
        m2 = re.search(r"<icon[^>]*src=[\"']([^\"']+)[\"']", txt, re.I)
        if m2:
            ip = os.path.join(os.path.dirname(xml), m2.group(1))
            if os.path.isfile(ip):
                icon = ip
    if icon is None and main:
        # 退而求其次：用目录里第一个 png 当图标
        for f in sorted(os.listdir(os.path.dirname(main))):
            if f.lower().endswith(".png"):
                icon = os.path.join(os.path.dirname(main), f)
                break
    return name, icon, main


def _list_our_gadgets():
    """列出本模块小工具库中的所有小工具，返回 [{key,name,path,icon,main}]。"""
    d = _our_gadgets_dir()
    out = []
    if not os.path.isdir(d):
        return out
    for entry in sorted(os.listdir(d)):
        if not entry.lower().endswith(".gadget"):
            continue
        gdir = os.path.join(d, entry)
        if not os.path.isdir(gdir):
            continue
        nm, icon, main = _parse_meta(gdir)
        out.append({"key": entry, "name": nm, "path": gdir,
                    "icon": icon, "main": main})
    return out


def _ensure_builtins():
    """把随程序分发的 5 个经典小工具拷贝进本模块私有目录（缺失或损坏时重新拷贝）。"""
    src = _builtin_gadgets_dir()
    if not src:
        return
    dst_root = _our_gadgets_dir()
    for name in os.listdir(src):
        if not name.lower().endswith(".gadget"):
            continue
        dst = os.path.join(dst_root, name)
        # 若目录不存在、为空或没有 gadget.xml，则视为损坏，重新拷贝
        needs_copy = True
        if os.path.isdir(dst):
            try:
                if os.listdir(dst) and any(
                    f.lower() == "gadget.xml"
                    for _, _, files in os.walk(dst)
                    for f in files
                ):
                    needs_copy = False
            except Exception:
                pass
        if needs_copy:
            try:
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                shutil.copytree(os.path.join(src, name), dst)
            except Exception:
                pass


def _import_all_from_system():
    """把本机已安装的全部小工具照搬进本模块私有目录。"""
    src = _user_gadgets_dir()
    if not os.path.isdir(src):
        return 0
    dst_root = _our_gadgets_dir()
    n = 0
    for name in os.listdir(src):
        if not name.lower().endswith(".gadget"):
            continue
        dst = os.path.join(dst_root, name)
        if os.path.isdir(dst):
            continue
        try:
            shutil.copytree(os.path.join(src, name), dst)
            n += 1
        except Exception:
            pass
    return n


# ---------------------------------------------------------------------------
# mshta 兼容宿主（注入 System stub，转换 g: 标签）
# ---------------------------------------------------------------------------
def _mshta_path():
    windir = os.environ.get("WINDIR") or r"C:\Windows"
    return os.path.join(windir, "System32", "mshta.exe")


def _detect_encoding(path):
    """检测 gadget 文件编码：先读 BOM，再按内容推断（多为 utf-16le 或 utf-8）。"""
    with open(path, "rb") as f:
        raw = f.read(4)
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # 无 BOM：尝试按 utf-16 解码，若出现大量 NUL 字节则认为是 utf-16le
    with open(path, "rb") as f:
        data = f.read(4096)
    if not data:
        return "utf-8"
    try:
        data.decode("utf-16-le")
        # 若奇数位置有大量 0，更可能是 utf-16
        if data.count(b"\x00") >= max(1, len(data) // 32):
            return "utf-16-le"
    except Exception:
        pass
    return "utf-8"


def _read_text(path):
    enc = _detect_encoding(path)
    with open(path, "r", encoding=enc, errors="ignore") as f:
        return f.read(), enc


def _write_text(path, text, enc):
    with open(path, "w", encoding=enc, errors="ignore") as f:
        f.write(text)


def _make_system_stub(runtime_dir, key):
    """生成注入到 gadget HTML 的 JS stub，模拟 Windows 7 Sidebar 的 System 对象。"""
    runtime_dir_js = runtime_dir.replace("\\", "/")
    stub = r'''<script>
(function(){
  if (window.System && window.System._wpp_stub_v4) return;
  // wpp_stub_v4: 兼容 Windows 7 Sidebar gadget 在 mshta/IE 下的运行
  var stubStorage = {};
  var stubTimeZones = {count: 0, item: function(i){ return null; }};
  var wsh = null;
  try { wsh = new ActiveXObject("WScript.Shell"); } catch(e) {}
  var fso = null;
  try { fso = new ActiveXObject("Scripting.FileSystemObject"); } catch(e) {}
  var shellApp = null;
  try { shellApp = new ActiveXObject("Shell.Application"); } catch(e) {}
  var envCache = {};
  window.System = {
    _wpp_stub_v4: true,
    Gadget: {
      path: "__RUNTIME_DIR__/app",
      name: "__GADGET_KEY__",
      version: "1.0",
      Platform: { version: "6.0" },
      Settings: {
        read: function(n){ try{ return localStorage.getItem("wpp_gadget_" + n) || stubStorage[n] || ""; }catch(e){ return stubStorage[n] || ""; } },
        readString: function(n){ return this.read(n); },
        write: function(n, v){ try{ localStorage.setItem("wpp_gadget_" + n, String(v)); }catch(e){} stubStorage[n] = String(v); },
        writeString: function(n, v){ this.write(n, v); }
      },
      settingsUI: "",
      onSettingsClosed: null,
      onSettingsClosing: null,
      visibilityChanged: null,
      dockingChanged: null,
      onUndock: null,
      onDock: null,
      docked: true,
      undocked: false,
      beginTransition: function(){},
      endTransition: function(){},
      Flyout: { file: "", onShow: null, onHide: null },
      onShowSettings: null,
      onHide: null,
      opacity: 255,
      draggable: true,
      persistInterval: 10000
    },
    Time: {
      now: function(){ return new Date(); },
      timeZones: stubTimeZones,
      getLocalTime: function(){ return new Date(); },
      getCurrentTime: function(){ return new Date(); }
    },
    Environment: {
      getEnvironmentVariable: function(name){
        if (envCache[name] !== undefined) return envCache[name];
        if (!wsh) return "";
        try { var v = wsh.ExpandEnvironmentStrings("%" + name + "%"); envCache[name] = v; return v; } catch(e) { return ""; }
      },
      machineName: (function(){ try{ return wsh ? wsh.ExpandEnvironmentStrings("%COMPUTERNAME%") : "PC"; }catch(e){ return "PC"; } })(),
      userName: (function(){ try{ return wsh ? wsh.ExpandEnvironmentStrings("%USERNAME%") : "User"; }catch(e){ return "User"; } })(),
      getUserName: function(){ return this.userName; },
      getMachineName: function(){ return this.machineName; }
    },
    Debug: {
      outputString: function(s){ try{ if (window.console && console.log) console.log(s); }catch(e){} },
      debugOutputString: function(s){ this.outputString(s); },
      assert: function(cond, msg){ if (!cond) this.outputString("ASSERT: " + msg); }
    },
    Shell: {
      execute: function(file, args, dir, op, show){
        if (!wsh) return;
        try {
          var cmd = '"' + file + '"';
          if (args) cmd += ' ' + args;
          wsh.Run(cmd, show === undefined ? 1 : show, false);
        } catch(e) {}
      },
      executeCommand: function(cmd){
        if (!wsh) return;
        try { wsh.Run(cmd, 1, false); } catch(e) {}
      },
      run: function(cmd){
        if (!wsh) return;
        try { wsh.Run(cmd, 1, false); } catch(e) {}
      },
      folderFromPath: function(path){
        if (!fso) return null;
        try { return fso.GetFolder(path); } catch(e) { return null; }
      },
      fileFromPath: function(path){
        if (!fso) return null;
        try { return fso.GetFile(path); } catch(e) { return null; }
      },
      chooseFile: function(){ return null; },
      saveFile: function(){ return null; },
      executeCommandLine: function(cmd){ this.executeCommand(cmd); },
      executeFile: function(file){ this.execute(file); }
    }
  };
  // mshta/IE 早期可能未暴露 HTMLDivElement/HTMLImageElement，统一做兜底
  var divProto = (typeof HTMLDivElement !== 'undefined' && HTMLDivElement.prototype)
               ? HTMLDivElement.prototype
               : (typeof HTMLElement !== 'undefined' && HTMLElement.prototype)
               ? HTMLElement.prototype : null;
  if (divProto && !divProto._wpp_src_patched) {
    try {
      Object.defineProperty(divProto, 'src', {
        get: function(){ return this.getAttribute('src') || ''; },
        set: function(v){
          this.setAttribute('src', v);
          if (/^url\(/.test(v)) { this.style.backgroundImage = v; }
          else if (v) { this.style.backgroundImage = 'url("' + v + '")'; }
        }
      });
    } catch(e) {}
    divProto.addShadow = function(){};
    divProto._wpp_src_patched = true;
  }
  var imgProto = (typeof HTMLImageElement !== 'undefined' && HTMLImageElement.prototype)
               ? HTMLImageElement.prototype
               : divProto;
  if (imgProto && !imgProto.addShadow) {
    imgProto.addShadow = function(){};
  }
  // 兜底：页面加载后把 <div src="..."> 的静态背景图也应用上
  var fixDivSrc = function(){
    try {
      var divs = document.getElementsByTagName('div');
      for (var i = 0; i < divs.length; i++) {
        var el = divs[i], s = el.getAttribute('src');
        if (s && !/^url\(/.test(el.style.backgroundImage || '')) {
          el.style.backgroundImage = 'url("' + s + '")';
        }
      }
    } catch (e) {}
  };
  if (window.addEventListener) {
    window.addEventListener('load', fixDivSrc);
  } else if (window.attachEvent) {
    window.attachEvent('onload', fixDivSrc);
  } else {
    var oldOnload = window.onload;
    window.onload = function() { if (oldOnload) oldOnload(); fixDivSrc(); };
  }
})();
</script>'''
    return stub.replace("__RUNTIME_DIR__", runtime_dir_js).replace("__GADGET_KEY__", key)


def _transform_gadget_html(html_path, runtime_dir, key):
    """把 gadget HTML 转换为可在 mshta/IE 下运行的 HTA 文件。

    保持原始编码，避免破坏非 utf-16 文件；在 <head> 中注入 System stub、HTA
    应用声明和 IE 文档模式；并将 g: 标签转换为普通 HTML 标签。
    输出为同名的 .hta 文件。
    """
    text, enc = _read_text(html_path)
    stub = _make_system_stub(runtime_dir, key)
    # HTA 应用声明 + IE 文档模式（必须放在 <head> 最前面）
    hta_head = (
        '<hta:application applicationname="WindowsPP_Gadget" border="dialog" '
        'scroll="no" singleinstance="yes" maximizeButton="no" minimizeButton="yes" />\n'
        '<meta http-equiv="X-UA-Compatible" content="IE=edge">\n'
    )
    # 优先在 <head ...> 标签结束后立即插入
    m = re.search(r'<head\b[^>]*>', text, re.I)
    if m:
        insert_pos = m.end()
        text = text[:insert_pos] + "\n" + hta_head + stub + "\n" + text[insert_pos:]
    elif "</head>" in text:
        text = text.replace("</head>", hta_head + stub + "\n</head>", 1)
    else:
        text = hta_head + stub + "\n" + text
    # 转换 Windows 7 gadget 自定义标签 g:background / g:image
    # 先处理成对标签（开+闭），再处理单独开/自闭合标签，最后清理残留闭合标签
    text = re.sub(r'<g:background\b([^>]*)>(.*?)</g:background>',
                  lambda m: f'<div{m.group(1)}>{m.group(2)}</div>', text, flags=re.I | re.S)
    text = re.sub(r'<g:background\s+([^>]*?)\s*/?>',
                  lambda m: f'<div {m.group(1)}></div>', text, flags=re.I)
    text = re.sub(r'</g:background>', '', text, flags=re.I)
    text = re.sub(r'<g:image\b([^>]*)>(.*?)</g:image>',
                  lambda m: f'<img{m.group(1)} alt="" />', text, flags=re.I | re.S)
    text = re.sub(r'<g:image\s+([^>]*?)\s*/?>',
                  lambda m: f'<img {m.group(1)} />', text, flags=re.I)
    text = re.sub(r'</g:image>', "", text, flags=re.I)
    hta_path = os.path.splitext(html_path)[0] + ".hta"
    _write_text(hta_path, text, enc)
    return hta_path


def _prepare_gadget_runtime(key, html):
    """为 gadget 创建运行时副本并做 IE/HTA 兼容转换，返回转换后的 .hta 路径。

    若 html 为 None 或不存在则返回 None。

    已转换过（运行时存在且已注入 System stub v4）则直接复用，避免每次打开都
    重建目录（更省资源，也避免重复删除/复制）。"""
    if not html or not os.path.isfile(html):
        return None
    app_dir = os.path.dirname(html)          # .../app/en-US 或 .../gadget根
    app_root = os.path.dirname(app_dir) if os.path.basename(app_dir).lower() in ("en-us", "zh-cn") else app_dir
    runtime_root = os.path.join(_our_gadgets_dir(), key, "runtime")
    runtime_app = os.path.join(runtime_root, "app")
    rel = os.path.relpath(html, app_root)
    existing_hta = os.path.join(runtime_app, os.path.splitext(rel)[0] + ".hta")
    if os.path.isfile(existing_hta):
        try:
            with open(existing_hta, "r", encoding=_detect_encoding(existing_hta), errors="ignore") as f:
                if "wpp_stub_v4" in f.read():
                    return existing_hta          # 已转换（v4 stub），直接复用
        except Exception:
            pass
    if os.path.isdir(runtime_root):
        try:
            shutil.rmtree(runtime_root)
        except Exception:
            pass
    os.makedirs(runtime_root, exist_ok=True)
    shutil.copytree(app_root, runtime_app)
    new_html = os.path.join(runtime_app, rel)
    new_hta = None
    if os.path.isfile(new_html):
        new_hta = _transform_gadget_html(new_html, runtime_root, key)
    settings_html = os.path.join(os.path.dirname(new_html), "settings.html")
    if os.path.isfile(settings_html):
        _transform_gadget_html(settings_html, runtime_root, key)
    return new_hta or existing_hta


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


GADGET_RUN_PREFIX = "WindowsPP_Gadget_"


class PageToys(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg="systemTransparent")
        self.app = app
        self.root = app.root
        self._icons = []          # 防止 PhotoImage 被 GC
        self._pet_btns = {}
        self._pet_selected = ""
        self._pet_proc = None
        self._build_ui()
        self.refresh()

    # ---------- UI ----------
    def _build_ui(self):
        # 工具区：本模块自带的小工具库
        f1 = ttk.LabelFrame(self, text="🧰 桌面工具（Windows 7 经典小工具，本程序独立承载）", padding=8)
        f1.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        ttk.Label(f1,
                  text="以下小工具直接复用 Windows 7 经典小工具（gadget）的代码与界面，"
                       "由 Windows++ 自己的窗口承载显示，不依赖外部侧边栏。"
                       "点击「▶ 打开」即以独立窗口运行该小工具。",
                  foreground="#555", wraplength=1000).pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(f1)
        row.pack(fill="x", pady=(0, 6))
        ttk.Button(row, text="📥 从本机导入全部小工具",
                   command=self._import_all).pack(side="left")
        self.gadget_status = ttk.Label(row, text="", foreground="#888")
        self.gadget_status.pack(side="left", padx=10)

        self._gadget_canvas = tk.Canvas(f1, height=260, bg="#FFFFFF")
        self._gadget_scroll = ttk.Scrollbar(f1, orient="vertical",
                                            command=self._gadget_canvas.yview)
        self._gadget_list = ttk.Frame(self._gadget_canvas)
        self._gadget_canvas.configure(yscrollcommand=self._gadget_scroll.set)
        self._gadget_canvas.pack(side="left", fill="both", expand=True)
        self._gadget_scroll.pack(side="right", fill="y")
        self._gadget_canvas.create_window((0, 0), window=self._gadget_list, anchor="nw")
        self._gadget_list.bind(
            "<Configure>",
            lambda e: self._gadget_canvas.configure(scrollregion=self._gadget_canvas.bbox("all")))

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
        _ensure_builtins()
        for w in self._gadget_list.winfo_children():
            w.destroy()
        self._icons = []
        gadgets = _list_our_gadgets()
        if not gadgets:
            ttk.Label(self._gadget_list, text="（暂无小工具，点击上方「导入」）",
                      foreground="#9CA3AF").pack(anchor="w", pady=6)
        cols = 3
        for i, g in enumerate(gadgets):
            card = ttk.Frame(self._gadget_list, relief="ridge", borderwidth=1, padding=6)
            card.grid(row=i // cols, column=i % cols, padx=6, pady=6, sticky="nsew")
            icon = None
            if g["icon"] and os.path.isfile(g["icon"]):
                try:
                    img = tk.PhotoImage(file=g["icon"])
                    self._icons.append(img)
                    icon = img
                except Exception:
                    icon = None
            lbl = ttk.Label(card, image=icon) if icon else ttk.Label(card, text="🧩")
            lbl.pack(pady=(0, 4))
            ttk.Label(card, text=g["name"], font=("Microsoft YaHei UI", 10, "bold"),
                      wraplength=180, justify="center").pack()
            btns = ttk.Frame(card)
            btns.pack(pady=(4, 0))
            ttk.Button(btns, text="▶ 打开", width=8,
                       command=lambda gg=g: self._open(gg)).pack(side="left", padx=2)
            ttk.Button(btns, text="🗑 卸载", width=8,
                       command=lambda gg=g: self._remove(gg)).pack(side="left", padx=2)
            var = tk.BooleanVar(value=bool(C.get_autostart_cmd(GADGET_RUN_PREFIX + g["key"])))
            cb = ttk.Checkbutton(card, text="自启动", variable=var,
                                 command=lambda gg=g, v=var: self._gadget_autostart(gg, v))
            cb.pack(pady=(4, 0))
        self._refresh_pet_grid()

    # ---------- 小工具：导入 / 打开 / 卸载 / 自启动 ----------
    def _import_all(self):
        self.gadget_status.configure(text="导入中…", foreground="#B45309")
        self.app.set_status("正在从本机导入全部小工具…")

        def worker():
            n = _import_all_from_system()
            self.root.after(0, lambda: self._import_done(n))

        threading.Thread(target=worker, daemon=True).start()

    def _import_done(self, n):
        self.gadget_status.configure(
            text=f"已导入 {n} 个小工具" if n else "没有可导入的新小工具",
            foreground="#16A34A" if n else "#888")
        self.app.set_status(f"从本机导入完成：{n} 个")
        self.refresh()

    def _open(self, g):
        if not g["main"]:
            messagebox.showerror(C.APP_NAME, "找不到该小工具的主页面文件。")
            return
        mshta = _mshta_path()
        try:
            runtime_hta = _prepare_gadget_runtime(g["key"], g["main"])
            if os.path.isfile(mshta):
                subprocess.Popen([mshta, runtime_hta], startupinfo=C._startupinfo())
                self.app.set_status(f"已打开小工具「{g['name']}」（独立窗口）")
                return
            os.startfile(runtime_hta)
        except Exception as e:
            messagebox.showerror(C.APP_NAME, f"打开失败: {e}")

    def _remove(self, g):
        if not messagebox.askyesno(C.APP_NAME, f"确定从本程序卸载小工具「{g['name']}」？（删除本地文件）"):
            return
        C._sync_autostart(False, GADGET_RUN_PREFIX + g["key"])
        try:
            shutil.rmtree(g["path"])
        except Exception as e:
            messagebox.showerror(C.APP_NAME, f"卸载失败: {e}")
        self.refresh()
        self.app.set_status(f"已卸载小工具「{g['name']}」")

    def _gadget_autostart(self, g, var):
        v = var.get()
        if v and not g["main"]:
            messagebox.showwarning(C.APP_NAME, "未找到小工具的可运行文件，无法自启动。")
            var.set(False)
            return
        try:
            runtime_hta = _prepare_gadget_runtime(g["key"], g["main"])
        except Exception as e:
            messagebox.showwarning(C.APP_NAME, f"准备小工具运行环境失败：{e}")
            var.set(False)
            return
        mshta = _mshta_path()
        cmd = f'"{mshta}" "{runtime_hta}"' if os.path.isfile(mshta) else f'"{runtime_hta}"'
        C._sync_autostart(v, GADGET_RUN_PREFIX + g["key"], raw_cmd=cmd)
        self.app.set_status(f"小工具「{g['name']}」开机自启动已{'开启' if v else '关闭'}")

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
