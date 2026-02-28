# Beyond Chatbot Workshop

This repo contains three demo projects for AI over API with tool calling.

## Projects

1. `chat-cli`
A simple CLI chat app in Python.

2. `tbcode`
A simple coding agent in Python with tools:
- `list_files`
- `read_file`
- `edit_file`

3. `tbplanner`
A simple web planner with:
- Manual add/remove calendar events
- Chatbot that uses tools:
  - `list_event` (by day)
  - `add_event`
  - `remove_event`

## Prerequisites

- Python 3.10+
- `pip`
- An OpenRouter API key

## 1) Run `chat-cli`

`chat-cli` reads `OPENROUTER_API_KEY` from your shell environment.

```bash
cd chat-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY="your-key"
python3 chat_cli.py
```

Optional:
- `MODEL` (default: `openai/gpt-oss-120b:free`)

## 2) Run `tbcode`

`tbcode` reads `OPENROUTER_API_KEY` from your shell environment.

```bash
cd tbcode
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENROUTER_API_KEY="your-key"
python3 tbcode.py
```

Optional:
- `MODEL` (default: `openai/gpt-oss-120b:free`)

## 3) Run `tbplanner`

`tbplanner` reads `OPENROUTER_API_KEY` from a local `.env` file.

```bash
cd tbplanner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY
python3 app.py
```

Open:
- http://127.0.0.1:5000
