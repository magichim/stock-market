#!/usr/bin/env bash
# KIS 게이트웨이 백그라운드 관리: ./server.sh {start|dev|stop|restart|status|log|vendor}
# 호출 통계·KIS 토큰 상태를 프로세스 메모리에 두므로 worker는 하나만 띄운다. vendor: KIS 샘플 저장소를 VENDOR_COMMIT으로 받는다
set -euo pipefail

cd "$(dirname "$0")"
# KIS 샘플(vendor/kis_auth.py)이 토큰 만료를 시스템 시간으로 판단하는데 KIS는 만료 시각을 한국 시간으로 준다 —
# 프로세스 시간대를 KST로 고정한다. POSIX 표기(UTC+9)라 서버에 tzdata가 없어도 된다
export TZ=KST-9
PORT="${PORT:-8200}"
RUN_DIR=.run
# KIS 샘플 저장소(koreainvestment/open-trading-api) 고정 커밋 — 올릴 때는 로컬에서 조회를 확인한 뒤 이 값을 바꾼다
VENDOR_COMMIT="${VENDOR_COMMIT:-74b0a082fa67a0be5bf53f561719c853890ed2df}"
PID_FILE="$RUN_DIR/uvicorn.pid"
LOG_FILE="$RUN_DIR/uvicorn.log"

# 터미널 출력 + 로그 파일에 타임스탬프와 함께 기록
log() { mkdir -p "$RUN_DIR"; echo "[$(date '+%F %T')] [server.sh] $*" | tee -a "$LOG_FILE"; }

port_pids() { lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true; }

is_running() { [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

start() {
  local mode_flags=("$@")
  if is_running; then
    log "이미 실행 중 (pid $(cat "$PID_FILE"), port $PORT)"; return
  fi
  if [[ -n "$(port_pids)" ]]; then
    log "시작 실패 — port $PORT 사용 중 (pid $(port_pids | tr '\n' ' ')) — 다른 프로세스. './server.sh stop'으로 정리 가능"; exit 1
  fi
  log "시작 시도 (port $PORT, ${mode_flags[*]})"
  nohup uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT" "${mode_flags[@]}" --timeout-graceful-shutdown 3 --log-config log.json \
    >>"$LOG_FILE" 2>&1 </dev/null &
  echo $! >"$PID_FILE"
  # HTTP 응답까지 기다린다
  for _ in {1..60}; do
    curl -sf -o /dev/null "http://127.0.0.1:$PORT/meta/status" && { log "시작됨 (pid $(cat "$PID_FILE"), http://127.0.0.1:$PORT, log $LOG_FILE)"; return; }
    is_running || break
    sleep 0.5
  done
  if is_running; then
    log "시작 실패 — 30초 내 port $PORT HTTP 미응답 (pid $(cat "$PID_FILE") 실행 중)"
  else
    log "시작 실패 — 프로세스 종료됨"
  fi
  echo "로그 확인: $LOG_FILE"; tail -n 20 "$LOG_FILE"; rm -f "$PID_FILE"; exit 1
}

stop() {
  local pids=""
  is_running && pids="$(cat "$PID_FILE") $(pgrep -P "$(cat "$PID_FILE")" || true)"
  pids="$pids $(port_pids)"
  pids="$(echo $pids)"
  if [[ -z "$pids" ]]; then
    echo "실행 중 아님"; rm -f "$PID_FILE"; return
  fi
  kill $pids 2>/dev/null || true
  for _ in {1..20}; do
    [[ -z "$(port_pids)" ]] && ! is_running && break
    sleep 0.5
  done
  if [[ -n "$(port_pids)" ]] || is_running; then
    log "정상 종료 안 됨 — 강제 종료 (pid $pids)"
    kill -9 $pids $(port_pids) 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  log "종료됨 (pid $pids)"
}

status() {
  if is_running; then
    echo "실행 중 (pid $(cat "$PID_FILE"), port $PORT)"
  elif [[ -n "$(port_pids)" ]]; then
    echo "port $PORT 사용 중이나 이 스크립트로 시작한 프로세스 아님 (pid $(port_pids | tr '\n' ' '))"
  else
    echo "실행 중 아님"
  fi
}

case "${1:-}" in
  start) start --workers 1 ;;
  dev) start --reload ;;
  stop) stop ;;
  restart) stop; start --workers 1 ;;
  status) status ;;
  vendor)
    # VENDOR_COMMIT 하나만 받아 그 커밋으로 맞춘다 — 서버마다 같은 샘플 코드를 쓰게 한다
    if [[ ! -d vendor/.git ]]; then
      git init -q vendor
      git -C vendor remote add origin https://github.com/koreainvestment/open-trading-api
    fi
    git -C vendor fetch -q --depth 1 origin "$VENDOR_COMMIT"
    git -C vendor checkout -q --detach FETCH_HEAD
    echo "vendor: $(git -C vendor log -1 --format='%h %cs')" ;;
  log) tail -n 50 -f "$LOG_FILE" ;;
  *) echo "사용법: $0 {start|dev|stop|restart|status|log|vendor}"; exit 1 ;;
esac
