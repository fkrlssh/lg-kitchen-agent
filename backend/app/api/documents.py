"""문서 관리 = 파일 수집 허브 — 분류별 처리.

- 부서 제출(마스터 엑셀): 양식 빡센 검증 → 통과 시 CSV 적재(회차 자동인식) + 원본 보관.
                          양식 아니면 거부(적재 안 함).
- 운영자 원천(각자 양식): 검증 없이 보관만 (추후 어댑터로 CSV 연결).

얇은 라우터 — 저장은 src/docstore.py, 파싱/검증은 src/parsing_lg.py + src/store.py.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src import changelog, docstore, parsing_lg, store

router = APIRouter()


class CompareReq(BaseModel):
    doc_a: str   # 이전 버전 문서 id
    doc_b: str   # 이후 버전 문서 id


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    category: str = Form(docstore.CAT_SOURCE),
    area: Optional[str] = Form(None),  # 지정 시 그 항목만 적재 (부서별 업로드)
):
    data = await file.read()
    fname = file.filename or "file"

    if category == docstore.CAT_DEPT:
        # 부서 제출 = 마스터 엑셀 → 빡센 양식 검증 후 CSV 적재
        if not fname.lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(400, "부서 제출은 엑셀(.xlsx) 파일이어야 합니다")
        verdict = parsing_lg.validate_master_format(data)
        if not verdict["ok"]:
            # 양식 아님 → 거부 (보관도 안 함)
            raise HTTPException(400, verdict["reason"])
        # 항목별 업로드면 그 항목 데이터가 실제로 있는지 확인
        if area:
            try:
                df_chk, _ = parsing_lg.parse_workbook(data)
            except Exception as e:
                raise HTTPException(400, f"양식 구조를 해석할 수 없습니다: {e}")
            if not len(df_chk[df_chk["항목"] == area]):
                raise HTTPException(400, f"이 파일에 '{area}' 데이터가 없습니다. 해당 항목이 기입된 파일을 올려주세요.")
        # 통과 → CSV 적재 (회차 자동 판단, area 지정 시 그 항목만)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            # 회차 추론으로 새 폴더 만들지 않음 — 항상 '현재 상태' 한 폴더에 머지(부서별 폴더 갈림 방지).
            outs, df, _report, used_period = store.save_excel(
                tmp_path, store.current_period(), only_area=area)
        except Exception as e:
            raise HTTPException(400, f"적재 실패: {e}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        # 원본도 보관 — 올린 이름 뭐든 정규화된 이름으로 ({부서}_{주차}_제출.xlsx).
        # 같은 부서·같은 주차를 또 올리면 _v2, _v3 … 으로 버전 보관.
        # 파일명 주차 = submission_filename 이 _area_latest(area, used_period)로 **그 항목 실제
        # 데이터의 주차**(W16)를 읽어 붙임 — 저장 폴더(현재 상태)명이 W18이어도 항목 기준으로 정확.
        if area:
            base = store.submission_filename(area, used_period)
            # 버전 카운트 = 같은 항목 + 같은 회차(차수)의 기존 제출 수.
            # 주차 라벨 substring 으로 세면 다른 회차의 같은 주차 파일까지 잡히므로 period_id 로 한정.
            prev = sum(1 for d in docstore.list_docs()
                       if d.get("area") == area and d.get("period_id") == used_period)
            clean = base if prev == 0 else base.replace("_제출.xlsx", f"_제출_v{prev + 1}.xlsx")
        else:
            clean = fname
        rec = docstore.save(data, clean, category=category, period_id=used_period, area=area)
        rec["ingested"] = True
        rec["period_id"] = used_period
        rec["area"] = area
        rec["saved_items"] = [p.stem for p in outs]
        rec["rows"] = int(len(df))
        # 버전업 자동 변경 추적 — 직전 동일 항목 버전과 비교해 피드에 기록
        if area:
            try:
                chg = changelog.record_on_upload(area, data, rec)
                if chg:
                    rec["change"] = chg["summary"]
            except Exception:
                pass
        return rec

    # 운영자 원천 등 = 보관만
    rec = docstore.save(data, fname, category=category)
    rec["ingested"] = False
    return rec


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    area: Optional[str] = Form(None),
):
    """부서 제출 파일 미리보기 — 양식 검증 + 적재 시 요약(저장 안 함)."""
    data = await file.read()
    fname = file.filename or "file"
    if not fname.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "엑셀(.xlsx) 파일이어야 합니다")
    verdict = parsing_lg.validate_master_format(data)
    if not verdict["ok"]:
        raise HTTPException(400, verdict["reason"])
    if area:
        df_chk, _ = parsing_lg.parse_workbook(data)
        if not len(df_chk[df_chk["항목"] == area]):
            raise HTTPException(400, f"이 파일에 '{area}' 데이터가 없습니다. 해당 항목이 기입된 파일을 올려주세요.")
    return store.preview_excel(data, only_area=area)


@router.get("")
async def list_documents():
    return {"documents": docstore.list_docs(), "categories": docstore.CATEGORIES}


@router.get("/changelog")
async def changelog_feed(limit: int = Query(100, ge=1, le=300)):
    """버전업 자동 변경 피드 — 최신순 (업로드 때마다 직전 대비 diff 누적)."""
    return {"feed": changelog.load_feed(limit)}


@router.get("/versions")
async def versions():
    """항목별 업로드 버전 목록 — 수동 비교 드롭다운용."""
    return {"versions": changelog.versions_by_area()}


@router.post("/compare")
async def compare(req: CompareReq):
    """두 버전 정밀 비교 — 셀 단위 변경/추가/삭제 (A=이전, B=이후)."""
    return changelog.diff_docs(req.doc_a, req.doc_b)


@router.get("/timeline")
async def timeline(area: Optional[str] = Query(None)):
    """최신 기준 변동 이력 — 항목별, 버전 체인 따라 변동된 셀의 최초→현재 + 변동 시점."""
    return {"timeline": changelog.revision_timeline(area)}


@router.get("/{doc_id}/download")
async def download(doc_id: str):
    rec = docstore.get(doc_id)
    p = docstore.path_of(doc_id)
    if not rec or not p:
        raise HTTPException(404, "문서 없음")
    return FileResponse(p, filename=rec["filename"])


@router.delete("/{doc_id}")
async def delete(doc_id: str):
    rec = docstore.get(doc_id)
    if not rec:
        raise HTTPException(404, "문서 없음")
    area = rec.get("area")
    pid = rec.get("period_id")
    if not docstore.delete(doc_id):
        raise HTTPException(404, "문서 없음")
    # 그 버전의 사이드카 캐시 + 변동이력 정리
    changelog.forget_doc(doc_id)

    # 부서 제출본(적재된 항목)이면 보고서 데이터도 함께 정리 —
    # 같은 (항목·회차)의 남은 최신 버전으로 재적재(되돌림), 없으면 항목 완전 제거(미수신).
    # ⚠️ **동기로** 처리(응답 전 반영 완료). 백그라운드로 돌리면 여러 버전 연속 삭제 시
    #   '복원' 태스크가 'remove' 뒤에 늦게 실행돼 지운 데이터를 되살리는 레이스 발생 → 동기 필수.
    #   remove_area=빠름(JSON만), revert=수 초(수식 재평가) — 정확성 우선.
    reverted = None
    removed = False
    if area and pid:
        remaining = [d for d in docstore.list_docs()
                     if d.get("area") == area and d.get("period_id") == pid]
        if remaining:
            latest = max(remaining, key=lambda d: d.get("uploaded_at", ""))
            p = docstore.path_of(latest["id"])
            if p:
                try:
                    store.save_excel(p.read_bytes(), pid, only_area=area, log=False)
                    reverted = latest["filename"]
                except Exception as e:
                    raise HTTPException(500, f"이전 버전 복원 실패: {e}")
        else:
            store.remove_area(pid, area)
            removed = True
    return {"status": "deleted", "id": doc_id, "area": area,
            "reverted_to": reverted, "removed": removed,
            "processing": False}
