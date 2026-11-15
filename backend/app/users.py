"""predict-market 사용자 프로필 조회와 탈퇴 사용자 정리.

users는 predict-market이 소유한다 — DB에 접근하지 않고 내부 API(GET /api/internal/users)로 받는다 (AUTH.md).
"""

import logging

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Account

log = logging.getLogger(__name__)

CHUNK = 200  # 요청당 id 수 (predict-market 상한 500)

client = httpx.AsyncClient(
    base_url=settings.predict_api_url,
    timeout=5,
    headers={"Authorization": f"Bearer {settings.internal_api_token}"},
)


async def fetch_users(ids: list[int]) -> dict[int, dict]:
    """id → 프로필. 응답에 없는 id는 삭제된 사용자. 실패하면 httpx.HTTPError."""
    result: dict[int, dict] = {}
    for i in range(0, len(ids), CHUNK):
        res = await client.get("/api/internal/users", params={"ids": ",".join(map(str, ids[i : i + CHUNK]))})
        res.raise_for_status()
        result.update({u["id"]: u for u in res.json()})
    return result


async def purge_deleted_users(session: AsyncSession) -> None:
    """predict-market에서 삭제된(탈퇴·게스트 병합) 사용자의 계좌를 지운다 — 보유·거래·스냅샷은 CASCADE.

    API 설정이 잘못돼(다른 서버 등) 전원이 없어 보이면 모두 지워지므로, 절반 넘게 없으면 지우지 않고 경고만 남긴다.
    """
    ids = list(await session.scalars(select(Account.user_id).distinct()))
    existing = await fetch_users(ids)
    missing = [i for i in ids if i not in existing]
    if len(missing) > 5 and len(missing) * 2 > len(ids):
        log.warning("purge skipped: %d/%d account users missing — check PREDICT_API_URL", len(missing), len(ids))
        return
    if missing:
        await session.execute(delete(Account).where(Account.user_id.in_(missing)))
        await session.commit()
        log.info("purged accounts of %d deleted users", len(missing))
