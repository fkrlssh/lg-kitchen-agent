"""Excel 보고서 생성 — Raw 집계 + 이상 항목."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..aggregation import by_category, by_department, missing_departments
from ..sensing import anomalies as get_anomalies, classify


def build_report(*, df: pd.DataFrame, period: str, narrative_summary: str,
                 anomaly_narratives: Dict[int, str],
                 category_insights: Optional[List[Dict[str, str]]] = None,
                 recommendations: Optional[List[str]] = None,
                 clustering: Optional[Dict[str, Any]] = None,
                 strategy: Optional[Dict[str, Any]] = None) -> bytes:
    """다중 시트 xlsx."""
    out = io.BytesIO()
    classified = classify(df)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        # Summary
        summary = pd.DataFrame({
            "항목": ["기간", "전체 목표(억원)", "전체 실적(억원)", "전체 달성률(%)",
                     "정상", "경고", "위험", "총 항목 수"],
            "값": [
                period,
                f"{df['목표(억원)'].sum():.1f}",
                f"{df['실적(억원)'].sum():.1f}",
                f"{(df['실적(억원)'].sum() / df['목표(억원)'].sum() * 100):.1f}" if df['목표(억원)'].sum() else "0",
                (classified["상태"] == "정상").sum(),
                (classified["상태"] == "경고").sum(),
                (classified["상태"] == "위험").sum(),
                len(classified),
            ],
        })
        summary.to_excel(xw, sheet_name="요약", index=False)

        by_category(df).round(2).to_excel(xw, sheet_name="영역별 집계", index=False)
        by_department(df).round(2).to_excel(xw, sheet_name="부서별 집계", index=False)
        classified.round(2).to_excel(xw, sheet_name="전체 데이터", index=False)
        ano = get_anomalies(df).round(2).reset_index(drop=True).copy()
        if not ano.empty:
            ano["AI 해석"] = [anomaly_narratives.get(i, "") for i in range(len(ano))]
        ano.to_excel(xw, sheet_name="이상 항목", index=False)

        missing = missing_departments(df)
        miss_rows = [{"카테고리": cat, "미회신 부서": d} for cat, depts in missing.items() for d in depts]
        pd.DataFrame(miss_rows or [{"카테고리": "(없음)", "미회신 부서": ""}]).to_excel(
            xw, sheet_name="미회신 부서", index=False
        )

        # 모니 카테고리별 분석
        if category_insights:
            pd.DataFrame(category_insights).to_excel(xw, sheet_name="모니 카테고리 분석", index=False)

        # 모니 클러스터
        if clustering and clustering.get("clusters"):
            cluster_rows = []
            for c in clustering.get("clusters", []):
                idxs = c.get("items", [])
                items_str = ", ".join(
                    f"{ano.iloc[idx]['카테고리']}/{ano.iloc[idx]['부서']}"
                    for idx in idxs if 0 <= idx < len(ano)
                )
                cluster_rows.append({
                    "클러스터": c.get("name", ""),
                    "포함 항목": items_str,
                    "근본원인": c.get("reason", ""),
                })
            reason_rows = (
                [{"단계": "관찰", "내용": o} for o in clustering.get("observations", [])]
                + [{"단계": f"추론 {i}", "내용": s}
                   for i, s in enumerate(clustering.get("reasoning", []), 1)]
            )
            pd.DataFrame(cluster_rows).to_excel(
                xw, sheet_name="모니 이상 클러스터", index=False
            )
            if reason_rows:
                pd.DataFrame(reason_rows).to_excel(
                    xw, sheet_name="모니 사고과정", index=False
                )

        # 모니 Follow-up 전략
        if strategy and strategy.get("strategies"):
            pd.DataFrame(strategy.get("strategies", [])).to_excel(
                xw, sheet_name="모니 Follow-up 전략", index=False
            )

        # 모니 권장 액션
        if recommendations:
            pd.DataFrame(
                [{"#": i, "권장 액션": r} for i, r in enumerate(recommendations, 1)]
            ).to_excel(xw, sheet_name="모니 권장 액션", index=False)

    out.seek(0)
    return out.read()


def save_report(path: Path, **kwargs) -> Path:
    data = build_report(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
