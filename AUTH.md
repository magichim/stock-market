# 인증 — agisaja.com 로그인 공유

stock.agisaja.com은 자체 로그인이 없다. agisaja.com(predict-market)이 발급한 인증 쿠키를 같이 쓴다.

## 역할 분담

| | agisaja.com (predict-market) | stock.agisaja.com (이 프로젝트) |
|---|---|---|
| 로그인 (이메일·소셜) | 처리 | agisaja.com 로그인 페이지로 보냄 (`?next=`로 복귀) |
| refresh | 처리 (`POST /api/auth/refresh`) | 프론트가 agisaja.com을 호출 |
| 로그아웃 | 처리 (`POST /api/auth/logout`) | 프론트가 agisaja.com을 호출 |
| access 토큰 검증 | 처리 | 같은 `JWT_SECRET`으로 서명만 검증 |
| refresh 토큰 DB | 읽기·쓰기 | 사용 안 함 |

refresh는 agisaja.com 한 곳에서만 한다. stock에서도 처리하면 refresh 쿠키 범위를 넓혀야 하고, 토큰 교체(rotation)·재사용 탐지 로직을 두 서버가 똑같이 유지해야 해서 어긋나면 로그인이 풀린다.

## 쿠키

agisaja.com 백엔드가 `COOKIE_DOMAIN=.agisaja.com`일 때 발급하는 쿠키.

| 쿠키 | Domain | Path | 속성 | 용도 |
|---|---|---|---|---|
| `__Secure-at` | `.agisaja.com` | `/` | HttpOnly, Secure, SameSite=Lax, 1시간 | access JWT (HS256). `sub`=user id, `username`, `typ`="access" |
| `has_session` | `.agisaja.com` | `/` | Secure, SameSite=Lax, 180일 | 로그인 여부 표시 (값 "1", JS로 읽음). 인증 정보 아님 |
| `rt` | agisaja.com 전용 | `/api/auth` | HttpOnly, Secure, SameSite=Strict, 180일 | refresh 토큰. stock에는 전송되지 않는다 |

stock.agisaja.com과 agisaja.com은 same-site라 SameSite=Strict여도 stock 페이지에서 agisaja.com으로 보내는 요청에 `rt`가 실린다. 서드파티 쿠키 차단에도 걸리지 않는다.

### has_session의 역할

토큰 쿠키는 HttpOnly라 JS가 읽을 수 없어서, 로그인 여부를 알리는 표시 쿠키를 따로 둔다.

- 프론트: 로그인 UI 표시, 401을 받았을 때 refresh를 시도할지 판단
- 서버: access가 없거나 만료된 요청에서 `has_session`이 있으면 401(refresh 유도), 없으면 비로그인으로 처리 (`backend/app/auth.py`)

## 흐름

### 로그인
1. "로그인" → `https://agisaja.com/login?next=<encodeURIComponent(현재 URL)>`
2. agisaja.com에서 로그인 → `.agisaja.com` 쿠키 발급
3. agisaja.com이 `next`로 돌려보낸다. 허용 범위: 프론트는 서브도메인·같은 호스트의 다른 포트, 백엔드(소셜 로그인)는 `TRUSTED_ORIGINS`
4. 이미 agisaja.com에 로그인된 상태면 로그인 페이지에서 바로 `next`로 돌아온다

### API 호출과 access 만료
```
stock 프론트                    stock 백엔드              agisaja.com 백엔드
  │ GET /api/me ───────────────▶│ __Secure-at 만료 + has_session 있음
  │◀───────────────── 401 ───────│
  │ POST https://agisaja.com/api/auth/refresh (credentials: 'include', rt 전송) ──▶│
  │◀──────── 200 + Set-Cookie: __Secure-at (Domain=.agisaja.com), rt(교체) ────────│
  │ GET /api/me 재시도 ─────────▶│ 검증 통과
  │◀───────────────── 200 ───────│
```
- 동시에 여러 요청이 401을 받아도 refresh는 한 번만 보낸다 (`frontend/src/api.ts` `refreshSession`)
- refresh가 실패하면(만료·폐기·탈취 감지) agisaja.com이 세션 쿠키를 지우고 401을 반환한다. 재시도는 비로그인으로 처리된다

### 로그아웃
`POST https://agisaja.com/api/auth/logout` (`credentials: 'include'`)
- 쿠키가 삭제되고 refresh 토큰 family가 DB에서 폐기된다. 같은 브라우저에서는 두 도메인이 함께 로그아웃된다
- 다른 기기의 로그인은 유지된다
- 이미 발급된 access JWT는 만료(최대 1시간)까지 서명 검증을 통과한다. 브라우저에서는 쿠키가 지워지므로 문제없다
- stock 백엔드에서 쿠키만 지우면 안 된다. `rt`가 남아 있어서 agisaja.com에 들어가면 다시 로그인된다

## 설정

### agisaja.com 백엔드 (predict-market `backend/.env`)
```
COOKIE_DOMAIN=.agisaja.com                  # 상위 도메인만. 스킴·포트·경로 없이
TRUSTED_ORIGINS=https://stock.agisaja.com   # origin 정확히, 끝 슬래시 없이. 여러 개면 쉼표로 구분
COOKIE_SECURE=true                          # 기본값. 켜져 있어야 __Secure-at 이름을 쓴다
JWT_SECRET=...                              # stock과 같은 값
```
`TRUSTED_ORIGINS`는 CORS(`allow_credentials`), CSRF Origin 검사, 소셜 로그인 후 복귀 URL 허용에 함께 쓰인다.

### stock 백엔드 (`backend/.env`)
```
JWT_SECRET=...              # agisaja.com과 같은 값 (필수)
ACCESS_COOKIE=__Secure-at   # 기본값
```

### stock 프론트 (빌드 시 환경변수)
```
VITE_AUTH_ORIGIN=https://agisaja.com   # 기본값
```

## 로컬 개발

localhost 쿠키는 포트를 구분하지 않으므로 `COOKIE_DOMAIN` 없이도 두 앱이 쿠키를 공유한다. 반드시 `127.0.0.1`이 아니라 `localhost`로 접속한다.

| 앱 | 프론트 | 백엔드 |
|---|---|---|
| predict-market | `localhost:5173` | `localhost:8000` |
| stock-market | `localhost:5273` | `localhost:8100` |

- predict-market `backend/.env`: `TRUSTED_ORIGINS=http://localhost:5273`을 추가한다 (소셜 로그인 복귀, CORS). `COOKIE_DOMAIN`은 비워 둔다
  - 로컬 refresh·로그아웃은 predict-market vite dev 서버가 localhost origin에 CORS 헤더를 채워 이 값 없이도 동작한다. 운영에는 vite가 없으므로 반드시 설정한다
- stock-market `backend/.env`: `JWT_SECRET`은 predict-market과 같은 값, `ACCESS_COOKIE=at` (predict-market이 `COOKIE_SECURE=false`이므로)
- stock 프론트는 `.env.development`의 `VITE_AUTH_ORIGIN=http://localhost:5173`으로 predict-market vite 서버를 거쳐 인증 API를 호출한다

## 배포 전환

배포 전에 로그인한 사용자는 호스트 전용 `__Host-at`, `has_session`만 가지고 있어서 stock에서는 비로그인으로 보인다.
- agisaja.com에 접속하면 앱 시작 시 `/api/auth/me`가 401을 받고 자동 refresh가 일어나 `.agisaja.com` 쿠키로 바뀐다 (기존 쿠키는 삭제)
- stock에 먼저 왔으면 로그인 버튼을 누르면 된다. agisaja.com 로그인 페이지에서 위 과정이 자동으로 진행되고 바로 stock으로 돌아온다. 다시 인증할 필요는 없다
- 배포 후 새로 로그인한 사용자는 처음부터 공유 쿠키로 발급된다

## 보안 주의

- `.agisaja.com` 아래 모든 서브도메인에 access 토큰이 전송된다. 신뢰할 수 없는 서브도메인을 만들지 않는다
- `JWT_SECRET`은 코드나 저장소에 넣지 않는다. 환경변수로만 주입한다
- stock 백엔드에 상태를 바꾸는 API(POST/PUT/DELETE)를 추가할 때는 CSRF 방어를 함께 넣는다. 예: predict-market `reject_cross_site_writes`처럼 Origin이 `https://stock.agisaja.com`인지 확인
- stock 백엔드는 JWT의 `typ == "access"`까지 확인한다 (`backend/app/auth.py`)
