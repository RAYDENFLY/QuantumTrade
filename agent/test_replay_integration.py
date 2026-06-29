"""
Quick integration test for Phase 10.5 Trade Replay blocking fixes.
"""
import os
import sys
import gc
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.storage import SQLiteAgentStorage
from agent.trade_replay import TradeRecorder

TEST_DB = "agent/test_replay_integration.sqlite"

def main():
    # Clean up any leftover test db
    for f in [TEST_DB, TEST_DB + "-wal", TEST_DB + "-shm"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except PermissionError:
                print(f"[WARN] Could not remove {f}")

    try:
        # 1. Storage creation + schema init
        storage = SQLiteAgentStorage(TEST_DB)
        storage.init_schema()
        print("[PASS] Storage created, schema initialized")

        # 2. TradeRecorder instantiation
        recorder = TradeRecorder(storage)
        print("[PASS] TradeRecorder instantiated")

        # 3. Create trade
        trade_id = recorder.create_trade("BTC_USDT", "BUY", plan_id=42, llm_provider="groq")
        assert trade_id and trade_id.startswith("42_BTC_USDT_"), f"Bad trade_id: {trade_id}"
        print(f"[PASS] create_trade: {trade_id}")

        expected_events = 1  # trade_created

        # 4. Record agent tick (NEW method)
        recorder.record_agent_tick(trade_id, tick_number=1, survival_mode="NORMAL", treasury_usdt=100.0)
        expected_events += 1
        print("[PASS] record_agent_tick")

        # 5. Record market snapshot
        recorder.record_market_snapshot(trade_id, {
            "account": {"equity": 1000, "drawdown_pct": -2.5, "exposure_x": 1.5, "open_positions": 3},
            "treasury_usdt": 100.0,
            "survival_mode": "NORMAL",
        })
        expected_events += 1
        print("[PASS] record_market_snapshot")

        # 6. Record risk validation (NEW method)
        recorder.record_risk_validation(trade_id, passed=True, reason="position size within limits")
        expected_events += 1
        print("[PASS] record_risk_validation")

        # 7. Record execution request
        recorder.record_execution_request(trade_id, {
            "contract": "BTC_USDT", "side": "BUY", "size": 0.1,
            "order_type": "MARKET", "price": None, "reduce_only": False, "ioc": True,
        })
        expected_events += 1
        print("[PASS] record_execution_request")

        # 8. Record exchange response
        recorder.record_exchange_response(trade_id, {
            "exchange_order_id": "12345", "status": "FILLED",
            "filled_size": 0.1, "avg_fill_price": 50000.0,
            "fees": 0.5, "slippage": 0.02, "error": None,
        }, latency_ms=150.5)
        expected_events += 1
        print("[PASS] record_exchange_response")

        # 9. Record position close (NEW method)
        recorder.record_position_close(trade_id, exit_price=51000.0, exit_size=0.1, exit_reason="TP_HIT", realized_pnl=100.0)
        expected_events += 1
        print("[PASS] record_position_close")

        # 10. Record PnL
        recorder.record_pnl(trade_id, realized_pnl=100.0, unrealized_pnl=0.0)
        expected_events += 1
        print("[PASS] record_pnl")

        # 11. Record reflection
        recorder.record_reflection(trade_id, "Good trade, TP hit as expected")
        expected_events += 1
        print("[PASS] record_reflection")

        # 12. Record memory update (NEW method)
        recorder.record_memory_update(trade_id, memory_tables=["episodes", "patterns"], rules_updated=3, episodes_updated=1)
        expected_events += 1
        print("[PASS] record_memory_update")

        # 13. Complete trade
        recorder.complete_trade(trade_id, final_pnl=100.0, outcome="profit", notes="perfect trade")
        expected_events += 1  # trade_complete
        print("[PASS] complete_trade")

        # 14. Get timeline — verify correct ordering
        timeline = recorder.get_trade_timeline(trade_id)
        assert len(timeline) == expected_events, f"Expected {expected_events} events, got {len(timeline)}"
        for i, ev in enumerate(timeline):
            assert ev["event_index"] == i, f"Event {i} has wrong index {ev['event_index']}"
            print(f"  [{ev['event_index']}] {ev['event_type']} status='{ev['status']}' plan_id={ev['plan_id']}")
        print(f"[PASS] Timeline ordering correct: {len(timeline)} sequential events")

        # 15. Get all trades
        trades = recorder.get_all_trades()
        assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
        print(f"[PASS] get_all_trades: {len(trades)} trade(s)")

        # 16. Verify standard metadata fields exist
        ev0 = timeline[0]
        required_fields = ["trade_id", "event_type", "event_index", "timestamp", "status", "duration_ms", "provider", "confidence", "latency_ms", "plan_id", "event_data"]
        for field in required_fields:
            assert field in ev0, f"Missing field: {field}"
        print(f"[PASS] All {len(required_fields)} standard metadata fields present")

        print("\n=== ALL 16 TESTS PASSED ===")

    finally:
        # Force cleanup
        gc.collect()
        for f in [TEST_DB, TEST_DB + "-wal", TEST_DB + "-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except PermissionError:
                    pass

if __name__ == "__main__":
    main()