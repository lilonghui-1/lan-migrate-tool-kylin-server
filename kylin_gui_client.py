#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麒麟桌面版 GUI 客户端启动脚本
适用于麒麟桌面版、Ubuntu、Deepin 等 Linux 发行版
"""
import os
import sys

# 确保使用 PyQt6
try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
except ImportError:
    print("[ERROR] 未安装 PyQt6，请先安装:")
    print("        pip3 install PyQt6")
    sys.exit(1)

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from gui.main_window import MainWindow


def main():
    """启动麒麟 GUI 客户端"""
    # 设置高 DPI 支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.VERSION)
    
    # 设置样式（Linux 适配）
    app.setStyle("Fusion")
    
    # 创建主窗口
    window = MainWindow()
    window.setWindowTitle(f"{config.APP_NAME} - 麒麟桌面版")
    window.show()
    
    print(f"[INFO] {config.APP_NAME} 麒麟桌面版启动成功")
    print(f"[INFO] 版本: {config.VERSION}")
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == "__main__":
    main()