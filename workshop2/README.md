# Beyond Chatbot Workshop 2

Workshop 2 contains two OpenRouter-based multimodal projects focused on image/video understanding and tool calling.

## Projects

1. `multimodal-upload` (web app)
- Upload image/video/document files
- Send them to a multimodal model via OpenRouter
- Get structured JSON output (`summary`, `key_entities`, `events`, `safety_flags`, `follow_up_questions`)

2. `vision-agent` (web app)
- Realtime webcam loop with OpenCV on the backend
- Periodic frame analysis via OpenRouter
- Model tool-calling with guardrails
- `save_snapshot(reason, confidence)` saves frame to disk when trigger conditions are met

## Prerequisites

- Python 3.10+
- `pip`
- OpenRouter API key
- Webcam (for `vision-agent`)

---

## 1) Run `multimodal-upload`

`multimodal-upload` reads `OPENROUTER_API_KEY` from `.env` or shell env.

```bash
cd workshop2/multimodal-upload
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY
python3 app.py
```

Open:
- http://127.0.0.1:5001

Optional env vars:
- `MODEL` (default: `google/gemini-2.5-flash`)
- `MAX_INLINE_BYTES` (default: `7340032`)

---

## 2) Run `vision-agent`

`vision-agent` reads config from `.env` or shell env.

```bash
cd workshop2/vision-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY
python3 app.py
```

Open:
- http://127.0.0.1:5002

Default behavior:
- Starts/stops webcam loop from the UI
- Analyzes one frame every 1000ms
- Calls `save_snapshot` only when confidence clears threshold and cooldown allows it
- Saves snapshots under `workshop2/vision-agent/snapshots/`

Key env vars:
- `MODEL` (default: `google/gemini-2.5-flash`)
- `ANALYSIS_INTERVAL_MS` (default: `1000`)
- `CONFIDENCE_THRESHOLD` (default: `0.75`)
- `SNAPSHOT_COOLDOWN_SECONDS` (default: `5`)
- `CAMERA_INDEX` (default: `0`)
- `FRAME_WIDTH` (default: `960`)
- `FRAME_HEIGHT` (default: `540`)
- `JPEG_QUALITY` (default: `85`)

---

## Troubleshooting

- Camera open failure: change `CAMERA_INDEX` to `1` (or another index).
- High latency: increase `ANALYSIS_INTERVAL_MS`, reduce `FRAME_WIDTH/FRAME_HEIGHT`.
- Too many false positives: raise `CONFIDENCE_THRESHOLD` and/or `SNAPSHOT_COOLDOWN_SECONDS`.
- Empty or invalid JSON in upload app: inspect the raw output panel and simplify prompt/files.
