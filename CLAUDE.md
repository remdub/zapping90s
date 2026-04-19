# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                          # install dependencies
uv run uvicorn main:app --reload                 # dev server on :8000
python data/init_db.py                           # (re)scan videos into DB
python data/init_db.py --reset                   # mark all videos as unplayed
python scripts/normalize_videos.py               # normalize audio (EBU R128, requires ffmpeg)
docker build -t zapping90s .
kubectl apply -f k8s-deployment.yaml
```

There are no tests.

## Architecture

**Backend** — `main.py` (single file, FastAPI + SQLite)

- `startup_init_db()` runs at boot: creates the `videos` table, scans `static/videos/*.mp4`, inserts new files, removes orphans.
- Video naming convention: `{category}__{title}.mp4`. The category prefix (before `__`) is stored in the DB.
- `pick_video(category)` draws a random unplayed video and marks it `played=1`. When all videos in a category are played, it resets them silently and retries (exhaustion algorithm).
- `ServerState` is an **in-memory singleton** holding IDLE/PLAYING status and the current video queue. This is why `replicas: 1` is mandatory in Kubernetes — multiple replicas would have divergent state.

**Video playback sequence** triggered by `POST /api/play`:
`pub-intro.mp4` → random pub ad → `pub-fermeture.mp4` → chosen video → `pub-intro.mp4` → random pub ad → `pub-fermeture.mp4`

**WebSocket** (`/ws`) — shared by both clients:
- Server broadcasts: `play` (start sequence) | `next_video` | `idle` (queue exhausted)
- Clients send: `video_ended` (triggers next item in queue or IDLE)

**Frontend** — two independent UIs in `static/`

- `display.html` / `display.js` — large screen. State machine: `BOOT → IDLE (Matrix animation + QR code) → CONNECTING → REVEAL (slot machine for category) → PLAYING`.
- `mobile.html` / `mobile.js` — phone controller. State machine: `INTRO → QUIZ (3 questions) → LOADING → CHOICE (3 video options) → WAITING`.

**Quiz** — 3 hardcoded pools in `main.py` (`q1_vibes`, `q2_dramas`, `q3_pride`), one question drawn per pool. Winning category = majority of the 3 answers (first answer breaks ties).

**DB** — SQLite at `data/zapping.db` (or `$DB_PATH`). Schema: single `videos` table with `filename`, `category`, `played` columns.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DB_PATH` | `data/zapping.db` | SQLite path (override for K8s PVC) |
| `RESET_PLAYED` | _(absent)_ | Si défini, remet tous les `played` à 0 au démarrage |
| `DISPLAY_TOKEN` | _(absent)_ | Si défini, seul `/display/<token>` donne accès à l'interface présentateur |
