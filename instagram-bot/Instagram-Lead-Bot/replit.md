# Workspace

## Overview

pnpm workspace monorepo. Contains a Python-based Instagram real estate automation tool with a Streamlit web dashboard.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Python version**: 3.11
- **Package manager**: pnpm (Node) + pip (Python)
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Bot UI**: Streamlit (Python) at `/` — port 25712
- **Database**: PostgreSQL + Drizzle ORM (Node) / SQLite (Python bot)
- **Browser automation**: Playwright (Python)

## Instagram Automation System

Located in `instagram_automation/`. All files are Python.

| File | Role |
|------|------|
| `streamlit_app.py` | Web dashboard UI (main entry point) |
| `bot_runner.py` | Bot logic with threading + log queue |
| `settings_manager.py` | settings.json read/write |
| `session_manager.py` | Playwright browser session |
| `lead_scraper.py` | Comment scraping + keyword filter |
| `automation_engine.py` | Follow / DM / reply logic |
| `database.py` | SQLite for lead tracking |
| `utils.py` | Delays, spintax, screenshots |
| `config.py` | Default constants |
| `gui.py` | Legacy CustomTkinter GUI (desktop only) |

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm --filter @workspace/api-server run dev` — run API server locally

## Artifacts

- `artifacts/bot-dashboard/` — Streamlit web UI at `/` (port 25712)
- `artifacts/api-server/` — Express API at `/api` (port 8080)
