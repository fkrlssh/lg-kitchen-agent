"""CSV 기반 raw 데이터 저장소 — 일명 "CSV DB".

DB 없이 간다. 업로드된 LG 엑셀을 parsing_lg 로 펼쳐 **CSV 파일**로 저장한다.

설계 (사용자 합의):
- 저장 단위 = data/{회차}/{출처}.csv  (부서/회신별 1파일)
  → 문제 생기면 담당자가 그 CSV 만 엑셀로 열어 직접 수정. DB 블랙박스 회피.
- 굳이 한 파일로 물리 병합 안 함. 집계는 load_period 가 회차 폴더의 CSV 를
  모두 읽어 메모리에서 잠깐 합쳐 반환.
- 저장하는 건 원천(당월 월별)뿐. 누적/분기/Master 는 읽을 때 재현(계산).

data/ 는 .gitignore 대상 → 실데이터 GitHub 비노출.
"""
from __future__ import annotations

import io
import json
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from . import registry
from .parsing_lg import parse_workbook

# 보고서 캐시(headline/master_table/area_table) 쓰기 직렬화 락 —
# 삭제 백그라운드 재계산 + 동시 업로드가 같은 회차 캐시 파일을 동시에 쓰면 깨질 수 있어 보호.
_CACHE_LOCK = threading.RLock()

# 제출 로그 파일명 (회차 폴더 내) — 항목별 제출횟수/마지막제출 기록
SUBMIT_LOG = "_submitlog.json"
# 요청(독촉) 발송 로그 — 항목별 마지막 발송 시각 (중복 발송 방지/표시용)
REMIND_LOG = "_remindlog.json"
# Master 대표총계(headline) 스냅샷 — overview(전체) 재현용 (leaf 합과 별개)
MASTER_FILE = "_master_headline.csv"

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"

RAW_COLUMNS = [
    "항목", "부서경로", "데이터종류", "연도", "종류",
    "월", "구분", "주차", "값", "원본셀", "연도구분",
]

# 항목 메타 = 레지스트리(단일 진실원천). slug → {slug, sheet, label, source, unit, derived_from}.
#  source: 부서=표준양식 직접제출 / 운영자=별도양식 메일받아 입력 / 파생=다른 항목 합(제출 대상 X)
#  unit:   주차=월+주차(W) 세분 / 월=월 단위만
#  ⚠️ 시트 이름·라벨이 바뀌면 src/registry.py 만 수정 (여긴 무변경).
AREA_META: dict = registry.BY_SLUG
# 제출 대상 = 파생 제외 전 항목
EXPECTED_AREAS = list(registry.EXPECTED_SLUGS)

FileLike = Union[str, Path]


def _safe(name: str) -> str:
    """파일명 안전화 (한글 허용, 그 외 특수문자 → _)."""
    stem = Path(str(name)).stem
    return re.sub(r"[^\w가-힣\-]+", "_", stem).strip("_") or "upload"


def period_dir(period_id: str) -> Path:
    # 회차(격주) = 스냅샷 단위 → data/{회차}/{항목}.csv  (연도/월은 CSV 컬럼)
    return DATA_DIR / period_id


def _wnum(s) -> int:
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else 0


def infer_period_id(df: pd.DataFrame) -> str:
    """파싱된 raw → '이건 몇 회차야' 자동 판단.

    실적(actual)이 어디까지 채워졌는지로 시점을 추론:
    - 당해(올해)의 실적이 있는 **마지막 월** = 현재 월
    - 그 달에서 실적이 들어온 **마지막 주차의 '월중 몇째 주'** = 정밀 차수(N차)
      (예: 3월 마지막 실적이 W12면 3월 3차 → '2026-03-3'. WEEK_MONTH 번호 그대로,
       보고서 드롭다운·target_week 역매핑과 같은 numbering 이라 라운드트립됨)
    - 주차 없는 월형 항목은 차 개념이 없어 마지막 월 2차로(관례).
    실적이 전혀 없으면 목표 기준 마지막 월 1차로. 비면 안전 기본값.
    """
    if df is None or len(df) == 0:
        return "2026-01-1"
    d = df
    if "연도구분" in d.columns and (d["연도구분"] == "당해").any():
        d = d[d["연도구분"] == "당해"]
    else:
        d = d[d["연도"] == d["연도"].max()]
    year = int(d["연도"].max())

    # 현재 시점 = "주차 실적이 충분히 찬 마지막 월". 주차 데이터가 시점을 가장 잘 보여줌
    # (월값은 그 달 마감돼야 차서 한 박자 늦음). 경계 주차(한 주가 두 달 걸침)로
    # 미래월에 1주만 튀는 건 '절반 이상 찬 달'만 인정해 걸러냄.
    wk_act = d[(d["종류"] == "실적") & (d["구분"] == "주차")]
    wk_tgt = d[(d["종류"].isin(["목표", "계획"])) & (d["구분"] == "주차")]
    if len(wk_act) and len(wk_tgt):
        # 월별: 실적 든 distinct 주차 수 vs 목표상 그 달 총 주차 수
        act_w = wk_act.groupby("월")["주차"].apply(lambda s: {_wnum(x) for x in s.dropna()})
        tgt_w = wk_tgt.groupby("월")["주차"].apply(lambda s: {_wnum(x) for x in s.dropna()})
        # 그 달 주차 2개 이상 실적이면 '진입한 달'로 인정 (경계 주차 1개만 튀는 건 무시)
        solid = [m for m in act_w.index if len(act_w[m]) >= 2]
        month = max(solid) if solid else int(wk_act["월"].max())
        # 정밀 차수 = 그 달 마지막 실적 주차의 '월중 몇째 주'(WEEK_MONTH 번호).
        last_act = max(act_w[month])
        mw = WEEK_MONTH.get(int(last_act))
        if mw:
            cha = mw[1]
        else:                                  # 매핑 밖 주차 → 그 달 목표 주차 중 위치로 폴백
            allw = sorted(tgt_w.get(month, act_w[month]))
            cha = (allw.index(last_act) + 1) if last_act in allw else len(allw)
        return f"{year}-{month:02d}-{cha}"

    # 주차 데이터 없는 경우(월형 항목만) → 월계 실적 충분히 찬 마지막 월, 2차로
    act = d[(d["종류"] == "실적") & (d["구분"] == "월계")]
    tgt = d[(d["종류"].isin(["목표", "계획"])) & (d["구분"] == "월계")]
    if len(act) and len(tgt):
        ac = act.groupby("월")["값"].count()
        tc = tgt.groupby("월")["값"].count()
        solid = [m for m in ac.index if ac[m] >= 0.5 * tc.get(m, ac[m])]
        month = max(solid) if solid else int(act["월"].max())
        return f"{year}-{month:02d}-2"

    month = int(d["월"].max()) if len(d) else 1
    return f"{year}-{month:02d}-1"


def _df_latest(df: "pd.DataFrame", year: int = 2026):
    """DF 의 당해 실적 최신 ((월,ISO주차) 쌍, 라벨). 주차 없으면 최신 월계 월. 경계주도 데이터 월 그대로."""
    if df is None or not len(df):
        return None, "—"
    d = df[df["종류"] == "실적"]
    if "연도구분" in d.columns:
        d = d[d["연도구분"] == "당해"]
    wk = d[d["구분"] == "주차"]
    pairs = {(int(m), _wnum(x)) for m, x in zip(wk["월"], wk["주차"])
             if pd.notna(m) and _wnum(x)}
    months = {int(x) for x in d[d["구분"] == "월계"]["월"].dropna()}
    if pairs:
        p = max(pairs)
        return p, f"{year}년 {p[0]}월 W{p[1]}"
    if months:
        return None, f"{year}년 {max(months)}월"
    return None, "—"


def _changed_past_cells(df: pd.DataFrame, existing: pd.DataFrame) -> int:
    """업로드 df vs 기존 저장분에서 **겹치는 실적 셀 중 값이 바뀐 개수**(과거 정정 감지)."""
    if not len(existing) or not len(df):
        return 0
    a = existing[existing["종류"] == "실적"].drop_duplicates("원본셀").set_index("원본셀")["값"]
    b = df[df["종류"] == "실적"].drop_duplicates("원본셀").set_index("원본셀")["값"]
    changed = 0
    for k in a.index.intersection(b.index):
        try:
            if abs(float(a[k]) - float(b[k])) > 0.01:
                changed += 1
        except (TypeError, ValueError):
            pass
    return changed


def _submission_kind(df: pd.DataFrame, existing: pd.DataFrame, year: int) -> str:
    """업로드 df vs 기존 저장분 비교 → 구분(첫 제출 / 신규 시점 / 재제출 (정정) / 재제출).

    미리보기 모달과 실적관리 상태칸이 **동일 기준**을 쓰게 하는 단일 판정 함수.
    - 첫 제출     : 기존 데이터 없음
    - 신규 시점   : 업로드 최신 (월,주차)가 기존보다 앞섬(새 시점 추가 — 재제출 아님)
    - 재제출 (정정): 겹치는 과거 실적 셀이 바뀜
    - 재제출      : 그 외(같은 시점 재업로드)
    """
    if not len(existing):
        return "첫 제출"
    up_pair, _ = _df_latest(df, year)
    ex_pair, _ = _df_latest(existing, year)
    if up_pair and (ex_pair is None or up_pair > ex_pair):
        return "신규 시점"
    return "재제출 (정정)" if _changed_past_cells(df, existing) > 0 else "재제출"


def preview_excel(source: FileLike, only_area: Optional[str] = None) -> dict:
    """저장하지 않고 파싱만 → 적재 시 무슨 일이 일어날지 요약 (미리보기).

    반환: period_id(폴더 판단) / latest_label(데이터 실제 최신 시점) / kind(첫제출/신규시점/재제출) /
          areas / rows / per_area / changed_past / is_new
    """
    df_all, _ = parse_workbook(source)
    df = df_all[df_all["항목"] == only_area] if only_area else df_all
    period_id = infer_period_id(df)   # 저장 폴더 판단용(유지)
    areas = sorted(df["항목"].dropna().unique().tolist())
    per_area = {a: int((df["항목"] == a).sum()) for a in areas}
    year = int(df["연도"].max()) if len(df) and "연도" in df.columns and df["연도"].notna().any() else 2026
    # 인식된 시점 = **데이터의 실제 최신 (월, 주차)** (경계주도 데이터 월 그대로 = latest_status 와 일관).
    up_pair, latest_label = _df_latest(df, year)

    # 이미 적재된 데이터 대비 과거 실적 변경 셀 수 — 비교는 **현재 상태**(저장 폴더)에서.
    existing = load_period(current_period() or period_id)
    if only_area and len(existing):
        existing = existing[existing["항목"] == only_area]
    is_new = not len(existing)
    changed = _changed_past_cells(df, existing)
    # 구분 — 첫 제출 / 신규 시점(기존보다 앞선 새 시점) / 재제출(정정=과거 변경) / 재제출
    #   저장 시 상태칸도 같은 함수(_submission_kind)로 판정 → 미리보기와 실적관리 일치.
    kind = _submission_kind(df, existing, year)
    return {
        "period_id": period_id,
        "latest_label": latest_label,
        "kind": kind,
        "areas": areas,
        "rows": int(len(df)),
        "per_area": per_area,
        "changed_past": changed,
        "is_new": is_new,
    }


def _source_bytes(source: FileLike) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if hasattr(source, "read"):
        return source.read()
    return Path(source).read_bytes()


def _latest_doc_bytes(area: str) -> Optional[bytes]:
    """그 항목의 최신 보관 문서(bytes) — 없으면 None. (고정비 컴포넌트 병합용)"""
    from . import docstore
    docs = [d for d in docstore.list_docs() if d.get("area") == area]
    if not docs:
        return None
    docs.sort(key=lambda d: d.get("uploaded_at", ""))
    p = docstore.path_of(docs[-1]["id"])
    return p.read_bytes() if p else None


def _copy_sheet_values(src_ws, dst_ws) -> None:
    """src 시트의 셀 값(수식 문자열 포함)을 dst 시트의 같은 좌표에 복사. master_lg 평가용(서식 무시).

    병합셀(앵커 외)은 읽기전용이라 건너뜀 — 값은 앵커 셀에만 있고 src·dst 병합구조가 같음.
    """
    from openpyxl.cell.cell import MergedCell
    for row in src_ws.iter_rows():
        for cell in row:
            if isinstance(cell, MergedCell):
                continue
            dst = dst_ws[cell.coordinate]
            if isinstance(dst, MergedCell):
                continue
            dst.value = cell.value


def _merged_component_source(source: FileLike, only_area: Optional[str]) -> Optional[bytes]:
    """고정비 컴포넌트(또는 파생) 업로드 시 — **다른 컴포넌트들의 최신 보관 시트**를 업로드
    워크북 위에 덮어 4개 최신 기준으로 고정비를 평가하게 한 워크북 bytes. 해당 없으면 None.

    배경: LG 고정비는 컴포넌트(사업부/생산제판/UnControl/Rawdata)가 **각각 풀 양식 파일**로 옴.
    어느 한 컴포넌트 파일엔 나머지 3개 시트가 낡아, 그 파일 하나로 고정비(=고정비 집계시트가
    4개를 cross-sheet 합산)를 재평가하면 '마지막 올린 파일' 기준이라 부정확 → 교차오염.
    해결: only_area(=방금 업로드, 최신)는 source 그대로 두고, 나머지 컴포넌트 시트만 각자
    최신 문서에서 덮어 4개 최신을 본다. master_lg 는 수식을 직접 평가(캐시 비의존)하므로
    raw+formula 보존만으로 정확. (only_area=None 통짜 업로드면 트리거 안 됨 → 기존 동작 무변경.)
    """
    derived = registry.DERIVED_SLUG
    comps = list(AREA_META.get(derived, {}).get("derived_from", []))
    if not comps or (only_area not in comps and only_area != derived):
        return None
    from openpyxl import load_workbook
    base = load_workbook(io.BytesIO(_source_bytes(source)), data_only=False)
    changed = False
    for comp in comps:
        if comp == only_area:
            continue                      # 업로드본(source)이 이미 최신
        raw = _latest_doc_bytes(comp)
        if not raw:
            continue
        sheet = AREA_META.get(comp, {}).get("sheet")
        if not sheet or sheet not in base.sheetnames:
            continue
        cwb = load_workbook(io.BytesIO(raw), data_only=False)
        if sheet not in cwb.sheetnames:
            continue
        _copy_sheet_values(cwb[sheet], base[sheet])
        changed = True
    if not changed:
        return None
    bio = io.BytesIO()
    base.save(bio)
    return bio.getvalue()


def save_excel(source: FileLike, period_id: Optional[str] = None,
               only_area: Optional[str] = None,
               log: bool = True) -> Tuple[List[Path], pd.DataFrame, dict, str]:
    """엑셀(경로) → parse_workbook → **항목별** CSV 분할 저장.

    period_id 가 None 이면 파일 내용으로 **회차 자동 판단**(infer_period_id).
    only_area 지정 시 **그 항목만** 저장(부서별 업로드 = 자기 항목만 적재, 나머지 안 건드림).
    회차는 항상 전체 df 로 판단(부분 파일이라도 주차 정보 살아있음).
    같은 (회차, 항목) 이면 덮어쓰기 → 항목 재제출은 그 파일만 교체.
    log=False 면 제출 횟수 카운트 안 올림(문서 삭제 시 이전 버전 복원 재적재 등 내부 재계산용).
    returns: (저장된 csv 경로 리스트, 저장한 DataFrame, 시트별 진단, 사용된 period_id)
    """
    if hasattr(source, "read"):        # 스트림 → bytes 1회 (parse + 병합 재평가가 여러 번 읽음)
        source = source.read()
    # 워크북을 **1회만** openpyxl 로드해 CSV 적재(parse_workbook)와 캐시 빌더가 공유.
    # (openpyxl 로드 ~1.1s×2 가 비용 대부분 — 안 공유하면 같은 파일을 4번 파싱 → ~5s.)
    shared_wbs = None
    try:
        from . import master_lg
        shared_wbs = master_lg._load_two(source)
    except Exception:
        shared_wbs = None
    df_all, report = parse_workbook(shared_wbs if shared_wbs is not None else source)
    if not period_id:
        period_id = infer_period_id(df_all)
    # only_area 면 그 항목만 추려 저장
    df = df_all[df_all["항목"] == only_area] if only_area else df_all
    d = period_dir(period_id)
    d.mkdir(parents=True, exist_ok=True)
    # 덮어쓰기 **전**의 기존 저장분으로 항목별 구분(신규 시점/재제출) 판정 → 상태칸이 미리보기와 일치.
    # 비교 기준은 미리보기(preview_excel)와 동일하게 **현재 상태 폴더**(current_period).
    year = int(df_all["연도"].max()) if len(df_all) and "연도" in df_all.columns and df_all["연도"].notna().any() else 2026
    existing_all = load_period(current_period() or period_id) if log else pd.DataFrame()
    outs: List[Path] = []
    saved_items: List[str] = []
    kinds: Dict[str, str] = {}
    for item, sub in df.groupby("항목", sort=True):
        if log:
            ex_item = existing_all[existing_all["항목"] == item] if len(existing_all) else existing_all
            kinds[str(item)] = _submission_kind(sub, ex_item, year)
        out = d / f"{_safe(str(item))}.csv"
        sub.to_csv(out, index=False, encoding="utf-8-sig")  # 엑셀에서 한글 안 깨짐
        outs.append(out)
        saved_items.append(str(item))
    if log:
        _log_submission(period_id, saved_items, kinds)
    # only_area 지정(부서별 개별 업로드)이면 보고서 캐시도 **그 항목만 머지**(전체 덮어쓰기 X)
    # → A 파일 올려도 그 안의 낡은 B 시트가 B 캐시를 덮지 않음(교차오염 방지).
    # 고정비 컴포넌트 업로드면 캐시 계산용 source 를 4개 최신 컴포넌트 병합본으로 교체(파생 정확).
    # (raw CSV 는 위에서 업로드 source 기준으로 이미 저장 — only_area 자기 데이터만.)
    # 고정비 컴포넌트 업로드면 캐시 계산용 source 를 4개 최신 컴포넌트 병합본으로 교체(파생 정확) →
    # 그 경우만 별도 로드. 그 외(대부분)는 위에서 1회 로드한 shared_wbs 를 그대로 재사용.
    merged = _merged_component_source(source, only_area)
    if merged is not None:
        try:
            cache_src = master_lg._load_two(merged)
        except Exception:
            cache_src = merged
    else:
        cache_src = shared_wbs if shared_wbs is not None else source
    with _CACHE_LOCK:   # 캐시 3종 머지/쓰기 직렬화(동시 삭제·업로드 충돌 방지)
        _save_master_headline(cache_src, period_id, only_area)
        _save_master_table(cache_src, period_id, only_area)
        _save_area_tables(cache_src, period_id, only_area)
    return outs, df, report, period_id


def _affected_areas(only_area: Optional[str]) -> Optional[set]:
    """캐시 머지 시 갱신할 항목 집합 — only_area + (고정비 컴포넌트/고정비면 고정비 롤업도).
    None = 전체(only_area 미지정 → 통짜 저장)."""
    if not only_area:
        return None
    aff = {only_area}
    d = registry.DERIVED_SLUG
    comps = set(AREA_META.get(d, {}).get("derived_from", []))
    if only_area == d or only_area in comps:
        aff.add(d)
    return aff


def _save_master_headline(source: FileLike, period_id: str, only_area: Optional[str] = None) -> None:
    """업로드 워크북의 Master 대표총계를 회차 폴더에 별도 저장 (overview 재현용).

    Master 수식이 가리키는 Area 대표행을 읽어 항목×월 목표/실적 headline 으로.
    only_area 지정 시 그 항목(+고정비) 행만 교체하고 나머지는 기존 유지(교차오염 방지).
    실패해도 raw 저장엔 영향 없게 swallow (Master 시트 없는 부분 제출 등).
    """
    try:
        from . import master_lg
        hl = master_lg.master_headline(source)
        if not len(hl):
            return
        aff = _affected_areas(only_area)
        if aff is not None:
            existing = load_master_headline(period_id)
            keep = existing[~existing["항목"].isin(aff)] if len(existing) else existing
            take = hl[hl["항목"].isin(aff)]
            hl = pd.concat([keep, take], ignore_index=True) if len(keep) else take
        hl.to_csv(period_dir(period_id) / MASTER_FILE, index=False, encoding="utf-8-sig")
    except Exception:
        pass


def load_master_headline(period_id: str) -> pd.DataFrame:
    """저장된 Master 대표총계 headline (항목/종류/월/구분/주차/값). 없으면 빈 DF."""
    f = period_dir(period_id) / MASTER_FILE
    if f.exists():
        return pd.read_csv(f, encoding="utf-8-sig")
    return pd.DataFrame(columns=["항목", "종류", "월", "구분", "주차", "값"])


MASTER_TABLE_FILE = "_master_table.json"


def _save_master_table(source: FileLike, period_id: str, only_area: Optional[str] = None) -> None:
    """Master 시트형 계층 테이블(합계/Area>하위 × 월) 저장. 회차 월 기준 미래 컷.
    only_area 지정 시 그 항목(+고정비) 행만 교체 + 합계행 재합산(나머지 유지=교차오염 방지)."""
    try:
        from . import master_lg
        cur_mo = _cache_current_month(period_id)   # 폴더 이름 아닌 데이터 기준(월 진행 대응)
        t = master_lg.master_table(source, current_month=cur_mo)
        if not t.get("rows"):
            return
        aff = _affected_areas(only_area)
        if aff is not None:
            existing = load_master_table(period_id)
            if existing.get("rows"):
                months = existing.get("months") or t.get("months", [])
                kept = [r for r in existing["rows"] if not r.get("bold") and r.get("area") not in aff]
                new_rows = [r for r in t["rows"] if not r.get("bold") and r.get("area") in aff]
                merged = kept + new_rows
                bold = [dict(r) for r in existing["rows"] if r.get("bold")] \
                    or [dict(r) for r in t["rows"] if r.get("bold")]
                l0 = [r for r in merged if r.get("level") == 0]
                for r in bold:
                    r["cells"] = _resum_bold(l0, months, "제외" in str(r.get("label", "")))
                t = {"months": months, "current_month": t.get("current_month", cur_mo),
                     "rows": bold + merged}
        (period_dir(period_id) / MASTER_TABLE_FILE).write_text(
            json.dumps(t, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def ensure_report_items(table: dict) -> dict:
    """전체 종합 표가 **항상 REPORT_ITEMS 전부**를 행으로 갖게 한다.

    데이터 없는 항목(미제출·삭제·트림 제외)은 표에서 사라지지 말고 **공란 L0행**으로 떠야 한다
    (카드 master_detail 은 REPORT_ITEMS 를 직접 순회해 공란으로라도 보여줌 — 표도 동일하게 정합).
    있는 항목은 기존 행(L0+세부) 보존, 없는 항목만 빈 셀 L0행 추가. 순서 = REPORT_ITEMS(카드와 동일).
    """
    rows = table.get("rows") or []
    bold = [r for r in rows if r.get("bold")]
    by_area: Dict[str, list] = {}
    for r in rows:
        if r.get("bold"):
            continue
        by_area.setdefault(r.get("area"), []).append(r)
    ordered: List[dict] = []
    for slug in registry.REPORT_ITEMS:
        if slug in by_area:
            ordered.extend(by_area.pop(slug))
        else:
            ordered.append({"label": registry.label_for(slug), "level": 0,
                            "bold": False, "area": slug, "cells": {}})
    for rs in by_area.values():        # REPORT_ITEMS 밖 항목(혹시) 뒤에 보존
        ordered.extend(rs)
    return {**table, "rows": bold + ordered}


def load_master_table(period_id: str) -> dict:
    """저장된 Master 계층 테이블. 없으면 빈 구조."""
    f = period_dir(period_id) / MASTER_TABLE_FILE
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"months": [], "rows": []}


# ─────────────────────────────────────────────
# 변경 시뮬레이션 조립 헬퍼 — 합계행 재합산(_resum_bold)·변경셀 마킹(_mark_changes/mark_area_changes).
# 실제 조립(현재 ⊕ 선택 항목의 변경월)은 changelog.compose_* 가 항목별 실제 문서에서 수행하며
# 이 헬퍼들을 호출한다. (합본 스냅샷 불필요 — 항목별 델타 즉석 조립, 엑셀 재계산 X)
# ─────────────────────────────────────────────

_EPS = 0.01   # 시뮬레이션 변경 셀 감지 임계 (실적 차이 > eps 면 '바뀜')


def sync_bold_to_detail(mt: dict, detail: dict) -> dict:
    """전체 종합 표의 합계행을 카드/그래프(master_detail, canonical=엑셀 합계)와 **동일 값**으로 맞춘다.

    표 합계는 L0 행 재합산인데, L0 없는 월형 sub(예 매출 지역2)가 잠정 보정 때 빠져 카드/그래프와
    어긋났다(4월 표≠그래프). 합계는 한 곳(master_detail)에서만 계산하고 표는 그걸 미러 → 단일 진실원천.
    chart 의 전체(실적)·H제외(실적_ex)를 '합계'·'합계(고정비 제외)' 행에 월별로 주입. (주차/chg/before 보존)
    """
    chart = (detail.get("summary") or {}).get("chart") or []
    by_m = {p.get("월"): p for p in chart}
    for r in mt.get("rows", []):
        if not r.get("bold"):
            continue
        ex = "제외" in str(r.get("label", ""))
        for mk, cell in (r.get("cells") or {}).items():
            try:
                p = by_m.get(int(mk))
            except (TypeError, ValueError):
                p = None
            if not p:
                continue
            cell["목표"] = p.get("목표_ex" if ex else "목표")
            cell["실적"] = p.get("실적_ex" if ex else "실적")
            cell["달성률"] = p.get("달성률_ex" if ex else "달성률")
            cell["잠정"] = p.get("잠정_ex" if ex else "잠정", cell.get("잠정"))
    return mt


def fix_prov_current(table: dict, is_master: bool) -> dict:
    """현재월 잠정 정합 — 그 달 월계 미도착(잠정=True)인 셀의 실적을 그 행 '마지막 주차값'으로 맞춘다.

    카드/그래프(master_detail)는 '월계 없으면 마지막 주차 누적값으로 채움'을 적용하는데, 전체 종합
    표/개별 표(master_lg)는 합계행에서 0으로 떨어지는 버그가 있어 같은 4월이 표(2210)≠그래프(1983)로
    어긋났다. 여기서 **잠정 셀만**(=현재월만, 닫힌 달은 잠정 아님) 마지막 주차값으로 통일하면 모두 일치.
    master 는 합계행 재합산. 잠정 아닌 셀·닫힌 달·미래월은 안 건드림(안전).
    """
    rows = table.get("rows") or []
    if not rows:
        return table

    def _last_wk(cell):
        wa = [w.get("실적") for w in (cell.get("weeks") or []) if w.get("실적") is not None]
        return wa[-1] if wa else None

    for r in rows:
        if is_master and r.get("bold"):
            continue
        for c in (r.get("cells") or {}).values():
            a = _last_wk(c)
            # 잠정 플래그가 있거나 — 실적이 0/None 인데 주차 누적값이 확실히 있어 '마감 미도착'이 분명하면
            # 잠정으로 마킹(예: 물류비 4월 마감만 제거). 대표총계 수식이 0 으로 떨어지는 경우까지 잡는다.
            if not c.get("잠정"):
                if c.get("실적") in (None, 0) and a not in (None, 0):
                    c["잠정"] = True
                else:
                    continue
            if a is None:
                continue
            c["실적"] = round(a, 2)
            t = c.get("목표")
            c["달성률"] = round(a / t * 100, 1) if t else None
    if is_master:
        months = table.get("months") or []
        l0 = [r for r in rows if not r.get("bold") and r.get("level") == 0]
        for r in rows:
            if r.get("bold"):
                r["cells"] = _resum_bold(l0, months, "제외" in str(r.get("label", "")))
    return table


def _resum_bold(l0_rows: List[dict], months: List[int], exclude_h: bool) -> Dict[str, dict]:
    """L0(Area 총계) 행들을 월·주차별로 합산 → 합계행 cells. (trim_master_table._resum 과 동일 규칙)."""
    src = [r for r in l0_rows if not (exclude_h and r.get("area") == registry.DERIVED_SLUG)]
    cells: Dict[str, dict] = {}
    for m in months:
        t = a = 0.0
        ht = ha = False
        wk: Dict[str, dict] = {}
        for r in src:
            c = (r.get("cells") or {}).get(str(m))
            if not c:
                continue
            if c.get("목표") is not None:
                t += c["목표"]; ht = True
            if c.get("실적") is not None:
                a += c["실적"]; ha = True
            for w in c.get("weeks", []):
                e = wk.setdefault(w["주차"], {"목표": 0.0, "실적": 0.0, "ht": False, "ha": False})
                if w.get("목표") is not None:
                    e["목표"] += w["목표"]; e["ht"] = True
                if w.get("실적") is not None:
                    e["실적"] += w["실적"]; e["ha"] = True
        weeks = [
            {"주차": k, "목표": v["목표"] if v["ht"] else None, "실적": v["실적"] if v["ha"] else None,
             "달성률": round(v["실적"] / v["목표"] * 100, 1) if v["ht"] and v["목표"] else None}
            for k, v in sorted(wk.items(), key=lambda kv: _wnum(kv[0]))
        ]
        cells[str(m)] = {
            "목표": round(t, 2) if ht else None,
            "실적": round(a, 2) if ha else None,
            "달성률": round(a / t * 100, 1) if ht and t else None,
            "weeks": weeks,
        }
    return cells


def _mark_changes(cur: dict, new: dict) -> None:
    """new 의 각 셀을 cur 대비 비교 → 실적이 달라진 셀에 chg=True, before=현재실적 부착(표 하이라이트용)."""
    cur_by = {(r.get("area"), r.get("level"), r.get("label")): r for r in cur.get("rows", [])}
    # bold(합계) 행은 area 없음 → label 로 매칭
    cur_bold = {r.get("label"): r for r in cur.get("rows", []) if r.get("bold")}
    for r in new.get("rows", []):
        base = cur_bold.get(r.get("label")) if r.get("bold") else cur_by.get(
            (r.get("area"), r.get("level"), r.get("label")))
        if not base:
            continue
        bcells = base.get("cells") or {}
        for mk, cell in (r.get("cells") or {}).items():
            bc = bcells.get(mk) or {}
            na, oa = cell.get("실적"), bc.get("실적")
            if na is not None and oa is not None and abs(float(na) - float(oa)) > _EPS:
                cell["chg"] = True
                cell["before"] = oa
            bw = {w.get("주차"): w for w in (bc.get("weeks") or [])}   # 주차 셀도 비교(시뮬 차 하이라이트)
            for w in (cell.get("weeks") or []):
                ow = bw.get(w.get("주차"))
                if ow and w.get("실적") is not None and ow.get("실적") is not None \
                        and abs(float(w["실적"]) - float(ow["실적"])) > _EPS:
                    w["chg"] = True
                    w["before"] = ow.get("실적")


def mark_area_changes(cur_t: dict, new_t: dict) -> dict:
    """area_table(new_t) 셀을 cur_t 대비 비교 → 실적 달라진 월/주차 셀에 chg=True+before. (시뮬 하이라이트).
    new_t 는 cur_t.rows 순서 그대로 만들어짐 → **인덱스 매칭**(고정비 중복 부서경로 오매칭 방지)."""
    cur_rows = cur_t.get("rows", [])
    for i, r in enumerate(new_t.get("rows", [])):
        base = cur_rows[i] if i < len(cur_rows) and cur_rows[i].get("부서경로") == r.get("부서경로") else None
        if not base:
            continue
        bcells = base.get("cells") or {}
        for mk, cell in (r.get("cells") or {}).items():
            bc = bcells.get(mk) or {}
            na, oa = cell.get("실적"), bc.get("실적")
            if na is not None and oa is not None and abs(float(na) - float(oa)) > _EPS:
                cell["chg"] = True
                cell["before"] = oa
            bw = {w.get("주차"): w for w in (bc.get("weeks") or [])}
            for w in (cell.get("weeks") or []):
                ow = bw.get(w.get("주차"))
                if ow and w.get("실적") is not None and ow.get("실적") is not None \
                        and abs(float(w["실적"]) - float(ow["실적"])) > _EPS:
                    w["chg"] = True
                    w["before"] = ow.get("실적")
    return new_t


AREA_TABLE_FILE = "_area_tables.json"


def _save_area_tables(source: FileLike, period_id: str, only_area: Optional[str] = None) -> None:
    """각 Area 시트를 **엑셀 그대로** 재현한 계층 테이블(합계/소계/Rate 포함) 저장.

    parse_sheet 가 버리는 수식 행(소계·합계·Rate)을 master_lg.area_table 이 평가해 포함.
    CSV(leaf) 만으론 합계 구조 복원 불가 → 엑셀 있는 ingest 시점에 계산해 JSON 보관.
    only_area 지정 시 그 항목(+고정비) 엔트리만 교체하고 나머지는 기존 유지(교차오염 방지).
    """
    try:
        from . import master_lg
        cur_mo = _cache_current_month(period_id)   # 폴더 이름 아닌 데이터 기준(월 진행 대응)
        # 고정비(파생)도 요약 시트가 실재 → area_table 가능. 빠지면 보고서 고정비 탭 표가 안 뜸.
        slugs = list(registry.SLUGS)
        if registry.DERIVED_SLUG not in slugs:
            slugs.append(registry.DERIVED_SLUG)
        aff = _affected_areas(only_area)
        compute = slugs if aff is None else [s for s in slugs if s in aff]
        tables: Dict[str, dict] = {}
        for area in compute:               # 슬러그 단위 — area_table 이 시트명으로 해석
            t = master_lg.area_table(source, area, current_month=cur_mo)
            if t.get("rows"):
                tables[area] = t
        if aff is not None:                # 기존에 머지(영향 항목만 교체)
            f = period_dir(period_id) / AREA_TABLE_FILE
            existing: Dict[str, dict] = {}
            if f.exists():
                try:
                    existing = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}
            existing.update(tables)
            tables = existing
        if tables:
            (period_dir(period_id) / AREA_TABLE_FILE).write_text(
                json.dumps(tables, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def load_area_table(period_id: str, area: str) -> dict:
    """저장된 Area 시트 재현 테이블. 없으면 빈 구조."""
    f = period_dir(period_id) / AREA_TABLE_FILE
    empty = {"area": area, "months": [], "rows": []}
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8")).get(area, empty)
        except Exception:
            pass
    return empty


def trim_area_tables(period_id: str, cutoffs: Dict[str, int]) -> None:
    """제출 시점 기준으로 area_tables 캐시 트림 (제출 부서별 latest-wins).

    (1) cutoffs 에 있는 부서만 남기고(나머지=미수집 → 개별 Area 뷰 빈 구조),
    (2) 각 부서의 기준 ISO 주차(cutoffs[area]) 이후 주차 셀을 제거한다.
    엑셀 셀을 비우는 방식은 영역마다 수식 구조가 달라(SUM/뺄셈/다른 행 참조) 일관 트림이
    안 되므로, 계산이 끝난 캐시(JSON)에서 **주차번호로 직접** 자른다(영역 구조 무관).
    """
    f = period_dir(period_id) / AREA_TABLE_FILE
    if not f.exists():
        return
    try:
        tables = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return
    out: Dict[str, dict] = {}
    for area, cw in cutoffs.items():
        t = tables.get(area)
        if not t:
            continue
        for row in t.get("rows", []):
            for cell in (row.get("cells") or {}).values():
                wks = cell.get("weeks")
                if wks:
                    cell["weeks"] = [w for w in wks if _wnum(w.get("주차")) <= cw]
        out[area] = t
    f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


def mask_missing_actual(period_id: str) -> None:
    """실적이 한 건도 없는(미수집) 항목의 area_table 실적을 전부 공란(None)으로 만든다.
    비운 leaf 를 소계 수식이 0 으로 합산한 잔여(0)를 제거 → 개별 상세표도 '미수집(공란)'으로 보이게.
    (목표는 계획이라 유지. aggregate_lg.master_detail 의 미수집 감지와 동일 규칙: 실적 nonzero 가 하나도
     없고 주차 실적도 전무하면 미수집으로 판정.)"""
    f = period_dir(period_id) / AREA_TABLE_FILE
    if not f.exists():
        return
    try:
        tables = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return
    changed = False
    for _area, t in tables.items():
        rows = t.get("rows", [])
        has_actual = any(
            (cell.get("실적") not in (None, 0))
            or any(w.get("실적") not in (None, 0) for w in (cell.get("weeks") or []))
            for row in rows if not row.get("is_rate")
            for cell in (row.get("cells") or {}).values() if isinstance(cell, dict)
        )
        if has_actual:
            continue
        # 목표까지 전무하면(완전 미수집) 목표도 공란. 목표만 있으면(실적 미수집) 목표는 유지.
        has_target = any(
            (cell.get("목표") not in (None, 0))
            for row in rows if not row.get("is_rate")
            for cell in (row.get("cells") or {}).values() if isinstance(cell, dict)
        )
        for row in rows:                       # 미수집 → 실적·달성률·잠정 공란 (완전 미수집이면 목표도)
            for cell in (row.get("cells") or {}).values():
                if not isinstance(cell, dict):
                    continue
                cell["실적"] = None
                cell["달성률"] = None
                cell["잠정"] = False
                if not has_target:
                    cell["목표"] = None
                for w in (cell.get("weeks") or []):
                    w["실적"] = None
                    w["달성률"] = None
                    if not has_target:
                        w["목표"] = None
        changed = True
    if changed:
        f.write_text(json.dumps(tables, ensure_ascii=False), encoding="utf-8")


# ── 동적 차수 보기 (보고서 드롭다운) — 최신 스냅샷 1벌을 읽고 요청 차수까지 주차만 컷 ──

def latest_stored_period() -> Optional[str]:
    """저장된 회차 중 가장 최신(=현재 데이터 스냅샷). 없으면 None."""
    ps = list_stored_periods()
    return ps[-1] if ps else None


def current_period() -> Optional[str]:
    """단일 '현재 상태' 폴더 id — 업로드/삭제는 **항상 이 한 폴더**에 머지한다.

    스냅샷 다(多)폴더 모델 폐기: 부서가 서로 다른 주차로 올려도 같은 현재 상태에 모여야
    보고서(latest_stored_period 한 폴더 읽음)가 모든 항목을 본다. 이미 폴더가 있으면 그걸,
    아직 없으면(시스템 첫 업로드) None → save_excel 이 그 한 번만 infer 로 폴더를 생성한다.
    이후 업로드는 새 폴더를 만들지 않는다(= fragmentation 원천 차단).
    """
    return latest_stored_period()


def data_current_month(period_id: Optional[str] = None) -> Optional[int]:
    """현재 상태 데이터의 '현재 월' = 당해 실적이 든 가장 늦은 월 (**폴더 이름 무관**).

    보고서 캐시 생성·시점 드롭다운이 공유 → 폴더 이름의 월(생성 시점에 고정)과 실제 데이터의
    월이 어긋나도(주/월이 진행되면) 항상 데이터 기준으로 일관되게 동작한다.
    """
    pid = period_id or current_period()
    if not pid:
        return None
    try:
        df = load_period(pid)
        act = df[df["종류"] == "실적"]
        if "연도구분" in act.columns:
            act = act[act["연도구분"] == "당해"]
        return int(act["월"].max()) if len(act) else None
    except Exception:
        return None


def data_year(period_id: Optional[str] = None) -> int:
    """현재 상태 데이터의 당해 연도. 비면 2026 기본."""
    pid = period_id or current_period()
    try:
        df = load_period(pid) if pid else None
        return int(df["연도"].max()) if df is not None and len(df) else 2026
    except Exception:
        return 2026


def _cache_current_month(period_id: str) -> Optional[int]:
    """보고서 캐시 생성용 current_month — 폴더월·데이터월 중 큰 값(데이터가 폴더보다 진행돼도
    안 잘리게, 폴더보다 뒤로도 안 가게). 데모는 둘 다 같아 기존과 동일."""
    parts = str(period_id).split("-")
    folder_mo = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
    data_mo = data_current_month(period_id)
    cands = [m for m in (folder_mo, data_mo) if m is not None]
    return max(cands) if cands else None


def target_week(period_id: str) -> Optional[int]:
    """period_id → 그 시점의 ISO 주차 (없으면 None = 그 달 전체).

    두 형식 지원:
    - '2026-05-W18' : **ISO 직접 지정**(경계주 대응 — 5월 W18처럼 WEEK_MONTH 정준월과 다른 주차도 표현).
    - '2026-05-2'   : 그 달 N차 → WEEK_MONTH 역매핑(레거시, 정준 주차만).
    """
    parts = str(period_id).split("-")
    if len(parts) < 3 or not parts[1].isdigit():
        return None
    p2 = parts[2]
    if p2[:1] in ("W", "w"):        # ISO 직접 지정 — 데이터에 있는 주차 그대로(경계주 무손실)
        iso = _wnum(p2)
        return iso or None
    if not p2.isdigit():
        return None
    mo, n = int(parts[1]), int(p2)
    for iso, (m, w) in WEEK_MONTH.items():
        if m == mo and w == n:
            return iso
    return None


def target_month(period_id: str) -> Optional[int]:
    """period_id 에서 월(M) 추출 — 월 네비게이션용.
    '2026-05'(2-part) 또는 '2026-05-3'(3-part·레거시 차수) → 둘 다 5. 못 찾으면 None(=컷 안 함)."""
    parts = str(period_id).split("-")
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def trim_table_to_month(table: dict, month: Optional[int]) -> dict:
    """area_table/master_table 캐시를 'M월 시점'으로 — months 를 ≤M 으로 필터, 각 행 cells 에서
    M 초과 월 제거, current_month=M 세팅(당월 토글이 M월 셀의 weeks 를 차수로 표시).

    데이터는 누적이라 1..M 월 셀 값은 이미 정확(부서별 최신 = 과거 다 포함) → 재합산 불필요.
    주차는 캐시에 이미 월별로 저장돼 있어 컷 없이 그대로 월 셀에 따라옴. (fresh dict in-place)
    """
    if month is None:
        return table
    months = [m for m in table.get("months", []) if m <= month]
    table["months"] = months
    keep = {str(m) for m in months}
    for row in table.get("rows", []):
        cells = row.get("cells") or {}
        row["cells"] = {k: v for k, v in cells.items() if k in keep}
    table["current_month"] = month
    return table


def trim_table_to_period(table: dict, month: Optional[int], target_week: Optional[int]) -> dict:
    """월+주차 시점 트림 — '연초~선택월 N차' 누적 뷰.

    - months ≤ month (이전 달은 그대로 = 완결), current_month=month.
    - **선택월(month)은 target_week 시점**으로: 그 달 주차 중 ≤target_week 만 남기고,
      그 달 월계 셀값 = 그 시점(마지막 ≤target_week 주차)의 **누적값**(목표/실적/달성률).
      (데이터가 누적이라 '그 달 N차 값' = N차 주차 셀 값.)
    - target_week=None(주차='전체') → 월컷만(그 달 전체).
    예: 4월·3차 → 1·2·3월 완결 + 4월은 W16(3차)까지 누적.
    """
    table = trim_table_to_month(table, month)
    if month is None or target_week is None:
        return table
    mk = str(month)
    for row in table.get("rows", []):
        cell = (row.get("cells") or {}).get(mk)
        if not cell:
            continue
        # 월계(실적)는 데이터에 있는 실제 월 총계 그대로 — 비우거나 주차값으로 안 바꿈
        # (업로드 때 월계도 같이 들어오니, 1월 1차여도 1월 월계는 실제값으로 표시).
        # 주차만 선택 차(target_week)까지 컷.
        cell["weeks"] = [w for w in (cell.get("weeks") or []) if _wnum(w.get("주차")) <= target_week]
    return table


def trim_table_weeks(table: dict, cutoff_week: int) -> dict:
    """area_table/master_table 캐시를 '그 차수까지'로 — 각 셀의 weeks 중 cutoff 초과분만 제거.
    월별 셀 값은 그대로(최신). 과거 차수 보기 = 주차 진행만 되감음. (fresh dict 라 in-place)
    주차별 합계는 주차마다 독립 계산이라 컷만 해도 정확(재합산 불필요)."""
    if cutoff_week is None:
        return table
    for row in table.get("rows", []):
        for cell in (row.get("cells") or {}).values():
            wks = cell.get("weeks")
            if wks:
                cell["weeks"] = [w for w in wks if _wnum(w.get("주차")) <= cutoff_week]
    return table


def trim_headline_weeks(hl, cutoff_week: int):
    """master_headline(df) 의 주차 행 중 cutoff 초과분 제거 (월계 행은 유지). master_detail 재집계용."""
    if cutoff_week is None or hl is None or not len(hl):
        return hl
    return hl[~((hl["구분"] == "주차") & (hl["주차"].map(_wnum) > cutoff_week))]


def trim_headline_to_period(hl, month: Optional[int], target_week: Optional[int]):
    """master_headline 을 '연초~month월 N차' 시점으로 — month 의 주차만 target_week 까지 컷.
    ⚠️ 월계(월 총계)는 **데이터 실제값 그대로 유지**(주차값으로 치환 X) — trim_table_to_period(표)와 동일.
    예전엔 월계를 마지막 주차 누적값으로 교체했으나, 블라인드 데이터(월≠주차합)에서 표(실제월값)↔카드/그래프
    (주차값)가 어긋남 → 치환 제거해 통일. 이전 달은 그대로. target_week=None 이면 변경 없음."""
    if hl is None or not len(hl) or month is None or target_week is None:
        return hl
    hl = hl.copy()
    # month 의 주차 행 중 target_week 초과 제거 (월계는 실제값 그대로)
    hl = hl[~((hl["월"] == month) & (hl["구분"] == "주차") & (hl["주차"].map(_wnum) > target_week))].copy()
    return hl


def trim_master_headline(period_id: str, cutoffs: Dict[str, int]) -> None:
    """전체 집계 재료(master_headline) 트림 — 제출 부서만 + 기준 주차 이후 주차 제거.
    master_detail 이 이 headline 으로 칩/요약/차트/항목을 매 요청마다 재집계하므로,
    headline 만 잘라도 전체 뷰의 집계가 모두 정합해진다."""
    f = period_dir(period_id) / MASTER_FILE
    if not f.exists():
        return
    try:
        hl = pd.read_csv(f)
    except Exception:
        return
    if not len(hl):
        return
    hl = hl[hl["항목"].isin(list(cutoffs))].copy()

    def _keep(r) -> bool:
        if r["구분"] == "주차":
            return _wnum(r["주차"]) <= cutoffs.get(r["항목"], 0)
        return True

    if len(hl):
        hl = hl[hl.apply(_keep, axis=1)]
    hl.to_csv(f, index=False, encoding="utf-8")


def trim_master_table(period_id: str, cutoffs: Dict[str, int]) -> None:
    """전체 종합 표(master_table) 트림 — 제출 부서 행만 남기고 주차 트림, 합계행 재합산.

    합계/합계(H제외) 행은 빌드 시점에 비제출 부서·미래 주차까지 포함해 계산돼 있다.
    제출 부서의 L0(Area 총계) 행만 남겨 트림한 뒤, 그 행들로 합계행을 **다시 합산**한다
    (월별·주차별·달성률). → 보고서 전체 종합이 area_tables/실적관리와 동일 데이터가 됨.
    """
    f = period_dir(period_id) / MASTER_TABLE_FILE
    if not f.exists():
        return
    try:
        mt = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return
    months = mt.get("months", [])
    bold = [r for r in mt.get("rows", []) if r.get("bold")]
    # 제출 부서 행만 남기고 주차 트림 (L0 총계 + L1 세부 모두)
    kept: List[dict] = []
    for r in mt.get("rows", []):
        if r.get("bold"):
            continue
        a = r.get("area")
        if a not in cutoffs:
            continue
        cw = cutoffs[a]
        for cell in (r.get("cells") or {}).values():
            wks = cell.get("weeks")
            if wks:
                cell["weeks"] = [w for w in wks if _wnum(w.get("주차")) <= cw]
        kept.append(r)
    l0 = [r for r in kept if r.get("level") == 0]

    def _resum(exclude_h: bool) -> Dict[str, dict]:
        src = [r for r in l0 if not (exclude_h and r.get("area") == registry.DERIVED_SLUG)]
        cells: Dict[str, dict] = {}
        for m in months:
            t = a = 0.0
            ht = ha = False
            wk: Dict[str, dict] = {}
            for r in src:
                c = (r.get("cells") or {}).get(str(m))
                if not c:
                    continue
                if c.get("목표") is not None:
                    t += c["목표"]; ht = True
                if c.get("실적") is not None:
                    a += c["실적"]; ha = True
                for w in c.get("weeks", []):
                    e = wk.setdefault(w["주차"], {"목표": 0.0, "실적": 0.0, "ht": False, "ha": False})
                    if w.get("목표") is not None:
                        e["목표"] += w["목표"]; e["ht"] = True
                    if w.get("실적") is not None:
                        e["실적"] += w["실적"]; e["ha"] = True
            weeks = [
                {"주차": k, "목표": v["목표"] if v["ht"] else None, "실적": v["실적"] if v["ha"] else None,
                 "달성률": round(v["실적"] / v["목표"] * 100, 1) if v["ht"] and v["목표"] else None}
                for k, v in sorted(wk.items(), key=lambda kv: _wnum(kv[0]))
            ]
            cells[str(m)] = {
                "목표": round(t, 2) if ht else None,
                "실적": round(a, 2) if ha else None,
                "달성률": round(a / t * 100, 1) if ht and t else None,
                "weeks": weeks,
            }
        return cells

    for r in bold:
        r["cells"] = _resum(exclude_h="제외" in str(r.get("label", "")))
    mt["rows"] = bold + kept
    f.write_text(json.dumps(mt, ensure_ascii=False), encoding="utf-8")


def _load_log(period_id: str) -> dict:
    f = period_dir(period_id) / SUBMIT_LOG
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _log_submission(period_id: str, items: List[str],
                    kinds: Optional[Dict[str, str]] = None) -> None:
    """업로드된 항목별 제출 횟수 +1, 마지막 제출 시각 갱신.

    kinds: 항목별 이번 제출 구분(_submission_kind) — 상태칸(latest_status)이
    '신규 시점 제출'과 '재제출(정정)'을 구분하는 데 사용(제출 횟수만으로는 신규 시점도 재제출로 오판).
    """
    f = period_dir(period_id) / SUBMIT_LOG
    log = _load_log(period_id)
    now = datetime.now().isoformat(timespec="seconds")
    for it in items:
        rec = log.get(it, {"count": 0, "last_at": None})
        rec["count"] = int(rec.get("count", 0)) + 1
        rec["last_at"] = now
        if kinds and it in kinds:
            rec["last_kind"] = kinds[it]
        log[it] = rec
    f.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def list_stored_periods() -> List[str]:
    """저장된 회차(스냅샷) 목록 — data/{회차}/ 직접 순회.
    ⚠️ '-sim'(시뮬레이션 변경적용 스냅샷)은 내부용이라 제외 — 회차 목록·최신회차·latest_status 미오염.
    (시뮬 스냅샷은 보고서 엔드포인트 snap= 으로만 명시 접근.)"""
    if not DATA_DIR.exists():
        return []
    return sorted(p.name for p in DATA_DIR.iterdir() if p.is_dir() and not p.name.endswith("-sim"))


def previous_period(period_id: str) -> Optional[str]:
    """저장된 회차 중 period_id 바로 직전 회차. 없으면 None."""
    periods = list_stored_periods()
    earlier = [p for p in periods if p < period_id]
    return earlier[-1] if earlier else None


# 정합성 비교 키 — 같은 셀을 가리키는 의미 좌표 (실적 한 칸을 유일 식별)
_CMP_KEYS = ["항목", "부서경로", "연도", "월", "구분", "주차", "종류"]


def compare_periods(prev_id: str, curr_id: str, eps: float = 0.01) -> dict:
    """직전 회차(prev) 대비 현재 회차(curr)에서 **과거 실적이 바뀌었는지** 검증.

    겹치는 셀(둘 다 존재) 중 값이 다르면 = 확정됐어야 할 과거값이 변경됨 → 경고.
    prev 엔 있는데 curr 에서 사라진 셀(과거 데이터 삭제)도 함께 보고.
    당해(올해) 실적만 대상 — 작년 실적/목표 재계획은 제외.
    """
    a = load_period(prev_id)
    b = load_period(curr_id)
    out = {"prev": prev_id, "curr": curr_id, "compared": 0,
           "changed": [], "removed": []}
    if not len(a) or not len(b):
        return out

    def _actuals(df):
        d = df[df["종류"] == "실적"].copy()
        if "연도구분" in d.columns:
            d = d[d["연도구분"] == "당해"]
        for k in _CMP_KEYS:
            if k not in d.columns:
                d[k] = None
        d["주차"] = d["주차"].fillna("")
        return d

    da, db = _actuals(a), _actuals(b)
    ka = da.set_index(_CMP_KEYS)["값"]
    kb = db.set_index(_CMP_KEYS)["값"]
    ka = ka[~ka.index.duplicated()]
    kb = kb[~kb.index.duplicated()]
    common = ka.index.intersection(kb.index)
    out["compared"] = int(len(common))

    for key in common:
        va, vb = ka[key], kb[key]
        try:
            if abs(float(va) - float(vb)) > eps:
                out["changed"].append(_diff_row(key, va, vb))
        except (TypeError, ValueError):
            if va != vb:
                out["changed"].append(_diff_row(key, va, vb))

    removed_idx = ka.index.difference(kb.index)
    for key in removed_idx:
        out["removed"].append(_diff_row(key, ka[key], None))

    # 보기 좋게: 변경분 절대 delta 큰 순
    out["changed"].sort(key=lambda r: abs(r.get("delta") or 0), reverse=True)
    return out


def _diff_row(key, old, new) -> dict:
    d = dict(zip(_CMP_KEYS, key))
    o = None if old is None else float(old)
    n = None if new is None else float(new)
    return {
        "항목": d["항목"], "부서경로": d["부서경로"], "연도": int(d["연도"]),
        "월": int(d["월"]), "주차": d["주차"] or None,
        "old": o, "new": n,
        "delta": (n - o) if (o is not None and n is not None) else None,
    }


def list_sources(period_id: str) -> List[str]:
    """회차 안의 **항목** CSV 목록 — 제출 현황(들어온 항목) 표시용."""
    d = period_dir(period_id)
    if not d.exists():
        return []
    # 항목 CSV 만 (언더스코어 시작 = 내부 파일: _master_headline 등 제외)
    return sorted(p.stem for p in d.glob("*.csv") if not p.stem.startswith("_"))


def load_period(period_id: str) -> pd.DataFrame:
    """회차 폴더의 항목별 CSV 를 모두 읽어 합쳐 반환.

    집계·보고서·웹 표시가 모두 이 함수로 raw 를 모아 쓴다.
    (파일명 = 항목이라 별도 출처 컬럼 불필요 — `항목` 컬럼이 그 역할)
    """
    d = period_dir(period_id)
    empty = pd.DataFrame(columns=RAW_COLUMNS)
    if not d.exists():
        return empty
    files = [f for f in sorted(d.glob("*.csv")) if not f.stem.startswith("_")]
    frames = [pd.read_csv(f, encoding="utf-8-sig") for f in files]
    return pd.concat(frames, ignore_index=True) if frames else empty


def delete_source(period_id: str, source_name: str) -> bool:
    """특정 출처 CSV 삭제 (잘못 올린 회신 제거)."""
    f = period_dir(period_id) / f"{_safe(source_name)}.csv"
    if f.exists():
        f.unlink()
        return True
    return False


def remove_area(period_id: str, area: str) -> None:
    """항목(area) 데이터·캐시를 회차에서 **완전 제거** — 그 항목 마지막 제출본까지 삭제한 경우.

    raw CSV + 보고서 캐시 3종(headline/master_table/area_table) + 제출 로그에서 그 항목을 빼고,
    master_table 합계행(bold)은 남은 항목들로 재합산. → /reports·/data 에서 '미수신'으로 보임.
    (남은 버전이 있으면 이 함수 대신 save_excel(log=False) 재적재로 그 버전으로 되돌림.)
    ⚠️ 고정비 컴포넌트 제거 시 파생 고정비 재계산은 별도 — 남은 컴포넌트 워크북 필요(기존 미결).
    """
    d = period_dir(period_id)
    if not d.exists():
        return
    with _CACHE_LOCK:   # save_excel 캐시 쓰기와 직렬화(동시 삭제·업로드 충돌 방지)
        _remove_area_locked(d, area)


def _remove_area_locked(d: Path, area: str) -> None:
    # 1) raw CSV
    (d / f"{_safe(area)}.csv").unlink(missing_ok=True)
    # 2) master_headline — 그 항목 행 제거(없으면 파일 자체 삭제)
    hf = d / MASTER_FILE
    if hf.exists():
        try:
            hl = pd.read_csv(hf, encoding="utf-8-sig")
            hl = hl[hl["항목"] != area]
            if len(hl):
                hl.to_csv(hf, index=False, encoding="utf-8-sig")
            else:
                hf.unlink(missing_ok=True)
        except Exception:
            pass
    # 3) master_table — 비-bold 그 항목 행 제거 + 합계행 재합산(나머지 항목 유지)
    mf = d / MASTER_TABLE_FILE
    if mf.exists():
        try:
            t = json.loads(mf.read_text(encoding="utf-8"))
            rows = t.get("rows") or []
            months = t.get("months") or []
            kept = [r for r in rows if not r.get("bold") and r.get("area") != area]
            bold = [dict(r) for r in rows if r.get("bold")]
            if kept:
                l0 = [r for r in kept if r.get("level") == 0]
                for r in bold:
                    r["cells"] = _resum_bold(l0, months, "제외" in str(r.get("label", "")))
                t["rows"] = bold + kept
                mf.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
            else:
                mf.unlink(missing_ok=True)   # 마지막 항목이었으면 표 비움
        except Exception:
            pass
    # 4) area_table — 그 항목 엔트리 제거
    af = d / AREA_TABLE_FILE
    if af.exists():
        try:
            tables = json.loads(af.read_text(encoding="utf-8"))
            if area in tables:
                tables.pop(area, None)
                if tables:
                    af.write_text(json.dumps(tables, ensure_ascii=False), encoding="utf-8")
                else:
                    af.unlink(missing_ok=True)
        except Exception:
            pass
    # 5) 제출 로그 — 그 항목 빼기(→ submission_status 에서 미수신)
    lf = d / SUBMIT_LOG
    if lf.exists():
        try:
            slog = json.loads(lf.read_text(encoding="utf-8"))
            if area in slog:
                slog.pop(area, None)
                lf.write_text(json.dumps(slog, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def _progress(df: pd.DataFrame, area: str, unit: str) -> dict:
    """항목별 진척 — 당해 실적이 들어온 단위(주차/월) 개수 / 기대 개수.

    주차형: 당해 실적 주차행의 distinct (월,주차) 수.  월형: distinct 월 수.
    기대치는 양식상 최대(주차 24·월 12) 기준 — 미래월 미입력은 자연히 분모 대비 낮게.
    """
    sub = df[(df["항목"] == area) & (df["종류"] == "실적")]
    if "연도구분" in sub.columns:
        sub = sub[sub["연도구분"] == "당해"]
    if unit == "주차":
        wk = sub[sub["구분"] == "주차"]
        filled = int(wk.groupby(["월", "주차"]).ngroups) if len(wk) else 0
        return {"unit": "주차", "filled": filled, "expected": 24}
    mo = sub[sub["구분"] == "월계"]
    filled = int(mo["월"].nunique()) if len(mo) else 0
    return {"unit": "월", "filled": filled, "expected": 12}


def submission_status(period_id: str) -> dict:
    """기대 Area(EXPECTED_AREAS) 대비 수신/미수신 — Area 단위 제출 현황.

    파생(H)은 제출 대상 아님 → derived=True 로만 표기. 수신된 Area 는 진척(주차/월)도 함께.
    """
    received = set(list_sources(period_id))
    df = load_period(period_id) if received else pd.DataFrame(columns=RAW_COLUMNS)
    log = _load_log(period_id)

    items = []
    for area, meta in AREA_META.items():
        rec = log.get(area, {})
        count = int(rec.get("count", 0))
        last_at = rec.get("last_at")
        if meta["source"] == "파생":
            items.append({
                "항목": area, "source": "파생", "unit": meta["unit"],
                "derived": True, "received": False, "progress": None,
                "count": 0, "last_at": None,
                "derived_from": meta.get("derived_from", []),
            })
            continue
        got = area in received
        prog = _progress(df, area, meta["unit"]) if (got and len(df)) else None
        items.append({
            "항목": area, "source": meta["source"], "unit": meta["unit"],
            "derived": False, "received": got, "progress": prog,
            "count": count, "last_at": last_at,
        })

    missing = [it["항목"] for it in items if not it["derived"] and not it["received"]]
    return {
        "period_id": period_id,
        "expected": EXPECTED_AREAS,
        "received": sorted(received),
        "missing": missing,
        "items": items,
    }


# ─────────────────────────────────────────────
# 부서별 "최신 주차" 상태 (실적 관리 화면) — latest-wins
# ─────────────────────────────────────────────

# 주차(W#) → (월, 그 달의 몇 주차). ⚠️ ver0.1(2026-06-24 '주차추가') 양식 기준:
#   1월=W1-5, 2월=W6-9, 3월=W10-14, 4월=W14-18 (W14=3·4월 경계 → 4월 1차로).
# 양식의 월별 주차 묶음을 그대로 반영(전 양식과 번호 체계 다름). 데이터는 1~4월.
# 5월+ 는 LG 추가 데이터 도착 시 확장(현재 미매핑 → week_label 이 'W##' fallback).
def _build_week_month(year: int) -> Dict[int, Tuple[int, int]]:
    """주차→(월, 월중차수) 를 **주차 규칙으로 자동 생성**(하드코딩 달력표 없음).

    규칙: 한 주 = **일요일~토요일**, W1 = 그 해 1/1 을 포함하는 주(일요일 시작).
          그 주가 속한 달 = **그 주 목요일이 있는 달**(주의 과반 = ISO 주차 규칙).
    연도만 바꾸면 어느 해든 1~12월 전부 자동 — 실 운영 무관(데이터의 주차 번호를 라벨링/경계 판정).
    """
    from datetime import date, timedelta
    jan1 = date(year, 1, 1)
    w1_sun = jan1 - timedelta(days=(jan1.weekday() + 1) % 7)   # 1/1 직전(포함) 일요일
    wm: Dict[int, Tuple[int, int]] = {}
    counts: Dict[int, int] = {}
    n = 1
    while True:
        thu = w1_sun + timedelta(days=(n - 1) * 7 + 4)         # 그 주 목요일
        if thu.year != year:
            break
        counts[thu.month] = counts.get(thu.month, 0) + 1
        wm[n] = (thu.month, counts[thu.month])
        n += 1
    return wm


# 데이터 연도 기준 자동 생성(현재 데이터 = 2026). ⚠️ 손으로 적은 달력표 아님 — 규칙으로 계산.
WEEK_MONTH: Dict[int, Tuple[int, int]] = _build_week_month(2026)


def week_label(iso_week) -> str:
    """ISO 주차 → 'N월 W##'(월 + 주차번호). 매핑 밖이면 'W##', 없으면 '—'. (표기 통일 = 주차번호 W)"""
    if iso_week is None:
        return "—"
    w = int(iso_week)
    mw = WEEK_MONTH.get(w)
    return f"{mw[0]}월 W{w}" if mw else f"W{w}"


# 한 주 = **일요일~토요일**. W1 = 2026년 1월을 포함하는 첫 주(일=2025-12-28). 각 W = 7일.
# 검증: 2026-02-01·03-01 이 일요일 → 2월=W6~9·3월=W10~14 와 정합(WEEK_MONTH 와 일치),
#       경계주 W14(3/29~4/4)가 4/1 포함 → 3·4월 양쪽에 걸침.
# ⚠️ LG 가 기준 주를 다르게 잡으면 WEEK1_START 한 줄만 수정.
WEEK1_START = date(2025, 12, 28)


def week_dates(iso_week) -> Optional[Tuple[date, date]]:
    """ISO 주차번호 → (시작 일요일, 끝 토요일). 'W14는 며칠?' 같은 질문 응답용. 없으면 None."""
    if iso_week is None:
        return None
    start = WEEK1_START + timedelta(weeks=int(iso_week) - 1)
    return start, start + timedelta(days=6)


# 제출 양식 구분 — 표준 엑셀양식(A·B·D·G·L) / 부서마다 다른 양식(C·E·F·I·J·K).
# ⚠️ 둘 다 부서가 메일로 보내주고 운영자가 받아서 업로드 → 전부 제출/독촉 대상.
#    (옛 AREA_META 의 source '부서'/'운영자' 는 '누가 만드냐'가 아니라 '양식 종류' 의미)
def area_format(source: str) -> str:
    return "표준양식" if source == "부서" else "별도양식"


def _pair_label(pair: Optional[Tuple[int, int]]) -> str:
    """(월, ISO주차) → 'N월 W##'. 경계주도 월이 데이터에 있으므로 그 월 그대로 라벨."""
    return f"{pair[0]}월 W{pair[1]}" if pair else "—"


def _all_week_pairs(period: Optional[str]) -> set:
    """양식이 정의한 **(월, ISO주차) 쌍 전부** — 목표(계획) 주차 행 기준(경계주 = 두 달 각각 포함).
    미제출 감지의 '있어야 할 주차' 단일 소스(데이터 기준 — 하드코딩 달력 아님)."""
    if not period:
        return set()
    df = load_period(period)
    if not len(df):
        return set()
    tgt = df[(df["종류"].isin(["목표", "계획"])) & (df["구분"] == "주차")]
    if "연도구분" in tgt.columns:
        tgt = tgt[tgt["연도구분"] == "당해"]
    return {(int(m), _wnum(x)) for m, x in zip(tgt["월"], tgt["주차"])
            if pd.notna(m) and _wnum(x)}


def _month_last_iso(all_pairs: set, m: int) -> int:
    """그 달(m)의 마지막 ISO 주차 — 양식 기준(경계주 포함). '마감'(그 달 끝 도달) 판정용."""
    isos = [iso for (mm, iso) in all_pairs if mm == m]
    return max(isos) if isos else 0


def _area_present(area: str, period: Optional[str]) -> Tuple[set, set]:
    """그 회차 CSV 에서 area 의 당해 실적이 들어온 **(월, ISO주차) 쌍 set** + 월계 월 set.

    ⚠️ 경계주(예 W14 = 3월·4월 양쪽) 구분 위해 ISO 번호만이 아니라 **(월, 주차) 쌍**으로 추적한다.
       → '3월 W14'와 '4월 W14'를 다른 시점으로 봄(각각 미제출/현재시점 감지). 월계 = 월 집합.
    """
    if not period:
        return set(), set()
    f = period_dir(period) / f"{_safe(area)}.csv"
    if not f.exists():
        return set(), set()
    df = pd.read_csv(f, encoding="utf-8-sig")
    d = df[df["종류"] == "실적"]
    if "연도구분" in d.columns:
        d = d[d["연도구분"] == "당해"]
    wk = d[d["구분"] == "주차"]
    weeks = {(int(m), _wnum(x)) for m, x in zip(wk["월"], wk["주차"])
             if pd.notna(m) and _wnum(x)}
    months = {int(x) for x in d[d["구분"] == "월계"]["월"].dropna()}
    return weeks, months


def _area_latest(area: str, period: str) -> Tuple[Optional[Tuple[int, int]], Optional[int]]:
    """그 회차 CSV 에서 area 의 당해 실적 최신 ((월,ISO주차) 쌍, 월). 월형은 주차쌍=None.
    쌍의 max = (월, 주차) 사전식 = 시간순 최신(경계주도 월로 정렬)."""
    weeks, months = _area_present(area, period)
    return (max(weeks) if weeks else None, max(months) if months else None)


def _report_present(period_id: Optional[str]) -> Dict[str, Tuple[set, set]]:
    """리포트 항목(REPORT_ITEMS)별 raw 실적 present — {슬러그: ((월,ISO) 쌍 set, 월계 월 set)}.

    파생(고정비)은 구성요소(derived_from) 합집합. 빈 템플릿 셀이 0으로 평가돼 생기는 phantom 주차와
    **실제 들어온 주차**를 구별하는 단일 소스(보고서 마스킹·드롭다운·경계주 처리 공통).
    """
    pid = period_id or current_period()
    res: Dict[str, Tuple[set, set]] = {}
    if not pid:
        return res
    for slug in registry.REPORT_ITEMS:
        meta = registry.BY_SLUG.get(slug, {})
        if meta.get("source") == "파생":
            wk: set = set(); mo: set = set()
            for c in meta.get("derived_from", []):
                cw, cm = _area_present(c, pid)
                wk |= cw; mo |= cm
            res[slug] = (wk, mo)
        else:
            res[slug] = _area_present(slug, pid)
    return res


def present_weeks_by_month(period_id: Optional[str] = None) -> Dict[int, List[int]]:
    """월별 실제 실적이 들어온 ISO 주차 목록(전 리포트 항목 합집합, 정렬).

    보고서 주차 드롭다운/캡 소스 — config 고정 차수(MONTH_WEEKS)가 아니라 **데이터에 실제 있는 주차**만.
    경계주(예 5월 W18)도 데이터가 있으면 그대로 포함(WEEK_MONTH 정준월과 무관).
    """
    pid = period_id or current_period()
    out: Dict[int, set] = {}
    for wk, _mo in _report_present(pid).values():
        for (m, iso) in wk:
            out.setdefault(m, set()).add(iso)
    return {m: sorted(v) for m, v in out.items()}


def mask_headline_to_present(hl, period_id: Optional[str] = None):
    """master_headline(df)의 **주차 행** 중 raw 실적에 실제 없는 (항목,월,ISO)를 제거.

    빈 템플릿 주차 셀이 0으로 평가돼 phantom 주차(예 5월 W19~)가 카드/그래프/집계에 새는 것 차단.
    → 잠정 채움이 '마지막 실제 주차'(예 5월 W18)를 집어 집계가 올바르게 확정. 월계 행은 유지.
    과거 완결월은 raw 에 전 주차가 있어 무손실(검증됨).
    """
    if hl is None or not len(hl):
        return hl
    pres = _report_present(period_id)

    def _ok(row) -> bool:
        if row.get("구분") != "주차":
            return True
        pair = pres.get(row.get("항목"))
        if pair is None:
            return True   # 미등록 항목(방어) — 건드리지 않음
        return (int(row["월"]), _wnum(row["주차"])) in pair[0]

    return hl[hl.apply(_ok, axis=1)].reset_index(drop=True)


def mask_table_to_present(table: dict, period_id: Optional[str] = None,
                          area: Optional[str] = None) -> dict:
    """표(master/area) 각 셀의 weeks 를 raw 실적 present 로 필터 — phantom 주차 제거.

    - 주차: (항목,월,ISO) 가 raw 실적에 없으면 그 주차 셀 제거(빈 템플릿 0 컬럼 안 보이게).
    - 월: 그 달 실적(주차·월계) 이 전혀 없으면 **실적/달성률/잠정 공란**(목표는 유지 — 목표는 전월 정의됨).
    합계행(bold)은 sync_bold_to_detail / 재합산이 처리하므로 건드리지 않음.
    area 지정(개별 Area 표) 시 전 행을 그 항목 기준으로 필터.
    """
    pres = _report_present(period_id)
    for row in table.get("rows", []):
        if row.get("bold"):
            continue
        a = area or row.get("area")
        pair = pres.get(a)
        if pair is None:
            continue
        wk_pairs, mo_set = pair
        months_present = {m for (m, _iso) in wk_pairs} | set(mo_set)
        for mk, cell in (row.get("cells") or {}).items():
            try:
                mo = int(mk)
            except (TypeError, ValueError):
                continue
            wks = cell.get("weeks")
            if wks:
                cell["weeks"] = [w for w in wks if (mo, _wnum(w.get("주차"))) in wk_pairs]
            if mo not in months_present:
                cell["실적"] = None
                cell["달성률"] = None
                cell["잠정"] = False
    return table


def _incomplete_cells(area: str, period: Optional[str]) -> List[dict]:
    """leaf '중간 구멍' 감지 — **셀 단위 누락**(다른 주차엔 실적을 내는 라인이 이 주차만 빔).

    한 부서경로(leaf)가 어떤 주차들엔 실적을 내는데, 그 활동 구간(첫 실적~마지막 실적) **사이**의
    어떤 주차에 목표는 있으나 실적이 빈 경우 = 내다가 빠뜨린 진짜 구멍. ⚠️ '한 번도 실적 없는
    라인'(목표만 있는 구조적 품목)·'아직 시점 안 온 뒷주차'는 제외(오탐 방지). 주차 셀만.

    ⚠️ **수식 평가본(area_table) 기준** — raw CSV(parsing_lg)는 수식 셀을 버려서, 수식으로 채운
    셀(예 '=M23+14')을 '빈 칸'으로 오판한다. area_table 은 수식을 평가한 값을 담으므로 '진짜 빈 셀'만
    None → 정확. (소계/Rate 행 제외, leaf 행만.)
    반환: 영향 주차별 [{월, 주차(ISO), label, n(빈 셀 수), leaves}], 없으면 [].
    """
    if not period:
        return []
    t = load_area_table(period, area)
    rows = [r for r in t.get("rows", []) if not r.get("is_subtotal") and not r.get("is_rate")]
    if not rows:
        return []
    # (월, ISO주차) 쌍으로 추적 — 경계주(3월 W14 vs 4월 W14) 구분. 셀의 월 키(mk)를 함께 씀.
    act_by_leaf: Dict[str, set] = {}   # 부서경로 → 실적 든 (월,주차)
    tgt_by_leaf: Dict[str, set] = {}   # 부서경로 → 목표 든 (월,주차)
    present_w: set = set()             # 받은 (월,주차) = 어느 leaf든 실적 있는
    for r in rows:
        dp = r.get("부서경로")
        for mk, cell in (r.get("cells") or {}).items():
            m = int(mk) if str(mk).isdigit() else None
            if m is None:
                continue
            for w in cell.get("weeks", []):
                iso = _wnum(w.get("주차"))
                if not iso:
                    continue
                key = (m, iso)
                if w.get("실적") is not None:
                    act_by_leaf.setdefault(dp, set()).add(key)
                    present_w.add(key)
                if w.get("목표") is not None:
                    tgt_by_leaf.setdefault(dp, set()).add(key)
    bywk: Dict[tuple, List[str]] = {}
    for dp, tgts in tgt_by_leaf.items():
        aw = act_by_leaf.get(dp)
        if not aw:                              # 한 번도 실적 없는 구조적 라인 → 제외
            continue
        for (m, iso) in tgts:
            # 활동구간은 **그 달 안에서** 판정(경계 월 섞이면 min/max 왜곡).
            aw_m = {i for (mm, i) in aw if mm == m}
            if not aw_m:
                continue
            # 받은 주차 + 이 leaf 그 달 활동구간 사이인데 이 주차만 빔 = 부분 구멍.
            if (m, iso) in present_w and min(aw_m) <= iso <= max(aw_m) and iso not in aw_m:
                bywk.setdefault((m, iso), []).append(str(dp))
    return [{"월": m, "iso": iso, "주차": iso, "label": f"{m}월 W{iso}",
             "n": len(set(leaves)), "leaves": sorted(set(leaves))}     # 빠진 부서경로(leaf) 목록
            for (m, iso), leaves in sorted(bywk.items())]


def _load_remindlog(period_id: str) -> dict:
    f = period_dir(period_id) / REMIND_LOG
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def record_remind(period_id: str, keys: List[str]) -> None:
    """요청(독촉) 발송 기록 — **조각(piece) 단위**. key='{area}:{종류}:{월}'.

    조각별로 (발송 시각 + 그때 내용 서명) 저장 → 조각 내용 바뀌거나 해소되면 latest_status 가
    '요청함' 자동 해제. 재발송도 시각·서명 갱신. 해소된(현재 없는) 조각은 로그에서 정리(무한누적 방지).
    """
    d = period_dir(period_id)
    d.mkdir(parents=True, exist_ok=True)
    cur = {g["key"]: g for it in latest_status()["items"] for g in it.get("gaps", [])}
    log = _load_remindlog(period_id)
    now = datetime.now().isoformat(timespec="seconds")
    for k in keys:
        g = cur.get(k)
        if g:
            prev = log.get(k) or {}
            log[k] = {"sent_at": now, "sig": _piece_sig(g),
                      "count": int(prev.get("count", 0)) + 1}   # 재발송 누적 = 반복 미제출 가시화
    log = {k: v for k, v in log.items() if k in cur}   # 해소된 조각 정리(데이터 오면 자동 해소)
    (d / REMIND_LOG).write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _expected_weeks(cur_week: int) -> set:
    """현재 주차(cur_week)까지 들어와 있어야 할 주차 집합 (양식상 정의된 주차만)."""
    return {w for w in WEEK_MONTH if w <= cur_week}


def _gap_pieces(area: str, missing_weeks: List[Tuple[int, int]], missing_months: List[int],
                incomplete: Optional[List[dict]] = None) -> List[dict]:
    """빠진 것을 '조각'(종류·월 단위)으로 분해 — 각각 따로 요청 가능.

    월계 조각 = 그 달 마감(월 전체실적) 미도착. 주차 조각 = 누락 (월, 주차)별(경계주 = 월별로 따로).
    부분 조각 = 받은 주차인데 그 안 일부 leaf 실적만 빔(어느 부서경로가 빠졌는지 leaves 동반).
    key = '{area}:{종류}:{월}' 또는 '{area}:주차:{월}-{ISO주차}'(경계주 구분).
    """
    pieces: List[dict] = []
    for m in sorted(missing_months):
        pieces.append({"key": f"{area}:월계:{m}", "kind": "월계", "월": m, "iso": None,
                       "label": f"{m}월 마감", "weeks": []})
    # 주차는 **각 (월,주차)별로 따로** — 경계주(3월 W14 vs 4월 W14)도 구분. key=주차:{월}-{ISO}
    for (m, iso) in sorted(missing_weeks):
        pieces.append({"key": f"{area}:주차:{m}-{iso}", "kind": "주차", "월": m, "iso": iso,
                       "label": f"{m}월 W{iso}", "weeks": [iso]})
    # 부분(셀 단위) 조각 — 받은 주차 안 일부 leaf 실적 누락. 빠진 부서경로(leaves) 동반.
    for x in (incomplete or []):
        m, iso = x["월"], x.get("iso", x.get("주차"))
        pieces.append({"key": f"{area}:부분:{m}-{iso}", "kind": "부분", "월": m, "iso": iso,
                       "label": f"{x['label']} 일부", "weeks": [iso],
                       "n": x["n"], "leaves": x.get("leaves", [])})
    return pieces


def _piece_sig(pc: dict) -> str:
    """조각 서명 — 내용 바뀌면(주차 일부 도착·빈 셀 채워짐 등) '요청함' 자동 해제용."""
    kind = pc.get("kind")
    if kind == "월계":
        return f"m{pc.get('월')}"
    if kind == "부분":   # 빠진 leaf 집합이 바뀌면(채워지면) 서명 변화 → 자동 해제
        return f"p{pc.get('월')}-{pc.get('iso')}:{sorted(pc.get('leaves', []))}"
    return f"w{pc.get('월')}-{pc.get('iso')}"   # 주차 = (월, ISO) 로 서명(경계주 구분)


def _gap_sig(missing_weeks: List[int], missing_months: List[int]) -> str:
    """'지금 빠진 것'의 서명 — 요청 시점의 빠진 내용과 비교해 '요청함'을 자동 무효화하는 키.
    빠진 내용이 바뀌면(새 누락·일부 도착) 서명이 달라져 옛 요청 표시가 눌어붙지 않는다."""
    return f"w{sorted(missing_weeks)}|m{sorted(missing_months)}"


def _gap_summary(missing_weeks: List[int], missing_months: List[int], has_data: bool) -> str:
    """빠진 것 사람이 읽을 요약 — 예: '1월 월계, 2월 2~4차'. 데이터 자체가 없으면 '전체 미제출'."""
    if not has_data:
        return "전체 미제출"
    parts: List[str] = []
    for m in sorted(missing_months):          # 지난 달 월 전체실적(마감) 누락 먼저
        parts.append(f"{m}월 마감")
    bym: Dict[int, List[int]] = {}            # 주차 누락 = 달별로 묶어 'N월 W##~W##'
    for (m, iso) in sorted(missing_weeks):    # (월, ISO주차) 쌍
        bym.setdefault(m, []).append(iso)
    for mo in sorted(bym):
        ws = sorted(bym[mo])
        parts.append(f"{mo}월 W{ws[0]}" if len(ws) == 1 else f"{mo}월 W{ws[0]}~W{ws[-1]}")
    return ", ".join(parts) if parts else "—"


def _prov_months_all(area_period: Dict[str, str]) -> Dict[str, set]:
    """항목별 area_table 에서 **잠정(마감 미도착) 셀이 있는 달** 집합. {area: {월}}.

    '마감 완전 도착' 판정용 — 그 달에 잠정 셀이 하나도 없으면 그 항목 그 달은 완전 마감.
    (area_table 캐시 = 잠정 단일 소스. 회차 폴더 _area_tables.json 한 번만 읽음.)
    """
    out: Dict[str, set] = {}
    cache: Dict[str, dict] = {}
    for area, period in area_period.items():
        if period not in cache:
            f = period_dir(period) / AREA_TABLE_FILE
            try:
                cache[period] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            except Exception:
                cache[period] = {}
        ms: set = set()
        for r in (cache[period].get(area) or {}).get("rows", []):
            for mk, c in (r.get("cells") or {}).items():
                if isinstance(c, dict) and c.get("잠정"):
                    try:
                        ms.add(int(mk))
                    except (TypeError, ValueError):
                        pass
        out[area] = ms
    return out


def submission_filename(area: str, period: Optional[str]) -> str:
    """업로드 보관용 정규화 파일명 — '{항목라벨}_{시점}_제출.xlsx' (예: 재료비_5월3차_제출.xlsx).

    올린 파일 이름이 뭐든 이 깔끔한 이름으로 docstore 에 보관.
    시점 = 주차형이면 'N월 M차', 월형이면 'N월', 못 구하면 회차.
    항목 표기 = 한글 라벨(registry). 파일명 안전화는 호출부(docstore)가 처리.
    """
    wk, mo = _area_latest(area, period) if period else (None, None)
    meta = AREA_META.get(area, {})
    if meta.get("unit") == "주차" and wk:
        when = _pair_label(wk).replace(" ", "")   # (월,주차) 쌍 → 'N월W##'
    elif mo:
        when = f"{mo}월"
    else:
        when = str(period or "미상")
    label = registry.label_for(area)
    return f"{label}_{when}_제출.xlsx"


def latest_status() -> dict:
    """항목별 '최신 시점' + **데이터 기준 빠진 것 세밀 감지** (실적 관리 화면).

    핵심: 각 항목은 주차값(W#)과 **월계(월 전체실적)** 둘 다 들어오는데, 월계는 주차보다
    늦게 도착한다(예: 1월 월계는 2월 2차쯤). 그래서 '빠진 것' = (현재 주차까지의 누락 주차)
    + (이미 지난 달인데 아직 안 온 월계). 데이터(CSV)를 직접 훑어 둘 다 찾는다.

    - 현재 주차(cur_week) = 주차형 항목들 중 가장 앞선 주차. cur_month = 그 주차의 달.
    - **닫힌 달** = cur_month 이전 달(1..cur_month-1) → 그 달 월계는 이미 도착했어야 함.
      현재 달(cur_month) 월계는 아직 진행 중이라 기대 안 함(누락 아님).
    - 주차형: 누락 = (≤cur_week 인데 없는 주차) + (닫힌 달인데 없는 월계).
    - 월형(주차 없음): 누락 = 닫힌 달인데 없는 월계.
    - has_gap = 누락이 하나라도 있으면 True → received=False(요청 대상). 빠진 게 없으면 입력완료.
    - requested/requested_at = 그 항목에 요청(독촉) 보낸 적 있나(_remindlog). 데이터 들어와
      누락이 사라지면 요청 목록에서 빠지며 잠금 자동 해제.
    """
    periods = list_stored_periods()
    area_period: Dict[str, str] = {}
    for p in periods:
        for a in list_sources(p):
            area_period[a] = p

    present: Dict[str, Tuple[set, set]] = {}     # area → ((월,주차) 쌍 set, 월계 월 set)
    cur_pair: Optional[Tuple[int, int]] = None   # 현재 (월, ISO주차) — 쌍 정렬=시간순(경계주도 월로)
    for area, meta in AREA_META.items():
        if meta["source"] == "파생":
            continue
        wks, mos = _area_present(area, area_period.get(area))
        present[area] = (wks, mos)
        if wks and meta["unit"] == "주차":          # 현재 = 주차형 항목 중 가장 앞선 (월,주차)
            mx = max(wks)
            if cur_pair is None or mx > cur_pair:
                cur_pair = mx
    cur_month = cur_pair[0] if cur_pair else 0
    cur_week = cur_pair[1] if cur_pair else 0     # ISO (current_week 필드/하위호환)
    closed_months = set(range(1, cur_month)) if cur_month else set()   # 이미 지난(닫힌) 달
    # 양식이 정의한 전체 (월,주차) 쌍(경계주 포함) → 현재까지 '있어야 할' 쌍. (데이터 기준)
    all_pairs = _all_week_pairs(latest_stored_period())
    exp_pairs = {p for p in all_pairs if cur_pair and p <= cur_pair}
    # 현재월 마감 due 판정 — 데이터 흐름이 W1·W2…→마감 이라, 어느 항목이든 현재월이 '완전 마감'
    # (그 달 잠정 셀 없고 월계 있음)되면 현재 마일스톤 = '그 달 마감'. 그러면 현재월 마감 미완 항목도 요청 대상.
    prov_by_area = _prov_months_all(area_period)
    cur_close_started = bool(cur_month) and any(
        cur_month in present.get(a, (set(), set()))[1] and cur_month not in prov_by_area.get(a, set())
        for a, m in AREA_META.items() if m["source"] != "파생")

    rows = []
    for area, meta in AREA_META.items():
        if meta["source"] == "파생":
            rows.append({"항목": area, "source": "파생", "format": "자동", "unit": meta["unit"],
                         "derived": True, "latest_week": None, "latest_month": None,
                         "latest_label": "—", "received": False, "last_at": None,
                         "count": 0, "state": "파생", "issues": [],
                         "missing_weeks": [], "missing_months": [], "gap_summary": "—",
                         "has_gap": False, "gaps": [], "requested": False, "requested_at": None,
                         "incomplete": [], "incomplete_cells": 0,
                         "derived_from": meta.get("derived_from", [])})
            continue
        p = area_period.get(area)
        wks, mos = present.get(area, (set(), set()))
        wk = max(wks) if wks else None
        mo = max(mos) if mos else None
        log_rec = _load_log(p).get(area, {}) if p else {}
        last_at = log_rec.get("last_at")
        count = int(log_rec.get("count", 0))
        rem_log = _load_remindlog(p) if p else {}

        # 빠진 것 감지 — 주차형은 주차+월계, 월형은 월계만. 마감 든 달의 빠진 주차도 '요청 가능'으로 둠
        # (보완하려면 요청해야 하니까). 단 마감 있는데 주차 불완전이면 별도 '정합성 경고'로 표시.
        missing_weeks = sorted(exp_pairs - wks) if meta["unit"] == "주차" else []   # (월,주차) 쌍
        missing_months = sorted(closed_months - mos)
        # 현재월 마감 시작됨(어느 항목 완전마감) + 이 항목은 미완(현재월 잠정 있거나 월계 없음) → 현재월 마감도 요청
        if cur_close_started and cur_month and (cur_month in prov_by_area.get(area, set()) or cur_month not in mos):
            if cur_month not in missing_months:
                missing_months = sorted(missing_months + [cur_month])
        # 월형(월별 제출 — 매출지역2·고정비 등)은 그 달 월계가 곧 데이터다. 현재 시점이 그 달(cur_month)인데
        # 아직 안 냈으면 바로 미제출. (주차형은 주차로 진행 중이라 현재월 월계는 lag = 정상이므로 제외.)
        if meta["unit"] == "월" and cur_month and cur_month not in mos and cur_month not in missing_months:
            missing_months = sorted(missing_months + [cur_month])
        # 정합성 경고 — 마감(월계)은 들어왔는데 그 달 주차가 불완전(이상 신호). 요청은 되게 하고 표시만 추가.
        anomaly_months = sorted({m for (m, iso) in missing_weeks if m in mos})
        issues = [f"{m}월 마감 있으나 주차 불완전" for m in anomaly_months]
        # 셀 단위 누락 — 받은 주차 안에 목표는 있는데 실적이 빈 leaf 셀(하나라도 있으면 제출오류).
        # 어디가 빠졌는지 명확히 — 빠진 부서경로(leaf)명을 문구에 포함(3개 초과는 '외 N').
        incomplete = _incomplete_cells(area, p) if meta["unit"] == "주차" else []
        for x in incomplete:
            lv = x.get("leaves", [])
            where = f": {', '.join(lv[:3])}{f' 외 {len(lv) - 3}' if len(lv) > 3 else ''}" if lv else ""
            issues.append(f"{x['label']} 실적 빈 셀 {x['n']}개{where}")
        has_data = bool(wks or mos)
        has_gap = bool(missing_weeks or missing_months or incomplete)   # 부분 누락도 요청 대상
        gap_summary = _gap_summary(missing_weeks, missing_months, has_data) if (missing_weeks or missing_months) else "—"
        # 빠진 것을 '조각'(종류·월·부분)으로 분해 — 각각 따로 체크/요청. 조각별 요청함 = 발송 기록 + 서명 일치
        # (조각 내용 바뀌면 자동 해제). 항목 requested = 모든 조각 요청됨(표 메일버튼용).
        gaps = []
        for pc in _gap_pieces(area, missing_weeks, missing_months, incomplete):
            rr = rem_log.get(pc["key"], {})
            req = bool(rr.get("sent_at")) and rr.get("sig") == _piece_sig(pc)
            gaps.append({**pc, "requested": req, "requested_at": rr.get("sent_at") if req else None,
                         "request_count": int(rr.get("count", 0))})   # 누적 요청 횟수(반복 미제출)
        requested = bool(gaps) and all(g["requested"] for g in gaps)
        requested_at = next((g["requested_at"] for g in gaps if g["requested_at"]), None) if requested else None

        # 최신 시점 — 주차형은 진행 중엔 'N월 W##', 그 달 마감(월계) 도착하면 'N월 마감'.
        # (데이터 흐름: W1·W2…W## 들어오다가 마지막에 그 달 마감(월계)이 늦게 도착)
        if meta["unit"] == "주차":
            wmo, wiso = (wk[0], wk[1]) if wk else (0, 0)   # wk = (월, ISO주차) 쌍
            mclosed = bool(mo) and mo not in prov_by_area.get(area, set())   # 그 달 잠정 없음 = 완전 마감
            # '마감'은 그 달 **마지막 주차까지 도달**해야 뜬다 — 월계가 수식(=주차 합)이라 부분합으로도
            #   항상 떠서, 뒤처진 부서(예: 품질 4월W14)가 '4월 마감'으로 오판되던 것 방지(4월 W18 도달 시만 마감).
            mo_last_wk = _month_last_iso(all_pairs, mo) if mo else 0
            if mo and mclosed and (not wk or (mo >= wmo and wiso >= mo_last_wk)):
                label = f"{mo}월 마감"
            elif wk:
                label = _pair_label(wk)           # 진행 중(마감 미완) = 'N월 W##' (경계주도 데이터 월)
            elif mo:
                label = f"{mo}월 마감" if mclosed else "데이터 없음"
            else:
                label = "데이터 없음"
        else:
            # 월형(주차 없음) — 월 데이터 = 그 달 마감 → 'N월 마감'.
            label = f"{mo}월 마감" if mo else "데이터 없음"
        received = not has_gap and not issues
        # 상태 — 제출오류(정합성 이상=마감 있는데 주차 불완전) 우선 / 미제출(요청대상) / 재제출 / 입력완료
        #   '재제출완료'는 **같은 시점을 다시 낸 정정**일 때만(신규 시점 제출은 '제출 완료').
        #   last_kind 는 저장 시 _submission_kind 로 기록(첫 제출/신규 시점/재제출 (정정)/재제출).
        last_kind = log_rec.get("last_kind")
        if issues:
            state = "제출오류"
        elif has_gap:
            state = "미제출"
        elif last_kind in ("재제출", "재제출 (정정)"):
            state = "재제출완료"
        elif last_kind:                 # 첫 제출 / 신규 시점 = 제출 완료
            state = "입력완료"
        elif count >= 2:                # last_kind 미기록(구 데이터) 폴백 = 종전 횟수 기준
            state = "재제출완료"
        else:
            state = "입력완료"
        rows.append({"항목": area, "source": meta["source"], "format": area_format(meta["source"]),
                     "unit": meta["unit"], "derived": False,
                     "latest_week": (wk[1] if wk else None), "latest_month": mo, "latest_label": label,
                     "received": received, "last_at": last_at,
                     "count": count, "state": state, "issues": issues,
                     "missing_weeks": missing_weeks, "missing_months": missing_months,
                     "gap_summary": gap_summary, "has_gap": has_gap, "gaps": gaps,
                     "requested": requested, "requested_at": requested_at,
                     "incomplete": incomplete, "incomplete_cells": sum(x["n"] for x in incomplete)})

    missing = [r["항목"] for r in rows if not r["derived"] and r["has_gap"]]
    return {
        "current_week": cur_week or None,
        # 현재 시점 — 현재월 마감 시작됐으면 'N월 마감', 아니면 'N월 W##'(진행 중). 경계주도 데이터 월(cur_pair) 기준.
        "current_label": (f"{cur_month}월 마감" if cur_close_started else _pair_label(cur_pair)) if cur_pair else "—",
        "current_close": cur_close_started,
        "current_month": cur_month or None,
        "expected": [a for a, m in AREA_META.items() if m["source"] != "파생"],
        "missing": missing,
        "items": rows,
    }


if __name__ == "__main__":  # 간이 점검
    import glob
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    cand = glob.glob("../*Master*ver0.1.xlsx") or glob.glob("../docs/lg_samples/excel/*.xlsx")
    xlsx = cand[0]
    outs, df, rep, pid = save_excel(xlsx)  # period_id=None → 자동 판단
    print(f"자동 판단 회차: {pid}  ({len(outs)}개 항목, {len(df)} 행)")
    print("회차 목록:", list_stored_periods())
    st = submission_status(pid)
    print("수신:", st["received"], "| 미수신:", st["missing"])
