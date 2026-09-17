"""버전 간 변경 추적 — 문서(엑셀) 두 벌의 셀 단위 diff + 업로드 자동 기록.

- diff_files: 두 파일(bytes) 파싱 → 같은 항목의 셀 비교 → 변경/추가/삭제.
- record_on_upload: 새 버전 업로드 시 직전 버전과 자동 비교 → changelog 누적(피드용).
- load_feed: 누적된 변경 피드 조회.

비교 키 = (항목·부서경로·연도·월·구분·주차·종류). 값 차이 > eps 면 '변경'.
당해(올해)만 — 전년 실적은 비교 대상 아님(바뀔 일 없음).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd

from . import docstore, parsing_lg, store

_CHANGELOG = docstore.DOC_DIR / "_changelog.json"
_KEYS = store._CMP_KEYS  # ['항목','부서경로','연도','월','구분','주차','종류']
_FEED_CAP = 300          # 피드 최대 보관 (오래된 건 버림)
# 한 업로드에 기록할 행 상한 — 변동 이력(revision_timeline)이 이 changelog 만 집계하므로
# 잘리면 변동이 화면에서 사라진다. per-area 업로드라 한 항목 셀 수(현실적으로 수백) 로
# 이미 제한되니, 실무에선 절대 안 잘릴 만큼 크게 두되 비정상 파일 대비 안전장치만 남김.
_ROW_CAP = 2000
_EPS = 0.01


def _row(key, old, new) -> dict:
    d = dict(zip(_KEYS, key))
    o = None if old is None else float(old)
    n = None if new is None else float(new)
    return {
        "항목": d["항목"], "부서경로": d["부서경로"],
        "연도": int(d["연도"]) if d["연도"] is not None else None,
        "월": int(d["월"]) if d["월"] is not None else None,
        "구분": d.get("구분"), "주차": (d["주차"] or None),
        "종류": d.get("종류"),
        "old": o, "new": n,
        "delta": (n - o) if (o is not None and n is not None) else None,
    }


def _index(df: pd.DataFrame, area: Optional[str]) -> "pd.Series":
    d = df.copy()
    if area:
        d = d[d["항목"] == area]
    if "연도구분" in d.columns:                 # 당해만 — 전년 실적은 변경 대상 아님
        d = d[d["연도구분"] == "당해"]
    for k in _KEYS:
        if k not in d.columns:
            d[k] = None
    d = d.dropna(subset=["값"])
    if not len(d):
        return pd.Series(dtype=float)
    d["주차"] = d["주차"].fillna("")
    s = d.set_index(_KEYS)["값"]
    return s[~s.index.duplicated()]


def diff_dfs(df_old: pd.DataFrame, df_new: pd.DataFrame, area: Optional[str] = None) -> dict:
    ko, kn = _index(df_old, area), _index(df_new, area)
    changed: List[dict] = []
    added: List[dict] = []
    removed: List[dict] = []
    common = ko.index.intersection(kn.index)
    for key in common:
        vo, vn = ko[key], kn[key]
        try:
            if abs(float(vo) - float(vn)) > _EPS:
                changed.append(_row(key, vo, vn))
        except (TypeError, ValueError):
            if vo != vn:
                changed.append(_row(key, vo, vn))
    for key in ko.index.difference(kn.index):
        removed.append(_row(key, ko[key], None))
    for key in kn.index.difference(ko.index):
        added.append(_row(key, None, kn[key]))
    changed.sort(key=lambda r: abs(r.get("delta") or 0), reverse=True)
    return {
        "changed": changed, "added": added, "removed": removed,
        "compared": int(len(common)),
        "summary": {"changed": len(changed), "added": len(added), "removed": len(removed)},
    }


def _parse_bytes(data: bytes) -> Optional[pd.DataFrame]:
    try:
        df, _ = parsing_lg.parse_workbook(data)
        return df
    except Exception:
        return None


def diff_docs(doc_id_a: str, doc_id_b: str) -> dict:
    """저장된 문서 두 벌 비교 (A=이전, B=이후). 같은 항목(area)만."""
    ra, rb = docstore.get(doc_id_a), docstore.get(doc_id_b)
    pa, pb = docstore.path_of(doc_id_a), docstore.path_of(doc_id_b)
    if not (ra and rb and pa and pb):
        return {"error": "문서를 찾을 수 없습니다", "changed": [], "added": [], "removed": []}
    area = ra.get("area") or rb.get("area")
    da, db = _parse_bytes(pa.read_bytes()), _parse_bytes(pb.read_bytes())
    if da is None or db is None:
        return {"error": "파일 파싱 실패", "changed": [], "added": [], "removed": []}
    out = diff_dfs(da, db, area=area)
    out["a"] = {"id": doc_id_a, "filename": ra["filename"], "uploaded_at": ra.get("uploaded_at")}
    out["b"] = {"id": doc_id_b, "filename": rb["filename"], "uploaded_at": rb.get("uploaded_at")}
    out["area"] = area
    return out


def _load() -> List[dict]:
    if not _CHANGELOG.exists():
        return []
    try:
        return json.loads(_CHANGELOG.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: List[dict]) -> None:
    _CHANGELOG.parent.mkdir(parents=True, exist_ok=True)
    _CHANGELOG.write_text(json.dumps(entries[-_FEED_CAP:], ensure_ascii=False, indent=2), encoding="utf-8")


def record_on_upload(area: str, new_bytes: bytes, new_rec: dict) -> Optional[dict]:
    """새 버전 업로드 시 직전 동일 항목 버전과 자동 비교 → 피드에 1건 누적.

    직전 버전 없으면(첫 업로드) None. 변경 0건이어도 기록(이력 추적용).
    """
    prevs = [d for d in docstore.list_docs()
             if d.get("area") == area and d.get("id") != new_rec.get("id")]
    if not prevs:
        return None
    prev = sorted(prevs, key=lambda d: d.get("uploaded_at", ""))[-1]  # 가장 최근 직전본
    pp = docstore.path_of(prev["id"])
    if not pp:
        return None
    d_old, d_new = _parse_bytes(pp.read_bytes()), _parse_bytes(new_bytes)
    if d_old is None or d_new is None:
        return None
    diff = diff_dfs(d_old, d_new, area=area)
    entry = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "항목": area,
        "from": {"id": prev["id"], "filename": prev["filename"], "uploaded_at": prev.get("uploaded_at")},
        "to": {"id": new_rec["id"], "filename": new_rec["filename"], "uploaded_at": new_rec.get("uploaded_at")},
        "summary": diff["summary"],
        "changed": diff["changed"][:_ROW_CAP],   # 변동 이력 완전성 위해 사실상 전부(_ROW_CAP 안전장치)
        "added": diff["added"][:_ROW_CAP],
        "removed": diff["removed"][:_ROW_CAP],
    }
    log = _load()
    log.append(entry)
    _save(log)
    return entry


def load_feed(limit: int = 100) -> List[dict]:
    """변경 피드 — 최신순."""
    return list(reversed(_load()))[:limit]


def _keydict(key) -> dict:
    d = dict(zip(_KEYS, key))
    return {"항목": d["항목"], "부서경로": d["부서경로"],
            "연도": int(d["연도"]) if d["연도"] is not None else None,
            "월": int(d["월"]) if d["월"] is not None else None,
            "구분": d.get("구분"), "주차": (d["주차"] or None), "종류": d.get("종류")}


def _fnum(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _val_changed(vo, vn) -> bool:
    if vo is None or vn is None:
        return vo is not vn and not (vo is None and vn is None)
    try:
        return abs(float(vo) - float(vn)) > _EPS
    except (TypeError, ValueError):
        return vo != vn


def revision_timeline(area: Optional[str] = None, limit_per_area: int = 300) -> List[dict]:
    """최신 기준 변동 이력 — **저장된 changelog(업로드별 diff)를 집계**해 셀별 변동 추적.

    각 셀(항목·부서경로·월·구분·주차·종류)에 대해 최초값→현재(최신)값 + 변동 시점들
    (어느 제출에서 old→new). 한 번이라도 변동된 셀만.
    ⚠️ 버전 엑셀을 재파싱하지 않고 record_on_upload 가 이미 저장한 diff 만 읽어 **빠름**.
    반환: [{항목, versions, cells:[{...key, 최초, 현재, count, events:[{at, version, old, new}]}]}]
    """
    vcount = {a: len(v) for a, v in versions_by_area().items()}
    acc: dict = {}   # area → {key → {events, 최초, 현재}}
    for e in _load():   # changelog 항목들(append=시간순)
        a = e.get("항목")
        if not a or (area and a != area):
            continue
        at = (e.get("to") or {}).get("uploaded_at") or e.get("at")
        ver = (e.get("to") or {}).get("filename", "")
        # added(신규 셀=새 시점/처음 채워진 값)는 '변동' 아님 — 새 데이터 도착이지 기존 값 정정이 아니다.
        # 기존에 있던 셀의 값 정정(changed)·값 소멸(removed)만 변동 이력에 기록. (사용자 요청 2026-07-01)
        for r in (e.get("changed") or []) + (e.get("removed") or []):
            key = (r.get("항목"), r.get("부서경로"), r.get("연도"), r.get("월"),
                   r.get("구분"), (r.get("주차") or None), r.get("종류"))
            cell = acc.setdefault(a, {}).setdefault(key, {"events": [], "최초": r.get("old"), "현재": None})
            cell["events"].append({"at": at, "version": ver, "old": r.get("old"), "new": r.get("new")})
            cell["현재"] = r.get("new")
    out: List[dict] = []
    for a, cells in acc.items():
        cl = [{**_keydict(key), "최초": c["최초"], "현재": c["현재"],
               "count": len(c["events"]), "events": c["events"]} for key, c in cells.items()]
        cl.sort(key=lambda x: (x["count"], abs((x["현재"] or 0) - (x["최초"] or 0))), reverse=True)
        out.append({"항목": a, "versions": vcount.get(a, 1), "cells": cl[:limit_per_area]})
    out.sort(key=lambda t: len(t["cells"]), reverse=True)
    return out


_HEADLINE_DIR = docstore.DOC_DIR / "_headlines"


def _doc_headline(doc_id: str) -> "Optional[pd.DataFrame]":
    """문서(버전) 1벌의 Master 대표총계 headline — 사이드카 캐시(`_headlines/{id}.csv`).

    master_headline 은 워크북 2회 로드+수식평가라 호출당 ~2.5s → 버전별로 한 번만 계산해 저장.
    이후엔 CSV 즉시 읽음(시뮬레이션 빨라짐). 문서 id 는 불변이라 캐시 무효화 불필요.
    """
    f = _HEADLINE_DIR / f"{doc_id}.csv"
    if f.exists():
        try:
            return pd.read_csv(f, encoding="utf-8-sig")
        except Exception:
            pass
    p = docstore.path_of(doc_id)
    if not p:
        return None
    from . import master_lg
    try:
        hl = master_lg.master_headline(p.read_bytes())
    except Exception:
        return None
    _HEADLINE_DIR.mkdir(parents=True, exist_ok=True)
    hl.to_csv(f, index=False, encoding="utf-8-sig")
    return hl


def simulate_versions(current_month: Optional[int] = None) -> List[dict]:
    """[프로토타입] 변경 데이터 시뮬레이션 — 버전 있는 항목의 '변경 전(v1) vs 변경 후(최신)' 대표총계.

    현재 보고서 데이터 = 최초 제출본(v1) 값(v2 는 문서로만 보관·미적재) → v1=변경 전,
    최신 버전=변경 후. 각 항목의 누적(≤current_month) 목표/실적/달성률을 두 시점으로 계산하고,
    실제로 대표총계가 움직인 항목만(변경이 보고서에 닿은 것) + 무엇이 바뀌었는지(셀 목록) 반환.
    """
    out: List[dict] = []
    for area, vers in versions_by_area().items():
        if len(vers) < 2:
            continue
        h1 = _doc_headline(vers[0]["id"])    # 사이드카 캐시 → 두번째부터 즉시
        hN = _doc_headline(vers[-1]["id"])
        if h1 is None or hN is None:
            continue

        def _agg(h) -> dict:
            d = h[(h["항목"] == area) & (h["구분"] == "월계")]
            if current_month:
                d = d[d["월"] <= current_month]
            t = float(d[d["종류"].isin(["목표", "계획"])]["값"].astype(float).sum())
            a = float(d[d["종류"] == "실적"]["값"].astype(float).sum())
            return {"목표": round(t, 2), "실적": round(a, 2),
                    "달성률": round(a / t * 100, 1) if t else None}

        before, after = _agg(h1), _agg(hN)
        # 후보 = 버전(v2) 있는 항목 전부 — 보고서에 안 닿는 변경(before==after)도 후보로 노출(투명).
        changes: List[dict] = []
        for e in reversed(_load()):    # 그 항목 최신 changelog 의 변경 셀
            if e.get("항목") == area:
                for r in (e.get("changed") or []):
                    # 변경 시점 라벨 — 주차 셀이면 'N월 M차', 월계(마감)면 'N월 마감'
                    gubun, ju, wol = r.get("구분"), r.get("주차"), r.get("월")
                    if gubun == "주차" and ju:
                        iso = store._wnum(ju)
                        when = store.week_label(iso) if iso else (f"{wol}월" if wol else "")
                    elif gubun == "월계":
                        when = f"{wol}월 마감" if wol else "마감"
                    else:
                        when = f"{wol}월" if wol else ""
                    changes.append({"부서경로": r.get("부서경로"), "월": wol,
                                    "구분": gubun, "주차": ju, "when": when,
                                    "old": r.get("old"), "new": r.get("new")})
                break
        latest = vers[-1]              # 변경 시점(언제 데이터인지) — 최신 버전의 회차/제출시각
        out.append({"항목": area, "before": before, "after": after, "changes": changes,
                    "pieces": _change_pieces(area),   # 차/마감 조각(칩 단위 선택) — 'm{월}'/'w{ISO}'
                    "period_id": latest.get("period_id"), "at": latest.get("uploaded_at"),
                    "versions": [{"id": v["id"], "label": v.get("filename"), "at": v.get("uploaded_at")}
                                 for v in vers]})   # 적용 버전 선택용(오래된→최신)
    return out


def versions_by_area() -> dict:
    """항목별 업로드 버전 목록 — 수동 비교 드롭다운용. {area: [{id,filename,uploaded_at,period_id}...]}."""
    out: dict = {}
    for d in docstore.list_docs():
        a = d.get("area")
        if not a:
            continue
        out.setdefault(a, []).append({
            "id": d["id"], "filename": d["filename"],
            "uploaded_at": d.get("uploaded_at"), "period_id": d.get("period_id"),
        })
    for a in out:
        out[a].sort(key=lambda x: x.get("uploaded_at") or "")
    return out


# ─────────────────────────────────────────────
# 변경 시뮬레이션 — 실사용 배선: 각 항목의 '실제 최신 문서(개별 파일)'에서 변경 반영
#   원리: 보고서는 항목들의 합 + 변경은 보통 닫힌(지난) 달에 일어남. 그래서 현재 스냅샷에서
#   **선택 항목의 '바뀐 달' 셀만 그 항목 최신 문서값으로 갈아끼우고** 합계만 다시 더하면,
#   합본 스냅샷 없이도 항목마다 제 파일에서 자동 반영됨. (현재월=마감lag 잠정이라 안 건드림)
#   per-doc 결과는 사이드카 캐시(문서 id 불변 → 무효화 불필요).
# ─────────────────────────────────────────────

_DOC_MT_DIR = docstore.DOC_DIR / "_doc_mtables"
_DOC_AT_DIR = docstore.DOC_DIR / "_doc_atables"


def forget_doc(doc_id: str) -> None:
    """문서(버전) 삭제 시 그 버전의 사이드카 캐시 + 변동이력 항목 정리.

    - per-doc 캐시(_headlines/{id}.csv, _doc_mtables/{id}.json, _doc_atables/{id}.json) 제거.
    - 이 버전이 만든 diff(to.id==doc_id) 를 changelog 피드에서 제거 → 사라진 버전의
      변동이 변동이력에 남지 않게(되돌림과 정합).
    """
    (_HEADLINE_DIR / f"{doc_id}.csv").unlink(missing_ok=True)
    (_DOC_MT_DIR / f"{doc_id}.json").unlink(missing_ok=True)
    (_DOC_AT_DIR / f"{doc_id}.json").unlink(missing_ok=True)
    log = _load()
    pruned = [e for e in log if (e.get("to") or {}).get("id") != doc_id]
    if len(pruned) != len(log):
        _save(pruned)


def _doc_master_table(doc_id: str) -> Optional[dict]:
    """문서 1벌의 전체 종합 표(master_table) — 사이드카 캐시."""
    f = _DOC_MT_DIR / f"{doc_id}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    p = docstore.path_of(doc_id)
    if not p:
        return None
    from . import master_lg
    try:
        t = master_lg.master_table(p.read_bytes())
    except Exception:
        return None
    _DOC_MT_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    return t


def _doc_area_table(doc_id: str, area: str) -> Optional[dict]:
    """문서 1벌의 개별 Area 표 — 사이드카 캐시."""
    f = _DOC_AT_DIR / f"{doc_id}_{area}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    p = docstore.path_of(doc_id)
    if not p:
        return None
    from . import master_lg
    try:
        t = master_lg.area_table(p.read_bytes(), area)
    except Exception:
        return None
    _DOC_AT_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    return t


def _latest_doc_id(area: str) -> Optional[str]:
    """그 항목의 최신 버전(=수정본) 문서 id. v2 이상(변경 있음)일 때만."""
    vers = versions_by_area().get(area, [])
    return vers[-1]["id"] if len(vers) >= 2 else None


def _changed_months(area: str) -> List[int]:
    """그 항목의 최신 changelog 에서 바뀐 달 목록."""
    for e in reversed(_load()):
        if e.get("항목") == area:
            return sorted({int(r["월"]) for r in (e.get("changed") or []) if r.get("월") is not None})
    return []


def _change_pieces(area: str) -> List[dict]:
    """그 항목 최신 changelog 변경을 '조각'으로 — 마감(월계 월별) / 차(주차 ISO별).

    /simulation 패널이 실적요청 칩처럼 차수 단위로 펼쳐 고르게 하기 위한 단위.
    key = 'm{월}'(마감) / 'w{ISO}'(차). compose 가 이 key 로 선택 조각만 반영.
    """
    for e in reversed(_load()):
        if e.get("항목") != area:
            continue
        close: dict = {}   # 월 → True (월계 변경)
        wk: dict = {}      # ISO → 월 (주차 변경)
        for r in (e.get("changed") or []):
            g, mo, ju = r.get("구분"), r.get("월"), r.get("주차")
            if g == "월계" and mo is not None:
                close[int(mo)] = True
            elif g == "주차" and ju:
                iso = store._wnum(ju)
                if iso:
                    wk[iso] = int(mo) if mo is not None else None
        pieces: List[dict] = []
        for m in sorted(close):
            pieces.append({"key": f"m{m}", "kind": "마감", "월": m, "label": f"{m}월 마감"})
        for iso in sorted(wk):
            pieces.append({"key": f"w{iso}", "kind": "차", "월": wk[iso], "iso": iso,
                           "label": store.week_label(iso)})
        return pieces
    return []


def _picked(area: str, picks):
    """picks[area] → (적용 문서 id, 선택 조각 key set|None). None=전체 조각·최신본.

    picks[area] 형태: None(=최신본·전체) / docid 문자열(=그 버전·전체) /
    {'doc':docid|None, 'pieces':set|None}(=버전+조각 선택, lgdata._sim_picks 신형식).
    """
    v = (picks or {}).get(area)
    if isinstance(v, dict):
        doc = v.get("doc") or _latest_doc_id(area)
        pieces = v.get("pieces")
    else:
        doc = v or _latest_doc_id(area)
        pieces = None
    return doc, pieces


def _sel_months_weeks(area: str, pieces):
    """선택 조각 → (마감 월 set, 차 ISO set). pieces=None → 그 항목 전체 변경 조각."""
    allp = _change_pieces(area)
    sel = allp if pieces is None else [p for p in allp if p["key"] in pieces]
    months = {p["월"] for p in sel if p.get("kind") == "마감" and p.get("월") is not None}
    weeks = {p["iso"] for p in sel if p.get("kind") == "차" and p.get("iso") is not None}
    return months, weeks


def _sim_areas(picks) -> List[str]:
    """반영 대상 항목 — 적용 버전 있고 선택 조각(마감/차)이 하나라도 있는 항목."""
    out: List[str] = []
    for a in (picks or {}):
        doc, pieces = _picked(a, picks)
        if not doc:
            continue
        m, w = _sel_months_weeks(a, pieces)
        if m or w:
            out.append(a)
    return out


def _apply_pieces(cells: Optional[dict], dcells: dict, months: set, weeks: set) -> dict:
    """현재 셀(cells)에 문서 셀값(dcells)을 조각 단위로 주입.

    마감(months) = 그 달 월계 스칼라(목표/실적/달성률/잠정) 교체(주차는 보존).
    차(weeks ISO) = 그 달 셀의 해당 주차(W#) 엔트리만 교체.
    (이 양식은 월계·주차가 독립 raw → 마감/차를 따로 갈아끼움이 정확.)
    """
    out: dict = {mk: dict(c) for mk, c in (cells or {}).items()}
    for m in months:
        mk = str(m)
        if mk not in dcells:
            continue
        if mk in out:
            for f in ("목표", "실적", "달성률", "잠정"):
                if f in dcells[mk]:
                    out[mk][f] = dcells[mk].get(f)
        else:
            out[mk] = dict(dcells[mk])
    for iso in weeks:
        mm = store.WEEK_MONTH.get(iso, (None, None))[0]
        if not mm:
            continue
        mk = str(mm)
        if mk not in out or not out[mk].get("weeks"):
            continue
        wlab = f"W{iso}"
        dweeks = {w.get("주차"): w for w in ((dcells.get(mk) or {}).get("weeks") or [])}
        if wlab in dweeks:
            out[mk] = dict(out[mk])
            out[mk]["weeks"] = [dict(dweeks[wlab]) if w.get("주차") == wlab else w
                                for w in out[mk]["weeks"]]
    return out


def compose_headline(cur_period: str, picks):
    """master_detail 용 headline — 선택 항목의 '선택 마감(월계) 달' 행만 선택버전 문서값으로 교체.
    (헤드라인=대표총계 월계만 → 차(주차) 조각은 헤드라인에 영향 없음.)"""
    cur = store.load_master_headline(cur_period)
    sel = _sim_areas(picks)
    if not sel or not len(cur):
        return cur
    cur = cur.copy()
    for a in sel:
        doc, pieces = _picked(a, picks)
        months, _w = _sel_months_weeks(a, pieces)
        if not months:
            continue
        hl = _doc_headline(doc)
        if hl is None or not len(hl):
            continue
        cur = cur[~((cur["항목"] == a) & (cur["월"].isin(months)))]
        cur = pd.concat([cur, hl[(hl["항목"] == a) & (hl["월"].isin(months))]], ignore_index=True)
    return cur


def compose_master_table(cur_period: str, picks) -> dict:
    """전체 종합 표 — 선택 항목의 선택 조각(마감 월계/차 주차) 셀만 교체 + 합계행 재합산 + chg 마킹."""
    cur = store.load_master_table(cur_period)
    sel = _sim_areas(picks)
    if not sel or not cur.get("rows"):
        return cur
    months = cur.get("months", [])
    rows = [dict(r) for r in cur.get("rows", [])]
    for a in sel:
        doc, pieces = _picked(a, picks)
        msel, wsel = _sel_months_weeks(a, pieces)
        if not msel and not wsel:
            continue
        mt = _doc_master_table(doc)
        if not mt:
            continue
        doc_by = {(r.get("area"), r.get("level"), r.get("label")): r
                  for r in mt.get("rows", []) if not r.get("bold")}
        for r in rows:
            if r.get("bold") or r.get("area") != a:
                continue
            dr = doc_by.get((r.get("area"), r.get("level"), r.get("label")))
            if not dr:
                continue
            r["cells"] = _apply_pieces(r.get("cells"), dr.get("cells") or {}, msel, wsel)
    l0 = [r for r in rows if not r.get("bold") and r.get("level") == 0]
    for r in rows:
        if r.get("bold"):
            r["cells"] = store._resum_bold(l0, months, "제외" in str(r.get("label", "")))
    out = {"months": months, "rows": rows}
    store._mark_changes(cur, out)   # 현재 대비 바뀐 셀 chg/before
    return out


def compose_area_table(cur_period: str, area: str, picks) -> dict:
    """개별 Area 표 — 선택 조각(마감 월계/차 주차) 셀을 선택버전 문서값으로 교체 + chg 마킹."""
    cur = store.load_area_table(cur_period, area)
    if area not in _sim_areas(picks):
        return cur
    doc, pieces = _picked(area, picks)
    months, weeks = _sel_months_weeks(area, pieces)
    at = _doc_area_table(doc, area)
    if not at or not at.get("rows"):
        return cur
    # 현재·문서 표는 같은 master_lg.area_table 로 만들어 **구조·순서 동일** → 인덱스로 매칭.
    #   (부서경로 매칭은 고정비처럼 라벨 없는 반복 블록에서 중복 경로가 겹쳐 오매칭되므로 인덱스 사용.
    #    구조가 어긋나면 부서경로 확인으로 폴백.)
    doc_rows = at.get("rows", [])
    rows = []
    for i, r in enumerate(cur.get("rows", [])):
        nr = dict(r)
        dr = doc_rows[i] if i < len(doc_rows) and doc_rows[i].get("부서경로") == r.get("부서경로") else None
        nr["cells"] = _apply_pieces(r.get("cells"), (dr.get("cells") or {}) if dr else {}, months, weeks)
        rows.append(nr)
    out = {**cur, "rows": rows}
    store.mark_area_changes(cur, out)
    return out
