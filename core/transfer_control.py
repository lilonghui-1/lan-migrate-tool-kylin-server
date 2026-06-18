"""
传输时效管控模块
提供：自动重试策略（指数退避）、传输时间窗口、慢网络自适应传输
"""
import time
import math
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Callable, Optional
import config
from utils.debug import debug_log


class RetryPolicy:
    """
    自动重试策略（指数退避）
    
    当传输失败时，自动重试并逐渐增加等待间隔：
    - 第1次重试：等待 2秒
    - 第2次重试：等待 4秒
    - 第3次重试：等待 8秒
    - 第4次重试：等待 16秒
    - 第5次重试：等待 32秒
    - 最大等待时间不超过60秒
    """
    
    def __init__(self):
        self.max_attempts = config.RETRY_MAX_ATTEMPTS
        self.base_delay = config.RETRY_BASE_DELAY
        self.max_delay = config.RETRY_MAX_DELAY
        self.exponential = config.RETRY_EXPONENTIAL
        self.enabled = config.RETRY_ENABLED
        
    def get_delay(self, attempt: int) -> float:
        """获取第 attempt 次重试的等待时间"""
        if not self.exponential:
            return min(self.base_delay, self.max_delay)
        
        delay = self.base_delay * math.pow(2, attempt)
        return min(delay, self.max_delay)
    
    def should_retry(self, attempt: int) -> bool:
        """判断是否应该继续重试"""
        if not self.enabled:
            return False
        return attempt < self.max_attempts
    
    def wait_before_retry(self, attempt: int, callback: Optional[Callable] = None) -> bool:
        """
        重试前等待
        
        Args:
            attempt: 当前重试次数（从0开始）
            callback: 可选的回调函数，接收(剩余时间)参数
        
        Returns:
            如果用户在等待期间取消返回False，否则返回True
        """
        delay = self.get_delay(attempt)
        debug_log(f"重试策略: 第 {attempt + 1} 次重试，等待 {delay:.1f} 秒...",
                  level="INFO", module="retry")
        
        # 分段等待，允许中断
        waited = 0
        interval = 0.5  # 每0.5秒检查一次
        while waited < delay:
            time.sleep(interval)
            waited += interval
            remaining = delay - waited
            if callback:
                if not callback(remaining):
                    debug_log("重试策略: 用户取消等待", level="WARNING", module="retry")
                    return False
        
        return True
    
    def execute_with_retry(self, operation: Callable, 
                           on_progress: Optional[Callable] = None,
                           on_error: Optional[Callable] = None) -> any:
        """
        带自动重试的执行器
        
        Args:
            operation: 要执行的操作函数，返回 True/False 表示成功/失败
            on_progress: 进度回调
            on_error: 错误回调
        
        Returns:
            operation 的返回值，或 None（如果全部重试失败）
        """
        attempt = 0
        last_error = None
        
        while True:
            try:
                debug_log(f"重试策略: 第 {attempt + 1} 次尝试",
                          level="DEBUG", module="retry")
                result = operation()
                if result:
                    if attempt > 0:
                        debug_log(f"重试策略: 第 {attempt + 1} 次尝试成功",
                                  level="INFO", module="retry")
                    return result
                
                last_error = "操作返回失败"
                
            except Exception as e:
                last_error = str(e)
                debug_log(f"重试策略: 第 {attempt + 1} 次尝试失败: {e}",
                          level="WARNING", module="retry")
            
            # 检查是否应该重试
            if not self.should_retry(attempt):
                debug_log(f"重试策略: 已达到最大重试次数 ({self.max_attempts})，放弃",
                          level="ERROR", module="retry")
                if on_error:
                    on_error(last_error)
                return None
            
            # 等待后重试
            if not self.wait_before_retry(attempt, on_progress):
                return None
            
            attempt += 1


class TransferScheduler:
    """
    传输时间窗口管理器
    
    控制传输只在指定的时间窗口内进行：
    - 支持跨天的时间窗口（如 22:00 ~ 06:00）
    - 在时间窗口外自动暂停传输
    - 到达开始时间后自动恢复传输
    """
    
    def __init__(self, start_time_str: str = None, end_time_str: str = None):
        """
        Args:
            start_time_str: 开始时间（HH:MM格式）
            end_time_str: 结束时间（HH:MM格式）
        """
        self.enabled = config.SCHEDULE_ENABLED
        self.start_time = self._parse_time(start_time_str or config.SCHEDULE_START_TIME)
        self.end_time = self._parse_time(end_time_str or config.SCHEDULE_END_TIME)
        self.allow_pause = config.SCHEDULE_ALLOW_PAUSE
        self._paused = False
        self._pause_callbacks = []
        self._resume_callbacks = []
    
    def _parse_time(self, time_str: str) -> dt_time:
        """解析时间字符串"""
        try:
            parts = time_str.strip().split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except Exception:
            return dt_time(0, 0)
    
    def is_in_window(self) -> bool:
        """判断当前是否在传输时间窗口内"""
        if not self.enabled:
            return True
        
        now = datetime.now().time()
        
        if self.start_time <= self.end_time:
            # 不跨天的情况，如 09:00 ~ 18:00
            return self.start_time <= now <= self.end_time
        else:
            # 跨天的情况，如 22:00 ~ 06:00
            return now >= self.start_time or now <= self.end_time
    
    def check_and_update(self) -> bool:
        """
        检查时间窗口状态并更新
        
        Returns:
            True 表示可以继续传输，False 表示需要暂停
        """
        if not self.enabled:
            return True
        
        should_run = self.is_in_window()
        
        if should_run and self._paused:
            # 恢复传输
            self._paused = False
            debug_log(f"传输时间窗口: 进入时间窗口 {self.start_time} ~ {self.end_time}，恢复传输",
                      level="INFO", module="scheduler")
            for cb in self._resume_callbacks:
                cb()
        
        elif not should_run and not self._paused:
            # 暂停传输
            self._paused = True
            debug_log(f"传输时间窗口: 超出时间窗口 {self.start_time} ~ {self.end_time}，暂停传输",
                      level="INFO", module="scheduler")
            for cb in self._pause_callbacks:
                cb()
        
        return should_run
    
    def get_wait_time(self) -> float:
        """获取到下一个时间窗口的等待时间（秒）"""
        if not self.enabled:
            return 0
        
        now = datetime.now()
        now_time = now.time()
        
        # 计算下一个开始时间
        if self.start_time > now_time:
            # 今天还没开始
            next_start = datetime.combine(now.date(), self.start_time)
        else:
            # 今天已过期，明天开始
            from datetime import timedelta
            next_start = datetime.combine(now.date() + timedelta(days=1), self.start_time)
        
        wait_seconds = (next_start - now).total_seconds()
        return max(0, wait_seconds)
    
    def add_pause_callback(self, callback: Callable):
        """添加暂停回调"""
        self._pause_callbacks.append(callback)
    
    def add_resume_callback(self, callback: Callable):
        """添加恢复回调"""
        self._resume_callbacks.append(callback)
    
    @property
    def is_paused(self) -> bool:
        """是否处于暂停状态"""
        return self._paused


class AdaptiveChunkManager:
    """
    慢网络自适应分块管理器
    
    根据实时传输速度动态调整分块大小：
    - 速度 < 1MB/s：使用 64KB 小分块，提高成功率
    - 速度 1~10MB/s：使用 512KB 中等分块
    - 速度 > 10MB/s：使用 1MB 大分块，提高吞吐量
    
    每10秒评估一次网络状况并调整。
    """
    
    def __init__(self):
        self.enabled = config.ADAPTIVE_CHUNK_ENABLED
        self.min_chunk = config.ADAPTIVE_MIN_CHUNK        # 64KB
        self.max_chunk = config.ADAPTIVE_MAX_CHUNK        # 1MB
        self.threshold_low = config.ADAPTIVE_SPEED_THRESHOLD_LOW      # 1MB/s
        self.threshold_high = config.ADAPTIVE_SPEED_THRESHOLD_HIGH    # 10MB/s
        self.switch_interval = config.ADAPTIVE_SWITCH_INTERVAL        # 10秒
        
        self.current_chunk_size = config.CHUNK_SIZE        # 当前分块大小
        self.last_check_time = time.time()
        self.speed_history = []           # 速度历史记录
        self.history_max_size = 5         # 保存最近5个速度样本
        
    def record_speed(self, speed_bytes_per_sec: float):
        """记录传输速度样本"""
        self.speed_history.append(speed_bytes_per_sec)
        if len(self.speed_history) > self.history_max_size:
            self.speed_history.pop(0)
    
    def get_average_speed(self) -> float:
        """获取平均速度"""
        if not self.speed_history:
            return 0
        return sum(self.speed_history) / len(self.speed_history)
    
    def should_adjust(self) -> bool:
        """判断是否应该调整分块大小"""
        if not self.enabled:
            return False
        
        elapsed = time.time() - self.last_check_time
        return elapsed >= self.switch_interval and len(self.speed_history) >= 3
    
    def adjust(self):
        """调整分块大小"""
        if not self.should_adjust():
            return self.current_chunk_size
        
        avg_speed = self.get_average_speed()
        old_size = self.current_chunk_size
        
        if avg_speed < self.threshold_low:
            # 慢网络，使用小分块
            self.current_chunk_size = self.min_chunk
            debug_log(f"自适应分块: 检测到慢网络 ({avg_speed/1024:.1f}KB/s)，"
                      f"分块大小从 {old_size/1024:.0f}KB 调整为 {self.min_chunk/1024:.0f}KB",
                      level="INFO", module="adaptive")
        
        elif avg_speed > self.threshold_high:
            # 快网络，使用大分块
            self.current_chunk_size = self.max_chunk
            debug_log(f"自适应分块: 检测到快网络 ({avg_speed/1024/1024:.1f}MB/s)，"
                      f"分块大小从 {old_size/1024:.0f}KB 调整为 {self.max_chunk/1024:.0f}KB",
                      level="INFO", module="adaptive")
        
        else:
            # 中等网络，使用中等分块
            mid_chunk = (self.min_chunk + self.max_chunk) // 2
            self.current_chunk_size = mid_chunk
            debug_log(f"自适应分块: 网络速度正常 ({avg_speed/1024/1024:.1f}MB/s)，"
                      f"分块大小从 {old_size/1024:.0f}KB 调整为 {mid_chunk/1024:.0f}KB",
                      level="INFO", module="adaptive")
        
        self.last_check_time = time.time()
        self.speed_history.clear()
        
        return self.current_chunk_size
    
    def get_chunk_size(self) -> int:
        """获取当前分块大小"""
        if self.enabled:
            # 先尝试调整
            self.adjust()
        return self.current_chunk_size
    
    def get_status(self) -> dict:
        """获取当前状态信息"""
        return {
            "enabled": self.enabled,
            "current_chunk_size": self.current_chunk_size,
            "min_chunk": self.min_chunk,
            "max_chunk": self.max_chunk,
            "average_speed": self.get_average_speed(),
            "sample_count": len(self.speed_history),
            "last_check": time.time() - self.last_check_time
        }


class TransferTimeout:
    """
    传输超时管理器
    
    为单个文件传输设置独立的超时时间：
    - 根据文件大小动态计算超时时间
    - 支持手动取消
    """
    
    def __init__(self, timeout_seconds: int = None):
        self.timeout = timeout_seconds or config.RETRY_TIMEOUT_PER_FILE
        self._cancelled = False
        self._start_time = None
    
    def start(self):
        """开始计时"""
        self._start_time = time.time()
        self._cancelled = False
    
    def cancel(self):
        """取消传输"""
        self._cancelled = True
    
    def is_expired(self) -> bool:
        """检查是否已超时"""
        if self._cancelled:
            return True
        if self._start_time is None:
            return False
        elapsed = time.time() - self._start_time
        return elapsed > self.timeout
    
    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._cancelled
    
    def get_elapsed(self) -> float:
        """获取已运行时间"""
        if self._start_time is None:
            return 0
        return time.time() - self._start_time
    
    def get_remaining(self) -> float:
        """获取剩余时间"""
        return max(0, self.timeout - self.get_elapsed())
    
    def get_progress_ratio(self) -> float:
        """获取超时进度比例（0.0 ~ 1.0）"""
        if self._start_time is None:
            return 0
        return min(1.0, self.get_elapsed() / self.timeout)


# 全局实例
_retry_policy = None
_scheduler = None
_chunk_manager = None


def get_retry_policy() -> RetryPolicy:
    """获取全局重试策略实例"""
    global _retry_policy
    if _retry_policy is None:
        _retry_policy = RetryPolicy()
    return _retry_policy


def get_scheduler() -> TransferScheduler:
    """获取全局传输调度器实例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TransferScheduler()
    return _scheduler


def get_chunk_manager() -> AdaptiveChunkManager:
    """获取全局分块管理器实例"""
    global _chunk_manager
    if _chunk_manager is None:
        _chunk_manager = AdaptiveChunkManager()
    return _chunk_manager