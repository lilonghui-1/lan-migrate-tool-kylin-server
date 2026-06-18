"""
传输进度页面
"""
import os
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTextEdit, QGroupBox, QMessageBox, QScrollArea, 
    QFrame, QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon

from utils.helpers import format_size, format_speed, format_time


class TransferPage(QWidget):
    """传输进度页面"""
    
    transfer_finished = pyqtSignal(dict)
    back_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    retry_failed_requested = pyqtSignal(list)
    progress_updated = pyqtSignal(dict)
    file_sent = pyqtSignal(int, str)
    log_message = pyqtSignal(str)
    parallel_status = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.setup_connections()
        
        self.start_time = 0
        self.total_bytes = 0
        self.transferred_bytes = 0
        self.current_file_bytes = 0
        self.current_file_total = 0
        self.total_files = 0
        self.completed_files = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_elapsed_time)
        
        self.parallel_files = {}
        self.parallel_widgets = {}
        self.failed_files = []
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        title = QLabel("数据传输中")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        top_stats = QHBoxLayout()
        
        self.file_count_label = QLabel("文件: 0 / 0")
        self.file_count_label.setStyleSheet("font-size: 13px; color: #666;")
        top_stats.addWidget(self.file_count_label)
        
        top_stats.addStretch()
        
        self.speed_label = QLabel("速度: --")
        self.speed_label.setStyleSheet("font-size: 13px; color: #2196F3; font-weight: bold;")
        top_stats.addWidget(self.speed_label)
        
        top_stats.addStretch()
        
        self.time_label = QLabel("已用: 0秒 | 剩余: --")
        self.time_label.setStyleSheet("font-size: 13px; color: #666;")
        top_stats.addWidget(self.time_label)
        
        layout.addLayout(top_stats)
        
        self.total_progress = QProgressBar()
        self.total_progress.setRange(0, 100)
        self.total_progress.setTextVisible(True)
        self.total_progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #ddd;
                border-radius: 8px;
                text-align: center;
                height: 35px;
                font-size: 14px;
                font-weight: bold;
                color: #333;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #4CAF50, stop: 1 #45a049);
                border-radius: 6px;
            }
        """)
        layout.addWidget(self.total_progress)
        
        progress_details = QHBoxLayout()
        
        self.current_file_label = QLabel("准备中...")
        self.current_file_label.setWordWrap(True)
        self.current_file_label.setStyleSheet("font-size: 12px; color: #333;")
        progress_details.addWidget(self.current_file_label)
        
        progress_details.addStretch()
        
        self.size_label = QLabel("0 B / 0 B")
        self.size_label.setStyleSheet("font-size: 12px; color: #666;")
        progress_details.addWidget(self.size_label)
        
        layout.addLayout(progress_details)
        
        self.file_progress = QProgressBar()
        self.file_progress.setRange(0, 100)
        self.file_progress.setTextVisible(False)
        self.file_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: center;
                height: 15px;
            }
            QProgressBar::chunk {
                background: #2196F3;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.file_progress)
        
        content_splitter = QHBoxLayout()
        
        left_panel = QGroupBox("传输日志")
        left_layout = QVBoxLayout(left_panel)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 5px;
                background: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
                padding: 5px;
            }
        """)
        left_layout.addWidget(self.log_text)
        self.max_log_lines = 500
        
        content_splitter.addWidget(left_panel, 1)
        
        right_panel = QGroupBox("失败文件")
        right_layout = QVBoxLayout(right_panel)
        
        self.failed_tree = QTreeWidget()
        self.failed_tree.setHeaderLabel("文件名")
        self.failed_tree.setColumnWidth(0, 200)
        self.failed_tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #ddd;
                border-radius: 5px;
                background: white;
            }
            QTreeWidget::item {
                padding: 4px;
                color: #333;
            }
            QTreeWidget::item:hover {
                background: #f5f5f5;
            }
        """)
        right_layout.addWidget(self.failed_tree)
        
        self.retry_btn = QPushButton("重新传输失败文件")
        self.retry_btn.setStyleSheet("""
            QPushButton {
                background: #FF9800;
                color: white;
                padding: 6px 15px;
                border: none;
                border-radius: 3px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #F57C00;
            }
            QPushButton:disabled {
                background: #ccc;
            }
        """)
        self.retry_btn.setEnabled(False)
        right_layout.addWidget(self.retry_btn)
        
        content_splitter.addWidget(right_panel, 1)
        
        layout.addLayout(content_splitter)
        
        btn_layout = QHBoxLayout()
        
        self.back_btn = QPushButton("返回")
        self.back_btn.setStyleSheet("""
            QPushButton {
                background: #9E9E9E;
                color: white;
                padding: 10px 25px;
                border: none;
                border-radius: 5px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #757575;
            }
        """)
        btn_layout.addWidget(self.back_btn)
        
        btn_layout.addStretch()
        
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background: #FF9800;
                color: white;
                padding: 10px 30px;
                border: none;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #F57C00;
            }
        """)
        btn_layout.addWidget(self.pause_btn)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: #f44336;
                color: white;
                padding: 10px 30px;
                border: none;
                border-radius: 5px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #d32f2f;
            }
        """)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def setup_connections(self):
        """设置信号连接"""
        self.back_btn.clicked.connect(self.on_back)
        self.pause_btn.clicked.connect(self.on_pause_resume)
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.retry_btn.clicked.connect(self.on_retry_failed)
        self.progress_updated.connect(self.update_progress)
        self.file_sent.connect(self.on_file_sent)
        self.log_message.connect(self.log)
        self.parallel_status.connect(self.update_parallel_status)
    
    def start_transfer(self, total_items: int, total_size: int):
        """开始传输"""
        self.start_time = time.time()
        self.total_bytes = total_size
        self.transferred_bytes = 0
        self.current_file_bytes = 0
        self.current_file_total = 0
        self.total_files = total_items
        self.completed_files = 0
        self.failed_files = []
        
        self.total_progress.setValue(0)
        self.file_progress.setValue(0)
        self.current_file_label.setText("准备中...")
        self.file_count_label.setText(f"文件: 0 / {total_items}")
        self.size_label.setText(f"0 B / {format_size(total_size)}")
        
        self.log_text.clear()
        self.failed_tree.clear()
        self.retry_btn.setEnabled(False)
        
        self.log("传输开始")
        self.log(f"总计 {total_items} 项, {format_size(total_size)}")
        
        self.timer.start(1000)
    
    def update_progress(self, data: dict):
        """更新进度"""
        status = data.get("status", "")
        if status == "connected":
            client = data.get("client", "")
            message = data.get("message", "")
            self.current_file_label.setText(message)
            self.log(f"连接建立: {client}")
            return
        
        if status == "transfer_start":
            total_count = data.get("total_count", 0)
            total_size = data.get("total_size", 0)
            
            self.total_bytes = total_size
            self.transferred_bytes = 0
            
            self.log(f"传输开始")
            self.log(f"总计 {total_count} 项, {format_size(total_size)}")
            return
        
        file_path = data.get("file_path", "")
        progress = data.get("progress", 0)
        sent = data.get("sent", 0)
        total = data.get("total", 0)
        speed = data.get("speed", 0)
        
        if file_path:
            self.current_file_label.setText(f"正在传输: {os.path.basename(file_path)}")
        self.file_progress.setValue(progress)
        
        if speed > 0:
            self.speed_label.setText(f"速度: {format_speed(speed)}")
        
        if total > 0:
            self.current_file_bytes = sent
            self.current_file_total = total
            
            transferred_display = format_size(self.transferred_bytes + sent)
            total_display = format_size(self.total_bytes)
            self.size_label.setText(f"{transferred_display} / {total_display}")
            
            if self.total_bytes > 0:
                total_progress = int(
                    (self.transferred_bytes + sent) / self.total_bytes * 100
                )
                self.total_progress.setValue(min(total_progress, 100))
    
    def on_file_sent(self, file_size: int, file_path: str):
        """文件发送完成"""
        self.transferred_bytes += file_size
        self.completed_files += 1
        
        self.file_count_label.setText(f"文件: {self.completed_files} / {self.total_files}")
        
        transferred_display = format_size(self.transferred_bytes)
        total_display = format_size(self.total_bytes)
        self.size_label.setText(f"{transferred_display} / {total_display}")
        
        self.log(f"✓ 完成: {os.path.basename(file_path)}")
        
        if self.total_bytes > 0:
            total_progress = int(self.transferred_bytes / self.total_bytes * 100)
            self.total_progress.setValue(min(total_progress, 100))
    
    def add_failed_file(self, file_path: str):
        """添加失败文件到列表"""
        if file_path not in self.failed_files:
            self.failed_files.append(file_path)
            
            item = QTreeWidgetItem(self.failed_tree)
            item.setText(0, os.path.basename(file_path))
            item.setData(0, Qt.ItemDataRole.UserRole, file_path)
            
            self.log(f"✗ 失败: {file_path}")
            
            if self.failed_files:
                self.retry_btn.setEnabled(True)
    
    def file_completed(self, file_path: str, success: bool):
        """文件传输完成"""
        if success:
            self.transferred_bytes += self.current_file_total
            self.completed_files += 1
            self.log(f"✓ 完成: {file_path}")
        else:
            self.add_failed_file(file_path)
        
        self.current_file_bytes = 0
        self.current_file_total = 0
    
    def update_elapsed_time(self):
        """更新已用时间"""
        elapsed = int(time.time() - self.start_time)
        
        if self.transferred_bytes > 0 and self.total_bytes > 0:
            speed = self.transferred_bytes / elapsed if elapsed > 0 else 0
            remaining_bytes = self.total_bytes - self.transferred_bytes
            if speed > 0:
                remaining = int(remaining_bytes / speed)
                self.time_label.setText(
                    f"已用: {format_time(elapsed)} | 剩余: {format_time(remaining)}"
                )
            else:
                self.time_label.setText(f"已用: {format_time(elapsed)} | 剩余: --")
        else:
            self.time_label.setText(f"已用: {format_time(elapsed)} | 剩余: --")
    
    def log(self, message: str):
        """添加日志"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
        
        block_count = self.log_text.document().blockCount()
        if block_count > self.max_log_lines:
            cursor.setPosition(0)
            cursor.movePosition(cursor.MoveOperation.NextBlock, cursor.MoveMode.KeepAnchor, block_count - self.max_log_lines)
            cursor.removeSelectedText()
    
    def on_back(self):
        """返回按钮"""
        self.back_requested.emit()
    
    def on_pause_resume(self):
        """暂停/继续按钮"""
        if self.pause_btn.text() == "暂停":
            self.pause_btn.setText("继续")
            self.log("传输已暂停")
            self.pause_requested.emit()
        else:
            self.pause_btn.setText("暂停")
            self.log("传输已继续")
            self.resume_requested.emit()
    
    def on_cancel(self):
        """取消按钮"""
        reply = QMessageBox.question(
            self,
            "确认取消",
            "确定要取消传输吗？已传输的数据将保留。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.log("用户取消传输")
            self.cancel_requested.emit()
            self.timer.stop()
    
    def on_retry_failed(self):
        """重新传输失败文件"""
        if self.failed_files:
            reply = QMessageBox.question(
                self,
                "重新传输",
                f"确定要重新传输 {len(self.failed_files)} 个失败的文件吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.retry_failed_requested.emit(self.failed_files.copy())
    
    def update_parallel_status(self, data: dict):
        """更新并行传输文件状态"""
        file_path = data.get("file_path", "")
        progress = data.get("progress", 0)
        status = data.get("status", "")
        speed = data.get("speed", 0)
        
        if not file_path:
            return
        
        self.parallel_files[file_path] = {
            'progress': progress,
            'status': status,
            'speed': speed
        }
        
        if status == "failed":
            self.add_failed_file(file_path)
        
        if status == "completed" or status == "failed":
            if file_path in self.parallel_widgets:
                widgets = self.parallel_widgets[file_path]
                self.parallel_layout.removeWidget(widgets['frame'])
                widgets['frame'].deleteLater()
                del self.parallel_widgets[file_path]
            del self.parallel_files[file_path]
    
    def transfer_complete(self, results: dict):
        """传输完成"""
        self.timer.stop()
        
        success = results.get("success", 0)
        failed = results.get("failed", 0)
        total_size = results.get("transferred_size", 0)
        failed_files = results.get("failed_files", [])
        elapsed = int(time.time() - self.start_time)
        
        for file_path in failed_files:
            self.add_failed_file(file_path)
        
        self.log("-" * 40)
        self.log("传输完成!")
        self.log(f"成功: {success} 项")
        self.log(f"失败: {failed} 项")
        self.log(f"总计: {format_size(total_size)}")
        self.log(f"用时: {format_time(elapsed)}")
        
        self.total_progress.setValue(100)
        self.file_progress.setValue(100)
        self.current_file_label.setText("传输完成!")
        self.speed_label.setText("速度: --")
        self.file_count_label.setText(f"文件: {success + failed} / {success + failed}")
        self.size_label.setText(f"{format_size(total_size)} / {format_size(total_size)}")
        
        complete_msg = (
            f"传输已完成!\n\n"
            f"成功: {success} 项\n"
            f"失败: {failed} 项\n"
            f"总计: {format_size(total_size)}\n"
            f"用时: {format_time(elapsed)}"
        )
        
        if failed_files:
            complete_msg += f"\n\n失败文件列表 ({len(failed_files)} 个):"
            for i, failed_file in enumerate(failed_files[:10]):
                complete_msg += f"\n  {os.path.basename(failed_file)}"
            if len(failed_files) > 10:
                complete_msg += f"\n  ... 还有 {len(failed_files) - 10} 个文件"
            complete_msg += "\n\n可点击'重新传输失败文件'按钮进行重试"
        
        QMessageBox.information(self, "传输完成", complete_msg)
        
        self.transfer_finished.emit(results)
    
    def showEvent(self, event):
        """页面显示"""
        super().showEvent(event)
        self.pause_btn.setText("暂停")