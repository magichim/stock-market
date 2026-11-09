# Agent Guidelines

## Core Principles

1. **Think first, then code** — Analyze the problem and plan the approach before writing any code.
2. **Reason step by step** — Break work into small steps and make decisions through logical reasoning, one step at a time.
3. **Keep code concise** — Write the simplest code that solves the problem. No unnecessary abstractions, boilerplate, or speculative features.
4. **Keep answers brief** — Respond concisely. No verbose explanations; state only what matters.

## Project

- stock.agisaja.com 서비스. `backend/` FastAPI(uv), `frontend/` Vite + React + TS.
- 기본 포트: 프론트 `5273`, 백엔드 `8100` — predict-market(5173·8000)과 겹치지 않게 유지한다.
- 실행 방법은 `README.md`.

## Auth

- 로그인·refresh·로그아웃은 agisaja.com(predict-market)이 처리한다. 이 프로젝트에 자체 로그인, refresh 토큰 처리, 세션 쿠키 발급·삭제를 만들지 않는다. 구조와 이유는 `AUTH.md`.
- 백엔드는 공유 access 쿠키를 `JWT_SECRET`으로 검증만 한다 (`backend/app/auth.py`). 로그인이 필요한 API는 `get_optional_user`를 쓰거나 같은 규칙(만료 + `has_session`이면 401)을 따른다.
- 프론트의 API 호출은 `frontend/src/api.ts`의 `send`를 거친다 (401 시 agisaja.com refresh 후 재시도).
- 상태를 바꾸는 API(POST/PUT/DELETE)를 추가할 때는 CSRF 방어(Origin 검사)를 함께 넣는다.
- `JWT_SECRET` 등 비밀값은 코드·저장소에 넣지 않고 `backend/.env`(git 제외)로만 주입한다.
- 인증 동작을 바꾸면 `AUTH.md`도 함께 고친다.

## UI Rules

- **No emoji in UI** — Never use emoji in user-facing UI text or code. Use plain symbols (•, ·, — 등) instead.

## Styles

- `frontend/src/index.css`는 `@import` 목록만 둔다. 실제 스타일은 `frontend/src/styles/*.css`에 기능·컴포넌트별로 있다 (각 파일 첫 줄 주석에 담당 컴포넌트).
- import 순서가 cascade 순서다. 순서를 바꾸거나, 뒤 파일이 덮어쓰는 규칙을 앞 파일로 옮기지 않는다.
- 새 기능은 새 파일을 만들고 관련 파일 뒤에 `@import`를 추가한다. 반응형 `@media`도 같은 파일 안, 해당 규칙 뒤에 둔다.

## Workflow

- Understand the requirement fully before touching code.
- When multiple approaches exist, briefly weigh them and pick one — don't implement all.
- Prefer editing existing code over adding new files.
- Verify changes work before declaring them done (`npm run build` for frontend).
