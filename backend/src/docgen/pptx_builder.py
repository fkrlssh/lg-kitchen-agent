"""PPT 보고서 생성 — 임원 보고용.

슬라이드 구성:
1. 표지
2. Executive Summary (메트릭 + AI 요약)
3. 영역별 실적 집계
4. 카테고리별 AI 분석  ← NEW
5. 목표 달성 Sensing
6. 이상 징후 (AI 해석)
7. 이상 항목 근본원인 클러스터 (AI Agent)  ← NEW
8. 미회신 부서
9. AI 권장 액션  ← NEW
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Cm, Pt, Emu

from ..aggregation import by_category, missing_departments, total
from ..sensing import anomalies as get_anomalies, classify, summary_counts
from .charts import achievement_chart, category_bar_chart

KOREAN_FONT = "맑은 고딕"

# Color tokens
COLOR_PRIMARY = RGBColor(0x0F, 0x17, 0x2A)   # slate-900
COLOR_MUTED = RGBColor(0x64, 0x74, 0x8B)     # slate-500
COLOR_BG = RGBColor(0xF8, 0xFA, 0xFC)        # slate-50
COLOR_ACCENT = RGBColor(0xA5, 0x00, 0x34)    # LG-ish red
STATUS_RGB = {
    "정상": RGBColor(0x10, 0xB9, 0x81),
    "경고": RGBColor(0xF5, 0x9E, 0x0B),
    "위험": RGBColor(0xEF, 0x44, 0x44),
}


def _set_font(run, *, size: int, bold: bool = False, color: RGBColor | None = None):
    run.font.name = KOREAN_FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def _add_text(slide, *, left, top, width, height, text, size=14, bold=False, color=None, align=None):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    if align is not None:
        p.alignment = align
    run = p.add_run()
    run.text = text
    _set_font(run, size=size, bold=bold, color=color)
    return tb


def _add_rect(slide, *, left, top, width, height, fill: RGBColor, line: RGBColor | None = None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
    return shape


# ─────────────────────────────────────────────
# Slides
# ─────────────────────────────────────────────


def _slide_cover(prs: Presentation, period: str, generated_at: datetime):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Accent bar
    _add_rect(slide, left=Cm(0), top=Cm(0), width=prs.slide_width, height=Cm(0.4), fill=COLOR_ACCENT)

    # Title
    _add_text(
        slide, left=Cm(2), top=Cm(5.5), width=Cm(21.3), height=Cm(2),
        text=f"{period} 경영성과 보고", size=40, bold=True, color=COLOR_PRIMARY,
    )
    _add_text(
        slide, left=Cm(2), top=Cm(8.0), width=Cm(21.3), height=Cm(1),
        text="키친 사업부 · Early Sensing Agent", size=20, color=COLOR_MUTED,
    )

    # Footer
    _add_text(
        slide, left=Cm(2), top=Cm(17.5), width=Cm(21.3), height=Cm(0.8),
        text=f"자동 생성 · {generated_at.strftime('%Y-%m-%d %H:%M')} · LGE Internal Use Only",
        size=10, color=COLOR_MUTED,
    )


def _slide_exec_summary(prs: Presentation, *, period: str, totals: dict, counts: dict, narrative: str):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(prs, slide, "Executive Summary", period)

    # Metric cards: 4 boxes
    metric_top = Cm(3.2)
    metric_h = Cm(2.6)
    metric_w = Cm(5.6)
    metric_gap = Cm(0.3)
    metric_left_start = Cm(2)

    cards = [
        ("전체 달성률", f"{totals['달성률']:.1f}%", COLOR_PRIMARY),
        ("정상", str(counts["정상"]), STATUS_RGB["정상"]),
        ("경고", str(counts["경고"]), STATUS_RGB["경고"]),
        ("위험", str(counts["위험"]), STATUS_RGB["위험"]),
    ]
    for i, (label, value, color) in enumerate(cards):
        left = Cm(2 + i * (5.6 + 0.3))
        _add_rect(slide, left=left, top=metric_top, width=metric_w, height=metric_h, fill=COLOR_BG)
        _add_text(slide, left=left, top=metric_top + Cm(0.3), width=metric_w, height=Cm(0.8),
                  text=label, size=11, color=COLOR_MUTED)
        _add_text(slide, left=left, top=metric_top + Cm(1.0), width=metric_w, height=Cm(1.4),
                  text=value, size=28, bold=True, color=color)

    # Narrative
    _add_text(slide, left=Cm(2), top=Cm(6.5), width=Cm(21.3), height=Cm(1),
              text="AI 분석 요약", size=14, bold=True, color=COLOR_PRIMARY)
    _add_text(slide, left=Cm(2), top=Cm(7.4), width=Cm(21.3), height=Cm(5),
              text=narrative, size=13, color=COLOR_PRIMARY)


def _slide_aggregation(prs: Presentation, *, period: str, agg_df: pd.DataFrame):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(prs, slide, "① 영역별 실적 집계", period)

    # Chart
    png = category_bar_chart(
        categories=agg_df["카테고리"].tolist(),
        targets=agg_df["목표(억원)"].astype(float).tolist(),
        actuals=agg_df["실적(억원)"].astype(float).tolist(),
    )
    slide.shapes.add_picture(io.BytesIO(png), left=Cm(2), top=Cm(3.0), width=Cm(21.3))

    # Table below chart
    rows, cols = len(agg_df) + 1, 4
    tbl = slide.shapes.add_table(rows, cols, Cm(2), Cm(11.5), Cm(21.3), Cm(0.6 * rows)).table
    headers = ["카테고리", "목표(억원)", "실적(억원)", "달성률(%)"]
    for j, h in enumerate(headers):
        c = tbl.cell(0, j)
        c.text = h
        for r in c.text_frame.paragraphs[0].runs:
            _set_font(r, size=11, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        c.fill.solid()
        c.fill.fore_color.rgb = COLOR_PRIMARY
    for i, row in agg_df.iterrows():
        vals = [row["카테고리"], f"{row['목표(억원)']:.1f}", f"{row['실적(억원)']:.1f}", f"{row['달성률(%)']:.1f}"]
        for j, v in enumerate(vals):
            c = tbl.cell(i + 1, j)
            c.text = v
            for r in c.text_frame.paragraphs[0].runs:
                _set_font(r, size=10, color=COLOR_PRIMARY)


def _slide_sensing(prs: Presentation, *, period: str, agg_df: pd.DataFrame):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(prs, slide, "② 목표 달성 Sensing", period)

    # 카테고리별 달성률 + 상태 결정 (행 단위 분류 후 카테고리 상태 = 최악 항목 기준)
    statuses = []
    for cat in agg_df["카테고리"]:
        pct = float(agg_df.loc[agg_df["카테고리"] == cat, "달성률(%)"].iloc[0])
        statuses.append("위험" if pct < 80 else "경고" if pct < 90 else "정상")

    png = achievement_chart(
        categories=agg_df["카테고리"].tolist(),
        achievements=agg_df["달성률(%)"].astype(float).tolist(),
        statuses=statuses,
    )
    slide.shapes.add_picture(io.BytesIO(png), left=Cm(2), top=Cm(3.0), width=Cm(21.3))

    _add_text(slide, left=Cm(2), top=Cm(13.5), width=Cm(21.3), height=Cm(1),
              text="기준선: 100% 목표, 90% 경고선, 80% 위험선",
              size=10, color=COLOR_MUTED)


def _slide_anomalies(prs: Presentation, *, period: str, anomalies_df: pd.DataFrame,
                     narratives: Dict[int, str]):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(prs, slide, "③ 이상 징후 — Early Sensing", period)

    if anomalies_df.empty:
        _add_text(slide, left=Cm(2), top=Cm(8), width=Cm(21.3), height=Cm(2),
                  text="✓ 모든 항목이 정상 범위 내에 있습니다.",
                  size=20, color=STATUS_RGB["정상"])
        return

    # Table
    headers = ["상태", "카테고리", "부서", "세부항목", "달성률", "AI 해석"]
    rows = len(anomalies_df) + 1
    tbl = slide.shapes.add_table(rows, len(headers), Cm(2), Cm(3.0), Cm(21.3), Cm(min(13.5, 0.9 * rows))).table

    widths_cm = [1.6, 2.4, 3.0, 3.5, 1.8, 9.0]
    for j, w in enumerate(widths_cm):
        tbl.columns[j].width = Cm(w)

    for j, h in enumerate(headers):
        c = tbl.cell(0, j)
        c.text = h
        for r in c.text_frame.paragraphs[0].runs:
            _set_font(r, size=11, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        c.fill.solid()
        c.fill.fore_color.rgb = COLOR_PRIMARY

    for i, (_, row) in enumerate(anomalies_df.iterrows()):
        status = row["상태"]
        narrative = narratives.get(int(row.name) if isinstance(row.name, int) else i, "")
        cells = [status, row["카테고리"], row["부서"], row["세부항목"],
                 f"{row['달성률(%)']:.1f}%", narrative]
        for j, v in enumerate(cells):
            c = tbl.cell(i + 1, j)
            c.text = str(v)
            for r in c.text_frame.paragraphs[0].runs:
                _set_font(
                    r, size=9,
                    color=STATUS_RGB.get(status, COLOR_PRIMARY) if j == 0 else COLOR_PRIMARY,
                    bold=(j == 0),
                )


def _slide_missing(prs: Presentation, *, period: str, missing: Dict[str, List[str]]):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(prs, slide, "④ 미회신 부서 — Follow-up 대상", period)

    if not missing:
        _add_text(slide, left=Cm(2), top=Cm(8), width=Cm(21.3), height=Cm(2),
                  text="✓ 모든 부서가 회신을 완료했습니다.",
                  size=20, color=STATUS_RGB["정상"])
        return

    top = Cm(3.2)
    for cat, depts in missing.items():
        _add_text(slide, left=Cm(2), top=top, width=Cm(6), height=Cm(1),
                  text=cat, size=14, bold=True, color=COLOR_PRIMARY)
        _add_text(slide, left=Cm(8), top=top, width=Cm(15.3), height=Cm(1),
                  text=", ".join(depts), size=13, color=STATUS_RGB["위험"])
        top += Cm(1.0)

    _add_text(slide, left=Cm(2), top=top + Cm(0.5), width=Cm(21.3), height=Cm(1),
              text="→ Follow-up 메일이 자동 발송됩니다.", size=12, color=COLOR_MUTED)


def _slide_category_insights(prs: Presentation, *, period: str, insights: List[Dict[str, str]]):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(prs, slide, "② 카테고리별 AI 분석", period)

    if not insights:
        _add_text(slide, left=Cm(2), top=Cm(8), width=Cm(21.3), height=Cm(2),
                  text="AI 분석 결과 없음.", size=14, color=COLOR_MUTED)
        return

    top = Cm(3.0)
    row_h = Cm(1.6)
    for ins in insights:
        cat = ins.get("카테고리", "")
        analysis = ins.get("분석", "")
        _add_rect(slide, left=Cm(2), top=top, width=Cm(4.5), height=row_h, fill=COLOR_BG)
        _add_text(slide, left=Cm(2.2), top=top + Cm(0.4), width=Cm(4.3), height=Cm(0.8),
                  text=cat, size=12, bold=True, color=COLOR_PRIMARY)
        _add_text(slide, left=Cm(7.0), top=top + Cm(0.2), width=Cm(16.3), height=row_h,
                  text=analysis, size=11, color=COLOR_PRIMARY)
        top += row_h + Cm(0.15)


def _slide_clustering(prs: Presentation, *, period: str, clustering: Dict[str, Any],
                       anomalies_df: pd.DataFrame):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(prs, slide, "④ 이상 항목 근본원인 클러스터 (모니)", period)

    clusters = clustering.get("clusters", [])
    if not clusters or anomalies_df.empty:
        _add_text(slide, left=Cm(2), top=Cm(8), width=Cm(21.3), height=Cm(2),
                  text="이상 항목 없음 — 클러스터링 생략.", size=14, color=COLOR_MUTED)
        return

    # 좌측: 사고 과정 (관찰/추론)
    _add_rect(slide, left=Cm(2), top=Cm(3.0), width=Cm(8.5), height=Cm(13), fill=COLOR_BG)
    _add_text(slide, left=Cm(2.2), top=Cm(3.2), width=Cm(8.1), height=Cm(0.8),
              text="🧠 AI 사고 과정", size=12, bold=True, color=COLOR_PRIMARY)
    top = Cm(4.2)
    _add_text(slide, left=Cm(2.2), top=top, width=Cm(8.1), height=Cm(0.6),
              text="[관찰]", size=10, bold=True, color=COLOR_MUTED)
    top += Cm(0.6)
    for obs in clustering.get("observations", [])[:4]:
        _add_text(slide, left=Cm(2.4), top=top, width=Cm(7.9), height=Cm(0.7),
                  text=f"• {obs}", size=9, color=COLOR_PRIMARY)
        top += Cm(0.7)
    top += Cm(0.3)
    _add_text(slide, left=Cm(2.2), top=top, width=Cm(8.1), height=Cm(0.6),
              text="[추론]", size=10, bold=True, color=COLOR_MUTED)
    top += Cm(0.6)
    for i, step in enumerate(clustering.get("reasoning", [])[:4], 1):
        _add_text(slide, left=Cm(2.4), top=top, width=Cm(7.9), height=Cm(0.7),
                  text=f"{i}. {step}", size=9, color=COLOR_PRIMARY)
        top += Cm(0.7)

    # 우측: 클러스터 결과
    _add_text(slide, left=Cm(11.5), top=Cm(3.0), width=Cm(11.8), height=Cm(0.8),
              text="[결론] 클러스터", size=12, bold=True, color=COLOR_PRIMARY)
    top = Cm(3.9)
    for c in clusters[:4]:
        name = c.get("name", "")
        item_idxs = c.get("items", [])
        reason = c.get("reason", "")
        item_labels = []
        for idx in item_idxs:
            if 0 <= idx < len(anomalies_df):
                r = anomalies_df.iloc[idx]
                item_labels.append(f"{r['카테고리']}/{r['부서']} ({r['달성률(%)']:.0f}%)")
        _add_rect(slide, left=Cm(11.5), top=top, width=Cm(11.8), height=Cm(2.8), fill=COLOR_BG)
        _add_text(slide, left=Cm(11.7), top=top + Cm(0.1), width=Cm(11.4), height=Cm(0.6),
                  text=f"▸ {name}", size=11, bold=True, color=COLOR_ACCENT)
        _add_text(slide, left=Cm(11.7), top=top + Cm(0.8), width=Cm(11.4), height=Cm(0.8),
                  text=", ".join(item_labels) if item_labels else "(항목 없음)",
                  size=9, color=COLOR_PRIMARY)
        _add_text(slide, left=Cm(11.7), top=top + Cm(1.7), width=Cm(11.4), height=Cm(1.0),
                  text=reason, size=9, color=COLOR_MUTED)
        top += Cm(3.0)


def _slide_recommendations(prs: Presentation, *, period: str, recs: List[str]):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _slide_header(prs, slide, "⑤ AI 권장 액션 — 차주 우선순위", period)

    if not recs:
        _add_text(slide, left=Cm(2), top=Cm(8), width=Cm(21.3), height=Cm(2),
                  text="권장 액션 없음.", size=14, color=COLOR_MUTED)
        return

    top = Cm(3.2)
    for i, rec in enumerate(recs, 1):
        _add_rect(slide, left=Cm(2), top=top, width=Cm(1.5), height=Cm(1.5), fill=COLOR_ACCENT)
        _add_text(slide, left=Cm(2), top=top + Cm(0.3), width=Cm(1.5), height=Cm(0.9),
                  text=str(i), size=22, bold=True,
                  color=RGBColor(0xFF, 0xFF, 0xFF))
        _add_text(slide, left=Cm(4), top=top + Cm(0.3), width=Cm(19.3), height=Cm(1.2),
                  text=rec, size=13, color=COLOR_PRIMARY)
        top += Cm(1.8)


def _slide_header(prs: Presentation, slide, title: str, period: str):
    _add_rect(slide, left=Cm(0), top=Cm(0), width=prs.slide_width, height=Cm(0.25), fill=COLOR_ACCENT)
    _add_text(slide, left=Cm(2), top=Cm(0.7), width=Cm(21.3), height=Cm(1.2),
              text=title, size=22, bold=True, color=COLOR_PRIMARY)
    _add_text(slide, left=Cm(2), top=Cm(2.0), width=Cm(21.3), height=Cm(0.7),
              text=period, size=11, color=COLOR_MUTED)


# ─────────────────────────────────────────────
# Public
# ─────────────────────────────────────────────


def build_report(*, df: pd.DataFrame, period: str, narrative_summary: str,
                 anomaly_narratives: Dict[int, str],
                 category_insights: Optional[List[Dict[str, str]]] = None,
                 recommendations: Optional[List[str]] = None,
                 clustering: Optional[Dict[str, Any]] = None,
                 strategy: Optional[Dict[str, Any]] = None) -> bytes:
    """집계된 데이터로 PPT bytes 생성."""
    prs = Presentation()
    prs.slide_width = Cm(25.4)   # 16:9 wide
    prs.slide_height = Cm(19.05)

    totals = total(df)
    counts = summary_counts(df)
    agg_df = by_category(df)
    anomalies_df = get_anomalies(df).reset_index(drop=True)
    missing = missing_departments(df)
    now = datetime.now()

    _slide_cover(prs, period, now)
    _slide_exec_summary(prs, period=period, totals=totals, counts=counts, narrative=narrative_summary)
    _slide_aggregation(prs, period=period, agg_df=agg_df)
    if category_insights:
        _slide_category_insights(prs, period=period, insights=category_insights)
    _slide_sensing(prs, period=period, agg_df=agg_df)
    _slide_anomalies(prs, period=period, anomalies_df=anomalies_df, narratives=anomaly_narratives)
    if clustering:
        _slide_clustering(prs, period=period, clustering=clustering, anomalies_df=anomalies_df)
    _slide_missing(prs, period=period, missing=missing)
    if recommendations:
        _slide_recommendations(prs, period=period, recs=recommendations)

    out = io.BytesIO()
    prs.save(out)
    out.seek(0)
    return out.read()


def save_report(path: Path, **kwargs) -> Path:
    data = build_report(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
