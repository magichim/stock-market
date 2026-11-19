# kis — KIS 게이트웨이

한국투자증권 Open API 샘플([koreainvestment/open-trading-api](https://github.com/koreainvestment/open-trading-api))의 `examples_llm` 함수를 HTTP로 구동한다. backend·frontend와 별개 프로세스이고, DB에는 접근하지 않는다 — 가격 적재는 backend 수집기가 `KisProvider`(`backend/app/prices.py`)로 이 서비스를 호출해서 한다.

파일 구성과 요청 흐름은 [STRUCTURE.md](STRUCTURE.md).

첫 버전(테스트용)이다. 웹소켓 실시간 시세는 아직 없고, 조회는 한 번에 하나씩 순서대로 KIS에 보낸다.

```
app/
  config.py   kis/.env 설정
  vendor.py   샘플 함수 목록(AST 스캔)·지연 import·인증·호출, 호출 통계
  quotes.py   /quotes — 수집기용 묶음 조회 (종목 현재가, 환율, 지수)
  main.py     /api/{카테고리}/{API명}, /meta, 페이지
  static/     모니터링(/)·API 목록(/apis) 페이지
vendor/       KIS 샘플 저장소 (git 제외 — ./server.sh vendor)
.run/         pid·로그, KIS 설정·토큰 파일(.run/home) — git 제외
```

## 실행

```bash
cp .env.example .env   # KIS Developers에서 받은 앱키·시크릿·계좌
./server.sh vendor     # KIS 샘플 저장소를 고정 커밋(server.sh의 VENDOR_COMMIT)으로 받는다
./server.sh dev        # start|dev|stop|restart|status|log, PORT 기본 8200
```

- `http://localhost:8200/` 모니터링 — 프로세스, 투자 환경, 앱키·토큰 상태, 호출 통계, 최근 호출
- `http://localhost:8200/apis` API 목록 — 검색, 파라미터, 설명, 조회 API 직접 호출

## API

| 경로 | 설명 |
| --- | --- |
| `GET /api/{카테고리}/{API명}?파라미터` | 조회 API. 응답 `{"data": ..., "error": KIS 오류 또는 null}` |
| `POST /api/{카테고리}/{API명}` (JSON) | 주문 API — `KIS_ALLOW_ORDER=true`일 때만 |
| `GET /quotes/stocks?items=005930:KOSPI,AAPL:NASDAQ` | 종목 현재가 묶음 |
| `GET /quotes/fx?currencies=USD` | 환율 (1 통화당 KRW) |
| `GET /quotes/indices?codes=0001,1001,2001` | 국내 지수 (코스피, 코스닥, 코스피200) |
| `GET /meta/status`, `GET /meta/apis` | 상태, API 목록 JSON |

`env_dv`(실전/모의) 파라미터는 호출자가 넘긴 값과 무관하게 `KIS_ENV`를 따른다.

## 주의

- 로그인이 없다. `127.0.0.1`에만 바인딩하고, 외부에 노출하지 않는다.
- 주문 API는 기본 차단. 켜더라도 JSON POST + Origin 검사를 거친다.
- 모의투자(`KIS_ENV=demo`)는 지수·환율·해외 시세 등 일부 조회를 지원하지 않는다. 가격 수집에 쓰려면 `real`이 필요하다.
- 샘플의 `kis_auth`는 `~/KIS/config`를 읽지만, 여기서는 `.env` 값으로 `.run/home/KIS/config/kis_devlp.yaml`을 만들어 그쪽을 읽게 한다. 토큰도 그곳에 하루 단위로 저장된다 (KIS 토큰 발급은 분당 1회 제한).
- worker는 하나만 띄운다 (토큰·호출 통계가 프로세스 메모리에 있다).
