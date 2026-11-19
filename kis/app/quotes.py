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
# 국내 개장일 캐시 {YYYYMMDD: 개장 여부} — KIS가 휴장일 조회는 1일 1회를 권하므로, 기준일부터 여러 날이 오는 응답을 모두 담아 둔다
_trading_days: dict[str, bool] = {}

# stocks.market → KIS 해외 거래소 코드. 없으면 국내(KRX)
OVERSEAS = {"NASDAQ": "NAS", "NYSE": "NYS", "AMEX": "AMS"}


def _collect(codes: list[str], fetch, interval: float = 0) -> dict:
    """fetch(code) → (API 키, 인자, 값이 든 컬럼). 응답 첫 행의 그 컬럼을 값으로 쓴다.

    순서대로 하나씩 호출하고, interval이 있으면 호출 시작 간격을 그 이상으로 벌린다.
    """
    prices, errors = {}, {}
    last = 0.0
    for code in codes:
        time.sleep(max(0.0, last + interval - time.monotonic()))
        last = time.monotonic()
        key, args, column = fetch(code)
        res = vendor.call(key, args)
        rows = res["data"][0] if key.endswith("chartprice") else res["data"]  # chartprice는 (현재, 일별) 튜플
        value = rows[0].get(column) if rows else None
        if value in (None, "", "0"):
            errors[code] = (res["error"] or {}).get("message") or "값 없음"
        else:
            prices[code] = value
    return {"prices": prices, "errors": errors}


def is_trading_day(day: str) -> bool:
    """국내 주식시장 개장일(opnd_yn)인지. 조회에 실패하면 KisError — 캐시하지 않아 다음 호출 때 다시 조회한다."""
    if day not in _trading_days:
        res = vendor.call("domestic_stock/chk_holiday", {"bass_dt": day})
        _trading_days.update({r["bass_dt"]: r["opnd_yn"] == "Y" for r in res["data"] or []})
        if day not in _trading_days:
            raise vendor.KisError(502, (res["error"] or {}).get("message") or "휴장일 조회 결과 없음")
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
