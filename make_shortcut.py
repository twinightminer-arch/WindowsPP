#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 ctypes 直接调 COM IShellLinkW 创建桌面快捷方式（免 pywin32，显式原型）。"""
import os
import sys
import ctypes
from ctypes import (Structure, c_void_p, c_wchar_p, c_int, c_uint, c_ushort,
                    c_ulong, c_ubyte, POINTER, WINFUNCTYPE, byref)

HRESULT = c_uint  # 无符号，避免符号扩展

ole32 = ctypes.windll.ole32
shell32 = ctypes.windll.shell32


class GUID(Structure):
    _fields_ = [("Data1", c_ulong),
                ("Data2", c_ushort),
                ("Data3", c_ushort),
                ("Data4", c_ubyte * 8)]

    @classmethod
    def from_str(cls, s):
        import uuid
        u = uuid.UUID(s)
        g = cls()
        g.Data1 = u.fields[0]
        g.Data2 = u.fields[1]
        g.Data3 = u.fields[2]
        for i, b in enumerate(u.bytes[8:16]):
            g.Data4[i] = b
        return g


CLSID_ShellLink = GUID.from_str("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = GUID.from_str("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = GUID.from_str("0000010B-0000-0000-C000-000000000046")

# ---- 原型 ----
P_QueryInterface = WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))
P_Release = WINFUNCTYPE(c_ulong, c_void_p)
P_SetPath = WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p)
P_SetArguments = WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p)
P_SetWorkingDirectory = WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p)
P_SetDescription = WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p)
P_SetIconLocation = WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p, c_int)
P_Save = WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p, c_int)


def vtbl_entry(iface_ptr, index):
    """iface_ptr: c_void_p COM 接口指针 -> vtable 第 index 项函数地址"""
    vtable = ctypes.cast(iface_ptr, POINTER(c_void_p))[0]
    return ctypes.cast(vtable, POINTER(c_void_p))[index]


def create_shortcut(lnk_path, target, args, workdir, icon, desc):
    ole32.CoInitializeEx(None, 0x2)
    try:
        psl = c_void_p()
        hr = ole32.CoCreateInstance(
            byref(CLSID_ShellLink), None, 0x17,
            byref(IID_IShellLinkW), byref(psl))
        if hr != 0:
            raise OSError(f"CoCreateInstance failed: {hr:#x}")

        P_SetPath(vtbl_entry(psl, 20))(psl, target)
        P_SetArguments(vtbl_entry(psl, 11))(psl, args)
        P_SetWorkingDirectory(vtbl_entry(psl, 9))(psl, workdir)
        P_SetDescription(vtbl_entry(psl, 7))(psl, desc)
        P_SetIconLocation(vtbl_entry(psl, 17))(psl, icon, 0)

        ppf = c_void_p()
        hr = P_QueryInterface(vtbl_entry(psl, 0))(
            psl, byref(IID_IPersistFile), byref(ppf))
        if hr != 0:
            raise OSError(f"QueryInterface failed: {hr:#x}")

        # 实测（Windows 11 / Python3.10 x64）：本机 IShellLinkW 的 IPersistFile
        # 真正的 Save 位于 vtable 索引 6（索引 5 会返回 0x80070002 且不落盘）。
        # 且对 OneDrive 重定向目录直接 Save 可能异常，统一先写本地再复制。
        P_Save(vtbl_entry(ppf, 6))(ppf, lnk_path, 1)

        P_Release(vtbl_entry(ppf, 2))(ppf)
        P_Release(vtbl_entry(psl, 2))(psl)
        return True
    finally:
        ole32.CoUninitialize()


if __name__ == "__main__":
    # 用系统 API 拿桌面路径（兼容 OneDrive 重定向）
    buf = ctypes.create_unicode_buffer(260)
    shell32.SHGetFolderPathW(None, 0, None, 0, buf)  # CSIDL_DESKTOP = 0
    desktop = buf.value or os.path.join(os.path.expanduser("~"), "Desktop")

    dir_ = os.path.dirname(os.path.abspath(__file__))
    import shutil
    tmp_lnk = os.path.join(os.path.expanduser("~"), "Desktop", "_wpp_tmp.lnk")
    if os.path.exists(tmp_lnk):
        os.remove(tmp_lnk)

    # 自动探测 pythonw.exe（与当前解释器同目录；找不到则回退 python.exe）
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = shutil.which("pythonw") or sys.executable

    create_shortcut(
        lnk_path=tmp_lnk,
        target=pythonw,
        args=f'"{os.path.join(dir_, "WindowsPP.py")}"',
        workdir=dir_,
        icon=os.path.join(dir_, "WindowsPP.ico"),
        desc="Windows++ Software Updater",
    )
    if not os.path.exists(tmp_lnk):
        print("FAILED: 临时 lnk 未生成")
        sys.exit(1)

    lnk = os.path.join(desktop, "Windows++.lnk")
    shutil.copy2(tmp_lnk, lnk)
    os.remove(tmp_lnk)
    print(f"OK: {lnk} ({os.path.getsize(lnk)} bytes)")
