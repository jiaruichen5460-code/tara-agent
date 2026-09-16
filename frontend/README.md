# Tara-Agent frontend

This Next.js application is the Tara-Agent MVP analysis workspace. It owns interaction and
presentation only; data selection and scientific calculations remain in the backend.

```powershell
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
pnpm install
pnpm dev
```

The workspace checks `GET /api/v1/health`, sends questions to `POST /api/v1/chat/stream`, renders
reasoning in a collapsible panel and answer deltas progressively, and then displays the final
trace, tables, warnings, provenance, and Plotly chart specifications. It does not calculate
statistics in the browser.
