# 麒麟/Linux 系统文件传输实操指南

## 目录
- [一、概述](#一概述)
- [二、环境准备](#二环境准备)
- [三、麒麟服务端部署](#三麒麟服务端部署)
- [四、Windows客户端使用](#四windows客户端使用)
- [五、目录管理可视化操作](#五目录管理可视化操作)
- [六、双向传输操作](#六双向传输操作)
- [七、常见问题排查](#七常见问题排查)

---

## 一、概述

本指南介绍如何在 **Windows** 与 **麒麟系统（Kylin OS）** 或 **其他 Linux 发行版** 之间进行文件传输。

### 功能特性
- **可视化目录管理**：在 Windows 端直接浏览麒麟系统的远程目录结构
- **双向传输**：支持 Windows → 麒麟、麒麟 → Windows 两个方向
- **跨平台兼容**：麒麟服务端基于 Python，支持源码运行或打包为可执行文件
- **安全传输**：使用 SHA-256 校验文件完整性，支持断点续传

### 系统架构
```
┌─────────────────┐         TCP 9000          ┌─────────────────┐
│   Windows 客户端 │  ═══════════════════════► │  麒麟/Linux服务端 │
│  (PyQt6 GUI)    │   自定义传输协议           │  (Python服务端)   │
│                 │ ◄═══════════════════════  │                 │
└─────────────────┘      目录浏览/文件传输     └─────────────────┘
```

---

## 二、环境准备

### 2.1 网络要求
- Windows 电脑和麒麟系统必须在 **同一局域网** 内
- 确保防火墙允许 **TCP 9000 端口** 通信
- 双方能够互相 Ping 通

### 2.2 麒麟系统环境检查

在麒麟系统终端执行以下命令检查环境：

```bash
# 检查 Python 版本（需要 3.8+）
python3 --version

# 检查 pip 是否安装
pip3 --version

# 检查网络连接
ip addr
```

### 2.3 Python 依赖安装（如需要源码运行）

如果麒麟系统已安装 Python 3.8+，安装依赖：

```bash
# 进入项目目录
cd /path/to/lan-migrate-tool-kylin-server

# 安装依赖
pip3 install -r requirements.txt
```

requirements.txt 内容：
```
PyQt6>=6.4.0
zeroconf>=0.47.0
```

> **注意**：麒麟服务端不需要 PyQt6，只需要 zeroconf（用于可选的设备发现功能）。纯文件传输不需要额外依赖。

---

## 三、麒麟服务端部署

### 3.1 方式一：源码运行（推荐开发/测试环境）

#### 步骤 1：复制项目文件到麒麟系统

将项目文件通过 U 盘或 SCP 复制到麒麟系统：

```bash
# 在麒麟系统上创建目录
mkdir -p ~/lan-migrate-tool

# 使用 scp 从 Windows 复制（在 Windows PowerShell 中执行）
scp -r ./* user@麒麟IP:~/lan-migrate-tool/
```

#### 步骤 2：启动服务端

```bash
cd ~/lan-migrate-tool

# 使用默认端口 9000
python3 server/kylin_server.py

# 或使用自定义端口
python3 server/kylin_server.py -p 9001

# 指定接收目录
python3 server/kylin_server.py -d /home/user/接收文件

# 后台运行
python3 server/kylin_server.py --daemon
```

启动成功后，将看到如下输出：
```
[INFO] 麒麟服务端启动成功，端口: 9000
[INFO] 接收目录: /home/user/LAN_Migrate_Received
[INFO] 等待连接...
```

### 3.2 方式二：打包为可执行文件（推荐生产环境）

#### 步骤 1：在麒麟系统上安装 PyInstaller

```bash
pip3 install pyinstaller
```

#### 步骤 2：打包服务端

```bash
cd ~/lan-migrate-tool

pyinstaller --onefile --name kylin-server server/kylin_server.py
```

打包完成后，可执行文件位于 `dist/kylin-server`。

#### 步骤 3：运行打包后的程序

```bash
# 直接运行
./dist/kylin-server

# 指定端口
./dist/kylin-server -p 9001
```

### 3.3 方式三：使用 systemd 服务（推荐服务器环境）

创建 systemd 服务文件，实现开机自启动：

```bash
sudo nano /etc/systemd/system/kylin-server.service
```

写入以下内容：
```ini
[Unit]
Description=LAN Migrate Kylin Server
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/lan-migrate-tool
ExecStart=/usr/bin/python3 /home/your_username/lan-migrate-tool/server/kylin_server.py -p 9000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable kylin-server
sudo systemctl start kylin-server

# 查看状态
sudo systemctl status kylin-server

# 查看日志
sudo journalctl -u kylin-server -f
```

---

## 四、Windows客户端使用

### 4.1 启动 Windows 客户端

双击运行 `main.py` 或打包后的可执行文件：

```bash
# 源码运行
python main.py

# 或运行打包后的程序
LAN迁移工具.exe
```

### 4.2 连接到麒麟系统

#### 方式一：自动发现（同一局域网）

1. 在 **发现设备** 页面，客户端会自动扫描局域网内的设备
2. 麒麟服务端会显示为 `"麒麟服务端"`
3. 点击设备卡片进行连接

#### 方式二：手动输入 IP（推荐）

1. 在 **发现设备** 页面，点击 **"手动输入IP"**
2. 输入麒麟系统的 IP 地址（如 `192.168.1.100`）
3. 端口号保持默认 `9000`
4. 点击 **"连接"**

#### 方式三：网络配置页面测试

1. 切换到 **网络配置** 页面
2. 在 **"目标IP"** 输入框填入麒麟系统 IP
3. 点击 **"开始测试"**
4. 如果三项测试都通过，说明连接正常

---

## 五、目录管理可视化操作

### 5.1 浏览远程目录

连接成功后，自动切换到 **麒麟传输** 页面：

1. 点击 **"浏览远程目录"** 按钮
2. 弹出 **远程目录浏览器** 窗口：
   - **左侧**：目录导航栏（返回上级、家目录、刷新）
   - **中间**：文件列表（名称、类型、大小、修改时间）
   - **底部**：操作按钮

3. 双击目录名称可进入子目录
4. 点击 **"返回上级"** 可返回上一级目录
5. 点击 **"家目录"** 可快速回到用户主目录

### 5.2 文件列表说明

| 列名 | 说明 |
|------|------|
| 名称 | 文件或目录名称（蓝色加粗为目录） |
| 类型 | 文件 或 目录 |
| 大小 | 文件大小（目录不显示大小） |
| 修改时间 | 最后修改时间 |

### 5.3 从麒麟系统下载文件到 Windows

1. 在远程目录浏览器中，**选中** 要下载的文件（可按住 Ctrl 多选）
2. 点击 **"下载选中文件"** 按钮
3. 选择 Windows 本地保存目录
4. 确认后，文件将下载到指定位置

**右键菜单操作**：
- 在文件列表上 **右键单击**，可看到：
  - 打开（双击效果）
  - 下载到本地...
  - 刷新

---

## 六、双向传输操作

### 6.1 Windows → 麒麟（上传文件）

1. 在 **麒麟传输** 页面，点击 **"上传文件到远程"**
2. 选择要上传的 Windows 本地文件（可多选）
3. 在弹出的远程目录浏览器中，选择麒麟系统的保存目录
4. 点击 **"选择此目录"**
5. 文件将上传到麒麟系统的指定位置

### 6.2 麒麟 → Windows（下载文件）

1. 在 **麒麟传输** 页面，点击 **"浏览远程目录"**
2. 导航到要下载的文件所在目录
3. 选中文件，点击 **"下载选中文件"**
4. 选择 Windows 本地保存目录
5. 确认下载

### 6.3 批量传输

支持批量选择多个文件进行上传或下载：
- 按住 **Ctrl** 键点击可选择多个不连续的文件
- 按住 **Shift** 键可选择连续范围

---

## 七、常见问题排查

### 7.1 连接失败

**现象**：Windows 客户端无法连接到麒麟服务端

**排查步骤**：

1. **检查网络连通性**
   ```bash
   # 在 Windows PowerShell 中执行
   ping 麒麟系统IP
   
   # 在麒麟系统终端执行
   ping WindowsIP
   ```

2. **检查端口是否开放**
   ```bash
   # 在麒麟系统上检查端口监听
   sudo netstat -tlnp | grep 9000
   
   # 在 Windows 上测试端口
   Test-NetConnection -ComputerName 麒麟IP -Port 9000
   ```

3. **检查防火墙**
   ```bash
   # 麒麟系统开放端口（UFW）
   sudo ufw allow 9000/tcp
   
   # 或使用 firewalld
   sudo firewall-cmd --permanent --add-port=9000/tcp
   sudo firewall-cmd --reload
   ```

4. **检查服务端是否运行**
   ```bash
   # 查看进程
   ps aux | grep kylin_server
   
   # 查看日志
   sudo journalctl -u kylin-server -f
   ```

### 7.2 传输中断

**现象**：文件传输到一半中断

**解决方案**：
- 检查网络稳定性
- 确认文件没有被占用
- 重新连接后继续传输（支持断点续传）

### 7.3 中文文件名乱码

**现象**：中文文件名显示为乱码

**解决方案**：
- 确保双方系统使用 UTF-8 编码
- 麒麟系统检查：
  ```bash
  echo $LANG
  # 应为 zh_CN.UTF-8 或类似值
  ```

### 7.4 权限问题

**现象**：无法写入文件或创建目录

**解决方案**：
```bash
# 修改接收目录权限
chmod 755 ~/LAN_Migrate_Received

# 或修改目录所有者
sudo chown -R $USER:$USER ~/LAN_Migrate_Received
```

### 7.5 Python 环境缺失

**现象**：麒麟系统没有 Python 或版本过低

**解决方案**：
```bash
# 安装 Python 3.8+
sudo apt update
sudo apt install python3 python3-pip

# 验证版本
python3 --version
```

---

## 附录

### A. 麒麟系统快捷命令

```bash
# 查看本机 IP
ip addr | grep inet

# 查看监听端口
sudo netstat -tlnp

# 查看防火墙状态
sudo ufw status
# 或
sudo firewall-cmd --state

# 查看系统信息
cat /etc/os-release
```

### B. Windows 快捷命令

```powershell
# 查看本机 IP
ipconfig

# 测试端口连通性
Test-NetConnection -ComputerName 192.168.1.100 -Port 9000

# 查看路由表
route print
```

### C. 麒麟服务端命令行参数

```
用法: python3 server/kylin_server.py [选项]

选项:
  -p, --port PORT       监听端口 (默认: 9000)
  -d, --dir DIRECTORY   接收文件目录 (默认: ~/LAN_Migrate_Received)
  --daemon              后台运行模式
  -h, --help            显示帮助信息
```

### D. 文件说明

| 文件 | 说明 |
|------|------|
| `server/kylin_server.py` | 麒麟/Linux 服务端主程序 |
| `core/protocol.py` | 自定义传输协议（Windows/麒麟通用） |
| `gui/remote_browser.py` | 远程目录浏览器 GUI |
| `utils/checksum.py` | 文件校验（SHA-256） |
| `config.py` | 全局配置 |

---

**文档版本**: 1.0  
**适用版本**: LAN迁移工具 v1.0.0+  
**最后更新**: 2026-06-18
