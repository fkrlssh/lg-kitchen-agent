"""엑셀 파일 파싱.

각 비용 카테고리별 xlsx 파일을 받아서 통일된 DataFrame으로 반환.
운영 단계에서는 부서별로 양식이 다를 수 있어 LLM normalize 단계 추가 가능.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Iterable, Tuple, Union

import pandas as pd

from .schema import EXCEL_COLUMNS

FileLike = Union[str, Path, BinaryIO]


def read_one(path_or_bytes: FileLike, category: str) -> pd.DataFrame:
    """단일 xlsx → 정규화된 DataFrame.

    표준 컬럼: 부서 / 세부항목 / 목표(억원) / 실적(억원) / 비고.
    추가로 '카테고리' 컬럼을 채워서 반환.
    """
    df = pd.read_excel(path_or_bytes, engine="openpyxl")
    # 누락 컬럼 채우기
    for col in EXCEL_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ("부서", "세부항목", "비고") else 0
    df = df[EXCEL_COLUMNS].copy()
    df["카테고리"] = category
    # 숫자 컬럼 강제 변환
    for col in ("목표(억원)", "실적(억원)"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def read_many(files: Iterable[Tuple[str, FileLike]]) -> pd.DataFrame:
    """[(category, file)...] → 통합 DataFrame."""
    frames = [read_one(f, cat) for cat, f in files]
    if not frames:
        return pd.DataFrame(columns=EXCEL_COLUMNS + ["카테고리"])
    return pd.concat(frames, ignore_index=True)
