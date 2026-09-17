"""모니 챗봇이 호출 가능한 도구들 — 실데이터 Q&A (OpenAI-compatible function calling).

설계 (2026-06-23 재작성 — 옛 mock/격주 도구 폐기):
- 챗봇 = "현재 LG 데이터 상태를 자연어로 묻는 Q&A 비서".
- 도구는 **결정론 store/aggregate_lg 가 계산한 값을 그대로 인용**한다 (숫자 hallucinate 방지).
- 항상 **최신 스냅샷**(store.latest_stored_period)을 본다. scenario_id/격주 개념 없음.
- CHAT_TOOLS: LLM 에 주는 schema / CHAT_TOOL_FUNCTIONS: name → 실행 함수.
- 확장 쉬움 — 도구 함수 + schema 한 쌍 추가하면 끝.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import aggregate_lg, registry, store


def _lbl(slug: str) -> str:
    """슬러그 → 표시용 한글 라벨 (챗봇 답변은 라벨로 노출)."""
    return registry.label_for(slug)


def _lbls(slugs) -> list:
    return [_lbl(s) for s in (slugs or [])]


def _resolve_area(area: str) -> str:
    """입력(슬러그/한글 라벨/시트명) → 슬러그. 못 찾으면 입력 그대로."""
    if not area:
        return area
    if area in registry.BY_SLUG:
        return area
    if area in registry.SHEET_TO_SLUG:
        return registry.SHEET_TO_SLUG[area]
    for it in registry.ITEMS:
        if it["label"] == area or it["label"] in area or area in it["label"]:
            return it["slug"]
    return area


# ─────────────────────────────────────────────
# 공통 — 최신 스냅샷 집계
# ─────────────────────────────────────────────

def _latest_detail() -> Optional[dict]:
    """최신 스냅샷의 보고서 집계(master_detail) — 항목별 누적/당월 + 전체 요약.
    데이터 없으면 None. 월 = 그 스냅샷의 월(누적=1..M / 당월=M월)."""
    period = store.latest_stored_period()
    if not period:
        return None
    hl = store.load_master_headline(period)
    if hl is None or not len(hl):
        return None
    mo = store.target_month(period)
    d = aggregate_lg.master_detail(
        hl, current_month=mo, all_items=list(registry.REPORT_ITEMS))
    if d and d.get("summary"):
        d["_period"] = period
    return d if d and d.get("summary") else None


# ─────────────────────────────────────────────
# 도구 구현 (정보 조회)
# ─────────────────────────────────────────────

def get_status() -> Dict[str, Any]:
    """제출 현황 — 현재 주차 + 부서별 최신 시점 + 미제출 항목.

    "몇 주차까지 데이터 있어?", "미제출 어디야?", "다 냈어?" 류 질문.
    """
    st = store.latest_status()
    items = [
        {
            "항목": _lbl(it["항목"]),
            "양식": it.get("format"),
            "최신": it.get("latest_label"),
            "제출됨": it.get("received"),
        }
        for it in st.get("items", []) if not it.get("derived")
    ]
    return {
        "현재_주차": st.get("current_label"),
        "현재_월": st.get("current_month"),
        "미제출": _lbls(st.get("missing", [])),
        "미제출_수": len(st.get("missing", [])),
        "전체_항목수": len(items),
        "항목별": items,
    }


def get_achievement(area: Optional[str] = None) -> Dict[str, Any]:
    """실적/달성률 — 목표 대비 실적·차이(남은 금액)·달성률.

    area 지정 시 그 항목만, 없으면 전체 종합(H포함/H제외). "얼마나 남았어?", "달성률?" 류.
    """
    d = _latest_detail()
    if not d:
        return {"error": "적재된 데이터가 없습니다. 먼저 실적 데이터를 업로드해 주세요."}
    if area:
        area = _resolve_area(area)   # 슬러그/라벨/시트명 어떤 형태든 슬러그로 정규화
        it = next((i for i in d.get("items", []) if i["항목"] == area), None)
        if not it:
            return {"error": f"'{_lbl(area)}' 항목을 찾을 수 없습니다."}
        return {"항목": _lbl(area), "누적": it.get("누적"), "당월": it.get("당월")}
    s = d["summary"]
    return {
        "기준_월": d.get("current_month"),
        "전체_누적": s.get("누적_전체"),      # H 포함 (목표/실적/차이/달성률)
        "H제외_누적": s.get("누적"),          # 실질 총합
        "당월": s.get("당월_전체"),
    }


def get_risks() -> Dict[str, Any]:
    """위험/미달 진단 — 목표 미달 영향 큰 항목 + 달성률 최저 항목 top3.

    "위험한 거 뭐야?", "제일 미달인 항목?" 류 질문.
    """
    d = _latest_detail()
    if not d:
        return {"error": "적재된 데이터가 없습니다."}
    s = d["summary"]

    def _label_rows(rows):
        return [{**r, "항목": _lbl(r.get("항목"))} for r in (rows or [])]

    return {
        "미달영향_top3": _label_rows(s.get("shortfall_top3", [])),   # 부족 금액 큰 순
        "달성률최저_top3": _label_rows(s.get("lowest_top3", [])),     # 달성률 낮은 순
    }


# ─────────────────────────────────────────────
# 도구 구현 (UI 액션) — frontend 가 처리할 action 표시
# ─────────────────────────────────────────────

# 살아있는 페이지만 — 실적관리/보고서운영/문서관리/제출관리/홈
_NAV_PATHS = ["/data", "/reports", "/documents", "/inbox", "/"]


def navigate_action(path: str) -> Dict[str, Any]:
    """페이지 이동 — frontend 가 router.push 처리."""
    if path not in _NAV_PATHS:
        return {"error": f"이동할 수 없는 경로: {path}", "valid_paths": _NAV_PATHS}
    return {"_chat_action": {"type": "navigate", "params": {"path": path}}, "ok": True}


def remind_action(area: Optional[str] = None) -> Dict[str, Any]:
    """미제출 항목 독촉 — 미제출 목록 + 실적관리(/data)로 이동(거기서 독촉 발송).

    area 지정 시 그 항목, 없으면 전체 미제출. 실제 발송은 /data 화면에서.
    """
    st = store.latest_status()
    missing = st.get("missing", [])
    targets = [area] if area else missing
    return {
        "미제출": _lbls(missing),
        "독촉_대상": _lbls(targets),
        "안내": "실적 관리 화면에서 해당 항목의 독촉 버튼으로 발송할 수 있습니다.",
        "_chat_action": {"type": "navigate", "params": {"path": "/data"}},
        "ok": True,
    }


# ─────────────────────────────────────────────
# 챗봇 도구 카탈로그 (LLM schema + 실행 매핑)
# ─────────────────────────────────────────────

CHAT_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_status",
            "description": (
                "제출 현황을 조회한다 — 현재 몇 주차까지 데이터가 있는지, 어느 항목이 "
                "미제출인지, 항목별 최신 제출 시점. '몇 주차?', '미제출 어디?', '다 냈어?' 류 질문에 사용."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_achievement",
            "description": (
                "실적/달성률을 조회한다 — 목표 대비 실적, 차이(남은 금액), 달성률. "
                "area 를 주면 그 항목(재료비·가공비·고정비 등)만, 안 주면 전체 종합. "
                "'얼마나 남았어?', '달성률?', '재료비 실적은?' 류 질문에 사용."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": "특정 항목 슬러그 (예: material_cost, fixed_cost). 전체를 원하면 비워둔다.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_risks",
            "description": (
                "위험/미달 항목을 진단한다 — 목표 미달 영향이 큰 항목과 달성률이 가장 낮은 항목 top3. "
                "'위험한 거?', '제일 미달인 항목?', '어디가 문제야?' 류 질문에 사용."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": (
                "특정 페이지로 이동한다. 정보 질문이 아니라 '~로 가줘', '~ 보여줘' 같은 "
                "이동 명령일 때만. (실적 관리=/data, 보고서 운영=/reports, 문서 관리=/documents, "
                "제출 관리=/inbox, 홈=/)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "enum": _NAV_PATHS,
                        "description": "이동할 경로",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remind",
            "description": (
                "미제출 항목에 대한 독촉을 안내한다 — 미제출 목록 + 실적 관리 화면 이동. "
                "'미제출한 데 독촉해줘', '안 낸 데 알려줘' 류 명령에 사용. area 로 특정 항목 지정 가능."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "area": {"type": "string", "description": "특정 항목 (선택)"},
                },
            },
        },
    },
]

CHAT_TOOL_FUNCTIONS: Dict[str, Any] = {
    "get_status": get_status,
    "get_achievement": get_achievement,
    "get_risks": get_risks,
    "navigate": navigate_action,
    "remind": remind_action,
}
