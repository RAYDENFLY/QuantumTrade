<p align="center">
  <a href="https://github.com/RAYDENFLY/Astel">
    <img src="https://github.com/RAYDENFLY/Astel/blob/main/assets/logo/astel-text.png" alt="Astel" width="500">
  </a>
</p>

# Astel Research - TradingAgents

**Autonomous AI-Powered Cryptocurrency Futures Trading System**

[![Status](https://img.shields.io/badge/Status-Observation%20Mode-blue)]()
[![Exchange](https://img.shields.io/badge/Exchange-Gate.io%20Testnet-green)]()
[![Python](https://img.shields.io/badge/Python-3.11%2B-brightgreen)]()
[![License](https://img.shields.io/badge/License-MIT-yellow)]()
[![Release](https://img.shields.io/github/v/release/RAYDENFLY/Astel?include_prereleases)](https://github.com/RAYDENFLY/Astel/releases)

Astel Research - TradingAgents is an autonomous AI trading system that combines **machine learning predictions**, **episodic memory**, **procedural memory**, **LLM reasoning**, and a **self-reflection feedback loop** to make and execute trading decisions on Gate.io Futures (Testnet).

The system operates continuously, learning from every trade through a multi-layered memory architecture and improving its decision quality over time through reinforcement-based pattern validation and self-reflection.

---

> **Creator & Lead Researcher:** [Azis Maulana Suhada](https://raydenfly.my.id)  
> **Developed by:** PT Authentic Media Servicex  
> **Research Areas:** Autonomous AI Agents • Quantitative Trading • Machine Learning • Large Language Models (LLMs)

## Overview

Astel Research - TradingAgents is built on the philosophy that successful autonomous trading requires more than a single ML model. It needs:

1. **Market Perception** — Feature engineering and ML prediction models that detect market regimes and generate probabilistic forecasts.
2. **Memory** — A structured memory system that stores what worked, what didn't, and why, across three dimensions: procedural rules, episodic experiences, and shadow validation.
3. **Reasoning** — LLM-powered reasoning that considers market state, memory context, risk policy, and past outcomes before making decisions.
4. **Execution** — A robust, fault-tolerant execution engine with rate limiting, deduplication, retry logic, and full trade lifecycle recording.
5. **Reflection** — A self-reflection feedback loop that analyzes every completed trade and feeds improvements back into the memory system.

```
Market Data
     │
     ▼
Feature Engineering ──► Machine Learning
                              │
                              ▼
   ┌─────────────────────────────────────┐
   │          MEMORY SYSTEM              │
   │  ┌────────┐  ┌────────┐  ┌───────┐ │
   │  │Proced. │  │Episode │  │Shadow │ │
   │  │Memory  │  │ Memory │  │Memory │ │
   │  └───┬────┘  └───┬────┘  └───┬───┘ │
   │      └──────────┬┘──────────┘      │
   │                 ▼                  │
   │        Memory Context Builder      │
   └─────────────────┬──────────────────┘
                     │
                     ▼
   ┌─────────────────────────────────────┐
   │         LLM REASONING               │
   │  ┌────────┐  ┌────────┐  ┌───────┐ │
   │  │  Groq  │  │ Ollama │  │DeepS. │ │
   │  └────────┘  └────────┘  └───────┘ │
   │         Reasoning Validator         │
   │         Reasoning Feedback          │
   │         Self-Reflection Loop        │
   └─────────────────┬──────────────────┘
                     │
                     ▼
   ┌─────────────────────────────────────┐
   │           PLANNER                   │
   │  Rule-based Plan + LLM Plan         │
   │  Policy Filtering                   │
   │  Guardrail Validation               │
   │  Risk Policy Application            │
   └─────────────────┬──────────────────┘
                     │
                     ▼
   ┌─────────────────────────────────────┐
   │         EXECUTION ENGINE            │
   │  Retry Logic │ Dedup │ Rate Limit   │
   │  GateExecutor → Gate.io Testnet     │
   └─────────────────┬──────────────────┘
                     │
                     ▼
   ┌─────────────────────────────────────┐
   │         TRADE REPLAY                │
   │  AI Flight Recorder — 20 stages     │
   └─────────────────┬──────────────────┘
                     │
                     ▼
   ┌─────────────────────────────────────┐
   │         DASHBOARD                   │
   │  Agent │ Evolution │ Performance    │
   │  Memory │ Self-Reflection           │
   └─────────────────────────────────────┘
```

---

## Core Components

### AutonomousAgent

The central orchestrator that runs a continuous loop (default: every 300 seconds). Each tick performs market snapshot, analyst evaluation, plan generation (rule-based + LLM), guardrail checking, execution, memory recording, and reflection.

- **Mode**: `observe` (monitor only) or `execute` (submit orders)
- **Survival Mode**: NORMAL → CONSERVATIVE → DEFENSIVE → HIBERNATE
- **Treasury Management**: Tracks capital, deducts operational costs, manages runway

### ExecutionEngine

A unified, fault-tolerant order execution wrapper that delegates to GateExecutor. Every order passes through:

1. **Dedup Cache** — 5-second TTL prevents duplicate order submission
2. **Risk Callback** — Pre-execution validation via Guardrails
3. **Rate Limiter** — Maximum 5 requests/second
4. **Retry with Backoff** — Up to 3 attempts with exponential backoff
5. **Storage Callback** — Every order stored in `agent_orders` table

Supports SIMULATION, TESTNET, and LIVE modes with identical code paths.

### GateExecutor

Direct Gate.io Futures API client supporting:

- Market orders (BUY/SELL)
- Limit orders
- TP/SL trigger orders (reduce-only)
- Position queries and reconciliation
- Leverage management
- Candlestick data fetching
- Account equity queries

### MemoryContextBuilder

**Phase 9.1** — Builds rich context for LLM reasoning by aggregating:

- Current market snapshot
- Survival mode and treasury state
- Procedural memory rules
- Shadow memory influence scores
- Recent episode outcomes
- Memory attribution data

### ReasoningValidator

**Phase 9.2** — Audits every LLM plan for:

- Memory usage score (did the LLM consider memory?)
- Context size and latency
- Which memory dimensions were used (procedural, episodic, shadow, ML, portfolio, risk, treasury)
- Raw reasoning content analysis

### ReasoningFeedbackEngine

**Phase 9.3** — Stores feedback from reasoning audits and builds a feedback prompt that is injected into the next LLM call. Creates a continuous self-reflection loop.

### TradeRecorder

**Phase 10.5** — The AI Flight Recorder. Records every stage of every trade as a structured timeline with standard metadata:

```
trade_created → agent_tick → market_snapshot → ml_prediction →
memory_context → reasoning_feedback → llm_reasoning →
agent_plan → guardrail → risk_validation → execution_request →
exchange_response → position_update → position_closed →
pnl_realized → reflection → memory_update → trade_complete
```

Every event stores: `trade_id`, `event_type`, `event_index`, `timestamp`, `status`, `duration_ms`, `provider`, `confidence`, `latency_ms`, `plan_id`, `event_data`.

Thread-safe with per-trade locks. **Never crashes the trading engine** — all failures are logged as warnings.

### Replay System

Two database tables with full indexing:

| Table | Columns | Indexes |
|-------|---------|---------|
| `agent_trade_replay_events` | 12 columns | 3 indexes (trade_id, event_type, composite) |
| `agent_trade_replay_summary` | 10 columns | 3 indexes (trade_id, status, created) |

---

## AI Memory Architecture

Astel Research - TradingAgents implements a multi-layered memory system inspired by cognitive architectures:

### Procedural Memory (Phase 7D.1)

Stores validated trading rules extracted from successful patterns. Rules are injected as context into LLM prompts. Managed by `ProceduralMemory` class with rule extraction, scoring, and injection.

### Episodic Memory (Phase 7A)

Records every action as an episode with full context: market state, decision, outcome, and importance score. Episodes are resolved after 6 hours with objective performance metrics. Managed by `EpisodeResolver`.

- 500+ episode capacity
- Importance scoring for selective retention
- Outcome resolution with survival score deltas

### Shadow Memory (Phase 2 + 8.1)

A read-only comparator that observes agent decisions without interference. Shadow observations are resolved after 24 hours with counterfactual analysis. Influence scores measure how well agent decisions align with memory-recommended actions.

- 24-hour observation window
- Counterfactual PnL calculation
- Agreement/disagreement tracking
- Influence weight calibration

### Memory Mining & Pattern Validation (Phase 7C)

`MemoryMiner` extracts recurring patterns from resolved episodes. `PatternValidator` scores each pattern for statistical significance. Validated patterns feed into procedural memory.

- Mining interval: every 10-50 ticks
- Pattern validity scoring (0.0 - 1.0)
- Automatic revalidation

### Memory Attribution (Phase 7D.2)

`MemoryAttributionEngine` tracks which memory rules influenced which decisions, and whether those decisions led to positive or negative outcomes. Enables per-rule contribution scoring.

### Reasoning Feedback Loop (Phase 9.3)

Every LLM call is audited for memory usage. Audit results are stored, aggregated, and injected as feedback into subsequent LLM prompts. Creates a continuous improvement cycle:

```
LLM Call → Reasoning Audit → Feedback Storage → Prompt Injection → Next LLM Call
```

---

## Trade Lifecycle

A complete trade follows this pipeline:

```
Agent Tick (every 300s)
     │
     ▼
1. Market Snapshot ──► Fetch account state, positions, treasury
     │
     ▼
2. Analyst Team ──► Multi-analyst reports with consensus scoring
     │
     ▼
3. Survival Mode ──► Deterministic mode selection (drawdown-based)
     │
     ▼
4. Rule-Based Plan ──► Immediate actions for clear conditions
     │
     ▼
5. Memory Context ──► Build rich context for LLM from all memory layers
     │
     ▼
6. LLM Reasoning ──► Groq / Ollama / DeepSeek with feedback injection
     │
     ▼
7. Agent Plan ──► Proposed actions with confidence scoring
     │
     ▼
8. Policy Filter ──► Remove actions violating current mode
     │
     ▼
9. Guardrails ──► Check rate limits, circuit breaker, drawdown
     │
     ▼
10. Execution ──► Submit order via ExecutionEngine → GateExecutor
     │
     ▼
11. Exchange Response ──► Record fill, latency, fees, order ID
     │
     ▼
12. TP/SL Management ──► Attach take-profit / stop-loss triggers
     │
     ▼
13. Episode Recording ──► Store action as episodic memory
     │
     ▼
14. Bull/Bear Research ──► Multi-perspective market analysis
     │
     ▼
15. Memory Update ──► Pattern mining, validation, attribution
     │
     ▼
16. Trade Replay ──► Record every stage with standard metadata
     │
     ▼
17. Self Reflection ──► Analyze outcome, store feedback for next LLM call
```

---

## Execution Model

Astel Research - TradingAgents maintains a **single execution owner** architecture. The only process that can submit orders to Gate.io is `AutonomousAgent` via `ExecutionEngine` → `GateExecutor`.

```
live_runner.py (launcher only)
     │
     ▼
AutonomousAgent (agent.py)
     │
     ▼
ExecutionEngine (quant_system/execution/execution_engine.py)
     │
     ▼
GateExecutor (quant_system/execution/gate_executor.py)
     │
     ▼
Gate.io Futures Testnet / Live
```

`live_runner.py` is a lightweight launcher that:

- Loads environment configuration
- Initializes logging
- Starts AutonomousAgent
- Handles signals for graceful shutdown

It does **not** instantiate `GateExecutor`, submit orders, manage positions, or set TP/SL. Those responsibilities belong exclusively to `AutonomousAgent`.

This architecture was chosen to prevent:

- Duplicate order submission
- TP/SL flapping between competing systems
- Inconsistent position management
- Incomplete replay data

---

## Dashboards

| Dashboard | Route | Description |
|-----------|-------|-------------|
| Agent Dashboard | `/agent` | Real-time agent state, treasury, survival mode, plans |
| Evolution Dashboard | `/evolution` | Pattern growth, memory learning curves, contribution scores |
| Performance Dashboard | `/performance` | Win rate, PnL, Sharpe, drawdown over time |
| Memory Dashboard | `/memory` | Memory usage scores, dimensions used, attribution metrics |
| Self Reflection Dashboard | `/reflection` | Feedback trends, reasoning quality, improvement metrics |

All dashboards are served by a FastAPI application at `dashboard/app.py`.

---

## Project Structure

```
Astel Research - TradingAgents/
│
├── live_runner.py              # Runtime launcher (single entry point)
├── requirements.txt            # Python dependencies
├── .env                        # Environment configuration
├── README.md                   # This file
│
├── agent/                      # AI Agent subsystem
│   ├── agent.py                # AutonomousAgent main loop
│   ├── actions.py              # Action execution dispatch
│   ├── analysts.py             # Multi-analyst team
│   ├── guardrails.py           # Guardrails, rate limiter, circuit breaker
│   ├── llm_client.py           # LLM Router (Groq/Ollama/DeepSeek)
│   ├── policy.py               # Survival mode policy + rule-based planning
│   ├── schema.py               # Pydantic models for plans/snapshots
│   ├── snapshot.py             # Market data snapshot fetcher
│   ├── researcher.py           # Bull/Bear research team
│   ├── shadow.py               # Shadow comparator (Phase 2)
│   ├── storage.py              # AgentStorage (SQLite + PostgreSQL)
│   ├── trade_replay.py         # TradeRecorder / AI Flight Recorder
│   ├── daily_report.py         # Daily operational report generator
│   ├── observe_hourly.py       # Hourly observation monitor
│   ├── memory.py               # Episode resolver
│   ├── memory_miner.py         # Pattern mining (Phase 7C)
│   ├── memory_sandbox.py       # Memory advisor (Phase 7D.0)
│   ├── memory_context.py       # Memory context builder (Phase 9.1)
│   ├── memory_attribution.py   # Memory attribution engine (Phase 7D.2)
│   ├── memory_shadow.py        # Shadow memory influence (Phase 8.1)
│   ├── procedural_memory.py    # Procedural memory (Phase 7D.1)
│   ├── pattern_validator.py    # Pattern validation (Phase 7C.2)
│   ├── reasoning_validator.py  # Reasoning audit (Phase 9.2)
│   └── reasoning_feedback.py   # Reasoning feedback (Phase 9.3)
│
├── quant_system/               # Quantitative subsystem
│   ├── config.yaml             # Main configuration
│   ├── main.py                 # System entry point (legacy)
│   ├── execution/
│   │   ├── execution_engine.py # Fault-tolerant execution wrapper
│   │   └── gate_executor.py    # Gate.io API client
│   ├── features/
│   │   └── build_features.py   # Feature engineering pipeline
│   ├── model/
│   │   └── predict.py          # ML prediction model
│   ├── risk/
│   │   └── risk_manager.py     # Position sizing and risk
│   ├── data/
│   │   └── fetch_data.py       # Market data fetcher
│   ├── database/
│   │   ├── db.py               # Database manager
│   │   └── journal.py          # Trade journal (legacy)
│   └── utils/
│       └── env.py              # Environment loader
│
├── dashboard/                  # Web dashboard
│   ├── app.py                  # FastAPI application
│   ├── data_service.py         # Data aggregation layer
│   └── templates/
│       ├── agent.html          # Agent dashboard
│       └── ...                 # Other dashboards
│
├── scripts/                    # Utility scripts
│   ├── gate_set_leverage_test.py
│   ├── repair_closures_from_gate.py
│   ├── reset_journal_db.py
│   └── train_from_gate.py
│
├── docs/                       # Documentation
│   ├── PROJECT_DOCUMENTATION.md
│   ├── phase5_bull_bear_researcher.md
│   ├── phase7_memory_learning_layer.md
│   ├── phase7_5_learning_acceleration.md
│   ├── phase7_6_3_data_lineage_audit.md
│   └── phase7_6_6_attribution_repair_design.md
│
└── reports/                    # Generated reports
    ├── daily_*.json            # Daily operational reports
    └── hourly_*.json           # Hourly observation snapshots
```

---

## Installation

### Prerequisites

- **Python 3.11+**
- **Ollama** (for local LLM inference)
- **PostgreSQL** (optional, SQLite fallback available)
- **Gate.io Testnet account** (free)

### Dependencies

```bash
pip install -r requirements.txt
```

Key dependencies:

- `pydantic` — Data validation
- `psycopg2-binary` — PostgreSQL driver
- `fastapi` — Dashboard server
- `uvicorn` — ASGI server
- `pyyaml` — Configuration
- `numpy`, `pandas` — Data processing
- `lightgbm` — ML model training
- `python-dotenv` — Environment loading

### Ollama Setup

```bash
# Install Ollama (see https://ollama.ai)
# Pull recommended models:
ollama pull qwen2.5:7b
ollama pull llama3.2:3b
```

### Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# Gate.io API
GATE_API_KEY=your_testnet_api_key
GATE_API_SECRET=your_testnet_api_secret

# Agent mode: observe | execute
AGENT_MODE=observe

# Storage (SQLite is default)
AGENT_STORAGE=sqlite

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_PRIMARY_MODEL=qwen2.5:7b
OLLAMA_FALLBACK_MODEL=llama3.2:3b

# Cloud LLM (optional)
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
DEEPSEEK_API_KEY=
AGENT_CLOUD_BUDGET_USD=0.0

# Agent loop timing
AGENT_LOOP_INTERVAL_SEC=300
AGENT_LLM_INTERVAL_SEC=3600

# Treasury
AGENT_INITIAL_TREASURY_USDT=20.0

# Dashboard
DASHBOARD_BASE_URL=http://localhost:8000
```

---

## Running

### 1. Start the Agent

```bash
# Observation mode (recommended for first run):
python live_runner.py

# The agent will start in the mode specified by AGENT_MODE in .env
# Default: observe (no orders submitted)
```

### 2. Start the Dashboard

```bash
# In a separate terminal:
python -m dashboard.app
# Open http://localhost:8000 in your browser
```

### 3. Monitor Hourly

```bash
# In a separate terminal:
python -m agent.observe_hourly

# Generates hourly snapshots in /reports/
# Press Ctrl+C to stop monitoring (agent continues)
```

### 4. Generate Daily Reports

```bash
python -m agent.daily_report

# Output: reports/daily_YYYY-MM-DD.json
```

### 5. Run Validation Suite

```bash
python agent/phase10_6_validation.py

# 285 checks covering storage, replay, performance, error handling
```

---

## Current Status

| Phase | Status |
|-------|--------|
| Operational Validation | ✅ Complete |
| Smoke Test | ✅ Complete |
| Execution Audit | ✅ Complete |
| Execution Unification | ✅ Complete |
| Gate.io Testnet Audit | ✅ Complete |
| **48-Hour Observation** | **🔄 In Progress** |

**Current Phase**: 10.7A — 48-Hour Observation Mode

**Readiness Score**: 99/100

**Single Execution Owner**: ✅ Achieved (AutonomousAgent only)

---

## Roadmap

### Completed Phases

| Phase | Description |
|-------|-------------|
| Phase 1-4 | Base agent loop, Shadow comparator, Analyst team, Bull/Bear research |
| Phase 5 | ML model integration, feature engineering, prediction pipeline |
| Phase 6 | Experiment tracking, survival mode, treasury management |
| Phase 7A-7D | Episodic memory, memory mining, pattern validation, memory attribution |
| Phase 8 | Shadow memory influence |
| Phase 9.1-9.3 | Memory context builder, reasoning validator, reasoning feedback |
| Phase 10 | ExecutionEngine, GateExecutor, order management |
| Phase 10.5 | Trade Replay / AI Flight Recorder |
| Phase 10.5B-10.5C | Replay storage, runtime integration |
| Phase 10.6 | Operational validation, smoke test, execution audit |
| Phase 10.6C | Execution unification (single owner) |
| Phase 10.6D | Gate.io Testnet readiness audit |

### Upcoming Phases

| Phase | Description |
|-------|-------------|
| 10.7B | **30-Day Testnet Execution** — Continuous Testnet trading |
| 10.8 | **LIVE Deployment** — Production exchange connection |
| 10.9 | **Dashboard Evolution** — Real-time trade replay viewer |
| 11 | **Multi-Agent Coordination** — Specialized trading sub-agents |
| 12 | **Advanced Risk** — VaR modeling, dynamic position sizing |

---

## Technology Stack

| Category | Technology |
|----------|-----------|
| Language | Python 3.11+ |
| Web Framework | FastAPI + Uvicorn |
| Frontend | Tailwind CSS + Chart.js |
| Database | PostgreSQL / SQLite |
| LLM | Ollama (local) • Groq (cloud) • DeepSeek (cloud) |
| Exchange | Gate.io Futures API v4 |
| ML Models | LightGBM / XGBoost |
| Data Validation | Pydantic v2 |

---

## License

MIT License

Copyright (c) 2026 Astel Research - TradingAgents

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Acknowledgements

- **[Gate.io](https://www.gate.io/)** — Futures API and Testnet infrastructure
- **[Ollama](https://ollama.ai/)** — Local LLM inference platform
- **[Groq](https://groq.com/)** — Cloud LLM inference with LPU architecture
- **[DeepSeek](https://deepseek.com/)** — Cloud LLM provider
- **[LightGBM](https://lightgbm.readthedocs.io/)** — Gradient boosting framework
- **[FastAPI](https://fastapi.tiangolo.com/)** — Modern Python web framework
- **[Tailwind CSS](https://tailwindcss.com/)** — Utility-first CSS framework
