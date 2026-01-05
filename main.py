"""
H2OGPTE to OpenAI API 转换服务

将 H2OGPTE 的 API 封装为标准的 OpenAI API 格式
支持 /v1/models 和 /v1/chat/completions 接口
"""
import json
import uuid
import time
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import config
from models import (
    Model, ModelsResponse,
    ChatMessage, ChatCompletionRequest, ChatCompletionResponse,
    ChatCompletionChoice, ChatCompletionChunk, ChatCompletionChunkChoice,
    DeltaMessage, Usage
)
from h2ogpte_client import h2ogpte_client
from session_manager import SessionManager


# ============ 应用初始化 ============

session_manager = SessionManager(h2ogpte_client)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print(f"🚀 H2OGPTE to OpenAI API 服务启动")
    print(f"📡 监听地址: http://{config.HOST}:{config.PORT}")
    print(f"🔗 目标服务: {config.H2OGPTE_BASE_URL}")
    print(f"🔄 启动会话池管理器...")
    await session_manager.start()
    yield
    print("👋 正在停止会话池...")
    await session_manager.stop()
    print("👋 服务关闭")


app = FastAPI(
    title="H2OGPTE to OpenAI API",
    description="将 H2OGPTE API 转换为标准 OpenAI API 格式",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ 辅助函数 ============

def generate_completion_id() -> str:
    """生成唯一的补全 ID"""
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def verify_api_key(authorization: Optional[str]) -> bool:
    """
    验证 API Key
    
    支持格式:
    - Bearer sk-xxx
    - sk-xxx
    
    如果未配置 API_KEY，则跳过验证
    """
    # 如果未配置 API_KEY，跳过验证
    if not config.API_KEY:
        return True
    
    if not authorization:
        return False
    
    # 提取 token
    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    
    # 验证 token
    return token == config.API_KEY


# ============ API 端点 ============

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "H2OGPTE to OpenAI API",
        "docs": "/docs",
        "endpoints": ["/v1/models", "/v1/chat/completions"]
    }


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(None)):
    """
    获取可用模型列表
    
    兼容 OpenAI API: GET /v1/models
    """
    if not verify_api_key(authorization):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    try:
        models_data = await h2ogpte_client.list_models()
        
        models = [
            Model(
                id=m.get("id", m.get("name", f"model-{i}")),
                created=int(time.time()),
                owned_by="h2ogpte"
            )
            for i, m in enumerate(models_data)
        ]
        
        return ModelsResponse(data=models)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")


@app.get("/v1/models/{model_id}")
async def get_model(model_id: str, authorization: Optional[str] = Header(None)):
    """
    获取单个模型信息
    
    兼容 OpenAI API: GET /v1/models/{model}
    """
    if not verify_api_key(authorization):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    return Model(id=model_id, created=int(time.time()), owned_by="h2ogpte")


@app.post("/v1/chat/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    authorization: Optional[str] = Header(None)
):
    """
    创建聊天补全
    
    兼容 OpenAI API: POST /v1/chat/completions
    支持流式和非流式响应
    """
    if not verify_api_key(authorization):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    try:
        # 提取系统提示词并构建完整的对话上下文
        system_prompt = None
        conversation_parts = []
        
        for msg in request.messages:
            if msg.role == "system":
                system_prompt = msg.content
            elif msg.role == "user":
                conversation_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                conversation_parts.append(f"Assistant: {msg.content}")
        
        # 将对话历史拼接成完整的消息
        # 如果只有一条用户消息，直接使用；否则拼接完整上下文
        if len(conversation_parts) == 1:
            user_message = request.messages[-1].content if request.messages else ""
        else:
            # 拼接对话历史，添加最终的提示
            user_message = "\n".join(conversation_parts)
            # 如果最后不是用户消息，添加提示
            if not user_message.endswith(conversation_parts[-1]):
                user_message += "\nAssistant:"
        
        # 如果没有用户消息，使用最后一条消息
        if not user_message and request.messages:
            user_message = request.messages[-1].content
        
        # 从会话池获取聊天会话
        chat_id = await session_manager.get_session()
        
        if request.stream:
            # 流式响应
            return StreamingResponse(
                stream_chat_completion(
                    chat_id=chat_id,
                    message=user_message,
                    model=request.model,
                    system_prompt=system_prompt,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens
                ),
                media_type="text/event-stream"
            )
        else:
            # 非流式响应
            response_content = await h2ogpte_client.send_message(
                message=user_message,
                chat_id=chat_id,
                model=request.model,
                system_prompt=system_prompt,
                temperature=request.temperature,
                max_tokens=request.max_tokens
            )
            
            # 回收聊天会话
            await session_manager.recycle_session(chat_id)
            
            completion_id = generate_completion_id()
            
            return ChatCompletionResponse(
                id=completion_id,
                model=request.model,
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatMessage(
                            role="assistant",
                            content=response_content
                        ),
                        finish_reason="stop"
                    )
                ],
                usage=Usage(
                    prompt_tokens=len(user_message) // 4,  # 粗略估算
                    completion_tokens=len(response_content) // 4,
                    total_tokens=(len(user_message) + len(response_content)) // 4
                )
            )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"聊天补全失败: {str(e)}")


async def stream_chat_completion(
    chat_id: str,
    message: str,
    model: str,
    system_prompt: Optional[str],
    temperature: float,
    max_tokens: Optional[int]
):
    """生成流式聊天补全响应"""
    completion_id = generate_completion_id()
    created = int(time.time())
    
    # 发送角色信息
    chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=DeltaMessage(role="assistant"),
                finish_reason=None
            )
        ]
    )
    yield f"data: {chunk.model_dump_json()}\n\n"
    
    try:
        # 流式获取内容
        async for content_chunk in h2ogpte_client.send_message_stream(
            message=message,
            chat_id=chat_id,
            model=model,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens
        ):
            chunk = ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=DeltaMessage(content=content_chunk),
                        finish_reason=None
                    )
                ]
            )
            yield f"data: {chunk.model_dump_json()}\n\n"
    
    except Exception as e:
        # 发送错误信息作为内容
        error_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=DeltaMessage(content=f"[Error: {str(e)}]"),
                    finish_reason=None
                )
            ]
        )
        yield f"data: {error_chunk.model_dump_json()}\n\n"
    
    # 发送结束信号
    final_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=DeltaMessage(),
                finish_reason="stop"
            )
        ]
    )
    yield f"data: {final_chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"
    
    # 回收聊天会话
    await session_manager.recycle_session(chat_id)


# ============ 启动入口 ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True
    )
