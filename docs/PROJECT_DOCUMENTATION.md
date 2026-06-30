# Astel Research - TradingAgents — Project Documentation (Lengkap)

> Dokumen ini dibuat untuk menjelaskan **Astel Research - TradingAgents** secara end-to-end (offline + live), termasuk arsitektur, alur data, modul utama, kontrak API/WebSocket, skema database SQLite, dan panduan menjalankan sistem.  
> Fokus utamanya adalah **engineering system + auditability + monitoring**, bukan janji profit.

---

## 0) Ringkasan satu paragraf

**Astel Research - TradingAgents** adalah sistem trading kuantitatif yang **config-driven** (dikontrol oleh `quant_system/config.yaml`) dengan dua mode:

- **Offline mode**: mengambil/menyiapkan dataset OHLCV (dari CSV cache), melakukan feature engineering, melatih model Machine Learning (LightGBM), dan melakukan evaluasi/backtest sederhana.
- **Live mode**: membaca candle **4H yang baru selesai (close)** dari Gate.io USDT Futures, membuat sinyal, mengeksekusi order futures, memasang **TP/SL** sebagai trigger orders di exchange, lalu mencatat seluruh aktivitas ke **SQLite journal** dan menampilkannya pada **dashboard web** (FastAPI + UI).

---

## 1) Target pengguna & scope

### 1.1 Untuk siapa?

- Pengembang/peneliti yang ingin studi **pipeline trading otomatis** (data → model → execution → journaling → monitoring).
- Mahasiswa yang ingin menjadikan proyek ini sebagai **TA Teknik Komputer** dengan fokus integrasi sistem, reliability, dan audit trail.

### 1.2 Yang *termasuk* di scope

- Pengambilan data candle (OHLCV) dari Gate futures (USDT).
- Caching data ke CSV (agar dataset makin besar dari waktu ke waktu).
- Training model ML (LightGBM) dan inference saat live.
- Eksekusi futures (market order) + set leverage + pasang TP/SL via trigger orders.
- Journaling audit ke SQLite: trades, equity_curve, weekly_performance, trade_closures.
- Dashboard monitoring (FastAPI + HTML) + realtime update (WebSocket) untuk Open Positions dan Unrealized PnL.

### 1.3 Yang *tidak dijamin*

- Profitabilitas.
- Ketahanan pada semua kondisi market / semua error exchange.

---

## 2) Struktur folder (high-level)

```
Astel Research - TradingAgents/
  quant_system/
    config.yaml
    execution/
      gate_executor.py
    database/
      schema.sql
      db.py
      journal.py
    data/
      csv/
    models/
    reports/
    ...

  dashboard/
    app.py
    data_service.py
    templates/
      index.html

  scripts/
    train_from_gate.py

  live_runner.py
  README.md
  docs/
    PROJECT_DOCUMENTATION.md
```

---

## 3) Konfigurasi utama (`quant_system/config.yaml`)

File ini adalah pusat pengaturan sistem. Beberapa bagian penting:

### 3.1 Sistem & waktu

- `system.timeframe`: default `"4H"` → sistem live trading memproses candle 4 jam.
- `system.prediction_horizon_bars`: horizon prediksi (mis. 1 bar ke depan).

### 3.2 Assets (contracts)

- `assets`: daftar kontrak Gate futures, contoh: `BTC_USDT`, `ETH_USDT`, dst.

> Catatan Gate: format contract umumnya `SYMBOL_USDT` (underscore). Bila sebuah pair error 400, cek contract name yang benar dari Gate.

### 3.3 Data

- `data.source`: `"gate"` untuk mengambil candle dari exchange.
- `data.csv_dir`: lokasi cache OHLCV.
- `data.gate.candles_limit`: jumlah candle yang diambil per request.

### 3.4 Risk & execution

- `risk.risk_per_trade`: risk sizing.
- `execution.max_open_pairs`: batas jumlah pair yang boleh punya posisi terbuka.
- `execution.leverage_min` / `execution.leverage_max`: clamp leverage sebelum dikirim ke Gate.

### 3.5 Gate environment

- `gate.base_url`: mis. testnet `https://api-testnet.gateapi.io/api/v4`.
- Credential **tidak disimpan di config**:
  - `GATE_API_KEY`
  - `GATE_API_SECRET`

### 3.6 Display

- `display.usdt_to_idr`: angka kurs untuk display dashboard (Rp + terbilang).

---

## 4) Arsitektur modul & tanggung jawab

### 4.1 Execution Adapter — `quant_system/execution/gate_executor.py`

Tanggung jawab utama:

- Signing request Gate v4 (HMAC SHA512)
- Retry/backoff untuk request yang gagal
- Read operations:
  - `get_account_equity()`
  - `get_open_positions()`
  - `get_open_trigger_orders()`
- Write operations (live runner):
  - `place_market_order(...)`
  - `set_leverage(...)`
  - `place_tpsl_orders(...)` → membuat trigger order TP/SL reduce-only

Tag order TP/SL agar mudah dipetakan di dashboard:

- `t-qt-tp`
- `t-qt-sl`

### 4.2 Live loop — `live_runner.py`

Kontrak perilaku:

- Polling interval (mis. 60 detik)
- Hanya trading saat **candle 4H baru close**
- Flow:
  1. Ambil candle terbaru
  2. Buat fitur, prediksi model
  3. Jika sinyal entry valid:
     - set leverage
     - place market order entry
     - place trigger orders TP/SL
     - jurnal entry ke SQLite (termasuk fee & order ids)
  4. Rekonsiliasi: jika journal masih OPEN tapi exchange sudah flat, catat closure ke `trade_closures`

### 4.3 Database layer — `quant_system/database/*`

- `schema.sql`: definisi tabel
- `db.py`: koneksi, migrasi/additive schema
- `journal.py`: operasi insert/update journal (trades/equity/weekly/closures)

### 4.4 Dashboard — `dashboard/app.py`, `dashboard/data_service.py`, `dashboard/templates/index.html`

- `dashboard/app.py`
  - REST API untuk UI
  - WebSocket realtime untuk open positions snapshot
- `dashboard/data_service.py`
  - Akses Gate lewat executor (read-only)
  - Baca SQLite untuk derived stats
  - Helper compute drawdown/exposure
- `dashboard/templates/index.html`
  - UI Tailwind
  - auto-refresh (10s) untuk non-realtime widgets
  - WS realtime untuk Open Positions + Unrealized PnL
  - Charts (Chart.js)

---

## 5) Skema Database SQLite (audit / journaling)

Sumber: `quant_system/database/schema.sql`.

### 5.1 Tabel `trades`

Menyimpan trade entry dan status OPEN/CLOSED (level “journal entry”). Kolom penting:

- `trade_id`: PK
- `timestamp`
- `asset`
- `side`
- `qty`
- `entry_order_id`, `tp_order_id`, `sl_order_id`
- `entry_price`
- `entry_fee`
- `stop_price`
- `tp_price`
- `leverage_implied`
- `prediction`
- `risk_at_stop`
- `status`

### 5.2 Tabel `trade_closures`

Satu record ketika posisi benar-benar dianggap closed (realized):

- `trade_id` (FK ke `trades` jika tersedia)
- `exit_order_id`
- `exit_reason` (mis. TP, SL, manual, reconcile)
- `gross_pnl`, `fees`, `pnl`

> Tabel ini dipakai untuk metrik performa yang “exchange-accurate”.

### 5.3 `equity_curve`

- snapshot equity (ts, equity)

### 5.4 `weekly_performance`

- ringkasan performa per minggu

### 5.5 `runner_state`

- generic key/value untuk menyimpan state runner

---

## 6) API Dashboard (REST) — Kontrak & contoh respons

Semua endpoint ini disediakan oleh `dashboard/app.py`.

### 6.1 Docs otomatis (OpenAPI)

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- Spec JSON: `/openapi.json`

### 6.2 `GET /api/account`

Tujuan: menampilkan equity, peak equity, drawdown, exposure.

Contoh response (shape):

- `equity`: float
- `peak_equity`: float
- `drawdown`: float (0..1)
- `total_exposure`: float (0..n)
- `usdt_to_idr`: optional

### 6.3 `GET /api/open-positions`

Tujuan: sumber data tabel **Open Positions**.

Response:

```json
{
  "positions": [
    {
      "contract": "BTC_USDT",
      "size": 0.001,
      "mark_price": 45000.0,
      "entry_price": 44900.0,
      "lever": 10,
      "unrealised_pnl": 1.23,
      "tp_price": 45500.0,
      "sl_price": 44500.0
    }
  ]
}
```

Catatan:

- Ini *mostly* mirror payload Gate, sehingga field lain pun bisa ada.
- `tp_price` / `sl_price` bisa datang dari:
  1) trigger order tag `t-qt-tp` / `t-qt-sl`
  2) fallback dari journal SQLite bila trigger order tidak terlihat

### 6.4 `GET /api/qt-performance-metrics`

Tujuan: sumber data card **QT PERFORMANCE METRICS**.

Bersumber dari SQLite `trade_closures`.

Response (shape):

- `total_net_pnl`: float
- `avg_win_rate`: float (0..1) atau null
- `total_win`: int
- `total_loss`: int
- `avg_total_pnl`: float atau null
- `avg_apy`: null (placeholder)

---

## 7) Realtime API (WebSocket)

### 7.1 `WS /ws/positions`

Tujuan:

- realtime update tabel **Open Positions**
- realtime update card **Unrealized PnL**

Server mengirim snapshot periodik (default 2 detik).

Message `type=positions`:

```json
{
  "type": "positions",
  "positions": [ ... ],
  "unreal_pnl": 12.34,
  "pos_count": 3,
  "ts": 1234567890
}
```

Message error:

```json
{ "type": "error", "message": "..." }
```

---

## 8) Cara menjalankan (Windows / PowerShell)

> Catatan: gunakan environment Python yang sama (venv/conda) untuk menghindari missing deps.

### 8.1 Menjalankan dashboard

```powershell
cd "D:\Data Ray\Astel Research - TradingAgents"
python -m uvicorn dashboard.app:app --reload --port 8000
```

Buka:

- http://127.0.0.1:8000

### 8.2 Menjalankan live runner

```powershell
cd "D:\Data Ray\Astel Research - TradingAgents"
python live_runner.py
```

### 8.3 Training dari Gate candles + cache ke CSV

```powershell
cd "D:\Data Ray\Astel Research - TradingAgents"
python scripts\train_from_gate.py
```

---

## 9) Observability & debugging

### 9.1 Hal yang sering ditanyakan

- “Kenapa TP/SL di dashboard ‘—’?”
  - Bisa karena trigger orders tidak terset, tidak terlihat, atau fallback juga tidak ada.
  - Sistem sudah coba membaca dari:
    1) trigger orders tag `t-qt-tp` / `t-qt-sl`
    2) journal trade OPEN (SQLite)

- “Kenapa angka Rp ada terbilang?”
  - `display.usdt_to_idr` di config dipakai untuk konversi.

### 9.2 Tentang limit API

WS di sini bukan streaming market tick; server tetap melakukan polling call ke Gate setiap beberapa detik. Jika terlalu cepat, bisa kena rate limit. Default dibuat konservatif.

---

## 10) Catatan keamanan (wajib dibaca)

- Jangan commit file `.env`
- Pastikan api key scope minimum.
- Mulai dari testnet.
- Periksa `gate.base_url` sebelum run live.

---

## 11) TA Teknik Komputer — cara memposisikan proyek

Poin yang paling “Teknik Komputer/Engineering” pada proyek ini:

- Arsitektur modular (execution adapter, runner, dashboard)
- Reliability (retry, fallback, reconcile journal ↔ exchange)
- Auditability (SQLite journaling lengkap + closures realized)
- Real-time monitoring (WS, UI, charts)

Judul yang cocok:

**Rancang Bangun Sistem Trading Otomatis Crypto Futures Berbasis Machine Learning dengan Gate.io API, Manajemen Risiko TP/SL, Jurnal Audit SQLite, dan Dashboard Monitoring Real‑Time**

---

## 12) Checklist fitur (untuk review/demonstrasi)

- [ ] Dashboard jalan (`/`)
- [ ] Swagger docs jalan (`/docs`)
- [ ] Open positions update realtime (WS)
- [ ] Unrealized PnL update realtime (WS)
- [ ] Live runner entry + set TP/SL (Gate)
- [ ] Journaling entry & closure akurat (SQLite)
- [ ] Charts terisi (trade_closures ada data)
