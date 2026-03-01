import atexit
import base64
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from openai import OpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
EVENTS_FILE = BASE_DIR / "events.jsonl"
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_snapshot",
            "description": (
                "Save the current camera frame to disk when phone usage is clearly detected. "
                "Only call when confidence is high."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Short reason for the snapshot.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence score from 0.0 to 1.0.",
                    },
                },
                "required": ["reason", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_incident",
            "description": "Log an observation event without saving a snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Event category, for example: phone_observed, unclear_frame.",
                    },
                    "details": {
                        "type": "string",
                        "description": "Short details for the log.",
                    },
                },
                "required": ["type", "details"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "You are a realtime visual monitoring assistant. "
    "Your task is to inspect each frame for phone usage. "
    "Call save_snapshot(reason, confidence) only when a person is actively looking at "
    "or using a phone and confidence is strong. "
    "If uncertain, do not call save_snapshot. "
    "You may call log_incident(type, details) for notable events. "
    "After tool calls (or without tools), respond with strict JSON only: "
    '{"observation":"string","phone_detected":true|false,"confidence":0.0,'
    '"action":"snapshot|none","reason":"string"}.'
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_json_obj(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def parse_tool_args(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class VisionAgent:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

        self.analysis_interval_ms = int(os.getenv("ANALYSIS_INTERVAL_MS", "1000"))
        self.confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
        self.cooldown_seconds = float(os.getenv("SNAPSHOT_COOLDOWN_SECONDS", "5"))
        self.camera_index = int(os.getenv("CAMERA_INDEX", "0"))
        self.frame_width = int(os.getenv("FRAME_WIDTH", "960"))
        self.frame_height = int(os.getenv("FRAME_HEIGHT", "540"))
        self.jpeg_quality = int(os.getenv("JPEG_QUALITY", "85"))

        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        self.running = False
        self.capture_thread: threading.Thread | None = None
        self.analysis_thread: threading.Thread | None = None
        self.cap: cv2.VideoCapture | None = None

        self.latest_frame = None
        self.latest_jpeg: bytes | None = None
        self.last_frame_at: str | None = None
        self.frames_captured = 0

        self.last_snapshot_monotonic = 0.0
        self.last_status: dict[str, Any] = {
            "at": now_iso(),
            "text": "idle",
            "parsed": None,
            "tool_calls": [],
            "latency_ms": None,
        }
        self.events: list[dict[str, Any]] = self._load_events()

    def _load_events(self) -> list[dict[str, Any]]:
        if not EVENTS_FILE.exists():
            return []

        items: list[dict[str, Any]] = []
        for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                items.append(parsed)
        return items[-200:]

    def _persist_event(self, event: dict[str, Any]) -> None:
        with EVENTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True) + "\n")

    def _append_event(self, event: dict[str, Any]) -> None:
        with self.lock:
            self.events.append(event)
            if len(self.events) > 200:
                self.events = self.events[-200:]
        self._persist_event(event)

    def set_model(self, model: str) -> None:
        with self.lock:
            self.model = model

    def update_config(self, payload: dict[str, Any]) -> None:
        with self.lock:
            if "analysis_interval_ms" in payload:
                self.analysis_interval_ms = max(250, min(10000, int(payload["analysis_interval_ms"])))
            if "confidence_threshold" in payload:
                self.confidence_threshold = max(0.0, min(1.0, float(payload["confidence_threshold"])))
            if "cooldown_seconds" in payload:
                self.cooldown_seconds = max(0.0, min(300.0, float(payload["cooldown_seconds"])))

    def start(self) -> None:
        with self.lock:
            if self.running:
                return

            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                raise RuntimeError(f"Unable to open camera index {self.camera_index}")

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)

            self.cap = cap
            self.running = True
            self.stop_event.clear()

            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.analysis_thread = threading.Thread(target=self._analysis_loop, daemon=True)
            self.capture_thread.start()
            self.analysis_thread.start()

    def stop(self) -> None:
        with self.lock:
            was_running = self.running
            self.running = False
            self.stop_event.set()
            capture_thread = self.capture_thread
            analysis_thread = self.analysis_thread
            cap = self.cap
            self.capture_thread = None
            self.analysis_thread = None
            self.cap = None

        if not was_running:
            return

        if capture_thread:
            capture_thread.join(timeout=1.0)
        if analysis_thread:
            analysis_thread.join(timeout=1.0)
        if cap:
            cap.release()

    def _capture_loop(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                cap = self.cap

            if cap is None:
                time.sleep(0.05)
                continue

            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
            )
            if not ok:
                continue

            with self.lock:
                self.latest_frame = frame
                self.latest_jpeg = encoded.tobytes()
                self.last_frame_at = now_iso()
                self.frames_captured += 1

            time.sleep(0.01)

    def _analysis_loop(self) -> None:
        next_run = 0.0
        while not self.stop_event.is_set():
            now = time.monotonic()
            with self.lock:
                interval_sec = self.analysis_interval_ms / 1000.0

            if now < next_run:
                time.sleep(min(0.05, next_run - now))
                continue

            with self.lock:
                frame = None if self.latest_frame is None else self.latest_frame.copy()

            if frame is None:
                next_run = time.monotonic() + 0.2
                continue

            start_ts = time.monotonic()
            try:
                result = self._analyze_with_model(frame)
            except Exception as exc:
                result = {
                    "text": "",
                    "parsed": None,
                    "tool_calls": [],
                    "error": str(exc),
                }

            latency_ms = round((time.monotonic() - start_ts) * 1000.0, 1)
            status = {
                "at": now_iso(),
                "text": result.get("text", ""),
                "parsed": result.get("parsed"),
                "tool_calls": result.get("tool_calls", []),
                "error": result.get("error"),
                "latency_ms": latency_ms,
            }

            with self.lock:
                self.last_status = status

            next_run = time.monotonic() + interval_sec

    def _frame_to_data_url(self, frame) -> str:
        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        if not ok:
            raise RuntimeError("Failed to encode frame")
        b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    def _analyze_with_model(self, frame) -> dict[str, Any]:
        data_url = self._frame_to_data_url(frame)
        user_content = [
            {
                "type": "text",
                "text": (
                    "Analyze this frame for phone usage. "
                    "Call tools if needed, then return strict JSON only."
                ),
            },
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        tool_log: list[dict[str, Any]] = []
        final_text = ""

        for _ in range(4):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.1,
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
                    args = parse_tool_args(call.function.arguments or "")
                    result = self._execute_tool(call.function.name, args, frame)
                    tool_log.append(
                        {
                            "name": call.function.name,
                            "arguments": args,
                            "result": result,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(result),
                        }
                    )
                continue

            final_text = msg.content or ""
            break

        return {
            "text": final_text,
            "parsed": parse_json_obj(final_text),
            "tool_calls": tool_log,
        }

    def _execute_tool(self, name: str, args: dict[str, Any], frame) -> dict[str, Any]:
        if name == "save_snapshot":
            return self._tool_save_snapshot(args, frame)
        if name == "log_incident":
            return self._tool_log_incident(args)
        return {"ok": False, "error": f"Unknown tool: {name}"}

    def _tool_save_snapshot(self, args: dict[str, Any], frame) -> dict[str, Any]:
        reason = str(args.get("reason", "")).strip() or "No reason provided"
        try:
            confidence = float(args.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        with self.lock:
            threshold = self.confidence_threshold
            cooldown = self.cooldown_seconds
            last_snapshot = self.last_snapshot_monotonic

        if confidence < threshold:
            return {
                "ok": True,
                "saved": False,
                "reason": "confidence_below_threshold",
                "confidence": confidence,
                "threshold": threshold,
            }

        now = time.monotonic()
        elapsed = now - last_snapshot if last_snapshot else cooldown + 1
        if elapsed < cooldown:
            return {
                "ok": True,
                "saved": False,
                "reason": "cooldown_active",
                "seconds_remaining": round(cooldown - elapsed, 2),
            }

        filename = f"snapshot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        path = SNAPSHOTS_DIR / filename
        wrote = cv2.imwrite(str(path), frame)
        if not wrote:
            return {"ok": False, "saved": False, "error": "Failed to write snapshot"}

        with self.lock:
            self.last_snapshot_monotonic = now

        event = {
            "at": now_iso(),
            "type": "snapshot_saved",
            "reason": reason,
            "confidence": round(confidence, 4),
            "file": filename,
        }
        self._append_event(event)

        return {
            "ok": True,
            "saved": True,
            "file": filename,
            "url": f"/snapshots/{filename}",
            "reason": reason,
            "confidence": confidence,
        }

    def _tool_log_incident(self, args: dict[str, Any]) -> dict[str, Any]:
        incident_type = str(args.get("type", "observation")).strip() or "observation"
        details = str(args.get("details", "")).strip() or "No details provided"

        event = {
            "at": now_iso(),
            "type": incident_type,
            "details": details,
        }
        self._append_event(event)
        return {"ok": True, "logged": True, "event": event}

    def get_latest_jpeg(self) -> bytes | None:
        with self.lock:
            return self.latest_jpeg

    def list_snapshots(self, limit: int = 12) -> list[dict[str, str]]:
        files = sorted(SNAPSHOTS_DIR.glob("*.jpg"), reverse=True)
        items: list[dict[str, str]] = []
        for file_path in files[:limit]:
            items.append({"name": file_path.name, "url": f"/snapshots/{file_path.name}"})
        return items

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            status = {
                "running": self.running,
                "model": self.model,
                "has_frame": self.latest_jpeg is not None,
                "last_frame_at": self.last_frame_at,
                "frames_captured": self.frames_captured,
                "analysis_interval_ms": self.analysis_interval_ms,
                "confidence_threshold": self.confidence_threshold,
                "cooldown_seconds": self.cooldown_seconds,
                "last_status": self.last_status,
                "recent_events": self.events[-20:],
            }
        status["recent_snapshots"] = self.list_snapshots(limit=8)
        return status


def get_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY in environment or .env")

    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )


app = Flask(__name__)
agent = VisionAgent(
    client=get_client(),
    model=os.getenv("MODEL", "google/gemini-2.5-flash"),
)


@app.route("/")
def index():
    return render_template("index.html", status=agent.get_status())


@app.post("/api/start")
def api_start():
    payload = request.get_json(silent=True) or {}
    model = str(payload.get("model", "")).strip()
    if model:
        agent.set_model(model)

    try:
        agent.start()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"started": True, "status": agent.get_status()})


@app.post("/api/stop")
def api_stop():
    agent.stop()
    return jsonify({"stopped": True, "status": agent.get_status()})


@app.get("/api/status")
def api_status():
    return jsonify(agent.get_status())


@app.post("/api/config")
def api_config():
    payload = request.get_json(force=True)
    try:
        agent.update_config(payload)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "status": agent.get_status()})


@app.post("/api/model")
def api_model():
    payload = request.get_json(force=True)
    model = str(payload.get("model", "")).strip()
    if not model:
        return jsonify({"error": "model is required"}), 400
    agent.set_model(model)
    return jsonify({"ok": True, "status": agent.get_status()})


@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            frame = agent.get_latest_jpeg()
            if frame is None:
                time.sleep(0.05)
                continue
            yield (
                b"--frame\\r\\n"
                b"Content-Type: image/jpeg\\r\\n\\r\\n" + frame + b"\\r\\n"
            )
            time.sleep(0.04)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/frame.jpg")
def frame_jpg():
    frame = agent.get_latest_jpeg()
    if frame is None:
        return Response(status=204)

    response = Response(frame, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/snapshots/<path:filename>")
def serve_snapshot(filename: str):
    return send_from_directory(SNAPSHOTS_DIR, filename)


@atexit.register
def _cleanup() -> None:
    agent.stop()


if __name__ == "__main__":
    app.run(debug=True, port=5002)
