#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麒麟服务器版命令行客户端
适用于麒麟服务器版、Ubuntu Server、CentOS 等无 GUI 的 Linux 系统
支持双向传输：上传文件到远程、从远程下载文件
"""
import os
import sys
import socket
import argparse
import time
import json
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.protocol import (
    Command, pack_message, unpack_message, pack_file_chunk,
    create_hello_payload, create_file_header_payload, create_list_dir_payload
)
from utils.checksum import compute_file_hash
from utils.helpers import format_size, ensure_dir


class KylinCLIClient:
    """麒麟命令行客户端"""
    
    def __init__(self, server_ip: str, port: int = 9000):
        self.server_ip = server_ip
        self.port = port
        self.socket = None
        self.connected = False
        self.buffer = b""
        
    def connect(self) -> bool:
        """连接到远程服务端"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)
            self.socket.connect((self.server_ip, self.port))
            
            # 发送握手消息
            hello = pack_message(Command.HELLO, create_hello_payload(
                "麒麟命令行客户端", config.VERSION, "kylin/linux"
            ))
            self.socket.sendall(hello)
            
            # 等待响应
            response = self.socket.recv(1024)
            cmd, payload, _ = unpack_message(response)
            
            if cmd == Command.HELLO:
                self.connected = True
                print(f"[SUCCESS] 已连接到 {self.server_ip}:{self.port}")
                print(f"[INFO] 远程设备: {payload.get('device_name', '未知')}")
                return True
            else:
                print("[ERROR] 握手失败")
                return False
                
        except Exception as e:
            print(f"[ERROR] 连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开连接"""
        if self.socket:
            self.socket.close()
            self.socket = None
        self.connected = False
        print("[INFO] 已断开连接")
    
    def list_remote_dir(self, path: str = "") -> list:
        """列出远程目录内容"""
        if not self.connected:
            print("[ERROR] 未连接")
            return []
        
        try:
            # 发送列出目录请求
            request = pack_message(Command.LIST_DIR, create_list_dir_payload(path))
            self.socket.sendall(request)
            
            # 等待响应
            start_time = time.time()
            while time.time() - start_time < 10:
                data = self.socket.recv(65536)
                if not data:
                    break
                
                self.buffer += data
                
                while len(self.buffer) >= 8:
                    cmd, payload, remaining = unpack_message(self.buffer)
                    if cmd is None:
                        break
                    
                    self.buffer = remaining
                    
                    if cmd == Command.LIST_DIR_RESPONSE:
                        return payload.get("entries", [])
                    elif cmd == Command.ERROR:
                        print(f"[ERROR] {payload.get('message', '未知错误')}")
                        return []
            
            print("[ERROR] 请求超时")
            return []
            
        except Exception as e:
            print(f"[ERROR] 列出目录失败: {e}")
            return []
    
    def upload_file(self, local_path: str, remote_dir: str = "") -> bool:
        """上传文件到远程"""
        if not self.connected:
            print("[ERROR] 未连接")
            return False
        
        if not os.path.exists(local_path):
            print(f"[ERROR] 本地文件不存在: {local_path}")
            return False
        
        try:
            file_size = os.path.getsize(local_path)
            file_name = os.path.basename(local_path)
            checksum = compute_file_hash(local_path)
            
            print(f"[INFO] 正在上传: {file_name} ({format_size(file_size)})")
            
            # 发送文件头部
            relative_path = os.path.join(remote_dir, file_name) if remote_dir else file_name
            header = pack_message(Command.FILE_HEADER, create_file_header_payload(
                local_path, file_size, checksum, relative_path
            ))
            self.socket.sendall(header)
            
            # 等待确认
            response = self.socket.recv(1024)
            cmd, payload, _ = unpack_message(response)
            
            if cmd != Command.FILE_HEADER or payload.get("status") != "ok":
                print("[ERROR] 远程端拒绝接收")
                return False
            
            # 发送文件内容
            chunk_index = 0
            uploaded_size = 0
            with open(local_path, "rb") as f:
                while True:
                    chunk = f.read(config.CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    chunk_packet = pack_file_chunk(chunk_index, chunk)
                    self.socket.sendall(chunk_packet)
                    
                    uploaded_size += len(chunk)
                    chunk_index += 1
                    
                    # 显示进度
                    progress = (uploaded_size / file_size) * 100
                    print(f"[进度] {progress:.1f}% ({format_size(uploaded_size)}/{format_size(file_size)})")
            
            # 发送校验请求
            verify = pack_message(Command.VERIFY_REQUEST, {
                "file_path": relative_path,
                "checksum": checksum
            })
            self.socket.sendall(verify)
            
            # 等待校验结果
            response = self.socket.recv(1024)
            cmd, payload, _ = unpack_message(response)
            
            if cmd == Command.VERIFY_RESPONSE and payload.get("verified"):
                print(f"[SUCCESS] 文件上传完成: {relative_path}")
                return True
            else:
                print("[ERROR] 文件校验失败")
                return False
                
        except Exception as e:
            print(f"[ERROR] 上传失败: {e}")
            return False
    
    def download_file(self, remote_path: str, local_dir: str) -> bool:
        """从远程下载文件"""
        if not self.connected:
            print("[ERROR] 未连接")
            return False
        
        try:
            # 发送获取文件请求
            request = pack_message(Command.GET_REMOTE_FILE, {"file_path": remote_path})
            self.socket.sendall(request)
            
            # 接收文件头部
            response = self.socket.recv(1024)
            cmd, payload, _ = unpack_message(response)
            
            if cmd == Command.ERROR:
                print(f"[ERROR] {payload.get('message', '文件不存在')}")
                return False
            
            if cmd != Command.FILE_HEADER:
                print("[ERROR] 未收到文件头部")
                return False
            
            file_size = payload.get("file_size", 0)
            file_name = os.path.basename(remote_path)
            expected_checksum = payload.get("checksum", "")
            
            print(f"[INFO] 正在下载: {file_name} ({format_size(file_size)})")
            
            # 创建本地文件
            ensure_dir(local_dir)
            local_file_path = os.path.join(local_dir, file_name)
            
            received_size = 0
            with open(local_file_path, "wb") as f:
                while received_size < file_size:
                    data = self.socket.recv(config.CHUNK_SIZE)
                    if not data:
                        break
                    
                    # 处理数据包
                    self.buffer += data
                    
                    while len(self.buffer) >= 8:
                        chunk_idx, chunk_data, remaining = unpack_file_chunk(self.buffer)
                        if chunk_idx is None:
                            # 可能是其他命令
                            cmd, payload, remaining = unpack_message(self.buffer)
                            if cmd is None:
                                break
                            self.buffer = remaining
                            if cmd == Command.VERIFY_REQUEST:
                                # 下载完成，进行校验
                                actual_checksum = compute_file_hash(local_file_path)
                                if actual_checksum == expected_checksum:
                                    print(f"[SUCCESS] 文件下载完成: {local_file_path}")
                                    return True
                                else:
                                    print("[ERROR] 文件校验失败")
                                    return False
                            continue
                        
                        self.buffer = remaining
                        f.write(chunk_data)
                        received_size += len(chunk_data)
                        
                        # 显示进度
                        progress = (received_size / file_size) * 100
                        print(f"[进度] {progress:.1f}% ({format_size(received_size)}/{format_size(file_size)})")
            
            print(f"[SUCCESS] 文件下载完成: {local_file_path}")
            return True
            
        except Exception as e:
            print(f"[ERROR] 下载失败: {e}")
            return False
    
    def upload_directory(self, local_dir: str, remote_dir: str = "") -> dict:
        """上传整个目录"""
        if not os.path.isdir(local_dir):
            print(f"[ERROR] 本地目录不存在: {local_dir}")
            return {"success": 0, "failed": 0}
        
        results = {"success": 0, "failed": 0, "total": 0}
        
        print(f"[INFO] 正在上传目录: {local_dir}")
        
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                local_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, local_dir)
                remote_path = os.path.join(remote_dir, relative_path) if remote_dir else relative_path
                
                results["total"] += 1
                
                if self.upload_file(local_path, os.path.dirname(remote_path)):
                    results["success"] += 1
                else:
                    results["failed"] += 1
        
        print(f"[完成] 成功: {results['success']}, 失败: {results['failed']}, 总计: {results['total']}")
        return results
    
    def interactive_mode(self):
        """交互模式"""
        print("\n" + "="*60)
        print("麒麟命令行客户端 - 交互模式")
        print("="*60)
        print("\n可用命令:")
        print("  ls [path]        - 列出远程目录")
        print("  upload <file>    - 上传文件")
        print("  uploaddir <dir>  - 上传目录")
        print("  download <file>  - 下载文件")
        print("  help             - 显示帮助")
        print("  quit             - 退出")
        print("\n")
        
        while self.connected:
            try:
                cmd_input = input("kylin> ").strip()
                
                if not cmd_input:
                    continue
                
                parts = cmd_input.split()
                command = parts[0].lower()
                
                if command == "quit" or command == "exit":
                    break
                
                elif command == "help":
                    print("\n可用命令:")
                    print("  ls [path]        - 列出远程目录")
                    print("  upload <file>    - 上传文件到远程")
                    print("  uploaddir <dir>  - 上传整个目录")
                    print("  download <file>  - 从远程下载文件")
                    print("  help             - 显示帮助")
                    print("  quit             - 退出")
                    print("\n")
                
                elif command == "ls":
                    path = parts[1] if len(parts) > 1 else ""
                    entries = self.list_remote_dir(path)
                    
                    if entries:
                        print(f"\n目录: {path or '~'}")
                        print("-" * 60)
                        for entry in entries:
                            name = entry.get("name", "")
                            entry_type = entry.get("type", "file")
                            size = entry.get("size", 0)
                            
                            if entry_type == "directory":
                                print(f"  [DIR]  {name}")
                            else:
                                print(f"  [FILE] {name} ({format_size(size)})")
                        print("-" * 60)
                        print(f"共 {len(entries)} 项\n")
                
                elif command == "upload":
                    if len(parts) < 2:
                        print("[ERROR] 请指定文件路径")
                        continue
                    
                    local_path = parts[1]
                    remote_dir = parts[2] if len(parts) > 2 else ""
                    
                    self.upload_file(local_path, remote_dir)
                
                elif command == "uploaddir":
                    if len(parts) < 2:
                        print("[ERROR] 请指定目录路径")
                        continue
                    
                    local_dir = parts[1]
                    remote_dir = parts[2] if len(parts) > 2 else ""
                    
                    self.upload_directory(local_dir, remote_dir)
                
                elif command == "download":
                    if len(parts) < 2:
                        print("[ERROR] 请指定远程文件路径")
                        continue
                    
                    remote_path = parts[1]
                    local_dir = parts[2] if len(parts) > 2 else os.path.expanduser("~/Downloads")
                    
                    self.download_file(remote_path, local_dir)
                
                else:
                    print(f"[ERROR] 未知命令: {command}")
                    print("输入 'help' 查看可用命令")
                    
            except KeyboardInterrupt:
                print("\n[INFO] 按Ctrl+C退出")
                break
            except Exception as e:
                print(f"[ERROR] {e}")
        
        self.disconnect()


def main():
    parser = argparse.ArgumentParser(description="麒麟命令行客户端")
    parser.add_argument("server_ip", help="远程服务端 IP 地址")
    parser.add_argument("-p", "--port", type=int, default=9000, help="服务端端口 (默认: 9000)")
    parser.add_argument("--upload", metavar="FILE", help="上传文件")
    parser.add_argument("--uploaddir", metavar="DIR", help="上传目录")
    parser.add_argument("--download", metavar="FILE", help="下载文件")
    parser.add_argument("--remote-dir", default="", help="远程保存目录")
    parser.add_argument("--local-dir", default=os.path.expanduser("~/Downloads"), help="本地保存目录")
    parser.add_argument("--ls", metavar="PATH", nargs="?", const="", help="列出远程目录")
    parser.add_argument("-i", "--interactive", action="store_true", help="交互模式")
    
    args = parser.parse_args()
    
    # 创建客户端
    client = KylinCLIClient(args.server_ip, args.port)
    
    # 连接
    if not client.connect():
        sys.exit(1)
    
    # 执行操作
    if args.ls is not None:
        # 列出目录
        entries = client.list_remote_dir(args.ls)
        if entries:
            print(f"\n目录: {args.ls or '~'}")
            print("-" * 60)
            for entry in entries:
                name = entry.get("name", "")
                entry_type = entry.get("type", "file")
                size = entry.get("size", 0)
                
                if entry_type == "directory":
                    print(f"  [DIR]  {name}")
                else:
                    print(f"  [FILE] {name} ({format_size(size)})")
            print("-" * 60)
    
    elif args.upload:
        # 上传文件
        client.upload_file(args.upload, args.remote_dir)
    
    elif args.uploaddir:
        # 上传目录
        client.upload_directory(args.uploaddir, args.remote_dir)
    
    elif args.download:
        # 下载文件
        client.download_file(args.download, args.local_dir)
    
    elif args.interactive:
        # 交互模式
        client.interactive_mode()
    
    else:
        # 默认进入交互模式
        client.interactive_mode()
    
    # 断开连接
    client.disconnect()


if __name__ == "__main__":
    main()