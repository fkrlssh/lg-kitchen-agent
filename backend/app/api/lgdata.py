"""LG 양식 데이터 — 업로드 → CSV 저장 → 조회.

POST /api/lgdata/upload          멀티파트 엑셀 업로드 → parse → CSV 저장
GET  /api/lgdata/periods         저장된 회차 목록
GET  /api/lgdata/{pid}/sources   회차 내 출처(부서) 목록
GET  /api/lgdata/{pid}/rows      raw 행 조회 (필터/페이징) — 웹 표 표시용
DELETE /api/lgdata/{pid}/sources/{name}   특정 출처 삭제

얇은 라우터 — 실제 저장/파싱 로직은 src/store.py + src/parsing_lg.py.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from src import aggregate_lg, changelog, registry, store

router = APIRouter()


class RemindRequest(BaseModel):
    keys: Optional[List[str]] = None  # 빠진 조각 key 목록('{area}:{종류}:{월}'). 비우면 미요청 조각 전체


def _reminder_draft(period_id: str, area: str, pieces: List[str]) -> dict:
    """항목별 독촉 메일 초안 — 요청하는 빠진 조각(예 '3월 월계','4월 2~5차')을 본문에 명시."""
    label = registry.label_for(area)   # 화면/메일엔 한글 라벨(area=슬러그)
    items_txt = ", ".join(pieces)
    subject = f"[경영성과 모니터링] {period_id} '{label}' 미제출 데이터 요청"
    body = (
        "안녕하세요.\n\n"
        f"{period_id} 회차 경영성과 데이터 취합 관련 안내드립니다.\n"
        f"'{label}'의 다음 데이터가 아직 제출되지 않았습니다: {items_txt}\n"
        "확인 후 회신(엑셀 첨부)으로 제출 부탁드립니다.\n\n"
        "감사합니다.\n챗봇 자동 안내"
    )
    return {"항목": area, "label": label, "pieces": pieces, "to": f"{label} 담당 부서",
            "subject": subject, "body": body}


def _json_safe(df: pd.DataFrame) -> List[dict]:
    """NaN → None (FastAPI strict JSON 거부 방지)."""
    return df.astype(object).where(pd.notna(df), None).to_dict(orient="records")


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    period_id: Optional[str] = Form(None),
):
    """LG 통합 워크북 업로드 → 파싱 → 회차 폴더에 **항목별** CSV 분할 저장.

    period_id 를 비우면 파일 내용(실적이 어디까지 찼는지)으로 **회차 자동 판단**.
    """
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "xlsx 파일만 업로드 가능합니다")

    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        # period_id 명시 없으면 '현재 상태' 한 폴더에 머지(매번 새 회차 폴더 추론 안 함).
        outs, df, report, used_period = store.save_excel(tmp_path, period_id or store.current_period())
    except Exception as e:  # 파싱 실패 → 400 으로 사유 반환
        raise HTTPException(400, f"파싱 실패: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    parsed = {k: v for k, v in report.items() if v.get("status") == "ok"}
    skipped = [k for k, v in report.items() if v.get("status") == "skip"]
    return {
        "period_id": used_period,
        "auto_detected": not period_id,
        "saved_items": [p.stem for p in outs],
        "rows": int(len(df)),
        "parsed_sheets": parsed,
        "skipped_sheets": skipped,
    }


@router.get("/registry")
async def registry_items():
    """항목 레지스트리 — 슬러그→한글 라벨/양식종류/단위/파생. 프론트 표시명 매핑용."""
    return {
        "items": [
            {"slug": it["slug"], "label": it["label"], "source": it["source"],
             "unit": it["unit"], "derived": it["source"] == "파생",
             "format": store.area_format(it["source"]),
             "derived_from": it.get("derived_from", [])}
            for it in registry.ITEMS
        ],
        "expected": list(registry.EXPECTED_SLUGS),
        "derived": registry.DERIVED_SLUG,
    }


@router.get("/periods")
async def periods():
    # latest_month/year = **데이터 기준**(폴더 이름 아님) → 월이 진행돼도 드롭다운이 따라감.
    # present_weeks = 월별 실제 데이터가 있는 ISO 주차(config 고정 차수 아님) → 드롭다운이 데이터에 있는
    #   주차만·최신까지만 보여주게(phantom 미래 주차 W20~ 선택 방지, 경계주 5월 W18도 포함).
    return {
        "periods": store.list_stored_periods(),
        "latest_month": store.data_current_month(),
        "present_weeks": store.present_weeks_by_month(),
        "year": str(store.data_year()),
    }


@router.get("/status")
async def status():
    """부서별 '최신 주차' 상태 — 실적 관리 화면용. 현재 주차/미제출/부서별 최신."""
    return store.latest_status()


@router.get("/{period_id}/sources")
async def sources(period_id: str):
    return {"period_id": period_id, "sources": store.list_sources(period_id)}


@router.delete("/{period_id}/sources/{source_name}")
async def delete_source(period_id: str, source_name: str):
    if not store.delete_source(period_id, source_name):
        raise HTTPException(404, "해당 출처 없음")
    return {"status": "deleted", "period_id": period_id, "source": source_name}


@router.get("/{period_id}/rows")
async def rows(
    period_id: str,
    항목: Optional[str] = Query(None),
    부서: Optional[str] = Query(None),
    월: Optional[int] = Query(None),
    종류: Optional[str] = Query(None),
    구분: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=2000),
):
    """raw 행 조회 — 항목/부서/월/종류/구분 필터 + 페이징. 웹 표 표시용."""
    df = store.load_period(period_id)
    total_all = len(df)
    if 항목:
        df = df[df["항목"] == 항목]
    if 부서:
        df = df[df["부서경로"].astype(str).str.contains(부서, na=False)]
    if 월 is not None:
        df = df[df["월"] == 월]
    if 종류:
        df = df[df["종류"] == 종류]
    if 구분:
        df = df[df["구분"] == 구분]
    total = len(df)
    page = df.iloc[offset:offset + limit]
    return {
        "period_id": period_id,
        "total_all": total_all,
        "total_filtered": total,
        "offset": offset,
        "limit": limit,
        "columns": list(df.columns),
        "rows": _json_safe(page),
    }


@router.get("/{period_id}/items")
async def items(period_id: str):
    """집계 가능한 항목(시트) + 연도 목록 — 피벗 화면 셀렉터용."""
    df = store.load_period(period_id)
    years: List[int] = []
    if len(df) and "연도" in df.columns:
        years = sorted(int(y) for y in df["연도"].dropna().unique())
    return {
        "period_id": period_id,
        "items": aggregate_lg.list_items(df),
        "years": years,
    }


@router.get("/{period_id}/pivot")
async def pivot(
    period_id: str,
    항목: str = Query(...),
    연도: Optional[int] = Query(None),
):
    """항목 1개 → 부서경로(행) × 월 [목표/실적/달성률] 매트릭스. 즉석 계산."""
    df = aggregate_lg.clip_future(store.load_period(period_id), period_id)
    return aggregate_lg.pivot_achievement(df, 항목, 연도)


@router.get("/{period_id}/overview")
async def overview(
    period_id: str,
    연도: Optional[int] = Query(None),
):
    """전 항목 한눈에 — 항목(행) × 월 [목표/실적/달성률] + 항목별 종합."""
    df = aggregate_lg.clip_future(store.load_period(period_id), period_id)
    return aggregate_lg.overview(df, 연도)


@router.get("/{period_id}/master")
async def master(period_id: str):
    """Master 재현 — Area 대표총계(headline) 기반 항목×월 + 합계(H제외).

    leaf 합산 아님(혼합지표 부풀림 방지). Master 수식이 지정한 대표행을 ingest 때
    저장해 둔 headline 으로 집계. **스냅샷 회차 이후 미래월은 제거**(5월 1차 스냅샷에
    6월 값이 보이지 않게 — overview/pivot 의 clip_future 와 동일 원칙).
    """
    hl = store.load_master_headline(period_id)
    # 회차(YYYY-MM-N)의 월 이후 미래월 제거. headline 은 당해(26) 기준이라 월로만 컷.
    parts = str(period_id).split("-")
    if len(parts) >= 2 and parts[1].isdigit() and len(hl):
        hl = hl[hl["월"] <= int(parts[1])]
    return aggregate_lg.overview_master(hl)


@router.get("/{period_id}/consistency")
async def consistency(period_id: str, prev: Optional[str] = Query(None)):
    """정합성 검증 — 직전 회차 대비 과거 실적이 바뀌었는지.

    prev 미지정 시 저장된 회차 중 바로 직전 회차와 비교.
    겹치는 과거 실적 셀 중 값이 달라진 것(=확정값 변경) + 삭제된 것 보고.
    """
    base = prev or store.previous_period(period_id)
    if not base:
        return {"prev": None, "curr": period_id, "compared": 0,
                "changed": [], "removed": [], "no_previous": True}
    return store.compare_periods(base, period_id)


def _sim_picks(sim: Optional[str]) -> dict:
    """sim 쿼리 → {항목: {'doc':문서id|None, 'pieces':조각key set|None}}.

    토큰 형식: 'area'(최신본·전체) / 'area@docid'(그 버전·전체) /
    'area@docid~k1.k2'(그 버전 + 선택 조각만, k='m{월}'마감|'w{ISO}'차). 빈 값=변경 미적용.
    """
    picks: dict = {}
    for tok in (sim or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        pieces = None
        if "~" in tok:
            tok, ps = tok.split("~", 1)
            pieces = {x for x in ps.split(".") if x}
        if "@" in tok:
            a, d = tok.split("@", 1)
            doc = d or None
        else:
            a, doc = tok, None
        picks[a] = {"doc": doc, "pieces": pieces}
    return picks


@router.get("/{period_id}/master/detail")
async def master_detail(period_id: str, sim: Optional[str] = Query(None)):
    """보고서 운영용 — 항목별 월/주차 상세 + 누적/당월 요약 + 그래프 데이터.

    월 네비게이션: period_id 의 월(M)이 당월. 누적=1..M, 당월=M월(그 달 주차).
    **sim**(쉼표구분 항목들) 지정 시 그 항목만 변경적용본으로 조립(시뮬레이션 = 항목별 델타).
    """
    cur = store.latest_stored_period() or period_id
    hl = changelog.compose_headline(cur, _sim_picks(sim))
    hl = store.mask_headline_to_present(hl, cur)   # phantom 주차(빈 템플릿 0 컬럼) 제거 → 잠정/집계 정합
    cur_mo = store.target_month(period_id)
    # 월+주차 시점(2026-MM-N): 그 달 월계를 N차 누적값으로 → 차트·요약카드도 그 시점 기준.
    hl = store.trim_headline_to_period(hl, cur_mo, store.target_week(period_id))
    # 보고서 라인아이템 = REPORT_ITEMS(8: 7개 + 고정비 롤업). 고정비 하위 4종은 보고서에
    # 따로 안 띄움(상단 항목별 현황 칩 = 11개 제출항목은 별도 status 로 표시).
    return aggregate_lg.master_detail(
        hl, current_month=cur_mo, all_items=list(registry.REPORT_ITEMS))


@router.get("/{period_id}/master/table")
async def master_table(period_id: str, sim: Optional[str] = Query(None)):
    """Master 시트 재현 — 계층 × 목표·실적·달성률 × 월. 월+주차 시점 트림(2026-MM-N → 연초~M월 N차 누적).
    sim 지정 시 그 항목만 변경적용본으로 조립(합계행 재합산)."""
    cur = store.latest_stored_period() or period_id
    sel = _sim_picks(sim)
    cur_mo, tw = store.target_month(period_id), store.target_week(period_id)
    mt = changelog.compose_master_table(cur, sel)
    mt = store.mask_table_to_present(mt, cur)         # phantom 주차 제거 + 데이터 없는 월 실적 공란
    mt = store.trim_table_to_period(mt, cur_mo, tw)
    mt = store.fix_prov_current(mt, is_master=True)   # 당월 잠정: 항목(L0) 행 정합(마지막 실제 주차값)
    mt = store.ensure_report_items(mt)                # 데이터 없는 항목도 공란 L0행으로(카드와 정합)
    # 합계행 = 카드/그래프(master_detail, =엑셀 합계 canonical)와 동일값으로 (월형 sub 누락 교정·단일 진실원천)
    hl = store.mask_headline_to_present(changelog.compose_headline(cur, sel), cur)
    hl = store.trim_headline_to_period(hl, cur_mo, tw)
    detail = aggregate_lg.master_detail(hl, current_month=cur_mo, all_items=list(registry.REPORT_ITEMS))
    return store.sync_bold_to_detail(mt, detail)


@router.get("/{period_id}/area/{area}/table")
async def area_table(period_id: str, area: str, sim: Optional[str] = Query(None)):
    """개별 Area 시트 **엑셀 그대로** 재현 — 합계/소계/Rate 포함. 월+주차 시점 트림.
    sim 에 이 area 가 있으면 변경적용본, 아니면 현재(개별 표는 항목 독립이라 그 항목만 봄)."""
    cur = store.latest_stored_period() or period_id
    t = changelog.compose_area_table(cur, area, _sim_picks(sim))
    t = store.mask_table_to_present(t, cur, area=area)   # phantom 주차 제거(이 항목 기준)
    t = store.trim_table_to_period(t, store.target_month(period_id), store.target_week(period_id))
    return store.fix_prov_current(t, is_master=False)   # 당월 잠정 정합


@router.get("/{period_id}/simulate")
async def simulate(period_id: str):
    """[프로토타입] 변경 데이터 시뮬레이션 — 버전 변경(v1→최신)이 항목 대표총계를 어떻게 바꾸나.

    현재 보고서=최초 제출본(v1) 값 → 변경 전. 최신 버전=변경 후. 누적(≤그 달) 목표/실적/달성률.
    """
    return {"items": changelog.simulate_versions(store.target_month(period_id))}


@router.get("/{period_id}/submission")
async def submission(period_id: str):
    """기대 항목 대비 수신/미수신 — 항목 단위 제출 현황."""
    return store.submission_status(period_id)


@router.post("/{period_id}/remind")
async def remind(period_id: str, req: RemindRequest):
    """빠진 데이터 항목에 요청(독촉) 메일 초안 생성 + 발송 기록 (지금은 시뮬 — SMTP 추후).

    items 비우면 현재 빠진 것(latest_status.missing) 전체. 발송하면 record_remind 로
    항목별 마지막 발송 시각을 남겨 같은 요청 중복 발송을 막는다(데이터 들어오면 자동 해제).
    재발송(다시 보내기)은 같은 항목을 다시 보내며 시각만 갱신.
    """
    st = store.latest_status()
    all_pieces = {g["key"]: g for it in st["items"] if not it["derived"] for g in it.get("gaps", [])}
    keys = req.keys if req.keys else [k for k, g in all_pieces.items() if not g["requested"]]
    keys = [k for k in keys if k in all_pieces]   # 유효한 조각만
    by_area: dict = {}
    for k in keys:
        g = all_pieces[k]
        txt = g["label"]
        if g.get("kind") == "부분" and g.get("leaves"):   # 부분 누락 = 빠진 항목(부서경로) 명시
            lv = g["leaves"]
            more = f" 외 {len(lv) - 3}건" if len(lv) > 3 else ""
            txt = f"{g['label']} ({', '.join(lv[:3])}{more} 실적 누락)"
        by_area.setdefault(k.split(":")[0], []).append(txt)
    drafts = [_reminder_draft(period_id, a, labels) for a, labels in by_area.items()]
    if keys:
        store.record_remind(period_id, keys)
    return {"period_id": period_id, "sent": len(keys), "drafts": drafts}
