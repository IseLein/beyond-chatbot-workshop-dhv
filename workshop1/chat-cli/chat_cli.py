import os
import sys

from openai import OpenAI


def build_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("Missing OPENROUTER_API_KEY environment variable.")
        sys.exit(1)

    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def main() -> None:
    client = build_client()
    # model = os.getenv("MODEL", "openai/gpt-oss-120b:free")
    model = os.getenv("MODEL", "moonshotai/kimi-k2.5")

    print("CLI Chat started. Type 'exit' to quit.")

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. If I tell you hey with multiple y's respond by saying 'i am not your friend lil bro'",
        }
    ]

    while True:
        user_text = input("you> ").strip()
        if user_text.lower() in {"exit", "quit"}:
            print("bye")
            break
        if not user_text:
            continue

        messages.append({"role": "user", "content": user_text})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
        )
        answer = response.choices[0].message.content or ""

        print(f"assistant> {answer}")
        messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
