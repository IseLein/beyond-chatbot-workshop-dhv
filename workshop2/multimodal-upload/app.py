import base64
import json
import mimetypes
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from openai import OpenAI

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
MAX_INLINE_BYTES = int(os.getenv("MAX_INLINE_BYTES", "7340032"))  # 7 MB

app = Flask(__name__)


def get_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENROUTER_API_KEY in environment or .env")

    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def extract_json_block(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None

    # Try fenced JSON first.
    fenced = re.search(r"```(?:json)?\\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1).strip() if fenced else text

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # Fall back to first JSON object region.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def guess_mime(filename: str, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or fallback


def storage_to_content_part(file_storage) -> tuple[dict, dict]:
    filename = file_storage.filename or "upload.bin"
    raw = file_storage.read()
    size_bytes = len(raw)
    mime = (file_storage.mimetype or "").strip() or guess_mime(filename)

    if size_bytes == 0:
        raise ValueError(f"File is empty: {filename}")

    if size_bytes > MAX_INLINE_BYTES:
        raise ValueError(
            f"{filename} is too large ({size_bytes} bytes). "
            f"Current MAX_INLINE_BYTES={MAX_INLINE_BYTES}."
        )

    metadata = {
        "filename": filename,
        "mime": mime,
        "size_bytes": size_bytes,
    }

    # For plain text-like files, inline the extracted text to improve reliability.
    text_like_mimes = {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "application/xml",
    }
    if mime.startswith("text/") or mime in text_like_mimes:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("latin-1", errors="replace")
        content = content[:50000]
        return {
            "type": "text",
            "text": f"File: {filename} ({mime})\\n\\n{content}",
        }, metadata

    b64 = base64.b64encode(raw).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    if mime.startswith("image/"):
        return {"type": "image_url", "image_url": {"url": data_url}}, metadata

    if mime.startswith("video/"):
        return {"type": "video_url", "video_url": {"url": data_url}}, metadata

    return {
        "type": "file",
        "file": {
            "filename": filename,
            "file_data": data_url,
        },
    }, metadata


@app.route("/")
def index():
    model = os.getenv("MODEL", "google/gemini-2.5-flash")
    return render_template(
        "index.html",
        default_model=model,
        max_inline_mb=round(MAX_INLINE_BYTES / (1024 * 1024), 2),
    )


@app.post("/api/analyze")
def api_analyze():
    files = request.files.getlist("files")
    prompt = (request.form.get("prompt") or "").strip()
    model = (request.form.get("model") or os.getenv("MODEL", "google/gemini-2.5-flash")).strip()

    if not files or all((f.filename or "").strip() == "" for f in files):
        return jsonify({"error": "Please upload at least one file."}), 400

    user_parts: list[dict] = [
        {
            "type": "text",
            "text": (
                "Analyze all provided files. Respond with strict JSON matching this schema: "
                "{summary:string,key_entities:string[],events:string[],"
                "safety_flags:string[],follow_up_questions:string[]}. "
                "Do not include markdown."
            ),
        }
    ]

    if prompt:
        user_parts.append({"type": "text", "text": f"User question: {prompt}"})

    uploaded: list[dict] = []
    try:
        for file_storage in files:
            if not (file_storage.filename or "").strip():
                continue
            part, metadata = storage_to_content_part(file_storage)
            uploaded.append(metadata)
            user_parts.append(part)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    if len(uploaded) == 0:
        return jsonify({"error": "No valid files were uploaded."}), 400

    try:
        client = get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a multimodal analysis assistant. "
                        "Always return strict JSON with the required keys."
                    ),
                },
                {"role": "user", "content": user_parts},
            ],
            temperature=0.1,
        )
    except Exception as exc:
        return jsonify({"error": f"Model request failed: {exc}"}), 500

    answer = response.choices[0].message.content or ""
    parsed = extract_json_block(answer)

    return jsonify(
        {
            "model": model,
            "files": uploaded,
            "parsed": parsed,
            "raw": answer,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
