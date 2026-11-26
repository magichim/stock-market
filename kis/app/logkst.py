"""로그 시각을 KST(UTC+9 고정)로 찍는 형식 — 서버의 시스템 시간대와 무관하다. uvicorn·앱 로그 모두 log.json(--log-config)이 이 형식을 쓴다."""

import time

from uvicorn.logging import AccessFormatter, DefaultFormatter


def kst_time(t: float) -> time.struct_time:
    return time.gmtime(t + 9 * 3600)


class KstFormatter(DefaultFormatter):
    converter = staticmethod(kst_time)


class KstAccessFormatter(AccessFormatter):
    converter = staticmethod(kst_time)
