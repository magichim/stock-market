"""수집기용 묶음 조회 — backend의 KisProvider(backend/app/prices.py)가 쓴다.

종목 하나가 실패해도 나머지는 돌려준다: {"prices": {코드: 값}, "errors": {코드: 사유}}.
"""

import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from . import vendor

router = APIRouter(prefix="/quotes")

# 시각은 UTC로 얻고 KIS에 넘기는 날짜만 KST(UTC+9 고정)로 바꾼다 — 서버의 시스템 시간대에 의존하지 않는다
KST = timezone(timedelta(hours=9), "KST")


def today_kst() -> str:
    return datetime.now(timezone.utc).astimezone(KST).strftime("%Y%m%d")

# 국내 종목 시세는 초당 최대 10건 — KIS 한도(초당 20건)의 절반만 쓴다. 호출 간격은 vendor.MIN_INTERVAL과 별개로 지킨다
DOMESTIC_INTERVAL = 0.1
# 국내 개장일 캐시 {YYYYMMDD: 개장 여부} — 마지막으로 조회한 날짜 하나만 둔다 (KIS 권고대로 1일 1회 호출, 미리 받은 뒷날짜 값은 쓰지 않는다)
_trading_days: dict[str, bool] = {}

# stocks.market → KIS 해외 거래소 코드. 없으면 국내(KRX)
OVERSEAS = {"NASDAQ": "NAS", "NYSE": "NYS", "AMEX": "AMS"}


def _rows(codes: list[str], fetch, interval: float = 0) -> tuple[dict, dict]:
    """fetch(code) → (API 키, 인자). ({code: 응답 첫 행 | None}, {code: KIS 오류})를 돌려준다.

    순서대로 하나씩 호출하고, interval이 있으면 호출 시작 간격을 그 이상으로 벌린다.
    """
    rows, errors = {}, {}
    last = 0.0
    for code in codes:
        time.sleep(max(0.0, last + interval - time.monotonic()))
        last = time.monotonic()
        key, args = fetch(code)
        res = vendor.call(key, args)
        data = res["data"][0] if key.endswith("chartprice") else res["data"]  # chartprice는 (현재, 일별) 튜플
        rows[code] = data[0] if data else None
        if res["error"]:
            errors[code] = res["error"].get("message") or "KIS 오류"
    return rows, errors


def _collect(codes: list[str], fetch, interval: float = 0) -> dict:
    """fetch(code) → (API 키, 인자, 값이 든 컬럼). 값이 비었거나 0인 코드는 errors로 돌린다."""
    columns = {}

    def request(code):
        key, args, columns[code] = fetch(code)
        return key, args

    rows, kis_errors = _rows(codes, request, interval)
    prices = {c: v for c, row in rows.items() if (v := (row or {}).get(columns[c])) not in (None, "", "0")}
    return {"prices": prices, "errors": {c: kis_errors.get(c, "값 없음") for c in rows if c not in prices}}


def is_trading_day(day: str) -> bool:
    """국내 주식시장 개장일(opnd_yn)인지. 조회에 실패하면 KisError — 캐시하지 않아 다음 호출 때 다시 조회한다."""
    if day not in _trading_days:
        # 첫 페이지만 — 기준일은 첫 행에 있고, 뒤 페이지(미래 날짜)까지 받으면 한 번 확인에 KIS를 11번 부른다
        res = vendor.call("domestic_stock/chk_holiday", {"bass_dt": day}, max_depth=0)
        opnd = next((r["opnd_yn"] for r in res["data"] or [] if r["bass_dt"] == day), None)
        if opnd is None:
            raise vendor.KisError(502, (res["error"] or {}).get("message") or "휴장일 조회 결과 없음")
        _trading_days.clear()
        _trading_days[day] = opnd == "Y"
    return _trading_days[day]


@router.get("/stocks")
def stocks(items: str) -> dict:
    """items: '005930:KOSPI,AAPL:NASDAQ' — 종목코드:시장.

    국내 종목은 휴장일 조회를 먼저 거쳐 오늘(KST)이 개장일일 때만 시세를 받는다. 아니면 errors에 사유를 담는다.
    """
    markets = dict(i.split(":") for i in items.split(",") if i)
    domestic = [s for s, m in markets.items() if m not in OVERSEAS]
    skipped: dict[str, str] = {}
    if domestic:
        try:
            reason = None if is_trading_day(today_kst()) else "휴장일"
        except vendor.KisError as e:
            reason = f"휴장일 조회 실패 — {e.message}"
        if reason:
            skipped = dict.fromkeys(domestic, reason)

    def fetch(symbol):
        excd = OVERSEAS.get(markets[symbol])
        if excd:
            return "overseas_stock/price", {"auth": "", "excd": excd, "symb": symbol}, "last"
        return "domestic_stock/inquire_price", {"fid_cond_mrkt_div_code": "UN", "fid_input_iscd": symbol}, "stck_prpr"  # UN: KRX+NXT 통합

    # 국내는 초당 10건 간격으로, 해외는 그 뒤에 이어서 조회한다
    result = _collect([s for s in domestic if s not in skipped], fetch, DOMESTIC_INTERVAL)
    overseas = _collect([s for s in markets if s not in domestic], fetch)
    result["prices"].update(overseas["prices"])
    result["errors"].update(overseas["errors"] | skipped)
    return result


@router.get("/trading-day")
def trading_day(day: str | None = None) -> dict:
    """day(YYYYMMDD, 생략하면 오늘 KST)가 국내 주식시장 개장일인지."""
    day = day or today_kst()
    return {"day": day, "trading": is_trading_day(day)}


@router.get("/nxt")
def nxt(symbols: str) -> dict:
    """symbols: '005930,069500' — 국내 종목이 지금 NXT(넥스트레이드)에서 거래되는 종목인지.

    주식기본조회의 NXT 거래종목여부(cptt_trad_tr_psbl_yn)가 Y이고 NXT 거래정지(nxt_tr_stop_yn)가 아닐 때 true.
    """
    rows, errors = _rows(
        [s for s in symbols.split(",") if s],
        lambda symbol: ("domestic_stock/search_stock_info", {"prdt_type_cd": "300", "pdno": symbol}),  # 300: 주식·ETF·ETN·ELW
        DOMESTIC_INTERVAL,
    )
    tradable = {}
    for code, row in rows.items():
        listed = (row or {}).get("cptt_trad_tr_psbl_yn")
        if listed in ("Y", "N"):
            tradable[code] = listed == "Y" and row.get("nxt_tr_stop_yn") != "Y"
        else:
            errors.setdefault(code, "값 없음")
    return {"tradable": tradable, "errors": {c: e for c, e in errors.items() if c not in tradable}}


@router.get("/fx")
def fx(currencies: str = "USD") -> dict:
    """통화 1단위당 KRW. 실전(real)에서만 지원된다."""
    today = today_kst()
    return _collect(
        [c for c in currencies.split(",") if c],
        lambda c: (
            "overseas_stock/inquire_daily_chartprice",
            {"fid_cond_mrkt_div_code": "X", "fid_input_iscd": f"FX@{'KRW' if c == 'USD' else c + 'KRW'}",
             "fid_input_date_1": today, "fid_input_date_2": today, "fid_period_div_code": "D"},
            "ovrs_nmix_prpr",
        ),
    )


@router.get("/indices")
def indices(codes: str = "0001,1001,2001") -> dict:
    """국내 업종 지수 — 0001 코스피, 1001 코스닥, 2001 코스피200."""
    return _collect(
        [c for c in codes.split(",") if c],
        lambda c: ("domestic_stock/inquire_index_price", {"fid_cond_mrkt_div_code": "U", "fid_input_iscd": c}, "bstp_nmix_prpr"),
    )
