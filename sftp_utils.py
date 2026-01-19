# sftp_utils.py
"""
SFTP传输模块 - 替代SMB映射，直接通过SSH传输文件
"""

import os
import stat
import paramiko
from pathlib import Path
from contextlib import contextmanager
import threading
from config import (
    NAS_SFTP_HOST, NAS_SFTP_PORT, NAS_SFTP_USER, NAS_SFTP_KEY_PATH,
    NAS_POOL_PATH, NAS_RESULTS_PATH
)

# 连接池（复用连接）
_sftp_client = None
_ssh_client = None
_conn_lock = threading.Lock()
_thread_local = threading.local()


def _connect(retry: int = 3):
    """获取当前线程的 SFTP 连接（自动重连）"""
    
    # 尝试复用当前线程的连接
    sftp = getattr(_thread_local, 'sftp', None)
    ssh = getattr(_thread_local, 'ssh', None)
    
    if sftp is not None:
        try:
            sftp.stat('.')
            return sftp
        except:
            _close()
    
    # 重试建立新连接
    last_err = None
    for attempt in range(retry):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            private_key = paramiko.Ed25519Key.from_private_key_file(NAS_SFTP_KEY_PATH)
            
            ssh.connect(
                hostname=NAS_SFTP_HOST,
                port=NAS_SFTP_PORT,
                username=NAS_SFTP_USER,
                pkey=private_key,
                timeout=30,
                banner_timeout=30,
                auth_timeout=30,
            )
            
            sftp = ssh.open_sftp()
            sftp.get_channel().settimeout(120)
            
            # 保存到线程本地
            _thread_local.ssh = ssh
            _thread_local.sftp = sftp
            
            return sftp
            
        except Exception as e:
            last_err = e
            _close()
            if attempt < retry - 1:
                import time
                time.sleep(2 * (attempt + 1))
    
    raise ConnectionError(f"SFTP connect failed after {retry} attempts: {last_err}")


def _close():
    """关闭当前线程的连接"""
    sftp = getattr(_thread_local, 'sftp', None)
    ssh = getattr(_thread_local, 'ssh', None)
    
    try:
        if sftp:
            sftp.close()
    except:
        pass
    try:
        if ssh:
            ssh.close()
    except:
        pass
    
    _thread_local.sftp = None
    _thread_local.ssh = None


def sftp_download_file(remote_path: str, local_path: str, retry: int = 3):
    """下载单个文件，带重试"""
    import time
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    last_err = None
    for attempt in range(retry):
        try:
            sftp = _connect()
            sftp.get(remote_path, local_path)
            return
        except Exception as e:
            last_err = e
            _close()  # 强制重连
            if attempt < retry - 1:
                time.sleep(1 * (attempt + 1))
    
    raise last_err


def sftp_upload_file(local_path: str, remote_path: str, retry: int = 3):
    """上传单个文件，带重试"""
    import time
    
    last_err = None
    for attempt in range(retry):
        try:
            sftp = _connect()
            _sftp_makedirs(sftp, os.path.dirname(remote_path))
            sftp.put(local_path, remote_path)
            return
        except Exception as e:
            last_err = e
            _close()  # 强制重连
            if attempt < retry - 1:
                time.sleep(1 * (attempt + 1))
    
    raise last_err


def sftp_download_folder(remote_dir: str, local_dir: str, callback=None):
    """
    递归下载整个文件夹
    callback: 可选，每下载一个文件调用 callback(filename)
    """
    sftp = _connect()
    os.makedirs(local_dir, exist_ok=True)
    
    for entry in sftp.listdir_attr(remote_dir):
        remote_path = f"{remote_dir}/{entry.filename}"
        local_path = os.path.join(local_dir, entry.filename)
        
        if stat.S_ISDIR(entry.st_mode):
            sftp_download_folder(remote_path, local_path, callback)
        else:
            sftp.get(remote_path, local_path)
            if callback:
                callback(entry.filename)


def sftp_upload_folder(local_dir: str, remote_dir: str, callback=None):
    """
    递归上传整个文件夹
    callback: 可选，每上传一个文件调用 callback(filename)
    """
    sftp = _connect()
    _sftp_makedirs(sftp, remote_dir)
    
    for root, dirs, files in os.walk(local_dir):
        # 计算相对路径
        rel_root = os.path.relpath(root, local_dir)
        if rel_root == '.':
            remote_root = remote_dir
        else:
            remote_root = f"{remote_dir}/{rel_root.replace(os.sep, '/')}"
        
        # 创建远程目录
        for d in dirs:
            _sftp_makedirs(sftp, f"{remote_root}/{d}")
        
        # 上传文件
        for f in files:
            local_path = os.path.join(root, f)
            remote_path = f"{remote_root}/{f}"
            sftp.put(local_path, remote_path)
            if callback:
                callback(f)


def sftp_list_cases(subdir: str = "") -> list:
    """
    列出池子中的案例文件夹
    subdir: 子目录，如 "inbox" 或 ""
    返回: 文件夹名列表
    """
    sftp = _connect()
    remote_dir = f"{NAS_POOL_PATH}/{subdir}".rstrip('/')
    
    result = []
    try:
        for entry in sftp.listdir_attr(remote_dir):
            if stat.S_ISDIR(entry.st_mode):
                result.append(entry.filename)
    except FileNotFoundError:
        pass
    return result


def sftp_exists(remote_path: str) -> bool:
    """检查远程路径是否存在"""
    sftp = _connect()
    try:
        sftp.stat(remote_path)
        return True
    except FileNotFoundError:
        return False


def sftp_rename(old_path: str, new_path: str):
    """重命名/移动远程文件或文件夹"""
    sftp = _connect()
    _sftp_makedirs(sftp, os.path.dirname(new_path))
    sftp.rename(old_path, new_path)


def sftp_remove_folder(remote_dir: str):
    """递归删除远程文件夹"""
    sftp = _connect()
    try:
        for entry in sftp.listdir_attr(remote_dir):
            remote_path = f"{remote_dir}/{entry.filename}"
            if stat.S_ISDIR(entry.st_mode):
                sftp_remove_folder(remote_path)
            else:
                sftp.remove(remote_path)
        sftp.rmdir(remote_dir)
    except FileNotFoundError:
        pass


def _sftp_makedirs(sftp, remote_dir: str):
    """递归创建远程目录（类似os.makedirs）"""
    if not remote_dir or remote_dir == '/':
        return
    
    try:
        sftp.stat(remote_dir)
        return  # 已存在
    except FileNotFoundError:
        pass
    
    # 递归创建父目录
    parent = os.path.dirname(remote_dir)
    if parent and parent != remote_dir:
        _sftp_makedirs(sftp, parent)
    
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass  # 可能已被其他进程创建


# ============ 业务层封装 ============

def download_case_from_pool(case_name: str, local_work_dir: str, pool_subdir: str = "inbox"):
    """
    从池子下载案例到本地工作目录
    
    Args:
        case_name: 案例名称
        local_work_dir: 本地工作目录
        pool_subdir: 池子子目录 (inbox/processing/finished)
    
    Returns:
        本地案例路径
    """
    remote_case_dir = f"{NAS_POOL_PATH}/{pool_subdir}/{case_name}"
    local_case_dir = os.path.join(local_work_dir, case_name)
    
    sftp_download_folder(remote_case_dir, local_case_dir)
    return local_case_dir


def upload_result_to_nas(local_case_dir: str, case_name: str):
    """
    上传计算结果到NAS结果目录
    
    Args:
        local_case_dir: 本地案例目录
        case_name: 案例名称（用于远程目录名）
    """
    remote_result_dir = f"{NAS_RESULTS_PATH}/{case_name}"
    sftp_upload_folder(local_case_dir, remote_result_dir)


def move_case_in_pool(case_name: str, from_subdir: str, to_subdir: str):
    """
    在池子内移动案例（如 inbox -> processing）
    """
    old_path = f"{NAS_POOL_PATH}/{from_subdir}/{case_name}"
    new_path = f"{NAS_POOL_PATH}/{to_subdir}/{case_name}"
    sftp_rename(old_path, new_path)


def delete_case_from_pool(case_name: str, pool_subdir: str = "finished"):
    """
    从池子中删除案例
    """
    remote_path = f"{NAS_POOL_PATH}/{pool_subdir}/{case_name}"
    sftp_remove_folder(remote_path)


def sftp_remove_file(remote_path: str):
    """删除远程单个文件"""
    sftp = _connect()
    try:
        sftp.remove(remote_path)
    except FileNotFoundError:
        pass
