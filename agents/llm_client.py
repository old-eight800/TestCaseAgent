"""
LLM Client — thin wrapper around openai.OpenAI with .env config loading.

Reuses the same .env keys as agentscope-testgen (LLM_PROVIDER / LLM_BASE_URL /
LLM_MODEL / OPENAI_API_KEY) so the two projects can share one config.
"""

import os
import json
from pathlib import Path
from typing import Optional


def _load_dotenv(env_path: Optional[str] = None) -> dict:
    """Read .env file into a dict, skipping comments and quoted values."""
    if env_path is None:
        env_path = Path(__file__).parent.parent / ".env"
    else:
        env_path = Path(env_path)

    if not env_path.exists():
        return {}

    result = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            for quote in ('"', "'"):
                if val.startswith(quote) and val.endswith(quote):
                    val = val[1:-1]
                    break
            result[key] = val
    return result


class LLMClient:
    """OpenAI-compatible chat completion client with .env-driven config.

    Usage:
        client = LLMClient()
        answer = client.chat(system_prompt, user_prompt)
    """

    def __init__(self, env_path: Optional[str] = None, **overrides):
        """
        Args:
            env_path: Path to .env file. Defaults to ../.env relative to this file.
            **overrides: Override any .env key directly (e.g. model="gpt-4o").
        """
        dotenv = _load_dotenv(env_path)

        # Apply .env → os.environ for downstream compatibility
        for k, v in dotenv.items():
            if v and "xxx" not in v.lower() and k not in os.environ:
                os.environ[k] = v

        # Merge overrides
        merged = {**dotenv, **{k: v for k, v in overrides.items() if v}}

        self.api_key = (merged.get("OPENAI_API_KEY") or
                        merged.get("DASHSCOPE_API_KEY") or
                        os.environ.get("OPENAI_API_KEY") or
                        os.environ.get("DASHSCOPE_API_KEY"))

        self.base_url = (merged.get("LLM_BASE_URL") or
                         os.environ.get("LLM_BASE_URL") or "")

        self.model = (merged.get("LLM_MODEL") or
                      merged.get("model") or
                      os.environ.get("LLM_MODEL") or
                      "gpt-4o")

        self.provider = (merged.get("LLM_PROVIDER") or
                         os.environ.get("LLM_PROVIDER") or
                         "openai")

        if not self.api_key or "xxx" in self.api_key:
            raise ValueError(
                "Missing valid API key. Set OPENAI_API_KEY in .env or pass api_key= override."
            )

        # Build client
        if self.provider == "openai" and self.base_url:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        else:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)

        self._model = self.model

    def chat(self, system: str, user: str,
             temperature: float = 0.3,
             max_tokens: int = 8000,
             json_mode: bool = False) -> str:
        """Send a chat completion and return the text response.

        Args:
            system: System prompt.
            user: User message.
            temperature: 0.0-2.0. Default 0.3 for structured output.
            max_tokens: Max response tokens.
            json_mode: If True, request JSON response format (model must support it).

        Returns:
            The assistant's text response.
        """
        kwargs = dict(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"⚠️  LLM 调用失败: {e}")
            raise

    def chat_json(self, system: str, user: str,
                  temperature: float = 0.2,
                  max_tokens: int = 8000) -> dict:
        """chat() with json_mode on and automatic parsing."""
        text = self.chat(system, user, temperature=temperature,
                         max_tokens=max_tokens, json_mode=True)
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Extract JSON from potentially markdown-wrapped LLM output."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

        # Last resort: try raw
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"⚠️  LLM 返回无法解析为 JSON，原文前 200 字符: {text[:200]}")
            return {}
