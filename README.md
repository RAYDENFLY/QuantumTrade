# QuantumTrade

Config-driven quantitative trading system with:

- Offline training/backtest pipeline (`quant_system/`)
- Gate.io Futures (USDT) execution adapter
- Live runner (`live_runner.py`) that trades on newly-closed 4H candles
- Monitoring website (FastAPI dashboard) in `dashboard/`
- Autonomous survival agent (`agent/`) with episodic memory, pattern mining, and memory learning layer

> **Safety note**: This repo can place real orders if `gate.base_url` points to production and your API keys have trading permissions. Start on testnet, size small, and consider adding/using a `dry_run` switch.

## Current Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 | ✅ Complete | Foundation, storage, schema, snapshots |
| Phase 1 | ✅ Complete | Observer / shadow mode |
| Phase 2 | ✅ Complete | Experiment tracking |
| Phase 3 | ✅ Complete | Survival economics (treasury, cost, runway) |
| Phase 4 | ✅ Complete | Multi-analyst system (Technical, Market, Survival) |
| Phase 5 | ✅ Complete | Bull vs Bear research & debate engine |
| Phase 6 | ✅ Complete | Continuous survival evaluation |
| Phase 7 | ✅ Complete | **Memory learning layer** (see below) |
| Phase 8 | 📋 Planned | Controlled memory influence |

---

## Phase 7 — Memory Learning Layer (Complete)

The memory learning layer enables the agent to learn from past decisions and build validated patterns from experience. All Phase 7 sub-phases are implemented and verified in production.

### 7A — Episodic Memory

- Every executed action is recorded as an **episode**.
- Episodes contain: action type, survival mode, treasury state, analyst consensus, debate verdict, and snapshot context.
- Episodes resolve after a **6-hour evaluation window**.
- Resolution captures:
  - `decision_quality` (positive / negative / neutral)
  - `survival_score_delta`
  - `equity_delta_pct`
  - `action_success`
  - `debate_verdict`

### 7B — Episode Resolution

- `EpisodeResolver` scans unresolved episodes older than 6 hours.
- Compares stored episode metrics against current experiment state.
- Produces deterministic decision quality classification.
- Triggers attribution outcome recording.

### 7C — Semantic Memory (Pattern Mining)

- `MemoryMiner` scans resolved episodes and groups them by:
  - action_type
  - survival_mode
  - analyst_consensus
  - debate_verdict
- Creates patterns only when:
  - sample_size >= 5
  - success_rate > 0.70 or < 0.30 (significant)
- **Warm-up mining**: fires every 10 loops during the first 100 loops, then every 50 loops.
- Idempotent — checkpoints track the last processed episode ID per pattern.

### 7C.2 — Pattern Validation

- `PatternValidator` validates patterns against:
  - `sample_size >= 10`
  - `confidence_score >= 0.60`
  - `success_rate >= 0.70`
  - `avg_survival_score_delta > 0`
- Validated patterns are flagged as `validated=True` with a `validation_score`.
- Invalid patterns are deactivated.

### 7D.0 — Memory Advisor (Sandbox)

- `MemoryAdvisor` provides counterfactual advice based on validated memory patterns.
- Advice is stored independently — planner decisions are never modified.
- Tracks agreement/disagreement between planner and memory recommendation.

### 7D.1 — Procedural Memory

- `ProceduralMemory` selects relevant validated patterns matching current conditions.
- `inject_for_plan()` is integrated into the agent loop.
- Injects pattern context into every plan cycle after Bull/Bear debate.
- Patterns are scored by relevance (survival mode match, analyst consensus match, debate verdict match).
- Top 5 relevant patterns are injected per plan.
- Memory is advisory only — planner authority is unchanged.

### 7D.2 — Memory Attribution Engine

- `MemoryAttributionEngine` tracks whether memory contributes to successful decisions.
- Attribution context is recorded **after** Bull/Bear research (ensures real debate verdict).
- Attribution captures:
  - `planner_decision`
  - `analyst_consensus`
  - `debate_verdict` (not hardcoded "unknown")
  - `survival_mode`
  - `memory_rules_count` (from validated pattern injections)
  - `memory_confidence`
- Single-record lifecycle — one episode = one attribution row.
- Duplicate attribution bug fixed (now uses UPDATE instead of INSERT).

### 7D.3 — Attribution Hook

- Attribution is triggered by `EpisodeResolver` on episode resolution.
- `attribute_outcome()` updates the existing pending attribution record.
- No duplicate rows created.

---

## Latest Verified Results

Confirmed in production via PostgreSQL audit:

| Component | Status | Detail |
|-----------|--------|--------|
| First semantic pattern | ✅ Created | `TIGHTEN_RISK|NORMAL|conservative|unknown` ss=11 sr=1.0 |
| Pattern validation | ✅ Passed | validation_score=0.7218 (all 4 checks passed) |
| Procedural memory injection | ✅ Active | 10+ injection records with rules=1 |
| Attribution context | ✅ Active | 12+ records with rules=1, conf=0.7218 |
| Memory advice | ✅ Active | 19 advice records stored |
| Debate verdict attribution | ✅ Verified | Real verdicts present in attribution records |
| Memory confidence propagation | ✅ Verified | confidence > 0 flowing through pipeline |
| Duplicate attribution lifecycle | ✅ Fixed | No duplicate episode_id in attributions |

---

## Current Status

**Memory infrastructure is complete.** All Phase 7 components are wired end-to-end:

```
Episode → Resolution → Pattern Mining → Validation → Procedural Injection → Attribution → Advice
```

Memory influence on planner decisions is **intentionally disabled** until:

- Sufficient resolved episodes accumulated (target: 50+)
- Sufficient validated patterns across diverse action groups (target: 3+)
- Sufficient attribution history to measure memory effectiveness (target: 10+ resolved)
- Acceptable diversity across action groups and debate verdicts

**Current mode: PASSIVE LEARNING ONLY**

The system learns, validates, and records memory but does not modify planner behavior.

---

## Roadmap

### Phase 8 — Controlled Memory Influence (Planned)

**Goals:**

- Enable memory-guided recommendations for planner decisions.
- Measure planner agreement vs memory advice.
- Track performance impact of memory-aware decisions.
- Prevent overfitting through confidence thresholds and diversity gates.
- Keep survival policy as the highest authority.

**Constraints:**

- Memory can **recommend** but cannot override hard risk controls.
- Survival mode always wins (NORMAL > CONSERVATIVE > DEFENSIVE > HIBERNATE).
- RiskManager remains the final authority on position sizing and exposure.
- All memory-influenced decisions are logged for audit and rollback.

---

## Apa itu QuantumTrade?

**QuantumTrade** adalah sistem trading kuantitatif yang dirancang **config-driven** (dikontrol dari `quant_system/config.yaml`) dan terdiri dari dua mode utama:

1) **Offline**: menyiapkan dataset OHLCV, feature engineering, training model Machine Learning, dan evaluasi/backtest sederhana.
2) **Live**: membaca candle dari exchange (Gate.io USDT Futures), membuat sinyal ketika candle **4H baru selesai (close)**, mengeksekusi order, memasang TP/SL di exchange, lalu melakukan **journaling ke SQLite** dan menampilkan monitoring di **dashboard** (FastAPI + web UI).

Repo ini fokus pada 3 hal:

- **Integrasi end-to-end**: data → model → eksekusi → audit/jurnal → monitoring
- **Akuntabilitas (auditability)**: semua aksi trading dicatat supaya bisa ditelusuri
- **Monitoring yang mudah dibaca**: posisi, mark price, TP/SL, jurnal, dan metrik performa

> Catatan: hasil profit tidak dijanjikan. Sistem ini adalah proyek engineering untuk otomasi dan monitoring trading berbasis data.

## Arsitektur (ringkas)

Komponen utama:

- `quant_system/`
	- Pipeline offline (training/backtest)
	- Feature engineering
	- Model (LightGBM) dan konfigurasi
	- Risk management (position sizing, stop)
	- Database journaling (SQLite)
- `quant_system/execution/gate_executor.py`
	- Adapter eksekusi Gate.io USDT Futures
	- Signing request, retry, order placement
	- Ambil equity/positions dan trigger orders (TP/SL)
- `live_runner.py`
	- Loop live (biasanya 60 detik) dan trading hanya saat **candle 4H close**
	- Menjaga agar tidak "over-trade" pada candle yang sama
	- Memasang TP/SL di exchange dan mencatat hasil (fee, order id)
- `agent/`
	- Autonomous survival agent (loop 5 menit)
	- Policy engine, guardrails, LLM planner
	- Multi-analyst team + Bull/Bear research
	- Memory learning layer (Phase 7)
- `dashboard/`
	- `dashboard/app.py`: FastAPI (API + serving HTML)
	- `dashboard/templates/index.html`: UI (Tailwind) + Chart.js
	- Data sumber: Gate (read-only) + SQLite (stats/journal)

## Data flow end-to-end

### 1) Data OHLCV (Exchange → CSV cache)

- Candle diambil dari Gate endpoint futures USDT (`/futures/usdt/candlesticks`).
- Data disimpan (upsert/dedup) ke:
	- `quant_system/data/csv/{ASSET}.csv`

Keuntungannya:

- dataset historis makin lama makin kaya
- offline training bisa diulang tanpa selalu memukul API

### 2) Feature engineering + Machine Learning

Secara umum alurnya:

- Load CSV OHLCV
- Buat fitur (returns, rolling stats, volatility, dsb)
- Training model global (LightGBM) sesuai config
- Simpan model agar bisa dipakai saat live

### 3) Signal → eksekusi → TP/SL

Saat live:

- Runner menunggu candle 4H benar-benar close
- Model menghasilkan sinyal (LONG/SHORT/FLAT)
- Jika entry terjadi:
	- dibuat market order
	- lalu langsung pasang TP/SL di exchange menggunakan trigger/plan orders (reduce-only)
	- order diberi tag deterministik:
		- `t-qt-tp` untuk TP
		- `t-qt-sl` untuk SL

### 4) Journaling (audit trail) ke SQLite

Sistem menyimpan record agar bisa diaudit:

- Entry: asset, side, qty, entry_price, stop_price, tp_price, leverage, entry_fee, entry_order_id, tp_order_id, sl_order_id
- Equity curve: snapshot equity berkala
- Weekly performance: ringkasan minggu
- Closures: saat posisi tutup (TP/SL/manual), dicatat ke `trade_closures` (realized PnL, fees)

Intinya: dashboard tidak hanya "lihat" kondisi, tapi punya **catatan historis** untuk evaluasi.

### 5) Monitoring dashboard

Dashboard menampilkan:

- Account summary (equity, peak equity, drawdown)
- Open positions (entry price, mark price, TP/SL, profit)
- Unrealized PnL (real-time dari snapshot positions)
- Charts (all-time win rate, monthly net pnl, monthly WL)
- Recent trades (journal)
- Recent closures (realized)

## Konsep "realtime" di project ini

Realtime di sini berarti **UI update cepat** dengan data terbaru dari exchange, bukan tick-by-tick.

- Open Positions + Unrealized PnL dapat update lewat WebSocket: `WS /ws/positions`
- Server mengirim snapshot setiap beberapa detik (default 2s)

Ini lebih stabil dibanding streaming market data penuh, dan cukup untuk monitoring posisi.

## API layer & dokumentasi

Dashboard menyediakan:

- REST APIs (JSON)
- WebSocket stream untuk positions
- OpenAPI docs otomatis dari FastAPI

Lihat:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Catatan keamanan

- Credential Gate **harus** via environment variables (`GATE_API_KEY`, `GATE_API_SECRET`).
- Jangan commit `.env`.
- Disarankan mulai dari testnet, ukuran kecil, dan pastikan permission API tidak lebih dari yang dibutuhkan.

## Requirements

- Python 3.10+ (you're currently on Python 3.13)
- Pip packages used by the project (pandas, fastapi, uvicorn, lightgbm, etc.)

## Environment variables

Gate credentials are **ENV-only**:

- `GATE_API_KEY`
- `GATE_API_SECRET`

For local dev, you can create a `.env` file in the repo root (it's loaded by `quant_system/utils/env.py`).

Additional environment variables used by the agent:

- `AGENT_STORAGE` — Storage backend (`sqlite` / `postgres` / `auto`)
- `AGENT_POSTGRES_DSN` — PostgreSQL connection string (required for postgres mode)
- `AGENT_MODE` — Agent operating mode (`observe` / `shadow` / `active`)
- `OLLAMA_BASE_URL` — Ollama LLM endpoint
- `GROQ_API_KEY` / `DEEPSEEK_API_KEY` — Cloud LLM API keys
- `AGENT_SERVER_COST_IDR` — Monthly server cost in IDR
- `AGENT_INITIAL_TREASURY_USDT` — Starting treasury balance
- `AGENT_LOOP_INTERVAL_SEC` — Agent loop interval (default 300s)

## Run the monitoring website (dashboard)

The website lives in `dashboard/app.py`.

### Option A — Run directly (recommended)

```powershell
cd "d:\Data Ray\QuantumTrade"
python -m uvicorn dashboard.app:app --reload --port 8000
```

Open:

- http://127.0.0.1:8000

API docs:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

### Option B — Without auto-reload

```powershell
cd "d:\Data Ray\QuantumTrade"
python -m uvicorn dashboard.app:app --port 8000
```

## Run live trading

```powershell
cd "d:\Data Ray\QuantumTrade"
python live_runner.py
```

What it does:

- Loads `quant_system/config.yaml`
- Fetches candles from Gate (`/futures/usdt/candlesticks`)
- Generates a signal when a **new 4H candle closes**
- Places market orders on Gate Futures
- Journals trades/equity into SQLite

## Run the autonomous survival agent

```powershell
cd "d:\Data Ray\QuantumTrade"
python -m agent.agent
```

What it does:

- Fetches account snapshot (positions, equity, SQLite stats)
- Runs analyst team (Technical, Market, Survival)
- Determines survival mode based on drawdown thresholds
- Generates rule-based and LLM plans
- Executes survival actions (pause entries, tighten risk, reduce positions)
- Records episodes for memory learning
- Runs Bull/Bear research and debate
- Mines patterns from resolved episodes
- Validates and injects memory patterns
- Tracks attribution and generates advice

## Train model from Gate candles

This downloads candles for configured assets, persists them to CSV cache, then trains the model.

```powershell
cd "d:\Data Ray\QuantumTrade"
python scripts\train_from_gate.py
```

## Data caching

Exchange OHLCV is cached (upsert/dedup) to:

- `quant_system/data/csv/{ASSET}.csv`

These CSVs act as your growing historical dataset.

## Troubleshooting

### Dashboard won't start

- Make sure `fastapi` and `uvicorn` are installed in the active env.
- If port 8000 is in use, run with another port:

```powershell
python -m uvicorn dashboard.app:app --reload --port 8001
```

### Live runner SQLite error: "11 values for 12 columns"

Fixed by ensuring the SQL `VALUES` placeholder count matches the insert columns in `quant_system/database/journal.py`.

## Dashboard APIs (for frontend / integrations)

### Open Positions

REST:

- `GET /api/open-positions`

Response:

- `{ "positions": [...] }`

Notes:

- Positions are sourced from Gate USDT futures.
- Extra fields may be merged in:
	- `tp_price`, `sl_price` (from trigger orders and/or SQLite journal fallback)

Realtime (WebSocket):

- `WS /ws/positions`

Messages:

- `{"type":"positions","positions":[...],"unreal_pnl":<float>,"pos_count":<int>,"ts":<int>}`
- `{"type":"error","message":"..."}`

### QT Performance Metrics

- `GET /api/qt-performance-metrics`

Response:

- `total_net_pnl`: all-time net PnL (USDT)
- `avg_win_rate`: all-time win rate (0..1)
- `total_win`: number of winning closures
- `total_loss`: number of losing closures
- `avg_total_pnl`: average PnL per win/loss closure

Data source:

- SQLite table `trade_closures`