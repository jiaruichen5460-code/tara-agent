# Tara-Agent

Tara-Agent 是 Tara Oceans 四份核心数据的分析 MVP：后端提供确定性分析、MCP 工具和 Agent，前端负责对话与结果展示。

## 启动准备

- Python 3.12 或 3.13、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js 22 和 pnpm 10（项目指定 pnpm 10.12.4）。
- 将四份原始 TSV 放在项目根目录的 `Tara_4_Core_Datasets/`。原始文件只读，不提交到 Git。
- 在 PowerShell 中直接使用 `uv` 命令；无需手动激活 `backend/.venv`，也不要使用 `python -m uv`。

## 1. 初始化并启动后端

在项目根目录打开第一个 PowerShell 终端：

```powershell
cd backend
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在 `backend/.env` 中把 `DEEPSEEK_API_KEY` 改为自己的密钥；如果该文件已存在，不要覆盖。然后预处理数据并启动服务：

```powershell
uv run tara-data
uv run fastapi dev
```

预处理把只读 TSV 验证并生成到 `backend/data/processed/`；重复运行会跳过未变化的数据。后端运行在 `http://localhost:8000`，可访问 `http://localhost:8000/api/v1/health` 检查状态。保持此终端运行。

## 2. 启动前端

在项目根目录打开第二个 PowerShell 终端：

```powershell
cd frontend
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
pnpm install
pnpm dev
```

打开 `http://localhost:3000`。前端通过 `frontend/.env.local` 中的 `NEXT_PUBLIC_API_BASE_URL` 连接后端，默认地址为 `http://localhost:8000`。

日常重新启动时，分别在 `backend/` 运行 `uv run fastapi dev`、在 `frontend/` 运行 `pnpm dev`；仅当原始数据或依赖变化时重新执行相应的预处理或安装命令。
