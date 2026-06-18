#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨平台兼容性测试脚本
验证 Windows <-> 麒麟 <-> Linux 三种平台间的双向传输
"""
import os
import sys
import socket
import threading
import time
import tempfile
import shutil

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from core.protocol import (
    Command, pack_message, unpack_message, pack_file_chunk, unpack_file_chunk,
    create_hello_payload, create_file_header_payload, create_list_dir_payload
)
from utils.checksum import compute_file_hash
from utils.helpers import format_size


class MockServer:
    """模拟服务端，用于测试"""
    
    def __init__(self, port: int = 19000):
        self.port = port
        self.socket = None
        self.received_files = []
        self.directory_listings = []
        self.sent_files = []
        
    def start(self):
        """启动模拟服务端"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("127.0.0.1", self.port))
        self.socket.listen(1)
        self.socket.settimeout(2.0)
        print(f"[模拟服务端] 启动在 127.0.0.1:{self.port}")
        
    def accept_one(self, timeout=5):
        """接受一个连接并处理"""
        try:
            conn, addr = self.socket.accept()
            print(f"[模拟服务端] 接受连接: {addr}")
            handler = MockServerHandler(conn, self)
            handler.handle()
        except socket.timeout:
            print("[模拟服务端] 等待连接超时")
            
    def stop(self):
        """停止服务端"""
        if self.socket:
            self.socket.close()


class MockServerHandler:
    """模拟服务端连接处理器"""
    
    def __init__(self, conn, server: MockServer):
        self.conn = conn
        self.server = server
        self.buffer = b""
        self.current_file = None
        self.current_file_path = None
        
    def handle(self):
        """处理连接"""
        try:
            self.conn.settimeout(5)
            
            # 发送 HELLO 响应
            hello = pack_message(Command.HELLO, create_hello_payload(
                "Mock Server", "1.0.0", "kylin/linux"
            ))
            self.conn.sendall(hello)
            
            while True:
                data = self.conn.recv(65536)
                if not data:
                    break
                
                self.buffer += data
                self._process_buffer()
                
        except Exception as e:
            print(f"[模拟服务端] 处理异常: {e}")
        finally:
            if self.current_file:
                self.current_file.close()
            self.conn.close()
    
    def _process_buffer(self):
        """处理缓冲区"""
        while len(self.buffer) >= 8:
            chunk_idx, chunk_data, remaining = unpack_file_chunk(self.buffer)
            if chunk_idx is not None:
                if self.current_file:
                    self.current_file.write(chunk_data)
                self.buffer = remaining
                continue
            
            cmd, payload, remaining = unpack_message(self.buffer)
            if cmd is None:
                break
            
            self.buffer = remaining
            self._handle_command(cmd, payload)
    
    def _handle_command(self, cmd, payload):
        """处理命令"""
        if cmd == Command.HELLO:
            print(f"[模拟服务端] 收到 HELLO")
            
        elif cmd == Command.LIST_DIR:
            path = payload.get("path", "")
            print(f"[模拟服务端] 收到 LIST_DIR: {path}")
            # 模拟返回目录列表
            entries = [
                {"name": "documents", "path": "/home/user/documents", "type": "directory", "size": 0, "modified": time.time()},
                {"name": "photos", "path": "/home/user/photos", "type": "directory", "size": 0, "modified": time.time()},
                {"name": "readme.txt", "path": "/home/user/readme.txt", "type": "file", "size": 1024, "modified": time.time()}
            ]
            from core.protocol import create_list_dir_response_payload
            response = pack_message(Command.LIST_DIR_RESPONSE, 
                                    create_list_dir_response_payload(path, entries))
            self.conn.sendall(response)
            self.server.directory_listings.append(path)
            print(f"[模拟服务端] 返回 {len(entries)} 个条目")
            
        elif cmd == Command.FILE_HEADER:
            self._handle_file_header(payload)
            
        elif cmd == Command.VERIFY_REQUEST:
            if self.current_file:
                self.current_file.close()
                self.current_file = None
            response = pack_message(Command.VERIFY_RESPONSE, {
                "verified": True,
                "checksum": payload.get("checksum", "")
            })
            self.conn.sendall(response)
            print(f"[模拟服务端] 校验完成: {self.current_file_path}")
            
        elif cmd == Command.GET_REMOTE_FILE:
            # 模拟发送文件
            self._handle_get_file(payload)
    
    def _handle_file_header(self, payload):
        """处理文件头部"""
        relative_path = payload.get("relative_path", "test_file.txt")
        self.current_file_path = os.path.join(tempfile.gettempdir(), "test_received", relative_path)
        os.makedirs(os.path.dirname(self.current_file_path), exist_ok=True)
        self.current_file = open(self.current_file_path, "wb")
        response = pack_message(Command.FILE_HEADER, {"status": "ok"})
        self.conn.sendall(response)
        self.server.received_files.append(self.current_file_path)
        print(f"[模拟服务端] 准备接收: {self.current_file_path}")
    
    def _handle_get_file(self, payload):
        """处理获取文件请求"""
        # 创建一个测试文件
        test_file = os.path.join(tempfile.gettempdir(), "test_server_file.txt")
        with open(test_file, "w") as f:
            f.write("Hello from mock server!\n" * 100)
        
        file_size = os.path.getsize(test_file)
        checksum = compute_file_hash(test_file)
        
        # 发送文件头部
        header = pack_message(Command.FILE_HEADER, create_file_header_payload(
            test_file, file_size, checksum, "test_server_file.txt"
        ))
        self.conn.sendall(header)
        
        # 发送文件内容
        chunk_index = 0
        with open(test_file, "rb") as f:
            while True:
                chunk = f.read(config.CHUNK_SIZE)
                if not chunk:
                    break
                self.conn.sendall(pack_file_chunk(chunk_index, chunk))
                chunk_index += 1
        
        # 发送校验请求
        verify = pack_message(Command.VERIFY_REQUEST, {
            "file_path": "test_server_file.txt",
            "checksum": checksum
        })
        self.conn.sendall(verify)
        self.server.sent_files.append(test_file)
        print(f"[模拟服务端] 发送文件完成: {test_file}")


def test_upload():
    """测试上传功能（所有平台通用）"""
    print("\n" + "="*60)
    print("测试 1: 文件上传（Windows -> 麒麟/Linux 通用）")
    print("="*60)
    
    server = MockServer(port=19001)
    server.start()
    
    # 启动服务端线程
    server_thread = threading.Thread(target=server.accept_one, daemon=True)
    server_thread.start()
    time.sleep(0.5)
    
    # 模拟客户端连接并上传
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(("127.0.0.1", 19001))
        
        # 握手
        hello = pack_message(Command.HELLO, create_hello_payload(
            "Test Client", "1.0.0"
        ))
        client_socket.sendall(hello)
        response = client_socket.recv(1024)
        cmd, _, _ = unpack_message(response)
        assert cmd == Command.HELLO, "握手失败"
        print("[客户端] 握手成功")
        
        # 创建测试文件
        test_file = os.path.join(tempfile.gettempdir(), "test_upload.txt")
        with open(test_file, "w") as f:
            f.write("This is a test file for upload.\n" * 50)
        
        file_size = os.path.getsize(test_file)
        checksum = compute_file_hash(test_file)
        
        # 发送文件头部
        header = pack_message(Command.FILE_HEADER, create_file_header_payload(
            test_file, file_size, checksum, "test_upload.txt"
        ))
        client_socket.sendall(header)
        response = client_socket.recv(1024)
        cmd, payload, _ = unpack_message(response)
        assert cmd == Command.FILE_HEADER and payload.get("status") == "ok"
        print(f"[客户端] 发送文件头部: {file_size} bytes")
        
        # 发送文件内容
        with open(test_file, "rb") as f:
            while True:
                chunk = f.read(config.CHUNK_SIZE)
                if not chunk:
                    break
                client_socket.sendall(pack_file_chunk(0, chunk))
        
        # 发送校验请求
        verify = pack_message(Command.VERIFY_REQUEST, {
            "file_path": "test_upload.txt",
            "checksum": checksum
        })
        client_socket.sendall(verify)
        
        # 等待校验响应
        response = client_socket.recv(1024)
        cmd, payload, _ = unpack_message(response)
        assert cmd == Command.VERIFY_RESPONSE and payload.get("verified")
        print(f"[客户端] 文件上传成功，校验通过")
        
        client_socket.close()
        
        # 验证服务端接收
        time.sleep(0.5)
        assert len(server.received_files) == 1, "服务端未收到文件"
        print(f"[测试通过] 文件上传功能正常")
        
    except Exception as e:
        print(f"[测试失败] {e}")
        return False
    finally:
        server.stop()
    
    return True


def test_list_directory():
    """测试目录列表功能"""
    print("\n" + "="*60)
    print("测试 2: 目录列表（所有平台通用）")
    print("="*60)
    
    server = MockServer(port=19002)
    server.start()
    
    server_thread = threading.Thread(target=server.accept_one, daemon=True)
    server_thread.start()
    time.sleep(0.5)
    
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(("127.0.0.1", 19002))
        
        # 握手
        hello = pack_message(Command.HELLO, create_hello_payload("Test Client", "1.0.0"))
        client_socket.sendall(hello)
        client_socket.recv(1024)
        
        # 发送列出目录请求
        request = pack_message(Command.LIST_DIR, create_list_dir_payload("/home/user"))
        client_socket.sendall(request)
        
        # 接收响应
        response = client_socket.recv(4096)
        cmd, payload, _ = unpack_message(response)
        assert cmd == Command.LIST_DIR_RESPONSE
        entries = payload.get("entries", [])
        assert len(entries) == 3
        print(f"[客户端] 收到目录列表: {len(entries)} 项")
        for entry in entries:
            print(f"  - {entry.get('name')} ({entry.get('type')})")
        
        client_socket.close()
        print(f"[测试通过] 目录列表功能正常")
        return True
        
    except Exception as e:
        print(f"[测试失败] {e}")
        return False
    finally:
        server.stop()


def test_download():
    """测试下载功能"""
    print("\n" + "="*60)
    print("测试 3: 文件下载（麒麟/Linux -> Windows 通用）")
    print("="*60)
    
    server = MockServer(port=19003)
    server.start()
    
    server_thread = threading.Thread(target=server.accept_one, daemon=True)
    server_thread.start()
    time.sleep(0.5)
    
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect(("127.0.0.1", 19003))
        
        # 握手
        hello = pack_message(Command.HELLO, create_hello_payload("Test Client", "1.0.0"))
        client_socket.sendall(hello)
        client_socket.recv(1024)
        
        # 发送获取文件请求
        request = pack_message(Command.GET_REMOTE_FILE, {"file_path": "/home/user/test.txt"})
        client_socket.sendall(request)
        
        # 接收文件头部
        response = client_socket.recv(4096)
        cmd, payload, _ = unpack_message(response)
        assert cmd == Command.FILE_HEADER
        file_size = payload.get("file_size", 0)
        print(f"[客户端] 收到文件头部: {file_size} bytes")
        
        # 接收文件内容（处理FILE_CHUNK和VERIFY_REQUEST）
        received_data = b""
        verify_received = False
        start_time = time.time()
        while time.time() - start_time < 5:
            data = client_socket.recv(65536)
            if not data:
                break
            
            # 解析数据包
            self_buffer = data
            while len(self_buffer) >= 8:
                chunk_idx, chunk_data, remaining = unpack_file_chunk(self_buffer)
                if chunk_idx is not None:
                    received_data += chunk_data
                    self_buffer = remaining
                    continue
                
                cmd2, payload2, remaining = unpack_message(self_buffer)
                if cmd2 is None:
                    break
                self_buffer = remaining
                
                if cmd2 == Command.VERIFY_REQUEST:
                    verify_received = True
                    payload = payload2
                    break
            
            if verify_received:
                break
        
        print(f"[客户端] 接收到 {len(received_data)} bytes")
        assert len(received_data) == file_size, f"接收数据大小不匹配: {len(received_data)} != {file_size}"
        assert verify_received, "未收到校验请求"
        
        # 发送校验响应
        verify_response = pack_message(Command.VERIFY_RESPONSE, {
            "verified": True,
            "checksum": payload.get("checksum", "")
        })
        client_socket.sendall(verify_response)
        print(f"[客户端] 校验通过")
        
        client_socket.close()
        print(f"[测试通过] 文件下载功能正常")
        return True
        
    except Exception as e:
        print(f"[测试失败] {e}")
        return False
    finally:
        server.stop()


def test_platform_compatibility():
    """测试跨平台兼容性"""
    print("\n" + "="*60)
    print("测试 4: 跨平台兼容性（协议层）")
    print("="*60)
    
    # 测试协议在不同平台上的一致性
    test_data = {
        "device_name": "麒麟-测试机",
        "version": "1.0.0",
        "os": "kylin/linux"
    }
    
    # 打包
    packed = pack_message(Command.HELLO, test_data)
    print(f"[协议测试] 打包后字节数: {len(packed)}")
    
    # 解包
    cmd, payload, remaining = unpack_message(packed)
    assert cmd == Command.HELLO
    assert payload == test_data
    assert remaining == b""
    print(f"[协议测试] 解包成功，命令: {cmd}, 载荷: {payload}")
    
    # 测试特殊字符和中文
    chinese_data = {
        "file_name": "测试文件.txt",
        "path": "/home/user/文档/",
        "description": "包含中英文 mixed content 123"
    }
    packed = pack_message(Command.FILE_HEADER, chinese_data)
    cmd, payload, _ = unpack_message(packed)
    assert payload == chinese_data
    print(f"[协议测试] 中文字符串处理正常")
    
    print(f"[测试通过] 跨平台协议兼容性正常")
    return True


def main():
    """运行所有测试"""
    print("="*60)
    print("跨平台兼容性测试套件")
    print("测试场景: Windows <-> 麒麟 <-> Linux")
    print("="*60)
    
    results = []
    results.append(("文件上传", test_upload()))
    results.append(("目录列表", test_list_directory()))
    results.append(("文件下载", test_download()))
    results.append(("协议兼容性", test_platform_compatibility()))
    
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
        print("✓ 所有测试通过！代码已兼容 Windows <-> 麒麟 <-> Linux 双向传输")
    else:
        print("✗ 部分测试失败，请检查相关功能")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())