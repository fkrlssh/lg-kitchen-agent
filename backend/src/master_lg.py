"""Master 재현 — **수식 계산기**(캐시 비의존).

배경: Master 합계 = 각 Area '대표 총계'(목표/실적)의 합. 대표 총계는 엑셀 수식인데,
SUM 뿐 아니라 곱/나눗셈(금액=수량×비율/100), cross-sheet(H=I+J+K+L) 도 섞임.
→ 단순 'leaf 더하기'론 부족. **수식을 직접 평가**하되, 수식 셀의 캐시값(트림 시 None)이
   아니라 **raw 입력 셀값**(항상 살아있음)만 읽어 우리가 계산한다.

전략(사용자 합의 2026-06-20):
- 업로드 시 워크북에서 Master 대표 셀의 수식을 따라가며 평가(_make_evaluator).
- 평가 입력 = 비수식(raw) 셀의 값. 수식 셀은 우리가 재귀 평가 → 캐시 불필요.
- 월별: 대표 행을 각 월의 '월계' 컬럼에서 평가(연도블록 시트는 같은 블록 내 컬럼).
검증: 1월 실적 합계(H제외)=361.05 / 목표=358.48 와 일치해야.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from . import registry
from .parsing_lg import _build_gran_map, _build_month_map, _find_month_row

FileLike = Union[str, Path]

_DTYPE_RE = re.compile(r"(목표|실적|계획)")
SKIP_SHEETS = {"Master", "마스터", "Summary", "요약"}


# ── 시트 참조 정규식 (워크북 실제 시트명 기반) ──
# ver0.1(2026-06-24)부터 시트명이 한글('재료비')·쉼표포함('고정비_생산,제판법인Control')으로
# 바뀜. 엑셀은 특수문자 시트를 작은따옴표로 감쌈. 시트명을 하드코딩(Area_*)하는 대신
# **워크북의 실제 시트 이름**으로 정규식을 만들어 어떤 이름이든 매칭한다.

def _name_alt(sheetnames) -> str:
    """시트명 alternation(긴 이름 우선 = 부분매칭 방지). 정규식 escape 처리."""
    return "|".join(re.escape(n) for n in sorted(sheetnames, key=len, reverse=True))


def _strip_q(tok: str) -> str:
    """참조 토큰의 작은따옴표 제거 — \"'고정비_생산,제판법인Control'\" → 원래 이름."""
    if tok and len(tok) >= 2 and tok[0] == "'" and tok[-1] == "'":
        return tok[1:-1].replace("''", "'")
    return tok


def _ref_res(sheetnames) -> dict:
    """시트명 집합 → 참조 매칭용 컴파일된 정규식 묶음.

    NAME = 작은따옴표로 감싼 이름 또는 bare 이름(둘 다). 캡처 그룹 = 시트 토큰.
    REF    : Master 셀이 단일 cross-sheet 참조('=재료비!G24')인지.
    CELLREF: 임의 셀 참조(시트 옵션) — 평가기 치환용.
    RANGE  : 범위 참조(시트 옵션).
    """
    alt = _name_alt(sheetnames)
    NAME = rf"(?:'(?:{alt})'|(?:{alt}))" if alt else r"(?:'[^']+'|[A-Za-z_가-힣0-9]+)"
    return {
        "REF": re.compile(rf"^=\s*({NAME})!\$?([A-Z]+)\$?(\d+)\s*$"),
        "CELLREF": re.compile(rf"(?:({NAME})!)?\$?([A-Z]{{1,3}})\$?(\d+)"),
        "RANGE": re.compile(rf"^(?:({NAME})!)?\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)$"),
        "ONE": re.compile(rf"^(?:({NAME})!)?\$?([A-Z]+)\$?(\d+)$"),
        "NAME": NAME,
    }


def _fmt_spec(nf: Optional[str]) -> Tuple[bool, Optional[int]]:
    """엑셀 셀 number_format → (퍼센트 여부, 소수 자리수).

    웹이 엑셀 표시 서식을 그대로 미러하기 위한 단일 판정.
    - '0.0%'          → (True, 1)  퍼센트·소수1자리 (값×100 후 1자리)
    - '0.00%'         → (True, 2)
    - '#,##0'         → (False, 0) 정수 표시(내부값이 유리수여도 엑셀은 정수)
    - '#,##0.00'      → (False, 2)
    - '_-* #,##0_-;…' → (False, 0) 회계서식(소수부 없음)
    - 'General'/빈값  → (False, None)  명시 서식 없음 → 프론트 폴백 규칙 사용
    """
    if not nf or str(nf).strip().lower() == "general":
        return (False, None)
    s = str(nf)
    pct = "%" in s
    m = re.search(r"\.(0+)", s)   # 소수부 '0' 개수 = 표시 소수 자리
    dec = len(m.group(1)) if m else 0
    return (pct, dec)


def _load_two(path_or_bytes: FileLike):
    # 이미 (wb_v, wb_f) 로 로드된 워크북 쌍이면 그대로 재사용 —
    # 한 파일로 headline/master_table/area_table 을 연달아 만들 때 openpyxl 로드(가장 비쌈)를
    # 1회로 공유(읽기 전용이라 안전). 삭제 복원·setup 적재 등에서 ~3배 가속.
    if isinstance(path_or_bytes, tuple) and len(path_or_bytes) == 2:
        return path_or_bytes
    if isinstance(path_or_bytes, (str, Path)):
        return load_workbook(path_or_bytes, data_only=True), load_workbook(path_or_bytes, data_only=False)
    raw = path_or_bytes.read() if hasattr(path_or_bytes, "read") else path_or_bytes
    return load_workbook(io.BytesIO(raw), data_only=True), load_workbook(io.BytesIO(raw), data_only=False)


# ───────────────────────── 수식 계산기 ─────────────────────────

def _split_commas(s: str) -> List[str]:
    """최상위 콤마로 분리 — 괄호 깊이 + **작은따옴표**(시트명 내 콤마 보호) 인식."""
    out, depth, cur, inq = [], 0, "", False
    for ch in s:
        if ch == "'":
            inq = not inq; cur += ch
        elif inq:
            cur += ch
        elif ch == "(":
            depth += 1; cur += ch
        elif ch == ")":
            depth -= 1; cur += ch
        elif ch == "," and depth == 0:
            out.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _make_evaluator(wb_v, wb_f) -> Callable[[str, str], float]:
    """(sheet,coord) → 평가값. 수식이면 raw 셀까지 재귀 평가(캐시 안 읽음).

    시트 참조 정규식은 워크북의 **실제 시트명**으로 빌드 → 한글·쉼표 시트도 매칭.
    """
    res = _ref_res(wb_f.sheetnames)
    RANGE, ONE, CELLREF = res["RANGE"], res["ONE"], res["CELLREF"]
    memo: Dict[Tuple[str, str], float] = {}
    inprog: set = set()

    def ev(sheet: str, coord: str) -> float:
        key = (sheet, coord)
        if key in memo:
            return memo[key]
        if key in inprog:
            return 0.0  # 순환 방지
        inprog.add(key)
        val = 0.0
        try:
            if sheet in wb_f.sheetnames:
                fv = wb_f[sheet][coord].value
                if isinstance(fv, str) and fv.startswith("="):
                    val = ev_expr(fv[1:], sheet)
                else:
                    vv = wb_v[sheet][coord].value if sheet in wb_v.sheetnames else None
                    val = float(vv) if isinstance(vv, (int, float)) else 0.0
        except Exception:
            val = 0.0
        inprog.discard(key)
        memo[key] = val
        return val

    def ev_range_or_cell(arg: str, ctx: str) -> float:
        arg = arg.strip()
        rng = RANGE.match(arg)
        if rng:
            sh = _strip_q(rng.group(1)) if rng.group(1) else ctx
            c1, r1, c2, r2 = rng.group(2), int(rng.group(3)), rng.group(4), int(rng.group(5))
            # 2D 범위 — 컬럼(c1..c2) × 행(r1..r2) 모두 순회. 세로범위(c1==c2)는 컬럼 1개라
            # 종전과 동일, 가로범위(r1==r2, 예 SUM(D5:O5))·블록범위도 정확히 합산.
            ci1, ci2 = column_index_from_string(c1), column_index_from_string(c2)
            return sum(ev(sh, f"{get_column_letter(cc)}{rr}")
                       for cc in range(min(ci1, ci2), max(ci1, ci2) + 1)
                       for rr in range(min(r1, r2), max(r1, r2) + 1))
        one = ONE.match(arg)
        if one:
            return ev(_strip_q(one.group(1)) if one.group(1) else ctx, f"{one.group(2)}{one.group(3)}")
        return ev_expr(arg, ctx)  # 산술 표현 인자

    def _strip_iferror(e: str) -> str:
        """IFERROR(inner, fallback) → (inner). 균형 괄호로 매칭(중첩·SUM 포함 대응).
        엑셀 저감율 등이 =IFERROR(F12/F10,"") 형태라 벗겨내야 함(안 하면 수치식 검사 탈락→0)."""
        while True:
            m = re.search(r"IFERROR\(", e, re.I)
            if not m:
                return e
            start = m.end()
            depth, i, comma = 1, start, -1
            while i < len(e) and depth > 0:
                ch = e[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "," and depth == 1 and comma < 0:
                    comma = i
                i += 1
            inner = e[start:comma] if comma >= 0 else e[start:i - 1]
            e = e[:m.start()] + "(" + inner + ")" + e[i:]

    def ev_expr(expr: str, ctx: str) -> float:
        # 가장 안쪽 SUM(...) 부터 수치로 치환 (시트명에 공백 없음 → 공백 제거 안전)
        expr = expr.replace(" ", "")
        expr = _strip_iferror(expr)   # 엑셀 함수 IFERROR 벗기기(inner 만 평가)
        pat = re.compile(r"(?:SUM|sum)\(([^()]*)\)")
        while True:
            m = pat.search(expr)
            if not m:
                break
            total = sum(ev_range_or_cell(a, ctx) for a in _split_commas(m.group(1)))
            expr = expr[:m.start()] + repr(total) + expr[m.end():]
        # 남은 셀 참조 → 값 치환
        expr = CELLREF.sub(
            lambda mm: repr(ev(_strip_q(mm.group(1)) if mm.group(1) else ctx,
                               f"{mm.group(2)}{mm.group(3)}")), expr)
        expr = expr.replace("^", "**")
        if not re.fullmatch(r"[0-9eE.+\-*/() ]*", expr):
            return 0.0
        try:
            return float(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 (숫자식만)
        except Exception:
            return 0.0

    return ev


# ───────────────────────── 월 컬럼 매핑 ─────────────────────────

def _month_col_runs(wsv) -> List[List[Tuple[int, int]]]:
    """시트의 '월계' 컬럼을 블록(run)별 [(월, 컬럼idx)...] 로. 연도블록 시트 = run 여럿."""
    mrow = _find_month_row(wsv)
    mmap = _build_month_map(wsv, mrow, wsv.max_column)
    gmap = _build_gran_map(wsv, mrow, wsv.max_column)
    cols = [c for c in range(1, wsv.max_column + 1)
            if mmap.get(c) and gmap.get(c, ("", None))[0] == "월계"]
    runs: List[List[Tuple[int, int]]] = []
    cur: List[Tuple[int, int]] = []
    prev = 0
    for c in sorted(cols):
        mo = int(mmap[c][:-1])
        if cur and mo <= prev:  # 월이 감소/리셋 → 새 블록
            runs.append(cur); cur = []
        cur.append((mo, c)); prev = mo
    if cur:
        runs.append(cur)
    return runs


def _run_for_col(runs, col: int):
    for run in runs:
        if any(c == col for _m, c in run):
            return run
    return runs[0] if runs else []


def _block_layout(wsv) -> List[List[dict]]:
    """시트 → 블록(run)별 [{월, 구분(월계|주차), 주차, col}...]. 월계+주차 모두 포함.

    연도블록 시트(B·C·E·L)는 블록 여럿. 대표셀이 속한 블록의 월별/주차별 컬럼 매핑용.
    """
    mrow = _find_month_row(wsv)
    mmap = _build_month_map(wsv, mrow, wsv.max_column)
    gmap = _build_gran_map(wsv, mrow, wsv.max_column)
    cells = []
    for c in range(1, wsv.max_column + 1):
        lab = mmap.get(c)
        if not lab:
            continue
        gran, wk = gmap.get(c, ("월계", None))
        if gran == "합계열":
            continue
        cells.append({"월": int(lab[:-1]), "구분": "주차" if gran == "주차" else "월계",
                      "주차": wk, "col": c})
    # 블록 분리: 월계 컬럼의 월이 감소/리셋되면 새 블록
    blocks: List[List[dict]] = []
    cur: List[dict] = []
    prev = 0
    for e in cells:
        if e["구분"] == "월계":
            if cur and e["월"] <= prev:
                blocks.append(cur); cur = []
            prev = e["월"]
        cur.append(e)
    if cur:
        blocks.append(cur)
    return blocks


def _block_for_col(blocks, col: int):
    for b in blocks:
        if any(e["col"] == col for e in b):
            return b
    return blocks[0] if blocks else []


# ───────────────────────── 대표 참조 + headline ─────────────────────────

def _contribution_refs(wb_f) -> Dict[str, Dict[str, List[Tuple[str, str, int]]]]:
    """Master 행별 대표 셀 참조 → {시트명: {목표/실적: [(시트, col, row)...]}}.

    키 = 실제 시트명(평가기로 셀 읽을 때 필요). 슬러그 변환은 호출부에서.
    """
    ms = wb_f["Master"]
    REF = _ref_res(wb_f.sheetnames)["REF"]
    refs: Dict[str, Dict[str, List[Tuple[str, str, int]]]] = {}
    for row in ms.iter_rows():
        dtype = None
        for c in row[:6]:
            if isinstance(c.value, str) and _DTYPE_RE.search(c.value):
                dtype = "목표" if ("목표" in c.value or "계획" in c.value) else "실적"
                break
        if not dtype:
            continue
        for c in row:
            if isinstance(c.value, str):
                m = REF.match(c.value.strip())
                if m:
                    sheet = _strip_q(m.group(1))
                    refs.setdefault(sheet, {}).setdefault(dtype, []).append(
                        (sheet, m.group(2), int(m.group(3))))
                    break
    return refs


HEADLINE_COLS = ["항목", "종류", "월", "구분", "주차", "값"]


def master_headline(path_or_bytes: FileLike) -> pd.DataFrame:
    """워크북 → 각 Area 대표총계의 **월별 + 주차별** 목표/실적. 수식 직접 평가.

    반환: 항목/종류/월/구분(월계|주차)/주차/값. 대표 행을 각 월의 월계·주차 컬럼에서 평가.
    """
    from openpyxl.utils import column_index_from_string, get_column_letter
    wb_v, wb_f = _load_two(path_or_bytes)
    if "Master" not in wb_f.sheetnames:
        return pd.DataFrame(columns=HEADLINE_COLS)
    ev = _make_evaluator(wb_v, wb_f)
    refs = _contribution_refs(wb_f)

    def _present(sheet: str, coord: str) -> bool:
        """공식 값 존재 여부 — 수식이거나 raw 값이 비어있지 않으면 True (master_table 와 동일 기준)."""
        fv = wb_f[sheet][coord].value if sheet in wb_f.sheetnames else None
        if isinstance(fv, str) and fv.startswith("="):
            return True
        vv = wb_v[sheet][coord].value if sheet in wb_v.sheetnames else None
        return vv is not None

    records: List[dict] = []
    for sheet, dd in refs.items():
        if sheet not in wb_v.sheetnames:
            continue
        slug = registry.slug_for_sheet(sheet) or sheet   # 항목 키 = 슬러그
        blocks = _block_layout(wb_v[sheet])
        for dtype, cells in dd.items():
            # (월,구분,주차) → 값 합 (대표 행이 여러 개면 합산)
            agg: Dict[tuple, float] = {}
            pres: Dict[tuple, bool] = {}   # 그 키의 원본 셀이 하나라도 실재하나
            for (sh, col0, row0) in cells:
                block = _block_for_col(blocks, column_index_from_string(col0))
                for e in block:
                    coord = f"{get_column_letter(e['col'])}{row0}"
                    key = (e["월"], e["구분"], e["주차"])
                    agg[key] = agg.get(key, 0.0) + ev(sh, coord)
                    pres[key] = pres.get(key, False) or _present(sh, coord)
            for (mo, gran, wk), v in agg.items():
                # ⚠️ 실적 원본 셀이 전부 비었으면(공식 월계 미도착) 0 짜리 실적 행을 만들지 말고 생략.
                # 그래야 master_detail(카드/그래프)이 '그 달 실적 월계 없음'으로 보고 주차값으로 폴백(잠정)
                # → 표(presence 기준)와 일치(안 그러면 카드=0, 표=잠정으로 어긋남).
                # 목표는 항상 내보낸다 — 월 축(1~12) 유지용(목표 라인은 미래월까지 그려야 함).
                if dtype == "실적" and gran == "월계" and not pres.get((mo, gran, wk)):
                    continue
                records.append({"항목": slug, "종류": dtype, "월": mo,
                                "구분": gran, "주차": wk, "값": v})
    return pd.DataFrame(records, columns=HEADLINE_COLS)


def master_table(path_or_bytes: FileLike, current_month: int = None) -> dict:
    """Master 시트 재현 — 계층(합계/Area>하위) × 목표·실적·달성률 × 월. raw 평가.

    Master 행: B열=주항목 / C열=하위 / D열=목표·실적·달성율 / 참조=Area_X!셀.
    각 행의 참조 Area 행을 월별 컬럼에서 평가. 합계/합계(H제외)는 라인아이템 합으로 계산
    (Master 의 월 컬럼은 1월만 배선돼 신뢰 X). current_month 이후 실적은 비움.
    반환: {months, rows:[{label, level, bold, cells:{월:{목표,실적,달성률}}}]}
    """
    from openpyxl.utils import column_index_from_string, get_column_letter
    wb_v, wb_f = _load_two(path_or_bytes)
    if "Master" not in wb_f.sheetnames:
        return {"months": [], "rows": []}
    ms = wb_f["Master"]
    ev = _make_evaluator(wb_v, wb_f)
    REF = _ref_res(wb_f.sheetnames)["REF"]

    # 1) Master 행 파싱 → 라인아이템 (합계 행 제외)
    items: List[dict] = []           # {primary, sub, area(slug), sheet, 목표/실적: (col,row)}
    order: List[tuple] = []
    by_key: Dict[tuple, dict] = {}
    cur_primary = ""
    cur_sub = ""
    for r in range(1, ms.max_row + 1):
        b = ms.cell(r, 2).value
        c = ms.cell(r, 3).value
        d = ms.cell(r, 4).value
        if isinstance(b, str) and b.strip():    # 새 주항목 → 하위 라벨 리셋
            cur_primary = b.strip()
            cur_sub = ""
        if isinstance(c, str) and c.strip():     # 하위 라벨 (목표 행에만 있음 → 이어감)
            cur_sub = c.strip()
        if not isinstance(d, str):
            continue
        dtype = "목표" if ("목표" in d or "계획" in d) else ("실적" if "실적" in d else None)
        if dtype is None:
            continue
        if "합계" in cur_primary:        # 합계/합계(파생 제외) → 합산으로 계산
            continue
        m = REF.match(str(ms.cell(r, 5).value).strip())
        if not m:
            continue
        sheet, col, row = _strip_q(m.group(1)), m.group(2), int(m.group(3))
        area = registry.slug_for_sheet(sheet) or sheet   # 항목 키 = 슬러그
        key = (cur_primary, cur_sub)
        if key not in by_key:
            by_key[key] = {"primary": cur_primary, "sub": cur_sub, "area": area, "sheet": sheet}
            order.append(key)
            items.append(by_key[key])
        by_key[key][dtype] = (col, row)

    # 2) 월 컬럼 매핑 (Area별 블록 캐시) + 라인아이템 월별 목표/실적 평가
    block_cache: Dict[str, list] = {}

    def month_cols(area: str, col0: str) -> Dict[int, int]:
        if area not in block_cache:
            block_cache[area] = _block_layout(wb_v[area]) if area in wb_v.sheetnames else []
        block = _block_for_col(block_cache[area], column_index_from_string(col0))
        return {e["월"]: e["col"] for e in block if e["구분"] == "월계"}

    def _present(sheet: str, coord: str) -> bool:
        """공식 월계 값 존재 여부 — 수식이거나 raw 값이 비어있지 않으면 True.
        (트림된 수식은 캐시값이 None 이라 수식 자체 유무로 먼저 판정)."""
        fv = wb_f[sheet][coord].value if sheet in wb_f.sheetnames else None
        if isinstance(fv, str) and fv.startswith("="):
            return True
        vv = wb_v[sheet][coord].value if sheet in wb_v.sheetnames else None
        return vv is not None

    all_months: set = set()
    for it in items:
        it["cells"] = {}
        it["official"] = {}   # {월: {목표/실적: bool}} — 공식 월계 셀이 실재했는지
        for dtype in ("목표", "실적"):
            if dtype not in it:
                continue
            col0, row0 = it[dtype]
            for mo, cidx in month_cols(it["sheet"], col0).items():
                all_months.add(mo)
                coord = f"{get_column_letter(cidx)}{row0}"
                it["cells"].setdefault(mo, {})[dtype] = ev(it["sheet"], coord)
                it["official"].setdefault(mo, {})[dtype] = _present(it["sheet"], coord)

    months = sorted(all_months)
    cur = current_month or (months[-1] if months else 12)
    if cur not in months:           # 당월 컬럼 보장(월계 없고 주차만 있는 경우 대비)
        months = sorted(set(months) | {cur})

    # 주차(W#) 평가 — 모든 월(월 네비: 과거 월도 당월 토글에서 차수 표시 가능)
    def week_cols(area: str, col0: str) -> List[Tuple[int, str, int]]:
        if area not in block_cache:
            block_cache[area] = _block_layout(wb_v[area]) if area in wb_v.sheetnames else []
        block = _block_for_col(block_cache[area], column_index_from_string(col0))
        return [(e["월"], (e["주차"] or get_column_letter(e["col"])), e["col"])
                for e in block if e["구분"] == "주차"]

    for it in items:
        it["weeks"] = {}   # {월: {주차: {목표/실적: 값}}}
        for dtype in ("목표", "실적"):
            if dtype not in it:
                continue
            col0, row0 = it[dtype]
            for mo, wk, wcol in week_cols(it["sheet"], col0):
                it["weeks"].setdefault(mo, {}).setdefault(wk, {})[dtype] = ev(it["sheet"], f"{get_column_letter(wcol)}{row0}")

    def _mk(t, a, mo, prov=False):
        future = mo > cur
        a = None if (future or a is None) else a
        rate = round(a / t * 100, 1) if (t and a is not None) else None
        # 잠정 = 실적이 공식 월계가 아니라 주차에서 채워진 값(월계 lag). 미래월(a=None)은 잠정 아님.
        return {"목표": round(t, 1) if t is not None else None,
                "실적": round(a, 1) if a is not None else None, "달성률": rate,
                "잠정": bool(prov) and a is not None}

    def _wk_list(wmap: dict) -> List[dict]:
        out = []
        for wk in sorted(wmap, key=lambda x: int(re.sub(r"\D", "", x) or 0)):
            t = wmap[wk].get("목표"); a = wmap[wk].get("실적")
            rate = round(a / t * 100, 1) if (t and a is not None) else None
            out.append({"주차": wk,
                        "목표": round(t, 1) if t is not None else None,
                        "실적": round(a, 1) if a is not None else None,
                        "달성률": rate})
        return out

    def _acc(dst: dict, wmap_by_mo: dict) -> None:
        # wmap_by_mo = {월: {주차: {목표/실적}}} → dst = {월: {주차: {목표/실적: 합}}}
        for mo, wmap in wmap_by_mo.items():
            d = dst.setdefault(mo, {})
            for wk, wv in wmap.items():
                for dtype in ("목표", "실적"):
                    v = wv.get(dtype)
                    if v is None:
                        continue
                    d.setdefault(wk, {}).setdefault(dtype, 0.0)
                    d[wk][dtype] += v

    # 3) 계층 rows + 합계
    rows: List[dict] = []
    # 합계용 누산
    g_all = {mo: {"목표": 0.0, "실적": 0.0} for mo in months}
    g_ex = {mo: {"목표": 0.0, "실적": 0.0} for mo in months}
    g_all_w: dict = {}; g_ex_w: dict = {}
    # primary 그룹
    from collections import OrderedDict
    groups: "OrderedDict[str, list]" = OrderedDict()
    for it in items:
        groups.setdefault(it["primary"], []).append(it)

    body: List[dict] = []
    for primary, its in groups.items():
        # 부모 = 하위 합
        parent = {mo: {"목표": 0.0, "실적": 0.0, "has_t": False, "has_a": False} for mo in months}
        parent_w: dict = {}
        sub_rows = []
        for it in its:
            cells = {}
            for mo in months:
                cc = it["cells"].get(mo, {})
                t = cc.get("목표"); a = cc.get("실적")
                wmap = it["weeks"].get(mo, {})
                # 공식 월계 실적이 없으면(월계 lag/트림) 주차 마지막(=최신 누적)값으로 채우고 잠정 마킹.
                # (area_table·master_detail 과 동일 규칙 → 같은 항목·달 잠정/숫자가 일치해야 함)
                # ⚠️ 채움은 **unrounded** it["weeks"] 사용 — _wk_list(라운딩됨)로 채우면 소계 합산 시
                #    leaf 별 0.1 반올림이 누적돼 master_detail(원값 합)과 어긋남. 라운딩은 _mk 가 한 번만.
                prov = False
                if (not it["official"].get(mo, {}).get("실적", False)) and mo <= cur:
                    wa = [wmap[w].get("실적")
                          for w in sorted(wmap, key=lambda x: int(re.sub(r"\D", "", x) or 0))
                          if wmap[w].get("실적") is not None]
                    a = wa[-1] if wa else None
                    prov = a is not None
                cell = _mk(t, a, mo, prov)
                cell["weeks"] = _wk_list(wmap)
                cells[str(mo)] = cell
                if t is not None:
                    parent[mo]["목표"] += t; parent[mo]["has_t"] = True
                if a is not None and mo <= cur:
                    parent[mo]["실적"] += a; parent[mo]["has_a"] = True
                    if prov:
                        parent[mo]["prov"] = True
                # 합계 누산
                if mo <= cur:
                    g_all[mo]["목표"] += t or 0.0
                    if a is not None:
                        g_all[mo]["실적"] += a
                        if prov:
                            g_all[mo]["prov"] = True
                    if it["area"] != registry.DERIVED_SLUG:
                        g_ex[mo]["목표"] += t or 0.0
                        if a is not None:
                            g_ex[mo]["실적"] += a
                            if prov:
                                g_ex[mo]["prov"] = True
                else:
                    g_all[mo]["목표"] += t or 0.0
                    if it["area"] != registry.DERIVED_SLUG:
                        g_ex[mo]["목표"] += t or 0.0
            _acc(parent_w, it["weeks"]); _acc(g_all_w, it["weeks"])
            if it["area"] != registry.DERIVED_SLUG:
                _acc(g_ex_w, it["weeks"])
            if it["sub"]:
                sub_rows.append({"label": it["sub"], "level": 1, "bold": False, "area": it["area"], "cells": cells})
        # 부모 cells
        g_area = its[0]["area"] if its else None
        pcells = {}
        for mo in months:
            t = parent[mo]["목표"] if parent[mo]["has_t"] else None
            a = parent[mo]["실적"] if parent[mo]["has_a"] else None
            pc = _mk(t, a, mo, parent[mo].get("prov", False))
            pc["weeks"] = _wk_list(parent_w.get(mo, {}))
            pcells[str(mo)] = pc
        body.append({"label": primary, "level": 0, "bold": False, "area": g_area, "cells": pcells})
        body.extend(sub_rows)

    def _grand(g, gw, label):
        cells = {}
        for mo in months:
            t = g[mo]["목표"]; a = g[mo]["실적"] if mo <= cur else None
            c = _mk(t, a, mo, g[mo].get("prov", False))
            c["weeks"] = _wk_list(gw.get(mo, {}))
            cells[str(mo)] = c
        return {"label": label, "level": 0, "bold": True, "area": None, "cells": cells}

    _ex_label = f"합계 ({registry.label_for(registry.DERIVED_SLUG)} 제외)" if registry.DERIVED_SLUG else "합계 (제외)"
    rows.append(_grand(g_all, g_all_w, "합계"))
    rows.append(_grand(g_ex, g_ex_w, _ex_label))
    rows.extend(body)
    return {"months": months, "current_month": cur, "rows": rows}


def area_table(path_or_bytes: FileLike, area: str, current_month: int = None) -> dict:
    """Area 시트 1장을 **엑셀 그대로 재현** — 합계/소계/Rate 행 포함, 수식 직접 평가.

    parse_sheet 는 raw leaf 만 적재(수식 skip)하지만, 여기선 **수식 행도 평가해 포함**한다
    (Group_B+Group_C 합계, Group_B/Group_C 소계, Rate 행 등). 두 양식 패턴을 한 함수로 흡수:
      · row-dtype (A·B·C·D·G·F): 좌측 dtype 열(목표/실적) → 한 라벨이 목표행+실적행 2줄.
      · year-block (E·L): 상단 연도블록(26목표/26실적) → 한 라벨이 1줄, kind 는 컬럼이 정함.

    반환: {area, months, current_month, rows:[{부서경로, level, is_subtotal, is_rate,
            cells:{"월":{목표,실적,달성률, weeks:[{주차,목표,실적,달성률}]}}}]}
    월별(월계) + 당월 주차(weeks) 모두 채워 한 번에 내려줌(프론트가 모드별로 골라 표시).
    """
    from openpyxl.utils import get_column_letter
    from .parsing_lg import (_find_month_row, _build_month_map, _build_gran_map,
                             _find_year_blocks, _is_dtype, _split_dtype)
    wb_v, wb_f = _load_two(path_or_bytes)
    # area = 슬러그 → 실제 시트명 해석(워크북 열기). 출력은 슬러그 유지.
    sheet_name = registry.sheet_for_slug(area) or area
    if sheet_name not in wb_v.sheetnames:
        return {"area": area, "months": [], "current_month": current_month, "rows": []}
    wsv, wsf = wb_v[sheet_name], wb_f[sheet_name]
    ev = _make_evaluator(wb_v, wb_f)
    max_col, max_row = wsv.max_column, wsv.max_row

    mrow = _find_month_row(wsv)
    month_map = _build_month_map(wsv, mrow, max_col)
    gran_map = _build_gran_map(wsv, mrow, max_col)
    year_blocks = _find_year_blocks(wsv, mrow, max_col)
    has_yb = any(yb[0] for yb in year_blocks.values())
    base_year = max([yb[0] for yb in year_blocks.values() if yb[0]], default=None)

    data_cols = [c for c in range(1, max_col + 1) if month_map.get(c)]
    if not data_cols:
        return {"area": area, "months": [], "current_month": current_month, "rows": []}
    first_data = min(data_cols)
    label_area = list(range(1, first_data))
    data_start = mrow + 1

    # dtype 열(목표/실적/계획 최다 열) → row-dtype 패턴 식별
    hits = {c: 0 for c in label_area}
    for r in range(data_start, max_row + 1):
        for c in label_area:
            if _is_dtype(wsv.cell(r, c).value):
                hits[c] += 1
    dtype_col = max(hits, key=lambda c: hits[c]) if hits and max(hits.values()) > 0 else None
    label_cols = [c for c in label_area if c != dtype_col]

    # row-dtype 시트: dtype 열에 연도(`25실적 / `26실적)가 박혀 있으면 → 최대연도=당해, 미만=전년 행.
    # (가공비 등은 year-block 아님 — 전년 실적이 같은 컬럼·다른 '행'에 있음)
    rd_years = set()
    if dtype_col is not None:
        for r in range(data_start, max_row + 1):
            yy, _ = _split_dtype(str(wsv.cell(r, dtype_col).value or "").strip())
            if yy is not None:
                rd_years.add(yy)
    rd_base = max(rd_years) if rd_years else None

    def _is_formula(coord: str) -> bool:
        v = wsf[coord].value
        return isinstance(v, str) and v.startswith("=")

    _NAME = _ref_res(wb_f.sheetnames)["NAME"]
    _AGG_RE = re.compile(rf"(?:({_NAME})!)?\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?")

    def _is_agg(coord: str) -> bool:
        """수식이 **다른 행/시트** 셀을 참조하면 세로집계(소계/합계/롤업)로 본다.
        같은 행 참조(=AJ6, =SUM(AL6:AP6) 주차 가로합)는 leaf 의 월합계 → 소계 아님."""
        v = wsf[coord].value
        if not (isinstance(v, str) and v.startswith("=")):
            return False
        self_row = int(re.match(r"[A-Z]+(\d+)", coord).group(1))
        for m in _AGG_RE.finditer(v[1:]):
            sh = _strip_q(m.group(1)) if m.group(1) else None
            if sh and sh != sheet_name:
                return True
            r1 = int(m.group(3))
            r2 = int(m.group(5)) if m.group(5) else r1
            if r1 != self_row or r2 != self_row:
                return True
        return False

    # 컬럼 분류: (월, 구분(월계|주차), 주차, kind) — kind 는 year-block 만 컬럼이 정함
    col_info: Dict[int, dict] = {}
    for c in data_cols:
        gran, wk = gran_map[c]
        yy, kk = year_blocks.get(c, (None, None))
        col_info[c] = {"월": int(month_map[c][:-1]),
                       "구분": "주차" if gran == "주차" else "월계",
                       "주차": wk, "year": yy, "kind": kk}

    all_months: set = set()

    def _eval_at(rownum: int, kind: str, gran: str, mo: int, year: Optional[int] = None):
        """라벨-아이템 한 줄에서 (kind, 월, 구분) 에 해당하는 셀 평가. 없으면 None.
        year 지정 시 그 연도 블록(전년 동기 등) 평가, 미지정이면 base_year(당해)."""
        yr = year if year is not None else base_year
        best = None
        for c, info in col_info.items():
            if info["월"] != mo or info["구분"] != gran:
                continue
            if has_yb:
                if info["year"] != yr or info["kind"] != kind:
                    continue
            coord = f"{get_column_letter(c)}{rownum}"
            # 빈 raw 셀이면 None 유지(0 으로 오염 방지)
            raw = wsv[coord].value
            if not _is_formula(coord) and raw is None:
                continue
            return ev(sheet_name, coord), _is_agg(coord)
        return best

    def _row_nf(rownum: Optional[int]) -> Optional[str]:
        """이 행의 대표 셀(당해 월계) 엑셀 number_format — 표시 서식 미러용(퍼센트/소수자리).
        행 안에서 서식은 일관되므로 첫 월계 컬럼 하나로 대표한다. (year-block 은 당해 실적 블록)"""
        if not rownum:
            return None
        for c, info in sorted(col_info.items()):
            if info["구분"] != "월계":
                continue
            if has_yb and (info.get("year") != base_year or info.get("kind") != "실적"):
                continue
            return wsv[f"{get_column_letter(c)}{rownum}"].number_format
        return None

    def _weeks_at(row_t: int, row_a: int, mo: int, row_prev: Optional[int] = None):
        """당월 주차 목록 — 주차 컬럼들(W#)에서 목표(row_t)/실적(row_a)/전년 평가.

        전년 주차: year-block = 같은 주차의 prev_year 실적 컬럼(같은 행) / row-dtype = 같은 주차 컬럼,
        전년 행(row_prev). 양식에 주차별 전년이 있으면(예 물류비 W1 전년=F6) 그대로 채운다.
        """
        # year-block: (주차 라벨 → prev_year 실적 주차 컬럼) 맵 (월계 전년과 동일 규칙)
        prev_wcol: Dict[str, int] = {}
        if has_yb and prev_year:
            for c2, i2 in col_info.items():
                if (i2["월"] == mo and i2["구분"] == "주차"
                        and i2.get("year") == prev_year and i2.get("kind") == "실적"):
                    prev_wcol[i2["주차"] or get_column_letter(c2)] = c2
        out = []
        seen = set()
        for c, info in sorted(col_info.items()):
            if info["월"] != mo or info["구분"] != "주차":
                continue
            if has_yb and info["kind"] not in (None, "실적"):
                # year-block 은 실적 블록에만 주차 → 목표 주차 없음
                pass
            wk = info["주차"] or get_column_letter(c)
            if wk in seen:
                continue
            seen.add(wk)
            tcoord = f"{get_column_letter(c)}{row_t}" if row_t else None
            acoord = f"{get_column_letter(c)}{row_a}" if row_a else None
            t = ev(sheet_name, tcoord) if (tcoord and (wsv[tcoord].value is not None or _is_formula(tcoord))) else None
            a = ev(sheet_name, acoord) if (acoord and (wsv[acoord].value is not None or _is_formula(acoord))) else None
            # 전년 주차 — year-block(prev_year 실적 컬럼, 같은 행) / row-dtype(같은 컬럼, 전년 행)
            prev = None
            if has_yb and prev_year and row_a and wk in prev_wcol:
                pc = f"{get_column_letter(prev_wcol[wk])}{row_a}"
                if wsv[pc].value is not None or _is_formula(pc):
                    prev = ev(sheet_name, pc)
            elif row_prev:
                pc = f"{get_column_letter(c)}{row_prev}"
                if wsv[pc].value is not None or _is_formula(pc):
                    prev = ev(sheet_name, pc)
            rate = round(a / t * 100, 1) if (t and a is not None) else None
            out.append({"주차": wk, "목표": t, "실적": a, "전년": prev, "달성률": rate})
        return out

    # ── 라벨-아이템 추출 (ffill) ──
    from collections import OrderedDict
    label_state: Dict[int, Optional[str]] = {c: None for c in label_cols}
    # 병합 블록 인스턴스 번호 — 라벨 컬럼에 **새 값(병합 top)** 이 찍힐 때마다 증가.
    #   고정비처럼 라벨 없는 반복 블록(사업부 내 Control ×3 등)이 경로가 같아 1개로 뭉치는 것 방지:
    #   items 키를 경로가 아니라 (컬럼,라벨,블록번호) 시그니처로 → 같은 블록의 F행(25실적/26목표/26예상)은
    #   라벨이 안 바뀌어 같은 시그니처(정상 병합), 새 병합 블록은 다른 번호(별도 행). 표시 경로는 그대로.
    block_seq: Dict[int, int] = {c: 0 for c in label_cols}
    _bseq = 0
    # 말단(리프) 라벨 컬럼 — 이 컬럼의 라벨 재등장은 블록을 나누지 않는다.
    #   이유: 투자비/매출2 는 dtype(목표/실적)가 라벨 위치(D)라 리프(Base/총매출 등)가 목표·실적 블록마다
    #   재기술됨 → 리프까지 새 블록으로 쪼개면 목표행(빈)·실적행(값)이 분리(회귀). 리프 재등장은 무시.
    #   고정비의 반복 블록(Control ×3)은 **비말단**(C=Control)이 재시작 → 그건 분리(정상).
    leaf_col = max(label_cols) if label_cols else None
    items: "OrderedDict[tuple, dict]" = OrderedDict()
    dt_year: Optional[int] = None   # dtype(목표/실적) ffill 상태 — 투자비처럼 블록당 1번만 적힌 양식 대응
    dt_kind: Optional[str] = None

    def _path_now() -> str:
        return " / ".join(x for x in label_state.values() if x)

    for r in range(data_start, max_row + 1):
        for c in label_cols:
            v = wsv.cell(r, c).value
            if v is not None and str(v).strip():
                label_state[c] = str(v).strip()
                if c != leaf_col:      # 비말단 라벨 재시작만 새 블록(리프 재등장=dtype 순환이라 무시)
                    _bseq += 1
                    block_seq[c] = _bseq
        path = _path_now()
        if not path:
            continue
        # 데이터가 하나도 없는 빈 행(양식 하단 패딩 등)은 건너뛴다 — ffill 된 dtype(예 '실적')로
        #   실데이터 행의 row_a/row_t 를 빈 행으로 덮어써 값이 사라지는 것 방지.
        #   (예: 재료비 제품2 아웃소싱 아래 빈 행들이 실적 행을 덮어 None 으로 만들던 버그.)
        if not any(wsv.cell(r, c).value is not None or _is_formula(f"{get_column_letter(c)}{r}")
                   for c in data_cols):
            continue
        # 블록 시그니처 = 경로 구성 컬럼별 (컬럼, 라벨, 블록번호). 라벨 같아도 블록번호 달라 별도 행.
        sig = tuple((c, label_state[c], block_seq[c]) for c in label_cols if label_state[c])
        # 이 행의 kind: row-dtype 이면 dtype 열, year-block 이면 컬럼이 정함(아래서 처리)
        # dtype(목표/실적)는 투자비처럼 블록당 D 한 번만 적힌 양식 대비 ffill(빈 칸=직전 헤더 상속).
        row_kind = None
        row_year = None
        if dtype_col is not None:
            dv = wsv.cell(r, dtype_col).value
            if dv is not None and str(dv).strip():
                dt_year, dt_kind = _split_dtype(str(dv).strip())
            row_year, row_kind = dt_year, dt_kind
        it = items.setdefault(sig, {"path": path, "row_t": None, "row_a": None,
                                    "row_prev": None, "row_any": None, "is_subtotal": False})
        it["row_any"] = it["row_any"] or r
        if has_yb:
            # 한 줄에 목표/실적 모두 — 같은 행
            it["row_t"] = it["row_a"] = r
        else:
            if row_kind in ("목표", "계획"):
                it["row_t"] = r
            elif row_kind == "실적":
                if row_year is not None and rd_base is not None and row_year < rd_base:
                    it["row_prev"] = r   # 전년 실적 행 (`25실적)
                else:
                    it["row_a"] = r
            else:
                it["row_t"] = it["row_t"] or r  # dtype 없는 단일 행

    months_set: set = set(info["월"] for info in col_info.values())
    months = sorted(months_set)
    cur = current_month or (months[-1] if months else 12)
    # 전년 동기 비교 — year-block 시트(전년 실적 블록 보유)만. 전년 = 당해(base_year) − 1.
    # (연도 하드코딩 X → 2027 스냅샷 들어오면 2026 이 자동으로 전년)
    prev_year = (base_year - 1) if (has_yb and base_year) else None

    rows: List[dict] = []
    for it in items.values():
        path = it["path"]   # 표시 경로(중복 가능 — 라벨 없는 반복 블록은 같은 경로로 여러 행)
        row_t, row_a, row_prev = it["row_t"], it["row_a"], it["row_prev"]
        # 비율(Rate) 행 — 말단(마지막 세그먼트)이 'Rate'/'율'(VI율·가공비율 등)인 행만.
        # ⚠️ 전체 경로로 보면 섹션명이 '가공비율'인 시트에서 그 아래 '생산액'·'가공비'(금액)까지
        #    '율'에 걸려 %로 오표시됨 → 반드시 leaf(말단)만 판정.
        leaf = path.split(" / ")[-1]
        is_rate = bool(re.search(r"rate|율", leaf, re.I))
        # 엑셀 셀 서식으로 표시 규칙 확정 — 퍼센트 서식(0.0%)이면 leaf 휴리스틱이 놓쳐도 비율로.
        #   (예: '… / VI율 / 아웃소싱' 은 leaf 가 '아웃소싱'이라 '율' 미매칭 → 서식이 진실.)
        pct, dec = _fmt_spec(_row_nf(it["row_a"] or it["row_t"]))
        is_rate = is_rate or pct
        cells: Dict[str, dict] = {}
        is_sub = False
        for mo in months:
            tt = _eval_at(row_t, "목표", "월계", mo) if row_t else None
            aa = _eval_at(row_a, "실적", "월계", mo) if row_a else None
            t = tt[0] if tt else None
            a = aa[0] if aa else None
            # 전년 동기 실적 — year-block(같은 행, 전년 연도 컬럼) 또는 row-dtype(별도 `25실적 행)
            prev = None
            if has_yb and prev_year and row_a:
                pp = _eval_at(row_a, "실적", "월계", mo, year=prev_year)
                prev = pp[0] if pp else None
            elif row_prev:
                pp = _eval_at(row_prev, "실적", "월계", mo)
                prev = pp[0] if pp else None
            if (tt and tt[1]) or (aa and aa[1]):
                is_sub = True
            future = mo > cur
            # 월 네비게이션 — 모든 월의 주차를 저장(과거 월도 당월 토글에서 차수 표시 가능).
            weeks = _weeks_at(row_t, row_a, mo, row_prev)
            # 월계 컬럼이 엑셀에 없으면(예: 당월) 주차에서 월 값을 채운다 — "없으면 구해서 채움".
            # 목표·실적 모두 부서가 **누적**으로 적어옴 → 그 달 값 = 주차 합이 아니라
            # **마지막(최신) 주차 값**. (weeks 는 주차 번호 오름차순 → 마지막 non-None 이 최신)
            if t is None and weeks:
                wt = [w["목표"] for w in weeks if w["목표"] is not None]
                t = wt[-1] if wt else None
            # 공식 월계 실적이 없으면 주차 마지막(=최신 누적)값으로 채우고 잠정 마킹(월계 lag).
            # ⚠️ 합계/소계 행은 월계 수식이 '빈 셀들의 합=0.0'으로 평가돼 a 가 None 이 아니라 0 → leaf 와
            #    달리 롤업이 안 됐다(개별 그래프=0·비잠정 vs 전체=508·잠정 어긋남). 월계가 None 이거나
            #    0 인데 주차 누적값이 유의미하면(=공식 월계 미도착) 동일하게 롤업+잠정.
            prov = False
            if weeks:
                wa = [w["실적"] for w in weeks if w["실적"] is not None]
                last = wa[-1] if wa else None
                if last is not None and (a is None or (abs(a) < 1e-9 and abs(last) > 1e-9)):
                    a = last; prov = True
            if future:
                a = None; prov = False
            rate = round(a / t * 100, 1) if (t and a is not None) else None
            # 저장 정밀도 — 비율(0.0769 등)은 ×100 표시 대비 4자리, 금액은 표시 서식(dec) 이상 보존.
            nd = 4 if is_rate else max(2, dec if dec is not None else 2)
            cells[str(mo)] = {
                "목표": round(t, nd) if t is not None else None,
                "실적": round(a, nd) if a is not None else None,
                "전년": round(prev, nd) if prev is not None else None,
                "달성률": rate,
                "잠정": bool(prov) and a is not None,
                "weeks": weeks,
            }
        segs = path.split(" / ")
        # Rate(비율)는 =G11/G3 식으로 다른 행을 나눗셈 참조해 소계로 오판되지만,
        # 합계/소계(세로 합산)가 아니라 파생 비율 → 소계 음영에서 제외(% 표시는 is_rate 로 따로).
        # pct/dec = 엑셀 표시 서식(프론트가 그대로 미러). dec None = 명시 서식 없음(프론트 폴백 규칙).
        rows.append({"부서경로": path, "level": len(segs) - 1,
                     "is_subtotal": is_sub and not is_rate, "is_rate": is_rate,
                     "pct": pct, "dec": dec, "cells": cells})

    return {"area": area, "months": months, "current_month": cur, "rows": rows}


if __name__ == "__main__":  # 검증
    import glob
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    orig = glob.glob(str(Path(__file__).resolve().parents[2] / "docs" / "lg_samples" / "excel" / "*Master*ver0.1.xlsx"))[0]
    hl = master_headline(orig)
    jan = hl[(hl["월"] == 1) & (hl["구분"] == "월계")]
    ex_h = jan[jan["항목"] != registry.DERIVED_SLUG]
    print(f"전체 {len(hl)}행 (월계 {int((hl['구분']=='월계').sum())} / 주차 {int((hl['구분']=='주차').sum())})")
    print("항목별 1월(월계):")
    for area in sorted(hl["항목"].unique()):
        t = jan[(jan["항목"] == area) & (jan["종류"] == "목표")]["값"].sum()
        a = jan[(jan["항목"] == area) & (jan["종류"] == "실적")]["값"].sum()
        print(f"  {area}: 목표={t:8.2f}  실적={a:8.2f}")
    print("\n[검증] 1월 실적(H제외):", round(ex_h[ex_h["종류"] == "실적"]["값"].sum(), 2), "(기대 361.05)")
    print("[검증] 1월 실적(전체) :", round(jan[jan["종류"] == "실적"]["값"].sum(), 2), "(기대 351.05)")
    print("[검증] 1월 목표(H제외):", round(ex_h[ex_h["종류"] == "목표"]["값"].sum(), 2), "(기대 358.48)")
