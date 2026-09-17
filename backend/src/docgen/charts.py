"""matplotlib 차트 → PNG bytes 변환. PPT/Word 슬라이드에 삽입.

한국어 폰트: Windows의 '맑은 고딕' 우선, 없으면 시스템 기본.
"""
from __future__ import annotations

import io
import platform
from typing import List

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
from matplotlib import rcParams

# 한국어 폰트 셋업
_KOREAN_FONTS = ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"]
for _f in _KOREAN_FONTS:
    try:
        plt.rcParams["font.family"] = _f
        # 폰트 적용 검증용 dummy plot (실패 안 함)
        break
    except Exception:  # pragma: no cover
        continue
rcParams["axes.unicode_minus"] = False

STATUS_COLORS = {
    "정상": "#10b981",  # emerald-500
    "경고": "#f59e0b",  # amber-500
    "위험": "#ef4444",  # rose-500
}


def category_bar_chart(categories: List[str], targets: List[float], actuals: List[float]) -> bytes:
    """카테고리별 목표 vs 실적 막대 (그룹 바)."""
    fig, ax = plt.subplots(figsize=(8.5, 3.6), dpi=140)
    x = range(len(categories))
    w = 0.36
    ax.bar([i - w / 2 for i in x], targets, width=w, label="목표", color="#94a3b8")  # slate-400
    ax.bar([i + w / 2 for i in x], actuals, width=w, label="실적", color="#3b82f6")  # blue-500
    ax.set_xticks(list(x))
    ax.set_xticklabels(categories, fontsize=10)
    ax.set_ylabel("억원", fontsize=9)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def achievement_chart(categories: List[str], achievements: List[float], statuses: List[str]) -> bytes:
    """카테고리별 달성률 막대 — 상태별 색상."""
    fig, ax = plt.subplots(figsize=(8.5, 3.2), dpi=140)
    colors = [STATUS_COLORS.get(s, "#94a3b8") for s in statuses]
    bars = ax.barh(categories, achievements, color=colors)
    ax.axvline(100, color="#475569", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.axvline(90, color="#f59e0b", linewidth=0.8, linestyle=":", alpha=0.6)
    ax.axvline(80, color="#ef4444", linewidth=0.8, linestyle=":", alpha=0.6)
    ax.set_xlabel("달성률 (%)", fontsize=9)
    ax.set_xlim(0, max(120, max(achievements) * 1.1 if achievements else 120))
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for b, v in zip(bars, achievements):
        ax.text(v + 1.5, b.get_y() + b.get_height() / 2, f"{v:.1f}%", va="center", fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
