# LLM Free API

English | [中文](README.md)

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-green)
![License](https://img.shields.io/badge/License-Educational-yellow)

> 🔄 **Convert private AI service APIs into standard OpenAI / Anthropic APIs. Use Claude, Kiro and more LLMs for free.**

> ⚠️ **Disclaimer: This project is for learning and research purposes only. Commercial use or any other non-educational purpose is strictly prohibited. Users assume all risks associated with usage. The author is not responsible for any misuse.**

## What Does This Project Do?

In short: **Expose the free quota of various AI services through standard API interfaces.**

Got a Kiro account? Configure the token, and you can call Claude models through standard OpenAI or Anthropic APIs. Supports multi-account rotation, load balancing, and automatic rate limiting.

```
Your App / ChatGPT-Next-Web / LobeChat / ...
        ↓ Standard OpenAI / Anthropic API
   ┌─────────────────────┐
   │   LLM Free API      │  ← This project
   └─────────────────────┘
        ↓ Private protocol conversion
   Kiro / More channels coming...
```

## Supported Channels

| Channel | Available Models | Status |
|---------|-----------------|--------|
| Kiro (AWS Claude) | See model list below | ✅ Supported |
| More channels | Coming soon... | 🚧 In progress |

### Kiro Available Models

| Model | Description |
|-------|-------------|
| `auto` | Automatically selects the best model |
| `claude-opus-4.6` | Most powerful Claude model, best for complex reasoning and creative tasks |
| `claude-sonnet-4.5` | Balanced performance, ideal for coding, writing, and general tasks |
| `claude-sonnet-4` | Previous generation Sonnet, stable and reliable |
| `claude-haiku-4.5` | Lightweight and fast, great for simple tasks and high-frequency calls |
| `deepseek-3.2` | DeepSeek open-source MoE model, excellent at coding and reasoning |
| `minimax-m2.5` | Latest MiniMax model, suited for complex tasks and multi-step workflows |
| `minimax-m2.1` | MiniMax open-source MoE model, strong at planning and reasoning |
| `glm-5` | Latest Zhipu GLM model, outstanding Chinese language capabilities |
| `qwen3-coder-next` | Qwen coding-focused model, ideal for development and large projects |

> 💡 Model availability depends on your Kiro account plan (free/paid). The above lists currently known available models.

## Key Features

- 🔌 **Standard API Output** — Compatible with both OpenAI (`/v1/chat/completions`) and Anthropic (`/v1/messages`) interfaces
- 🔀 **Multi-Account Management** — YAML-based multi-account config with ordered / random / round_robin routing strategies
- ⚡ **Streaming Support** — Full SSE streaming and non-streaming output
- 🚦 **Smart Rate Limiting** — Model validation + concurrency control + coroutine-based queuing
- 🧩 **Plugin Architecture** — Metaclass auto-registration, add new channels without touching core code
- 📊 **Ops Friendly** — Usage stats, health checks, and Swagger docs included
- ⚡ **High Performance** — Fully async architecture based on FastAPI + httpx

## Quick Start

### Requirements

- Python 3.10+
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/simkeke/ai_getway.git
cd ai_getway

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy environment config
cp .env.example .env

# Copy channel config
cp channels.yaml.example channels.yaml
```

Edit `channels.yaml` with your Kiro refresh_token:

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

### How to Get Kiro Credentials

You need a Kiro account to obtain the `refresh_token`. Here's how:

**Option 1: From Kiro IDE Credentials File (Recommended)**

Open [Kiro IDE](https://kiro.dev/) and log in. The credentials file is automatically created at:

```
~/.aws/sso/cache/kiro-auth-token.json
```

Open the JSON file and copy the `refreshToken` value into your `channels.yaml`.

**Option 2: From Kiro CLI**

If you use [Kiro CLI](https://kiro.dev/cli/), credentials are saved after login at:

```
~/.local/share/kiro-cli/data.sqlite3
```

**Option 3: Network Interception**

Use a proxy tool (e.g., Fiddler, Charles) to intercept Kiro IDE traffic. Look for requests to:

```
prod.us-east-1.auth.desktop.kiro.dev/refreshToken
```

The `refreshToken` in the response body is what you need.

### Run

```bash
python -m app.main
```

The server runs at `http://localhost:8800` by default.

## Usage

Once started, you can connect any OpenAI API-compatible client:

### curl Example

```bash
curl -X POST http://localhost:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": true
  }'
```

### Third-Party Clients

In ChatGPT-Next-Web, LobeChat, or similar clients, set the API URL to:

```
http://localhost:8800
```

Select OpenAI or Anthropic mode and you're good to go.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | OpenAI-style Chat |
| `/v1/messages` | POST | Anthropic-style Chat |
| `/admin/models` | GET | List supported models |
| `/admin/stats` | GET | Channel statistics |
| `/health` | GET | Health check |
| `/docs` | GET | Swagger docs |

## Adding New Channels

Thanks to the metaclass auto-registration mechanism, adding a new channel requires only three steps:

1. Create a new subpackage under `channels/` with Channel and ChannelGroup subclasses
2. Declare `channel_type` / `group_type` class attributes
3. Add configuration to `channels.yaml`

No changes needed to registry, router, throttle, or any core code.

## Architecture

```
Client Request (OpenAI/Anthropic format)
  → Protocol Adapter (input: client format → internal format)
  → Throttle (model check / waiting limit / coroutine wait)
  → Model Router (select channel group by priority)
  → Channel Group → Channel (internal format → upstream format → HTTP)
  → Upstream API
```

## Project Structure

```
app/
├── config/          # Configuration (Pydantic Settings)
├── core/            # Core infrastructure (logging/middleware/exceptions/lifespan)
├── schemas/         # Data models (internal format/OpenAI/Anthropic)
├── gateway/         # Gateway layer (router/throttle/protocol adapters)
├── channels/        # Channel layer (metaclass registry/channel groups/implementations)
├── api/             # REST API routes
└── db/              # Data storage
```

## Tech Stack

| Category | Technology |
|----------|-----------|
| Web Framework | FastAPI + Uvicorn |
| HTTP Client | httpx (async) |
| Storage | SQLite (WAL mode) |
| Configuration | Pydantic Settings + PyYAML |
| Logging | Loguru |

## Star History

If you find this useful, please give it a Star ⭐

## License

This project is for learning and research purposes only. Commercial use is strictly prohibited.
