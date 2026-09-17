"""격주 정의 — datetime 기반 동적 생성.

매월 1~14일 = N월 1차, 15~말일 = N월 2차.

오늘 (date.today()) 기준 **최근 6개 격주** 자동 생성. 시간이 지나서 다음 격주가
시작되면 자동으로 list 가 밀림 (6월 1차 시작 시 → 6월 1차가 이번 격주, 3월 1차 밀려남).

mock anomalies/missing 패턴은 offset (현재로부터 거리) 별로 고정:
- offset 0  (이번 격주)         → severe + 미회신 다수
- offset -1                      → anomaly (위험 + 미회신)
- offset -2                      → mild (경고만)
- offset -3                      → mild
- offset -4                      → mild
- offset -5 (가장 오래된)        → normal
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Tuple


@dataclass
class Period:
    id: str
    label: str
    start_date: str
    deadline: str
    pattern: str
    anomalies: List[Tuple[str, str, str, float]] = field(default_factory=list)
    missing: List[Tuple[str, str]] = field(default_factory=list)
    is_current: bool = False


# ─────────────────────────────────────────────
# 격주 산식
# ─────────────────────────────────────────────


def _period_of(d: date) -> Tuple[int, int, int]:
    """date → (year, month, week_within_month). week=1 (1~14일) | 2 (15~말일)."""
    week = 1 if d.day <= 14 else 2
    return d.year, d.month, week


def _period_id(year: int, month: int, week: int) -> str:
    return f"{year}-{month:02d}-{week}"


def _period_label(year: int, month: int, week: int, is_current: bool = False) -> str:
    suffix = " (이번 격주)" if is_current else ""
    return f"{year}년 {month}월 {week}차{suffix}"


def _period_dates(year: int, month: int, week: int) -> Tuple[str, str]:
    """격주의 (시작일, 마감일) ISO 문자열."""
    if week == 1:
        start = date(year, month, 1)
        end = date(year, month, 14)
    else:
        start = date(year, month, 15)
        # 다음 달 첫날 - 1 일
        if month == 12:
            next_first = date(year + 1, 1, 1)
        else:
            next_first = date(year, month + 1, 1)
        end = next_first - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _prev_period(year: int, month: int, week: int) -> Tuple[int, int, int]:
    if week == 2:
        return year, month, 1
    if month == 1:
        return year - 1, 12, 2
    return year, month - 1, 2


# ─────────────────────────────────────────────
# Mock anomalies/missing 패턴 — offset 별 고정
# ─────────────────────────────────────────────

_PATTERN_BY_OFFSET = {
    -5: ("normal", [], []),
    -4: ("mild", [
        ("품질개선", "HSES팀", "공정 품질", 0.86),
    ], []),
    -3: ("mild", [
        ("품질개선", "HSES팀", "공정 품질", 0.82),
        ("가공비", "구매팀", "불량 감축", 0.89),
    ], []),
    -2: ("mild", [
        ("품질개선", "HSES팀", "공정 품질", 0.78),
        ("가공비", "구매팀", "불량 감축", 0.87),
        ("물류비", "외주관리팀", "국내 운송", 0.87),
    ], [
        ("매출비", "키친배외영업실"),
    ]),
    -1: ("anomaly", [
        ("재료비", "시스템개선팀", "원자재 단가", 0.72),
        ("품질개선", "HSES팀", "공정 품질", 0.65),
        ("물류비", "외주관리팀", "국내 운송", 0.83),
        ("가공비", "구매팀", "불량 감축", 0.87),
        ("고정비", "금형개발팀", "유지보수", 0.78),
    ], [
        ("고정비", "연구개발관리팀"),
        ("매출비", "키친배외영업실"),
    ]),
    0: ("severe", [
        ("재료비", "시스템개선팀", "원자재 단가", 0.68),
        ("재료비", "설비기획팀", "포장재 최적화", 0.74),
        ("품질개선", "HSES팀", "공정 품질", 0.62),
        ("가공비", "구매팀", "불량 감축", 0.79),
        ("고정비", "금형개발팀", "유지보수", 0.76),
        ("물류비", "외주관리팀", "국내 운송", 0.81),
    ], [
        ("고정비", "연구개발관리팀"),
        ("매출비", "키친배외영업실"),
        ("투자비", "외주관리팀"),
    ]),
}

_NUM_PERIODS = 6  # 최근 6개 격주


def _generate_periods(today: date | None = None) -> List[Period]:
    if today is None:
        today = date.today()
    cur = _period_of(today)
    periods: List[Period] = []
    # offset = -5..0
    chain: List[Tuple[int, int, int]] = [cur]
    while len(chain) < _NUM_PERIODS:
        chain.append(_prev_period(*chain[-1]))
    chain.reverse()  # 가장 오래된 게 앞

    for i, (y, m, w) in enumerate(chain):
        offset = -(_NUM_PERIODS - 1 - i)  # i=0 → offset=-5, i=5 → 0
        pattern, anomalies, missing = _PATTERN_BY_OFFSET.get(offset, ("normal", [], []))
        is_current = offset == 0
        start, deadline = _period_dates(y, m, w)
        periods.append(Period(
            id=_period_id(y, m, w),
            label=_period_label(y, m, w, is_current=is_current),
            start_date=start,
            deadline=deadline,
            pattern=pattern,
            anomalies=anomalies,
            missing=missing,
            is_current=is_current,
        ))
    return periods


# 모듈 로드 시 한 번 생성. backend restart 시 갱신.
PERIODS: List[Period] = _generate_periods()


def list_periods() -> List[Period]:
    return PERIODS


def get_period(period_id: str) -> Period | None:
    for p in PERIODS:
        if p.id == period_id:
            return p
    return None


def current_period() -> Period:
    for p in PERIODS:
        if p.is_current:
            return p
    return PERIODS[-1]


# ─────────────────────────────────────────────
# Period 수신 상태 — in-memory (시연용)
# ─────────────────────────────────────────────


_FETCHED_PERIODS: set[str] = {p.id for p in PERIODS if not p.is_current}
# 처음엔 이번 격주 외에는 모두 수신 완료. 이번 격주만 미수신.


def is_fetched(period_id: str) -> bool:
    return period_id in _FETCHED_PERIODS


def mark_fetched(period_id: str) -> None:
    _FETCHED_PERIODS.add(period_id)


def reset_fetch_state() -> None:
    """데모 리셋 — 이번 격주 다시 비어있음으로."""
    global _FETCHED_PERIODS
    _FETCHED_PERIODS = {p.id for p in PERIODS if not p.is_current}
