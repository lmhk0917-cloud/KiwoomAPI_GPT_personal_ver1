"""Kiwoom OpenAPI+ realtime/TR adapter.

This class is intentionally narrow: it receives Kiwoom events, converts them
to plain Python dictionaries, and passes them to the in-memory/SQLite stores.
Trading orders are not sent from this project yet.
"""

from datetime import datetime, timedelta
from PyQt5.QAxContainer import QAxWidget

from config import PRINT_REALTIME_TICKS, REALTIME_TICK_PRINT_EVERY
from kiwoom_context_mappings import (
    REALTIME_CONTEXT_TYPES,
    STOCK_PROGRAM_TRADING_REALTIME_FIDS,
    get_realtime_fid_list,
    get_tr_mapping,
)


class KiwoomClient:
    def __init__(self, tick_store, codes, market_context_store=None, require_existing_login=False):
        self.tick_store = tick_store
        self.codes = list(codes)
        self.market_context_store = market_context_store
        self.tr_context_requests = {}
        self.is_logged_in = False
        self.ever_logged_in = False
        self.last_login_error_code = None
        self.login_failure_count = 0
        self.require_existing_login = require_existing_login
        self.received_tick_count = 0

        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")

        self.ocx.OnEventConnect.connect(self.on_login)
        self.ocx.OnReceiveRealData.connect(self.on_receive_real_data)
        self.ocx.OnReceiveTrData.connect(self.on_receive_tr_data)

    def login(self):
        connect_state = self.ocx.dynamicCall("GetConnectState()")
        print("키움 연결 상태 확인:", connect_state)
        try:
            connect_state = int(connect_state)
        except (TypeError, ValueError):
            connect_state = 0

        if connect_state == 1:
            print("키움 이미 연결됨: 로그인 요청 생략")
            self.on_login(0)
            return

        if self.require_existing_login:
            print("키움 기존 연결 필요: 현재 미연결이므로 로그인 요청 생략")
            self.is_logged_in = False
            return

        print("키움 로그인 요청")
        result = self.ocx.dynamicCall("CommConnect()")
        print("키움 로그인 요청 반환값:", result)

    def on_login(self, err_code):
        if err_code == 0:
            self.is_logged_in = True
            self.ever_logged_in = True
            self.last_login_error_code = None
            print("키움 로그인 성공")
            self.register_realtime_codes()
        else:
            self.is_logged_in = False
            self.last_login_error_code = int(err_code)
            self.login_failure_count += 1
            print("키움 로그인 실패:", err_code)

    def register_realtime_codes(self):
        # 체결 데이터는 틱 저장과 1/3/5분봉 생성의 원천 데이터다.
        code_list = ";".join(self.codes)

        if not code_list:
            print("실시간 등록 종목 없음")
            return

        trade_fid_list = get_realtime_fid_list("stock_trade")
        orderbook_fid_list = get_realtime_fid_list("stock_orderbook")
        program_fid_list = get_realtime_fid_list("stock_program_trading")

        trade_result = self.ocx.dynamicCall(
            "SetRealReg(QString, QString, QString, QString)",
            REALTIME_CONTEXT_TYPES["stock_trade"]["screen_no"],
            code_list,
            trade_fid_list,
            "0"
        )
        orderbook_result = self.ocx.dynamicCall(
            "SetRealReg(QString, QString, QString, QString)",
            REALTIME_CONTEXT_TYPES["stock_orderbook"]["screen_no"],
            code_list,
            orderbook_fid_list,
            "1"
        )
        program_result = self.ocx.dynamicCall(
            "SetRealReg(QString, QString, QString, QString)",
            REALTIME_CONTEXT_TYPES["stock_program_trading"]["screen_no"],
            code_list,
            program_fid_list,
            "1"
        )

        print("체결 실시간 등록 결과:", trade_result)
        print("호가 실시간 등록 결과:", orderbook_result)
        print("프로그램매매 실시간 등록 결과:", program_result)
        print("등록 종목:", code_list)

    def clear_realtime_codes(self):
        """Remove realtime registrations from the screens used by this app."""
        for mapping_name in ("stock_trade", "stock_orderbook", "stock_program_trading"):
            screen_no = REALTIME_CONTEXT_TYPES[mapping_name]["screen_no"]
            self.ocx.dynamicCall(
                "SetRealRemove(QString, QString)",
                screen_no,
                "ALL"
            )

    def update_realtime_codes(self, codes):
        """Replace realtime watch codes while the program is running."""
        self.codes = list(codes)

        if not self.is_logged_in:
            return

        self.clear_realtime_codes()
        self.register_realtime_codes()

    def _make_orderbook_fid_list(self):
        # 예전 호출부와 호환되도록 남겨둔다. 실제 등록은 mapping 모듈을 사용한다.
        ask_price_fids = range(41, 51)
        bid_price_fids = range(51, 61)
        ask_qty_fids = range(61, 71)
        bid_qty_fids = range(71, 81)
        total_fids = [121, 125]
        fids = (
            list(ask_price_fids)
            + list(bid_price_fids)
            + list(ask_qty_fids)
            + list(bid_qty_fids)
            + total_fids
        )
        return ";".join(str(fid) for fid in fids)

    def get_real_data(self, code, fid):
        return self.ocx.dynamicCall(
            "GetCommRealData(QString, int)",
            code,
            fid
        ).strip()

    @staticmethod
    def parse_int(value):
        try:
            value = value.strip().replace("+", "").replace("-", "")
            if value == "":
                return None
            return abs(int(value))
        except:
            return None

    @staticmethod
    def parse_float(value):
        try:
            value = value.strip().replace("+", "").replace("%", "")
            if value == "":
                return None
            return float(value)
        except:
            return None

    def request_market_context_tr(
        self,
        rq_name,
        tr_code,
        inputs,
        output_fields,
        context_section,
        code=None,
        static_values=None,
        repeat_aggregation=None,
        screen_no="2000"
    ):
        # Kiwoom TR은 SetInputValue -> CommRqData -> OnReceiveTrData 순서로 동작한다.
        # 이 함수는 공매도/신용/선물옵션 같은 보조 컨텍스트를 같은 방식으로 저장한다.
        for input_name, input_value in inputs.items():
            self.ocx.dynamicCall(
                "SetInputValue(QString, QString)",
                input_name,
                str(input_value)
            )

        self.tr_context_requests[rq_name] = {
            "code": code,
            "context_section": context_section,
            "output_fields": output_fields,
            "static_values": static_values or {},
            "repeat_aggregation": repeat_aggregation or {},
        }

        return self.ocx.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            rq_name,
            tr_code,
            0,
            screen_no
        )

    def request_context_mapping(self, mapping_name, code=None, extra_inputs=None, screen_no="2000"):
        """Request a market-context TR mapping after it has been verified.

        TR mappings are disabled by default until the exact TR code and output
        item names are checked in KOA Studio. This guard prevents accidental
        live calls with guessed fields.
        """
        mapping = get_tr_mapping(mapping_name)

        if not mapping.get("enabled"):
            raise ValueError(
                "TR mapping '{}' is disabled. Verify tr_code/output_fields in KOA Studio first."
                .format(mapping_name)
            )

        tr_code = mapping.get("tr_code")
        output_fields = mapping.get("output_fields") or {}
        repeat_aggregation = mapping.get("repeat_aggregation") or {}

        if (
            not tr_code
            or (
                not any(item_name is not None for item_name in output_fields.values())
                and not repeat_aggregation
            )
        ):
            raise ValueError(
                "TR mapping '{}' is incomplete. Fill tr_code and output_fields first."
                .format(mapping_name)
            )

        inputs = {}
        for input_name, input_value in (mapping.get("inputs") or {}).items():
            inputs[input_name] = self._resolve_tr_input_value(input_value, code)

        if extra_inputs:
            inputs.update(extra_inputs)

        static_values = {}
        for key, value in (mapping.get("static_values") or {}).items():
            static_values[key] = self._resolve_tr_input_value(value, code)

        empty_inputs = [
            input_name
            for input_name, input_value in inputs.items()
            if input_value is None or input_value == ""
        ]
        if empty_inputs:
            raise ValueError(
                "TR mapping '{}' has empty inputs: {}"
                .format(mapping_name, ", ".join(empty_inputs))
            )

        rq_name = "{}_{}".format(mapping_name, code or "global")
        return self.request_market_context_tr(
            rq_name=rq_name,
            tr_code=tr_code,
            inputs=inputs,
            output_fields=output_fields,
            context_section=mapping["context_section"],
            code=code,
            static_values=static_values,
            repeat_aggregation=repeat_aggregation,
            screen_no=screen_no
        )

    def _resolve_tr_input_value(self, input_value, code):
        """Resolve mapping placeholders to runtime input values."""
        if input_value == "{code}":
            return code

        today = datetime.now()
        if input_value == "{today}":
            return today.strftime("%Y%m%d")
        if input_value == "{yesterday}":
            return (today - timedelta(days=1)).strftime("%Y%m%d")
        if input_value == "{lookback_start_7d}":
            return (today - timedelta(days=7)).strftime("%Y%m%d")
        if input_value == "{front_future_code}":
            return self._get_front_future_code()
        if input_value == "{front_option_month}":
            return self._get_front_option_month()

        return input_value

    def _get_front_future_code(self):
        """Return the front KOSPI200 futures code from Kiwoom."""
        code = self.ocx.dynamicCall("GetFutureCodeByIndex(int)", 0)
        return (code or "").strip()

    def _get_front_option_month(self):
        """Return the nearest listed KOSPI200 option expiration month."""
        raw_value = self.ocx.dynamicCall("GetMonthList()")
        months = [
            item.strip()
            for item in (raw_value or "").split(";")
            if item and item.strip()
        ]
        today_month = datetime.now().strftime("%Y%m")
        future_months = sorted([
            month for month in months
            if len(month) == 6 and month >= today_month
        ])

        if future_months:
            return future_months[0]

        return months[0] if months else ""

    def on_receive_tr_data(
        self,
        screen_no,
        rq_name,
        tr_code,
        record_name,
        prev_next,
        data_len,
        error_code,
        message,
        splm_msg
    ):
        request = self.tr_context_requests.pop(rq_name, None)

        if not request or not self.market_context_store:
            return

        values = {}
        for output_key, item_name in request["output_fields"].items():
            if item_name is None:
                continue
            raw_value = self.ocx.dynamicCall(
                "GetCommData(QString, QString, int, QString)",
                tr_code,
                record_name,
                0,
                item_name
            ).strip()
            values[output_key] = self._normalize_context_value(
                context_section=request["context_section"],
                output_key=output_key,
                value=self._parse_context_value(raw_value)
            )

        values.update(self._aggregate_repeat_context(
            tr_code=tr_code,
            record_name=record_name,
            context_section=request["context_section"],
            repeat_aggregation=request.get("repeat_aggregation") or {}
        ))

        if request.get("static_values"):
            values.update(request["static_values"])

        received_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        values["asof"] = received_at
        values["source"] = tr_code

        code = request.get("code")
        context_section = request["context_section"]

        if code:
            self.market_context_store.update_code_context(code, context_section, values)
            self.market_context_store.update_code_context(code, "data_quality", {
                "{}_last_received_at".format(context_section): received_at,
            })
        else:
            self.market_context_store.update_global_context(context_section, values)
            self.market_context_store.update_global_context("data_quality", {
                "{}_last_received_at".format(context_section): received_at,
            })

        derived_values = self._update_derived_context_values(context_section, code)
        if derived_values:
            values.update(derived_values)

        self._save_market_context_snapshot(
            scope="code" if code else "global",
            code=code,
            section=context_section,
            values=values,
            received_at=received_at,
            source=tr_code
        )

    def _aggregate_repeat_context(self, tr_code, record_name, context_section, repeat_aggregation):
        """Aggregate repeated TR rows into compact market-context fields."""
        if not repeat_aggregation:
            return {}

        count = self.ocx.dynamicCall(
            "GetRepeatCnt(QString, QString)",
            tr_code,
            record_name
        )
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 0

        values = {}
        row_count_key = repeat_aggregation.get("row_count_key")
        if row_count_key:
            values[row_count_key] = count

        for output_key, item_name in (repeat_aggregation.get("sum_fields") or {}).items():
            total = 0.0
            seen = False
            for index in range(count):
                value = self._read_comm_data_value(
                    tr_code=tr_code,
                    record_name=record_name,
                    index=index,
                    item_name=item_name,
                    context_section=context_section,
                    output_key=output_key
                )
                numeric = self._to_float(value)
                if numeric is None:
                    continue
                total += numeric
                seen = True
            values[output_key] = int(total) if seen and total.is_integer() else (round(total, 4) if seen else None)

        for output_key, item_name in (repeat_aggregation.get("avg_fields") or {}).items():
            total = 0.0
            seen_count = 0
            for index in range(count):
                value = self._read_comm_data_value(
                    tr_code=tr_code,
                    record_name=record_name,
                    index=index,
                    item_name=item_name,
                    context_section=context_section,
                    output_key=output_key
                )
                numeric = self._to_float(value)
                if numeric is None:
                    continue
                total += numeric
                seen_count += 1
            values[output_key] = round(total / seen_count, 4) if seen_count else None

        return values

    def _read_comm_data_value(self, tr_code, record_name, index, item_name, context_section, output_key):
        raw_value = self.ocx.dynamicCall(
            "GetCommData(QString, QString, int, QString)",
            tr_code,
            record_name,
            index,
            item_name
        ).strip()
        return self._normalize_context_value(
            context_section=context_section,
            output_key=output_key,
            value=self._parse_context_value(raw_value)
        )

    def _update_derived_context_values(self, context_section, code):
        """Derive ratios after multiple related context TRs have arrived."""
        if context_section == "market_investor_flow" and not code:
            market_flow = self.market_context_store.runtime_global_context.get(
                "market_investor_flow",
                {}
            )
            derived_values = {
                "combined_foreign_net_value": self._sum_optional(
                    market_flow.get("kospi_foreign_net_value"),
                    market_flow.get("kosdaq_foreign_net_value")
                ),
                "combined_institution_net_value": self._sum_optional(
                    market_flow.get("kospi_institution_net_value"),
                    market_flow.get("kosdaq_institution_net_value")
                ),
                "combined_individual_net_value": self._sum_optional(
                    market_flow.get("kospi_individual_net_value"),
                    market_flow.get("kosdaq_individual_net_value")
                ),
                "reliability": "sector_sum_proxy_pending_live_unit_validation",
            }
            self.market_context_store.update_global_context("market_investor_flow", derived_values)
            return derived_values

        if context_section != "derivatives" or code:
            return {}

        derivatives = self.market_context_store.runtime_global_context.get("derivatives", {})
        call_volume = self._to_float(derivatives.get("call_option_volume"))
        put_volume = self._to_float(derivatives.get("put_option_volume"))
        call_open_interest = self._to_float(derivatives.get("call_option_open_interest"))
        put_open_interest = self._to_float(derivatives.get("put_option_open_interest"))
        call_iv = self._to_float(derivatives.get("call_implied_volatility_avg"))
        put_iv = self._to_float(derivatives.get("put_implied_volatility_avg"))

        derived_values = {}
        if call_volume not in (None, 0) and put_volume is not None:
            derived_values["put_call_ratio"] = round(put_volume / call_volume, 4)
        if call_open_interest not in (None, 0) and put_open_interest is not None:
            derived_values["put_call_open_interest_ratio"] = round(put_open_interest / call_open_interest, 4)
        iv_values = [value for value in (call_iv, put_iv) if value is not None]
        if iv_values:
            derived_values["implied_volatility"] = round(sum(iv_values) / len(iv_values), 4)

        if derived_values:
            self.market_context_store.update_global_context("derivatives", derived_values)

        return derived_values

    @classmethod
    def _sum_optional(cls, *values):
        """Return a numeric sum when at least one source value is present."""
        numeric_values = [cls._to_float(value) for value in values]
        numeric_values = [value for value in numeric_values if value is not None]

        if not numeric_values:
            return None

        total = sum(numeric_values)
        return int(total) if float(total).is_integer() else round(total, 4)

    def _save_market_context_snapshot(self, scope, code, section, values, received_at, source):
        """Persist non-realtime market context when SQLite storage is available."""
        if not self.tick_store:
            return

        save_snapshot = getattr(self.tick_store, "save_market_context_snapshot", None)
        if not save_snapshot:
            return

        save_snapshot(
            scope=scope,
            code=code,
            section=section,
            payload=values,
            collected_at=received_at,
            source=source
        )

    @staticmethod
    def _parse_context_value(value):
        if value is None:
            return None

        cleaned = value.strip().replace(",", "").replace("+", "")

        if cleaned == "":
            return None

        try:
            if "." in cleaned:
                return float(cleaned)
            return int(cleaned)
        except ValueError:
            return cleaned

    @staticmethod
    def _to_float(value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_context_value(context_section, output_key, value):
        """Normalize known Kiwoom field unit quirks after numeric parsing."""
        if value is None:
            return None

        if context_section == "market_program_trading" and output_key == "kospi200":
            try:
                if abs(float(value)) > 10000:
                    return round(float(value) / 100.0, 2)
            except (TypeError, ValueError):
                return value

        return value

    def on_receive_real_data(self, code, real_type, real_data):
        if self._is_real_type(real_type, "주식호가잔량"):
            self._handle_orderbook_data(code)
            return

        if self._is_real_type(real_type, "종목프로그램매매"):
            self._handle_program_trading_data(code)
            return

        if not self._is_real_type(real_type, "주식체결"):
            return

        # 주식체결 FID 값은 부호가 붙어 올 수 있으므로 저장 전 숫자로 정규화한다.
        tick = {
            "code": code,
            "trade_time": self.get_real_data(code, 20),
            "price": self.parse_int(self.get_real_data(code, 10)),
            "change_rate": self.parse_float(self.get_real_data(code, 12)),
            "acc_volume": self.parse_int(self.get_real_data(code, 13)),
            "tick_volume": self.parse_int(self.get_real_data(code, 15)),
            "open_price": self.parse_int(self.get_real_data(code, 16)),
            "high_price": self.parse_int(self.get_real_data(code, 17)),
            "low_price": self.parse_int(self.get_real_data(code, 18)),
            "strength": self.parse_float(self.get_real_data(code, 228)),
            "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        }

        self.tick_store.add_tick(tick)
        self.received_tick_count += 1
        if self.market_context_store:
            self.market_context_store.update_code_context(code, "data_quality", {
                "tick_last_received_at": tick["received_at"],
            })

        if self._should_print_tick():
            print(
                f"[{tick['received_at']}] "
                f"{code} 현재가={tick['price']} "
                f"등락률={tick['change_rate']} "
                f"거래량={tick['tick_volume']}"
            )

    @staticmethod
    def _is_real_type(real_type, expected):
        """Match Kiwoom real_type across normal Korean and mojibake variants.

        Some Windows/console combinations surface Kiwoom COM event names as
        CP949 bytes decoded through a Latin code page, e.g. ``주식체결`` appears
        as ``ÁÖ½ÄÃ¼°á``. Accepting both forms prevents valid realtime ticks from
        being filtered out before persistence.
        """
        if real_type == expected:
            return True

        try:
            if real_type.encode("latin1").decode("cp949") == expected:
                return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

        try:
            if expected.encode("cp949").decode("latin1") == real_type:
                return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

        return False

    def _should_print_tick(self):
        if not PRINT_REALTIME_TICKS:
            return False

        if REALTIME_TICK_PRINT_EVERY <= 1:
            return True

        return self.received_tick_count % REALTIME_TICK_PRINT_EVERY == 0

    def _handle_orderbook_data(self, code):
        if not self.market_context_store:
            return

        ask_levels = []
        bid_levels = []

        for level in range(1, 11):
            ask_price = self.parse_int(self.get_real_data(code, 40 + level))
            bid_price = self.parse_int(self.get_real_data(code, 50 + level))
            ask_qty = self.parse_int(self.get_real_data(code, 60 + level))
            bid_qty = self.parse_int(self.get_real_data(code, 70 + level))

            ask_levels.append({
                "level": level,
                "price": ask_price,
                "qty": ask_qty,
            })
            bid_levels.append({
                "level": level,
                "price": bid_price,
                "qty": bid_qty,
            })

        best_ask = ask_levels[0]["price"] if ask_levels else None
        best_bid = bid_levels[0]["price"] if bid_levels else None
        total_ask_qty = self.parse_int(self.get_real_data(code, 121))
        total_bid_qty = self.parse_int(self.get_real_data(code, 125))

        spread = None
        spread_pct = None
        if best_ask is not None and best_bid is not None:
            spread = best_ask - best_bid
            mid_price = (best_ask + best_bid) / 2.0
            if mid_price:
                spread_pct = round(spread / mid_price * 100, 4)

        bid_ask_imbalance = None
        if total_bid_qty is not None and total_ask_qty is not None:
            total_qty = total_bid_qty + total_ask_qty
            if total_qty:
                bid_ask_imbalance = round((total_bid_qty - total_ask_qty) / total_qty, 4)

        orderbook = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "spread_pct": spread_pct,
            "total_bid_qty": total_bid_qty,
            "total_ask_qty": total_ask_qty,
            "bid_ask_imbalance": bid_ask_imbalance,
            "bid_levels": bid_levels,
            "ask_levels": ask_levels,
        }
        self.market_context_store.update_orderbook(code, orderbook)
        self.market_context_store.update_code_context(code, "data_quality", {
            "orderbook_last_received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        })

    def _handle_program_trading_data(self, code):
        if not self.market_context_store:
            return

        values = {}
        for fid, output_key in STOCK_PROGRAM_TRADING_REALTIME_FIDS.items():
            raw_value = self.get_real_data(code, fid)
            values[output_key] = self._parse_context_value(raw_value)

        self.market_context_store.update_program_trading(code, {
            "program_net_value": values.get("program_net_value"),
            "program_buy_value": values.get("program_buy_value"),
            "program_sell_value": values.get("program_sell_value"),
            "raw_realtime": values,
        })
        self.market_context_store.update_code_context(code, "data_quality", {
            "program_trading_last_received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        })
