"""vendor/(koreainvestment/open-trading-api)의 examples_llm 샘플 함수를 찾아 호출한다.

- 목록은 소스를 AST로 읽어 만든다 (import 없이).
- 호출은 처음 쓸 때 해당 파일만 import 한다.
- kis_auth는 ~/KIS/config/kis_devlp.yaml을 읽으므로, import 동안만 홈을 .run/home으로 돌리고
  .env 값으로 그 파일을 만들어 둔다 (토큰 파일도 같은 곳에 저장된다).
"""

import ast
import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
import threading
from collections import deque
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from unittest import mock

import yaml

from .config import ROOT, settings

VENDOR = ROOT / "vendor"
EXAMPLES = VENDOR / "examples_llm"
HOME = ROOT / ".run" / "home"
# 페이지네이션용 내부 인자 — 목록·호출에서 숨긴다
INTERNAL = {"tr_cont", "depth", "max_depth"}
MIN_INTERVAL = {"real": 0.06, "demo": 0.5}[settings.kis_env]  # KIS 초당 호출 제한 (실전 20건, 모의 2건)


class KisError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


@dataclass
class Api:
    category: str
    name: str
    title: str
    url: str
    kind: str  # rest | order | websocket
    doc: str
    params: list[dict]


def scan() -> dict[str, Api]:
    apis = {}
    for path in sorted(EXAMPLES.glob("*/*/*.py")):
        name = path.stem
        if name != path.parent.name:
            continue
        src = path.read_text(encoding="utf-8")
        fn = next((n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name), None)
        if fn is None:
            continue
        lines = src.splitlines()
        args = fn.args.args
        defaults = [None] * (len(args) - len(fn.args.defaults)) + fn.args.defaults
        params = []
        for a, d in zip(args, defaults):
            type_ = ast.unparse(a.annotation) if a.annotation else "str"
            if a.arg in INTERNAL or "DataFrame" in type_:
                continue
            params.append({
                "name": a.arg,
                "type": type_,
                "required": d is None,
                "default": d.value if isinstance(d, ast.Constant) else None,
                "desc": lines[a.lineno - 1].partition("#")[2].strip(),
            })
        title = re.search(r"^#\s*(\[.+)$", src, re.M)
        url = re.search(r'API_URL\s*=\s*"([^"]+)"', src)
        kind = "websocket" if "_url_fetch" not in src else "order" if re.search(r"postFlag\s*=\s*True", src) else "rest"
        category = path.parent.parent.name
        apis[f"{category}/{name}"] = Api(
            category, name, title.group(1).strip() if title else name, url.group(1) if url else "",
            kind, ast.get_docstring(fn) or "", params,
        )
    return apis


def vendor_version() -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(VENDOR), "log", "-1", "--format=%h %cs"], capture_output=True, text=True, timeout=5
        ).stdout.strip() or None
    except Exception:
        return None


APIS = scan()

_lock = threading.Lock()  # kis_auth가 전역 상태를 쓰고 호출 제한도 있어 한 번에 하나만 호출한다
_ka = None
_functions: dict[str, object] = {}
_last_fetch = 0.0
_last_error: dict | None = None
_auth_retry_at = 0.0
upstream = {"calls": 0, "errors": 0}  # KIS로 나간 HTTP 요청 (페이지네이션 포함)
totals = {"calls": 0, "errors": 0}  # 게이트웨이 API 호출
recent: deque[dict] = deque(maxlen=100)  # 최근 호출 (프로세스 메모리 — 재시작하면 비워진다)


def _write_config() -> None:
    cfg = yaml.safe_load((VENDOR / "kis_devlp.yaml").read_text(encoding="utf-8"))  # 도메인·User-Agent는 샘플 값 그대로
    s = settings
    cfg.update(
        my_app=s.kis_app_key, my_sec=s.kis_app_secret, paper_app=s.kis_paper_app_key, paper_sec=s.kis_paper_app_secret,
        my_htsid=s.kis_hts_id, my_acct_stock=s.kis_acct_stock, my_acct_future=s.kis_acct_future,
        my_paper_stock=s.kis_paper_acct_stock, my_paper_future=s.kis_paper_acct_future, my_prod=s.kis_prod, my_token="",
    )
    path = HOME / "KIS" / "config" / "kis_devlp.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)  # 토큰 파일도 여기에 저장된다
    path.touch(mode=0o600)
    path.chmod(0o600)
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")


def _kis_auth():
    global _ka
    if _ka is None:
        if not EXAMPLES.is_dir():
            raise KisError(503, "vendor 없음 — ./server.sh vendor 로 받는다")
        _write_config()
        sys.path.insert(0, str(EXAMPLES))
        expanduser = os.path.expanduser
        with mock.patch("os.path.expanduser", lambda p: str(HOME) if p == "~" else expanduser(p)):
            import kis_auth
        fetch = kis_auth._url_fetch

        def tracked_fetch(*args, **kwargs):
            """호출 간격을 지키고, 샘플 함수가 삼키는 KIS 오류를 기록한다."""
            global _last_fetch, _last_error
            time.sleep(max(0.0, _last_fetch + MIN_INTERVAL - time.monotonic()))
            res = fetch(*args, **kwargs)
            _last_fetch = time.monotonic()
            upstream["calls"] += 1
            if not res.isOK():
                upstream["errors"] += 1
                _last_error = {"code": res.getErrorCode(), "message": res.getErrorMessage()}
            return res

        kis_auth._url_fetch = tracked_fetch
        _ka = kis_auth
    return _ka


def _ensure_auth(ka) -> None:
    global _auth_retry_at
    if not settings.configured:
        raise KisError(503, f"KIS 앱키 미설정 — kis/.env ({settings.kis_env})")
    # 발급 성공 여부는 헤더로 본다 — kis_auth는 첫 발급 때 TRENV.my_token을 비워 둔다
    if ka.read_token(settings.svr) and ka._base_headers.get("authorization"):
        return
    if time.monotonic() < _auth_retry_at:
        raise KisError(503, "KIS 토큰 발급 실패 — 1분 뒤 다시 시도한다")
    ka.auth(svr=settings.svr, product=settings.kis_prod)
    if not ka._base_headers.get("authorization"):
        _auth_retry_at = time.monotonic() + 60  # KIS 토큰 발급은 분당 1회 제한
        raise KisError(503, "KIS 토큰 발급 실패 — 앱키·시크릿을 확인한다")


def _function(key: str):
    if key not in _functions:
        api = APIS[key]
        path = EXAMPLES / api.category / api.name / f"{api.name}.py"
        spec = importlib.util.spec_from_file_location(f"kis_{api.category}_{api.name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _functions[key] = getattr(module, api.name)
    return _functions[key]


def _to_json(value):
    if hasattr(value, "to_json"):  # DataFrame — NaN은 null로
        return json.loads(value.to_json(orient="records", force_ascii=False))
    if isinstance(value, (tuple, list)):
        return [_to_json(v) for v in value]
    return value


def call(key: str, args: dict) -> dict:
    """샘플 함수를 호출해 {"data", "error"}를 돌려준다. error는 KIS가 돌려준 오류(없으면 None)."""
    start, error = time.monotonic(), None
    try:
        res = _invoke(key, args)
        error = res["error"] and res["error"]["message"]
        return res
    except KisError as e:
        error = e.message
        raise
    finally:
        totals["calls"] += 1
        totals["errors"] += error is not None
        recent.appendleft({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "api": key,  # UTC
            "ms": round((time.monotonic() - start) * 1000), "error": error,
        })


def _invoke(key: str, args: dict) -> dict:
    global _last_error
    api = APIS.get(key)
    if api is None:
        raise KisError(404, f"없는 API: {key}")
    if api.kind == "websocket":
        raise KisError(400, "웹소켓 API는 아직 지원하지 않는다")
    if api.kind == "order" and not settings.kis_allow_order:
        raise KisError(403, "주문 API 차단됨 — kis/.env의 KIS_ALLOW_ORDER=true 로 허용한다")
    by_name = {p["name"]: p for p in api.params}
    unknown = sorted(set(args) - set(by_name))
    if unknown:
        raise KisError(400, f"없는 파라미터: {', '.join(unknown)}")
    kwargs = {k: int(v) if by_name[k]["type"] == "int" else v for k, v in args.items()}
    if "env_dv" in by_name:
        kwargs["env_dv"] = settings.kis_env  # 실전/모의는 서버 설정을 따른다
    missing = [p["name"] for p in api.params if p["required"] and p["name"] not in kwargs]
    if missing:
        raise KisError(400, f"필수 파라미터 누락: {', '.join(missing)}")
    with _lock:
        ka = _kis_auth()
        _ensure_auth(ka)
        _last_error = None
        try:
            data = _function(key)(**kwargs)
        except (ValueError, TypeError) as e:  # 샘플 함수의 인자 검증
            raise KisError(400, str(e))
        return {"data": _to_json(data), "error": _last_error}


def token_expires_at() -> str | None:
    """저장된 토큰의 만료 시각 (토큰 값은 읽지 않는다)."""
    try:
        path = max((HOME / "KIS" / "config").glob(f"KIS*_{settings.svr}"), key=lambda p: p.stat().st_mtime)
        valid = yaml.safe_load(path.read_text(encoding="utf-8"))["valid-date"]
        return valid.isoformat() if valid > datetime.now() else None
    except Exception:
        return None


def catalog() -> list[dict]:
    return [asdict(a) for a in APIS.values()]
