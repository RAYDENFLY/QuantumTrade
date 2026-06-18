"""
agent/llm_client.py — Adapter LLM: Ollama (primary) → Groq → DeepSeek (fallback).

Urutan routing:
  1. Ollama lokal (gratis, 99% kasus)
  2. Groq (free tier, cepat)  — jika lokal gagal dan GROQ_API_KEY tersedia
  3. DeepSeek (paid)          — jika Groq juga gagal DAN masih dalam budget
- Tidak pernah kirim secret/API key ke prompt
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests

from agent.schema import AgentPlan, AgentSnapshot, TokenUsage

log = logging.getLogger("agent.llm")

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an autonomous trading risk agent for a futures trading system (Gate.io testnet).
Your job: analyze the current market snapshot and propose safe, conservative actions.

Rules you MUST follow:
1. Output ONLY valid JSON matching the AgentPlan schema — no prose, no markdown, no code blocks.
2. CLOSE_POSITION and REVERSE_POSITION require emergency=true.
3. Be conservative. Survival is the primary objective.
4. Never suggest actions that increase exposure when drawdown > 10%.
5. confidence must be between 0.0 and 1.0.

AgentPlan JSON schema:
{
  "ts": "<ISO8601>",
  "summary": "<1-2 sentence summary>",
  "observations": ["<observation>"],
  "risks": ["<risk>"],
  "proposed_actions": [
    {
      "type": "<ACTION_TYPE>",
      "params": {},
      "why": "<reason>",
      "guardrails": ["<condition>"]
    }
  ],
  "needs_human_approval": false,
  "confidence": 0.7,
  "emergency": false
}

Valid action types: PAUSE_ENTRIES, RESUME_ENTRIES, TIGHTEN_RISK, ROTATE_LOGS,
EXPORT_REPORT, NOTIFY, CANCEL_STALE_TPSL, REPLACE_TPSL, REDUCE_POSITION,
CLOSE_POSITION, REVERSE_POSITION, SET_SURVIVAL_MODE, UPDATE_CONFIG
"""


def _build_user_prompt(snapshot: AgentSnapshot) -> str:
    return (
        "Current system snapshot:\n\n"
        + snapshot.to_prompt_text()
        + "\n\nAnalyze and respond with AgentPlan JSON only."
    )


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        primary_model: str = "qwen2.5:7b",
        fallback_model: str = "llama3.2:3b",
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.timeout = timeout

    def _chat(self, model: str, user_prompt: str) -> Tuple[str, TokenUsage]:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.9},
            "format": "json",
        }
        resp = requests.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        # Ollama tidak kasih token usage yang presisi, estimasi kasar
        usage = TokenUsage(
            provider="ollama",
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            cost_usd=0.0,
        )
        return content, usage

    def generate(self, snapshot: AgentSnapshot) -> Tuple[str, TokenUsage]:
        user_prompt = _build_user_prompt(snapshot)
        # Coba primary dulu
        try:
            log.info("Ollama generate: model=%s", self.primary_model)
            return self._chat(self.primary_model, user_prompt)
        except Exception as e:
            log.warning("Ollama primary (%s) failed: %s — trying fallback %s", self.primary_model, e, self.fallback_model)

        # Fallback ke model ringan
        try:
            return self._chat(self.fallback_model, user_prompt)
        except Exception as e2:
            raise RuntimeError(f"Ollama both models failed: {e2}") from e2

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False



# ---------------------------------------------------------------------------
# Groq client (free tier, OpenAI-compatible API)
# ---------------------------------------------------------------------------

# Model Groq yang direkomendasikan untuk planning (fast + gratis sampai rate limit):
# - "llama-3.3-70b-versatile"   → paling capable, cocok untuk planning
# - "llama-3.1-8b-instant"      → super cepat, cocok untuk fallback ringan
# - "mixtral-8x7b-32768"        → context panjang
GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
GROQ_FAST_MODEL    = "llama-3.1-8b-instant"


class GroqClient:
    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str = GROQ_DEFAULT_MODEL,
        fallback_model: str = GROQ_FAST_MODEL,
        timeout: int = 30,
    ) -> None:
        self.api_key       = api_key
        self.model         = model
        self.fallback_model = fallback_model
        self.timeout       = timeout

    def _chat(self, model: str, user_prompt: str) -> Tuple[str, TokenUsage]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        resp = requests.post(self.API_URL, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        raw_usage = data.get("usage", {})
        usage = TokenUsage(
            provider="groq",
            model=model,
            input_tokens=raw_usage.get("prompt_tokens", 0),
            output_tokens=raw_usage.get("completion_tokens", 0),
            cost_usd=0.0,  # Groq free tier = $0
        )
        return content, usage

    def generate(self, snapshot: AgentSnapshot) -> Tuple[str, TokenUsage]:
        user_prompt = _build_user_prompt(snapshot)
        try:
            log.info("Groq generate: model=%s", self.model)
            return self._chat(self.model, user_prompt)
        except Exception as e:
            log.warning("Groq primary (%s) failed: %s — trying fast model %s", self.model, e, self.fallback_model)
            return self._chat(self.fallback_model, user_prompt)


# ---------------------------------------------------------------------------
# DeepSeek client (paid fallback)
# ---------------------------------------------------------------------------

class DeepSeekClient:
    API_URL = "https://api.deepseek.com/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",   # non-thinking mode
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, snapshot: AgentSnapshot) -> Tuple[str, TokenUsage]:
        user_prompt = _build_user_prompt(snapshot)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        resp = requests.post(self.API_URL, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        raw_usage = data.get("usage", {})
        ph_tokens = raw_usage.get("prompt_tokens", 0)
        ch_tokens = raw_usage.get("completion_tokens", 0)
        cache_hit = raw_usage.get("prompt_cache_hit_tokens", 0)
        usage = TokenUsage.deepseek_cost(
            model=self.model,
            input_tokens=ph_tokens,
            output_tokens=ch_tokens,
            cache_hit_input=cache_hit,
        )
        return content, usage


# ---------------------------------------------------------------------------
# LLMRouter — local-first dengan fallback cloud
# ---------------------------------------------------------------------------

class LLMRouter:
    """
    Routing priority:
      1. Ollama lokal (gratis)
      2. Groq (free tier)   — jika Ollama gagal dan GROQ_API_KEY ada
      3. DeepSeek (paid)    — jika Groq juga gagal DAN masih dalam budget
    """

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        primary_model: str = "qwen2.5:7b",
        fallback_model: str = "llama3.2:3b",
        groq_api_key: Optional[str] = None,
        groq_model: str = GROQ_DEFAULT_MODEL,
        deepseek_api_key: Optional[str] = None,
        cloud_budget_per_day_usd: float = 0.0,
    ) -> None:
        self._ollama = OllamaClient(
            base_url=ollama_base_url,
            primary_model=primary_model,
            fallback_model=fallback_model,
        )
        self._groq: Optional[GroqClient] = None
        if groq_api_key:
            self._groq = GroqClient(api_key=groq_api_key, model=groq_model)
            log.info("Groq client enabled: model=%s", groq_model)

        self._deepseek: Optional[DeepSeekClient] = None
        if deepseek_api_key:
            self._deepseek = DeepSeekClient(api_key=deepseek_api_key)

        self.cloud_budget_per_day_usd = cloud_budget_per_day_usd
        self._cloud_spent_today_usd: float = 0.0
        self._cloud_day: Optional[str] = None   # "YYYY-MM-DD" untuk reset harian

    def _reset_daily_if_needed(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if self._cloud_day != today:
            self._cloud_day = today
            self._cloud_spent_today_usd = 0.0

    def _within_cloud_budget(self) -> bool:
        """DeepSeek budget check. Groq = free, tidak perlu cek budget."""
        self._reset_daily_if_needed()
        return (
            self.cloud_budget_per_day_usd > 0
            and self._cloud_spent_today_usd < self.cloud_budget_per_day_usd
        )

    def generate_plan(self, snapshot: AgentSnapshot) -> Tuple[AgentPlan, TokenUsage]:
        """
        Panggil LLM sesuai urutan priority.
        Jika semua gagal → kembalikan safe default plan (PAUSE_ENTRIES).
        """
        raw_content: str = ""
        usage: Optional[TokenUsage] = None

        # 1. Coba Ollama lokal
        try:
            raw_content, usage = self._ollama.generate(snapshot)
            log.info("LLM response from Ollama model=%s tokens_in=%d tokens_out=%d",
                     usage.model, usage.input_tokens, usage.output_tokens)
        except Exception as ollama_err:
            log.warning("Ollama failed: %s", ollama_err)

            # 2. Fallback Groq (free tier, tidak perlu cek budget)
            if self._groq:
                try:
                    raw_content, usage = self._groq.generate(snapshot)
                    log.warning("Using Groq fallback. model=%s tokens_in=%d tokens_out=%d",
                                usage.model, usage.input_tokens, usage.output_tokens)
                except Exception as groq_err:
                    log.warning("Groq also failed: %s", groq_err)

            # 3. Fallback DeepSeek (paid, cek budget)
            if not raw_content and self._deepseek and self._within_cloud_budget():
                try:
                    raw_content, usage = self._deepseek.generate(snapshot)
                    self._cloud_spent_today_usd += (usage.cost_usd if usage else 0.0)
                    log.warning("Using DeepSeek fallback. model=%s cost_today=$%.5f",
                                usage.model if usage else "?", self._cloud_spent_today_usd)
                except Exception as ds_err:
                    log.error("DeepSeek also failed: %s", ds_err)
            elif not raw_content and self._deepseek and not self._within_cloud_budget():
                log.warning("Cloud budget exhausted (budget=%.3f spent=%.3f) — skipping DeepSeek",
                            self.cloud_budget_per_day_usd, self._cloud_spent_today_usd)

        # Jika tidak ada output sama sekali → safe default
        if not raw_content:
            log.error("All LLM providers failed — returning safe PAUSE plan")
            return _safe_default_plan(snapshot), TokenUsage(provider="none", model="none")

        # Parse + validate
        try:
            plan = _parse_plan(raw_content, snapshot)
            if usage:
                return plan, usage
            return plan, TokenUsage(provider="ollama", model="unknown")
        except Exception as parse_err:
            log.error("Failed to parse LLM output: %s\nRaw: %.500s", parse_err, raw_content)
            return _safe_default_plan(snapshot), TokenUsage(provider="parse_error", model="")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_plan(raw: str, snapshot: AgentSnapshot) -> AgentPlan:
    """Ekstrak JSON dari output LLM dan validasi sebagai AgentPlan."""
    raw = raw.strip()
    # Kadang LLM wrap dengan ```json ... ```
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            l for l in lines
            if not l.strip().startswith("```")
        )
    data = json.loads(raw)
    # Pastikan ts ada
    if "ts" not in data:
        data["ts"] = snapshot.ts.isoformat()
    return AgentPlan.model_validate(data)


def _safe_default_plan(snapshot: AgentSnapshot) -> AgentPlan:
    """Plan aman default ketika LLM gagal total: pause entries."""
    from datetime import timezone
    from datetime import datetime as dt
    from agent.schema import ProposedAction, ActionType
    return AgentPlan(
        ts=dt.now(tz=timezone.utc),
        summary="LLM unavailable — applying safe default: pause new entries.",
        observations=["All LLM providers failed or returned invalid output."],
        risks=["Unknown state — conservative action chosen."],
        proposed_actions=[
            ProposedAction(
                type=ActionType.PAUSE_ENTRIES,
                params={"duration_min": 60},
                why="LLM fallback safety pause",
                guardrails=[],
            )
        ],
        confidence=1.0,
        emergency=False,
    )
