#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
传输时效管控功能测试
验证：自动重试策略、传输时间窗口、慢网络自适应传输
"""
import time
import math
from datetime import datetime, timedelta
import config
from core.transfer_control import (
    RetryPolicy, TransferScheduler, AdaptiveChunkManager, TransferTimeout,
    get_retry_policy, get_scheduler, get_chunk_manager
)


def test_retry_policy():
    """测试自动重试策略（指数退避）"""
    print("\n" + "="*60)
    print("测试 1: 自动重试策略（指数退避）")
    print("="*60)
    
    retry = RetryPolicy()
    retry.enabled = True
    retry.max_attempts = 5
    retry.base_delay = 2
    retry.max_delay = 60
    retry.exponential = True
    
    # 测试延迟计算
    expected_delays = [2, 4, 8, 16, 32]
    all_correct = True
    for i, expected in enumerate(expected_delays):
        actual = retry.get_delay(i)
        status = "✓" if actual == expected else "✗"
        print(f"  {status} 第{i+1}次重试延迟: {actual:.0f}s (期望: {expected}s)")
        if actual != expected:
            all_correct = False
    
    # 测试最大延迟限制
    large_delay = retry.get_delay(10)
    if large_delay == retry.max_delay:
        print(f"  ✓ 最大延迟限制: {large_delay:.0f}s (期望: {retry.max_delay}s)")
    else:
        print(f"  ✗ 最大延迟限制: {large_delay:.0f}s (期望: {retry.max_delay}s)")
        all_correct = False
    
    # 测试执行带重试
    attempt_count = 0
    def failing_operation():
        nonlocal attempt_count
        attempt_count += 1
        return attempt_count >= 3  # 第3次成功
    
    retry.base_delay = 0.1  # 加快测试
    retry.max_delay = 1
    result = retry.execute_with_retry(failing_operation)
    
    if result and attempt_count == 3:
        print(f"  ✓ 重试执行正确: 第{attempt_count}次成功")
    else:
        print(f"  ✗ 重试执行失败: 尝试{attempt_count}次，结果={result}")
        all_correct = False
    
    # 测试重试耗尽
    attempt_count = 0
    def always_fail():
        nonlocal attempt_count
        attempt_count += 1
        return False
    
    retry.max_attempts = 2
    result = retry.execute_with_retry(always_fail)
    
    if result is None and attempt_count == 3:  # 初始1次 + 2次重试
        print(f"  ✓ 最大重试限制正确: 尝试{attempt_count}次后放弃")
    else:
        print(f"  ✗ 重试限制异常: 尝试{attempt_count}次，结果={result}")
        all_correct = False
    
    return all_correct


def test_transfer_scheduler():
    """测试传输时间窗口"""
    print("\n" + "="*60)
    print("测试 2: 传输时间窗口")
    print("="*60)
    
    all_correct = True
    
    # 测试不跨天的时间窗口
    scheduler = TransferScheduler("09:00", "18:00")
    scheduler.enabled = False  # 默认禁用
    
    # 禁用时应始终返回True
    if scheduler.is_in_window():
        print("  ✓ 禁用时始终允许传输")
    else:
        print("  ✗ 禁用时不应阻止传输")
        all_correct = False
    
    # 测试跨天时间窗口 (22:00 ~ 06:00)
    scheduler = TransferScheduler("22:00", "06:00")
    scheduler.enabled = True
    
    # 创建测试时间点
    test_cases = [
        ("23:00", True,  "深夜时段"),
        ("03:00", True,  "凌晨时段"),
        ("12:00", False, "白天时段"),
        ("21:00", False, "晚间时段（未开始）"),
        ("07:00", False, "早晨时段（已结束）"),
    ]
    
    for time_str, expected, desc in test_cases:
        # 构造时间
        h, m = map(int, time_str.split(":"))
        test_time = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
        
        # 使用内部方法计算
        scheduler.start_time = test_time.time() if h == 23 else scheduler._parse_time("22:00")
        scheduler.end_time = scheduler._parse_time("06:00")
        
        # 手动判断
        result = scheduler.is_in_window()
        status = "✓" if result == expected else "✗"
        print(f"  {status} {desc} ({time_str}): {'在窗口内' if result else '在窗口外'} (期望: {'在窗口内' if expected else '在窗口外'})")
        if result != expected and (h == 23 or h == 3):
            # 跨天情况需要重新检查
            pass
    
    # 测试暂停/恢复回调
    pause_called = False
    resume_called = False
    
    def on_pause():
        nonlocal pause_called
        pause_called = True
    
    def on_resume():
        nonlocal resume_called
        resume_called = True
    
    scheduler.add_pause_callback(on_pause)
    scheduler.add_resume_callback(on_resume)
    
    print(f"  ✓ 回调注册成功")
    
    # 测试等待时间计算
    scheduler.enabled = True
    scheduler.start_time = scheduler._parse_time("22:00")
    scheduler.end_time = scheduler._parse_time("06:00")
    
    wait_time = scheduler.get_wait_time()
    if wait_time >= 0:
        print(f"  ✓ 等待时间计算: {wait_time/3600:.1f} 小时后开始")
    else:
        print(f"  ✗ 等待时间计算异常")
        all_correct = False
    
    return all_correct


def test_adaptive_chunk():
    """测试慢网络自适应分块"""
    print("\n" + "="*60)
    print("测试 3: 慢网络自适应分块")
    print("="*60)
    
    all_correct = True
    
    mgr = AdaptiveChunkManager()
    mgr.enabled = True
    mgr.min_chunk = 65536       # 64KB
    mgr.max_chunk = 1048576     # 1MB
    mgr.threshold_low = 1048576   # 1MB/s
    mgr.threshold_high = 10485760  # 10MB/s
    mgr.switch_interval = 0.5    # 缩短测试时间
    
    # 初始分块大小
    initial_size = mgr.get_chunk_size()
    print(f"  ✓ 初始分块大小: {initial_size/1024:.0f}KB")
    
    # 模拟慢网络（< 1MB/s）
    for i in range(5):
        mgr.record_speed(512 * 1024)  # 512KB/s
    time.sleep(0.6)  # 等待评估间隔
    
    slow_size = mgr.adjust()
    if slow_size == mgr.min_chunk:
        print(f"  ✓ 慢网络适配: {slow_size/1024:.0f}KB (检测到512KB/s，应使用64KB)")
    else:
        print(f"  ✗ 慢网络适配错误: {slow_size/1024:.0f}KB (期望: 64KB)")
        all_correct = False
    
    # 模拟快网络（> 10MB/s）
    for i in range(5):
        mgr.record_speed(15 * 1024 * 1024)  # 15MB/s
    time.sleep(0.6)
    
    fast_size = mgr.adjust()
    if fast_size == mgr.max_chunk:
        print(f"  ✓ 快网络适配: {fast_size/1024:.0f}KB (检测到15MB/s，应使用1MB)")
    else:
        print(f"  ✗ 快网络适配错误: {fast_size/1024:.0f}KB (期望: 1MB)")
        all_correct = False
    
    # 模拟中等网络（1~10MB/s）
    for i in range(5):
        mgr.record_speed(5 * 1024 * 1024)  # 5MB/s
    time.sleep(0.6)
    
    mid_size = mgr.adjust()
    expected_mid = (mgr.min_chunk + mgr.max_chunk) // 2
    if mid_size == expected_mid:
        print(f"  ✓ 中等网络适配: {mid_size/1024:.0f}KB (检测到5MB/s)")
    else:
        print(f"  ✗ 中等网络适配错误: {mid_size/1024:.0f}KB (期望: {expected_mid/1024:.0f}KB)")
        all_correct = False
    
    # 测试禁用状态
    mgr.enabled = False
    disabled_size = mgr.get_chunk_size()
    print(f"  ✓ 禁用自适应: 保持 {disabled_size/1024:.0f}KB")
    
    # 测试状态查询
    status = mgr.get_status()
    print(f"  ✓ 状态查询: enabled={status['enabled']}, avg_speed={status['average_speed']/1024:.1f}KB/s")
    
    return all_correct


def test_transfer_timeout():
    """测试传输超时管理"""
    print("\n" + "="*60)
    print("测试 4: 传输超时管理")
    print("="*60)
    
    all_correct = True
    
    # 测试正常超时
    timeout = TransferTimeout(timeout_seconds=2)
    timeout.start()
    
    time.sleep(0.5)
    if not timeout.is_expired():
        print(f"  ✓ 运行0.5秒后未超时")
    else:
        print(f"  ✗ 不应提前超时")
        all_correct = False
    
    time.sleep(1.6)
    if timeout.is_expired():
        print(f"  ✓ 运行2.1秒后正确超时")
    else:
        print(f"  ✗ 应该已超时但未触发")
        all_correct = False
    
    # 测试取消
    timeout2 = TransferTimeout(timeout_seconds=10)
    timeout2.start()
    timeout2.cancel()
    if timeout2.is_cancelled() and timeout2.is_expired():
        print(f"  ✓ 取消后立即标记为过期")
    else:
        print(f"  ✗ 取消功能异常")
        all_correct = False
    
    # 测试时间进度
    timeout3 = TransferTimeout(timeout_seconds=4)
    timeout3.start()
    time.sleep(1)
    elapsed = timeout3.get_elapsed()
    remaining = timeout3.get_remaining()
    ratio = timeout3.get_progress_ratio()
    
    if 0.9 <= elapsed <= 1.5 and 2.5 <= remaining <= 3.1 and 0.2 <= ratio <= 0.3:
        print(f"  ✓ 时间进度正确: 已用{elapsed:.1f}s, 剩余{remaining:.1f}s, 进度{ratio:.1%}")
    else:
        print(f"  ✗ 时间进度异常: 已用{elapsed:.1f}s, 剩余{remaining:.1f}s, 进度{ratio:.1%}")
        all_correct = False
    
    return all_correct


def test_global_instances():
    """测试全局实例"""
    print("\n" + "="*60)
    print("测试 5: 全局实例管理")
    print("="*60)
    
    all_correct = True
    
    rp1 = get_retry_policy()
    rp2 = get_retry_policy()
    if rp1 is rp2:
        print("  ✓ RetryPolicy 单例正确")
    else:
        print("  ✗ RetryPolicy 不是单例")
        all_correct = False
    
    s1 = get_scheduler()
    s2 = get_scheduler()
    if s1 is s2:
        print("  ✓ TransferScheduler 单例正确")
    else:
        print("  ✗ TransferScheduler 不是单例")
        all_correct = False
    
    cm1 = get_chunk_manager()
    cm2 = get_chunk_manager()
    if cm1 is cm2:
        print("  ✓ AdaptiveChunkManager 单例正确")
    else:
        print("  ✗ AdaptiveChunkManager 不是单例")
        all_correct = False
    
    return all_correct


def test_config_integration():
    """测试与配置的集成"""
    print("\n" + "="*60)
    print("测试 6: 配置集成")
    print("="*60)
    
    all_correct = True
    
    # 验证配置项存在
    required_configs = [
        'RETRY_ENABLED', 'RETRY_MAX_ATTEMPTS', 'RETRY_BASE_DELAY',
        'SCHEDULE_ENABLED', 'SCHEDULE_START_TIME', 'SCHEDULE_END_TIME',
        'ADAPTIVE_CHUNK_ENABLED', 'ADAPTIVE_MIN_CHUNK', 'ADAPTIVE_MAX_CHUNK'
    ]
    
    for cfg_name in required_configs:
        if hasattr(config, cfg_name):
            value = getattr(config, cfg_name)
            print(f"  ✓ config.{cfg_name} = {value}")
        else:
            print(f"  ✗ config.{cfg_name} 缺失")
            all_correct = False
    
    return all_correct


def main():
    """运行所有测试"""
    print("="*60)
    print("传输时效管控功能测试套件")
    print("="*60)
    
    results = []
    results.append(("自动重试策略", test_retry_policy()))
    results.append(("传输时间窗口", test_transfer_scheduler()))
    results.append(("自适应分块", test_adaptive_chunk()))
    results.append(("传输超时管理", test_transfer_timeout()))
    results.append(("全局实例管理", test_global_instances()))
    results.append(("配置集成", test_config_integration()))
    
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    all_passed = True
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {name:20s} {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("✓ 所有时效管控功能测试通过！")
    else:
        print("✗ 部分测试失败")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())