"""항목 레지스트리 — 시스템 전체의 단일 진실원천(single source of truth).

LG 양식이 ver0.1(2026-06-24 '주차추가')부터 시트 이름을 **실제 한글 항목명**으로
공유함(이전엔 익명 `Area_A~L`). 이름이 또 바뀔 수 있으므로 **여기 한 곳**에서만
"시트명 ↔ 내부 슬러그 ↔ 표시명 ↔ 메타"를 정의한다. 코드 나머지는 전부 **슬러그**로
항목을 식별한다(파일명·URL·CSV 키 안전 = ASCII). 화면/보고서는 `label`(한글) 사용.

LG 가 시트명을 또 바꾸면 → 이 파일의 `sheet` 값만 고치면 됨(코드 무변경).

필드:
  slug        : 내부 id (ASCII, 파일명/URL/CSV 키). 절대 안 바뀜.
  sheet       : 엑셀 시트 이름 (LG 양식 = 진실). 양식 바뀌면 여기만 수정.
  label       : 화면/보고서 표시용 한글명.
  source      : 양식 종류 — '부서'(표준양식) / '운영자'(별도양식) / '파생'(다른 항목 합).
                ⚠️ 둘 다 부서가 메일로 보내고 운영자가 업로드 → 전부 제출/독촉 대상.
                  차이는 '양식 종류'뿐. '파생'만 제출 대상 아님(재계산).
  unit        : 관리 단위 — '주차'(월+W# 세분) / '월'(월 단위만).
  derived_from: 파생 항목이 합산하는 하위 슬러그들(파생만).
"""
from __future__ import annotations

from typing import Dict, List, Optional

# 순서 = Master 표시 순서(재료비 → … → 고정비, 그 아래 고정비 하위 4종)
ITEMS: List[dict] = [
    {"slug": "material_cost",     "sheet": "재료비",                  "label": "재료비",                "source": "부서",   "unit": "주차"},
    {"slug": "processing_cost",   "sheet": "가공비",                  "label": "가공비",                "source": "부서",   "unit": "주차"},
    {"slug": "logistics_cost",    "sheet": "물류비",                  "label": "물류비",                "source": "운영자", "unit": "주차"},
    {"slug": "investment",        "sheet": "투자비",                  "label": "투자비",                "source": "부서",   "unit": "주차"},
    {"slug": "sales_region1",     "sheet": "매출_지역1",              "label": "매출(지역1)",           "source": "운영자", "unit": "주차"},
    {"slug": "sales_region2",     "sheet": "매출_지역2",              "label": "매출(지역2)",           "source": "운영자", "unit": "월"},
    {"slug": "quality",           "sheet": "품질",                    "label": "품질",                  "source": "부서",   "unit": "주차"},
    {"slug": "fixed_cost",        "sheet": "고정비",                  "label": "고정비",                "source": "파생",   "unit": "월",
     "derived_from": ["fixed_div_control", "fixed_prod_control", "fixed_uncontrol", "fixed_rawdata"]},
    # 고정비 하위 4종 — 라벨 단축(고정비·접두 + 짧은 구분). 화면 폭/가독성용.
    {"slug": "fixed_div_control", "sheet": "고정비_사업부Control",     "label": "고정비·사업부",          "source": "운영자", "unit": "월"},
    {"slug": "fixed_prod_control","sheet": "고정비_생산,제판법인Control","label": "고정비·생산제판",        "source": "운영자", "unit": "월"},
    {"slug": "fixed_uncontrol",   "sheet": "고정비_UnControl",         "label": "고정비·UnControl",       "source": "운영자", "unit": "월"},
    {"slug": "fixed_rawdata",     "sheet": "고정비_Rawdata",           "label": "고정비·Rawdata",         "source": "부서",   "unit": "월"},
]

# ── 조회 맵 (slug 기준) ──
BY_SLUG: Dict[str, dict] = {it["slug"]: it for it in ITEMS}
SLUGS: List[str] = [it["slug"] for it in ITEMS]
SHEET_TO_SLUG: Dict[str, str] = {it["sheet"]: it["slug"] for it in ITEMS}
SLUG_TO_SHEET: Dict[str, str] = {it["slug"]: it["sheet"] for it in ITEMS}
LABELS: Dict[str, str] = {it["slug"]: it["label"] for it in ITEMS}

# 제출/독촉 대상 = 파생 제외 전 항목
EXPECTED_SLUGS: List[str] = [it["slug"] for it in ITEMS if it["source"] != "파생"]
# 파생 항목 슬러그(보통 1개: fixed_cost). "합계(H제외)" 등에서 제외 대상.
DERIVED_SLUGS: List[str] = [it["slug"] for it in ITEMS if it["source"] == "파생"]
DERIVED_SLUG: Optional[str] = DERIVED_SLUGS[0] if DERIVED_SLUGS else None

# 파생의 구성요소(어떤 derived_from 에 속한 슬러그) — 고정비 하위 4종.
# 이들은 Master 라인아이템이 아니라 고정비(롤업)의 입력 → **보고서엔 별도로 안 띄움**.
COMPONENT_SLUGS: List[str] = sorted({
    c for it in ITEMS for c in it.get("derived_from", [])
})

# 보고서(Master 재현) 라인아이템 = 구성요소 제외 전 항목 (= Master 가 직접 참조하는 것들).
# 7 일반 + 고정비(롤업) = 8. 고정비 하위 4종은 실적/문서관리에만(제출 대상).
REPORT_ITEMS: List[str] = [s for s in SLUGS if s not in COMPONENT_SLUGS]

# 엑셀 시트 이름 집합(파싱 대상 식별용) — 양식 시트만, Master/요약 제외
SHEET_NAMES: List[str] = [it["sheet"] for it in ITEMS]


def slug_for_sheet(sheet: str) -> Optional[str]:
    """엑셀 시트명 → 내부 슬러그. 미등록 시트면 None(=Master/잡시트, 파싱 skip)."""
    return SHEET_TO_SLUG.get(str(sheet).strip())


def sheet_for_slug(slug: str) -> Optional[str]:
    """내부 슬러그 → 엑셀 시트명(워크북 열 때)."""
    return SLUG_TO_SHEET.get(slug)


def label_for(slug: str) -> str:
    """슬러그 → 표시명(한글). 미등록이면 슬러그 그대로."""
    return LABELS.get(slug, slug)


def meta(slug: str) -> dict:
    """슬러그 → 메타(source/unit/derived_from). 미등록이면 빈 dict."""
    return BY_SLUG.get(slug, {})
