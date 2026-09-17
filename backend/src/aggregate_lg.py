"""LG raw(long) → 사람용 집계(피벗) — 즉석 계산.

저장하지 않는다. 조회할 때마다 raw 에서 계산해서 돌려준다.
(누적/Master 와 같은 파생값 — 원천만 저장, 나머지는 재현 원칙)

핵심: pivot_achievement = 항목 1개를 부서×월 [목표/실적/달성률] 매트릭스로.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

import pandas as pd

from . import registry

MONTHS = list(range(1, 13))


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def clip_future(df: pd.DataFrame, period_id: str) -> pd.DataFrame:
    """스냅샷 회차 이후의 미래 월 제거.

    예: 2026-06-1 스냅샷이면 당해(2026)는 6월까지만 실적 인정 → 7월+ 행 제거.
    이전 연도(2025 등)는 이미 완결이라 그대로 둠.
    (미래 달에 남아있는 샘플 잔재/예측값이 달성률·종합을 오염시키는 것 방지)
    """
    if df is None or len(df) == 0:
        return df
    parts = str(period_id).split("-")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return df
    y, mo = int(parts[0]), int(parts[1])
    return df[~((df["연도"] == y) & (df["월"] > mo))].copy()


def pivot_achievement(df: pd.DataFrame, 항목: str, 연도: Optional[int] = None) -> dict:
    """항목 1개 → 부서경로(행) × 월 [목표/실적/달성률].

    - 월계(구분='월계')만 사용 (주차 제외)
    - 목표/계획은 '목표'로 통합 (항목4는 '계획' 사용)
    - 달성률 = 실적/목표*100 (목표 0/없으면 None)
    ⚠️ 월계 lag(주차 마지막값 채움+잠정)는 여기선 적용 안 함 — leaf 단위 /data 업데이트 뷰라
       그대로 둔다. 마감 보고서의 잠정 처리는 master_detail/master_table/overview_master 가 담당.
       (셀에 잠정:False 만 부착해 스키마는 통일)
    """
    if df is None or len(df) == 0:
        return {"항목": 항목, "연도": 연도, "months": MONTHS, "rows": []}

    d = df[(df["항목"] == 항목) & (df["구분"] == "월계")].copy()
    if 연도 is not None:
        d = d[d["연도"] == 연도]
    if len(d) == 0:
        return {"항목": 항목, "연도": 연도, "months": MONTHS, "rows": []}

    # 종류 → 지표 통합
    d["지표"] = d["종류"].map(
        lambda k: "목표" if k in ("목표", "계획") else ("실적" if k == "실적" else "기타")
    )
    d = d[d["지표"].isin(["목표", "실적"])]

    g = d.groupby(["부서경로", "월", "지표"], as_index=False)["값"].sum()

    rows: List[dict] = []
    for dept, sub in g.groupby("부서경로", sort=False):
        cells: Dict[str, dict] = {}
        for month, msub in sub.groupby("월"):
            mp = dict(zip(msub["지표"], msub["값"]))
            tgt, act = _num(mp.get("목표")), _num(mp.get("실적"))
            rate = round(act / tgt * 100, 1) if tgt not in (None, 0) and act is not None else None
            cells[str(int(month))] = {"목표": tgt, "실적": act, "달성률": rate, "잠정": False}
        rows.append({"부서경로": dept, "cells": cells})

    return {"항목": 항목, "연도": 연도, "months": MONTHS, "rows": rows}


def overview(df: pd.DataFrame, 연도: Optional[int] = None) -> dict:
    """전 항목 한눈에 (Master 뷰) — 항목(행) × 월 [목표/실적/달성률] + 항목별 종합.

    - 월계만, 목표/계획→목표 통합
    - 항목별 종합 = 전 월·전 부서 합 → 달성률
    """
    empty = {"연도": 연도, "months": MONTHS, "rows": []}
    if df is None or len(df) == 0:
        return empty

    d = df[df["구분"] == "월계"].copy()
    if 연도 is not None:
        d = d[d["연도"] == 연도]
    if len(d) == 0:
        return empty

    d["지표"] = d["종류"].map(
        lambda k: "목표" if k in ("목표", "계획") else ("실적" if k == "실적" else "기타")
    )
    d = d[d["지표"].isin(["목표", "실적"])]
    g = d.groupby(["항목", "월", "지표"], as_index=False)["값"].sum()

    rows: List[dict] = []
    for item, sub in g.groupby("항목", sort=True):
        cells: Dict[str, dict] = {}
        t_tot = 0.0
        a_tot = 0.0
        for month, msub in sub.groupby("월"):
            mp = dict(zip(msub["지표"], msub["값"]))
            tgt, act = _num(mp.get("목표")), _num(mp.get("실적"))
            rate = round(act / tgt * 100, 1) if tgt not in (None, 0) and act is not None else None
            # 월계 lag 채움은 미적용(leaf /data 뷰) — 잠정:False 로 스키마만 통일. (pivot_achievement 주석 참조)
            cells[str(int(month))] = {"목표": tgt, "실적": act, "달성률": rate, "잠정": False}
            # 종합 = YTD: 실적 있는 달만 (목표·실적 같은 기간) → 연중에도 의미 있는 달성률
            if act is not None:
                if tgt:
                    t_tot += tgt
                a_tot += act
        종합 = {
            "목표": t_tot or None,
            "실적": a_tot or None,
            "달성률": round(a_tot / t_tot * 100, 1) if t_tot else None,
        }
        rows.append({"항목": item, "cells": cells, "종합": 종합})

    return {"연도": 연도, "months": MONTHS, "rows": rows}


def overview_master(hl: pd.DataFrame, exclude_derived: str = registry.DERIVED_SLUG) -> dict:
    """Master 대표총계(headline) → 항목(행) × 월 [목표/실적/달성률] + 종합 + 합계(H제외).

    leaf 합산이 아니라 Master 가 지정한 Area 대표총계(master_lg.master_headline)를 사용.
    한 Area 에 대표행이 여러 개면(예: Area_A=Type_A+Type_B) 합산.
    """
    empty = {"months": MONTHS, "rows": [], "total": None}
    if hl is None or len(hl) == 0:
        return empty
    # 월계 lag — 공식 월계 실적이 없는 달은 주차 마지막(=최신 누적)값으로 채우고 잠정 표시
    # (master_detail/master_table 과 동일 규칙). ⚠️ 한계: 어떤 달에 월계가 목표·실적 모두
    #  없으면 groupby 에 안 잡혀 채움 대상에서 빠짐 — 그 경우만 master_detail 과 차이날 수 있음.
    last_wk: Dict[tuple, float] = {}   # (항목,월) → 최신 주차 실적
    if "구분" in hl.columns:
        wk = hl[(hl["구분"] == "주차") & (hl["종류"] == "실적")]
        if len(wk):
            gw = wk.groupby(["항목", "월", "주차"], as_index=False)["값"].sum()
            gw = gw.assign(_n=gw["주차"].map(lambda x: int(re.sub(r"\D", "", str(x)) or 0)))
            for (it_, mo_), s in gw.sort_values("_n").groupby(["항목", "월"]):
                last_wk[(it_, int(mo_))] = _num(s["값"].iloc[-1])
        hl = hl[hl["구분"] == "월계"]
    g = hl.groupby(["항목", "종류", "월"], as_index=False)["값"].sum()

    # grand[키][월] — full=전체(H포함), ex=H제외
    grand = {"full": ({}, {}), "ex": ({}, {})}  # 키 → (목표맵, 실적맵)
    grand_prov = {"full": set(), "ex": set()}   # 잠정 실적이 섞인 월
    rows: List[dict] = []
    for area, sub in g.groupby("항목", sort=True):
        cells: Dict[str, dict] = {}
        t_tot = a_tot = 0.0
        prov_any = False
        for month, msub in sub.groupby("월"):
            mo = int(month)
            mp = dict(zip(msub["종류"], msub["값"]))
            tgt, act = _num(mp.get("목표")), _num(mp.get("실적"))
            prov = False
            if act is None:
                fa = last_wk.get((area, mo))
                if fa is not None:
                    act = fa; prov = True; prov_any = True
            rate = round(act / tgt * 100, 1) if tgt not in (None, 0) and act is not None else None
            cells[str(mo)] = {"목표": tgt, "실적": act, "달성률": rate, "잠정": prov}
            if act is not None:
                if tgt:
                    t_tot += tgt
                a_tot += act
                for key in ("full",) + (("ex",) if area != exclude_derived else ()):
                    tmap, amap = grand[key]
                    tmap[mo] = tmap.get(mo, 0.0) + (tgt or 0.0)
                    amap[mo] = amap.get(mo, 0.0) + act
                    if prov:
                        grand_prov[key].add(mo)
        종합 = {
            "목표": t_tot or None, "실적": a_tot or None,
            "달성률": round(a_tot / t_tot * 100, 1) if t_tot else None,
            "잠정": prov_any and a_tot != 0.0,
        }
        rows.append({"항목": area, "derived": area == exclude_derived, "cells": cells, "종합": 종합})

    def _total_row(label: str, key: str) -> dict:
        tmap, amap = grand[key]
        tcells: Dict[str, dict] = {}
        gt = ga = 0.0
        for mo in MONTHS:
            tgt, act = tmap.get(mo), amap.get(mo)
            if tgt is None and act is None:
                continue
            rate = round(act / tgt * 100, 1) if tgt and act is not None else None
            tcells[str(mo)] = {"목표": tgt, "실적": act, "달성률": rate,
                               "잠정": mo in grand_prov[key]}
            if act is not None:
                gt += tgt or 0.0
                ga += act
        return {"항목": label, "cells": tcells,
                "종합": {"목표": gt or None, "실적": ga or None,
                        "달성률": round(ga / gt * 100, 1) if gt else None,
                        "잠정": bool(grand_prov[key]) and ga != 0.0}}

    return {
        "months": MONTHS,
        "rows": rows,
        "total": _total_row("합계 (전체)", "full"),
        "total_ex": _total_row(f"합계 ({exclude_derived} 제외)", "ex"),
    }


def master_detail(hl: pd.DataFrame, current_month: Optional[int] = None,
                  exclude_derived: str = registry.DERIVED_SLUG,
                  all_items: Optional[List[str]] = None,
                  component_items: Optional[List[str]] = None) -> dict:
    """보고서 운영용 — 항목별 월/주차 상세 + 누적/당월 요약.

    반환:
      months: 실제 데이터 있는 월
      items: [{항목, derived, component, months:{월:{목표,실적,달성률, weeks:[...]}},
               누적:{목표,실적,차이,달성률}, 당월:{...}}]
      summary: 전체(파생제외) 누적·당월 요약 + 월별 합계(그래프용)
    current_month 미지정 시 데이터 있는 마지막 월.

    all_items 주면 **전 항목 항상 포함** — 데이터 없어도 빈 셀로 자리 잡음. 순서도 그 목록 기준.
    component_items(예: 고정비 하위 4종): **데이터는 표시하되 합계(g_full/g_ex)·top3 에선 제외**
      — 파생(고정비)이 이미 합산하므로 이중계산 방지. 화면엔 `component: True` 로 내려감.
    """
    empty = {"months": [], "items": [], "summary": None}
    if hl is None or len(hl) == 0:
        return empty
    comps = set(component_items or [])
    has_w = "구분" in hl.columns
    mo_df = hl[hl["구분"] == "월계"] if has_w else hl
    if not len(mo_df):
        return empty

    months = sorted(int(m) for m in mo_df["월"].unique())
    cur = current_month or months[-1]

    def _cell(sub):
        mp = dict(zip(sub["종류"], sub["값"]))
        t, a = _num(mp.get("목표")), _num(mp.get("실적"))
        rate = round(a / t * 100, 1) if t not in (None, 0) and a is not None else None
        return {"목표": t, "실적": a, "달성률": rate}

    items: List[dict] = []
    # 그래프용 월별 합계 — 목표는 전 월(계획), 실적은 현재월까지만. ex(H제외)/full(H포함)
    g_ex = {m: {"목표": 0.0, "실적": 0.0} for m in months}
    g_full = {m: {"목표": 0.0, "실적": 0.0} for m in months}
    for area, asub in mo_df.groupby("항목", sort=True):
        derived = area == exclude_derived
        is_comp = area in comps      # 고정비 하위 = 표시만, 합계엔 미가산
        mcells: dict = {}
        cum_t = cum_a = 0.0
        cum_prov = False
        for m in months:
            msub = asub[asub["월"] == m]
            c = _cell(msub)
            # 주차
            weeks = []
            if has_w and m <= cur:
                wk = hl[(hl["항목"] == area) & (hl["월"] == m) & (hl["구분"] == "주차")]
                for w, wsub in wk.groupby("주차", sort=True):
                    wc = _cell(wsub)
                    weeks.append({"주차": w, **wc})
                weeks.sort(key=lambda x: int(re.sub(r"\D", "", str(x["주차"])) or 0))
            # 월별 목표/실적 확정 — 공식 월계 실적이 없으면 주차 마지막(=최신 누적)값으로 채우고 잠정.
            # (master_table/area_table 과 동일 규칙 → 같은 항목·달 숫자/잠정이 일치해야 함)
            t = c["목표"]; a = c["실적"]; prov = False
            # 마감(월계) 실적이 없거나(None) — 또는 대표총계 수식이 0 인데 주차 누적값이 확실히 존재(≠0)해
            # '마감 미도착'이 분명하면 — 주차 마지막(=최신 누적)값으로 채우고 잠정(예: 물류비 4월 마감만 제거).
            # (주차값도 없으면 아래 미수집 감지로 넘어감. 월계가 진짜 0이면 주차 누적도 0 → 안 건드림.)
            if m <= cur and weeks:
                wa = [w["실적"] for w in weeks if w["실적"] is not None]
                if wa and (a is None or (a == 0 and wa[-1] not in (None, 0))):
                    a = wa[-1]; prov = True
            rate = round(a / t * 100, 1) if (t not in (None, 0) and a is not None) else None
            if m > cur:  # 미래월 = 목표만, 실적/달성률 비움
                mcells[str(m)] = {"목표": c["목표"], "실적": None, "달성률": None, "잠정": False, "weeks": []}
            else:
                mcells[str(m)] = {"목표": t, "실적": a, "달성률": rate, "잠정": prov, "weeks": weeks}
            # 누적(항목별)은 component 도 계산 — 자기 항목 카드/표에 표시.
            if m <= cur and a is not None:
                cum_t += t or 0.0
                cum_a += a
                if prov:
                    cum_prov = True
            # 합계(그래프/요약)에는 component(고정비 하위) 미가산 — 고정비 롤업과 이중계산 방지.
            if not is_comp:
                g_full[m]["목표"] += t or 0.0
                if not derived:
                    g_ex[m]["목표"] += t or 0.0
                if m <= cur and a is not None:
                    g_full[m]["실적"] += a
                    if prov:
                        g_full[m]["prov"] = True
                    if not derived:
                        g_ex[m]["실적"] += a
                        if prov:
                            g_ex[m]["prov"] = True
        # 미수집(실적 전무) 감지 — 기대 항목(파생·component 제외)인데 m<=cur 에 실적이 한 건도 안 옴
        #   (월계 0/None + 주차 실적도 0/None). → 개별: 그 달 실적 공란(미수집). 전체(합계): 그 항목 몫이
        #   빠진 '불완전 합계'라 그 달 잠정(추정) 표시. (목표는 계획이라 유지 → 합계 목표엔 그대로 반영.)
        expected = not derived and not is_comp
        got_actual = any(
            (mcells[str(m)]["실적"] not in (None, 0))
            or any(w.get("실적") not in (None, 0) for w in mcells[str(m)]["weeks"])
            for m in months if m <= cur)
        missing = expected and not got_actual
        no_target = all(mcells[str(m)]["목표"] in (None, 0) for m in months)
        blank_all = missing and no_target        # 목표도 전무 = 완전 미수집 → 목표까지 공란
        if missing:
            for m in months:
                mm = mcells[str(m)]
                if m <= cur:
                    mm["실적"] = None
                    mm["달성률"] = None
                    mm["잠정"] = False            # 항목 자체는 '미수집'(잠정 아님)
                    g_full[m]["prov"] = True      # 전체 = 이 항목 빠진 불완전 합계 → 잠정
                    g_ex[m]["prov"] = True
                if blank_all:
                    mm["목표"] = None             # 완전 미수집 → 목표도 공란(전 월)
        cur_cell = mcells.get(str(cur), {"목표": None, "실적": None, "달성률": None, "잠정": False})
        items.append({
            "항목": area, "derived": derived, "component": is_comp, "months": mcells,
            "누적": _summary(None if blank_all else cum_t, None if missing else cum_a, False if missing else cum_prov),
            "당월": _summary(cur_cell["목표"], cur_cell["실적"], cur_cell.get("잠정", False)),
        })

    # (b) 전 항목 항상 표시 — 데이터 없는 항목도 빈 칸으로 자리 잡게 (실적 관리와 동일 철학).
    #     칩/탭/표에서 항목 줄은 존재하되 값만 None(프론트는 '–'·회색 칩으로 렌더).
    if all_items:
        present = {it["항목"] for it in items}
        for area in all_items:
            if area in present:
                continue
            is_der = area == exclude_derived
            is_cmp = area in comps
            items.append({
                "항목": area,
                "derived": is_der,
                "component": is_cmp,
                "months": {str(m): {"목표": None, "실적": None, "달성률": None, "잠정": False, "weeks": []} for m in months},
                "누적": _summary(None, None),
                "당월": _summary(None, None),
            })
            if not is_der and not is_cmp:   # 헤드라인에 아예 없는 기대 항목(완전 미수집) → 전체 그 달 잠정(불완전)
                for m in months:
                    if m <= cur:
                        g_full[m]["prov"] = True
                        g_ex[m]["prov"] = True
        order = {a: i for i, a in enumerate(all_items)}  # 목록 순서 우선 안정 정렬
        items.sort(key=lambda it: order.get(it["항목"], len(order)))

    # 실적 요약 (누적 기준, 파생·component 제외 항목) — 계산값, LLM 미사용
    live = [it for it in items if not it["derived"] and not it.get("component")]
    # ① 합계 목표 미달에 가장 큰 영향(금액): 부족분(목표-실적) 큰 순
    short = []
    for it in live:
        t, a = it["누적"]["목표"], it["누적"]["실적"]
        if t is not None and a is not None and t > a:
            short.append({"항목": it["항목"], "부족": round(t - a, 1),
                          "목표": round(t, 1), "실적": round(a, 1), "달성률": it["누적"]["달성률"]})
    short.sort(key=lambda x: x["부족"], reverse=True)
    # ② 달성율 가장 낮은 순
    rated = [{"항목": it["항목"], "달성률": it["누적"]["달성률"],
              "목표": it["누적"]["목표"], "실적": it["누적"]["실적"]}
             for it in live if it["누적"]["달성률"] is not None]
    rated.sort(key=lambda x: x["달성률"])

    def _cum(g):
        t = sum(g[m]["목표"] for m in months if m <= cur)
        a = sum(g[m]["실적"] for m in months if m <= cur)
        prov = any(g[m].get("prov") for m in months if m <= cur)
        return _summary(t, a, prov)

    def _rate(g, m):
        return round(g[m]["실적"] / g[m]["목표"] * 100, 1) if g[m]["목표"] else None

    # 그래프: 전 월(1~12) — 목표는 다, 실적/달성률은 현재월까지(미래는 null)
    chart = []
    for m in months:
        future = m > cur
        chart.append({
            "월": m,
            "목표": round(g_full[m]["목표"], 1),
            "실적": None if future else round(g_full[m]["실적"], 1),
            "달성률": None if future else _rate(g_full, m),
            "잠정": False if future else bool(g_full[m].get("prov", False)),
            "목표_ex": round(g_ex[m]["목표"], 1),
            "실적_ex": None if future else round(g_ex[m]["실적"], 1),
            "달성률_ex": None if future else _rate(g_ex, m),
            "잠정_ex": False if future else bool(g_ex[m].get("prov", False)),
        })

    return {
        "months": months,                # 전 월(미래 포함)
        "current_month": cur,
        "items": items,
        "summary": {
            "누적": _cum(g_ex),          # 기본 = H제외 (실질 총합)
            "당월": _summary(g_ex.get(cur, {}).get("목표", 0.0), g_ex.get(cur, {}).get("실적", 0.0), g_ex.get(cur, {}).get("prov", False)),
            "누적_전체": _cum(g_full),
            "당월_전체": _summary(g_full.get(cur, {}).get("목표", 0.0), g_full.get(cur, {}).get("실적", 0.0), g_full.get(cur, {}).get("prov", False)),
            "chart": chart,
            "shortfall_top3": short[:3],   # 합계 목표 미달 영향 큰 항목 (금액)
            "lowest_top3": rated[:3],      # 달성율 낮은 항목 (비율)
        },
    }


def _summary(t, a, prov=False) -> dict:
    t = _num(t); a = _num(a)
    return {
        "목표": t, "실적": a,
        "차이": (a - t) if (t is not None and a is not None) else None,
        "달성률": round(a / t * 100, 1) if t not in (None, 0) and a is not None else None,
        # 잠정 = 포함된 실적 중 하나라도 공식 월계 아닌 주차 채움값(월계 lag)
        "잠정": bool(prov) and a is not None,
    }


def list_items(df: pd.DataFrame) -> List[str]:
    """집계 가능한 항목(시트) 목록."""
    if df is None or len(df) == 0:
        return []
    return sorted(df["항목"].dropna().unique().tolist())


def leaf_headline(df: pd.DataFrame, slugs: List[str]) -> pd.DataFrame:
    """raw(leaf) → 지정 항목들의 **월별 목표/실적 합** (headline 보강용).

    Master 가 직접 참조 안 하는 항목(예: 고정비 하위 4종)은 master_headline 에 없어
    보고서에서 '미입력'이 됨. 그 항목들의 leaf 월계를 합쳐 headline 행으로 만들어 보강한다.
    (leaf 합 = 시트 총계 — 수식 셀은 parse 단계에서 이미 제외돼 이중계산 없음.)
    반환 컬럼: 항목/종류/월/구분/주차/값 (master_headline 과 동일 스키마, 월계만).
    """
    cols = ["항목", "종류", "월", "구분", "주차", "값"]
    if df is None or len(df) == 0 or not slugs:
        return pd.DataFrame(columns=cols)
    d = df[(df["항목"].isin(slugs)) & (df["구분"] == "월계")].copy()
    if "연도구분" in d.columns:
        d = d[d["연도구분"] == "당해"]
    d["지표"] = d["종류"].map(lambda k: "목표" if k in ("목표", "계획") else ("실적" if k == "실적" else None))
    d = d[d["지표"].notna()]
    if not len(d):
        return pd.DataFrame(columns=cols)
    g = d.groupby(["항목", "지표", "월"], as_index=False)["값"].sum()
    g = g.rename(columns={"지표": "종류"})
    g["구분"] = "월계"
    g["주차"] = None
    return g[cols]
