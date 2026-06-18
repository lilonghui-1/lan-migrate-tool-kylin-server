"""
数据选择页面
"""
import os
import threading
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QSplitter, QTextEdit, QMessageBox,
    QDialog, QFrame, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from core.scanner import DataScanner, DataCategory, DataItem
from utils.helpers import format_size


class MultiDirSelectDialog(QDialog):
    """自定义多选目录选择对话框"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择要迁移的目录（可多选）")
        self.resize(800, 600)
        
        self.selected_dirs = []
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("目录")
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.tree.setColumnCount(1)
        self.tree.itemExpanded.connect(self.on_item_expanded)
        layout.addWidget(self.tree)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)
        
        btn_layout = QHBoxLayout()
        
        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        
        self.load_drives()
    
    def load_drives(self):
        """加载系统驱动器"""
        import sys
        if sys.platform == "win32":
            import string
            from string import ascii_uppercase
            for letter in ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    try:
                        item = QTreeWidgetItem(self.tree)
                        item.setText(0, drive)
                        item.setData(0, Qt.ItemDataRole.UserRole, drive)
                        item.setExpanded(False)
                        temp_child = QTreeWidgetItem(item)
                        temp_child.setText(0, "Loading...")
                        item.addChild(temp_child)
                    except Exception:
                        pass
        else:
            root = "/"
            item = QTreeWidgetItem(self.tree)
            item.setText(0, root)
            item.setData(0, Qt.ItemDataRole.UserRole, root)
            item.setExpanded(False)
            temp_child = QTreeWidgetItem(item)
            temp_child.setText(0, "Loading...")
            item.addChild(temp_child)
    
    def on_item_expanded(self, item):
        """目录展开时的处理"""
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        
        first_child = item.child(0)
        if first_child and first_child.text(0) == "Loading...":
            item.takeChildren()
            self.load_directory(item, path)
    
    def load_directory(self, parent_item, path):
        """加载目录内容"""
        try:
            entries = os.listdir(path)
            dirs = []
            
            for entry in entries:
                full_path = os.path.join(path, entry)
                if os.path.isdir(full_path):
                    if entry.startswith('$') or entry.startswith('.'):
                        continue
                    dirs.append(entry)
            
            dirs.sort()
            
            for dir_name in dirs:
                full_path = os.path.join(path, dir_name)
                try:
                    item = QTreeWidgetItem(parent_item)
                    item.setText(0, dir_name)
                    item.setData(0, Qt.ItemDataRole.UserRole, full_path)
                    temp_child = QTreeWidgetItem(item)
                    temp_child.setText(0, "Loading...")
                    item.addChild(temp_child)
                except Exception:
                    pass
        except PermissionError:
            pass
        except Exception:
            pass
    
    def accept(self):
        """确定按钮处理"""
        self.selected_dirs = []
        selected_items = self.tree.selectedItems()
        
        for item in selected_items:
            dir_path = item.data(0, Qt.ItemDataRole.UserRole)
            if dir_path and os.path.isdir(dir_path):
                self.selected_dirs.append(dir_path)
        
        super().accept()


class SelectPage(QWidget):
    """数据选择页面"""
    
    transfer_started = pyqtSignal(list, str)
    back_requested = pyqtSignal()
    
    _scan_finished = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scanner = DataScanner()
        self._scanning = False
        self.pending_task_info = None
        self.setup_ui()
        self.setup_connections()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        title = QLabel("选择要迁移的数据")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        self.desc_label = QLabel("正在扫描本地数据...")
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc_label.setStyleSheet("color: #666;")
        layout.addWidget(self.desc_label)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["数据项", "大小", "数量", "描述"])
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 80)
        self.tree.setColumnWidth(3, 200)
        self.tree.setIndentation(20)
        self.tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #ddd;
                border-radius: 5px;
                background: white;
                alternate-background-color: #f9f9f9;
            }
            QTreeWidget::item {
                padding: 5px;
                color: #333;
            }
            QTreeWidget::item:selected {
                background: #1a1a1a;
                color: white;
            }
            QTreeWidget::item:hover {
                background: #f0f0f0;
            }
            QTreeWidget::branch:has-siblings:!has-children:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {
                border-image: none;
                image: url(:/images/branch-closed.png);
            }
            QTreeWidget::branch:open:has-children:has-siblings,
            QTreeWidget::branch:open:has-children:!has-siblings {
                border-image: none;
                image: url(:/images/branch-open.png);
            }
        """)
        self.tree.setMinimumWidth(500)
        splitter.addWidget(self.tree)
        
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        
        detail_title = QLabel("详细信息")
        detail_title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        detail_layout.addWidget(detail_title)
        
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ddd;
                border-radius: 5px;
                background: #f9f9f9;
                padding: 10px;
            }
        """)
        detail_layout.addWidget(self.detail_text)
        
        splitter.addWidget(detail_widget)
        splitter.setSizes([500, 300])
        
        layout.addWidget(splitter)
        
        self.stats_label = QLabel("已选择: 0 项, 总计: 0 B")
        self.stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #2196F3;
                padding: 10px;
                background: #e3f2fd;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.stats_label)
        
        btn_layout = QHBoxLayout()
        
        self.back_btn = QPushButton("返回")
        self.back_btn.setStyleSheet("""
            QPushButton {
                background: #9E9E9E;
                color: white;
                padding: 8px 20px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #757575;
            }
        """)
        btn_layout.addWidget(self.back_btn)
        
        btn_layout.addStretch()
        
        self.scan_btn = QPushButton("重新扫描")
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background: #2196F3;
                color: white;
                padding: 8px 20px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #1976D2;
            }
        """)
        btn_layout.addWidget(self.scan_btn)
        
        self.add_dir_btn = QPushButton("添加目录")
        self.add_dir_btn.setStyleSheet("""
            QPushButton {
                background: #FF9800;
                color: white;
                padding: 8px 20px;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #F57C00;
            }
        """)
        btn_layout.addWidget(self.add_dir_btn)
        
        self.resume_btn = QPushButton("继续上次传输")
        self.resume_btn.setStyleSheet("""
            QPushButton {
                background: #FF5722;
                color: white;
                padding: 8px 20px;
                border: none;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #F4511E;
            }
        """)
        self.resume_btn.hide()
        btn_layout.addWidget(self.resume_btn)
        
        self.start_btn = QPushButton("开始迁移")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                padding: 8px 20px;
                border: none;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #45a049;
            }
        """)
        btn_layout.addWidget(self.start_btn)
        
        layout.addLayout(btn_layout)
    
    def setup_connections(self):
        """设置信号连接"""
        self.scan_btn.clicked.connect(self.scan_data)
        self.start_btn.clicked.connect(self.start_transfer)
        self.resume_btn.clicked.connect(self.resume_transfer)
        self.back_btn.clicked.connect(self.back_requested)
        self.add_dir_btn.clicked.connect(self.add_directory)
        self.tree.itemClicked.connect(self.on_item_clicked)
        self.tree.itemChanged.connect(self.on_item_changed)
        self._scan_finished.connect(self._on_scan_finished)
    
    def scan_data(self):
        """扫描数据"""
        if self._scanning:
            return
        
        self._scanning = True
        self.scan_btn.setEnabled(False)
        self.add_dir_btn.setEnabled(False)
        self.desc_label.setText("正在扫描本地数据，请稍候...")
        self.tree.clear()
        
        thread = threading.Thread(target=self._scan_worker, daemon=True)
        thread.start()
    
    def _scan_worker(self):
        """扫描工作线程"""
        try:
            categories = self.scanner.scan_all()
        except Exception as e:
            categories = []
        
        self._scan_finished.emit(categories)
    
    def _on_scan_finished(self, categories):
        """扫描完成处理"""
        for category in categories:
            self.add_category_to_tree(category)
        
        self.update_stats()
        
        summary = self.scanner.get_summary()
        self.desc_label.setText(
            f"扫描完成，发现 {summary['category_count']} 类数据，"
            f"共 {format_size(summary['total_size'])}"
        )
        
        self._scanning = False
        self.scan_btn.setEnabled(True)
        self.add_dir_btn.setEnabled(True)
    
    def add_directory(self):
        """添加自定义目录"""
        dialog = MultiDirSelectDialog(self)
        if dialog.exec():
            dir_paths = dialog.selected_dirs
        else:
            dir_paths = []
        
        if not dir_paths:
            return
        
        added_count = 0
        skipped_count = 0
        
        for dir_path in dir_paths:
            exists = False
            for category in self.scanner.categories:
                for item in category.items:
                    if item.path == dir_path:
                        exists = True
                        break
                if exists:
                    break
            
            if exists:
                skipped_count += 1
                continue
            
            size = self.get_folder_size(dir_path)
            count = self.count_files(dir_path)
            
            dir_name = os.path.basename(dir_path)
            
            custom_category = None
            for category in self.scanner.categories:
                if category.name == "custom_dirs":
                    custom_category = category
                    break
            
            if not custom_category:
                custom_category = DataCategory(
                    name="custom_dirs",
                    display_name="自定义目录",
                    description="手动添加的目录"
                )
                self.scanner.categories.append(custom_category)
            
            item = DataItem(
                name=dir_name,
                path=dir_path,
                item_type="folder",
                size=size,
                count=count,
                description=f"自定义目录: {dir_path}"
            )
            custom_category.items.append(item)
            
            found = False
            for i in range(self.tree.topLevelItemCount()):
                top_item = self.tree.topLevelItem(i)
                cat_data = top_item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(cat_data, DataCategory) and cat_data.name == "custom_dirs":
                    self.add_item_to_tree(top_item, item)
                    top_item.setExpanded(True)
                    found = True
                    break
            
            if not found:
                self.add_category_to_tree(custom_category)
            
            added_count += 1
        
        self.update_stats()
        
        message = f"添加完成！\n"
        if added_count > 0:
            message += f"成功添加: {added_count} 个目录\n"
        if skipped_count > 0:
            message += f"已存在跳过: {skipped_count} 个目录"
        
        QMessageBox.information(self, "添加结果", message)
    
    def get_folder_size(self, folder_path):
        """计算文件夹大小"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(filepath)
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return total_size
    
    def count_files(self, folder_path):
        """统计文件数量"""
        count = 0
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                count += len(filenames)
        except (OSError, PermissionError):
            pass
        return count
    
    def add_category_to_tree(self, category: DataCategory):
        """添加分类到树"""
        cat_item = QTreeWidgetItem(self.tree)
        cat_item.setText(0, category.display_name)
        cat_item.setText(1, format_size(category.total_size))
        cat_item.setText(2, str(category.total_count))
        cat_item.setText(3, category.description)
        cat_item.setData(0, Qt.ItemDataRole.UserRole, category)
        cat_item.setExpanded(True)
        cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        cat_item.setCheckState(0, Qt.CheckState.Unchecked)
        
        for item in category.items:
            self.add_item_to_tree(cat_item, item)
    
    def add_item_to_tree(self, parent: QTreeWidgetItem, item: DataItem):
        """添加数据项到树"""
        tree_item = QTreeWidgetItem(parent)
        tree_item.setText(0, item.name)
        tree_item.setText(1, format_size(item.size))
        tree_item.setText(2, str(item.count))
        tree_item.setText(3, item.description)
        tree_item.setData(0, Qt.ItemDataRole.UserRole, item)
        tree_item.setFlags(tree_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        tree_item.setCheckState(0, Qt.CheckState.Unchecked)
    
    def on_item_changed(self, item: QTreeWidgetItem, column: int):
        """树项状态变更（复选框变更）"""
        if column != 0:
            return
        
        data = item.data(0, Qt.ItemDataRole.UserRole)
        check_state = item.checkState(0)
        
        if isinstance(data, DataCategory):
            data.selected = check_state == Qt.CheckState.Checked
            
            for i in range(item.childCount()):
                child = item.child(i)
                child.setCheckState(0, check_state)
                child_data = child.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(child_data, DataItem):
                    child_data.selected = check_state == Qt.CheckState.Checked
        
        elif isinstance(data, DataItem):
            data.selected = check_state == Qt.CheckState.Checked
            
            parent = item.parent()
            if parent:
                parent_data = parent.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(parent_data, DataCategory):
                    all_checked = True
                    any_checked = False
                    for i in range(parent.childCount()):
                        child = parent.child(i)
                        child_state = child.checkState(0)
                        if child_state == Qt.CheckState.Checked:
                            any_checked = True
                        elif child_state == Qt.CheckState.Unchecked:
                            all_checked = False
                        else:
                            any_checked = True
                            all_checked = False
                    
                    if all_checked:
                        parent.setCheckState(0, Qt.CheckState.Checked)
                        parent_data.selected = True
                    elif any_checked:
                        parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
                        parent_data.selected = True
                    else:
                        parent.setCheckState(0, Qt.CheckState.Unchecked)
                        parent_data.selected = False
        
        self.update_stats()
    
    def on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """点击树项 - 显示详细信息"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        
        if isinstance(data, DataItem):
            info = f"""
<b>名称:</b> {data.name}<br>
<b>路径:</b> {data.path}<br>
<b>类型:</b> {data.item_type}<br>
<b>大小:</b> {format_size(data.size)}<br>
<b>文件数:</b> {data.count}<br>
<b>描述:</b> {data.description}
            """.strip()
            self.detail_text.setHtml(info)
        
        elif isinstance(data, DataCategory):
            info = f"""
<b>分类:</b> {data.display_name}<br>
<b>描述:</b> {data.description}<br>
<b>总大小:</b> {format_size(data.total_size)}<br>
<b>总文件数:</b> {data.total_count}<br>
<b>包含项:</b> {len(data.items)}
            """.strip()
            self.detail_text.setHtml(info)
    
    def update_stats(self):
        """更新统计信息"""
        selected_items = self.scanner.get_selected_items()
        total_size = sum(item.size for item in selected_items)
        
        self.stats_label.setText(
            f"已选择: {len(selected_items)} 项, 总计: {format_size(total_size)}"
        )
    
    def start_transfer(self):
        """开始传输"""
        selected_items = self.scanner.get_selected_items()
        
        if not selected_items:
            QMessageBox.warning(self, "提示", "请至少选择一项数据进行迁移")
            return
        
        browser_items = [item for item in selected_items 
                        if "browser" in item.path.lower() or 
                        any(b in item.name for b in ["Chrome", "Edge", "Firefox"])]
        
        for item in browser_items:
            if "正在运行" in item.description:
                reply = QMessageBox.question(
                    self,
                    "浏览器正在运行",
                    f"{item.name} 似乎正在运行。迁移浏览器数据前需要关闭浏览器，是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        
        items_dict = [item.to_dict() for item in selected_items]
        self.transfer_started.emit(items_dict, "")
    
    def set_pending_task_info(self, task_info: dict):
        """设置待恢复的任务信息"""
        self.pending_task_info = task_info
        if task_info:
            self.resume_btn.show()
        else:
            self.resume_btn.hide()
    
    def resume_transfer(self):
        """继续上次未完成的传输"""
        if not self.pending_task_info:
            QMessageBox.warning(self, "提示", "没有待恢复的任务")
            return
        
        task_id = self.pending_task_info["task_id"]
        items = self.pending_task_info["items"]
        
        self.pending_task_info = None
        self.resume_btn.hide()
        
        self.transfer_started.emit(items, task_id)
    
    def showEvent(self, event):
        """页面显示事件"""
        super().showEvent(event)