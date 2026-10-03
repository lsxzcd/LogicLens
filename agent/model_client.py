from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class ModelConfigError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, url: str | None = None, model: str | None = None, api_key: str | None = None, timeout: int = 120):
        self.url = url or os.getenv("LOGICLENS_MODEL_URL")
        self.model = model or os.getenv("LOGICLENS_MODEL_NAME", "local-coder-model")
        self.api_key = api_key or os.getenv("LOGICLENS_API_KEY", "")
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        if not self.url:
            raise ModelConfigError(
                "No model endpoint configured. Set LOGICLENS_MODEL_URL or use --mock."
            )
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are an RTL Verilog engineer. Return concise, synthesizable Verilog."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"model request failed: {exc}") from exc
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("model response does not look like an OpenAI-compatible chat response") from exc


def extract_verilog(text: str) -> str:
    """Extract the first fenced Verilog/SystemVerilog block, or use raw text."""
    for marker in ("```systemverilog", "```verilog", "```sv", "```"):
        if marker in text:
            part = text.split(marker, 1)[1]
            return part.split("```", 1)[0].strip()
    return text.strip()

