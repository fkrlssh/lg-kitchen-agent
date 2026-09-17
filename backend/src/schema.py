"""공통 스키마 / 상수.

요구사항 이미지 (docs/requirements/01_early-sensing-agent-overview.png) 기반.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

# 7개 비용 카테고리 × 각 카테고리를 담당하는 부서 목록
CATEGORIES: Dict[str, List[str]] = {
    "가공비": ["생산개선Tag팀", "시스템개선팀", "구매팀", "시스템화VI팀", "원가혁신IUT팀"],
    "재료비": ["시스템개선팀", "설비기획팀"],
    "고정비": ["경영관리팀", "설비기획팀", "생산기술팀", "금형개발팀", "연구개발관리팀", "외주관리팀"],
    "투자비": ["외주관리팀"],
    "품질개선": ["고객품질개선팀", "HSES팀", "한국영업지원팀"],
    "물류비": ["국내물류팀", "외주관리팀"],
    "매출비": ["HS물류개선팀", "H제재관리팀", "키친배외영업실"],
}

CATEGORY_ORDER: List[str] = list(CATEGORIES.keys())

# 표준 엑셀 컬럼 (각 부서가 회신하는 양식 — PoC에서는 통일된 양식으로 가정)
EXCEL_COLUMNS = ["부서", "세부항목", "목표(억원)", "실적(억원)", "비고"]


@dataclass
class Threshold:
    """이상 감지 임계값. 운영 단계에서 LG 협의로 조정."""

    warn_pct: float = 90.0   # 달성률 < 90% → 경고
    danger_pct: float = 80.0  # 달성률 < 80% → 위험


DEFAULT_THRESHOLD = Threshold()


def status_for(achievement_pct: float, t: Threshold = DEFAULT_THRESHOLD) -> str:
    """달성률(%) → '정상' / '경고' / '위험'."""
    if achievement_pct < t.danger_pct:
        return "위험"
    if achievement_pct < t.warn_pct:
        return "경고"
    return "정상"
