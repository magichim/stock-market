# DB 설계 — 주식 모의 거래 (PostgreSQL 17)

SERVICE_PLAN.md를 구체화한 스키마. 정해진 주기마다 증권거래소 API로 지정 종목의 현재가를 적재하고, 사용자는 그 가격으로 가상 자금을 매수·매도한다. 오더북(호가 매칭)이 없어 주문은 **항상 그 시점의 최신가로 즉시 전량 체결**된다. 인센티브는 수익률과 리더보드(실시간 / 월간 / 연간 / 이벤트)다.

```
[predict-market API]                 [stock_market DB — 이 서비스 전용]
GET /api/internal/users ··user_id··▶ accounts ──┬── holdings ──▶ stocks ◀── price_ticks
                  (FK 없음, 앱에서 합침)   ▲     ├── trades ─────▶   ▲            ▲
                                          │     └── equity_snapshots └─ tick_id ─┘
                                        events (이벤트 계좌)
```

## 0. predict-market과의 관계 — 사용자는 API로만

- 데이터는 **이 서비스 전용 DB**(`stock_market`, `DATABASE_URL`)에 둔다. predict-market DB에는 접속하지 않는다.
- 사용자는 predict-market이 소유한다. 로그인은 agisaja.com이 처리하고 이 서비스는 access JWT의 `sub`(= predict-market `users.id`)만 신뢰한다 (AUTH.md). `accounts.user_id`는 이 id를 저장하며 **FK가 없다**.
- 다른 사용자의 표시 정보(리더보드)는 predict-market 내부 API `GET /api/internal/users?ids=1,2,3`(서버 간 Bearer 토큰, AUTH.md "서버 간 내부 API")으로 받는다. 응답: `{id, username, display_name, avatar_url, animal, ranked}`.
  - `ranked=false`(봇·게스트·admin)는 리더보드에서 뺀다 — 제외 기준은 predict-market이 한 곳에서 정한다.
  - `avatar_url`은 업로드 이미지의 절대 URL, `animal`은 기본 동물 아바타 키.
  - 리더보드 요청마다 그 순위의 id를 한 번에 조회한다 (`users.fetch_users`, 캐시 없음). API가 실패하면 순위는 그대로 두고 이름만 비워 내린다.
- 탈퇴 정리: predict-market에서 사용자가 삭제되면(탈퇴, 게스트 병합) 장 마감 후 하루 한 번 배치(`users.purge_deleted_users`)가 같은 API로 존재 여부를 확인해(응답에 없는 id = 삭제) 그 사용자의 계좌를 지운다 (보유·거래·스냅샷은 CASCADE). 그 전까지 리더보드에서는 응답에 없는 사용자를 뺀다. API 설정이 잘못돼 절반 넘게 없어 보이면 지우지 않고 경고만 남긴다.

테이블 생성은 predict-market과 같이 앱 시작 시 `create_all`(멱등)로 한다. DB는 superuser로 한 번 만들어 둔다 (`createdb -O dev stock_market`).

## ENUM 대신 CHECK

거래 방향은 `'buy' | 'sell'` 두 값뿐이라 Postgres ENUM 타입 대신 `VARCHAR + CHECK`로 둔다 (값 추가가 쉽다).

## 1. 종목과 가격

### stocks

가격을 수집하는 종목 목록("특정 기업 리스트"). 시드(`app/seed.py`)로 넣고 `is_active`로 수집 대상을 켜고 끈다. `last_price`/`last_price_at`은 수집기가 매 틱마다 갱신하는 **최신가 캐시**로, 체결가·평가액 계산이 매번 `price_ticks`를 뒤지지 않게 한다. `prev_close`는 전 거래일 마지막 가격(등락률 표시용).

```sql
CREATE TABLE stocks (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol        VARCHAR(12)  NOT NULL UNIQUE,   -- 거래소 종목코드 (예: 005930)
    name          VARCHAR(100) NOT NULL,          -- 삼성전자
    market        VARCHAR(10)  NOT NULL,          -- KOSPI | KOSDAQ
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    display_order SMALLINT     NOT NULL DEFAULT 0,
    last_price    NUMERIC(14,2),                  -- 최신가 (수집기 갱신)
    last_price_at TIMESTAMPTZ,                    -- 최신가 수집 시각
    prev_close    NUMERIC(14,2),                  -- 전 거래일 종가
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

### price_ticks

수집기가 주기(`PRICE_INTERVAL_SECONDS`, 기본 60초)마다 적재하는 append-only 시계열. 차트의 원천이며, 각 체결이 어떤 가격으로 이뤄졌는지 `trades.tick_id`로 추적한다.

```sql
CREATE TABLE price_ticks (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stock_id     BIGINT        NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    price        NUMERIC(14,2) NOT NULL CHECK (price > 0),
    collected_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (stock_id, collected_at)   -- (stock_id, collected_at) 인덱스 겸용: 종목별 기간 조회
);
```

규모: 종목 30개 × 390틱/일 × 250거래일 ≈ 연 300만 행. 장기 차트가 필요해지면 일봉 집계 테이블을 추가한다.

## 2. 이벤트

### events

이벤트 대회. 참가자는 이벤트 전용 계좌(`accounts.event_id`)를 받아 같은 시작 자금으로 기간 안에서만 거래하고, 이벤트 리더보드는 이 계좌들의 수익률로 매긴다. 기간은 KST 날짜 단위 — 시작일 장 시작부터 종료일 장 마감까지 거래할 수 있고, 최종 순위는 종료일 마감 스냅샷으로 확정된다.

```sql
CREATE TABLE events (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug         VARCHAR(40)   NOT NULL UNIQUE,
    title        VARCHAR(100)  NOT NULL,
    description  TEXT          NOT NULL DEFAULT '',
    initial_cash NUMERIC(18,2) NOT NULL CHECK (initial_cash > 0),
    start_date   DATE          NOT NULL,   -- KST
    end_date     DATE          NOT NULL,   -- KST (포함)
    published    BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CHECK (start_date <= end_date)
);
```

## 3. 계좌와 거래

### accounts

사용자 × (기본 | 이벤트)당 1개. `event_id IS NULL`이 기본 계좌로, 월간·연간·실시간 리더보드 대상이다. 계좌는 첫 매수 때 만들어진다 — 그 전 조회는 "시작 자금만 있는 빈 계좌"로 응답한다. 추가 입금은 없으므로 수익률은 항상 `평가액 / 기준 평가액 − 1`로 구할 수 있다.

```sql
CREATE TABLE accounts (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT        NOT NULL,          -- predict-market users.id (다른 서비스라 FK 없음)
    event_id     BIGINT        REFERENCES events(id) ON DELETE CASCADE,
    initial_cash NUMERIC(18,2) NOT NULL,              -- 생성 시점 시작 자금 (설정·이벤트 값 복사)
    cash         NUMERIC(18,2) NOT NULL CHECK (cash >= 0),
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (user_id, event_id)
);
```

### holdings

계좌 × 종목당 현재 보유. 수량이 0이 되면 행을 삭제한다. `avg_price`는 이동평균 매입가 — 매수 시 `(기존수량×평단 + 매수수량×체결가) / 새 수량`으로 갱신하고 매도 시에는 바뀌지 않는다. 공매도는 없다(보유 수량까지만 매도).

```sql
CREATE TABLE holdings (
    account_id BIGINT        NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    stock_id   BIGINT        NOT NULL REFERENCES stocks(id),
    quantity   BIGINT        NOT NULL CHECK (quantity > 0),
    avg_price  NUMERIC(16,4) NOT NULL,
    updated_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, stock_id)
);
```

### trades

append-only 체결 내역. 주문 = 체결이라 주문 테이블이 따로 없다. `price`는 체결 시점의 `stocks.last_price`, `tick_id`는 그 가격의 원천 틱. 매도는 `realized_pnl = (체결가 − 평단) × 수량`을 기록한다.

```sql
CREATE TABLE trades (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id   BIGINT        NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    stock_id     BIGINT        NOT NULL REFERENCES stocks(id),
    tick_id      BIGINT        REFERENCES price_ticks(id),
    side         VARCHAR(4)    NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity     BIGINT        NOT NULL CHECK (quantity > 0),
    price        NUMERIC(14,2) NOT NULL,
    amount       NUMERIC(18,2) NOT NULL,     -- price × quantity
    realized_pnl NUMERIC(18,2),              -- sell만
    executed_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_trades_account_time ON trades (account_id, executed_at DESC);
```

#### 체결 규칙

1. 장 운영 시간(KST 평일 09:00–15:30)이고, 종목 최신가가 신선할 때(`last_price_at`이 수집 주기 × 3 이내)만 체결한다. 이벤트 계좌는 이벤트 기간 안에서만.
2. 한 트랜잭션에서 계좌 행을 `SELECT ... FOR UPDATE`로 잠근 뒤 현금·보유 수량을 확인하고 `accounts.cash`, `holdings`, `trades`를 함께 갱신한다 — 동시 주문으로 현금이 음수가 되거나 초과 매도되지 않는다 (`cash >= 0`, `quantity > 0` CHECK가 최종 방어선).
3. 수수료·세금은 아직 없다. 필요해지면 `trades.fee` 컬럼을 추가하고 현금 차감에 반영한다.

## 4. 평가액 스냅샷과 리더보드

### equity_snapshots

장 마감 후(15:30 이후 첫 수집 루프) 모든 계좌의 평가액(`cash + Σ 보유수량 × 최신가`)을 날짜별로 적재한다. 월간·연간·이벤트 수익률의 기준점이며, 내 자산 추이 차트의 원천이다. 같은 날 다시 찍으면 덮어쓴다.

```sql
CREATE TABLE equity_snapshots (
    account_id    BIGINT        NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    snapshot_date DATE          NOT NULL,   -- KST 거래일
    total_value   NUMERIC(18,2) NOT NULL,
    PRIMARY KEY (account_id, snapshot_date)
);
```

### 리더보드 계산

모두 **수익률** 순위다. 평가액 `V`는 진행 중인 구간이면 최신가 기준 현재 평가액, 끝난 구간이면 구간 안 마지막 스냅샷.

| 리더보드 | 대상 계좌 | 기준 평가액 | 수익률 |
| --- | --- | --- | --- |
| 실시간 | 기본 계좌 | `initial_cash` | `V / initial_cash − 1` (누적) |
| 월간 / 연간 | 기본 계좌, 구간 끝 전에 거래가 있었던 계좌 | 구간 시작 전 마지막 스냅샷, 없으면(구간 중 가입) `initial_cash` | `V / 기준 − 1` |
| 이벤트 | 그 이벤트 계좌 | `initial_cash` (이벤트 시작 자금) | `V / initial_cash − 1`, 종료 후에는 종료일까지의 마지막 스냅샷으로 고정 |

실시간 리더보드는 매 수집 직후 계산해 **Redis 정렬 집합**에 넣고 조회는 Redis에서 읽는다. 월간·연간·이벤트는 요청 시 SQL로 계산한다.

## Redis (테이블 없음)

predict-market과 같은 Redis를 쓰므로 키는 모두 `stock:` 접두어를 붙인다.

| 키 | 타입 | 용도 |
| --- | --- | --- |
| `stock:lb:realtime` | ZSET | 실시간 리더보드. member = user_id, score = 누적 수익률. 수집 직후 임시 키에 만들어 `RENAME`으로 원자 교체 |
| `stock:lock:collect` | STRING (NX, EX 주기−1초) | 워커가 여러 개여도(uvicorn `--workers 2`) 한 주기에 한 워커만 가격을 수집 |
| `stock:lock:purge:{YYYY-MM-DD}` | STRING (NX, EX 2일) | 탈퇴 사용자 정리를 하루 한 번만 (실패 시 키 삭제 후 재시도) |
| `stock:lock:snapshot:{YYYY-MM-DD}` | STRING (NX, EX 2일) | 장 마감 스냅샷을 하루 한 번만 (실패 시 키 삭제 후 재시도) |

## 설계 결정 요약

| 결정 | 이유 |
| --- | --- |
| 데이터는 전용 DB, predict-market DB에는 접속하지 않음 | 부하·백업·복구·스키마 변경을 predict-market과 독립. 가격 틱이 쌓여도 predict-market에 영향 없음 |
| 사용자 프로필은 predict-market 내부 API로 매번 조회 (캐시 없음) | users 스키마·리더보드 제외 기준·아바타 규칙을 predict-market이 소유. DB 접속 정보 없이 토큰 하나로 접근 |
| `accounts.user_id` FK 없음 + 일 배치 정리 | 다른 서비스라 FK·CASCADE가 불가능. 정리 전까지는 표시 단계에서 탈퇴 사용자를 거른다 |
| 오더북·주문 테이블 없음, `trades`만 | 주문은 최신가로 즉시 전량 체결 — 주문 = 체결 |
| `stocks.last_price` 캐시 | 체결·평가액·리더보드 계산을 종목 수만큼의 조인으로 끝낸다 |
| 금액·가격 `NUMERIC` | 부동소수 오차 없이 현금·평단 계산 |
| 이벤트는 전용 계좌 | 같은 시작 자금·같은 기간으로 공정 비교. 기본 계좌 성과와 섞이지 않음 |
| 일별 `equity_snapshots` | 추가 입금이 없어 기간 수익률 = 평가액 비율. 기간 시작 평가액만 있으면 월간·연간·이벤트를 모두 계산 |
| 실시간 리더보드는 Redis ZSET | 가격이 바뀔 때(수집 주기)만 순위가 바뀌므로 그때 한 번 계산하고 조회는 메모리에서 |
