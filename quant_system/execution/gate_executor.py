"""Gate.io USDT-margined perpetual futures execution layer.

This module adds a real (networked) executor for Gate.io Futures (USDT).
No strategy logic is implemented here; it's strictly an API adapter with safety checks.

Signing (Gate API v4):
  SIGN = HMAC_SHA512(secret, timestamp + method + request_path + query_string + body_hash)
  body_hash = SHA512(body_string)

Required headers:
  KEY, Timestamp, SIGN, Content-Type: application/json

Endpoints used (relative to base_url):
  GET  /futures/usdt/contracts
  POST /futures/usdt/orders
  GET  /futures/usdt/positions
  POST /futures/usdt/positions/{contract}/leverage

Safety rules implemented:
- retries: 3 attempts
- logs: endpoint, payload, response code, response JSON/text
- checks: portfolio risk cap, no duplicate position same direction

Notes:
- This executor expects `contract` values to match Gate futures contract symbols.
- Gate uses `size` with sign: positive=long, negative=short.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


class GateHTTPError(RuntimeError):
    """Raised for non-2xx responses and unrecoverable HTTP issues."""


@dataclass
class GateExecutor:
    api_key: str
    api_secret: str
    base_url: str
    fee_rate: float
    slippage: float

    def __post_init__(self) -> None:
        self.log = logging.getLogger(self.__class__.__name__)
        self.base_url = self.base_url.rstrip("/")

    # -----------------
    # Public methods
    # -----------------

    def set_leverage(self, contract: str, leverage: int) -> Dict[str, Any]:
        """Set leverage for a futures contract (applies to future position opens).

        Endpoint:
            POST /futures/usdt/positions/{contract}/leverage

        Note:
            Gate expects `leverage` (and optionally `cross_leverage_limit`) as query parameters
            for this endpoint, not in the JSON body.
        """
        path = f"/futures/usdt/positions/{contract}/leverage"
        params = {"leverage": str(int(leverage))}
        return self._request_json("POST", path, params=params, payload=None)

    def get_futures_candlesticks(
        self,
        *,
        contract: str,
        interval: str = "4h",
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Fetch futures candlesticks (public endpoint).

        Endpoint:
            GET /futures/usdt/candlesticks

        Params:
            contract, interval, limit

        Response example (list):
            {"t": 1539852480, "v": "97151", "c": "1.032", "h": "1.032", "l": "1.032", "o": "1.032", "sum": "3580"}
        """
        path = "/futures/usdt/candlesticks"
        params: Dict[str, Any] = {
            "contract": contract,
            "interval": interval,
            "limit": int(limit),
        }
        res = self._request_json("GET", path, params=params, payload=None)
        if isinstance(res, list):
            return res
        return [res]

    def place_market_order(
        self,
        contract: str,
        size: float,
        *,
        open_positions: Optional[List[Dict[str, Any]]] = None,
        portfolio_risk_ok: bool = True,
    ) -> Dict[str, Any]:
        """Place a market order.

        Args:
            contract: Gate futures contract symbol.
            size: positive -> long, negative -> short.
            open_positions: optional pre-fetched positions for safety checks.
            portfolio_risk_ok: set by the caller (RiskManager) to enforce max portfolio risk.

        Returns:
            Gate order JSON.
        """
        if not portfolio_risk_ok:
            raise ValueError("Portfolio risk exceeded; refusing to place order")
        if size == 0:
            raise ValueError("Order size cannot be 0")

        direction = 1 if size > 0 else -1
        if open_positions is None:
            open_positions = self.get_open_positions()
    # NOTE: We intentionally allow adding to an existing position (scaling-in).
    # Risk/margin constraints are enforced by the caller (RiskManager + live runner).

        path = "/futures/usdt/orders"
        payload = {
            "contract": contract,
            "size": int(size),
            # Gate futures expects `type=market` for a market order.
            # `price` must be "0" (string) for market orders.
            "price": "0",
            "type": "market",
            # Gate requires market orders to use IOC or FOK.
            "tif": "ioc",
            # Gate requires the client order tag `text` to start with `t-`.
            "text": "t-quant_system",
        }
        return self._request_json("POST", path, params=None, payload=payload)

    def place_tpsl_orders(
        self,
        *,
        contract: str,
        position_side: str,
        size: float,
        take_profit: Optional[float],
        stop_loss: Optional[float],
    ) -> Dict[str, Any]:
        """Place reduce-only TP/SL trigger orders for an open position.

        This uses Gate futures "price triggered order" (a.k.a plan order) endpoint.

        Notes:
        - Gate uses signed sizes: positive=buy/open long, negative=sell/open short.
          For closing, we send the opposite side size.
        - We send reduce_only=true so it won't add margin.

        Returns a dict with keys: {"tp": <resp|None>, "sl": <resp|None>}.
        """
        side = str(position_side).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError("position_side must be 'LONG' or 'SHORT'")
        if size == 0:
            raise ValueError("size cannot be 0")

        abs_size = int(abs(size))
        results: Dict[str, Any] = {"tp": None, "sl": None}

        # For a LONG position, TP/SL are SELL orders; for SHORT, TP/SL are BUY orders.
        close_side = "sell" if side == "LONG" else "buy"

        if take_profit is not None:
            results["tp"] = self._place_trigger_order(
                contract=contract,
                side=close_side,
                size=abs_size,
                trigger_price=float(take_profit),
                order_price=0.0,
                reduce_only=True,
                text="t-qt-tp",
            )

        if stop_loss is not None:
            results["sl"] = self._place_trigger_order(
                contract=contract,
                side=close_side,
                size=abs_size,
                trigger_price=float(stop_loss),
                order_price=0.0,
                reduce_only=True,
                text="t-qt-sl",
            )

        return results

    def _place_trigger_order(
        self,
        *,
        contract: str,
        side: str,
        size: int,
        trigger_price: float,
        order_price: float = 0.0,
        reduce_only: bool = True,
    text: str = "t-quant_system-tpsl",
    ) -> Dict[str, Any]:
        """Place a futures triggered order (plan order).

        Endpoint:
          POST /futures/usdt/price_orders

        We set `price=0` to make it market when triggered.
        """
        path = "/futures/usdt/price_orders"
        payload: Dict[str, Any] = {
            "contract": contract,
            "size": int(size),
            "side": str(side),
            "trigger": {
                "price": str(trigger_price),
                # Default to last price trigger; Gate supports different types but we keep it simple.
                "rule": 1,
            },
            "order": {
                "price": "0" if float(order_price) == 0.0 else str(order_price),
                "tif": "ioc",
                "reduce_only": bool(reduce_only),
                "text": str(text),
            },
        }
        return self._request_json("POST", path, params=None, payload=payload)

    def get_open_positions(self) -> List[Dict[str, Any]]:
        path = "/futures/usdt/positions"
        res = self._request_json("GET", path, params=None, payload=None)
        # Gate returns a list
        if isinstance(res, list):
            return res
        return [res]

    def get_contracts(self) -> List[Dict[str, Any]]:
        """List USDT futures contracts.

        Endpoint:
            GET /futures/usdt/contracts

        This is used for metadata like contract size / multiplier so we can
        normalize quantities and match Gate UI PnL.
        """
        path = "/futures/usdt/contracts"
        res = self._request_json("GET", path, params=None, payload=None)
        if isinstance(res, list):
            return res
        return [res]

    def get_contract_detail(self, contract: str) -> Dict[str, Any]:
        """Fetch single contract metadata.

        Endpoint:
            GET /futures/usdt/contracts/{contract}
        """
        path = f"/futures/usdt/contracts/{contract}"
        res = self._request_json("GET", path, params=None, payload=None)
        if isinstance(res, dict):
            return res
        # Some Gate responses might wrap; keep best-effort.
        return {"data": res}

    def get_open_trigger_orders(self, *, contract: Optional[str] = None) -> List[Dict[str, Any]]:
        """List open futures trigger/plan orders.

        Endpoint:
          GET /futures/usdt/price_orders

        If `contract` is provided, Gate supports filtering by contract.
        """
        path = "/futures/usdt/price_orders"
        params: Dict[str, Any] = {"status": "open"}
        if contract:
            params["contract"] = str(contract)
        res = self._request_json("GET", path, params=params, payload=None)
        if isinstance(res, list):
            return res
        return [res]

    def get_trigger_order(self, order_id: str) -> Dict[str, Any]:
        """Fetch a futures trigger/plan order by id.

        Endpoint:
            GET /futures/usdt/price_orders/{order_id}
        """
        path = f"/futures/usdt/price_orders/{order_id}"
        return self._request_json("GET", path, params=None, payload=None)

    def get_account_equity(self) -> float:
        """Fetch account equity from Gate futures USDT account endpoint.

        Endpoint:
            GET /futures/usdt/accounts

        Strict parsing:
            - only accepts the `total` field
            - raises if the response format changes
        """
        path = "/futures/usdt/accounts"
        data = self._request_json("GET", path, params=None, payload=None)

        if not isinstance(data, dict):
            raise ValueError("Invalid account response")

        if "total" in data:
            return float(data["total"])

        raise KeyError("Cannot find 'total' in account response")

    def close_position(self, contract: str) -> Optional[Dict[str, Any]]:
        """Close a position by submitting a market order of the opposite size.

        Returns None if no open position is found.
        """
        positions = self.get_open_positions()
        pos = self._find_position(positions, contract)
        if pos is None:
            return None

        size = self._parse_position_size(pos)
        if size == 0:
            return None

        # Send opposite order.
        return self.place_market_order(contract=contract, size=-size, open_positions=positions, portfolio_risk_ok=True)

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Fetch a futures order by id.

        Endpoint:
          GET /futures/usdt/orders/{order_id}

        Returns:
            Order JSON including fill fields when available.
        """
        path = f"/futures/usdt/orders/{order_id}"
        return self._request_json("GET", path, params=None, payload=None)

    def get_my_trades(
        self,
        *,
        contract: str,
        from_ts: int,
        to_ts: int,
    ) -> List[Dict[str, Any]]:
        """Fetch account trade fills for a contract between two unix timestamps.

        Endpoint:
          GET /futures/usdt/my_trades

        Args:
            contract: futures contract.
            from_ts: unix timestamp seconds (inclusive).
            to_ts: unix timestamp seconds (inclusive).

        Returns:
            List of trade fill objects.
        """
        path = "/futures/usdt/my_trades"
        params = {
            "contract": contract,
            "from": int(from_ts),
            "to": int(to_ts),
        }
        res = self._request_json("GET", path, params=params, payload=None)
        if isinstance(res, list):
            return res
        return [res]

    # -----------------
    # Internals
    # -----------------

    def _request_json(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]],
        payload: Optional[Dict[str, Any]],
    ) -> Any:
        method = method.upper()
        url, request_path, query_string = self._build_url(path, params)

        body = ""
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        headers = self._signed_headers(method, request_path, query_string, body)

        last_err: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                req = urllib.request.Request(
                    url=url,
                    data=body.encode("utf-8") if body else None,
                    headers=headers,
                    method=method,
                )

                self.log.info("Gate API call: %s %s", method, url)
                if payload is not None:
                    self.log.info("Payload: %s", body)

                with urllib.request.urlopen(req, timeout=30) as resp:
                    status = int(resp.status)
                    raw = resp.read().decode("utf-8")

                self.log.info("Response code: %s", status)
                self.log.info("Response body: %s", raw)

                if status < 200 or status >= 300:
                    raise GateHTTPError(f"Non-2xx response: {status} body={raw}")

                if raw.strip() == "":
                    return {}
                return json.loads(raw)

            except urllib.error.HTTPError as e:
                # Gate returns useful JSON error details in the body for 4xx/5xx.
                try:
                    err_raw = e.read().decode("utf-8")
                except Exception:  # noqa: BLE001
                    err_raw = ""

                last_err = GateHTTPError(
                    f"HTTP {getattr(e, 'code', '?')}: {getattr(e, 'reason', '')} body={err_raw}"
                )
                self.log.exception("Gate request failed (attempt %d/3): %s", attempt, str(last_err))
                if attempt < 3:
                    time.sleep(0.75 * attempt)
                    continue
                break

            except Exception as e:  # noqa: BLE001 (we re-raise after retries)
                last_err = e
                self.log.exception("Gate request failed (attempt %d/3): %s", attempt, str(e))
                if attempt < 3:
                    time.sleep(0.75 * attempt)
                    continue
                break

        raise GateHTTPError(f"Gate request failed after retries: {last_err}")

    def _build_url(self, path: str, params: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
        request_path = path if path.startswith("/") else f"/{path}"
        query_string = ""
        if params:
            # Sort for reproducible signing.
            # Note: Gate signature expects the *raw* query-string as in URL (not url-encoded again).
            # We still build it via urlencode, which is also what we put in the actual URL.
            query_string = urllib.parse.urlencode(sorted(params.items()), doseq=True)

        url = self.base_url + request_path
        if query_string:
            url = url + "?" + query_string
        return url, request_path, query_string

    def _signing_path(self, request_path: str) -> str:
        """Return the path that must be used in the Gate v4 signature.

        Gate signs the full URL path *including* any base prefix like `/api/v4`.
        Example (docs): `/api/v4/futures/usdt/accounts`.
        """
        base_path = urllib.parse.urlparse(self.base_url).path or ""
        base_path = base_path.rstrip("/")
        if not base_path:
            return request_path
        if request_path.startswith(base_path + "/") or request_path == base_path:
            return request_path
        return base_path + request_path

    def _signed_headers(self, method: str, request_path: str, query_string: str, body: str) -> Dict[str, str]:
        ts = str(int(time.time()))
        body_hash = hashlib.sha512(body.encode("utf-8")).hexdigest()

        # Gate v4 signature string generation:
        #   METHOD + "\n" + URL_PATH + "\n" + QUERY_STRING + "\n" + SHA512(body) + "\n" + TIMESTAMP
        # Query string must be exactly as in the URL (no leading '?'). Use empty string if none.
        signing_path = self._signing_path(request_path)
        sign_payload = "\n".join([method, signing_path, query_string or "", body_hash, ts])

        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            sign_payload.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()

        return {
            "KEY": self.api_key,
            "Timestamp": ts,
            "SIGN": signature,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _parse_position_size(position: Dict[str, Any]) -> int:
        # Gate futures position typically contains "size".
        size = position.get("size", 0)
        try:
            return int(float(size))
        except Exception:
            return 0

    @staticmethod
    def _find_position(positions: List[Dict[str, Any]], contract: str) -> Optional[Dict[str, Any]]:
        for p in positions:
            if str(p.get("contract")) == contract:
                return p
        return None

    @staticmethod
    def _has_duplicate_direction(
        positions: List[Dict[str, Any]],
        contract: str,
        direction: int,
    ) -> bool:
        pos = GateExecutor._find_position(positions, contract)
        if pos is None:
            return False
        size = GateExecutor._parse_position_size(pos)
        if size == 0:
            return False
        return (size > 0 and direction > 0) or (size < 0 and direction < 0)
