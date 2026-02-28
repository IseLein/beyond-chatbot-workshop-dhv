import json
import os
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
EVENTS_FILE = BASE_DIR / "events.json"
DATA_LOCK = threading.Lock()

app = Flask(__name__)


def get_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY. Add it to .env.")

    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def load_events() -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    with DATA_LOCK:
        raw = EVENTS_FILE.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return data


def save_events(events: list[dict]) -> None:
    with DATA_LOCK:
        EVENTS_FILE.write_text(json.dumps(events, indent=2), encoding="utf-8")


def validate_date(value: str) -> str:
    date.fromisoformat(value)
    return value


def validate_time(value: str) -> str:
    if not value:
        return ""
    datetime.strptime(value, "%H:%M")
    return value


def sorted_events(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: (e.get("date", ""), e.get("time", ""), e.get("title", "")))


def list_events_for_day(day: str) -> list[dict]:
    day = validate_date(day)
    events = load_events()
    day_events = [evt for evt in events if evt.get("date") == day]
    return sorted(day_events, key=lambda e: (e.get("time", ""), e.get("title", "")))


def add_event(day: str, title: str, time_text: str = "") -> dict:
    day = validate_date(day)
    time_text = validate_time(time_text)
    if not title.strip():
        raise ValueError("Title is required")

    events = load_events()
    event = {
        "id": str(uuid.uuid4()),
        "date": day,
        "title": title.strip(),
        "time": time_text,
    }
    events.append(event)
    save_events(sorted_events(events))
    return event


def remove_event(event_id: str) -> bool:
    events = load_events()
    remaining = [evt for evt in events if evt.get("id") != event_id]
    removed = len(remaining) != len(events)
    if removed:
        save_events(sorted_events(remaining))
    return removed


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_event",
            "description": "List events for a given date (YYYY-MM-DD).",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format.",
                    }
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_event",
            "description": "Add a calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Event title.",
                    },
                    "time": {
                        "type": "string",
                        "description": "Optional HH:MM time.",
                    },
                },
                "required": ["date", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_event",
            "description": "Remove event by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "ID of the event to remove.",
                    }
                },
                "required": ["event_id"],
            },
        },
    },
]


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/events")
def api_list_events():
    day = request.args.get("date")
    if day:
        try:
            return jsonify({"events": list_events_for_day(day)})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    return jsonify({"events": sorted_events(load_events())})


@app.post("/api/events")
def api_add_event():
    payload = request.get_json(force=True)
    day = payload.get("date", "")
    title = payload.get("title", "")
    time_text = payload.get("time", "")

    try:
        event = add_event(day, title, time_text)
        return jsonify({"event": event})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/events/<event_id>")
def api_remove_event(event_id: str):
    removed = remove_event(event_id)
    if not removed:
        return jsonify({"error": "Event not found"}), 404
    return jsonify({"removed": True})


def run_chat(history: list[dict]) -> tuple[str, list[dict]]:
    client = get_client()
    model = os.getenv("MODEL", "openai/gpt-oss-120b:free")
    tool_call_log: list[dict] = []

    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are TBPlanner assistant. Help manage events. "
                "Use tools for listing, adding, and removing events when needed. "
                "When removing events, get the event id via list_event first if missing."
            ),
        }
    ]

    for msg in history:
        role = msg.get("role")
        content = msg.get("content", "")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})

    for _ in range(20):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )

        msg = response.choices[0].message
        if msg.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
            )

            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                tool_call_log.append({"name": call.function.name, "arguments": args})

                try:
                    if call.function.name == "list_event":
                        result = list_events_for_day(args.get("date", ""))
                    elif call.function.name == "add_event":
                        result = add_event(
                            args.get("date", ""),
                            args.get("title", ""),
                            args.get("time", ""),
                        )
                    elif call.function.name == "remove_event":
                        result = {"removed": remove_event(args.get("event_id", ""))}
                    else:
                        result = {"error": f"Unknown tool: {call.function.name}"}
                except Exception as exc:
                    result = {"error": str(exc)}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result),
                    }
                )
            continue

        return msg.content or "", tool_call_log

    return "I could not finish the request after multiple tool rounds.", tool_call_log


@app.post("/api/chat")
def api_chat():
    payload = request.get_json(force=True)
    history = payload.get("history", [])

    if not isinstance(history, list):
        return jsonify({"error": "history must be a list"}), 400

    try:
        reply, tool_calls = run_chat(history)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"reply": reply, "tool_calls": tool_calls})


if __name__ == "__main__":
    app.run(debug=True)
