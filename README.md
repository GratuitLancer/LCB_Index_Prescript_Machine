# LCB Index Prescript Machine

一个以《Limbus Company》氛围为灵感的中文指令生成器，配有终端式网页、解码动画与提示音。后端使用 FastAPI + SQLite，可连接本地模型或云端 LLM 服务。

## 功能

- 支持 **Ollama** 本地模型与 **OpenAI 兼容 Chat Completions API**。
- 提供仪式、日常、荒谬三种生成模式。
- 保存指令到 SQLite，并将最近十条历史加入提示词以减少重复。
- 清理模型输出，只显示最终正文。
- 提供中文错误提示、音效开关与减少动态效果支持。
- API 密钥保存在后端，通过 `.env` 或环境变量配置。

## 安装与运行

需要 **Python 3.10 或更高版本**，以及可用的 Ollama 模型或 OpenAI 兼容 API 服务。

### 1. 获取项目

```bash
git clone https://github.com/GratuitLancer/lcb_index_precript_machine.git
cd lcb_index_precript_machine
```

### 2. 安装依赖并创建配置

Windows PowerShell：

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux / macOS：

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### 3. 配置模型并启动

按下方 [配置 LLM](#配置-llm) 编辑项目根目录的 `.env`，然后启动：

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

打开 **http://127.0.0.1:8000/**，网页会跳转到同一服务提供的页面；接口文档位于 **http://127.0.0.1:8000/docs**。前端通过相对地址调用后端，更换端口后也能正常工作。

系统环境变量的优先级高于 `.env`。配置会缓存，修改配置后请重启服务；仅修改 `.env` 不一定触发 `--reload`。

## 配置 LLM

### 本地 Ollama

先运行 Ollama 并下载所需模型，例如：

```powershell
ollama pull qwen2.5:3b
```

`.env`：

```dotenv
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5:3b
LLM_API_KEY=
LLM_MAX_TOKENS=80
```

客户端会在基础地址后添加 `/api/generate`。地址可指向其他机器上的 Ollama 服务。

### 云端或自托管 OpenAI 兼容 API

将 `.env` 中对应的值替换为服务商提供的配置：

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-model-id
LLM_API_KEY=your-api-key
LLM_MAX_TOKENS=256
LLM_TEMPERATURE=1.0
LLM_TOKEN_LIMIT_FIELD=max_tokens
```

上面是占位示例，必须替换地址、模型 ID 和密钥。客户端会在 `LLM_BASE_URL` 后添加 `/chat/completions`：保留服务商要求的 `/v1` 或其他路径前缀，**不要填写完整的 `/chat/completions` 地址**。

请求格式参考 [OpenAI 官方 Chat Completions 文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)：模型、消息列表和 Bearer 认证。兼容服务商的模型、参数和额度以其文档为准。

部分模型要求 `max_completion_tokens`，或不支持自定义 `temperature`。可以改为：

```dotenv
LLM_TOKEN_LIMIT_FIELD=max_completion_tokens
LLM_TEMPERATURE=
LLM_MAX_TOKENS=1024
```

留空的 `LLM_TEMPERATURE` 不会出现在请求中。推理模型的 token 预算可能包含思考消耗，正文为空时可增加预算或换用适合短句生成的模型。当前只使用最终正文，不回退到思考内容。

### 可选参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | `ollama` 或 `openai_compatible` |
| `LLM_BASE_URL` | Ollama 的本机地址 | 云端模式必须明确配置基础地址 |
| `LLM_MODEL` | Ollama 的 `qwen2.5:3b` | 云端模式必须明确配置模型 |
| `LLM_API_KEY` | 空 | 云端模式必填，只在后端使用 |
| `LLM_TIMEOUT_SECONDS` | `120` | 读取响应的超时，范围 1–600 秒；连接超时最长 10 秒 |
| `LLM_MAX_TOKENS` | 本地 `80` / 云端 `256` | 输出 token 上限；示例文件显式设置为 `256` |
| `LLM_TEMPERATURE` | `1.0` | 0–2，留空时不传递该参数 |
| `LLM_TOKEN_LIMIT_FIELD` | `max_tokens` | 云端可切换为 `max_completion_tokens` |
| `CORS_ALLOW_ORIGINS` | 空 | 额外允许的网页来源，用逗号分隔；同源网页不需要设置 |

`.env` 已加入忽略规则，请勿把真实密钥放入网页或提交到仓库。每次点击只发送一次生成请求；失败后由用户主动重试，不自动产生额外生成请求。

建议通过 FastAPI 打开网页。如仍要双击 `web/index.html`，需显式设置 `CORS_ALLOW_ORIGINS=null` 并使用本机 8000 端口。若将前端单独部署，需要配置对应的明确来源，并修改 `web/app.js` 中的 `API_BASE`。

## 接口与生成流程

- `GET /`：打开网页。
- `GET /health`：检查配置，返回服务类型、模型与超时。**不调用模型，不验证上游连通性**。
- `POST /generate`：生成并保存指令。
- `/web/*`：网页资源。
- `GET /docs`：交互式接口文档。

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/generate" `
    -Method Post `
    -ContentType "application/json" `
    -Body '{"mode":"ritual"}'
```

成功响应示例：

```json
{
  "id": 12,
  "prescript": "将桌面左侧的空杯移到未编号的角落",
  "mode": "ritual"
}
```

`id` 是 SQLite 持久化编号。模式支持 `ritual`（仪式）、`daily`（日常）和 `absurd`（荒谬），其他值返回 422。提示词包含最近十条历史以减少重复，但尚未强制执行相似度检查。

生成失败时返回 `{"detail":"中文错误说明"}`。配置不完整返回 503；上游认证、格式或正文问题返回 502；限流返回 429；连接失败或上游不可用返回 503；超时返回 504。失败内容不会写入历史，网页会显示可读错误信息。

数据库位于项目根目录的 `data/prescripts.db`，首次启动时自动创建。

## 开发与测试

后端测试需要开发依赖，前端逻辑测试需要 Node.js：

```powershell
python -m pip install -r requirements-dev.txt
python -B -m unittest discover -s tests -v
node --check web/app.js
node --test tests/web_app.test.cjs
```

Python 测试模拟上游响应，并使用临时 SQLite 数据库，覆盖两种服务、配置校验、失败处理、历史保存、模式与静态资源，不会调用真实付费 API 或改动现有历史。Node 测试验证网页的成功与失败流程，以及模型文本的安全显示。

## 项目结构

- `app/config.py`：读取与校验配置。
- `app/llm_client.py`：LLM 服务适配与上游错误处理。
- `app/main.py`：API 与网页入口。
- `app/prompt_builder.py`：模式、风格与历史提示。
- `app/rule_engine.py`：正文清理及质量检查函数。
- `app/storage.py`：SQLite 保存与历史读取。
- `web/`：终端界面、样式与交互。
- `tests/`：不依赖真实 LLM 的回归测试。

界面图片位于 `web/Index_Logo.png`，可替换为自己的图片。

## 反馈与贡献

欢迎通过 [Issues](https://github.com/GratuitLancer/lcb_index_precript_machine/issues) 提交问题或功能建议，也欢迎提交 Pull Request。

报告问题时，请附上运行环境、复现步骤及错误信息；不要附带真实 API 密钥。提交代码变更前，请运行相关测试。

## Disclaimer

本项目为粉丝创作，与 Project Moon 无关联，也未获得其官方背书。相关商标与 Logo 归原权利人所有。

This project is a fan-made tool inspired by the atmosphere of Project Moon's works.
It is not affiliated with or endorsed by Project Moon.

All trademarks and logos belong to their respective owners.
