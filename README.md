# Windows++ 🪟

> 一站式 Windows 软件管家：检查更新 · 卸载软件 · 清理旧版 · 锁定桌面 · 个性化 · 桌面工具与宠物

Windows++ 是一款 Windows 桌面工具，左侧导航栏集成六大功能模块：

## ✨ 功能一览

| 模块 | 说明 |
|---|---|
| ⬆ **软件更新** | 注册表枚举 + winget 比对，一键批量更新，支持暂停/跳过/取消、实时状态、右键取消勾选、导出报告；注册表版本交叉校验，更新后不再误报 |
| 🗑 **软件卸载** | 已装软件列表，支持名称搜索、按名称/大小/日期排序，调用系统卸载程序并反馈结果 |
| 🧹 **扫描清理** | 全盘扫描「旧版本残留文件」+「下载未清理的安装包」，进度条、勾选列表、全选/全不选、清理选中 |
| 🔒 **桌面锁定** | 一键扫描桌面图标、逐图标锁定开关（持久化）；锁定图标被移动/删除时弹窗提示并可一键前往解锁；支持全局自动排列锁定 |
| ⚙ **设置** | Windows 10/11 色板主题一键换肤；背景图片/视频（不透明度滑块，默认 35%）；背景音乐（视频未静音时优先视频音轨） |
| 🧸 **工具与宠物** | 内置时钟/日历/CPU 仪表盘小工具（独立打开 + 开机自启动）；桌面宠物（默认 FeibiPet，支持指定路径/导入自定义） |

## 📦 环境要求

| 依赖 | 说明 |
|---|---|
| Windows 10 (1809+) / Windows 11 | 必需 |
| winget（Windows 包管理器） | Win11 与新版 Win10 通常自带；缺失时在微软商店安装「应用安装程序」或访问 https://aka.ms/getwinget |
| Python 3.7+（含 tkinter） | 源码运行需要；也可直接使用发布的 **exe 免安装版** |

> 纯标准库实现（源码版），**无需安装任何第三方 Python 包**。

## 🚀 快速开始

```bash
# 方式一：双击已编译的 WindowsPP.exe（免安装）

# 方式二：源码运行（图形界面）
python WindowsPP.py

# 只读扫描（命令行，不执行更新）
python WindowsPP.py --scan

# 后台最小化运行（开机启动 / 桌面监控场景）
python WindowsPP.py --tray
```

Windows 用户也可直接双击 `启动WindowsPP.bat`（自动探测 py/python 解释器）。

## 🗂 文件结构

```
WindowsPP/
├── WindowsPP.py          # 入口（GUI + 命令行）
├── wpp_tools.py          # 内置小工具独立入口（开机自启动用）
├── wpp/                  # 核心包
│   ├── app.py            # 主框架：侧边栏导航 + 页面切换 + 主题/背景
│   ├── common.py         # 公共库：命令/注册表/winget/清理/配置/桌面监控
│   ├── tools.py          # 时钟 / 日历 / CPU 仪表盘
│   ├── page_updater.py   # 软件更新页
│   ├── page_uninstall.py # 软件卸载页
│   ├── page_cleaner.py   # 扫描清理页
│   ├── page_desklock.py  # 桌面锁定页
│   ├── page_settings.py  # 设置页
│   └── page_toys.py      # 工具与宠物页
├── 启动WindowsPP.bat     # 双击启动脚本
├── WindowsPP.ico         # 程序图标（微软四色格子）
├── make_icon.py / make_shortcut.py / package.py  # 工具脚本
```

## 💡 常见问题

- **启动提示找不到 winget？** 在微软商店安装「应用安装程序」，重开程序即可。
- **更新失败？** 查看日志错误尾巴，常见原因是软件正在运行 / 需要管理员权限。可稍后手动执行 `winget upgrade --id <ID> -e`。
- **状态是「—」（灰色）？** 说明 winget 未收录该软件，无法自动判定/升级，属正常现象。
- **背景图片不显示？** 图片缩放/透明度需要 pillow（`pip install pillow`），未安装时仅显示原尺寸。
- **桌面锁定拦不住拖拽？** Windows 未提供阻止拖拽的官方接口，请配合「全局锁定（自动排列）」使用。

## ⚠️ 免责声明

- 所有更新均调用系统自带 winget，安装包来自 winget 官方源（winget / msstore）
- 卸载功能仅调用软件自带卸载程序，不静默删除任何文件
- 「跳过 / 取消」会强制结束 winget 进程树，极少数情况可能留下不完整安装，重试一次即可

## 📄 License

[MIT](LICENSE)

Copyright (c) 2026 twinightminer-arch
