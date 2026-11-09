# stock-market

stock.agisaja.com — 로그인은 agisaja.com(predict-market)과 공유한다. 구조와 설정은 [AUTH.md](AUTH.md) 참고.

```
backend/   FastAPI — GET /api/me (공유 access 쿠키 검증)
frontend/  Vite + React — 메인 페이지 하나 (로그인 상태·로그인·로그아웃 테스트)
```

## 실행 (로컬)

predict-market(프론트 5173, 백엔드 8000)이 먼저 떠 있어야 로그인할 수 있다.

```bash
# 백엔드 — localhost:8100
cd backend
cp .env.example .env   # JWT_SECRET을 predict-market과 같게, 로컬은 ACCESS_COOKIE=at
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
