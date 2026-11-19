# kis 프로젝트 구조

KIS 게이트웨이(포트 8200)의 파일 구성과 요청 흐름. 실행 방법과 API 표는 [README.md](README.md).

## 위치

```
stock-market/
  frontend/   5273  Vite + React
  backend/    8100  FastAPI — DB 적재, 수집기
  kis/        8200  FastAPI — KIS 호출만 (DB 접근 없음)
```

```
backend 수집기 (prices.py · KisProvider)
      │  GET /quotes/stocks, /quotes/fx
      ▼
kis 게이트웨이 ──▶ vendor/examples_llm 샘플 함수 ──▶ KIS Open API
      ▲
브라우저 (/ 모니터링, /apis 목록)
```

## 파일

```
kis/
  pyproject.toml     의존성 (fastapi, uvicorn + 샘플이 쓰는 pandas·requests·pyyaml 등)
  uv.lock
  server.sh          백그라운드 관리 — start|dev|stop|restart|status|log|vendor
  .env.example       설정 견본 (커밋)
  .env               실제 설정 — 앱키·시크릿·계좌 (git 제외)
  README.md          실행·API·주의 사항
  STRUCTURE.md       이 문서
  app/
    config.py        .env 로딩 (Settings)
    vendor.py        샘플 함수 목록·인증·호출·통계
    quotes.py        /quotes 묶음 조회
    main.py          FastAPI 앱, 라우트
    static/
      index.html     모니터링 페이지 (/)
      apis.html      API 목록 페이지 (/apis)
      style.css      두 페이지 공통 스타일
  vendor/            koreainvestment/open-trading-api — server.sh의 VENDOR_COMMIT 커밋 (git 제외)
  .run/              실행 중 생기는 파일 (git 제외)
    uvicorn.pid, uvicorn.log        server.sh가 쓴다
    home/KIS/config/kis_devlp.yaml  .env로 만든 KIS 설정 (권한 600)
    home/KIS/config/KIS{날짜}_{svr}  KIS 접근 토큰 (하루 단위)
```

## 모듈

### `app/config.py`

`Settings` — `kis/.env`를 읽는다. 프로세스 시작 시 한 번만 읽으므로 `.env`를 고치면 재시작해야 한다 (`--reload`는 `.py` 변경만 감지한다).

| 속성 | 설명 |
| --- | --- |
| `kis_env` | `demo`(모의) / `real`(실전) |
| `kis_allow_order` | 주문 API 허용 여부 |
| `svr` | `kis_auth`의 서버 구분 — `real`→`prod`, `demo`→`vps` |
| `configured` | 현재 환경의 앱키·시크릿이 채워져 있는지 |

### `app/vendor.py`

샘플 저장소와 맞닿는 유일한 모듈.

| 이름 | 역할 |
| --- | --- |
| `scan()` → `APIS` | `vendor/examples_llm/{카테고리}/{API명}/{API명}.py`를 AST로 읽어 목록을 만든다 (import 없음). 종류는 소스로 판별 — `_url_fetch` 없음: `websocket`, `postFlag=True`: `order`, 나머지: `rest` |
| `_kis_auth()` | 처음 호출 때 `kis_auth`를 import. `.env` 값으로 `kis_devlp.yaml`을 만들고, import 동안만 홈 경로를 `.run/home`으로 돌린다. `_url_fetch`를 감싸 호출 간격(실전 0.06초, 모의 0.5초)과 KIS 오류를 기록한다 |
| `_ensure_auth()` | 유효한 토큰이 없으면 발급. 실패하면 1분간 재시도하지 않는다 |
| `_function()` | 호출할 샘플 파일만 지연 import |
| `call()` | 호출 + 통계 기록 (`totals`, `recent`) |
| `_invoke()` | 파라미터 검증 → 락 → 인증 → 샘플 함수 실행 → JSON 변환 |
| `token_expires_at()` | 토큰 파일의 만료 시각 (토큰 값은 읽지 않는다) |
| `KisError` | HTTP 상태 코드와 메시지를 담는 예외 |

프로세스 메모리에 두는 상태: `APIS`(목록), `_functions`(import한 함수), `totals`·`upstream`(호출 수), `recent`(최근 100건). 재시작하면 통계는 비워진다.

### `app/quotes.py`

backend 수집기가 쓰는 묶음 조회. 종목 하나가 실패해도 나머지는 `prices`에, 실패 사유는 `errors`에 담는다.

| 경로 | 쓰는 샘플 API | 값 컬럼 |
| --- | --- | --- |
| `/quotes/stocks` | 국내 `domestic_stock/inquire_price`, 해외 `overseas_stock/price` | `stck_prpr`, `last` |
| `/quotes/fx` | `overseas_stock/inquire_daily_chartprice` (시장 `X`) | `ovrs_nmix_prpr` |
| `/quotes/indices` | `domestic_stock/inquire_index_price` | `bstp_nmix_prpr` |

`/quotes/stocks`는 국내 종목이 있으면 `domestic_stock/chk_holiday`(국내휴장일조회)를 먼저 호출해 오늘(KST)이 개장일(`opnd_yn=Y`)일 때만 국내 시세를 받는다. 휴장일이거나 조회에 실패하면 국내 종목은 `errors`(`휴장일` / `휴장일 조회 실패 — …`)로 돌려주고, 해외 종목은 그대로 조회한다. KIS가 이 API는 1일 1회 호출을 권하므로 응답에 담긴 날짜별 개장 여부를 프로세스 메모리에 캐시한다 (실패는 캐시하지 않는다).

국내 시세는 KRX+NXT 통합(`fid_cond_mrkt_div_code=UN`)으로 받는다 — backend가 NXT 시간을 포함한 평일 08:00–20:00에 수집한다(`backend/app/market.py`). 국내 종목 시세는 순서대로 하나씩, 초당 최대 10건(`DOMESTIC_INTERVAL` 0.1초 간격)으로 조회한다 — KIS 한도(초당 20건)의 절반. 해외 종목은 국내 조회가 끝난 뒤 `vendor.MIN_INTERVAL` 간격으로 이어서 조회한다.

### `app/main.py`

| 경로 | 설명 |
| --- | --- |
| `GET /api/{카테고리}/{API명}` | 조회 API — 쿼리 파라미터를 샘플 함수 인자로 넘긴다 |
| `POST /api/{카테고리}/{API명}` | 주문 API — JSON 본문, Origin 검사 |
| `GET /meta/status` | 상태 JSON (모니터링 페이지가 5초마다 읽는다) |
| `GET /meta/apis` | API 목록 JSON |
| `GET /`, `GET /apis` | 페이지 |
| `/static/*` | 페이지 자원 |
| `/docs` | FastAPI OpenAPI 문서 |

## 요청 흐름

`GET /api/domestic_stock/inquire_price?fid_cond_mrkt_div_code=J&fid_input_iscd=005930`

1. `main.call_get` — 주문 API면 405
2. `vendor.call` → `_invoke`
   - 목록에 없으면 404, 웹소켓이면 400, 주문인데 차단 상태면 403
   - 없는 파라미터·필수 누락이면 400
   - `env_dv`는 `KIS_ENV` 값으로 덮어쓴다
3. 락을 잡고 `_kis_auth` → `_ensure_auth` (앱키 없음·토큰 실패면 503)
4. 샘플 함수 실행 → `kis_auth._url_fetch`가 KIS에 요청
5. DataFrame을 JSON으로 바꿔 `{"data": ..., "error": ...}` 응답, `recent`에 기록

## 시간

- 게이트웨이 코드는 시각을 UTC로 얻고, KIS에 넘기는 날짜만 KST(UTC+9 고정)로 바꾼다 (`quotes.today_kst`).
- KIS 샘플(`vendor/kis_auth.py`)은 토큰 만료를 시스템 시간으로 판단한다. KIS가 만료 시각을 한국 시간으로 주므로 `server.sh`가 프로세스 시간대를 `TZ=KST-9`로 고정한다. `server.sh` 없이 직접 띄울 때도 같은 값을 준다.

## 아직 없는 것

- 웹소켓 실시간 시세 (목록에만 나온다)
- 지수의 DB 적재 (조회만 된다)
- 동시 호출 — 락으로 한 번에 하나씩 보낸다
- 실제 KIS 응답으로 확인한 `/quotes` 필드명
