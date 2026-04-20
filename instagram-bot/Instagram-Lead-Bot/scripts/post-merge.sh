#!/bin/bash
set -e
pnpm install --frozen-lockfile
pnpm --filter db push
python3 -m playwright install chromium --quiet || true
