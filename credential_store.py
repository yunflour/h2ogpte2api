"""凭证存储模块

管理本地凭证文件的读写和自动刷新
"""
import json
import os
import asyncio
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class StoredCredential:
    """存储的凭证数据"""
    session: str
    csrf_token: str
    user_id: str
    username: str
    created_at: str
    last_used_at: str


class CredentialStore:
    """凭证存储管理器"""
    
    DEFAULT_FILE = "guest_credentials.json"
    
    def __init__(self, file_path: Optional[str] = None):
        """
        初始化凭证存储
        
        Args:
            file_path: 凭证文件路径，默认为当前目录下的 guest_credentials.json
        """
        if file_path:
            self.file_path = Path(file_path)
        else:
            # 默认存储在项目目录下
            self.file_path = Path(__file__).parent / self.DEFAULT_FILE
        
        self._credential: Optional[StoredCredential] = None
        self._lock = asyncio.Lock()
    
    def _load_from_file(self) -> Optional[StoredCredential]:
        """从文件加载凭证"""
        if not self.file_path.exists():
            return None
        
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return StoredCredential(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            print(f"加载凭证文件失败: {e}")
            return None
    
    def _save_to_file(self, credential: StoredCredential) -> bool:
        """保存凭证到文件"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(asdict(credential), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存凭证文件失败: {e}")
            return False
    
    async def get_credential(self) -> Optional[StoredCredential]:
        """
        获取当前凭证
        
        如果内存中没有，尝试从文件加载
        """
        async with self._lock:
            if self._credential is None:
                self._credential = self._load_from_file()
            
            if self._credential:
                # 更新最后使用时间
                self._credential.last_used_at = datetime.now().isoformat()
            
            return self._credential
    
    async def save_credential(
        self, 
        session: str, 
        csrf_token: str, 
        user_id: str = "",
        username: str = ""
    ) -> bool:
        """
        保存新凭证
        
        Args:
            session: h2ogpte.session cookie 值
            csrf_token: CSRF token
            user_id: 用户 ID
            username: 用户名
        """
        async with self._lock:
            now = datetime.now().isoformat()
            self._credential = StoredCredential(
                session=session,
                csrf_token=csrf_token,
                user_id=user_id,
                username=username,
                created_at=now,
                last_used_at=now
            )
            return self._save_to_file(self._credential)
    
    async def clear_credential(self) -> bool:
        """清除凭证"""
        async with self._lock:
            self._credential = None
            if self.file_path.exists():
                try:
                    os.remove(self.file_path)
                    return True
                except Exception as e:
                    print(f"删除凭证文件失败: {e}")
                    return False
            return True
    
    async def renew_session(self) -> Optional[StoredCredential]:
        """
        续期当前 Guest 的 session
        
        用现有 cookie 重新访问页面获取新的 session 和 csrf_token
        
        Returns:
            更新后的凭证，如果失败返回 None
        """
        import httpx
        import re
        import json as json_module
        
        current_cred = await self.get_credential()
        if not current_cred or not current_cred.session:
            print("没有现有凭证，无法续期")
            return None
        
        print(f"正在续期 {current_cred.username} 的 session...")
        
        try:
            headers = {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            cookies = {
                "h2ogpte.session": current_cred.session
            }
            
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(
                    "https://h2ogpte.genai.h2o.ai/chats",
                    headers=headers,
                    cookies=cookies,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    print(f"续期请求失败: {response.status_code}")
                    return None
                
                # 尝试从响应或重定向历史获取新的 session
                new_session = None
                for r in [response] + list(response.history):
                    for header in r.headers.get_list("set-cookie"):
                        if "h2ogpte.session=" in header:
                            match = re.search(r'h2ogpte\.session=([^;]+)', header)
                            if match:
                                new_session = match.group(1)
                                break
                    if new_session:
                        break
                
                # 如果没有新 session，继续使用旧的
                if not new_session:
                    new_session = current_cred.session
                
                # 提取新的 csrf_token
                html = response.text
                start_marker = "data-conf='"
                start = html.find(start_marker)
                if start >= 0:
                    start += len(start_marker)
                    end = html.find("'", start)
                    if end > start:
                        config_json = html[start:end]
                        try:
                            config_data = json_module.loads(config_json)
                            new_csrf = config_data.get("csrf_token", "")
                            new_user_id = config_data.get("user_id", current_cred.user_id)
                            new_username = config_data.get("username", current_cred.username)
                            
                            # Guest 模式：持久化到文件
                            # 用户模式：只更新内存，不持久化
                            from config import config as app_config
                            if app_config.IS_GUEST:
                                await self.save_credential(
                                    session=new_session,
                                    csrf_token=new_csrf,
                                    user_id=new_user_id,
                                    username=new_username
                                )
                            else:
                                # 用户模式：只更新内存中的凭证
                                self._credential = StoredCredential(
                                    session=new_session,
                                    csrf_token=new_csrf,
                                    user_id=new_user_id,
                                    username=new_username,
                                    created_at=current_cred.created_at,
                                    last_used_at=datetime.now().isoformat()
                                )
                            print(f"续期成功: {new_username}")
                            return self._credential
                        except json_module.JSONDecodeError:
                            pass
                
                print("续期失败: 无法解析新 token")
                return None
                
        except Exception as e:
            print(f"续期失败: {e}")
            return None
    
    async def refresh_credential(self) -> Optional[StoredCredential]:
        """
        获取全新的 Guest 凭证（新账号）
        
        用于没有凭证或当前 Guest 额度耗尽时
        
        Returns:
            新的凭证，如果失败返回 None
        """
        return await self._fetch_new_guest()
    
    async def _fetch_new_guest(self) -> Optional[StoredCredential]:
        """获取全新的 Guest 凭证（内部方法）"""
        import httpx
        import re
        import json as json_module
        
        print("正在获取新的 Guest 凭证...")
        
        try:
            headers = {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            # 不带 cookie 的请求会获得新 Guest
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(
                    "https://h2ogpte.genai.h2o.ai/chats",
                    headers=headers,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    print(f"获取新凭证失败: {response.status_code}")
                    return None
                
                # 从重定向历史获取 session
                new_session = None
                for r in list(response.history) + [response]:
                    for header in r.headers.get_list("set-cookie"):
                        if "h2ogpte.session=" in header:
                            match = re.search(r'h2ogpte\.session=([^;]+)', header)
                            if match:
                                new_session = match.group(1)
                                break
                    if new_session:
                        break
                
                if not new_session:
                    print("获取新凭证失败: 无法获取 session")
                    return None
                
                # 提取 csrf_token 和用户信息
                html = response.text
                start_marker = "data-conf='"
                start = html.find(start_marker)
                if start >= 0:
                    start += len(start_marker)
                    end = html.find("'", start)
                    if end > start:
                        config_json = html[start:end]
                        try:
                            config_data = json_module.loads(config_json)
                            new_csrf = config_data.get("csrf_token", "")
                            new_user_id = config_data.get("user_id", "")
                            new_username = config_data.get("username", "")
                            
                            await self.save_credential(
                                session=new_session,
                                csrf_token=new_csrf,
                                user_id=new_user_id,
                                username=new_username
                            )
                            print(f"获取新凭证成功: {new_username}")
                            return self._credential
                        except json_module.JSONDecodeError:
                            pass
                
                print("获取新凭证失败: 无法解析配置")
                return None
                
        except Exception as e:
            print(f"获取新凭证失败: {e}")
            return None
    
    
    def get_session(self) -> str:
        """同步获取 session（用于配置）"""
        if self._credential:
            return self._credential.session
        cred = self._load_from_file()
        return cred.session if cred else ""
    
    def get_csrf_token(self) -> str:
        """同步获取 CSRF token（用于配置）"""
        if self._credential:
            return self._credential.csrf_token
        cred = self._load_from_file()
        return cred.csrf_token if cred else ""


# 全局凭证存储实例
credential_store = CredentialStore()
