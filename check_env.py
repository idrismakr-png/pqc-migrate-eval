import os
import sys
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")

if not api_key:
    sys.exit("FAIL: OPENROUTER_API_KEY not found in .env")

print(f"PASS: key loaded (prefix={api_key[:12]}, length={len(api_key)})")
print(f"PASS: python={sys.executable}")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
)

try:
    resp = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "Reply with exactly: CONNECTION_OK"}],
        max_tokens=10,
        temperature=0,
    )
    content = resp.choices[0].message.content.strip()
    print(f"PASS: OpenRouter responded: {content}")
except Exception as e:
    sys.exit(f"FAIL: OpenRouter call failed: {e}")
