# Instagram Lead Bot Workspace

## Overview

Python-based Instagram real estate automation tool with a Streamlit web dashboard. The active project files are under `instagram-bot/Instagram-Lead-Bot/`.

## Stack

- **Python version**: 3.11
- **Node.js version**: 24
- **UI**: Streamlit dashboard
- **Browser automation**: Playwright with system Chromium
- **Storage**: SQLite for lead tracking
- **Package management**: Python packages installed into the Replit environment; pnpm workspace files remain for bundled project structure

## Active App

- Workflow: `Instagram Bot`
- Entry point: `instagram-bot/Instagram-Lead-Bot/instagram_automation/streamlit_app.py`
- Run command: starts Streamlit on port 5000 from the `instagram_automation` directory

## Instagram Automation System

Located in `instagram-bot/Instagram-Lead-Bot/instagram_automation/`.

| File | Role |
|------|------|
| `streamlit_app.py` | Web dashboard UI and main entry point |
| `bot_runner.py` | Bot orchestration with background thread logging |
| `settings_manager.py` | Reads/writes `settings.json` |
| `session_manager.py` | Playwright browser/session handling |
| `lead_scraper.py` | Scrapes comments and filters potential leads |
| `automation_engine.py` | Follow, DM, and comment reply actions |
| `database.py` | SQLite lead tracking |
| `utils.py` | Delays, spintax, screenshots, helpers |
| `config.py` | Default constants |
| `gui.py` | Legacy desktop GUI |

## Notes

- The Streamlit dashboard is currently the main user-facing app.
- Python dependencies required for the dashboard are `streamlit`, `playwright`, `aiosqlite`, `openpyxl`, and `customtkinter`.
- Restart the `Instagram Bot` workflow after dependency or app changes.
- Chromium is launched from an explicit Nix/system executable path in `session_manager.py`; Playwright is not allowed to auto-select a browser.
- `session_manager.py` sets `LD_LIBRARY_PATH` for Chromium libraries and saves an immediate launch screenshot to `instagram_automation/emergency_debug.png`.
