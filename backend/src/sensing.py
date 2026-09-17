"""목표 달성 Sensing / 이상 징후 Monitoring (요구사항의 Output #2, #3).

룰 기반 1차 분류 → LLM narrative는 narrative.py 가 담당.
"""
from __future__ import annotations

import pandas as pd

from .schema import DEFAULT_THRESHOLD, Threshold, status_for


def classify(df: pd.DataFrame, t: Threshold = DEFAULT_THRESHOLD) -> pd.DataFrame:
    """각 행에 상태(정상/경고/위험) 컬럼 추가."""
    df = df.copy()
    df["달성률(%)"] = (df["실적(억원)"] / df["목표(억원)"].replace(0, pd.NA) * 100).astype(float)
    df["상태"] = df["달성률(%)"].fillna(0).apply(lambda p: status_for(p, t))
    return df


def anomalies(df: pd.DataFrame, t: Threshold = DEFAULT_THRESHOLD) -> pd.DataFrame:
    """경고/위험 항목만 추출 — 정렬: 위험 먼저, 그 다음 달성률 낮은 순."""
    classified = classify(df, t)
    a = classified[classified["상태"].isin(("경고", "위험"))].copy()
    a["__sev"] = a["상태"].map({"위험": 0, "경고": 1}).fillna(2)
    a = a.sort_values(["__sev", "달성률(%)"]).drop(columns="__sev").reset_index(drop=True)
    return a


def summary_counts(df: pd.DataFrame, t: Threshold = DEFAULT_THRESHOLD) -> dict:
    classified = classify(df, t)
    counts = classified["상태"].value_counts().to_dict()
    return {
        "정상": int(counts.get("정상", 0)),
        "경고": int(counts.get("경고", 0)),
        "위험": int(counts.get("위험", 0)),
        "총": int(len(classified)),
    }
