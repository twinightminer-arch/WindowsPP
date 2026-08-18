#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows++ — 一键识别电脑上安装的所有软件是否最新版本，并启动自动更新
依赖：Windows 10/11 + winget（Windows 包管理器，系统自带）+ Python 3.7+（含 tkinter）

功能：扫描已装软件 / 一键更新 / 暂停·继续 / 取消全部 / 跳过当前 / 取消当前 /
      实时状态（等待·进行中·成功·超时·失败·已跳过·已取消·已是最新）/
      右键取消勾选 / 导出报告 / 旧版文件清理（扫描·杀出，保留登录与数据）/
      扫描并清除下载的安装包 / 更新后版本交叉验证（不再误报可更新）/
      设置界面（桌面图标锁定 + 开机启动开关）/ 桌面新文件写入提示

用法：
    python WindowsPP.py         # 打开图形界面
    python WindowsPP.py --scan  # 命令行模式：仅扫描并输出报告，不更新
    python WindowsPP.py --tray  # 后台最小化运行（开机启动场景，监控桌面）
"""

import os
import sys
import re
import time
import shutil
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

# 安装包扩展名（用于“清除下载的安装包”）
INSTALLER_EXTS = {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle"}

# 目录名中的版本号模式（用于识别“版本目录”，如 9.9.22 / 26.02 / 2.4.0.0 / 9.9.33-52230）
_VER_IN_DIR_RE = re.compile(r"\d+(?:\.\d+){1,3}(?:[-_]\d+)*")

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
# 版本比较
# ============================================================
def _ver_parts(s):
    """把版本串拆成 (权重, 值) 序列用于比较。数字段权重高、按数值比，字母段按字典序。"""
    s = str(s or "").strip().lower()
    parts = re.findall(r"\d+|[a-z]+", s)
    out = []
    for p in parts:
        if p.isdigit():
            out.append((1, int(p)))
        else:
            out.append((0, p))
    return out


def _cmp_ver(a, b):
    """比较两个版本号：a>b 返回 1，a<b 返回 -1，相等/无法区分返回 0。
    尾零视为等价：'9.9.33' == '9.9.33.0'。"""
    pa, pb = _ver_parts(a), _ver_parts(b)
    for x, y in zip(pa, pb):
        if x != y:
            return (x > y) - (x < y)
    if len(pa) == len(pb):
        return 0
    longer, shorter = (pa, pb) if len(pa) > len(pb) else (pb, pa)
    rest = longer[len(shorter):]
    if all(x[0] == 1 and x[1] == 0 for x in rest):
        return 0
    return (len(pa) > len(pb)) - (len(pa) < len(pb))


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

    def _row(app, matched, status):
        return {
            "name": app["name"],
            "version": app["version"] or (matched["version"] if matched else ""),
            "available": matched["available"] if matched else "",
            "source": matched["source"] if matched else "",
            "id": matched["id"] if matched else "",
            "publisher": app["publisher"],
            "install_loc": app["install_loc"],
            "uninstall": app["uninstall"],
            "status": status,
            "upd_state": "pending",
        }

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
            status = "updatable"
            # 交叉校验：注册表里的当前版本已 >= winget 可用版本 -> 实际已是最新。
            # winget 仍报“可升级”通常是旧版本文件残留或清单滞后（如 QQ 双版本）。
            if app["version"] and _cmp_ver(app["version"], matched["available"]) >= 0:
                status = "latest"
            rows.append(_row(app, matched, status))
        else:
            rows.append(_row(app, None, "unknown"))  # winget 未报告更新

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
            "install_loc": "",
            "uninstall": "",
            "status": "updatable",
            "upd_state": "pending",
        })

    # 排序：可更新 > 已是最新 > 未知
    order = {"updatable": 0, "latest": 1, "unknown": 2}
    rows.sort(key=lambda r: (order.get(r["status"], 9), _norm(r["name"])))
    return rows


# ============================================================
# 磁盘清理：旧版本文件 / 下载安装包
# ============================================================
def scan_old_version_dirs(rows):
    """扫描各行安装目录，找出“同一父目录下并存多版本”中的旧版本目录。

    返回 [(app_name, parent_dir, old_dir, version), ...]
    规则：仅当父目录下存在 >=2 个目录名含版本号的子目录时，保留版本最大者，
    其余判为旧版本残留。只针对程序目录，绝不触碰 AppData/Documents 等用户数据。
    """
    def _effective_loc(r):
        loc = (r.get("install_loc") or "").strip()
        if not loc:
            # 注册表未写 InstallLocation（如 QQNT）时，从卸载命令提取安装目录
            un = (r.get("uninstall") or "").strip()
            cand = ""
            m = re.search(r'"[^"]+"', un)
            if m:
                cand = m.group(0).strip('"')
            elif un and not un.startswith("MsiExec"):
                cand = un.split()[-1]
            if cand and os.path.isfile(cand):
                loc = os.path.dirname(cand)
        return os.path.normcase(os.path.normpath(loc)) if loc and os.path.isdir(loc) else ""

    row_locs = []  # (norm_loc, name)
    for r in rows:
        loc = _effective_loc(r)
        if loc:
            row_locs.append((loc, r["name"]))

    parents = {}  # 父目录 -> [(full, ver, name)]
    extra_sub = ("versions", "resources", "resources/app",
                 "resources/app/versions", "app/versions", "bin")
    for loc, _ in row_locs:
        bases = [loc]
        for extra in extra_sub:
            p = os.path.join(loc, extra)
            if os.path.isdir(p):
                bases.append(p)
        for base in bases:
            try:
                entries = sorted(os.listdir(base))
            except OSError:
                continue
            bl = os.path.normcase(base)
            for e in entries:
                full = os.path.join(base, e)
                if not os.path.isdir(full):
                    continue
                el = e.lower()
                # 排除用户数据/配置类目录，避免误删
                if any(t in el for t in ("userdata", "documents", "appdata",
                                         "cache", "temp", "log", "config", "data")):
                    continue
                m = _VER_IN_DIR_RE.search(e)
                if m:
                    existing = parents.get(bl, [])
                    if not any(x[0] == full for x in existing):
                        parents.setdefault(bl, []).append((full, m.group(0), e))

    findings = []
    for base, items in parents.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda x: _ver_parts(x[1]), reverse=True)
        for full, ver, name in items[1:]:
            app = "未知软件"
            for loc, aname in row_locs:
                if loc == base:
                    app = aname
                    break
                for extra in extra_sub:
                    if os.path.normcase(os.path.join(loc, extra)) == base:
                        app = aname
                        break
            findings.append((app, base, full, ver))
    findings.sort(key=lambda x: (x[0].lower(), x[2].lower()))
    return findings


def scan_installers():
    """扫描常见下载/临时目录中的安装包，返回 [{path,size,mtime}]，按大小降序。"""
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    dirs = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
        os.environ.get("TEMP", ""),
        os.path.join(local, "Temp"),
        os.path.join(local, "Packages", "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe", "LocalState"),
    ]
    out = []
    seen = set()
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for e in entries:
            full = os.path.join(d, e)
            if not os.path.isfile(full):
                continue
            if os.path.splitext(e)[1].lower() not in INSTALLER_EXTS:
                continue
            key = os.path.normcase(full)
            if key in seen:
                continue
            seen.add(key)
            try:
                out.append({"path": full, "size": os.path.getsize(full),
                            "mtime": os.path.getmtime(full)})
            except OSError:
                continue
    out.sort(key=lambda x: -x["size"])
    return out


def safe_delete_path(path):
    """删除文件或目录。返回 (ok, msg)。正在使用/无权限的文件会失败并跳过。"""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True, f"已删除: {path}"
    except Exception as e:
        return False, f"删除失败: {path}（{e}；可能文件正被占用，请关闭相关软件后重试）"


# ============================================================
# 设置（注册表 HKCU\Software\WindowsPP）/ 桌面图标锁定 / 开机启动
# ============================================================
SETTINGS_KEY = r"Software\WindowsPP"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "WindowsPP"
# 桌面图标“自动排列”位（Shell Bags FFlags）
FFLAGS_AUTO_ARRANGE = 0x40000000


def load_settings():
    """读取 HKCU\\Software\\WindowsPP 下的设置。"""
    d = {"icon_lock": False, "autostart": False}
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
        for name in ("IconLock", "AutoStart"):
            try:
                d[name.lower()] = bool(winreg.QueryValueEx(key, name)[0])
            except OSError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass
    return d


def save_settings(icon_lock=None, autostart=None):
    """写入设置并同步开机启动注册表项。返回最新设置 dict。"""
    import winreg
    cur = load_settings()
    if icon_lock is not None:
        cur["icon_lock"] = bool(icon_lock)
    if autostart is not None:
        cur["autostart"] = bool(autostart)
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
        winreg.SetValueEx(key, "IconLock", 0, winreg.REG_DWORD, int(cur["icon_lock"]))
        winreg.SetValueEx(key, "AutoStart", 0, winreg.REG_DWORD, int(cur["autostart"]))
        winreg.CloseKey(key)
    except OSError:
        pass
    # 同步“启动”项
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_READ | winreg.KEY_WRITE)
        if cur["autostart"]:
            py = sys.executable
            pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
            if not os.path.isfile(pyw):
                pyw = py
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "WindowsPP.py")
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ,
                              f'"{pyw}" "{script}" --tray')
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except OSError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass
    return cur


def get_autostart_cmd():
    """读取当前开机启动项命令行（调试用）。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        val, _ = winreg.QueryValueEx(key, RUN_VALUE)
        winreg.CloseKey(key)
        return val
    except OSError:
        return None


def set_desktop_icon_lock(enabled):
    """启用/关闭桌面图标“自动排列”（即锁定排布）。返回 (ok, msg)。"""
    import winreg
    import ctypes
    path = r"Software\Microsoft\Windows\Shell\Bags\1\Desktop"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                             winreg.KEY_READ | winreg.KEY_WRITE)
    except OSError:
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
        except OSError as e:
            return False, f"无法打开桌面设置注册表: {e}"
    try:
        try:
            fflags, _ = winreg.QueryValueEx(key, "FFlags")
        except OSError:
            fflags = 0
        if enabled:
            new = fflags | FFLAGS_AUTO_ARRANGE
        else:
            new = fflags & ~FFLAGS_AUTO_ARRANGE
        winreg.SetValueEx(key, "FFlags", 0, winreg.REG_DWORD, new)
        winreg.CloseKey(key)
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
        except Exception:
            pass
        return True, ("已启用桌面图标锁定" if enabled else "已关闭桌面图标锁定")
    except OSError as e:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
        return False, f"写入失败: {e}"


class DesktopMonitor(threading.Thread):
    """监控桌面目录的新文件/文件夹写入；锁定开启时经回调上报（只读，不修改任何文件）。"""

    ACTION_ADDED = 1
    ACTION_RENAMED_NEW = 5

    def __init__(self, path, on_event):
        super().__init__(daemon=True)
        self.path = path
        self.on_event = on_event      # callable(action_text, filename)
        self._stop_evt = threading.Event()
        self._h = None

    def stop(self):
        self._stop_evt.set()
        if self._h:
            try:
                ctypes.windll.kernel32.CancelIoEx(self._h, None)
            except Exception:
                pass

    def run(self):
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        FILE_LIST_DIRECTORY = 0x0001
        share = 0x1 | 0x2 | 0x4          # 允许读/写/删共享，避免影响桌面操作
        OPEN_EXISTING = 3
        FLAG_BACKUP = 0x02000000
        CHANGES = 0x1 | 0x2 | 0x100      # FILE_NAME | DIR_NAME | CREATION
        try:
            CreateFileW = kernel32.CreateFileW
            CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.HANDLE]
            CreateFileW.restype = wintypes.HANDLE
            ReadDirectoryChangesW = kernel32.ReadDirectoryChangesW
            ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                              wintypes.DWORD, wintypes.BOOL,
                                              wintypes.DWORD, wintypes.LPDWORD,
                                              wintypes.LPVOID, wintypes.LPVOID]
            ReadDirectoryChangesW.restype = wintypes.BOOL
            CloseHandle = kernel32.CloseHandle
            CancelIoEx = kernel32.CancelIoEx
        except Exception:
            return
        self._h = CreateFileW(self.path, FILE_LIST_DIRECTORY, share, None,
                              OPEN_EXISTING, FLAG_BACKUP, None)
        if not self._h or self._h == wintypes.HANDLE(-1).value:
            return
        buf = ctypes.create_string_buffer(64 * 1024)
        try:
            while not self._stop_evt.is_set():
                n = wintypes.DWORD(0)
                ok = ReadDirectoryChangesW(self._h, buf, len(buf), True,
                                           CHANGES, ctypes.byref(n), None, None)
                if not ok:
                    break  # 句柄被取消/关闭
                self._parse(buf, n.value)
        finally:
            try:
                CancelIoEx(self._h, None)
            except Exception:
                pass
            CloseHandle(self._h)

    def _parse(self, buf, size):
        import struct
        off = 0
        while off + 12 <= size:
            next_off = struct.unpack_from("<I", buf, off)[0]
            action = struct.unpack_from("<I", buf, off + 4)[0]
            nlen = struct.unpack_from("<I", buf, off + 8)[0]
            if nlen <= 0:
                break
            name = buf[off + 12: off + 12 + nlen].decode("utf-16-le", "ignore")
            if action in (self.ACTION_ADDED, self.ACTION_RENAMED_NEW):
                self.on_event("创建" if action == self.ACTION_ADDED else "重命名", name)
            if next_off == 0:
                break
            off += next_off


def query_installed_version(pkg_id):
    """更新后用 winget list 查询实际安装版本（尽力而为，失败返回 None）。"""
    out, err, rc = run_cmd(
        f'winget list --id "{pkg_id}" -e --accept-source-agreements --disable-interactivity',
        timeout=120)
    if rc != 0:
        return None
    for line in out.splitlines():
        s = line.strip()
        if not s or s.startswith("-") or pkg_id.lower() not in s.lower():
            continue
        parts = s.split()
        if len(parts) >= 3 and parts[1].lower() == pkg_id.lower():
            return parts[2]
    return None


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
    latest = [r for r in rows if r["status"] == "latest"]
    lines.append(f"可更新: {len(updatable)} 个；已是最新: {len(latest)} 个；"
                 f"无法检查: {len(rows) - len(updatable) - len(latest)} 个")
    lines.append("")
    for r in updatable:
        lines.append(f"  [可更新] {r['name']}")
        lines.append(f"           当前 {r['version']} → 最新 {r['available']}  (ID: {r['id']}, 来源: {r['source']})")
    lines.append("")
    lines.append(f"已是最新: {len(latest)} 个")
    for r in latest:
        lines.append(f"  [已最新] {r['name']}  {r['version']}")
    lines.append("")
    lines.append(f"未报告更新/无法检查: {len(rows) - len(updatable) - len(latest)} 个")
    for r in rows:
        if r["status"] not in ("updatable", "latest"):
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
        self.root.geometry("1120x700")
        self.root.minsize(960, 600)

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

        # 更新后附加处理选项（在确认对话框中勾选）
        self.clean_old_opt = False
        self.clean_inst_opt = False

        # 设置与桌面监控
        self.settings = load_settings()
        self.icon_locked = self.settings["icon_lock"]
        self._desk_monitor = None
        self._last_desk_prompt = 0.0
        self._settings_dlg = None
        self._settings_dlg_vars = None

        self._set_icon()
        self._build_ui()
        self.start_desktop_monitor()

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
            text="① 扫描 → ② 勾选可更新项（可右键取消勾选）→ ③ 开始更新，可暂停/跳过/取消；更新后可清理旧文件与安装包",
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left")
        self.status_lbl = ttk.Label(top, text="就绪", foreground="#555")
        self.status_lbl.pack(side="right")

        # 按钮区（第一行：主操作）
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
        self.settings_btn = ttk.Button(btns, text="⚙ 设置", command=self.open_settings)
        self.settings_btn.pack(side="left", padx=(0, 6))
        self.clean_inst_btn = ttk.Button(btns, text="🗑 清除下载安装包", command=self.on_clean_installers)
        self.clean_inst_btn.pack(side="left", padx=(0, 6))

        # 按钮区（第二行：更新控制）
        btns2 = ttk.Frame(self.root, padding=(10, 2))
        btns2.pack(fill="x")
        ttk.Label(btns2, text="更新控制：", foreground="#555").pack(side="left")
        self.pause_btn = ttk.Button(btns2, text="⏸ 暂停更新", command=self.on_pause_toggle, state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 6))
        self.skip_btn = ttk.Button(btns2, text="⏭ 跳过当前", command=self.on_skip_current, state="disabled")
        self.skip_btn.pack(side="left", padx=(0, 6))
        self.cancelcur_btn = ttk.Button(btns2, text="✖ 取消当前", command=self.on_cancel_current, state="disabled")
        self.cancelcur_btn.pack(side="left", padx=(0, 6))
        self.cancelall_btn = ttk.Button(btns2, text="⏹ 取消全部", command=self.on_cancel_all, state="disabled")
        self.cancelall_btn.pack(side="left", padx=(0, 6))
        self.clean_old_btn = ttk.Button(btns2, text="🧹 清理旧版本文件", command=self.on_clean_old, state="disabled")
        self.clean_old_btn.pack(side="left", padx=(6, 0))
        self.scan_old_btn = ttk.Button(btns2, text="🔍 扫描旧版文件", command=self.on_scan_old, state="disabled")
        self.scan_old_btn.pack(side="left", padx=(6, 0))

        # 表格
        columns = ("chk", "name", "version", "available", "status", "source", "publisher")
        headers = {
            "chk": "✔", "name": "软件名称", "version": "当前版本",
            "available": "最新版本", "status": "状态",
            "source": "来源", "publisher": "发布者",
        }
        widths = {"chk": 36, "name": 280, "version": 110, "available": 110,
                  "status": 90, "source": 70, "publisher": 150}

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
        self.tree.tag_configure("latest", foreground="#16A34A")
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
            self.settings_btn.configure(state="disabled")
            self.clean_inst_btn.configure(state="disabled")
            self.clean_old_btn.configure(state="disabled")
            self.scan_old_btn.configure(state="disabled")
            self.pause_btn.configure(state="normal")
            self.skip_btn.configure(state="normal")
            self.cancelcur_btn.configure(state="normal")
            self.cancelall_btn.configure(state="normal")
        else:
            self.scan_btn.configure(state="normal")
            self.update_btn.configure(state="normal" if self.rows else "disabled")
            self.selall_btn.configure(state="normal" if self.rows else "disabled")
            self.export_btn.configure(state="normal" if self.rows else "disabled")
            self.settings_btn.configure(state="normal")
            self.clean_inst_btn.configure(state="normal")
            self.clean_old_btn.configure(state="normal" if self.rows else "disabled")
            self.scan_old_btn.configure(state="normal" if self.rows else "disabled")
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
                st_text = "可更新"
            elif r["status"] == "latest":
                r["checked"] = False
                chk = ""
                st_text = "已是最新"
            else:
                r["checked"] = False
                chk = ""
                st_text = "—"
            avail = r["available"] or ("—" if r["status"] == "unknown" else "")
            item = self.tree.insert("", "end", values=(
                chk, r["name"], r["version"] or "—", avail, st_text,
                r["source"] or "—", r["publisher"] or "—",
            ), tags=(r["status"],))
            self.item_row[item] = r

        n_up = sum(1 for r in rows if r["status"] == "updatable")
        n_latest = sum(1 for r in rows if r["status"] == "latest")
        self.set_status(f"共 {len(rows)} 个软件，{n_up} 个可更新，{n_latest} 个已是最新")
        self.log(f"扫描完成：共 {len(rows)} 个软件，可更新 {n_up} 个，已是最新 {n_latest} 个"
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
        opts = self._ask_update_options(targets)
        if opts is None:
            return
        self.clean_old_opt, self.clean_inst_opt = opts

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

    # ---------- 自定义对话框 ----------
    def _ask_update_options(self, targets):
        """更新前确认对话框：清单 + 两个附加选项。返回 (clean_old, clean_inst) 或 None（取消）。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("确认更新")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 60, self.root.winfo_rooty() + 60))
        result = {"v": None}

        head = ttk.LabelFrame(dlg, text=f"即将通过 winget 更新 {len(targets)} 个软件", padding=8)
        head.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        txt = tk.Text(head, height=8, width=70, font=("Microsoft YaHei UI", 9))
        for r in targets:
            txt.insert("end", f"· {r['name']}  {r['version']} → {r['available']}\n")
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)

        optf = ttk.LabelFrame(dlg, text="更新后处理（可勾选）", padding=8)
        optf.pack(fill="x", padx=10, pady=4)
        v1 = tk.BooleanVar(value=True)
        v2 = tk.BooleanVar(value=False)
        ttk.Checkbutton(optf, text="✔ 清理旧版本文件残留（仅删旧程序目录，保留登录与使用数据）",
                        variable=v1).pack(anchor="w")
        ttk.Checkbutton(optf, text="✔ 扫描并清除下载目录中的安装包（释放磁盘空间）",
                        variable=v2).pack(anchor="w")
        ttk.Label(optf, text="提示：更新过程可能需几分钟到十几分钟，部分软件更新完可能要求重启。",
                  foreground="#888", font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(4, 0))

        btns = ttk.Frame(dlg, padding=(10, 8))
        btns.pack(fill="x")
        def on_ok():
            result["v"] = (v1.get(), v2.get())
            dlg.destroy()
        def on_cancel():
            result["v"] = None
            dlg.destroy()
        ttk.Button(btns, text="开始更新", command=on_ok).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="取消", command=on_cancel).pack(side="right")
        dlg.bind("<Escape>", lambda e: on_cancel())
        dlg.wait_window()
        return result["v"]

    def _ask_delete_list(self, title, items, note):
        """items: [{desc, path}]；Listbox 多选默认全选。返回选中项列表或 None（取消）。"""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 80, self.root.winfo_rooty() + 80))
        result = {"v": None}

        ttk.Label(dlg, text=note, wraplength=600, justify="left",
                  foreground="#555").pack(anchor="w", padx=10, pady=(10, 4))

        frame = ttk.Frame(dlg, padding=(10, 4))
        frame.pack(fill="both", expand=True)
        lb = tk.Listbox(frame, selectmode="multiple", height=min(len(items), 12),
                        font=("Microsoft YaHei UI", 9), width=88)
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
        def on_ok():
            result["v"] = [items[i] for i in lb.curselection()]
            dlg.destroy()
        def on_cancel():
            result["v"] = None
            dlg.destroy()
        def on_all():
            for i in range(len(items)):
                lb.selection_set(i)
        def on_none():
            for i in range(len(items)):
                lb.selection_clear(i)
        ttk.Button(btns, text="全选", command=on_all).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="全不选", command=on_none).pack(side="left")
        ttk.Button(btns, text="确认删除", command=on_ok).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="取消", command=on_cancel).pack(side="right")
        dlg.bind("<Escape>", lambda e: on_cancel())
        dlg.wait_window()
        return result["v"]

    # ---------- 设置界面（桌面图标锁定 / 开机启动 / 旧文件清理入口） ----------
    def open_settings(self):
        if self.busy:
            return
        if self._settings_dlg is not None and self._settings_dlg.winfo_exists():
            self._settings_dlg.lift()
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Windows++ 设置")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 120, self.root.winfo_rooty() + 60))
        self._settings_dlg = dlg
        vars_ = {"icon_lock": tk.BooleanVar(value=self.icon_locked),
                 "autostart": tk.BooleanVar(value=self.settings["autostart"])}
        self._settings_dlg_vars = vars_

        # 1) 旧版本文件清理（扫描 / 杀出）
        f1 = ttk.LabelFrame(dlg, text="旧版本文件清理", padding=8)
        f1.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(f1,
                  text="检测软件安装目录中“同目录并存多版本”的旧版残留（仅删旧程序目录，不触碰登录与使用数据）：",
                  wraplength=460, foreground="#555").pack(anchor="w")
        bf1 = ttk.Frame(f1)
        bf1.pack(anchor="w", pady=(6, 0))
        ttk.Button(bf1, text="🔍 扫描旧版文件（只列出）", command=self.on_scan_old).pack(side="left", padx=(0, 8))
        ttk.Button(bf1, text="🗡 杀出旧版文件（扫描并删除）", command=self.on_clean_old).pack(side="left")

        # 2) 桌面图标锁定
        f2 = ttk.LabelFrame(dlg, text="桌面图标锁定", padding=8)
        f2.pack(fill="x", padx=10, pady=4)
        ttk.Checkbutton(f2, text="锁定桌面图标排布（自动对齐网格，禁止拖乱）",
                        variable=vars_["icon_lock"],
                        command=self._apply_icon_lock).pack(anchor="w")
        ttk.Label(f2,
                  text="开启后：桌面新增文件/文件夹时会弹窗提示，可选择临时关闭锁定进行整理。\n"
                       "更改立即写入注册表；若图标未即时变化，请右键桌面 → 查看 → 勾选「自动排列图标」，\n或重启资源管理器 / 重启电脑后生效。",
                  wraplength=460, foreground="#888",
                  font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(4, 0))

        # 3) 开机启动
        f3 = ttk.LabelFrame(dlg, text="开机启动", padding=8)
        f3.pack(fill="x", padx=10, pady=4)
        ttk.Checkbutton(f3, text="开机自动启动 Windows++（后台最小化运行，监控桌面）",
                        variable=vars_["autostart"],
                        command=self._apply_autostart).pack(anchor="w")
        ttk.Label(f3,
                  text="勾选后写入注册表「启动」项，下次开机自动后台运行；取消勾选即移除启动项。",
                  wraplength=460, foreground="#888",
                  font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(4, 0))

        bf3 = ttk.Frame(dlg, padding=(10, 8))
        bf3.pack(fill="x")
        ttk.Button(bf3, text="关闭", command=self._close_settings).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", self._close_settings)

    def _close_settings(self):
        self._settings_dlg_vars = None
        dlg = self._settings_dlg
        self._settings_dlg = None
        if dlg is not None:
            try:
                dlg.destroy()
            except Exception:
                pass

    def _apply_icon_lock(self):
        if self._settings_dlg_vars is not None:
            self.set_icon_lock(self._settings_dlg_vars["icon_lock"].get())

    def _apply_autostart(self):
        if self._settings_dlg_vars is None:
            return
        v = self._settings_dlg_vars["autostart"].get()
        self.settings = save_settings(autostart=v)
        self.log("🚀 开机启动已" + ("启用" if v else "关闭"))
        self.set_status("开机启动已" + ("启用" if v else "关闭"))

    def set_icon_lock(self, enabled, notify=True):
        ok, msg = set_desktop_icon_lock(enabled)
        self.icon_locked = enabled
        self.settings = save_settings(icon_lock=enabled)
        self.log(f"🔒 {msg}")
        self.set_status(msg)
        if self._settings_dlg_vars is not None:
            self._settings_dlg_vars["icon_lock"].set(enabled)
        if ok and notify:
            messagebox.showinfo(
                APP_NAME,
                msg + "\n\n提示：若桌面图标未立即变化，请右键桌面 → 查看 → 勾选「自动排列图标」，"
                      "或重启资源管理器 / 重启电脑后生效。")

    # ---------- 桌面监控（新文件写入提示） ----------
    def _desktop_path(self):
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf)
            return buf.value
        except Exception:
            return os.path.join(os.path.expanduser("~"), "Desktop")

    def start_desktop_monitor(self):
        if self._desk_monitor is not None:
            return
        path = self._desktop_path()
        if not os.path.isdir(path):
            return
        self._desk_monitor = DesktopMonitor(path, self._on_desktop_event)
        self._desk_monitor.start()

    def _on_desktop_event(self, action, name):
        # 仅在锁定开启时提示；过滤临时文件；15 秒冷却避免轰炸
        if not self.icon_locked:
            return
        base = os.path.basename((name or "").lower())
        if base.startswith("~$") or base.endswith((".tmp", ".temp")):
            return
        now = time.time()
        if now - self._last_desk_prompt < 15:
            return
        self._last_desk_prompt = now
        self._queue.put(("desktop_new", action, name))

    # ---------- 清理旧版本文件 ----------
    def on_clean_old(self):
        if self.busy or not self.rows:
            return
        self.set_status("正在扫描旧版本文件…")
        self.log("🧹 开始扫描旧版本文件残留…")

        def worker():
            findings = scan_old_version_dirs(self.rows)
            self.root.after(0, lambda: self._clean_old_done(findings))

        threading.Thread(target=worker, daemon=True).start()

    def _clean_old_done(self, findings):
        if not findings:
            self.log("🧹 未发现旧版本文件残留")
            self.set_status(f"共 {len(self.rows)} 个软件，无旧版本残留")
            messagebox.showinfo(APP_NAME, "未发现旧版本文件残留 🎉")
            return
        items = [{"desc": f"【{app}】旧版本 {ver}\n    {full}",
                  "path": full} for app, _, full, ver in findings]
        chosen = self._ask_delete_list(
            "清理旧版本文件",
            items,
            f"发现 {len(findings)} 个疑似旧版本目录（同一父目录并存多个版本，保留最新）。\n"
            f"删除仅移除程序文件，不触碰登录与使用数据；正在使用的文件会自动跳过。")
        if chosen is None:
            self.log("🧹 已取消清理")
            self.set_status("已取消清理")
            return
        ok = fail = 0
        for item in chosen:
            okk, msg = safe_delete_path(item["path"])
            if okk:
                ok += 1
            else:
                fail += 1
            self.log(msg)
        self.log(f"🧹 清理完成：删除 {ok} 个，失败 {fail} 个")
        self.set_status(f"清理完成：删除 {ok} 个，失败 {fail} 个")
        messagebox.showinfo(APP_NAME, f"清理完成：删除 {ok} 个，失败 {fail} 个\n"
                                     f"（失败项通常因软件正在运行，关闭后重试即可）")

    # ---------- 扫描旧版文件（只读，不删除） ----------
    def on_scan_old(self):
        if self.busy or not self.rows:
            return
        self.set_status("正在扫描旧版文件…")
        self.log("🔍 开始扫描旧版文件残留（只读，不删除）…")

        def worker():
            findings = scan_old_version_dirs(self.rows)
            self.root.after(0, lambda: self._scan_old_done(findings))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_old_done(self, findings):
        if not findings:
            self.log("🔍 未发现旧版文件残留")
            self.set_status("未发现旧版文件残留")
            messagebox.showinfo(APP_NAME, "未发现旧版本文件残留 🎉")
            return
        items = [{"desc": f"【{app}】旧版本 {ver}\n    {full}",
                  "path": full} for app, _, full, ver in findings]
        self._show_list_only(
            "扫描结果：旧版文件残留（只读）",
            items,
            f"发现 {len(findings)} 个疑似旧版本目录（同一父目录并存多个版本，保留最新）。\n"
            f"此处仅列出，不执行任何删除；如需清理请使用「🗡 杀出旧版文件」。")

    def _show_list_only(self, title, items, note):
        """只读列表弹窗（无删除操作）。"""
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
                        font=("Microsoft YaHei UI", 9), width=94)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=vsb.set)
        lb.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        for it in items:
            lb.insert("end", it["desc"])
        bf = ttk.Frame(dlg, padding=(10, 8))
        bf.pack(fill="x")
        ttk.Button(bf, text="关闭", command=dlg.destroy).pack(side="right")

    # ---------- 清除下载安装包 ----------
    def on_clean_installers(self):
        if self.busy:
            return
        self.set_status("正在扫描安装包…")
        self.log("🗑 开始扫描下载目录中的安装包…")

        def worker():
            pkgs = scan_installers()
            self.root.after(0, lambda: self._clean_inst_done(pkgs))

        threading.Thread(target=worker, daemon=True).start()

    def _clean_inst_done(self, pkgs):
        if not pkgs:
            self.log("🗑 未发现安装包")
            self.set_status("未发现安装包")
            messagebox.showinfo(APP_NAME, "下载目录中没有发现安装包 🎉")
            return
        total_mb = sum(p["size"] for p in pkgs) / 1048576
        items = [{"desc": f"{os.path.basename(p['path'])}  "
                          f"({p['size']/1048576:.1f} MB，{datetime.datetime.fromtimestamp(p['mtime']).strftime('%Y-%m-%d')})\n"
                          f"    {p['path']}",
                  "path": p["path"]} for p in pkgs]
        chosen = self._ask_delete_list(
            "清除下载的安装包",
            items,
            f"发现 {len(pkgs)} 个安装包，共 {total_mb:.1f} MB（按大小排序）。\n"
            f"删除后不可恢复；正在使用的文件会自动跳过。")
        if chosen is None:
            self.log("🗑 已取消清除")
            self.set_status("已取消清除")
            return
        ok = fail = 0
        freed = 0
        for item in chosen:
            okk, msg = safe_delete_path(item["path"])
            if okk:
                ok += 1
                try:
                    freed += os.path.getsize(item["path"]) if os.path.exists(item["path"]) else 0
                except OSError:
                    pass
            else:
                fail += 1
            self.log(msg)
        self.log(f"🗑 清除完成：删除 {ok} 个，失败 {fail} 个，释放 {freed/1048576:.1f} MB")
        self.set_status(f"清除完成：删除 {ok} 个，失败 {fail} 个")
        messagebox.showinfo(APP_NAME, f"清除完成：删除 {ok} 个，失败 {fail} 个\n"
                                     f"释放空间 {freed/1048576:.1f} MB")

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
                # 尽力验证实际安装版本；若已达标则标记“已是最新”
                real = query_installed_version(t["id"])
                if real:
                    t["version"] = real
                    if _cmp_ver(real, t["available"]) >= 0:
                        self._queue.put(("latest", t["name"]))
                self._queue.put(("done", t["name"]))
                self._queue.put(("log", f"✔ [{i}/{total}] {t['name']} 更新成功"
                                        f"（当前 {real or '?'} → 最新 {t['available']}）"))
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

        # 更新后附加处理（用户取消时跳过，避免误清理）
        if not self.cancel_all.is_set():
            if self.clean_old_opt:
                self._post_clean_old(targets)
            if self.clean_inst_opt:
                self._post_clean_installers()

        self._queue.put(("finish", stats, total))

    def _post_clean_old(self, targets):
        """更新成功后自动清理旧版本目录（worker 线程调用）。"""
        succ = [t for t in targets if t.get("upd_state") == "success"]
        if not succ:
            return
        self._queue.put(("log", "🧹 开始检查旧版本文件残留…"))
        findings = scan_old_version_dirs(succ)
        if not findings:
            self._queue.put(("log", "🧹 未发现旧版本残留，无需清理"))
            return
        ok = fail = 0
        for app, parent, full, ver in findings:
            okk, msg = safe_delete_path(full)
            if okk:
                ok += 1
            else:
                fail += 1
            self._queue.put(("log", f"🧹 {msg}"))
        self._queue.put(("log", f"🧹 旧文件清理完成：删除 {ok} 个，失败 {fail} 个"
                                f"（失败项可能因软件正在运行）"))

    def _post_clean_installers(self):
        """更新后自动清除下载目录安装包（worker 线程调用）。"""
        self._queue.put(("log", "🗑 开始扫描下载目录中的安装包…"))
        pkgs = scan_installers()
        if not pkgs:
            self._queue.put(("log", "🗑 未发现安装包"))
            return
        ok = fail = 0
        freed = 0
        for p in pkgs:
            okk, msg = safe_delete_path(p["path"])
            if okk:
                ok += 1
                freed += p["size"]
            else:
                fail += 1
            self._queue.put(("log", f"🗑 {msg}"))
        self._queue.put(("log", f"🗑 安装包清理完成：删除 {ok} 个，失败 {fail} 个，"
                                f"释放 {freed/1048576:.1f} MB"))

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
                            # 更新成功后：当前版本列显示新版本
                            self.tree.set(item, "version", row["available"])
                elif kind == "desktop_new":
                    action, name = msg[1], msg[2]
                    if messagebox.askyesno(
                        APP_NAME,
                        f"检测到桌面新增内容：{action}「{name}」\n\n"
                        f"当前已开启「桌面图标锁定」，新图标会自动对齐网格。\n"
                        f"如需自由摆放 / 整理图标，是否关闭锁定？",
                        icon="question",
                    ):
                        self.set_icon_lock(False)
                    else:
                        self.log(f"🔒 保持桌面图标锁定（新增: {name}）")
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
    latest = [r for r in rows if r["status"] == "latest"]
    print(f"\n{'='*70}")
    print(f"可更新软件 ({len(updatable)} 个):")
    for r in updatable:
        print(f"  {r['name']:<45} {r['version']} → {r['available']}")
    print(f"{'='*70}")
    print(f"已是最新（winget 报告可升但注册表版本已达标）: {len(latest)} 个")
    for r in latest:
        print(f"  {r['name']:<45} {r['version']}  ✅")
    print(f"未报告更新/无法检查: {len(rows) - len(updatable) - len(latest)} 个")
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
    if "--tray" in sys.argv:
        # 后台最小化运行（开机启动场景），桌面监控照常工作
        root.after(400, root.iconify)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
