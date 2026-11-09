#!/usr/bin/env bash
# 백엔드 앱서버 백그라운드 관리: ./server.sh {start|dev|stop|restart|status|log}
# start: worker 2개, dev: --reload (코드 변경 시 자동 재시작)
set -euo pipefail

cd "$(dirname "$0")"
PORT="${PORT:-8100}"
RUN_DIR=.run
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
  nohup uv run uvicorn app.main:app --port "$PORT" "${mode_flags[@]}" --timeout-graceful-shutdown 3 \
    >>"$LOG_FILE" 2>&1 </dev/null &
  echo $! >"$PID_FILE"
  # 포트는 worker 기동(lifespan, 스키마 패치) 전에 열리므로 HTTP 응답까지 기다린다
  for _ in {1..60}; do
    curl -sf -o /dev/null "http://127.0.0.1:$PORT/docs" && { log "시작됨 (pid $(cat "$PID_FILE"), http://127.0.0.1:$PORT, log $LOG_FILE)"; return; }
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
  start) start --workers 2 ;;
  dev) start --reload ;;
  stop) stop ;;
  restart) stop; start --workers 2 ;;
  status) status ;;
  log) tail -n 50 -f "$LOG_FILE" ;;
  *) echo "사용법: $0 {start|dev|stop|restart|status|log}"; exit 1 ;;
esac
