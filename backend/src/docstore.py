"""문서 보관소 — 만회 대책 등 일반 문서 업로드/조회/다운로드.

실적 데이터(엑셀→CSV, store.py)와 별개. 여기는 보고/대책 문서 등 첨부 파일을 그대로 보관.
- 파일 = backend/documents/{id}__{원본파일명}
- 메타 = backend/documents/_index.json (id/파일명/분류/크기/회차/업로드시각)
documents/ 는 .gitignore (실문서 GitHub 비노출).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
DOC_DIR = BACKEND_DIR / "documents"
INDEX = DOC_DIR / "_index.json"

# 분류 — 부서 제출(마스터 엑셀)은 실적 관리에서 업로드·적재 → docstore 에 원본 보관.
#  문서 관리 = 그 업로드 원본들을 리스트로 열람(다운로드/삭제). 별도 업로드 분류는 안 씀.
CAT_DEPT = "부서 제출"
CAT_SOURCE = "운영자 원천"
CATEGORIES = [CAT_DEPT, CAT_SOURCE]


def _load_index() -> List[dict]:
    if INDEX.exists():
        try:
            return json.loads(INDEX.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_index(items: List[dict]) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe(name: str) -> str:
    return re.sub(r"[^\w가-힣.\-]+", "_", name).strip("_") or "file"


def save(data: bytes, filename: str, category: str = "기타",
         period_id: Optional[str] = None, area: Optional[str] = None) -> dict:
    """문서 저장 → 메타 반환. area = 항목(부서)별 업로드 시 그 항목."""
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    doc_id = uuid.uuid4().hex[:12]
    safe_name = _safe(filename)
    path = DOC_DIR / f"{doc_id}__{safe_name}"
    path.write_bytes(data)
    rec = {
        "id": doc_id,
        "filename": filename,
        "stored": path.name,
        "category": category or "기타",
        "period_id": period_id,
        "area": area,
        "size": len(data),
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    items = _load_index()
    items.append(rec)
    _save_index(items)
    return rec


def list_docs() -> List[dict]:
    """업로드 최신순."""
    return sorted(_load_index(), key=lambda r: r.get("uploaded_at", ""), reverse=True)


def get(doc_id: str) -> Optional[dict]:
    return next((r for r in _load_index() if r["id"] == doc_id), None)


def path_of(doc_id: str) -> Optional[Path]:
    rec = get(doc_id)
    if not rec:
        return None
    p = DOC_DIR / rec["stored"]
    return p if p.exists() else None


def delete(doc_id: str) -> bool:
    items = _load_index()
    rec = next((r for r in items if r["id"] == doc_id), None)
    if not rec:
        return False
    (DOC_DIR / rec["stored"]).unlink(missing_ok=True)
    _save_index([r for r in items if r["id"] != doc_id])
    return True
