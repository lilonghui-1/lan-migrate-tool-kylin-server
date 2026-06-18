"""
全局配置文件
"""
import os
import sys

# 获取应用程序所在目录
def get_app_dir():
    """获取应用程序所在目录（处理打包和源码两种情况）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()

# 应用信息
APP_NAME = "LAN迁移工具"
VERSION = "1.0.0"

# 调试配置 - 使用环境变量控制，默认关闭
DEBUG = os.environ.get('LAN_MIGRATE_DEBUG', 'false').lower() in ('true', '1', 'yes')
DEBUG_LOG_FILE = os.path.join(APP_DIR, "transfer_debug.log")  # 调试日志文件

# 网络配置
SERVICE_TYPE = "_filetransfer._tcp.local."
DEFAULT_PORT = 9000

# 传输配置
CHUNK_SIZE = 524288               # 512KB，增大常规传输块大小以提高吞吐量
RESUME_CHUNK_SIZE = 33554432      # 32MB，大幅增大断点续传分块大小
SOCKET_TIMEOUT = 600              # socket超时时间增加到10分钟
FILE_MAX_RETRIES = 0              # 取消单个文件重试，由上层管理

# 自动重试策略配置（指数退避）
RETRY_ENABLED = True              # 是否启用自动重试
RETRY_MAX_ATTEMPTS = 5            # 单个文件最大重试次数
RETRY_BASE_DELAY = 2              # 基础重试延迟（秒）
RETRY_MAX_DELAY = 60              # 最大重试延迟（秒）
RETRY_EXPONENTIAL = True          # 是否使用指数退避
RETRY_TIMEOUT_PER_FILE = 300      # 单个文件超时时间（秒），慢网络下缩短

# 传输时间窗口配置（定时传输）
SCHEDULE_ENABLED = False          # 是否启用定时传输
SCHEDULE_START_TIME = "22:00"     # 默认开始时间（HH:MM格式）
SCHEDULE_END_TIME = "06:00"       # 默认结束时间（HH:MM格式）
SCHEDULE_ALLOW_PAUSE = True       # 是否在时间窗口外暂停传输

# 慢网络自适应传输配置
ADAPTIVE_CHUNK_ENABLED = True     # 是否启用自适应分块大小
ADAPTIVE_MIN_CHUNK = 65536        # 最小分块大小（64KB）
ADAPTIVE_MAX_CHUNK = 1048576      # 最大分块大小（1MB）
ADAPTIVE_SPEED_THRESHOLD_LOW = 1048576     # 低速阈值：1MB/s以下视为慢网络
ADAPTIVE_SPEED_THRESHOLD_HIGH = 10485760   # 高速阈值：10MB/s以上视为快网络
ADAPTIVE_SWITCH_INTERVAL = 10     # 每10秒评估一次网络状况并调整分块大小

# 心跳配置
HEARTBEAT_INTERVAL = 30           # 心跳间隔增大到30秒，减少网络开销
HEARTBEAT_TIMEOUT = 120           # 心跳超时时间增加到2分钟

# 数据库配置
DB_NAME = os.path.join(APP_DIR, "transfer_state.db")

# 浏览器配置
BROWSERS = {
    "Chrome": {
        "path": r"Google\Chrome\User Data",
        "local": True,
        "processes": ["chrome.exe"]
    },
    "Edge": {
        "path": r"Microsoft\Edge\User Data",
        "local": True,
        "processes": ["msedge.exe"]
    },
    "Firefox": {
        "path": r"Mozilla\Firefox\Profiles",
        "local": False,
        "processes": ["firefox.exe"]
    }
}

# 用户文件夹配置
USER_FOLDERS = [
    ("Documents", "文档"),
    ("Desktop", "桌面"),
    ("Downloads", "下载"),
    ("Pictures", "图片"),
    ("Videos", "视频"),
    ("Music", "音乐"),
]

# 注册表配置
REGISTRY_ROOT = r"Software"
