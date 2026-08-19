#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wpp.recorder — 屏幕录制核心（基于系统 ffmpeg）。

- 视频：gdigrab 捕获桌面画面（全屏或指定区域）
- 音频：dshow 捕获（优先系统声音，其次第一个麦克风；无设备则仅视频）
- 输出：mp4（libx264 + aac），保存位置可自定义（默认 用户\\视频）
- 停止：向 ffmpeg 发送 'q' 正常收尾
- 全局热键：RegisterHotKey（默认 Ctrl+H）触发开始/停止
"""

import os
import re
import time
import shutil
import struct
import ctypes
import subprocess
import threading
import datetime

from wpp import common as C


# ============================================================
# ffmpeg 探测
# ============================================================
def find_ffmpeg():
    for cand in (shutil.which("ffmpeg"),
                 r"C:\ffmpeg\bin\ffmpeg.exe",
                 r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                 r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"):
        if cand and os.path.isfile(cand):
            return cand
    return None


# ============================================================
# 保存位置
# ============================================================
def default_videos_dir():
    """用户\\视频 目录（SHGetFolderPathW CSIDL_MYVIDEO=0x000E）。"""
    try:
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x000E, None, 0, buf)
        if buf.value and os.path.isdir(buf.value):
            return buf.value
    except Exception:
        pass
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Videos"), os.path.join(home, "视频")):
        if os.path.isdir(cand):
            return cand
    return home


def pick_save_dir(current=""):
    """从配置/默认返回保存目录（不存在则创建）。"""
    d = (current or "").strip()
    if not d or not os.path.isdir(d):
        d = default_videos_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


# ============================================================
# dshow 音频设备枚举
# ============================================================
def list_dshow_devices(ffmpeg):
    """枚举 dshow 音频设备名。返回 [设备名...]；失败返回 []。"""
    try:
        r = subprocess.run(
            f'"{ffmpeg}" -hide_banner -list_devices true -f dshow -i dummy',
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=20, shell=True, startupinfo=C._startupinfo() if hasattr(C, "_startupinfo") else None)
    except Exception:
        return []
    out = (r.stderr or "") + (r.stdout or "")
    names = []
    in_audio = False
    for line in out.splitlines():
        s = line.strip()
        if "DirectShow audio devices" in s or "音频设备" in s:
            in_audio = True
            continue
        if "DirectShow video devices" in s or "视频设备" in s:
            in_audio = False
            continue
        if in_audio:
            m = re.search(r'"(.*?)"', s)
            if m and m.group(1).strip():
                names.append(m.group(1).strip())
    return names


def pick_audio_device(ffmpeg):
    """优先系统声音（virtual-audio-capturer），否则第一个可用设备；无则 None。"""
    devs = list_dshow_devices(ffmpeg)
    if not devs:
        return None
    for d in devs:
        if "virtual-audio-capturer" in d.lower() or "立体声混音" in d or "Stereo Mix" in d:
            return d
    return devs[0]


# ============================================================
# 录制器
# ============================================================
class Recorder:
    """基于 ffmpeg 的屏幕录制。

    start(region=None, out_dir=None, fps=10, audio=True)
      region: (x, y, w, h) 或 None（全屏）
    stop()  -> 返回输出文件路径；失败返回 None
    """

    def __init__(self):
        self._proc = None
        self._stderr_thread = None
        self.out_path = None
        self.started_at = 0.0
        self.error = None

    @property
    def recording(self):
        return self._proc is not None and self._proc.poll() is None

    def _read_stderr(self, proc):
        """后台读取 ffmpeg stderr，用于诊断。"""
        try:
            for line in iter(proc.stderr.readline, b""):
                if line:
                    self.error = (self.error or "") + line.decode("utf-8", "ignore")
        except Exception:
            pass

    def start(self, region=None, out_dir=None, fps=10, audio=True):
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self.error = "未找到 ffmpeg，无法录制。请安装 ffmpeg 并加入 PATH。"
            return False
        if self.recording:
            return False
        d = pick_save_dir(out_dir)
        name = "WindowsPP_录屏_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".mp4"
        self.out_path = os.path.join(d, name)
        self.error = None

        # 基础 gdigrab 命令（区域 / 全屏）
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-f", "gdigrab", "-framerate", str(int(fps)),
               "-draw_mouse", "1", "-i", "desktop"]
        if region:
            x, y, w, h = [int(v) for v in region]
            if w > 0 and h > 0:
                cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                       "-f", "gdigrab", "-framerate", str(int(fps)),
                       "-draw_mouse", "1",
                       "-offset_x", str(x), "-offset_y", str(y),
                       "-video_size", f"{w}x{h}", "-i", "desktop"]

        # 音频：无可用设备时仅录制画面，避免损坏文件
        dev = pick_audio_device(ffmpeg) if audio else None
        if dev:
            cmd += ["-f", "dshow", "-thread_queue_size", "4096", "-i", f"audio={dev}"]

        # 视频编码：yuv420p 保证兼容性；AAC 音频（仅在音频设备有效时）
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                "-pix_fmt", "yuv420p", "-threads", "0"]
        if dev:
            cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
        cmd += [self.out_path]

        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, startupinfo=C._startupinfo())
        except Exception as e:
            self.error = f"启动 ffmpeg 失败: {e}"
            return False

        self._stderr_thread = threading.Thread(target=self._read_stderr, args=(self._proc,), daemon=True)
        self._stderr_thread.start()

        self.started_at = time.monotonic()
        time.sleep(0.8)
        if not self.recording:
            self.error = (self.error or "ffmpeg 启动后立即退出（可能设备被占用或无权限）").strip()
            return False
        return True

    def stop(self):
        """正常停止并返回输出路径。"""
        proc = self._proc
        self._proc = None
        if proc is None:
            return self.out_path
        try:
            proc.stdin.write(b"q")
            proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(timeout=20)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass
        if self._stderr_thread and self._stderr_thread.is_alive():
            try:
                self._stderr_thread.join(timeout=2)
            except Exception:
                pass
        self._stderr_thread = None

        # 验证文件可被 ffprobe 识别；否则给出更明确的错误
        if self.out_path and os.path.isfile(self.out_path) and os.path.getsize(self.out_path) > 1024:
            if self._video_valid(self.out_path):
                return self.out_path
            self.error = (self.error or "") + " 输出文件生成但无法被 ffprobe 解析，可能编码参数不受支持。"
        return None

    def _video_valid(self, path):
        """用 ffprobe 快速验证文件是否可解码。"""
        ffprobe = None
        for cand in (shutil.which("ffprobe"),
                     r"C:\ffmpeg\bin\ffprobe.exe",
                     r"C:\Program Files\ffmpeg\bin\ffprobe.exe"):
            if cand and os.path.isfile(cand):
                ffprobe = cand
                break
        if not ffprobe:
            return True
        try:
            r = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, errors="ignore",
                timeout=15, startupinfo=C._startupinfo())
            return bool((r.stdout or "").strip())
        except Exception:
            return True


# ============================================================
# 全局热键（RegisterHotKey）
# ============================================================
class HotKey(threading.Thread):
    """注册全局热键，按下时调用 on_press()。daemon 线程 + 消息泵。"""

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000

    def __init__(self, mods, vk, on_press):
        super().__init__(daemon=True)
        self.mods = mods
        self.vk = vk
        self.on_press = on_press
        self._id = 0xE001
        self._thread_id = None
        self._user32 = ctypes.windll.user32

    def start(self):
        # 先注销同 ID 旧热键，避免注册失败
        try:
            self._user32.UnregisterHotKey(None, self._id)
        except Exception:
            pass
        super().start()

    def stop(self):
        try:
            self._user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass

    def run(self):
        from ctypes import wintypes
        u = self._user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        mods = self.mods | self.MOD_NOREPEAT
        ok = u.RegisterHotKey(None, self._id, mods, self.vk)
        if not ok:
            return  # 注册失败（被占用等）
        msg = wintypes.MSG()
        try:
            while u.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    try:
                        self.on_press()
                    except Exception:
                        pass
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        finally:
            try:
                u.UnregisterHotKey(None, self._id)
            except Exception:
                pass


def parse_hotkey(spec):
    """'ctrl+h' -> (mods, vk)；失败返回 None。"""
    if not spec or "+" not in spec:
        return None
    mods = 0
    key = None
    for part in spec.split("+"):
        p = part.strip().lower()
        if p == "ctrl":
            mods |= HotKey.MOD_CONTROL
        elif p == "alt":
            mods |= HotKey.MOD_ALT
        elif p == "shift":
            mods |= HotKey.MOD_SHIFT
        elif p and len(p) == 1 and (p.isalnum()):
            key = ord(p.upper())
    if mods == 0 or key is None:
        return None
    return mods, key
