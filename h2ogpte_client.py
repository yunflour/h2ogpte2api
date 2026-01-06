"""H2OGPTE API 客户端

基于浏览器分析的结果：
- /rpc/db: 用于 session 管理和历史查询
- WebSocket (wss://h2ogpte.genai.h2o.ai/ws): 用于实时聊天消息

RPC 方法:
- create_chat_session: ["create_chat_session", null, "workspaces/h2ogpte-guest"]
- list_chat_messages_full: ["list_chat_messages_full", session_id, offset, limit]
- get_chat_session: ["get_chat_session", session_id]

WebSocket 消息格式:
- 发送: {"t": "cq", "session_id": "...", "body": "...", "llm": "auto", ...}
- 接收: {"t": "cp", ...} (partial) 或 {"t": "ca", ...} (answer)
"""
import httpx
import json
import uuid
import asyncio
import websockets
from typing import AsyncGenerator, Optional, List, Dict, Any
from config import config


class H2OGPTEClient:
    """H2OGPTE 客户端"""
    
    # 类级别的刷新锁，确保并发401时只刷新一次
    _refresh_lock: Optional[asyncio.Lock] = None
    _refreshing: bool = False
    
    def __init__(self):
        self.base_url = config.H2OGPTE_BASE_URL
        self.rpc_db_endpoint = f"{self.base_url}/rpc/db"
        self.ws_endpoint = self.base_url.replace("https://", "wss://") + "/ws"
        self._initialized = False
        
        # 初始化刷新锁
        if H2OGPTEClient._refresh_lock is None:
            H2OGPTEClient._refresh_lock = asyncio.Lock()
    
    @property
    def headers(self) -> dict:
        """动态获取请求头"""
        return config.get_headers()
    
    @property
    def cookies(self) -> dict:
        """动态获取 cookies"""
        return config.get_cookies()
    
    def _get_cookie_header(self) -> str:
        """获取 Cookie 头字符串"""
        return "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
    
    async def _ensure_credentials(self) -> bool:
        """确保有有效的凭证"""
        # 检查是否已有凭证
        if config.get_session() and config.get_csrf_token():
            return True
        
        # Guest 模式下尝试获取新凭证
        if config.IS_GUEST:
            return await self._refresh_credentials()
        
        # 非 Guest 模式没有凭证时报错
        print("非 Guest 模式，请在 .env 中配置 H2OGPTE_SESSION 和 H2OGPTE_CSRF_TOKEN")
        return False
    
    async def _refresh_credentials(self, force_new: bool = False) -> bool:
        """
        刷新凭证（Guest 和非 Guest 模式均支持）
        
        使用锁确保并发401时只刷新一次
        
        Args:
            force_new: 是否强制获取新 Guest（仅 Guest 模式有效）
        """
        # 使用锁确保只刷新一次
        async with H2OGPTEClient._refresh_lock:
            # 再次检查，可能其他请求已经刷新成功
            if not force_new and config.get_session() and config.get_csrf_token():
                # 如果刚刚有其他请求刷新成功，直接返回
                if H2OGPTEClient._refreshing:
                    H2OGPTEClient._refreshing = False
                    return True
            
            H2OGPTEClient._refreshing = True
            
            from credential_store import credential_store
            
            if not force_new:
                # 优先尝试续期当前账号（保持同一账号，利用现有额度）
                cred = await credential_store.renew_session()
                if cred:
                    config.update_credentials(cred.session, cred.csrf_token)
                    return True
            
            # Guest 模式：续期失败则获取新 Guest
            if config.IS_GUEST:
                cred = await credential_store.refresh_credential()
                if cred:
                    config.update_credentials(cred.session, cred.csrf_token)
                    return True
            
            return False
    
    async def _rpc_db(self, method: str, *args) -> Any:
        """调用 /rpc/db 端点，支持 401/429 自动刷新"""
        # 确保有凭证
        await self._ensure_credentials()
        
        payload = json.dumps([method, *args])
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.rpc_db_endpoint,
                headers=self.headers,
                cookies=self.cookies,
                content=payload,
                timeout=60.0
            )
            
            # 401 错误：凭证失效，尝试续期
            if response.status_code == 401:
                print("检测到 401 Unauthorized，正在刷新凭证...")
                if await self._refresh_credentials():
                    response = await client.post(
                        self.rpc_db_endpoint,
                        headers=self.headers,
                        cookies=self.cookies,
                        content=payload,
                        timeout=60.0
                    )
            
            # 429 错误：配额耗尽，获取新 Guest（仅 Guest 模式）
            if response.status_code == 429 and config.IS_GUEST:
                print("检测到 429 Too Many Requests，Guest 配额耗尽，正在获取新 Guest...")
                if await self._refresh_credentials(force_new=True):
                    response = await client.post(
                        self.rpc_db_endpoint,
                        headers=self.headers,
                        cookies=self.cookies,
                        content=payload,
                        timeout=60.0
                    )
            
            response.raise_for_status()
            return response.json()
    
    # ============ 模型相关 ============
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """获取可用模型列表"""
        # 返回默认模型列表（基于浏览器观察到的模型）
        return [
            {"id": "auto", "name": "Autoselect LLM"},
            {"id": "claude-sonnet-4-5-20250929", "name": "Claude Sonnet 4.5"},
            {"id": "claude-3-7-sonnet", "name": "Claude 3.7 Sonnet"},
            {"id": "claude-3-5-sonnet", "name": "Claude 3.5 Sonnet"},
            {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1"},
            {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3"},
            {"id": "gpt-4.1", "name": "GPT-4.1"},
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "gpt-5", "name": "GPT-5"},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        ]
    
    # ============ 聊天会话相关 ============
    
    async def create_chat_session(self, workspace: Optional[str] = None) -> str:
        """创建新的聊天会话"""
        try:
            # 如果未指定 workspace，使用配置中的默认值
            target_workspace = workspace or config.H2OGPTE_WORKSPACE_ID
            
            # 正确的参数格式: ["create_chat_session", null, "workspaces/uuid"]
            result = await self._rpc_db("create_chat_session", None, target_workspace)
            if isinstance(result, dict):
                return result.get("id", str(uuid.uuid4()))
            elif isinstance(result, str):
                return result
            return str(uuid.uuid4())
        except Exception as e:
            print(f"创建聊天会话失败: {e}")
            return str(uuid.uuid4())
    
    async def get_chat_session(self, session_id: str) -> Dict[str, Any]:
        """获取聊天会话信息"""
        try:
            return await self._rpc_db("get_chat_session", session_id)
        except Exception as e:
            print(f"获取聊天会话失败: {e}")
            return {}
    
    async def list_chat_messages_full(
        self, 
        session_id: str, 
        offset: int = 0, 
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取聊天历史消息"""
        try:
            result = await self._rpc_db("list_chat_messages_full", session_id, offset, limit)
            return result if isinstance(result, list) else []
        except Exception as e:
            print(f"获取聊天消息失败: {e}")
            return []
    
    async def _rpc_job(self, method: str, params: Dict[str, Any]) -> Any:
        """调用 /rpc/job 端点，支持 401/429 自动刷新"""
        await self._ensure_credentials()
        
        payload = json.dumps([method, params])
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/rpc/job",
                headers=self.headers,
                cookies=self.cookies,
                content=payload,
                timeout=60.0
            )
            
            # 401 错误：凭证失效，尝试续期
            if response.status_code == 401:
                print("检测到 401 Unauthorized，正在刷新凭证...")
                if await self._refresh_credentials():
                    response = await client.post(
                        f"{self.base_url}/rpc/job",
                        headers=self.headers,
                        cookies=self.cookies,
                        content=payload,
                        timeout=60.0
                    )
            
            # 429 错误：配额耗尽，获取新 Guest（仅 Guest 模式）
            if response.status_code == 429 and config.IS_GUEST:
                print("检测到 429 Too Many Requests，Guest 配额耗尽，正在获取新 Guest...")
                if await self._refresh_credentials(force_new=True):
                    response = await client.post(
                        f"{self.base_url}/rpc/job",
                        headers=self.headers,
                        cookies=self.cookies,
                        content=payload,
                        timeout=60.0
                    )
            
            response.raise_for_status()
            return response.json()
    
    async def delete_chat_session(self, session_id: str) -> bool:
        """删除聊天会话"""
        try:
            result = await self._rpc_job(
                "q:crawl_quick.DeleteChatSessionsJob",
                {
                    "name": "Deleting Chat Sessions",
                    "chat_session_ids": [session_id]
                }
            )
            return True
        except Exception as e:
            print(f"删除聊天会话失败: {e}")
            return False
    
    # ============ WebSocket 聊天 ============
    
    async def send_message(
        self,
        message: str,
        chat_id: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """发送消息并获取完整回复（非流式）"""
        # 创建会话（如果需要）
        if not chat_id:
            chat_id = await self.create_chat_session()
        
        full_response = ""
        async for chunk in self._ws_chat(
            session_id=chat_id,
            message=message,
            llm=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens
        ):
            full_response += chunk
        
        return full_response
    
    async def send_message_stream(
        self,
        message: str,
        chat_id: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        """发送消息并获取流式回复"""
        # 创建会话（如果需要）
        if not chat_id:
            chat_id = await self.create_chat_session()
        
        async for chunk in self._ws_chat(
            session_id=chat_id,
            message=message,
            llm=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens
        ):
            yield chunk
    
    async def _ws_chat(
        self,
        session_id: str,
        message: str,
        llm: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        """通过 WebSocket 进行聊天"""
        ws_url = f"{self.ws_endpoint}?currentSessionID={session_id}"
        
        # 准备 WebSocket headers
        ws_headers = {
            "Cookie": self._get_cookie_header(),
            "Origin": self.base_url,
            "User-Agent": self.headers.get("user-agent", ""),
        }
        
        # 构建 LLM 参数（与浏览器捕获的格式一致）
        llm_args = {
            "enable_vision": "auto",
            "visible_vision_models": ["auto"],
            "use_agent": False,
            "cost_controls": {
                "max_cost": 0.05,
                "willingness_to_pay": 1,
                "willingness_to_wait": 60
            },
            "remove_non_private": False
        }
        if temperature:
            llm_args["temperature"] = min(max(temperature, 0), 1.0)
        
        # 构建 RAG 配置
        rag_config = {
            "rag_type": "auto",
            "hyde_no_rag_llm_prompt_extension": None,
            "num_neighbor_chunks_to_include": 1,
            "meta_data_to_include": {
                "name": True,
                "page": True,
                "text": True,
                "captions": True
            }
        }
        
        # 构建聊天请求（完整格式）
        chat_request = {
            "t": "cq",  # Chat Query
            "mode": "s",  # Stream mode
            "session_id": session_id,
            "correlation_id": str(uuid.uuid4()),  # 关键：客户端生成的 correlation ID
            "body": message,
            "llm": llm or "auto",
            "llm_args": json.dumps(llm_args),
            "self_reflection_config": "null",
            "rag_config": json.dumps(rag_config),
            "include_chat_history": "auto",
            "tags": [],
            "prompt_template_id": config.H2OGPTE_PROMPT_TEMPLATE_ID if config.H2OGPTE_PROMPT_TEMPLATE_ID else None
        }
        
        if system_prompt:
            chat_request["system_prompt"] = system_prompt
        
        try:
            async with websockets.connect(
                ws_url,
                additional_headers=ws_headers,
                ping_timeout=60,
                close_timeout=10
            ) as websocket:
                # 发送聊天请求
                await websocket.send(json.dumps(chat_request))
                
                # 用于收集流式响应的变量
                collected_response = ""
                
                # 接收响应
                while True:
                    try:
                        response = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=120.0  # 增加超时时间
                        )
                        
                        data = json.loads(response)
                        msg_type = data.get("t", "")
                        
                        if msg_type == "cx":  # Chat context/initial
                            # 初始响应，包含 message_id
                            continue
                        
                        elif msg_type == "cp":  # Chat Partial
                            # 流式响应片段
                            content = data.get("body", "")
                            if content:
                                yield content
                                collected_response += content
                        
                        elif msg_type == "cr":  # Chat Response (full accumulated)
                            # 完整累积响应
                            content = data.get("body", "")
                            # 如果之前没有收到流式片段，使用完整响应
                            if not collected_response and content:
                                yield content
                            continue
                        
                        elif msg_type == "ca":  # Chat Answer (final metadata)
                            # 最终元数据（包含 usage_stats 等）
                            # 不需要再 yield 内容
                            break
                        
                        elif msg_type == "ce":  # Chat Error
                            error_msg = data.get("error", data.get("body", "Unknown error"))
                            raise Exception(f"聊天错误: {error_msg}")
                        
                        elif msg_type == "cd":  # Chat Done
                            break
                        
                    except asyncio.TimeoutError:
                        print("WebSocket 响应超时")
                        break
                    except websockets.exceptions.ConnectionClosed:
                        print("WebSocket 连接关闭")
                        break
                        
        except Exception as e:
            print(f"WebSocket 聊天失败: {e}")
            raise


# 全局客户端实例
h2ogpte_client = H2OGPTEClient()
