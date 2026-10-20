# -*- coding: utf-8 -*-
"""
C盘空间扫描器 v1.1
- 扫描指定目录（默认 C:\），按占用大小列出子文件夹/文件
- 每项附带「用途说明」与「能否删」标注，告诉你这是啥、能不能动
- 勾选后删除（送入回收站，可逆，不会直接永久删除）
- 「打开文件夹」按钮：在资源管理器中打开/定位选中项
- 双击文件夹可进入下一层继续扫描
依赖：仅标准库（tkinter / ctypes / subprocess / os）
"""
import os
import sys
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import ctypes
    from ctypes import wintypes
    _HAS_WIN = True
except Exception:
    _HAS_WIN = False


# ---------- 回收站删除（Windows 原生，可逆） ----------
FO_DELETE = 3
FOF_ALLOWUNDO = 0x40
FOF_NOCONFIRMATION = 0x10


def send_to_recycle_bin(paths):
    """把路径列表送入回收站，返回 (成功数, 失败列表)。仅 Windows。"""
    if not _HAS_WIN:
        return 0, paths
    if not paths:
        return 0, []
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.UINT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]
    pFrom = "\0".join(paths) + "\0\0"
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = pFrom
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION
    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if res == 0 and not op.fAnyOperationsAborted:
        return len(paths), []
    return 0, paths


# ---------- 用途说明知识库 ----------
# 规则：按路径关键字匹配（小写），命中即返回 (说明, 风险)
# 风险：green=可安全清理 / yellow=谨慎（先打开确认）/ red=勿动 / gray=未识别
KB = [
    # ===== 系统 =====
    ("\\windows\\winsxs", "Windows 组件存储（系统更新必需，手删会损坏系统）", "red"),
    ("\\windows\\installer", "程序安装缓存（卸载/修复软件必需）", "red"),
    ("\\windows\\system32", "系统核心 DLL 库（勿动）", "red"),
    ("\\windows\\syswow64", "32 位兼容组件库（勿动）", "red"),
    ("\\windows\\servic", "系统服务运行数据（勿动）", "red"),
    ("\\windows\\assembly", ".NET 程序集缓存（勿动）", "red"),
    ("\\windows\\security", "系统安全与证书存储", "red"),
    ("\\windows\\inf", "驱动安装文件", "red"),
    ("\\windows\\fonts", "系统字体", "red"),
    ("\\windows\\softwaredistribution", "Windows 更新下载缓存（可清，会自动重下）", "green"),
    ("\\windows\\temp", "系统临时文件（可清）", "green"),
    ("\\windows\\memory.dmp", "系统崩溃转储文件（可清）", "green"),
    ("\\windows\\minidump", "系统小转储文件（可清）", "green"),
    ("\\windows\\logs", "系统日志", "yellow"),
    ("\\windows\\panther", "系统升级日志", "green"),
    ("\\$recycle.bin", "回收站（清空后不可恢复）", "yellow"),
    ("\\system volume information", "系统还原点与卷影副本（可清理旧还原点）", "yellow"),
    ("\\pagefile.sys", "虚拟内存文件（勿删）", "red"),
    ("\\hiberfil.sys", "休眠文件（关闭休眠可释放）", "yellow"),
    ("\\swapfile.sys", "系统交换文件（勿删）", "red"),

    # ===== NVIDIA / 显卡 =====
    ("\\programdata\\nvidia corporation\\downloader", "NVIDIA 驱动安装包缓存（可清，会自动重下）", "green"),
    ("\\programdata\\nvidia corporation\\drs", "NVIDIA 驱动配置备份（可清）", "green"),
    ("\\programdata\\nvidia corporation", "NVIDIA 驱动公共数据/安装缓存（多数可清）", "green"),
    ("\\programdata\\nvidia", "NVIDIA 公共数据（多数可清）", "green"),
    ("\\appdata\\local\\nvidia\\dxcache", "NVIDIA DirectX 着色器缓存（可清，游戏启动重建）", "green"),
    ("\\appdata\\local\\nvidia\\glcache", "NVIDIA OpenGL 着色器缓存（可清，游戏启动重建）", "green"),
    ("\\appdata\\local\\nvidia", "NVIDIA 着色器缓存（可清，游戏启动自动重建）", "green"),
    ("\\program files\\nvidia gpu computing toolkit", "NVIDIA CUDA 工具包（AI/PyTorch 训练用，删了需重装）", "yellow"),
    ("\\program files\\nvidia corporation", "NVIDIA 驱动与控制面板（勿动）", "red"),
    ("\\program files (x86)\\nvidia", "NVIDIA 驱动 32 位组件（勿动）", "red"),

    # ===== 编程 / Python 生态 =====
    ("\\appdata\\local\\uv\\cache", "uv 依赖缓存（可清：uv cache clean）", "green"),
    ("\\appdata\\local\\uv", "uv 包管理缓存（可清：uv cache clean）", "green"),
    ("\\appdata\\local\\pip\\cache", "pip 下载缓存（可清：pip cache purge）", "green"),
    ("\\appdata\\local\\pip", "pip 安装缓存（可清：pip cache purge）", "green"),
    ("\\appdata\\local\\programs\\python", "Python 解释器本体（删了所有环境失效）", "red"),
    ("\\appdata\\local\\node-gyp", "Node 原生模块编译缓存（可清）", "green"),
    ("\\appdata\\local\\npm-cache", "npm 缓存（可清：npm cache clean）", "green"),
    ("\\appdata\\roaming\\npm", "npm 全局包（装的命令行工具）", "yellow"),
    ("\\appdata\\local\\conda", "Conda 环境与包缓存", "yellow"),
    ("\\.conda", "Conda 环境目录", "yellow"),
    ("\\anaconda3", "Anaconda 安装目录（Python 环境）", "yellow"),
    ("\\programdata\\anaconda3", "Anaconda 公共包与缓存", "yellow"),
    ("\\program files\\dotnet", ".NET 运行时/SDK（很多软件依赖，勿乱删）", "red"),
    ("\\program files\\java", "Java 运行环境（JRE/JDK，勿动）", "red"),
    ("\\program files\\git", "Git 客户端", "yellow"),
    ("\\git", "Git 客户端", "yellow"),
    ("\\.gitconfig", "Git 全局配置文件", "yellow"),

    # ===== 浏览器 =====
    ("\\appdata\\local\\google\\chrome\\user data", "Chrome 用户数据（书签/密码/扩展，勿删）", "red"),
    ("\\appdata\\local\\google\\chrome\\cache", "Chrome 网页缓存（可清）", "green"),
    ("\\appdata\\local\\google", "Google 浏览器数据（Chrome 配置与缓存）", "yellow"),
    ("\\appdata\\local\\microsoft\\edge", "Edge 浏览器数据", "yellow"),
    ("\\appdata\\local\\chromium", "Chromium 浏览器数据", "yellow"),
    ("\\appdata\\roaming\\mozilla", "Firefox 配置（书签与扩展）", "red"),
    ("\\appdata\\local\\d3dscache", "DirectX 着色器缓存（可清）", "green"),
    ("\\appdata\\local\\crashdumps", "程序崩溃转储（可清）", "green"),

    # ===== 聊天 / 网盘 / 云 =====
    ("\\appdata\\roaming\\tencent\\wechat", "微信聊天记录与接收文件（勿删）", "red"),
    ("\\appdata\\roaming\\tencent\\qq", "QQ 聊天记录与接收文件（勿删）", "red"),
    ("\\appdata\\roaming\\tencent", "微信/QQ 聊天记录与附件（勿删）", "red"),
    ("\\appdata\\roaming\\baidu", "百度网盘同步数据（勿删）", "red"),
    ("\\appdata\\roaming\\quark", "夸克网盘/浏览器数据", "yellow"),
    ("\\appdata\\local\\quark", "夸克网盘/浏览器本地数据", "yellow"),
    ("\\appdata\\local\\quarkclouddrive", "夸克网盘下载与缓存（可清）", "green"),
    ("\\appdata\\roaming\\onedrive", "OneDrive 同步数据（勿删）", "red"),
    ("\\onedrive", "OneDrive 云同步目录（勿删）", "red"),
    ("\\dropbox", "Dropbox 同步目录（勿删）", "red"),
    ("\\appdata\\roaming\\.heyboxwow", "Heybox 工具数据", "yellow"),
    ("\\appdata\\roaming\\ccvoicehub", "语音工具数据", "yellow"),
    ("\\appdata\\roaming\\qqex", "QQ 扩展组件数据", "yellow"),

    # ===== 豆包 / AI 工具 =====
    ("\\appdata\\local\\doubao", "豆包客户端本地数据（含提示词库，勿删）", "red"),
    ("\\appdata\\roaming\\doubao", "豆包客户端配置（勿删）", "red"),
    ("\\appdata\\local\\webgrabber", "网页助手项目数据（你的工作文件，勿删）", "red"),
    ("\\appdata\\roaming\\webgrabber", "网页助手配置（勿删）", "red"),
    ("\\appdata\\local\\comfy", "ComfyUI 本地数据（模型/工作流，勿删）", "red"),
    ("\\appdata\\local\\clipdrop", "Clipdrop AI 工具数据", "yellow"),
    ("\\appdata\\roaming\\comfyui", "ComfyUI 配置（勿删）", "red"),
    ("\\appdata\\local\\comfyui", "ComfyUI 用户数据（勿删）", "red"),

    # ===== 模拟器 =====
    ("\\ldplayer", "雷电模拟器（游戏实例与镜像，删了丢模拟器）", "red"),
    ("\\androwsbox", "夜神模拟器（游戏实例，删了丢模拟器）", "red"),
    ("\\program files\\ldplayer", "雷电模拟器程序本体", "red"),
    ("\\program files\\androwsbox", "夜神模拟器程序本体", "red"),

    # ===== 其他软件 =====
    ("\\program files\\tencent", "腾讯软件本体（QQ/WeChat/游戏）", "yellow"),
    ("\\programdata\\tencent", "腾讯软件公共数据", "yellow"),
    ("\\program files\\workbuddy", "WorkBuddy 本体（含插件缓存）", "yellow"),
    ("\\program files\\comfy desktop", "ComfyUI 桌面版", "yellow"),
    ("\\program files\\epic games", "Epic Games 启动器（游戏本体在别处）", "yellow"),
    ("\\epic games", "Epic Games 启动器与游戏", "yellow"),
    ("\\program files\\lg hub", "罗技 G HUB 设备软件（可卸，键鼠灯效会失效）", "yellow"),
    ("\\lg hub", "罗技 G HUB 设备软件（可卸，键鼠灯效会失效）", "yellow"),
    ("\\lghub", "罗技 G HUB 设备软件（可卸，键鼠灯效会失效）", "yellow"),
    ("\\program files\\windowsapps", "微软商店应用安装目录（删了对应应用会丢失）", "red"),
    ("\\program files\\common files", "各软件共用组件库（勿动）", "red"),
    ("\\reference assemblies", "开发参考程序集（可清，会重新下载）", "green"),
    ("\\program files (x86)\\microsoft", "微软旧版 32 位组件（部分软件依赖，勿动）", "red"),
    ("\\programdata\\lg hub", "罗技 G HUB 配置与更新包（可清）", "green"),
    ("\\program files (x86)\\kingsoft", "金山 WPS/金山组件", "yellow"),
    ("\\appdata\\roaming\\kingsoft", "WPS 文档数据（勿删）", "red"),
    ("\\appdata\\roaming\\sogouinput", "搜狗输入法词库与配置（勿删）", "red"),
    ("\\program files (x86)\\sogouinput", "搜狗输入法程序本体", "yellow"),
    ("\\huorong", "火绒安全软件（可卸，卸后需换杀软）", "yellow"),
    ("\\cloudflare", "Cloudflare WARP 隧道程序", "yellow"),
    ("\\moonlight", "Moonlight 串流客户端", "yellow"),
    ("\\cheat engine", "Cheat Engine 修改器（自己用的调试工具）", "yellow"),
    ("\\program files\\todesk", "ToDesk 远程控制（可删）", "green"),
    ("\\program files\\2345soft", "2345 系列软件（浏览器/看图/输入法）", "yellow"),
    ("\\appdata\\roaming\\2345pic", "2345 看图图片数据与配置", "yellow"),
    ("\\appdata\\roaming\\2345ocr", "2345 OCR 数据", "yellow"),
    ("\\uninstall", "程序卸载信息（乱删会导致无法卸载）", "red"),
    ("\\package cache", "安装包缓存（删了可能无法修复/卸载）", "yellow"),
    ("\\usoshared", "Windows 更新共享数据", "yellow"),
    ("\\searchpicturetool", "搜图工具数据（可清）", "green"),
    ("\\kuwodata", "数据采集组件数据（可清）", "green"),
    ("\\oray", "向日葵远程控制数据（可清）", "green"),
    ("\\appdata\\local\\temp", "用户临时文件（可清）", "green"),
    ("\\windows.old", "旧版 Windows 备份（可删，释放大量空间）", "green"),
    ("\\appdata\\local\\microsoft\\windows\\inetcache", "系统网络缓存（可清）", "green"),
    ("\\appdata\\local\\microsoft\\windows\\webcache", "网页缓存（可清）", "green"),
    ("\\appdata\\local\\microsoft\\windows\\explorer", "缩略图与图标缓存（可清）", "green"),
    ("\\appdata\\local\\microsoft\\windows\\wer", "Windows 错误报告（可清）", "green"),
    ("\\appdata\\local\\microsoft\\onedrive", "OneDrive 客户端程序", "yellow"),
    ("\\programdata\\microsoft\\search", "Windows 搜索索引（可重建）", "green"),
    ("\\program files\\microsoft office", "Office 办公套件", "red"),
    ("\\appdata\\local\\microsoft\\office", "Office 本地数据", "yellow"),
]

# 文件名关键字（路径没命中时，用文件名猜）
NAME_KB = [
    ("cache", "缓存文件（可清）", "green"),
    ("cachedata", "缓存数据（可清）", "green"),
    ("temp", "临时文件（可清）", "green"),
    ("tmp", "临时文件（可清）", "green"),
    ("log", "日志文件（可清）", "green"),
    ("crashdump", "崩溃转储（可清）", "green"),
    ("backup", "备份文件（先确认再动）", "yellow"),
    ("installer", "安装包（可清）", "green"),
    ("setup", "安装包（可清）", "green"),
    ("download", "下载相关文件/目录（确认后再处理）", "yellow"),
    ("packages", "软件包缓存（可清）", "green"),
    ("shader", "着色器缓存（可清）", "green"),
    (".old", "旧版本残留（可清）", "green"),
]

# 扩展名说明
EXT_KB = {
    ".exe": "程序可执行文件", ".dll": "程序库文件", ".sys": "系统驱动文件",
    ".log": "日志文件（可清）", ".tmp": "临时文件（可清）", ".bak": "备份文件",
    ".old": "旧版残留（可清）", ".zip": "压缩包", ".7z": "压缩包", ".rar": "压缩包",
    ".iso": "光盘镜像", ".mp4": "视频文件", ".mkv": "视频文件", ".avi": "视频文件",
    ".mov": "视频文件", ".jpg": "图片文件", ".png": "图片文件", ".gif": "图片文件",
    ".mp3": "音频文件", ".wav": "音频文件", ".flac": "音频文件",
    ".ini": "配置文件", ".cfg": "配置文件", ".json": "配置文件", ".xml": "配置文件",
    ".dat": "数据文件", ".bin": "二进制数据", ".pak": "数据包",
    ".pdb": "调试符号（可清）", ".lib": "开发库文件", ".obj": "编译中间文件",
}

RISK_TEXT = {"green": "可安全清理", "yellow": "谨慎", "red": "勿动", "gray": "未识别"}
RISK_COLOR = {"green": "#1b7f3b", "yellow": "#b35c00", "red": "#c62828", "gray": "#666666"}


def describe(path, is_dir):
    """返回 (用途说明, 风险等级key)。"""
    p = path.lower().replace("/", "\\")
    for key, desc, risk in KB:
        if key in p:
            return desc, risk
    name = os.path.basename(p)
    for key, desc, risk in NAME_KB:
        if key in name:
            return desc, risk
    if not is_dir:
        ext = os.path.splitext(name)[1].lower()
        if ext in EXT_KB:
            desc = EXT_KB[ext]
            risk = "green" if "可清" in desc else "gray"
            return desc, risk
    # 按所在位置兜底
    stripped = p.rstrip("\\")
    parts = [x for x in stripped.split("\\") if x]
    tail = parts[-1].lower() if parts else ""
    if tail == "windows" and stripped.endswith(":\\windows"):
        return "Windows 系统目录（勿动）", "red"
    if tail == "program files":
        return "已安装的软件（64 位）", "yellow"
    if tail == "program files (x86)":
        return "已安装的软件（32 位，兼容组件）", "yellow"
    if tail == "programdata":
        return "软件公共数据 / 驱动缓存", "yellow"
    if tail == "users":
        return "各用户主目录（个人数据都在这）", "yellow"
    if tail == "appdata":
        return "用户应用配置与缓存目录", "yellow"
    if tail == "local" and len(parts) >= 2 and parts[-2].lower() == "appdata":
        return "用户本地应用数据与缓存", "yellow"
    if tail == "roaming" and len(parts) >= 2 and parts[-2].lower() == "appdata":
        return "用户漫游配置数据", "yellow"
    if "\\windows\\" in p:
        return "Windows 系统文件/组件", "red"
    if "\\program files\\" in p:
        return "已安装的软件（64 位）", "yellow"
    if "\\program files (x86)\\" in p:
        return "已安装的软件（32 位，兼容组件）", "yellow"
    if "\\programdata\\" in p:
        return "软件公共数据 / 驱动缓存", "yellow"
    if "\\appdata\\local\\" in p:
        return "用户本地应用数据与缓存", "yellow"
    if "\\appdata\\roaming\\" in p:
        return "用户漫游配置数据", "yellow"
    if is_dir:
        return "普通文件夹（建议先打开确认内容）", "gray"
    return "未识别的项目（建议先打开看看）", "gray"


# ---------- 工具函数 ----------
def fmt_size(n):
    if n is None or n < 0:
        return "无权限"
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_point(path):
    """判断路径是否为联接/符号链接（Windows 重解析点）。"""
    try:
        st = os.lstat(path)
        return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


class SizeCache:
    """目录体积缓存。

    第一次扫描 C:\\ 时会把所有子目录的体积算完并记下来；
    之后往下一层翻，只做 os.scandir 列目录 + 查表，不再重复遍历磁盘。
    """

    def __init__(self):
        self._sizes = {}      # 目录路径 -> 字节数
        self.hits = 0         # 缓存命中次数
        self.misses = 0       # 实际遍历次数
        self.disabled = False  # 关闭时置位，阻止后台线程再写缓存

    def size_of(self, path):
        if self.disabled:
            return 0
        v = self._sizes.get(path)
        if v is not None:
            self.hits += 1
            return v
        self.misses += 1
        v = self._compute(path)
        if not self.disabled:      # 计算期间可能已被关闭，别再写回
            self._sizes[path] = v
        return v

    def _compute(self, path):
        if is_reparse_point(path):
            return 0
        total = 0
        try:
            for entry in os.scandir(path):
                try:
                    st = entry.stat(follow_symlinks=False)
                    # 联接 / 符号链接：只算链接自身，不递归进去
                    if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        total += self.size_of(entry.path)
                    else:
                        total += st.st_size
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            return -1
        return total

    def invalidate(self, path):
        """清掉某个路径及其所有子目录的缓存。"""
        p = path.lower().rstrip("\\")
        for k in [k for k in self._sizes
                  if k.lower().rstrip("\\") == p or k.lower().rstrip("\\").startswith(p + "\\")]:
            del self._sizes[k]

    def clear(self):
        self._sizes.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self):
        return len(self._sizes)


_DEFAULT_CACHE = SizeCache()


def dir_size(path, cache=None):
    """目录体积（带缓存）。"""
    return (cache or _DEFAULT_CACHE).size_of(path)


def open_in_explorer(path):
    """在资源管理器中打开文件夹，或定位选中文件。"""
    if not os.path.exists(path):
        messagebox.showwarning("提示", f"路径不存在：\n{path}")
        return
    try:
        if os.path.isfile(path):
            subprocess.run(['explorer', f'/select,"{path}"'], shell=True)
        else:
            os.startfile(path)
    except Exception as e:
        messagebox.showerror("打开失败", str(e))


# ---------- 主程序 ----------
class DiskScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("C 盘空间扫描器 v1.4")
        self.root.geometry("1240x680")

        self.current_path = "C:\\"
        self.all_entries = []          # 当前目录下全部子项
        self.selected = set()          # 勾选要删除的路径
        self.scanning = False
        self.cache = SizeCache()       # 体积缓存，跨层级复用
        self._scan_gen = 0             # 扫描代次，防止旧结果覆盖新结果

        self._build_ui()
        self._start_scan(self.current_path)

    # -------- 退出清理 --------
    def _on_close(self):
        """关闭程序时自动清空缓存。

        缓存全部在内存里（不写任何临时文件到磁盘），退出时显式清空，
        确保不留残留、不占用内存。正在跑的后台扫描线程是守护线程，
        会被随之结束，不会卡住退出。
        """
        n = len(self.cache)
        self.cache.disabled = True   # 先停写，避免后台线程把缓存又填回来
        self.cache.clear()
        self.selected.clear()
        self.all_entries = []
        self._scan_gen += 1           # 让在途的扫描结果作废
        try:
            self.status_var.set(f"已退出，清理内存缓存 {n} 个目录")
            self.root.update_idletasks()
        except Exception:
            pass
        self.root.destroy()

    # -------- UI --------
    def _build_ui(self):
        # 顶部：路径 + 操作
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="路径：").pack(side="left")
        self.path_var = tk.StringVar(value=self.current_path)
        self.path_entry = ttk.Entry(top, textvariable=self.path_var, width=42)
        self.path_entry.pack(side="left", padx=(0, 6))
        self.path_entry.bind("<Return>", lambda e: self._start_scan(self.path_var.get()))

        ttk.Button(top, text="扫描", command=lambda: self._start_scan(self.path_var.get())).pack(side="left", padx=2)
        ttk.Button(top, text="↑ 返回上级", command=self._go_up).pack(side="left", padx=2)
        ttk.Button(top, text="刷新", command=lambda: self._start_scan(self.current_path)).pack(side="left", padx=2)
        ttk.Button(top, text="重算此项",
                   command=lambda: self._start_scan(self.current_path, force=True)).pack(side="left", padx=2)
        ttk.Button(top, text="清空缓存", command=self._clear_cache).pack(side="left", padx=2)

        ttk.Label(top, text="仅显示 ≥").pack(side="left", padx=(12, 2))
        self.thr_var = tk.StringVar(value="100 MB")
        thr_cb = ttk.Combobox(top, textvariable=self.thr_var, width=9, state="readonly",
                              values=["全部", "10 MB", "50 MB", "100 MB", "500 MB", "1 GB"])
        thr_cb.pack(side="left")
        thr_cb.bind("<<ComboboxSelected>>", lambda e: self._repopulate())

        # 进度条 + 状态
        mid = ttk.Frame(self.root)
        mid.pack(fill="x", padx=8)
        self.progress = ttk.Progressbar(mid, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 4))
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(mid, textvariable=self.status_var).pack(anchor="w")

        # 列表
        # 注意：Treeview 的父容器必须是 tree_wrap，否则 grid/pack 会打架
        tree_wrap = ttk.Frame(self.root)
        tree_wrap.pack(fill="both", expand=True, padx=8, pady=(4, 4))

        cols = ("sel", "name", "size", "desc", "risk", "type", "path")
        self.cols = cols
        self.tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", selectmode="extended")
        heads = {"sel": "☑", "name": "名称", "size": "占用", "desc": "这是啥（用途说明）",
                 "risk": "能否删", "type": "类型", "path": "路径"}
        widths = {"sel": 38, "name": 230, "size": 92, "desc": 330, "risk": 80,
                  "type": 58, "path": 420}
        for c in cols:
            self.tree.heading(c, text=heads[c])
            # stretch=False：列宽完全由我们自己管理，避免 Tk 自行挤压后不恢复
            self.tree.column(c, width=widths[c], stretch=False,
                             anchor="center" if c in ("sel", "risk", "type") else ("e" if c == "size" else "w"))
        # 风险等级配色
        for key, color in RISK_COLOR.items():
            self.tree.tag_configure(key, foreground=color)

        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)
        self.vsb = vsb
        self.hsb = hsb

        # ---- 列宽自适应（自己管列宽，不让 Tk 挤压后不恢复） ----
        self.FLEX_COLS = ("name", "desc", "path")          # 参与弹性伸缩的列
        self.MIN_WIDTH = {"sel": 34, "name": 100, "size": 84, "desc": 130,
                          "risk": 70, "type": 50, "path": 110}
        self._col_ref = dict(widths)    # 基准宽度（默认比例）
        self._user_widths = {}          # 用户手动拖过的列（锁定宽度）
        self._applied = {}              # 上次实际写入的宽度
        self._relayouting = False
        self.tree.bind("<Configure>", self._on_tree_configure)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double)

        # 底部按钮
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=8, pady=6)
        ttk.Button(bottom, text="打开文件夹", command=self._open_selected).pack(side="left", padx=4)
        ttk.Button(bottom, text="全选", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(bottom, text="全不选", command=self._deselect_all).pack(side="left", padx=4)
        ttk.Button(bottom, text="删除选中（回收站）", command=self._delete_selected).pack(side="left", padx=4)
        ttk.Button(bottom, text="重置列宽", command=self._reset_columns).pack(side="left", padx=4)

        self.safe_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text="只看「可安全清理」的项",
                        variable=self.safe_var, command=self._repopulate).pack(side="left", padx=(14, 4))
        self.sel_size_var = tk.StringVar(value="已选：0 项 / 0 B")
        ttk.Label(bottom, textvariable=self.sel_size_var).pack(side="right", padx=6)

        # 图例
        legend = ttk.Frame(self.root)
        legend.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(legend, text="图例：", foreground="#555555").pack(side="left")
        for key, label in (("green", "可安全清理（删了会自动重建）"),
                           ("yellow", "谨慎（先点「打开文件夹」确认）"),
                           ("red", "勿动（系统文件 / 你的数据）"),
                           ("gray", "未识别（自己看一眼）")):
            lb = ttk.Label(legend, text=label, foreground=RISK_COLOR[key])
            lb.pack(side="left", padx=6)

    # -------- 列宽自适应 --------
    def _col_at(self, x):
        """把 identify_column 返回的 '#3' 换成列名。"""
        try:
            cid = self.tree.identify_column(x)
            if cid.startswith("#"):
                return self.cols[int(cid[1:]) - 1]
        except Exception:
            pass
        return None

    def _on_tree_configure(self, event):
        """窗口尺寸变化 → 重新分配列宽，让所有列始终铺满可用宽度。"""
        if event.widget is not self.tree:
            return
        self._layout_columns()

    def _on_tree_release(self, event):
        """用户可能刚拖过表头分隔线，松手后重排一次（保留他拖出来的宽度）。"""
        try:
            region = self.tree.identify_region(event.x, event.y)
        except Exception:
            return
        if region != "heading":
            return
        col = self._col_at(event.x)
        if col:
            # 手动调过的列锁定为固定宽度，窗口缩放时不再被改动
            self._user_widths[col] = self.tree.column(col, "width")
        self._layout_columns()

    def _layout_columns(self):
        """按可用宽度重新分配各列宽度。

        · 固定列（勾选/占用/能否删/类型）保持设定宽度
        · 用户手动拖过的列锁定为该宽度，不再被自动缩放
        · 剩下的弹性列（名称/说明/路径）按基准比例瓜分剩余空间

        这样窗口拉窄再拉宽时，列宽会跟着恢复，不会被压扁后回不来。
        """
        if self._relayouting:
            return
        self._relayouting = True
        try:
            tree = self.tree
            w = tree.winfo_width()
            if w <= 1:
                return
            vsb_w = self.vsb.winfo_width() if self.vsb.winfo_ismapped() else 0
            avail = w - vsb_w - 6
            if avail < 240:
                return

            new = {}
            flex = []
            for c in self.cols:
                if c in self._user_widths:
                    new[c] = self._user_widths[c]          # 手动锁定
                elif c in self.FLEX_COLS:
                    flex.append(c)
                    new[c] = self._col_ref[c]
                else:
                    new[c] = self._col_ref[c]              # 固定列

            fixed_total = sum(new[c] for c in self.cols if c not in flex)
            remaining = avail - fixed_total
            ref_total = sum(self._col_ref[c] for c in flex)
            if flex and remaining > 0 and ref_total > 0:
                for c in flex:
                    new[c] = max(self.MIN_WIDTH[c], int(self._col_ref[c] * remaining / ref_total))
                # 补上取整误差
                diff = avail - sum(new.values())
                if diff:
                    last = flex[-1]
                    new[last] = max(self.MIN_WIDTH[last], new[last] + diff)
            elif flex:
                for c in flex:
                    new[c] = self.MIN_WIDTH[c]

            for c in self.cols:
                if new[c] > 0:
                    tree.column(c, width=new[c])
            self._applied = dict(new)
        finally:
            self._relayouting = False

    def _reset_columns(self):
        """恢复默认列宽（清掉手动锁定）。"""
        self._user_widths.clear()
        self._layout_columns()
        self.status_var.set("已重置列宽为默认比例。")

    # -------- 扫描 --------
    def _start_scan(self, path, force=False):
        path = os.path.abspath(path.strip())
        if not os.path.isdir(path):
            messagebox.showerror("错误", f"路径不是有效目录：\n{path}")
            return
        if force:
            self.cache.invalidate(path)
        self.current_path = path
        self.path_var.set(path)
        self.selected.clear()
        self.all_entries = []
        self.tree.delete(*self.tree.get_children())
        self.scanning = True
        self._scan_gen += 1
        gen = self._scan_gen
        self.progress.start()
        self.status_var.set(f"正在扫描：{path} （优先用缓存，没有的才实际统计…）")
        t = threading.Thread(target=self._scan_worker, args=(path, gen), daemon=True)
        t.start()

    def _scan_worker(self, path, gen):
        entries = []
        try:
            names = sorted(os.listdir(path))
        except (PermissionError, OSError) as e:
            self.root.after(0, lambda: messagebox.showerror("扫描失败", str(e)))
            self.root.after(0, self._scan_done, [], gen)
            return
        for name in names:
            full = os.path.join(path, name)
            is_dir = False
            try:
                if is_reparse_point(full):
                    # 联接/符号链接：指向别处，体积算在目标上，这里不重复计
                    size = 0
                    desc, risk = "系统兼容性联接（指向别处，勿删）", "gray"
                else:
                    is_dir = os.path.isdir(full)
                    size = self.cache.size_of(full) if is_dir else os.path.getsize(full)
                    desc, risk = describe(full, is_dir)
            except (PermissionError, OSError):
                size = -1
                desc, risk = describe(full, is_dir)
            entries.append({"name": name, "path": full, "size": size,
                            "type": "文件夹" if is_dir else "文件",
                            "desc": desc, "risk": risk})
        entries.sort(key=lambda x: (x["size"] if x["size"] >= 0 else -1), reverse=True)
        self.root.after(0, self._scan_done, entries, gen)

    def _scan_done(self, entries, gen=None):
        if gen is not None and gen != self._scan_gen:
            return  # 已被更新的扫描取代，丢弃过期结果
        self.all_entries = entries
        self.scanning = False
        self.progress.stop()
        self._repopulate()
        total = len(entries)
        safe = sum(1 for e in entries if e["risk"] == "green" and e["size"] > 0)
        safe_bytes = sum(e["size"] for e in entries if e["risk"] == "green" and e["size"] > 0)
        self.status_var.set(
            f"共 {total} 项｜可安全清理 {safe} 项 / 约 {fmt_size(safe_bytes)}｜"
            f"缓存 {len(self.cache)} 个目录（命中 {self.cache.hits} / 实算 {self.cache.misses}）｜{self.current_path}")

    def _repopulate(self):
        self.tree.delete(*self.tree.get_children())
        thr = self._threshold_bytes()
        only_safe = self.safe_var.get()
        for idx, e in enumerate(self.all_entries):
            if thr is not None and e["size"] < thr:
                continue
            if only_safe and e["risk"] != "green":
                continue
            mark = "☑" if e["path"] in self.selected else "☐"
            self.tree.insert("", "end", iid=str(idx), tags=(e["risk"],),
                             values=(mark, e["name"], fmt_size(e["size"]), e["desc"],
                                     RISK_TEXT[e["risk"]], e["type"], e["path"]))
        self._update_sel_label()

    def _threshold_bytes(self):
        v = self.thr_var.get().strip()
        if v == "全部":
            return None
        try:
            num = float(v.split()[0])
        except Exception:
            return None
        if "GB" in v.upper():
            return num * 1024 ** 3
        if "MB" in v.upper():
            return num * 1024 ** 2
        if "KB" in v.upper():
            return num * 1024
        return num

    # -------- 交互 --------
    def _on_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#1":
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        e = self.all_entries[int(row)]
        if e["path"] in self.selected:
            self.selected.discard(e["path"])
            self.tree.set(row, "sel", "☐")
        else:
            self.selected.add(e["path"])
            self.tree.set(row, "sel", "☑")
        self._update_sel_label()

    def _on_double(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        e = self.all_entries[int(row)]
        if e["type"] == "文件夹" and e["size"] != -1:
            self._start_scan(e["path"])

    def _go_up(self):
        parent = os.path.dirname(self.current_path.rstrip("\\"))
        if parent and parent != self.current_path:
            self._start_scan(parent)

    def _clear_cache(self):
        n = len(self.cache)
        self.cache.clear()
        self.status_var.set(f"已清空缓存（{n} 个目录）。下次扫描会重新统计。")

    def _open_selected(self):
        rows = self.tree.selection()
        if not rows:
            messagebox.showinfo("提示", "请先选中一行，再点「打开文件夹」。")
            return
        for row in rows:
            e = self.all_entries[int(row)]
            open_in_explorer(e["path"])

    def _select_all(self):
        for row in self.tree.get_children():
            e = self.all_entries[int(row)]
            self.selected.add(e["path"])
            self.tree.set(row, "sel", "☑")
        self._update_sel_label()

    def _deselect_all(self):
        self.selected.clear()
        for row in self.tree.get_children():
            self.tree.set(row, "sel", "☐")
        self._update_sel_label()

    def _update_sel_label(self):
        total = sum(e["size"] for e in self.all_entries if e["path"] in self.selected and e["size"] >= 0)
        self.sel_size_var.set(f"已选：{len(self.selected)} 项 / {fmt_size(total)}")

    def _delete_selected(self):
        if not self.selected:
            messagebox.showinfo("提示", "没有勾选任何项。")
            return
        paths = list(self.selected)
        picked = [e for e in self.all_entries if e["path"] in self.selected]
        size_sum = sum(e["size"] for e in picked if e["size"] >= 0)
        red = [e for e in picked if e["risk"] == "red"]
        detail = "\n".join(f"· {e['name']}（{e['desc']}）" for e in picked[:8])
        if len(picked) > 8:
            detail += "\n…"
        warn = ""
        if red:
            warn = f"\n\n⚠ 其中 {len(red)} 项标记为【勿动】：\n" + \
                   "\n".join(f"· {e['name']} — {e['desc']}" for e in red[:5]) + \
                   "\n删除后可能需要重装软件或丢失数据。"
        ans = messagebox.askyesno(
            "确认删除",
            f"将把以下 {len(paths)} 项送入【回收站】（可逆，不会永久删除）：\n\n"
            f"合计约 {fmt_size(size_sum)}\n\n{detail}{warn}\n\n确认继续？"
        )
        if not ans:
            return
        ok, failed = send_to_recycle_bin(paths)
        if failed:
            messagebox.showwarning("部分失败", f"成功 {ok} 项，失败 {len(failed)} 项：\n" + "\n".join(failed[:10]))
        else:
            messagebox.showinfo("完成", f"已送入回收站：{ok} 项。")
        self.selected.clear()
        self._start_scan(self.current_path)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use("clam")
    except Exception:
        pass
    app = DiskScannerApp(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
