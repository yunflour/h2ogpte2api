# H2OGPTE to OpenAI API

将 H2OGPTE 的 API 封装为标准的 OpenAI API 格式，方便与各种 AI 应用和工具集成。

## 功能特性

- ✅ `/v1/models` - 获取可用模型列表
- ✅ `/v1/chat/completions` - 聊天补全接口（支持流式和非流式）
- ✅ 会话池 (Session Pool) - 后台自动管理和预热会话，提升响应速度
- ✅ 自动凭据管理 - 支持 Guest 用户自动获取和续期凭据
- ✅ 标准 OpenAI API 格式响应
- ✅ CORS 支持

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填写你的配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
H2OGPTE_BASE_URL=https://h2ogpte.genai.h2o.ai
IS_GUEST=true (默认为 true,若为true,以下不填)
H2OGPTE_SESSION=your-session-id-here (如果 IS_GUEST 为 false 则必填)
H2OGPTE_CSRF_TOKEN=your-csrf-token-here (如果 IS_GUEST 为 false 则必填)
H2OGPTE_WORKSPACE_ID=workspaces/your-uuid-here (workspaces/h2ogpte-guest或用户自定义的uuid)
H2OGPTE_PROMPT_TEMPLATE_ID=your-prompt-template-uuid (可选，若为guest模式则必须置空)
API_KEY=your-secret-key (可选)
```

> **获取凭据 (非 Guest 模式)**：
> 1. 登录 h2ogpte 网站
> 2. 打开浏览器开发者工具 (F12)
> 3. **Session ID & Token**: 在网络请求中找到 Cookie (`h2ogpte.session`) 和 Header (`x-csrf-token`)
> 4. **Workspace ID**: 查看浏览器地址栏或网络请求，格式通常为 `workspaces/uuid`。如果是 guest 用户，默认为 `workspaces/h2ogpte-guest`。
> 5. **Prompt Template ID**: 在 "Customize chat" > "Prompts" 中选择模板后，从网络请求 `set_chat_session_prompt_template` 的参数中获取 UUID。

### 3. 启动服务

```bash
python main.py
```

服务将在 `http://localhost:<PORT>` 启动，未设置 `PORT` 时默认使用 `2156`。

## API 使用

### 获取模型列表

```bash
curl http://localhost:2156/v1/models
```

### 聊天补全（非流式）

```bash
curl http://localhost:2156/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'
```

### 聊天补全（流式）

```bash
curl http://localhost:2156/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "你好"}
    ],
    "stream": true
  }'
```

## 与第三方应用集成

可以将此服务作为 OpenAI API 的替代，配置到各种支持自定义 API 端点的应用中：

```
API Base URL: http://localhost:2156/v1
API Key: any-value (当前未启用验证)
```

## 项目结构

```
h2ogpt2api/
├── main.py                 # FastAPI 主应用
├── config.py               # 配置管理
├── models.py               # Pydantic 数据模型
├── h2ogpte_client.py       # H2OGPTE API 客户端
├── session_manager.py      # 会话池管理器
├── credential_store.py     # 凭据存储管理（自动续期逻辑）
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量模板
└── README.md               # 项目说明
```

## 注意事项

1. **Session & 凭据**：程序支持自动管理 Guest 凭据。对于登录用户，建议定期更新 Session ID。
2. **会自动续期**：Guest 模式下，程序会自动检测 401 错误并尝试重新获取凭据。
3. **请求限制**：请注意 H2OGPTE 服务的请求频率限制。
4. **安全性**：建议在 `.env` 中设置 `API_KEY` 以启用基础验证。
