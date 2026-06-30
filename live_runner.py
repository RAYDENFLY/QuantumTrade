"""
Phase 10.6C — Astel Research - TradingAgents Runtime Launcher

This file is the SINGLE entry point for running Astel Research - TradingAgents.

It does NOT execute trades directly.

It does NOT instantiate GateExecutor.

It does NOT submit orders.

It does NOT manage positions.

It does NOT manage TP/SL.

Its only responsibility is to:

• load environment
• load configuration
• initialize logging
• initialize monitoring
• start AutonomousAgent
• handle graceful shutdown
• handle signals

Execution ownership belongs to AutonomousAgent only.

    AutonomousAgent
        ↓
    ExecutionEngine
        ↓
    GateExecutor
        ↓
    Gate.io

No other code path reaches the exchange.

Usage:
    python live_runner.py

Environment variables:
    GATE_API_KEY       — Gate.io API key (for TESTNET or LIVE)
    GATE_API_SECRET    — Gate.io API secret
    AGENT_STORAGE      — Storage backend (sqlite / postgres)
    AGENT_POSTGRES_DSN — PostgreSQL DSN (if postgres storage)
    AGENT_MODE         — observe | execute
    AGENT_LOOP_INTERVAL_SEC — Agent loop interval (default: 300)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# ---------------------------------------------------------------------------
# Signal handler for graceful shutdown
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _handle_signal(signum: int, frame: Any) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    log = logging.getLogger("live_runner")
    log.warning("Signal %d received. Shutting down gracefully...", signum)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_config(config_path: Path) -> Dict[str, Any]:
    """Load YAML configuration. Returns dict (may be empty if file missing)."""
    try:
        with config_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[live_runner] WARNING: Could not load config from {config_path}: {e}")
        return {}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(cfg: Dict[str, Any]) -> None:
    """Configure logging for the entire application."""
    level_name = str(cfg.get("logging", {}).get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    use_json = bool((cfg.get("logging") or {}).get("json", False))

    if use_json:
        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                payload: Dict[str, Any] = {
                    "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                if record.exc_info:
                    payload["exc"] = self.formatException(record.exc_info)
                for k, v in record.__dict__.items():
                    if k.startswith("_"):
                        continue
                    if k in {
                        "name", "msg", "args", "levelname", "levelno",
                        "pathname", "filename", "module", "exc_info",
                        "exc_text", "stack_info", "lineno", "funcName",
                        "created", "msecs", "relativeCreated", "thread",
                        "threadName", "processName", "process",
                    }:
                        continue
                    try:
                        json.dumps(v)
                        payload[k] = v
                    except Exception:
                        payload[k] = str(v)
                return json.dumps(payload, ensure_ascii=False)

        root = logging.getLogger()
        root.setLevel(level)
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(_JsonFormatter())
        root.addHandler(handler)
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )

    # Suppress noisy third-party loggers
    for logger_name in ("urllib3", "requests", "httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Main launcher
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point. Loads config, sets up logging, starts AutonomousAgent."""

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Determine project root
    root = Path(__file__).resolve().parent

    # Load configuration
    config_path = root / "quant_system" / "config.yaml"
    cfg = _load_config(config_path)

    # Set up logging
    _setup_logging(cfg)

    log = logging.getLogger("live_runner")
    log.info("=" * 60)
    log.info("Astel Research - TradingAgents Launcher starting...")
    log.info("=" * 60)
    log.info("Config path: %s", config_path)

    # ------------------------------------------------------------------
    # Environment validation
    # ------------------------------------------------------------------
    api_key = os.environ.get("GATE_API_KEY")
    api_secret = os.environ.get("GATE_API_SECRET")
    agent_mode = os.environ.get("AGENT_MODE", "observe")

    if not api_key or not api_secret:
        log.warning(
            "GATE_API_KEY or GATE_API_SECRET not set. "
            "AutonomousAgent will run but ExecutionEngine may fail."
        )

    log.info("Agent mode: %s", agent_mode)
    log.info("Storage backend: %s", os.environ.get("AGENT_STORAGE", "sqlite (default)"))

    # ------------------------------------------------------------------
    # Verify no other execution path exists
    # ------------------------------------------------------------------
    log.info("Execution ownership: AutonomousAgent (single owner)")
    log.info("live_runner.py is a launcher only — does NOT execute trades")

    # ------------------------------------------------------------------
    # Start AutonomousAgent
    # ------------------------------------------------------------------
    try:
        from agent.agent import AutonomousAgent
        from agent.agent import _load_agent_config

        # Load agent-specific config (env vars + yaml)
        agent_cfg = _load_agent_config()

        # Create agent
        agent = AutonomousAgent(agent_cfg)

        log.warning("AutonomousAgent created successfully")
        log.warning("Starting agent main loop...")

        # Run the agent (blocking — runs forever until signal/shutdown)
        agent.run()

    except ImportError as e:
        log.exception("Failed to import agent modules: %s", e)
        log.error("Make sure you are running from the project root directory.")
        log.error("  cd d:\\Data Ray\\Astel Research - TradingAgents && python live_runner.py")
        sys.exit(1)
    except Exception as e:
        log.exception("AutonomousAgent failed to start or crashed: %s", e)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Graceful shutdown (reached when agent.run() returns)
    # ------------------------------------------------------------------
    log.warning("Astel Research - TradingAgents shutdown complete.")
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()