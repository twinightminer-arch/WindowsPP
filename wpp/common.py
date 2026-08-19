#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.common — Windows++ 公共工具库（标准库实现）。

命令执行 / 注册表枚举 / winget / 版本比较 / 旧文件与安装包扫描 /
配置持久化 / 桌面图标锁定 / 桌面目录监控。
"""

import os
import re
import sys
import time
import ctypes
import shutil
import subprocess
import threading

# ============================================================
# 常量
# ============================================================
APP_NAME = "Windows++"
VERSION = "4.0"

UPDATE_TIMEOUT = 1800                       # 单软件更新超时（秒）
INSTALLER_EXTS = {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle"}
_VER_IN_DIR_RE = re.compile(r"\d+(?:\.\d+){1,3}")

SETTINGS_KEY = r"Software\WindowsPP"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "WindowsPP"
FFLAGS_AUTO_ARRANGE = 0x40000000           # 桌面图标自动排列位

# 预设主题色（Windows 10/11 个性化色板）
THEME_COLORS = [
    ("Windows 蓝", "#0078D4"), ("深青", "#00B7C3"), ("活力紫", "#8764B8"),
    ("玫红", "#E3008C"), ("中国红", "#E81123"), ("炽橙", "#CA5010"),
    ("金黄", "#C19C00"), ("荧光绿", "#7FBA00"), ("松绿", "#00B294"),
    ("灰蓝", "#647687"), ("炭黑", "#393939"), ("活力粉", "#F7630C"),
]

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
# 命令执行
# ============================================================
def _startupinfo():
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def run_cmd(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore",
                           timeout=timeout, shell=True, startupinfo=_startupinfo())
        return r.stdout or "", r.stderr or "", r.returncode
    except subprocess.TimeoutExpired:
        return "", "命令超时", -1
    except Exception as e:
        return "", str(e), -1


def has_winget():
    return run_cmd("winget --version", timeout=30)[2] == 0


# ============================================================
# 注册表：已安装软件枚举
# ============================================================
def get_installed_from_registry():
    """枚举所有已安装软件。
    返回 list[dict]: name/version/publisher/install_loc/uninstall/size_mb/inst_date"""
    try:
        import winreg
    except ImportError:
        return []
    results = {}
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    def _g(key, name):
        try:
            v, _ = winreg.QueryValueEx(key, name)
            return str(v) if v is not None else ""
        except OSError:
            return ""

    def _size_mb(key):
        try:
            kb = int(winreg.QueryValueEx(key, "EstimatedSize")[0])
            return round(kb / 1024.0, 1) if kb > 0 else 0.0
        except (OSError, ValueError, TypeError):
            return 0.0

    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(key)[0]):
            try:
                sub = winreg.OpenKey(key, winreg.EnumKey(key, i))
            except OSError:
                continue
            name = _g(sub, "DisplayName")
            if not name:
                continue
            if _g(sub, "SystemComponent") == "1":
                continue
            if _g(sub, "ReleaseType") in ("Security Update", "Update Rollup",
                                          "Hotfix", "Service Pack"):
                continue
            entry = {
                "name": name.strip(),
                "version": _g(sub, "DisplayVersion").strip(),
                "publisher": _g(sub, "Publisher").strip(),
                "install_loc": _g(sub, "InstallLocation").strip(),
                "uninstall": _g(sub, "UninstallString").strip(),
                "size_mb": _size_mb(sub),
                "inst_date": _g(sub, "InstallDate").strip(),
            }
            k = name.lower()
            if k not in results:
                results[k] = entry
    return list(results.values())


# ============================================================
# winget
# ============================================================
_WINGET_ROW_RE = re.compile(r"^(.+?)\s{2,}(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")


def get_winget_upgrades():
    """解析 `winget upgrade` 输出，返回可更新软件列表。"""
    out, err, rc = run_cmd(
        "winget upgrade --accept-source-agreements --disable-interactivity", timeout=300)
    if rc != 0:
        return [], err or "winget upgrade 执行失败"
    upgrades, started = [], False
    for line in out.splitlines():
        s = line.rstrip()
        if not started:
            if ("名称" in s or "Name" in s) and ("ID" in s or "Id" in s):
                started = True
            continue
        if not s.strip() or set(s.strip()) <= set("-─ "):
            continue
        if "升级" in s or "upgrade" in s.lower():
            continue
        m = _WINGET_ROW_RE.match(s)
        if not m:
            continue
        name, pid, ver, avail, src = [x.strip() for x in m.groups()]
        upgrades.append({"name": name, "id": pid, "version": ver,
                         "available": avail, "source": src})
    return upgrades, None


def query_installed_version(pkg_id):
    """winget list 查询实际安装版本（尽力而为）。"""
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
# 版本比较
# ============================================================
def _norm(s):
    return re.sub(r"[\s\u00a0]+", "", s).lower()


def _ver_parts(s):
    s = str(s or "").strip().lower()
    out = []
    for p in re.findall(r"\d+|[a-z]+", s):
        if p.isdigit():
            out.append((1, int(p)))
        else:
            out.append((0, p))
    return out


def _cmp_ver(a, b):
    """a>b 返回 1，a<b 返回 -1，相等/无法区分 0。尾零等价：9.9.33==9.9.33.0。"""
    pa, pb = _ver_parts(a), _ver_parts(b)
    for x, y in zip(pa, pb):
        if x != y:
            return (x > y) - (x < y)
    if len(pa) == len(pb):
        return 0
    longer, shorter = (pa, pb) if len(pa) > len(pb) else (pb, pa)
    if all(x[0] == 1 and x[1] == 0 for x in longer[len(shorter):]):
        return 0
    return (len(pa) > len(pb)) - (len(pa) < len(pb))


# ============================================================
# 合并状态（软件更新页用）
# ============================================================
def merge_status(installed, upgrades):
    """installed 全量行 + winget-only 行；含注册表版本交叉校验（已是最新）。"""
    up_by_norm = {}
    for u in upgrades:
        up_by_norm.setdefault(_norm(u["name"]), []).append(u)
    rows, used = [], set()

    def _best_fuzzy(key):
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
        matched = up_by_norm.get(key) or (up_by_norm.get(_best_fuzzy(key)) if _best_fuzzy(key) else None)
        matched = matched[0] if matched else None
        if matched:
            used.add(_norm(matched["name"]))
            status = "updatable"
            if app["version"] and _cmp_ver(app["version"], matched["available"]) >= 0:
                status = "latest"   # 注册表版本已达标 -> winget 误报纠正
            rows.append({
                "name": app["name"], "version": app["version"] or matched["version"],
                "available": matched["available"], "source": matched["source"],
                "id": matched["id"], "publisher": app["publisher"],
                "install_loc": app["install_loc"], "uninstall": app["uninstall"],
                "status": status, "upd_state": "pending",
            })
        else:
            rows.append({
                "name": app["name"], "version": app["version"], "available": "",
                "source": "", "id": "", "publisher": app["publisher"],
                "install_loc": app["install_loc"], "uninstall": app["uninstall"],
                "status": "unknown", "upd_state": "pending",
            })
    for u in upgrades:
        if _norm(u["name"]) in used:
            continue
        rows.append({
            "name": u["name"], "version": u["version"], "available": u["available"],
            "source": u["source"], "id": u["id"], "publisher": "",
            "install_loc": "", "uninstall": "", "status": "updatable", "upd_state": "pending",
        })
    order = {"updatable": 0, "latest": 1, "unknown": 2}
    rows.sort(key=lambda r: (order.get(r["status"], 9), _norm(r["name"])))
    return rows


# ============================================================
# 磁盘清理：旧版本文件 / 安装包
# ============================================================
def scan_old_version_dirs(rows):
    """找出“同一父目录下并存多版本”中的旧版本目录。
    返回 [(app_name, parent, old_dir, version), ...]。只读。"""
    def _effective_loc(r):
        loc = (r.get("install_loc") or "").strip()
        if not loc:
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

    row_locs = []
    for r in rows:
        loc = _effective_loc(r)
        if loc:
            row_locs.append((loc, r["name"]))

    extra_sub = ("versions", "resources", "resources/app",
                 "resources/app/versions", "app/versions", "bin")
    parents = {}
    for loc, _ in row_locs:
        bases = [loc] + [os.path.join(loc, e) for e in extra_sub if os.path.isdir(os.path.join(loc, e))]
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
                if any(t in el for t in ("userdata", "documents", "appdata",
                                         "cache", "temp", "log", "config", "data")):
                    continue
                m = _VER_IN_DIR_RE.search(e)
                if m and not any(x[0] == full for x in parents.get(bl, [])):
                    parents.setdefault(bl, []).append((full, m.group(0), e))

    findings = []
    for base, items in parents.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda x: _ver_parts(x[1]), reverse=True)
        for full, ver, name in items[1:]:
            app = "未知软件"
            for loc, aname in row_locs:
                if loc == base or any(os.path.normcase(os.path.join(loc, x)) == base for x in extra_sub):
                    app = aname
                    break
            findings.append((app, base, full, ver))
    findings.sort(key=lambda x: (x[0].lower(), x[2].lower()))
    return findings


def scan_installers():
    """扫描常见下载/临时目录中的安装包，返回 [{path,size,mtime}]，按大小降序。"""
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    dirs = [os.path.join(home, "Downloads"), os.path.join(home, "Desktop"),
            os.environ.get("TEMP", ""), os.path.join(local, "Temp"),
            os.path.join(local, "Packages",
                         "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe", "LocalState")]
    out, seen = [], set()
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for e in entries:
            full = os.path.join(d, e)
            if not os.path.isfile(full) or os.path.splitext(e)[1].lower() not in INSTALLER_EXTS:
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
    """删除文件或目录。返回 (ok, msg)。占用/无权限自动跳过。"""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True, f"已删除: {path}"
    except Exception as e:
        return False, f"删除失败: {path}（{e}；可能正被占用，请关闭相关软件后重试）"


# ============================================================
# 配置持久化（HKCU\Software\WindowsPP）
# ============================================================
def load_settings():
    d = {"icon_lock": False, "autostart": False, "theme": "",
         "bg_image": "", "bg_video": "", "bg_opacity": 35, "bg_mute": False,
         "bg_music": "", "pet_path": "", "pet_autostart": False,
         "pet_selected": "", "pets": [],
         "rec_dir": "", "rec_hotkey": "ctrl+h", "rec_region": "",
         "desk_locked_icons": []}
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
        pairs = [("IconLock", "icon_lock", bool), ("AutoStart", "autostart", bool),
                 ("Theme", "theme", str), ("BgImage", "bg_image", str),
                 ("BgVideo", "bg_video", str), ("BgOpacity", "bg_opacity", int),
                 ("BgMute", "bg_mute", bool), ("BgMusic", "bg_music", str),
                 ("PetPath", "pet_path", str), ("PetAutoStart", "pet_autostart", bool),
                 ("PetSelected", "pet_selected", str),
                 ("RecDir", "rec_dir", str), ("RecHotkey", "rec_hotkey", str),
                 ("RecRegion", "rec_region", str)]
        for reg, name, conv in pairs:
            try:
                v = winreg.QueryValueEx(key, reg)[0]
                if conv is bool:
                    d[name] = bool(v)
                elif conv is int:
                    d[name] = int(v)
                else:
                    d[name] = str(v)
            except OSError:
                pass
        for reg, name in (("DeskLockIcons", "desk_locked_icons"),
                          ("Pets", "pets")):
            try:
                v, t = winreg.QueryValueEx(key, reg)
                if t == winreg.REG_MULTI_SZ:
                    d[name] = [x for x in v if x]
            except OSError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass
    return d


def save_settings(**kw):
    """写入设置并同步开机启动项。kw 键名同 load_settings 返回的 dict。"""
    import winreg
    cur = load_settings()
    cur.update({k: v for k, v in kw.items() if k in cur})
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
        regs = [("IconLock", "icon_lock"), ("AutoStart", "autostart"), ("Theme", "theme"),
                ("BgImage", "bg_image"), ("BgVideo", "bg_video"), ("BgOpacity", "bg_opacity"),
                ("BgMute", "bg_mute"), ("BgMusic", "bg_music"), ("PetPath", "pet_path"),
                ("PetAutoStart", "pet_autostart"), ("PetSelected", "pet_selected"),
                ("RecDir", "rec_dir"), ("RecHotkey", "rec_hotkey"), ("RecRegion", "rec_region")]
        for reg, name in regs:
            v = cur[name]
            if isinstance(v, bool):
                winreg.SetValueEx(key, reg, 0, winreg.REG_DWORD, int(v))
            elif isinstance(v, int):
                winreg.SetValueEx(key, reg, 0, winreg.REG_DWORD, v)
            else:
                winreg.SetValueEx(key, reg, 0, winreg.REG_SZ, str(v))
        locked = [x for x in cur.get("desk_locked_icons") or [] if x]
        winreg.SetValueEx(key, "DeskLockIcons", 0, winreg.REG_MULTI_SZ, locked)
        pets = [x for x in cur.get("pets") or [] if x]
        winreg.SetValueEx(key, "Pets", 0, winreg.REG_MULTI_SZ, pets)
        if cur.get("pet_selected"):
            winreg.SetValueEx(key, "PetSelected", 0, winreg.REG_SZ, str(cur["pet_selected"]))
        winreg.CloseKey(key)
    except OSError:
        pass
    _sync_autostart(cur["autostart"], RUN_VALUE, script=os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "WindowsPP.py")))
    return cur


def _sync_autostart(enabled, value_name, script=None, extra_args="", raw_cmd=None):
    """写/删 HKCU Run 项。raw_cmd 直接作为启动命令；否则 pythonw + script + args。"""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_READ | winreg.KEY_WRITE)
        if enabled:
            if raw_cmd:
                cmd = raw_cmd
            elif getattr(sys, "frozen", False):
                # 已打包为 exe：直接以 exe 自身为启动命令
                cmd = f'"{sys.executable}" {extra_args}'.strip()
            else:
                py = sys.executable
                pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
                if not os.path.isfile(pyw):
                    pyw = py
                if script is None:
                    script = os.path.abspath(__file__)
                cmd = f'"{pyw}" "{script}" {extra_args}'.strip()
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, value_name)
            except OSError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass


def get_autostart_cmd(value_name=RUN_VALUE):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        val, _ = winreg.QueryValueEx(key, value_name)
        winreg.CloseKey(key)
        return val
    except OSError:
        return None


# ============================================================
# 桌面图标锁定（FFlags 自动排列）
# ============================================================
def set_desktop_icon_lock(enabled):
    """启用/关闭桌面图标“自动排列”。返回 (ok, msg)。"""
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
        new = (fflags | FFLAGS_AUTO_ARRANGE) if enabled else (fflags & ~FFLAGS_AUTO_ARRANGE)
        winreg.SetValueEx(key, "FFlags", 0, winreg.REG_DWORD, new)
        winreg.CloseKey(key)
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        except Exception:
            pass
        return True, ("已启用桌面图标锁定" if enabled else "已关闭桌面图标锁定")
    except OSError as e:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
        return False, f"写入失败: {e}"


# ============================================================
# 桌面目录监控（ReadDirectoryChangesW）
# ============================================================
def desktop_path():
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf)
        return buf.value
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def list_desktop_icons():
    """列出桌面上的图标条目（快捷方式/文件/文件夹），只读。
    返回 [(name, is_dir, path), ...]，按名称排序。"""
    d = desktop_path()
    if not os.path.isdir(d):
        return []
    out = []
    try:
        for e in sorted(os.listdir(d)):
            full = os.path.join(d, e)
            if e.startswith("."):
                continue
            out.append((e, os.path.isdir(full), full))
    except OSError:
        pass
    return out


class DesktopMonitor(threading.Thread):
    """监控桌面目录变化；经回调上报 (action_text, filename)。只读。"""
    ACTION_ADDED, ACTION_RENAMED_NEW = 1, 5

    def __init__(self, path, on_event):
        super().__init__(daemon=True)
        self.path = path
        self.on_event = on_event
        self._stop_evt = threading.Event()
        self._h = None

    def stop(self):
        self._stop_evt.set()
        if self._h:
            try:
                import ctypes
                ctypes.windll.kernel32.CancelIoEx(self._h, None)
            except Exception:
                pass

    def run(self):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        try:
            k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            k32.CreateFileW.restype = wintypes.HANDLE
            k32.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                                  wintypes.BOOL, wintypes.DWORD, wintypes.LPDWORD,
                                                  wintypes.LPVOID, wintypes.LPVOID]
            k32.ReadDirectoryChangesW.restype = wintypes.BOOL
        except Exception:
            return
        self._h = k32.CreateFileW(self.path, 0x0001, 0x1 | 0x2 | 0x4, None, 3,
                                  0x02000000, None)  # FILE_LIST_DIRECTORY, share R|W|D, OPEN_EXISTING, BACKUP_SEMANTICS
        if not self._h or self._h == wintypes.HANDLE(-1).value:
            return
        buf = ctypes.create_string_buffer(64 * 1024)
        try:
            while not self._stop_evt.is_set():
                n = wintypes.DWORD(0)
                ok = k32.ReadDirectoryChangesW(self._h, buf, len(buf), True,
                                               0x1 | 0x2 | 0x100, ctypes.byref(n), None, None)
                if not ok:
                    break
                self._parse(buf, n.value)
        finally:
            try:
                k32.CancelIoEx(self._h, None)
            except Exception:
                pass
            k32.CloseHandle(self._h)

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


# ============================================================
# 桌面图标拖拽拦截（WH_MOUSE_LL 低级鼠标钩子，真正阻止移动）
# ============================================================
class _DP_POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class DesktopDragGuard:
    """桌面图标锁定引擎。

    原理：安装低级鼠标钩子（WH_MOUSE_LL）。锁定模式下，对桌面图标区域
    （SysListView32）的“单击按下”事件直接吞掉 —— 图标无法被选中、无法被
    拖动，从根本上阻止移动；“双击”会被识别并放行（双击仍可正常打开软件）。
    无需读取图标名（桌面列表为 owner-draw 虚拟列表，跨进程取文本不可行）。
    """

    _WH_MOUSE_LL = 14
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONDBLCLK = 0x0203

    class _MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("pt", _DP_POINT), ("mouseData", ctypes.c_ulong),
                    ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.c_void_p)]

    def __init__(self):
        self._hook = None
        self._thread = None
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._cb = None
        self._thread_id = None
        self.enabled = False          # 锁定模式开关（由页面/主框架控制）
        self._last_down = 0.0         # 上次按下时间（time.monotonic）
        self._last_pt = None          # 上次按下坐标
        self._grace_until = 0.0       # 双击放行截止时间

    def set_enabled(self, flag):
        self.enabled = bool(flag)
        return self

    def start(self):
        if self._thread is not None:
            return True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        t = self._thread
        self._thread = None
        if t is not None and self._thread_id:
            try:
                self._user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass

    # ---------- 钩子线程 ----------
    def _run(self):
        from ctypes import wintypes
        u = self._user32
        self._thread_id = self._kernel32.GetCurrentThreadId()
        CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                                     ctypes.c_void_p, ctypes.c_void_p)
        self._cb = CMPFUNC(self._proc)
        # 低级钩子（WH_MOUSE_LL）：回调位于当前进程内时 hMod 传 NULL 即可
        self._hook = u.SetWindowsHookExW(self._WH_MOUSE_LL, self._cb, None, 0)
        if not self._hook:
            self._hook = None
            return
        msg = wintypes.MSG()
        try:
            while u.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        finally:
            try:
                u.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = None

    # ---------- 回调 ----------
    def _proc(self, n_code, w_param, l_param):
        u = self._user32
        try:
            if n_code >= 0 and self.enabled:
                now = time.monotonic()
                if w_param == self.WM_LBUTTONDOWN:
                    if now < self._grace_until:
                        return self._next(n_code, w_param, l_param)   # 双击放行期
                    info = ctypes.cast(l_param,
                                       ctypes.POINTER(self._MSLLHOOKSTRUCT)).contents
                    # 双击意图：第二次快速按下（同位置）→ 放行并进入双击放行期
                    if (self._last_down and now - self._last_down < 0.6
                            and self._last_pt is not None
                            and abs(info.pt.x - self._last_pt.x) < 6
                            and abs(info.pt.y - self._last_pt.y) < 6):
                        self._grace_until = now + 0.7
                        self._last_down = 0.0
                        return self._next(n_code, w_param, l_param)
                    self._last_down = now
                    self._last_pt = (info.pt.x, info.pt.y)
                    if self._on_desktop_icon(info.pt):
                        return 1      # 吞掉单击：不可选中/不可拖动
                elif w_param == self.WM_LBUTTONDBLCLK:
                    return self._next(n_code, w_param, l_param)
        except Exception:
            pass
        return self._next(n_code, w_param, l_param)

    def _next(self, n_code, w_param, l_param):
        try:
            return self._user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        except Exception:
            return 0

    # ---------- 命中检测（只锁桌面图标，不误锁其他窗口；仅本地只读 API） ----------
    def _on_desktop_icon(self, pt):
        """判断鼠标按下位置是否位于“桌面图标”之上。

        用 WindowFromPoint 取鼠标下最顶层的窗口，仅当它是桌面窗口
        （Progman 及其子窗口 SHELLDLL_DefView/SysListView32、壁纸层 WorkerW）
        时才拦截 —— 软件窗口 / 截图工具等覆盖在桌面上时不会误锁。
        全部使用只读 API，不发送任何跨进程消息（避免资源管理器死锁）。"""
        try:
            u = self._user32
            u.WindowFromPoint.argtypes = [ctypes.POINTER(_DP_POINT)]
            u.WindowFromPoint.restype = ctypes.c_void_p
            hwnd = u.WindowFromPoint(ctypes.byref(pt))
            if not hwnd:
                # WindowFromPoint 不可用时（异常会话）保守放行，避免误锁
                return False
            # 沿父链取根窗口：根 == Progman（桌面宿主）则命中
            u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            u.GetAncestor.restype = ctypes.c_void_p
            u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            u.FindWindowW.restype = ctypes.c_void_p
            root = u.GetAncestor(hwnd, 2)  # GA_ROOT
            prog = u.FindWindowW("Progman", None)
            if root == prog:
                return True
            # 类名兜底（部分系统点击空白处返回 WorkerW 等）
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
            u.GetClassNameW(hwnd, cls, 64)
            return cls.value in ("Progman", "WorkerW", "SHELLDLL_DefView", "SysListView32")
        except Exception:
            return False


# ============================================================
# 内置迷你工具（时钟 / 日历 / CPU 仪表盘）的独立运行入口
# ============================================================
def run_builtin_tool(tool_name):
    """在独立进程中运行内置小工具（供自启动调用）。tool_name: clock/calendar/cpu"""
    import tkinter as tk
    from wpp.tools import make_tool_window
    root = tk.Tk()
    root.withdraw()
    w = make_tool_window(root, tool_name)
    if w is None:
        return
    root.deiconify()
    root.mainloop()
