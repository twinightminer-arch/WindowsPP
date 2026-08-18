#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Windows++ 使用说明 Word 文档，并打包 zip 到桌面。"""
import os
import zipfile
import datetime

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

BASE = os.path.dirname(os.path.abspath(__file__))

# 桌面路径（兼容 OneDrive 重定向），用系统 API 获取
import ctypes
_buf = ctypes.create_unicode_buffer(260)
ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, _buf)  # CSIDL_DESKTOP = 0
DESKTOP = _buf.value or os.path.join(os.path.expanduser("~"), "Desktop")

MS_BLUE = RGBColor(0x00, 0xA4, 0xEF)
HEADER = RGBColor(0x1F, 0x29, 0x37)
CODE_BG = RGBColor(0x33, 0x33, 0x33)


def h(doc, text, size=14, color=HEADER, space_before=10):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(size)
    r.font.color.rgb = color
    return p


def para(doc, text, size=10.5, bold=False, space_after=4, indent=0):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if indent:
        p.paragraph_format.left_indent = Cm(indent)
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    r.font.size = Pt(size)
    return p


def code_block(doc, text, size=9.5):
    for line in text.strip("\n").split("\n"):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(line)
        r.font.name = "Consolas"
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(0x0B, 0x53, 0x4F)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def build_docx(path):
    doc = Document()

    # 标题
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("Windows++ 使用说明")
    r.bold = True
    r.font.size = Pt(22)
    r.font.color.rgb = HEADER

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("软件版本检查 & 一键更新工具   |   更新日期：2026-08-19")
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    # 一、简介
    h(doc, "一、软件简介")
    para(doc, "Windows++ 是一款 Windows 桌面小工具，用于：")
    bullet(doc, "一键识别电脑上安装的所有软件（通过注册表枚举）；")
    bullet(doc, "借助 winget（Windows 包管理器）比对最新版本，标出可更新项；")
    bullet(doc, "一键批量自动更新，支持暂停 / 跳过 / 取消等细粒度控制；")
    bullet(doc, "旧版文件残留扫描 / 杀出（保留登录与使用数据）、清除下载安装包；")
    bullet(doc, "设置界面：桌面图标锁定（新增文件提示）、开机启动开关；")
    bullet(doc, "导出文本报告，便于留档或离线查看。")

    # 二、环境要求
    h(doc, "二、环境要求（配置环境）")
    bullet(doc, "操作系统：Windows 10（1809 及以上）或 Windows 11；")
    bullet(doc, "winget（Windows 包管理器）：Windows 11 与新版 Win10 通常自带。"
                "若缺失，可在微软商店搜索安装「应用安装程序 App Installer」，或访问 https://aka.ms/getwinget ；")
    bullet(doc, "Python 3.7+（必须包含 tkinter，标准安装默认包含）。"
                "下载地址：https://www.python.org/downloads/windows/ ，"
                "安装时勾选「Add Python to PATH」。")
    para(doc, "提示：本工具为绿色单文件，无需安装任何第三方 Python 库。", bold=True)

    # 三、文件说明
    h(doc, "三、文件说明")
    files = [
        ("WindowsPP.py", "主程序（图形界面 + 命令行），核心文件"),
        ("WindowsPP.ico", "程序图标（微软四色格子）"),
        ("启动WindowsPP.bat", "双击启动脚本（自动探测 py/python 解释器）"),
        ("make_icon.py", "图标生成脚本（一般无需使用）"),
        ("make_shortcut.py", "桌面快捷方式创建脚本（一般无需使用）"),
        ("Windows++ 使用说明.docx", "本文档"),
    ]
    for name, desc in files:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(f"· {name}")
        r.bold = True
        r.font.size = Pt(10.5)
        r2 = p.add_run(f"　—　{desc}")
        r2.font.size = Pt(10.5)

    # 四、启动方式
    h(doc, "四、启动方式")
    bullet(doc, "方式一（推荐）：双击桌面上的「Windows++」快捷方式（带微软四色图标），或双击「启动WindowsPP.bat」。", size=10.5)
    bullet(doc, "方式二（命令行，只读扫描）：", size=10.5)
    code_block(doc, "python WindowsPP.py --scan\n"
                    "# 仅列出全部已装软件与可更新项，不执行更新")
    bullet(doc, "方式三（命令行，打开图形界面）：", size=10.5)
    code_block(doc, "python WindowsPP.py")

    # 五、使用方法
    h(doc, "五、使用方法（图形界面）")
    para(doc, "1. 点击「🔄 扫描并检查更新」：列出全部已装软件，可更新项默认勾选（✔）并标为「可更新」；", size=10.5)
    para(doc, "2. 调整勾选：点击行首 ✔ 列可勾选/取消；选中某行后点右键，可在菜单中「取消勾选（不更新）」或「重新勾选」；", size=10.5)
    para(doc, "3. 点击「⬆ 开始更新（选中项）」：弹出确认清单，确认后逐个通过 winget 自动升级；", size=10.5)
    para(doc, "4. 更新过程中可随时控制（见下方功能表），状态列实时显示每个软件的结果；", size=10.5)
    para(doc, "5. 点击「📄 导出报告」可将结果保存为 txt。", size=10.5)

    # 六、设置与高级功能（v2.0）
    h(doc, "六、设置与高级功能（v2.0）")
    para(doc, "点击主界面「⚙ 设置」按钮打开设置界面，包含以下功能：", size=10.5)
    rows2 = [
        ("🔍 扫描旧版文件（只读）", "列出“同目录并存多版本”的旧版残留，不执行任何删除"),
        ("🗡 杀出旧版文件", "扫描后弹出勾选清单，确认后删除旧程序目录（保留登录与使用数据）"),
        ("🔒 桌面图标锁定", "开启后桌面图标自动对齐网格、禁止拖乱；桌面新增文件/文件夹时弹窗提示，可临时关闭锁定整理桌面"),
        ("🚀 开机启动", "勾选后写入注册表「启动」项，开机自动后台最小化运行（监控桌面）；取消勾选即移除"),
    ]
    table2 = doc.add_table(rows=len(rows2), cols=2)
    table2.style = "Light Grid Accent 1"
    for i, (a, b) in enumerate(rows2):
        c0 = table2.cell(i, 0)
        c0.text = ""
        r = c0.paragraphs[0].add_run(a)
        r.bold = True
        r.font.size = Pt(10)
        c1 = table2.cell(i, 1)
        c1.text = ""
        r = c1.paragraphs[0].add_run(b)
        r.font.size = Pt(10)
    para(doc, "主界面第二行按钮：「⏸ 暂停更新 / ⏭ 跳过当前 / ✖ 取消当前 / ⏹ 取消全部」"
              "及「🧹 清理旧版本文件 / 🔍 扫描旧版文件」，供快速操作。", size=10.5)
    para(doc, "命令行附加用法：", size=10.5)
    code_block(doc, "python WindowsPP.py --tray   # 后台最小化运行（开机启动场景）")

    # 七、功能表
    h(doc, "七、更新控制与状态说明")
    rows = [
        ("⏸ 暂停更新 / ▶ 继续更新", "暂停队列：等待中的软件不再启动，正在运行的会跑完"),
        ("⏭ 跳过当前", "终止正在更新的软件（标记「已跳过」）；无运行中则跳过下一个"),
        ("✖ 取消当前", "只终止当前正在更新的软件（标记「已取消」）"),
        ("⏹ 取消全部", "终止剩余全部更新（含正在运行的），需确认"),
        ("状态：等待/进行中", "灰色/蓝色：排队中 / 正在执行"),
        ("状态：成功/失败", "绿色/红色：更新成功 / winget 返回错误"),
        ("状态：超时", "橙色：单个软件超过 30 分钟未完成，自动终止"),
        ("状态：已跳过/已取消", "灰色：用户操作导致未完成"),
    ]
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Light Grid Accent 1"
    for i, (a, b) in enumerate(rows):
        c0 = table.cell(i, 0)
        c0.text = ""
        r = c0.paragraphs[0].add_run(a)
        r.bold = True
        r.font.size = Pt(10)
        c1 = table.cell(i, 1)
        c1.text = ""
        r = c1.paragraphs[0].add_run(b)
        r.font.size = Pt(10)

    # 八、常见问题
    h(doc, "八、常见问题（FAQ）")
    faqs = [
        ("启动时提示找不到 winget？",
         "请在微软商店安装「应用安装程序」（App Installer），装完重开程序。"),
        ("更新失败怎么办？",
         "看下方日志中的错误尾巴。常见原因：软件正在运行（请先关闭）、需要管理员权限、网络问题。"
         "可在日志里找到对应软件的 ID，稍后手动执行：winget upgrade --id <ID> -e"),
        ("更新超时了？",
         "个别大软件（如 Visual Studio）下载慢。可先用「⏭ 跳过当前」，稍后单独更新；"
         "或提高 WindowsPP.py 中 UPDATE_TIMEOUT 常量（默认 1800 秒）。"),
        ("部分软件状态是「—」（灰色）？",
         "说明 winget 未收录该软件的更新信息，无法自动判定/升级，属正常现象，并非所有软件都有自动更新渠道。"),
        ("更新需要重启电脑吗？",
         "部分系统组件更新后要求重启，提示时重启即可，不影响其它软件。"),
    ]
    for q, a in faqs:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        r = p.add_run("Q: " + q)
        r.bold = True
        r.font.size = Pt(10.5)
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run("A: " + a)
        r.font.size = Pt(10.5)

    # 九、安全说明
    h(doc, "九、安全与免责说明")
    bullet(doc, "更新前会弹出清单确认，绝不静默安装；")
    bullet(doc, "所有更新均调用系统自带的 winget 完成，安装包来自 winget 官方源（winget / msstore）；")
    bullet(doc, "「跳过 / 取消」会强制结束 winget 进程树，极少数情况可能留下不完整安装，重试一次即可；")
    bullet(doc, "本工具仅做版本检查与升级，不包含卸载功能，请勿用于误操作。")

    doc.save(path)
    return path


def make_zip(zip_path, extra_docx):
    files = [
        "WindowsPP.py",
        "WindowsPP.ico",
        "启动WindowsPP.bat",
        "make_icon.py",
        "make_shortcut.py",
    ]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files + [os.path.basename(extra_docx)]:
            z.write(os.path.join(BASE, f), arcname=f)
    return zip_path


def main():
    docx_path = os.path.join(BASE, "Windows++ 使用说明.docx")
    build_docx(docx_path)
    print(f"DOCX OK: {docx_path} ({os.path.getsize(docx_path)} bytes)")

    zip_path = os.path.join(BASE, "Windows++_v2.0.zip")
    make_zip(zip_path, docx_path)
    print(f"ZIP OK: {zip_path} ({os.path.getsize(zip_path)} bytes)")

    # 复制到桌面
    dst_docx = os.path.join(DESKTOP, os.path.basename(docx_path))
    dst_zip = os.path.join(DESKTOP, os.path.basename(zip_path))
    import shutil
    shutil.copy2(docx_path, dst_docx)
    shutil.copy2(zip_path, dst_zip)
    print(f"DESKTOP DOCX: {dst_docx} -> exists={os.path.exists(dst_docx)}")
    print(f"DESKTOP ZIP : {dst_zip} -> exists={os.path.exists(dst_zip)}")

    # 展示 zip 内容清单
    with zipfile.ZipFile(zip_path) as z:
        print("\nZIP CONTENTS:")
        for info in z.infolist():
            print(f"  {info.filename}  ({info.file_size} bytes)")


if __name__ == "__main__":
    main()
