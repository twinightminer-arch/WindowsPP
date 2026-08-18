# Windows++ 🪟

> 一键识别电脑上所有已装软件是否为最新版本，并批量自动更新。

Windows++ 是一款 Windows 桌面小工具：扫描注册表枚举全部已装软件，借助系统自带的 **winget**（Windows 包管理器）比对最新版本，标出可更新项，然后**一键批量更新**——支持暂停、跳过、取消等细粒度控制，全程可视化状态反馈。

![Windows](https://img.shields.io/badge/Windows-10%2F11-00A4EF?style=flat-square&logo=windows)
![Python](https://img.shields.io/badge/Python-3.7%2B-3776AB?style=flat-square&logo=python)
![License](https://img.shields.io/badge/License-MIT-7FBA00?style=flat-square)
![winget](https://img.shields.io/badge/deps-winget%20%2B%20tkinter-FFB900?style=flat-square)

## ✨ 特性

- 🔄 **一键扫描**：注册表枚举全部已装软件 + winget 比对，可更新项一目了然
- ✅ **版本交叉校验**：更新后不再误报「可更新」——注册表版本已达标即显示绿色「已是最新」
- ⬆ **批量更新**：逐包调用 winget 自动升级，失败不中断队列
- ⏸ **暂停 / ▶ 继续**：随时暂停队列，等待中的软件不再启动
- ⏭ **跳过当前 / ✖ 取消当前**：细粒度控制，终止正在进行的更新
- ⏹ **取消全部**：一键终止剩余所有更新（含运行中的）
- 📊 **实时状态**：等待 / 进行中 / 成功 / 超时 / 失败 / 已跳过 / 已取消，颜色区分
- 🖱 **右键菜单**：对已勾选的软件右键取消勾选，灵活选择
- 🔍 **扫描旧版文件 / 🗡 杀出旧版文件**：检测「同目录并存多版本」的旧版残留并清理（仅删旧程序目录，保留登录与使用数据）
- 🗑 **清除下载安装包**：扫描下载/临时目录中的 .exe/.msi 等安装包，勾选删除释放空间
- 🔒 **桌面图标锁定**：设置界面开关，开启后图标自动对齐网格；桌面新增文件/文件夹时弹窗提示可临时关闭锁定
- 🚀 **开机启动**：设置界面开关，勾选后开机自动后台最小化运行（`--tray` 监控桌面）
- 📄 **导出报告**：一键保存 txt 版本清单

## 📦 环境要求

| 依赖 | 说明 |
|---|---|
| Windows 10 (1809+) / Windows 11 | 必需 |
| winget（Windows 包管理器） | Win11 与新版 Win10 通常自带；缺失时在微软商店安装「应用安装程序 App Installer」或访问 https://aka.ms/getwinget |
| Python 3.7+（含 tkinter） | 标准安装默认包含；下载 https://www.python.org/downloads/windows/ |

> 纯标准库实现，**无需安装任何第三方 Python 包**。

## 🚀 快速开始

```bash
# 打开图形界面
python WindowsPP.py

# 只读扫描（命令行，不执行更新）
python WindowsPP.py --scan

# 后台最小化运行（开机启动 / 桌面监控场景）
python WindowsPP.py --tray
```

Windows 用户也可直接双击 `启动WindowsPP.bat`（自动探测 py/python 解释器）。

### 界面操作

1. 点击 **🔄 扫描并检查更新**，列出全部已装软件，可更新项默认勾选 ✔
2. 调整勾选：点击行首 ✔ 列，或选中行后**右键**「取消勾选（不更新）」
3. 点击 **⬆ 开始更新（选中项）**，确认清单后开始批量升级
4. 更新过程中可随时 **暂停 / 跳过当前 / 取消当前 / 取消全部**
5. 完成后点 **📄 导出报告** 留档

### 状态说明

| 状态 | 颜色 | 含义 |
|---|---|---|
| 等待 / 进行中 | 灰 / 蓝 | 排队中 / 正在执行 |
| 成功 / 失败 | 绿 / 红 | winget 执行结果 |
| 超时 | 橙 | 单个软件超过 30 分钟未完成，自动终止 |
| 已跳过 / 已取消 | 灰 | 用户操作导致未完成 |
| 已是最新 | 绿 | 注册表版本已达标（winget 误报自动纠正） |

## 🗂 文件结构

```
WindowsPP/
├── WindowsPP.py          # 主程序（GUI + 命令行）
├── 启动WindowsPP.bat     # 双击启动脚本
├── WindowsPP.ico         # 程序图标（微软四色格子）
├── make_icon.py          # 图标生成脚本（可选）
├── make_shortcut.py      # 桌面快捷方式创建脚本（可选）
└── package.py            # zip 打包 + 使用说明生成脚本（可选）
```

## 💡 常见问题

- **启动提示找不到 winget？** 在微软商店安装「应用安装程序」，重开程序即可。
- **更新失败？** 查看日志错误尾巴，常见原因是软件正在运行 / 需要管理员权限。可稍后手动执行 `winget upgrade --id <ID> -e`。
- **状态是「—」（灰色）？** 说明 winget 未收录该软件，无法自动判定/升级，属正常现象。
- **超时了？** 大软件（如 Visual Studio）下载慢，可先跳过，或调大 `WindowsPP.py` 中的 `UPDATE_TIMEOUT` 常量（默认 1800 秒）。

## ⚠️ 免责声明

- 所有更新均调用系统自带 winget，安装包来自 winget 官方源（winget / msstore）
- 「跳过 / 取消」会强制结束 winget 进程树，极少数情况可能留下不完整安装，重试一次即可
- 本工具仅做版本检查与升级，**不包含卸载功能**

## 📄 License

[MIT](LICENSE)

Copyright (c) 2026 twinightminer-arch
