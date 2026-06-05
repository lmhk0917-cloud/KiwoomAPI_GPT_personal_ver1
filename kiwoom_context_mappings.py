"""Kiwoom market-context collection mappings.

This module separates two kinds of market-context data:

1. Realtime FID mappings that are available from Kiwoom real-time feeds.
2. TR mappings that still need KOA Studio verification before live use.

The important rule is conservative: do not pretend an unverified TR code is
production-ready. The realtime orderbook mapping is already wired in
``kiwoom_client.py``. Other mappings are kept here so they can be filled in
after checking the exact TR code, input names, and output item names in KOA
Studio.
"""


STOCK_TRADE_FIDS = {
    10: "current_price",
    12: "change_rate",
    13: "acc_volume",
    15: "tick_volume",
    16: "open_price",
    17: "high_price",
    18: "low_price",
    20: "trade_time",
    228: "strength",
}


STOCK_ORDERBOOK_FIDS = {
    "ask_price": list(range(41, 51)),
    "bid_price": list(range(51, 61)),
    "ask_qty": list(range(61, 71)),
    "bid_qty": list(range(71, 81)),
    "total_ask_qty": 121,
    "total_bid_qty": 125,
}


# The installed OpenAPI realtime definition exposes this real type. The field
# names below are intentionally broad because broker-side documentation can
# label these fields slightly differently across OpenAPI versions.
STOCK_PROGRAM_TRADING_REALTIME_FIDS = {
    20: "trade_time",
    10: "current_price",
    25: "direction",
    11: "price_change",
    12: "change_rate",
    13: "acc_volume",
    202: "program_net_qty",
    204: "program_net_value",
    206: "program_buy_qty",
    208: "program_buy_value",
    210: "program_sell_qty",
    211: "program_sell_value",
    212: "program_net_buy_ratio",
    213: "program_buy_ratio",
    214: "program_sell_ratio",
    215: "program_buy_avg_price",
    216: "program_sell_avg_price",
}


REALTIME_CONTEXT_TYPES = {
    "stock_trade": {
        "real_type": "주식체결",
        "screen_no": "1000",
        "fids": STOCK_TRADE_FIDS,
        "implemented": True,
    },
    "stock_orderbook": {
        "real_type": "주식호가잔량",
        "screen_no": "1001",
        "fids": STOCK_ORDERBOOK_FIDS,
        "implemented": True,
    },
    "stock_program_trading": {
        "real_type": "종목프로그램매매",
        "screen_no": "1002",
        "fids": STOCK_PROGRAM_TRADING_REALTIME_FIDS,
        "implemented": True,
        "note": "Parser stores core values plus raw_realtime; verify field meanings during live test.",
    },
}


TR_CONTEXT_MAPPINGS = {
    "short_selling": {
        "enabled": True,
        "context_section": "short_selling",
        "tr_code": "OPT10014",
        "inputs": {
            "종목코드": "{code}",
            "시간구분": "1",
            "시작일자": "{lookback_start_7d}",
            "종료일자": "{today}",
        },
        "output_fields": {
            "date": "일자",
            "close": "종가",
            "short_sale_volume": "공매도량",
            "short_sale_value": "공매도거래대금",
            "short_sale_ratio_pct": "매매비중",
            "short_sale_avg_price": "공매도평균가",
            "short_balance_qty": None,
            "short_balance_ratio_pct": None,
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt10014.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "공매도 잔고는 이 TR 출력에 없어 None으로 유지한다.",
    },
    "stock_loan_trend": {
        "enabled": True,
        "context_section": "short_selling",
        "tr_code": "OPT10068",
        "inputs": {
            "시작일자": "{lookback_start_7d}",
            "종료일자": "{today}",
            "전체구분": "1",
            "종목코드": "{code}",
        },
        "output_fields": {
            "stock_loan_date": "일자",
            "stock_loan_execution_qty": "대차거래체결주수",
            "stock_loan_repayment_qty": "대차거래상환주수",
            "stock_loan_change_qty": "대차거래증감",
            "stock_loan_balance_qty": "잔고주수",
            "stock_loan_balance_value": "잔고금액",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt10068.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "공매도 잔고 직접값이 아니라 대차잔고 추이다. 공매도 압력 보조지표로만 사용한다.",
    },
    "credit": {
        "enabled": True,
        "context_section": "credit",
        "tr_code": "OPT10013",
        "inputs": {
            "종목코드": "{code}",
            "일자": "{today}",
            "조회구분": "1",
        },
        "output_fields": {
            "date": "일자",
            "credit_new_qty": "신규",
            "credit_repay_qty": "상환",
            "credit_balance_qty": "잔고",
            "credit_amount": "금액",
            "credit_balance_change_qty": "대비",
            "credit_supply_ratio_pct": "공여율",
            "credit_balance_ratio_pct": "잔고율",
            "loan_balance_qty": None,
            "loan_balance_change_qty": None,
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt10013.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "기본은 조회구분=1 융자. 대주는 별도 매핑이 필요하면 추가한다.",
    },
    "investor_flow": {
        "enabled": True,
        "context_section": "investor_flow",
        "tr_code": "OPT10059",
        "inputs": {
            "일자": "{today}",
            "종목코드": "{code}",
            "금액수량구분": "1",
            "매매구분": "0",
            "단위구분": "1",
        },
        "output_fields": {
            "date": "일자",
            "individual_net_value": "개인투자자",
            "foreign_net_value": "외국인투자자",
            "institution_net_value": "기관계",
            "financial_investment_net_value": "금융투자",
            "insurance_net_value": "보험",
            "trust_net_value": "투신",
            "bank_net_value": "은행",
            "pension_net_value": "연기금등",
            "private_fund_net_value": "사모펀드",
            "other_corporation_net_value": "기타법인",
            "domestic_foreign_net_value": "내외국인",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt10059.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "금액수량구분=1, 매매구분=0 기준 순매수 금액.",
    },
    "market_investor_flow_kospi": {
        "enabled": True,
        "context_section": "market_investor_flow",
        "tr_code": "OPT10051",
        "inputs": {
            "시장구분": "0",
            "금액수량구분": "0",
            "기준일자": "{today}",
            "거래소구분": "1",
        },
        "output_fields": {},
        "repeat_aggregation": {
            "row_count_key": "kospi_sector_count",
            "sum_fields": {
                "kospi_individual_net_value": "개인순매수",
                "kospi_foreign_net_value": "외국인순매수",
                "kospi_institution_net_value": "기관계순매수",
            },
        },
        "static_values": {
            "kospi_source_note": "OPT10051 sector-sum proxy; verify units during the next live session.",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt10051.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "KOSPI sector-level investor net values aggregated as a market-flow proxy.",
    },
    "market_investor_flow_kosdaq": {
        "enabled": True,
        "context_section": "market_investor_flow",
        "tr_code": "OPT10051",
        "inputs": {
            "시장구분": "1",
            "금액수량구분": "0",
            "기준일자": "{today}",
            "거래소구분": "1",
        },
        "output_fields": {},
        "repeat_aggregation": {
            "row_count_key": "kosdaq_sector_count",
            "sum_fields": {
                "kosdaq_individual_net_value": "개인순매수",
                "kosdaq_foreign_net_value": "외국인순매수",
                "kosdaq_institution_net_value": "기관계순매수",
            },
        },
        "static_values": {
            "kosdaq_source_note": "OPT10051 sector-sum proxy; verify units during the next live session.",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt10051.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "KOSDAQ sector-level investor net values aggregated as a market-flow proxy.",
    },
    "market_index_kospi": {
        "enabled": True,
        "context_section": "market_indices",
        "tr_code": "OPT20001",
        "inputs": {
            "시장구분": "0",
            "업종코드": "001",
        },
        "output_fields": {
            "kospi": "현재가",
            "kospi_change_pct": "등락률",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt20001.enc / C:\\OpenAPI\\koatrinputlegend.ini",
    },
    "market_index_kosdaq": {
        "enabled": True,
        "context_section": "market_indices",
        "tr_code": "OPT20001",
        "inputs": {
            "시장구분": "1",
            "업종코드": "101",
        },
        "output_fields": {
            "kosdaq": "현재가",
            "kosdaq_change_pct": "등락률",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt20001.enc / C:\\OpenAPI\\koatrinputlegend.ini",
    },
    "market_index_kospi200": {
        "enabled": True,
        "context_section": "market_indices",
        "tr_code": "OPT20001",
        "inputs": {
            "시장구분": "2",
            "업종코드": "201",
        },
        "output_fields": {
            "kospi200": "현재가",
            "kospi200_change_pct": "등락률",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt20001.enc / C:\\OpenAPI\\koatrinputlegend.ini",
    },
    "fx_usd_krw": {
        "enabled": False,
        "context_section": "market_indices",
        "tr_code": None,
        "inputs": {
            "통화코드": "USD",
        },
        "output_fields": {
            "usd_krw": "현재환율",
            "usd_krw_change_pct": "등락률",
        },
        "static_values": {
            "currency_pair": "USD/KRW",
        },
        "needs_koa_studio_verification": True,
        "source": "C:\\OpenAPI\\KOAStudioSA.exe lists overseas FX screens 2410/2411 and currency-rate fields 8043/8045/8988, but no verified OPT/OPW TR mapping was found in local .enc files.",
        "note": "Enable only after KOA Studio confirms the exact TR code, input names, and output item names for USD/KRW.",
    },
    "market_program_trading": {
        "enabled": True,
        "context_section": "market_program_trading",
        "tr_code": "OPT90005",
        "inputs": {
            "날짜": "{today}",
            "시간구분": "1",
            "금액수량구분": "1",
            "시장구분": "P00101",
            "분틱구분": "1",
            "거래소구분": "1",
        },
        "output_fields": {
            "time": "체결시간",
            "date": "일자",
            "arbitrage_sell_value": "차익거래매도",
            "arbitrage_buy_value": "차익거래매수",
            "arbitrage_net_value": "차익거래순매수",
            "non_arbitrage_sell_value": "비차익거래매도",
            "non_arbitrage_buy_value": "비차익거래매수",
            "non_arbitrage_net_value": "비차익거래순매수",
            "total_sell_value": "전체매도",
            "total_buy_value": "전체매수",
            "total_net_value": "전체순매수",
            "kospi200": "KOSPI200",
            "basis": "BASIS",
        },
        "static_values": {
            "market": "KOSPI",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt90005.enc / C:\\OpenAPI\\koatrinputlegend.ini",
    },
    "derivatives": {
        "enabled": True,
        "context_section": "derivatives",
        "tr_code": "OPT50001",
        "inputs": {
            "종목코드": "{front_future_code}",
        },
        "output_fields": {
            "kospi200_futures_price": "현재가",
            "kospi200_futures_change_pct": "등락율",
            "basis": "시장베이시스",
            "theoretical_basis": "이론베이시스",
            "futures_volume": "거래량",
            "open_interest": "미결제약정",
            "foreign_futures_net_contracts": None,
            "institution_futures_net_contracts": None,
            "put_call_ratio": None,
            "implied_volatility": None,
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\opt50001.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "front_future_code is resolved with GetFutureCodeByIndex(0). 투자자별 선물 순매수/PCR/IV는 별도 TR 검증 후 추가.",
    },
    "option_call_chain": {
        "enabled": True,
        "context_section": "derivatives",
        "tr_code": "OPT50021",
        "inputs": {
            "만기년월": "{front_option_month}",
        },
        "output_fields": {},
        "repeat_aggregation": {
            "row_count_key": "call_option_count",
            "sum_fields": {
                "call_option_volume": "누적거래량",
                "call_option_trading_value": "누적거래대금",
                "call_option_open_interest": "미결제약정",
            },
            "avg_fields": {
                "call_implied_volatility_avg": "내재변동성",
            },
        },
        "static_values": {
            "option_month": "{front_option_month}",
            "option_side": "call",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\OPT50021.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "콜옵션 월물 체인을 집계한다. PCR은 풋옵션 집계와 함께 계산한다.",
    },
    "option_put_chain": {
        "enabled": True,
        "context_section": "derivatives",
        "tr_code": "OPT50022",
        "inputs": {
            "만기년월": "{front_option_month}",
        },
        "output_fields": {},
        "repeat_aggregation": {
            "row_count_key": "put_option_count",
            "sum_fields": {
                "put_option_volume": "누적거래량",
                "put_option_trading_value": "누적거래대금",
                "put_option_open_interest": "미결제약정",
            },
            "avg_fields": {
                "put_implied_volatility_avg": "내재변동성",
            },
        },
        "static_values": {
            "option_month": "{front_option_month}",
            "option_side": "put",
        },
        "needs_koa_studio_verification": False,
        "source": "C:\\OpenAPI\\data\\OPT50022.enc / C:\\OpenAPI\\koatrinputlegend.ini",
        "note": "풋옵션 월물 체인을 집계한다. PCR은 콜옵션 집계와 함께 계산한다.",
    },
}


def get_realtime_fid_list(mapping_name):
    """Return a semicolon-separated FID list for SetRealReg."""
    mapping = REALTIME_CONTEXT_TYPES[mapping_name]
    fids = mapping["fids"]

    if isinstance(fids, dict):
        if all(isinstance(key, int) for key in fids.keys()):
            return ";".join(str(fid) for fid in fids.keys())

        flattened = []
        for value in fids.values():
            if isinstance(value, list):
                flattened.extend(value)
            else:
                flattened.append(value)
        return ";".join(str(fid) for fid in flattened)

    return ";".join(str(fid) for fid in fids)


def get_tr_mapping(mapping_name):
    """Return a TR mapping definition by name."""
    return TR_CONTEXT_MAPPINGS[mapping_name]
