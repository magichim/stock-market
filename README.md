# stock-market

stock.agisaja.com — 로그인은 agisaja.com(predict-market)과 공유한다. 구조와 설정은 [AUTH.md](AUTH.md) 참고.

주식 모의 거래 — 기획은 [SERVICE_PLAN.md](SERVICE_PLAN.md), 스키마는 [DB_DESIGN.md](DB_DESIGN.md).

```
backend/app/
  main.py         앱·lifespan (stock 스키마 create_all, 종목 시드, 가격 수집기 시작), CSRF 검사
  prices.py       가격 수집기 — 장중 주기 수집(Redis 락으로 워커 하나만), 장 마감 후 탈퇴 정리·평가액 스냅샷, 가격 공급자
  trading.py      계좌 조회·시장가 체결 (오더북 없음, 최신가로 즉시 전량 체결)
  leaderboard.py  수익률 순위 — 실시간(Redis ZSET) / 월간 / 연간 / 이벤트
  users.py        predict-market 프로필 조회(내부 API)·탈퇴 사용자 계좌 정리
  routers/        /api/stocks, /api/account, /api/trades, /api/events, /api/leaderboard
frontend/src/     종목(주문) · 내 계좌 · 리더보드 탭
```

데이터는 전용 DB(`stock_market`)에 두고, 다른 사용자의 프로필은 predict-market 내부 API로 조회한다 (AUTH.md "서버 간 내부 API"). Redis는 predict-market과 같이 써도 된다 (키 접두어 `stock:`).

로컬은 DB를 한 번 만들어 둔다 (테이블은 백엔드 시작 시 생성): `createdb -O dev stock_market` — `dev`에 DB 생성 권한이 없으면 superuser로 실행.

## 실행 (로컬)

predict-market(프론트 5173, 백엔드 8000)이 먼저 떠 있어야 로그인할 수 있다.

```bash
# 백엔드 — localhost:8100
cd backend
cp .env.example .env   # JWT_SECRET·INTERNAL_API_TOKEN을 predict-market과 같게, 로컬은 ACCESS_COOKIE=at, PREDICT_API_URL=http://localhost:8000
uv run uvicorn app.main:app --port 8100 --reload

# 프론트 — localhost:5273 (/api는 8100으로 프록시)
cd frontend
npm install
npm run dev
```

predict-market `backend/.env`에 `TRUSTED_ORIGINS=http://localhost:5273`을 추가한다. 소셜 로그인 후 이 앱으로 돌아오는 데 필요하고, CORS를 운영과 같은 조건으로 맞춘다 (로컬 refresh·로그아웃은 vite dev 서버가 CORS 헤더를 채워 이 값 없이도 동작한다).

브라우저에서 `http://localhost:5273`으로 접속한다 (`127.0.0.1` 말고 `localhost`).

## 운영

nginx가 모든 요청을 백엔드(8100)로 넘긴다. `frontend/dist`가 있으면 백엔드가 `/api/*`는 API로, 빌드 파일은 그대로, 나머지 경로는 `index.html`로 응답한다 (`backend/app/main.py`). dist는 백엔드 시작 시점에 확인하므로 빌드 후 백엔드를 시작(재시작)한다.

```bash
cd frontend && npm ci && npm run build
cd ../backend && ./server.sh restart   # start|dev|stop|restart|status|log, PORT 기본 8100
```

`server.sh`는 `uv run uvicorn app.main:app --port 8100 --workers 2`를 백그라운드로 띄우고 pid·로그를 `backend/.run/`에 둔다.
