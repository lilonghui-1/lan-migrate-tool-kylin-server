#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麒麟/Linux 文件传输服务端
支持接收和发送文件，双向传输
"""
import os
import sys
import socket
import struct
import json
import threading
import time
import argparse
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from core.protocol import (
    Command, pack_message, unpack_message, pack_file_chunk, unpack_file_chunk,
    create_hello_payload, create_file_header_payload, create_list_dir_response_payload,
    create_remote_path_info_response_payload, create_error_payload
)
from utils.checksum import compute_file_hash
from utils.helpers import ensure_dir, format_size


class KylinServer:
    """麒麟/Linux 文件传输服务端"""
    
    def __init__(self, port=9000, receive_dir=None):
        self.port = port
        self.socket = None
        self.running = False
        self.receive_dir = receive_dir or os.path.expanduser("~/LAN_Migrate_Received")
        ensure_dir(self.receive_dir)
        self.buffer = b""
        self.current_file = None
        self.current_file_path = None
        self.current_file_size = 0
        self.received_size = 0
        
    def start(self):
        """启动服务端"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(("0.0.0.0", self.port))
            self.socket.listen(32)
            self.socket.settimeout(1.0)
            self.running = True
            
            print(f"[INFO] 麒麟服务端启动成功，端口: {self.port}")
            print(f"[INFO] 接收目录: {self.receive_dir}")
            print(f"[INFO] 等待连接...")
            
            while self.running:
                try:
                    conn, addr = self.socket.accept()
                    print(f"[INFO] 客户端连接: {addr[0]}:{addr[1]}")
                    handler = ConnectionHandler(conn, addr, self.receive_dir)
                    thread = threading.Thread(target=handler.handle, daemon=True)
                    thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"[ERROR] 接受连接失败: {e}")
                        
        except Exception as e:
            print(f"[ERROR] 启动服务端失败: {e}")
            return False
        return True
    
    def stop(self):
        """停止服务端"""
        self.running = False
        if self.socket:
            self.socket.close()
            self.socket = None
        print("[INFO] 服务端已停止")


class ConnectionHandler:
    """连接处理器"""
    
    def __init__(self, conn, addr, receive_dir):
        self.conn = conn
        self.addr = addr
        self.receive_dir = receive_dir
        self.buffer = b""
        self.current_file = None
        self.current_file_path = None
        self.current_file_size = 0
        self.received_size = 0
        
    def handle(self):
        """处理连接"""
        try:
            self.conn.settimeout(config.SOCKET_TIMEOUT)
            
            while True:
                data = self.conn.recv(config.CHUNK_SIZE)
                if not data:
                    break
                
                self.buffer += data
                self._process_buffer()
                
        except Exception as e:
            print(f"[ERROR] 连接处理异常: {e}")
        finally:
            self._cleanup_current_file()
            self.conn.close()
            print(f"[INFO] 客户端断开: {self.addr[0]}:{self.addr[1]}")
    
    def _process_buffer(self):
        """处理接收缓冲区"""
        while len(self.buffer) >= 8:
            chunk_idx, chunk_data, remaining = unpack_file_chunk(self.buffer)
            if chunk_idx is not None:
                self._handle_file_chunk(chunk_idx, chunk_data)
                self.buffer = remaining
                continue
            
            cmd, payload, remaining = unpack_message(self.buffer)
            
            if cmd is None:
                break
            
            self.buffer = remaining
            self._handle_command(cmd, payload)
    
    def _handle_command(self, cmd: Command, payload: dict):
        """处理命令"""
        if cmd == Command.HELLO:
            print(f"[INFO] 收到 HELLO 消息，来自 {self.addr}")
            response = pack_message(Command.HELLO, create_hello_payload(
                "麒麟服务端", config.VERSION, "kylin/linux"
            ))
            self.conn.sendall(response)
            
        elif cmd == Command.TRANSFER_START:
            self._cleanup_current_file()
            response = pack_message(Command.TRANSFER_START, {"status": "ready"})
            self.conn.sendall(response)
            
        elif cmd == Command.FILE_HEADER:
            self._handle_file_header(payload)
            
        elif cmd == Command.FILE_CHUNK:
            # 已由 _process_buffer 处理
            pass
            
        elif cmd == Command.VERIFY_REQUEST:
            self._handle_verify_request(payload)
            
        elif cmd == Command.COMPLETE:
            print("[INFO] 传输完成")
            
        elif cmd == Command.CANCEL:
            self._cleanup_current_file()
            
        elif cmd == Command.PING:
            pong = pack_message(Command.PONG, {"timestamp": payload.get("timestamp", 0)})
            self.conn.sendall(pong)
            
        elif cmd == Command.LIST_DIR:
            self._handle_list_dir(payload)
            
        elif cmd == Command.REMOTE_PATH_INFO:
            self._handle_path_info(payload)
            
        elif cmd == Command.GET_REMOTE_FILE:
            self._handle_get_remote_file(payload)
            
        elif cmd == Command.ERROR:
            print(f"[ERROR] 客户端错误: {payload.get('message', '未知错误')}")
    
    def _handle_file_header(self, payload: dict):
        """处理文件头部"""
        self._cleanup_current_file()
        
        relative_path = payload.get("relative_path", "")
        file_size = payload.get("file_size", 0)
        original_path = payload.get("file_path", "")
        
        if relative_path:
            self.current_file_path = os.path.join(self.receive_dir, relative_path)
        elif original_path:
            self.current_file_path = os.path.join(self.receive_dir, os.path.basename(original_path))
        else:
            self.current_file_path = os.path.join(self.receive_dir, "unknown_file")
        
        try:
            ensure_dir(os.path.dirname(self.current_file_path))
            self.current_file_size = file_size
            self.received_size = 0
            self.current_file = open(self.current_file_path, "ab")
            
            response = pack_message(Command.FILE_HEADER, {"status": "ok"})
            self.conn.sendall(response)
            print(f"[INFO] 准备接收文件: {self.current_file_path}")
        except Exception as e:
            print(f"[ERROR] 处理 FILE_HEADER 失败: {e}")
            self._cleanup_current_file()
            error_msg = pack_message(Command.ERROR, {"message": str(e)})
            self.conn.sendall(error_msg)
    
    def _handle_file_chunk(self, chunk_index: int, data: bytes):
        """处理文件数据块"""
        if self.current_file:
            try:
                self.current_file.write(data)
                self.current_file.flush()
                self.received_size += len(data)
            except Exception as e:
                print(f"[ERROR] 写入文件块失败: {e}")
    
    def _handle_verify_request(self, payload: dict):
        """处理校验请求"""
        self._cleanup_current_file()
        
        file_path = payload.get("file_path", "")
        
        full_path = None
        if self.current_file_path and os.path.exists(self.current_file_path):
            full_path = self.current_file_path
        else:
            full_path = os.path.join(self.receive_dir, file_path)
        
        verified = False
        actual_checksum = ""
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            verified = True
            actual_checksum = compute_file_hash(full_path)
        
        response = pack_message(Command.VERIFY_RESPONSE, {
            "file_path": file_path,
            "verified": verified,
            "checksum": actual_checksum
        })
        self.conn.sendall(response)
        
        if verified:
            print(f"[INFO] 文件接收完成: {full_path}")
    
    def _handle_list_dir(self, payload: dict):
        """处理列出目录请求"""
        path = payload.get("path", "")
        
        if not path:
            path = os.path.expanduser("~")
        
        try:
            entries = []
            if os.path.exists(path) and os.path.isdir(path):
                for entry in sorted(os.listdir(path)):
                    full_path = os.path.join(path, entry)
                    try:
                        stat = os.stat(full_path)
                        entries.append({
                            "name": entry,
                            "path": full_path,
                            "type": "directory" if os.path.isdir(full_path) else "file",
                            "size": stat.st_size if os.path.isfile(full_path) else 0,
                            "modified": stat.st_mtime
                        })
                    except (PermissionError, OSError):
                        continue
            
            response = pack_message(Command.LIST_DIR_RESPONSE, 
                                    create_list_dir_response_payload(path, entries))
            self.conn.sendall(response)
            print(f"[INFO] 列出目录: {path} ({len(entries)} 项)")
            
        except Exception as e:
            print(f"[ERROR] 列出目录失败: {e}")
            error_msg = pack_message(Command.ERROR, {"message": str(e)})
            self.conn.sendall(error_msg)
    
    def _handle_path_info(self, payload: dict):
        """处理路径信息查询"""
        path = payload.get("path", "")
        
        try:
            exists = os.path.exists(path)
            is_dir = os.path.isdir(path) if exists else False
            size = os.path.getsize(path) if exists and os.path.isfile(path) else 0
            
            response = pack_message(Command.REMOTE_PATH_INFO,
                                    create_remote_path_info_response_payload(path, exists, is_dir, size))
            self.conn.sendall(response)
        except Exception as e:
            error_msg = pack_message(Command.ERROR, {"message": str(e)})
            self.conn.sendall(error_msg)
    
    def _handle_get_remote_file(self, payload: dict):
        """处理获取远程文件请求（从本机发送文件到客户端）"""
        file_path = payload.get("file_path", "")
        
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            error_msg = pack_message(Command.ERROR, {"message": f"文件不存在: {file_path}"})
            self.conn.sendall(error_msg)
            return
        
        try:
            file_size = os.path.getsize(file_path)
            checksum = compute_file_hash(file_path)
            relative_path = os.path.basename(file_path)
            
            # 发送文件头部
            header = pack_message(Command.FILE_HEADER, create_file_header_payload(
                file_path, file_size, checksum, relative_path
            ))
            self.conn.sendall(header)
            
            # 等待客户端确认
            # 简化处理：直接发送文件内容
            chunk_index = 0
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(config.CHUNK_SIZE)
                    if not chunk:
                        break
                    chunk_packet = pack_file_chunk(chunk_index, chunk)
                    self.conn.sendall(chunk_packet)
                    chunk_index += 1
            
            # 发送校验请求
            verify = pack_message(Command.VERIFY_REQUEST, {
                "file_path": relative_path,
                "checksum": checksum
            })
            self.conn.sendall(verify)
            
            print(f"[INFO] 发送文件完成: {file_path}")
            
        except Exception as e:
            print(f"[ERROR] 发送文件失败: {e}")
            error_msg = pack_message(Command.ERROR, {"message": str(e)})
            self.conn.sendall(error_msg)
    
    def _cleanup_current_file(self):
        """清理当前文件"""
        if self.current_file:
            self.current_file.close()
            self.current_file = None


def main():
    parser = argparse.ArgumentParser(description="麒麟/Linux 文件传输服务端")
    parser.add_argument("-p", "--port", type=int, default=9000, help="监听端口 (默认: 9000)")
    parser.add_argument("-d", "--dir", default=None, help="接收文件目录 (默认: ~/LAN_Migrate_Received)")
    parser.add_argument("--daemon", action="store_true", help="后台运行")
    args = parser.parse_args()
    
    server = KylinServer(port=args.port, receive_dir=args.dir)
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[INFO] 收到中断信号，正在关闭...")
        server.stop()


if __name__ == "__main__":
    main()
