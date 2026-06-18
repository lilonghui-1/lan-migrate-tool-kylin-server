"""
远程目录浏览器
用于可视化浏览麒麟/Linux系统的远程目录结构
支持双向传输：上传文件到远程 / 从远程下载文件到本地
"""
import os
import time
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QLineEdit, QMessageBox,
    QDialog, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QMenu, QAbstractItemView, QProgressBar,
    QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor, QIcon

from core.protocol import (
    Command, pack_message, unpack_message,
    create_list_dir_payload, create_remote_path_info_payload
)
from utils.helpers import format_size


class RemoteFileEntry:
    """远程文件/目录条目"""
    def __init__(self, data: dict):
        self.name = data.get("name", "")
        self.path = data.get("path", "")
        self.entry_type = data.get("type", "file")  # directory 或 file
        self.size = data.get("size", 0)
        self.modified = data.get("modified", 0)
    
    def is_dir(self):
        return self.entry_type == "directory"
    
    def modified_str(self):
        try:
            return datetime.fromtimestamp(self.modified).strftime("%Y-%m-%d %H:%M")
        except:
            return "--"


class RemoteDirWorker(QThread):
    """远程目录加载工作线程"""
    
    dir_loaded = pyqtSignal(str, list)  # path, entries
    error = pyqtSignal(str)
    
    def __init__(self, socket_conn, path: str):
        super().__init__()
        self.socket_conn = socket_conn
        self.path = path
        self.buffer = b""
    
    def run(self):
        try:
            # 发送列出目录请求
            request = pack_message(Command.LIST_DIR, create_list_dir_payload(self.path))
            self.socket_conn.sendall(request)
            
            # 等待响应
            start_time = time.time()
            while time.time() - start_time < 10:
                data = self.socket_conn.recv(65536)
                if not data:
                    break
                
                self.buffer += data
                
                while len(self.buffer) >= 8:
                    cmd, payload, remaining = unpack_message(self.buffer)
                    if cmd is None:
                        break
                    
                    self.buffer = remaining
                    
                    if cmd == Command.LIST_DIR_RESPONSE:
                        path = payload.get("path", "")
                        entries_data = payload.get("entries", [])
                        entries = [RemoteFileEntry(e) for e in entries_data]
                        self.dir_loaded.emit(path, entries)
                        return
                    elif cmd == Command.ERROR:
                        self.error.emit(payload.get("message", "未知错误"))
                        return
            
            self.error.emit("请求超时")
            
        except Exception as e:
            self.error.emit(str(e))


class RemoteBrowserDialog(QDialog):
    """
    远程目录浏览器对话框
    
    可视化浏览麒麟/Linux远程目录，支持：
    - 浏览远程目录树
    - 查看文件详情（大小、修改时间）
    - 选择远程保存路径
    - 从远程下载文件到本地
    """
    
    path_selected = pyqtSignal(str)  # 用户选择了路径
    files_to_download = pyqtSignal(list)  # 用户选择下载的文件列表 [{remote_path, local_dir}]
    
    def __init__(self, socket_conn, mode="select_path", parent=None):
        """
        Args:
            socket_conn: 已连接的socket
            mode: "select_path" - 选择保存路径, "browse" - 浏览并下载
        """
        super().__init__(parent)
        self.socket_conn = socket_conn
        self.mode = mode
        self.current_path = ""
        self.entries = []
        self.selected_path = ""
        
        self.setWindowTitle("远程目录浏览器 - 麒麟/Linux系统")
        self.resize(900, 600)
        self.setup_ui()
        
        # 加载家目录
        self.load_directory("")
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # 标题
        title = QLabel("麒麟/Linux 远程目录管理")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 路径导航栏
        nav_layout = QHBoxLayout()
        
        self.back_btn = QPushButton("返回上级")
        self.back_btn.setStyleSheet("""
            QPushButton {
                background: #607D8B;
                color: white;
                padding: 5px 15px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #546E7A;
            }
        """)
        self.back_btn.clicked.connect(self.go_up)
        nav_layout.addWidget(self.back_btn)
        
        nav_layout.addWidget(QLabel("当前路径:"))
        
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setStyleSheet("""
            QLineEdit {
                background: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 3px;
                padding: 5px;
                font-family: Consolas, monospace;
            }
        """)
        nav_layout.addWidget(self.path_edit, 1)
        
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: #2196F3;
                color: white;
                padding: 5px 15px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #1976D2;
            }
        """)
        self.refresh_btn.clicked.connect(self.refresh_current)
        nav_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(nav_layout)
        
        # 文件列表
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(4)
        self.file_table.setHorizontalHeaderLabels(["名称", "类型", "大小", "修改时间"])
        self.file_table.setColumnWidth(0, 350)
        self.file_table.setColumnWidth(1, 100)
        self.file_table.setColumnWidth(2, 120)
        self.file_table.setColumnWidth(3, 150)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_table.setAlternatingRowColors(True)
        self.file_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #ddd;
                border-radius: 5px;
                background: white;
                alternate-background-color: #f9f9f9;
            }
            QTableWidget::item {
                padding: 8px;
                color: #333;
            }
            QTableWidget::item:selected {
                background: #e3f2fd;
                color: #1976D2;
            }
            QHeaderView::section {
                background: #f5f5f5;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #ddd;
                font-weight: bold;
            }
        """)
        self.file_table.doubleClicked.connect(self.on_item_double_clicked)
        self.file_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_table.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.file_table)
        
        # 状态栏
        self.status_label = QLabel("正在加载...")
        self.status_label.setStyleSheet("color: #666;")
        layout.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 不确定模式
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        
        self.home_btn = QPushButton("家目录")
        self.home_btn.setStyleSheet("""
            QPushButton {
                background: #9C27B0;
                color: white;
                padding: 8px 20px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #7B1FA2;
            }
        """)
        self.home_btn.clicked.connect(lambda: self.load_directory(""))
        btn_layout.addWidget(self.home_btn)
        
        btn_layout.addStretch()
        
        if self.mode == "select_path":
            self.select_btn = QPushButton("选择此目录")
            self.select_btn.setStyleSheet("""
                QPushButton {
                    background: #4CAF50;
                    color: white;
                    padding: 8px 25px;
                    border: none;
                    border-radius: 3px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #45a049;
                }
            """)
            self.select_btn.clicked.connect(self.on_select_path)
            btn_layout.addWidget(self.select_btn)
        else:
            self.download_btn = QPushButton("下载选中文件")
            self.download_btn.setStyleSheet("""
                QPushButton {
                    background: #FF9800;
                    color: white;
                    padding: 8px 25px;
                    border: none;
                    border-radius: 3px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #F57C00;
                }
            """)
            self.download_btn.clicked.connect(self.on_download)
            btn_layout.addWidget(self.download_btn)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #f44336;
                color: white;
                padding: 8px 25px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #d32f2f;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def load_directory(self, path: str):
        """加载远程目录"""
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"正在加载: {path or '家目录'}...")
        self.file_table.setEnabled(False)
        
        # 使用工作线程加载
        self.worker = RemoteDirWorker(self.socket_conn, path)
        self.worker.dir_loaded.connect(self.on_dir_loaded)
        self.worker.error.connect(self.on_load_error)
        self.worker.finished.connect(lambda: self.file_table.setEnabled(True))
        self.worker.start()
    
    def on_dir_loaded(self, path: str, entries: list):
        """目录加载完成"""
        self.current_path = path
        self.entries = entries
        self.path_edit.setText(path or "~")
        
        # 清空表格
        self.file_table.setRowCount(0)
        
        # 添加条目
        for entry in entries:
            row = self.file_table.rowCount()
            self.file_table.insertRow(row)
            
            # 名称
            name_item = QTableWidgetItem(entry.name)
            if entry.is_dir():
                name_item.setForeground(QColor("#1976D2"))
                name_item.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
            self.file_table.setItem(row, 0, name_item)
            
            # 类型
            type_text = "目录" if entry.is_dir() else "文件"
            type_item = QTableWidgetItem(type_text)
            self.file_table.setItem(row, 1, type_item)
            
            # 大小
            size_text = "" if entry.is_dir() else format_size(entry.size)
            size_item = QTableWidgetItem(size_text)
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.file_table.setItem(row, 2, size_item)
            
            # 修改时间
            time_item = QTableWidgetItem(entry.modified_str())
            self.file_table.setItem(row, 3, time_item)
        
        self.status_label.setText(f"共 {len(entries)} 项")
        self.progress_bar.setVisible(False)
    
    def on_load_error(self, error_msg: str):
        """加载错误"""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"加载失败: {error_msg}")
        QMessageBox.warning(self, "加载失败", f"无法加载远程目录:\n{error_msg}")
    
    def on_item_double_clicked(self, index):
        """双击条目"""
        row = index.row()
        if row < 0 or row >= len(self.entries):
            return
        
        entry = self.entries[row]
        if entry.is_dir():
            self.load_directory(entry.path)
    
    def go_up(self):
        """返回上级目录"""
        if not self.current_path:
            return
        
        parent = os.path.dirname(self.current_path)
        if parent and parent != self.current_path:
            self.load_directory(parent)
        else:
            self.load_directory("")
    
    def refresh_current(self):
        """刷新当前目录"""
        self.load_directory(self.current_path)
    
    def show_context_menu(self, position):
        """显示右键菜单"""
        menu = QMenu(self)
        
        open_action = menu.addAction("打开")
        download_action = menu.addAction("下载到本地...")
        menu.addSeparator()
        refresh_action = menu.addAction("刷新")
        
        action = menu.exec(self.file_table.viewport().mapToGlobal(position))
        
        if action == open_action:
            self.on_item_double_clicked(self.file_table.currentIndex())
        elif action == download_action:
            self.on_download()
        elif action == refresh_action:
            self.refresh_current()
    
    def on_select_path(self):
        """选择当前路径"""
        self.selected_path = self.current_path
        self.path_selected.emit(self.selected_path)
        self.accept()
    
    def on_download(self):
        """下载选中的文件"""
        selected_rows = set(idx.row() for idx in self.file_table.selectedIndexes())
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要下载的文件")
            return
        
        # 选择本地保存目录
        local_dir = QFileDialog.getExistingDirectory(self, "选择保存目录", os.path.expanduser("~"))
        if not local_dir:
            return
        
        files_to_download = []
        for row in selected_rows:
            if row < 0 or row >= len(self.entries):
                continue
            entry = self.entries[row]
            if not entry.is_dir():
                files_to_download.append({
                    "remote_path": entry.path,
                    "local_dir": local_dir
                })
        
        if files_to_download:
            self.files_to_download.emit(files_to_download)
            QMessageBox.information(
                self,
                "下载任务已创建",
                f"已添加 {len(files_to_download)} 个文件到下载队列\n"
                f"保存位置: {local_dir}"
            )
    
    def get_selected_path(self):
        """获取用户选择的路径"""
        return self.selected_path


class RemoteTransferWidget(QWidget):
    """
    远程传输主控件
    
    集成到主窗口的远程传输页面
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.socket_conn = None
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # 标题
        title = QLabel("麒麟/Linux 远程文件传输")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 说明
        desc = QLabel("连接到麒麟/Linux系统后，可以双向传输文件并可视化浏览远程目录")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #666;")
        layout.addWidget(desc)
        
        # 操作按钮区
        btn_layout = QHBoxLayout()
        
        self.browse_btn = QPushButton("浏览远程目录")
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background: #2196F3;
                color: white;
                padding: 10px 30px;
                border: none;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #1976D2;
            }
        """)
        self.browse_btn.clicked.connect(self.open_remote_browser)
        btn_layout.addWidget(self.browse_btn)
        
        self.upload_btn = QPushButton("上传文件到远程")
        self.upload_btn.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                padding: 10px 30px;
                border: none;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #45a049;
            }
        """)
        self.upload_btn.clicked.connect(self.upload_to_remote)
        btn_layout.addWidget(self.upload_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # 提示信息
        tip = QLabel("""
<b>使用说明：</b><br>
1. 在<b>发现设备</b>页面连接到麒麟/Linux系统<br>
2. 点击<b>浏览远程目录</b>查看远程文件系统<br>
3. 点击<b>上传文件到远程</b>将本地文件发送到麒麟系统<br>
4. 在远程目录浏览器中可以下载文件到本地<br>
        """)
        tip.setStyleSheet("""
            QLabel {
                background: #fff3e0;
                border: 1px solid #ffe0b2;
                border-radius: 5px;
                padding: 15px;
                color: #e65100;
            }
        """)
        layout.addWidget(tip)
        
        layout.addStretch()
    
    def set_connection(self, socket_conn):
        """设置连接"""
        self.socket_conn = socket_conn
        self.browse_btn.setEnabled(socket_conn is not None)
        self.upload_btn.setEnabled(socket_conn is not None)
    
    def open_remote_browser(self):
        """打开远程目录浏览器"""
        if not self.socket_conn:
            QMessageBox.warning(self, "未连接", "请先连接到麒麟/Linux系统")
            return
        
        dialog = RemoteBrowserDialog(self.socket_conn, mode="browse", parent=self)
        dialog.files_to_download.connect(self.on_files_to_download)
        dialog.exec()
    
    def upload_to_remote(self):
        """上传文件到远程"""
        if not self.socket_conn:
            QMessageBox.warning(self, "未连接", "请先连接到麒麟/Linux系统")
            return
        
        # 选择本地文件
        files, _ = QFileDialog.getOpenFileNames(self, "选择要上传的文件", os.path.expanduser("~"))
        if not files:
            return
        
        # 选择远程保存目录
        dialog = RemoteBrowserDialog(self.socket_conn, mode="select_path", parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            remote_dir = dialog.get_selected_path()
            if remote_dir:
                # 这里可以触发实际上传逻辑
                QMessageBox.information(
                    self,
                    "上传任务",
                    f"已选择 {len(files)} 个文件\n"
                    f"远程保存位置: {remote_dir or '家目录'}\n\n"
                    f"（实际传输逻辑需要在 TransferManager 中实现）"
                )
    
    def on_files_to_download(self, files: list):
        """处理下载请求"""
        # 这里可以触发实际下载逻辑
        print(f"待下载文件: {files}")
