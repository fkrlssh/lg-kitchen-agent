"""집계 — 영역별 실적 집계 (요구사항의 Output #1)."""
from __future__ import annotations

import pandas as pd

from .schema import CATEGORIES, CATEGORY_ORDER


def add_achievement(df: pd.DataFrame) -> pd.DataFrame:
    """달성률(%) 컬럼 추가. 목표 0이면 NaN."""
    df = df.copy()
    df["달성률(%)"] = (df["실적(억원)"] / df["목표(억원)"].replace(0, pd.NA) * 100).astype(float)
    return df


def by_category(df: pd.DataFrame) -> pd.DataFrame:
    """카테고리별 합계 + 달성률."""
    agg = (
        df.groupby("카테고리", sort=False)[["목표(억원)", "실적(억원)"]]
        .sum()
        .reset_index()
    )
    agg["달성률(%)"] = (agg["실적(억원)"] / agg["목표(억원)"].replace(0, pd.NA) * 100).astype(float)
    # 카테고리 순서 고정
    agg["__order"] = agg["카테고리"].apply(lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 999)
    agg = agg.sort_values("__order").drop(columns="__order").reset_index(drop=True)
    return agg


def by_department(df: pd.DataFrame, category: str | None = None) -> pd.DataFrame:
    """부서별 합계 (옵션: 카테고리 필터)."""
    src = df if category is None else df[df["카테고리"] == category]
    agg = (
        src.groupby(["카테고리", "부서"], sort=False)[["목표(억원)", "실적(억원)"]]
        .sum()
        .reset_index()
    )
    agg["달성률(%)"] = (agg["실적(억원)"] / agg["목표(억원)"].replace(0, pd.NA) * 100).astype(float)
    return agg


def total(df: pd.DataFrame) -> dict:
    """전체 합계 (대시보드 상단 메트릭용)."""
    target = float(df["목표(억원)"].sum())
    actual = float(df["실적(억원)"].sum())
    return {
        "목표": target,
        "실적": actual,
        "달성률": (actual / target * 100) if target else 0.0,
        "항목수": len(df),
    }


def missing_departments(df: pd.DataFrame) -> dict[str, list[str]]:
    """카테고리별로 회신 안 온 부서 목록 (요구사항: 실적/대책 미회신 부서 확인)."""
    result: dict[str, list[str]] = {}
    for cat, expected in CATEGORIES.items():
        received = set(df[df["카테고리"] == cat]["부서"].astype(str).unique())
        missing = [d for d in expected if d not in received]
        if missing:
            result[cat] = missing
    return result
