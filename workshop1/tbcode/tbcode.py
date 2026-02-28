import json
import os
import sys
from pathlib import Path
from typing import Callable

from openai import OpenAI

WORKSPACE_ROOT = Path.cwd().resolve()


def build_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("Missing OPENROUTER_API_KEY environment variable.")
        sys.exit(1)
    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def resolve_path(raw_path: str) -> Path:
    candidate = (WORKSPACE_ROOT / raw_path).resolve()
    if WORKSPACE_ROOT not in candidate.parents and candidate != WORKSPACE_ROOT:
        raise ValueError("Path is outside workspace root.")
    return candidate


def tool_list_files(path: str = ".") -> str:
    root = resolve_path(path)
    if not root.exists():
        return f"Path does not exist: {path}"

    if root.is_file():
        return str(root.relative_to(WORKSPACE_ROOT))

    entries: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        for dirname in dirnames:
            rel = (current / dirname).relative_to(WORKSPACE_ROOT)
            entries.append(f"{rel}/")
        for filename in filenames:
            rel = (current / filename).relative_to(WORKSPACE_ROOT)
            entries.append(str(rel))

    if not entries:
        return f"No files found under {path}"

    max_items = 500
    truncated = entries[:max_items]
    text = "\n".join(truncated)
    if len(entries) > max_items:
        text += f"\n... truncated, {len(entries) - max_items} more entries"
    return text


def tool_read_file(path: str) -> str:
    file_path = resolve_path(path)
    if not file_path.exists():
        return f"File not found: {path}"
    if file_path.is_dir():
        return f"Path is a directory, not a file: {path}"

    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"File is not valid UTF-8 text: {path}"


def tool_edit_file(path: str, content: str) -> str:
    file_path = resolve_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {path}"


def run_agent(client: OpenAI, user_request: str, model: str) -> str:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files under a workspace path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path from workspace root. Defaults to '.'",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a UTF-8 text file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative file path to read.",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Write full file content to a path. Creates file if needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative file path to write.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Entire new UTF-8 file contents.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
    ]

    tool_map: dict[str, Callable[..., str]] = {
        "list_files": tool_list_files,
        "read_file": tool_read_file,
        "edit_file": tool_edit_file,
    }

    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are TBCode, a lightweight coding agent. Use tools to inspect files and make edits. "
                "Be concise and explain what you changed."
            ),
        },
        {"role": "user", "content": user_request},
    ]

    for _ in range(20):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )

        message = response.choices[0].message

        if message.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [tc.model_dump() for tc in message.tool_calls],
                }
            )

            for tc in message.tool_calls:
                fn_name = tc.function.name
                try:
                    parsed_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    parsed_args = {"_raw_arguments": tc.function.arguments or ""}

                tool_call_info = {"name": fn_name, "arguments": parsed_args}
                print(f"[tool_call]: {json.dumps(tool_call_info, ensure_ascii=True)}")

                fn = tool_map.get(fn_name)
                if fn is None:
                    tool_result = f"Unknown tool: {fn_name}"
                else:
                    try:
                        tool_result = fn(**parsed_args)
                    except Exception as exc:
                        tool_result = f"Tool error: {exc}"

                # print(f"[tool_response]: {tool_result}")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        final_text = message.content or ""
        return final_text

    return "Stopped after too many tool-calling rounds."


def main() -> None:
    client = build_client()
    model = os.getenv("MODEL", "openai/gpt-oss-120b:free")

    print("TBCode started. Enter coding requests. Type 'exit' to quit.")
    print(f"Workspace root: {WORKSPACE_ROOT}")

    while True:
        request = input("tbcode> ").strip()
        if request.lower() in {"exit", "quit"}:
            print("bye")
            break
        if not request:
            continue

        answer = run_agent(client, request, model)
        print(f"\n{answer}\n")


if __name__ == "__main__":
    main()
