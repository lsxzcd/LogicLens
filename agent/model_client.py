"""Model client for an OpenAI-compatible local inference server.

Everything the competition's gain comparison depends on is captured here and
nowhere else: the sampling parameters, the context budget, and whether a
request is reproducible. `run.sh` and `run_baseline.sh` must use the same
configuration, so the defaults live in one place and are reported by
`describe()` for the design report.

Note on the endpoint: the base URL is configured without the path
(`http://127.0.0.1:11434/v1`) and the chat path is appended, so switching
between Ollama, llama.cpp server and vLLM is a host change only.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

CHAT_PATH = "/chat/completions"
DEFAULT_SYSTEM_PROMPT = (
    "You are an RTL Verilog engineer. Return concise, synthesizable Verilog."
)


class ModelConfigError(RuntimeError):
    """Raised when no endpoint is configured, as opposed to a failed request."""


class ModelRequestError(RuntimeError):
    """Raised when the endpoint was reached but the call did not succeed."""


def normalise_base_url(url: str) -> str:
    """Accept either a base URL or a full chat-completions URL.

    Contributors routinely paste `http://host:port/v1/chat/completions` from a
    sample command, and appending the path to that yields a 404 that reads like
    a server fault. Both spellings are accepted instead.
    """
    url = url.rstrip("/")
    if url.endswith(CHAT_PATH):
        return url
    return url + CHAT_PATH


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class ModelClient:
    def __init__(
        self,
        url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        seed: int | None = None,
        system_prompt: str | None = None,
        retries: int | None = None,
    ):
        raw_url = url or os.getenv("LOGICLENS_MODEL_URL") or ""
        self.url = normalise_base_url(raw_url) if raw_url else ""
        self.base_url = raw_url.rstrip("/")
        self.model = model or os.getenv("LOGICLENS_MODEL_NAME", "local-coder-model")
        self.api_key = api_key if api_key is not None else os.getenv("LOGICLENS_API_KEY", "")
        self.timeout = timeout if timeout is not None else _env_int("LOGICLENS_TIMEOUT", 300)
        # Sampling is fixed by default so a reported pass@k is reproducible.
        self.temperature = (
            temperature if temperature is not None else _env_float("LOGICLENS_TEMPERATURE", 0.2)
        )
        self.top_p = top_p if top_p is not None else _env_float("LOGICLENS_TOP_P", 0.95)
        self.max_tokens = max_tokens if max_tokens is not None else _env_int("LOGICLENS_MAX_TOKENS", 2048)
        self.seed = seed if seed is not None else _env_int("LOGICLENS_SEED", None) if os.getenv("LOGICLENS_SEED") else None
        self.system_prompt = system_prompt if system_prompt is not None else os.getenv(
            "LOGICLENS_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT
        )
        self.retries = retries if retries is not None else _env_int("LOGICLENS_RETRIES", 2)

    # ---------------------------------------------------------------- reporting

    def describe(self) -> dict:
        """Configuration summary for MODEL.md and the design report."""
        return {
            "endpoint": self.url or "(not configured)",
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "seed": self.seed,
            "timeout_seconds": self.timeout,
            "retries": self.retries,
            "system_prompt_chars": len(self.system_prompt),
        }

    # ------------------------------------------------------------------ calling

    def _payload(self, prompt: str, attempt: int = 1) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        if self.seed is not None:
            # Offset per attempt so a repair can differ from the attempt it is
            # fixing, while the run as a whole stays reproducible.
            payload["seed"] = self.seed + max(0, attempt - 1)
        return payload

    def generate(self, prompt: str, temperature: float | None = None, attempt: int = 1) -> str:
        """Send one chat request and return the assistant message content.

        `attempt` varies the seed per repair round. With a fixed seed the local
        server is fully deterministic - raising the temperature does not change
        that - so resending a similar prompt returned byte-identical code and
        every retry was wasted. Offsetting the seed keeps a whole run
        reproducible while letting a repair actually produce something new.

        Retries cover transport failures and 5xx responses. A 4xx is returned
        immediately: retrying a malformed request or a bad model name cannot
        help, and it would multiply the wall clock during a batch run.
        """
        if not self.url:
            raise ModelConfigError(
                "No model endpoint configured. Set LOGICLENS_MODEL_URL, pass --model-url, or use --mock."
            )
        payload = self._payload(prompt, attempt=attempt)
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 2):
            request = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                return self._content(raw)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                except Exception:  # noqa: BLE001 - the body is best effort only
                    detail = ""
                if exc.code < 500:
                    raise ModelRequestError(
                        f"model endpoint rejected the request: HTTP {exc.code} {detail}"
                    ) from exc
                last_error = ModelRequestError(f"HTTP {exc.code} {detail}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = ModelRequestError(f"{type(exc).__name__}: {exc}")
            if attempt <= self.retries:
                time.sleep(min(2.0 * attempt, 6.0))
        raise ModelRequestError(
            f"model request failed after {self.retries + 1} attempt(s): {last_error}"
        )

    @staticmethod
    def _content(raw: str) -> str:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelRequestError(f"model response was not JSON: {raw[:200]}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelRequestError(
                "model response does not look like an OpenAI-compatible chat response"
            ) from exc
        if not isinstance(content, str):
            raise ModelRequestError("model response content was not a string")
        return content

    # ----------------------------------------------------------------- probing

    def probe(self, timeout: int | None = None) -> dict:
        """Check the endpoint end to end and report what it actually did.

        Returns a dict rather than raising, so a setup check can report every
        problem at once instead of stopping at the first.
        """
        report: dict = {"configured": bool(self.url), **self.describe()}
        if not self.url:
            report["ok"] = False
            report["error"] = "no endpoint configured (LOGICLENS_MODEL_URL is unset)"
            return report
        started = time.perf_counter()
        try:
            text = self.generate("Reply with the single word: ready", temperature=0.0)
        except (ModelConfigError, ModelRequestError) as exc:
            report["ok"] = False
            report["error"] = str(exc)
            report["elapsed_seconds"] = round(time.perf_counter() - started, 2)
            return report
        report["ok"] = True
        report["elapsed_seconds"] = round(time.perf_counter() - started, 2)
        report["reply_chars"] = len(text)
        report["reply_preview"] = text.strip()[:80]
        report["looks_like_verilog"] = bool(re.search(r"\bmodule\b|\bendmodule\b", text))
        return report


def extract_verilog(text: str) -> str:
    """Extract the first fenced Verilog/SystemVerilog block, or use raw text.

    The competition harness asks for `[BEGIN]`/`[DONE]` delimiters and the
    VerilogEval harness for markdown fences, so both are honoured before falling
    back to the whole reply.
    """
    for begin, end in (("[BEGIN]", "[DONE]"), ("<CODE>", "</CODE>")):
        if begin in text and end in text:
            body = text.split(begin, 1)[1].split(end, 1)[0].strip()
            if body:
                return body
    for marker in ("```systemverilog", "```verilog", "```sv", "```"):
        if marker in text:
            part = text.split(marker, 1)[1]
            return part.split("```", 1)[0].strip()
    return text.strip()
