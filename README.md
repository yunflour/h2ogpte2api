# H2OGPTE to OpenAI API

将 H2OGPTE 的 API 封装为标准的 OpenAI API 格式，方便与各种 AI 应用和工具集成。

## 功能特性

- ✅ `/v1/models` - 获取可用模型列表
- ✅ `/v1/chat/completions` - 聊天补全接口（支持流式和非流式）
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
H2OGPTE_SESSION=your-session-id-here
H2OGPTE_CSRF_TOKEN=your-csrf-token-here
```

> **获取凭据**：登录 h2ogpte 网站后，打开浏览器开发者工具，在网络请求中找到：
> - `h2ogpte.session`: Cookie 中的值
> - `x-csrf-token`: 请求头中的值

### 3. 启动服务

```bash
python main.py
```

服务将在 `http://localhost:2156` 启动。

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
├── main.py              # FastAPI 主应用
├── config.py            # 配置管理
├── models.py            # Pydantic 数据模型
├── h2ogpte_client.py    # H2OGPTE API 客户端
├── requirements.txt     # Python 依赖
├── .env.example         # 环境变量模板
└── README.md            # 项目说明
```

## 注意事项

1. **Session 有效期**：H2OGPTE 的 session 可能会过期，需要定期更新
2. **请求限制**：请注意 H2OGPTE 服务的请求频率限制
3. **安全性**：生产环境中建议添加 API Key 验证
