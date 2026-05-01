# LLM Free API

[English](README_EN.md) | 中文

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-green)
![License](https://img.shields.io/badge/License-Educational-yellow)

> 🔄 **将各类 AI 服务的私有接口转换为标准 OpenAI / Anthropic API，免费使用 Claude、Kiro 等大模型。**

> ⚠️ **免责声明：本项目仅供学习和研究使用，严禁用于任何商业用途或其他非学习目的。使用者需自行承担使用风险，作者不对任何滥用行为负责。**

## 这个项目能做什么？

简单来说：**把各种 AI 服务的免费额度，通过标准 API 接口暴露出来**。

你有一个 Kiro 账号？配置好 token，就能通过标准的 OpenAI 或 Anthropic 接口调用 Claude 模型。支持多账号轮询、负载均衡、自动限流。

```
你的应用 / ChatGPT-Next-Web / LobeChat / ...
        ↓ 标准 OpenAI / Anthropic API
   ┌─────────────────────┐
   │   LLM Free API      │  ← 本项目
   └─────────────────────┘
        ↓ 私有协议转换
   Kiro / 更多渠道陆续接入...
```

## 已支持的渠道

| 渠道 | 可用模型 | 状态 |
|------|---------|------|
| Kiro (AWS Claude) | 见下方模型列表 | ✅ 已支持 |
| 更多渠道 | 持续接入中... | 🚧 开发中 |

### Kiro 可用模型

| 模型 | 说明 |
|------|------|
| `auto` | 自动选择最佳模型 |
| `claude-opus-4.6` | Claude 最强模型，复杂推理和创作首选 |
| `claude-sonnet-4.5` | 性能均衡，编程、写作和通用任务的最佳选择 |
| `claude-sonnet-4` | 上一代 Sonnet，稳定可靠 |
| `claude-haiku-4.5` | 轻量快速，适合简单任务和高频调用 |
| `deepseek-3.2` | DeepSeek 开源 MoE 模型，编程和推理表现出色 |
| `minimax-m2.5` | MiniMax 最新模型，适合复杂任务和多步工作流 |
| `minimax-m2.1` | MiniMax 开源 MoE 模型，规划和推理能力强 |
| `glm-5` | 智谱 GLM 系列最新模型，中文能力突出 |
| `qwen3-coder-next` | 通义千问编程专用模型，适合开发和大型项目 |

> 💡 模型可用性取决于你的 Kiro 账号套餐（免费/付费），以上为目前已知可用模型。

## 核心特性

- 🔌 **标准 API 输出** — 同时兼容 OpenAI (`/v1/chat/completions`) 和 Anthropic (`/v1/messages`) 接口
- 🔀 **多账号管理** — YAML 配置多账号，支持 ordered / random / round_robin 路由策略
- ⚡ **流式响应** — 完整支持 SSE 流式和非流式输出
- 🚦 **智能限流** — 模型校验 + 并发控制 + 协程排队等待
- 🧩 **插件式扩展** — 元类自动注册，新增渠道无需改动核心代码
- 📊 **运维友好** — 额度统计、健康检查、Swagger 文档一应俱全
- ⚡ **高性能** — 基于 FastAPI + httpx 的全异步架构

## 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装

```bash
# 克隆项目
git clone https://github.com/simkeke/ai_getway.git
cd ai_getway

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

### 配置

```bash
# 复制环境变量配置
cp .env.example .env

# 复制通道配置
cp channels.yaml.example channels.yaml
```

编辑 `channels.yaml`，填入你的 Kiro refresh_token：

```yaml
channel_groups:
  - name: kiro
    type: kiro
    priority: 1
    strategy: ordered
    channels:
      - name: kiro-account-1
        priority: 1
        refresh_token: "your-refresh-token-here"
        region: us-east-1
        max_concurrency: 1
```

### 如何获取 Kiro 凭据

你需要一个 Kiro 账号来获取 `refresh_token`。以下是获取方式：

**方式一：从 Kiro IDE 凭据文件获取（推荐）**

打开 [Kiro IDE](https://kiro.dev/) 并登录，凭据文件会自动生成在：

```
~/.aws/sso/cache/kiro-auth-token.json
```

打开该 JSON 文件，复制 `refreshToken` 字段的值填入 `channels.yaml` 即可。

**方式二：从 Kiro CLI 获取**

如果你使用 [Kiro CLI](https://kiro.dev/cli/)，登录后凭据保存在：

```
~/.local/share/kiro-cli/data.sqlite3
```

**方式三：抓包获取**

使用抓包工具（如 Fiddler、Charles）拦截 Kiro IDE 的网络请求

响应体中的 `refreshToken` 即为所需值。

### 启动

```bash
python -m app.main
```

服务默认运行在 `http://localhost:8800`。

## 使用方式

启动后，你可以用任何支持 OpenAI API 的客户端直接对接：

### curl 示例

```bash
curl -X POST http://localhost:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": true
  }'
```

### 对接第三方客户端

在 ChatGPT-Next-Web、LobeChat 等客户端中，将 API 地址设为：

```
http://localhost:8800
```

选择 OpenAI 或 Anthropic 接口模式即可使用。

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/v1/chat/completions` | POST | OpenAI 风格 Chat |
| `/v1/messages` | POST | Anthropic 风格 Chat |
| `/admin/models` | GET | 查询支持的模型 |
| `/admin/stats` | GET | 查询统计信息 |
| `/health` | GET | 健康检查 |
| `/docs` | GET | Swagger 文档 |

## 新增渠道

得益于元类自动注册机制，新增渠道只需三步：

1. 在 `channels/` 下新建子包，实现 Channel 和 ChannelGroup 子类
2. 声明 `channel_type` / `group_type` 类属性
3. 在 `channels.yaml` 添加配置

无需修改 registry、router、throttle 等核心代码。

## 架构概览

```
客户端请求 (OpenAI/Anthropic 格式)
  → 协议适配器 (输入转换: 客户端格式 → 内部格式)
  → 全局限流 (模型校验 / 等待数控制 / 协程等待)
  → 模型路由 (按优先级选通道组)
  → 通道组 → 通道 (内部格式 → 上游私有格式 → HTTP 请求)
  → 上游 API
```

## 项目结构

```
app/
├── config/          # 配置层 (Pydantic Settings)
├── core/            # 核心基础设施 (日志/中间件/异常/生命周期)
├── schemas/         # 数据格式定义 (内部格式/OpenAI/Anthropic)
├── gateway/         # 网关层 (路由/限流/协议适配器)
├── channels/        # 通道层 (元类注册/通道组/通道实现)
├── api/             # REST API 路由
└── db/              # 数据存储
```

## 技术栈

| 类别 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| HTTP 客户端 | httpx (异步) |
| 存储 | SQLite (WAL 模式) |
| 配置 | Pydantic Settings + PyYAML |
| 日志 | Loguru |

## Star History

如果觉得有用，欢迎 Star ⭐

## 许可证

本项目仅供学习和研究使用，严禁用于任何商业用途。
