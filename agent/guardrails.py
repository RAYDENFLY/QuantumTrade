"""
agent/guardrails.py — Circuit-breaker, rate limiter, dan emergency conditions.

Setiap action yang mau dieksekusi WAJIB lewat check_guardrails() dulu.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from agent.schema import ActionType, AgentSnapshot, HIGH_RISK_ACTIONS, MEDIUM_RISK_ACTIONS

log = logging.getLogger("agent.guardrails")


# ---------------------------------------------------------------------------
# Rate limiter — per contract per 4H
# ---------------------------------------------------------------------------

class RateLimiter:
    """Track eksekusi order per contract per window."""

    def __init__(self, window_sec: int = 4 * 3600, max_per_window: int = 6) -> None:
        self.window_sec = window_sec
        self.max_per_window = max_per_window
        self._history: Dict[str, List[float]] = defaultdict(list)

    def check(self, contract: str) -> bool:
        """True jika masih dalam batas."""
        now = time.time()
        cutoff = now - self.window_sec
        self._history[contract] = [t for t in self._history[contract] if t > cutoff]
        return len(self._history[contract]) < self.max_per_window

    def record(self, contract: str) -> None:
        self._history[contract].append(time.time())

    def count(self, contract: str) -> int:
        now = time.time()
        cutoff = now - self.window_sec
        self._history[contract] = [t for t in self._history[contract] if t > cutoff]
        return len(self._history[contract])


# ---------------------------------------------------------------------------
# Circuit breaker — auto-trip saat error rate tinggi
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    States: CLOSED (normal) → OPEN (tripped) → HALF_OPEN (testing)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout_sec: int = 300,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout_sec = reset_timeout_sec
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._state = "CLOSED"

    @property
    def state(self) -> str:
        if self._state == "OPEN":
            if self._opened_at and (time.time() - self._opened_at) > self.reset_timeout_sec:
                self._state = "HALF_OPEN"
                log.info("CircuitBreaker → HALF_OPEN (testing recovery)")
        return self._state

    def is_open(self) -> bool:
        return self.state == "OPEN"

    def record_success(self) -> None:
        self._failures = 0
        if self._state in ("OPEN", "HALF_OPEN"):
            self._state = "CLOSED"
            log.info("CircuitBreaker → CLOSED (recovered)")

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold and self._state == "CLOSED":
            self._state = "OPEN"
            self._opened_at = time.time()
            log.error("CircuitBreaker → OPEN after %d failures", self._failures)

    def reset(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._state = "CLOSED"


# ---------------------------------------------------------------------------
# Guardrails checker
# ---------------------------------------------------------------------------

class GuardrailsChecker:
    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        max_drawdown_pct: float = -20.0,
        max_exposure_x: float = 8.0,
        max_order_rate_4h: int = 6,
        min_equity_usdt: float = 0.0,
    ) -> None:
        self.rate_limiter     = rate_limiter or RateLimiter()
        self.circuit_breaker  = circuit_breaker or CircuitBreaker()
        self.max_drawdown_pct = max_drawdown_pct
        self.max_exposure_x   = max_exposure_x
        self.max_order_rate_4h = max_order_rate_4h
        self.min_equity_usdt  = min_equity_usdt

    def check_action(
        self,
        action_type: ActionType,
        snapshot: AgentSnapshot,
        contract: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Returns: (allowed: bool, reason: str)
        reason = "" jika allowed.
        """
        # 1. Circuit breaker
        if self.circuit_breaker.is_open():
            return False, f"Circuit breaker OPEN (exchange/system error rate high)"

        # 2. Equity floor
        if snapshot.account.equity <= self.min_equity_usdt:
            if action_type not in {ActionType.PAUSE_ENTRIES, ActionType.NOTIFY}:
                return False, f"equity={snapshot.account.equity:.2f} <= floor={self.min_equity_usdt}"

        # 3. Drawdown hard limit
        if snapshot.account.drawdown_pct <= self.max_drawdown_pct:
            if action_type not in {ActionType.PAUSE_ENTRIES, ActionType.NOTIFY, ActionType.CLOSE_POSITION}:
                return False, (
                    f"drawdown={snapshot.account.drawdown_pct:.1f}% <= hard_limit={self.max_drawdown_pct}%"
                )

        # 4. Rate limit (hanya untuk action yang melibatkan order)
        order_actions = HIGH_RISK_ACTIONS | MEDIUM_RISK_ACTIONS | {ActionType.REPLACE_TPSL}
        if action_type in order_actions and contract:
            if not self.rate_limiter.check(contract):
                count = self.rate_limiter.count(contract)
                return False, f"rate_limit: {contract} has {count}/{self.max_order_rate_4h} orders in 4H window"

        # 5. Exposure limit
        if snapshot.account.exposure_x >= self.max_exposure_x:
            # Hanya block action yang menambah exposure (bukan close/reduce)
            if action_type not in {
                ActionType.CLOSE_POSITION, ActionType.REDUCE_POSITION,
                ActionType.PAUSE_ENTRIES, ActionType.CANCEL_STALE_TPSL,
                ActionType.REPLACE_TPSL, ActionType.NOTIFY,
            }:
                return False, f"exposure={snapshot.account.exposure_x:.1f}x >= max={self.max_exposure_x}x"

        return True, ""

    def record_order(self, contract: str) -> None:
        """Panggil setelah setiap order berhasil dikirim."""
        self.rate_limiter.record(contract)
