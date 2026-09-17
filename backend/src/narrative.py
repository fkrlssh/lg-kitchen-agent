"""LLM 호출 전담 모듈 — 시스템에서 LLM 부르는 건 다 여기 거침.

────────────────────────────────────────────────────────────────────
역할 (3가지)
────────────────────────────────────────────────────────────────────

1) 분석 파이프라인이 부르는 LLM 함수 7개 (한국어 텍스트 생성)
   - executive_summary    임원 요약 (대시보드 첫 화면 + PPT 표지)
   - explain_anomaly      이상 항목 한 줄 AI 해석
   - category_analysis    카테고리별 1~2문장 분석
   - recommendations      차주 권장 액션 3~5개
   - cluster_anomalies    이상 항목 근본 원인 클러스터링 (LLM 판단)
   - followup_strategy    부서별 follow-up 전략 결정 (LLM 판단)
   - followup_email       부서별 메일 본문

   → run_pipeline (app/services/pipeline.py) 이 결정론으로 데이터 모은 뒤
     위 함수들 호출해서 한국어 분석 텍스트를 받아 대시보드/보고서에 채움.
   → 이 모듈 없으면 대시보드/보고서가 숫자만 남고 한국어 분석 한 줄도 안 나옴.

2) 챗봇 tool-use 루프 (chat_with_tool_use)
   - 홈/대시보드 우하단 챗봇 (frontend components/chat/*) 가 호출
   - 사용자 질문 → LLM 이 tool 선택 → tools.py 의 CHAT_TOOLS 실행 → 응답

3) 공통 utility
   - _llm_client       Ollama / LG endpoint 연결
   - _llm_complete     단순 LLM 호출 entry (system + sanitize + stop + retry)
   - _LANG_GUARD       한국어 강제 prompt (모든 system 메시지 끝에 합쳐짐)
   - _sanitize         한자 4자+ 블록 + <|im_start|> 등 특수 토큰 제거 정규식
   - _is_polluted      sanitize 가 처리할 게 있는지 감지

────────────────────────────────────────────────────────────────────
주변 모듈과의 관계 (헷갈리지 않게)
────────────────────────────────────────────────────────────────────

- narrative.py (이 파일)  = LLM 한테 "한국어 문장 써줘" 시키는 함수 모음
- tools.py                = 챗봇이 부를 수 있는 도구 정의 + 구현 (메일 가져오기, 집계 등)
- pipeline.py             = 결정론 분석 흐름 (parsing → aggregation → sensing → narrative)
- agent.py / cache_*      = 제거됨 (B+ 정리)

────────────────────────────────────────────────────────────────────
LLM endpoint
────────────────────────────────────────────────────────────────────

- 시연: 로컬 Ollama (qwen2.5 / EXAONE 등)
- 운영: LG 내부망 endpoint. .env 의 LLM_BASE_URL / LLM_MODEL 만 교체하면 됨 (코드 0 변경)
- LLM 도달 불가 → 각 함수 안의 template fallback 으로 자동 대체 (시스템 죽지 않음)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# .env 자동 로드 — narrative.py 가 FastAPI 외부에서도 import 되므로 (cache_prebuild 등)
try:
    from dotenv import load_dotenv
    _ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)
except Exception:
    pass

logger = logging.getLogger(__name__)

# OpenAI SDK 는 선택적 — 없거나 endpoint 도달 못해도 demo 동작 (cache + template fallback)
# AzureOpenAI 는 LG 사내 Azure OpenAI endpoint 용 (`LLM_PROVIDER=azure`).
try:
    from openai import OpenAI, AzureOpenAI
    _OPENAI_AVAILABLE = True
except Exception:  # pragma: no cover
    _OPENAI_AVAILABLE = False


# ─────────────────────────────────────────────
# Demo mode storage — pre-recorded LLM 출력 재생
# ─────────────────────────────────────────────
# DEMO_MODE=true: LLM 호출 skip. mock_narratives/{period_id}.json 에 record 된 게 있으면 그것 사용.
# RECORD_NARRATIVES=true: 라이브 LLM 결과를 mock_narratives 에 저장 (record 스크립트 전용).
# 두 플래그 모두 false 면 = 기존 동작 (라이브 LLM + template fallback).

def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


_MOCK_NARRATIVES_DIR = Path(__file__).resolve().parents[1] / "mock_narratives"
_RECORDED_CACHE: Dict[str, Dict[str, Any]] = {}  # period_id → dict (in-memory)


def _recorded_path(scenario_id: str) -> Path:
    return _MOCK_NARRATIVES_DIR / f"{scenario_id}.json"


def _load_recorded(scenario_id: str, key: str) -> Optional[Any]:
    if not scenario_id or not key:
        return None
    if scenario_id not in _RECORDED_CACHE:
        p = _recorded_path(scenario_id)
        if not p.exists():
            _RECORDED_CACHE[scenario_id] = {}
        else:
            try:
                _RECORDED_CACHE[scenario_id] = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("mock_narratives load failed (%s): %s", scenario_id, exc)
                _RECORDED_CACHE[scenario_id] = {}
    return _RECORDED_CACHE[scenario_id].get(key)


def _store_recorded(scenario_id: str, key: str, value: Any) -> None:
    if not scenario_id or not key:
        return
    p = _recorded_path(scenario_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[key] = value
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _RECORDED_CACHE[scenario_id] = data


# ─────────────────────────────────────────────
# LLM client — OpenAI-compatible
# ─────────────────────────────────────────────


def _llm_client():
    """LLM client factory — provider 별로 분기.

    LLM_PROVIDER:
      - `openai_compatible` (기본) — Ollama / vLLM / LG 자체 OpenAI 호환 게이트웨이 등
      - `azure`                   — LG 사내 Azure OpenAI (https://*.openai.azure.com)
                                     LLM_MODEL 은 Azure deployment 이름 (실제 모델 ID 아님).
                                     LLM_API_VERSION 필수 (예: 2024-08-01-preview).
    """
    if not _OPENAI_AVAILABLE:
        return None
    # DEMO_MODE: LLM 호출 자체 skip (recorded JSON 또는 template fallback 으로)
    if _flag("DEMO_MODE"):
        return None
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    if not base_url:
        return None
    provider = os.getenv("LLM_PROVIDER", "openai_compatible").strip().lower()
    timeout = float(os.getenv("LLM_TIMEOUT", "60.0"))
    try:
        if provider == "azure":
            return AzureOpenAI(
                azure_endpoint=base_url,
                api_key=os.getenv("LLM_API_KEY", ""),
                api_version=os.getenv("LLM_API_VERSION", "2024-08-01-preview"),
                timeout=timeout,
            )
        return OpenAI(
            base_url=base_url,
            api_key=os.getenv("LLM_API_KEY", "demo-key"),
            timeout=timeout,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("LLM client init failed: %s", exc)
        return None


# ─────────────────────────────────────────────
# Response sanitization — qwen 류 모델 한자/특수 토큰 누출 방어
# ─────────────────────────────────────────────

# qwen ChatML 경계 토큰류 — 디코딩 누출 시 본문에 박힘
_SPECIAL_TOKEN_RE = re.compile(r"<\|[^>]*?\|>")
# 연속 4자 이상 CJK Unified Ideographs — 한국어 한자어(보통 2~3자)는 통과, 중국어 문장은 잡힘
_CHINESE_BLOCK_RE = re.compile(r"[一-鿿]{4,}")
# 히라가나 / 가타카나 — 한국어 출력에는 안 나타남, 일본어 누출 명확 시그널
_JAPANESE_KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]+")
# Markdown bold 누출 — LLM 이 "** 단어 **" 식으로 본문에 박는 경우. 시연 화면에 그대로 노출되면 깨짐.
_MARKDOWN_BOLD_RE = re.compile(r"\*\*+")
# Markdown header / list bullet 누출
_MARKDOWN_HEADER_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_STOP_TOKENS = ["<|im_start|>", "<|im_end|>", "<|endoftext|>"]

# system 메시지 끝에 붙는 출력 가드 — 짧고 명령형이 효과 큼
_LANG_GUARD = (
    "출력 규칙: 반드시 한국어로만 응답. 중국어/일본어 단어·문장 절대 금지. "
    "시스템 토큰(<|im_start|>, <|im_end|> 등) 출력 금지. "
    "영문 약어(AI, KPI 등)와 숫자/단위(%, 억원)는 허용."
)


def _is_polluted(text: str) -> bool:
    if not text:
        return False
    if _SPECIAL_TOKEN_RE.search(text):
        return True
    if _CHINESE_BLOCK_RE.search(text):
        return True
    if _JAPANESE_KANA_RE.search(text):
        return True
    return False


def _sanitize(text: str) -> str:
    if not text:
        return text
    text = _SPECIAL_TOKEN_RE.sub("", text)
    text = _CHINESE_BLOCK_RE.sub("", text)
    text = _JAPANESE_KANA_RE.sub("", text)
    text = _MARKDOWN_BOLD_RE.sub("", text)
    text = _MARKDOWN_HEADER_RE.sub("", text)
    return text.strip()


def _llm_complete(
    prompt: str,
    *,
    system: Optional[str] = None,
    cache_key: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> Optional[str]:
    """단일 LLM 호출 entry. cache_key + scenario_id 주면 record/replay layer 가 끼어듦.

    - DEMO_MODE + recorded 있음 → 즉시 recorded text 반환 (LLM 호출 zero)
    - DEMO_MODE + recorded 없음 → None (caller 가 template fallback)
    - 평소 → LLM 호출. RECORD_NARRATIVES 켜져 있으면 결과 JSON 저장
    """
    # 1) recorded 가 있으면 무조건 우선 (DEMO_MODE 든 아니든, demo 일관성 보장)
    if cache_key and scenario_id:
        cached = _load_recorded(scenario_id, cache_key)
        if isinstance(cached, str) and cached.strip():
            return cached

    client = _llm_client()
    if client is None:
        return None
    model = os.getenv("LLM_MODEL", "qwen2.5:3b-instruct")
    base_sys = system or "당신은 '챗봇' — 키친솔루션 한계돌파 플랫폼의 경영성과 모니터링 비서입니다. 한국어로 간결하고 구조적으로, 친근하게 답변합니다."
    sys_msg = f"{base_sys}\n\n{_LANG_GUARD}"
    base_temp = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=base_temp + (0.1 if attempt > 0 else 0),
                stop=_STOP_TOKENS,
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.warning("LLM call failed, falling back: %s", exc)
            return None

        if _is_polluted(raw):
            logger.warning(
                "LLM response polluted (attempt %d/2): special_token=%s chinese_block=%s",
                attempt + 1,
                bool(_SPECIAL_TOKEN_RE.search(raw)),
                bool(_CHINESE_BLOCK_RE.search(raw)),
            )
            if attempt == 0:
                continue
        # markdown bold / header 는 polluted 가 아니어도 항상 제거 — 화면 노출 방어
        cleaned = _sanitize(raw)
        # record 모드면 깨끗한 결과만 저장
        if cleaned and cache_key and scenario_id and _flag("RECORD_NARRATIVES"):
            _store_recorded(scenario_id, cache_key, cleaned)
        return cleaned
    return None


# ─────────────────────────────────────────────
# CoT prompt helper — 관찰/추론/결론 3단 구조
# ─────────────────────────────────────────────

_COT_INSTRUCTION = """반드시 다음 형식을 정확히 지켜 답변하세요. 섹션 머리표시를 그대로 사용:

[관찰]
- 데이터에서 본 사실 1
- 사실 2
- 사실 3

[추론]
1. 추론 단계 1
2. 추론 단계 2
3. 추론 단계 3

[결론]
{result_format}

작성 규칙:
- 각 항목은 한 줄 완결 — 빈 bullet (`- *`, `**`) 절대 금지
- markdown 강조 (`**단어**`) 사용 금지 — 평문 한국어
- 헤더 (`##`) 사용 금지
"""


def _parse_cot(text: str) -> Dict[str, Any]:
    """LLM 출력 → {observations, reasoning, conclusion_raw}"""
    obs = _extract_section(text, "관찰")
    reason = _extract_section(text, "추론")
    concl = _extract_section(text, "결론")
    return {
        "observations": _bullets(obs),
        "reasoning": _bullets(reason),
        "conclusion_raw": concl.strip(),
    }


def _extract_section(text: str, label: str) -> str:
    pattern = rf"\[{label}\](.*?)(?=\[(관찰|추론|결론)\]|\Z)"
    m = re.search(pattern, text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _bullets(text: str) -> List[str]:
    """LLM 출력의 [관찰]/[추론] 섹션을 한 줄씩 추출.

    EXAONE 류가 종종 `- *`, `* *`, `**` 같은 빈 bullet 을 list separator 로 끼워 넣음.
    leading 마커를 반복적으로 벗기고, 의미 없는 punctuation-only / 너무 짧은 줄은 버림.
    """
    lines: List[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        # leading bullet / 번호 / markdown bold 마커를 반복적으로 제거
        # (`- *`, `* *`, `1. *`, `**1.` 같은 중첩 케이스)
        prev = None
        while s != prev:
            prev = s
            s = re.sub(r"^[\-\*•·▪►\s]+", "", s)
            s = re.sub(r"^\d+[\.\)]\s*", "", s)
            s = s.strip()
        # 본문에 남은 markdown bold 잔여 (sanitize 가 먼저 잡아도 보완)
        s = re.sub(r"\*+", "", s).strip()
        # 의미 있는 컨텐츠 — 최소 한글/영문/숫자 글자 2자 이상
        if len(s) < 2:
            continue
        if not re.search(r"[\w가-힣]", s):
            continue
        lines.append(s)
    return lines


# ─────────────────────────────────────────────
# Public — 단순 텍스트 생성 (cache 적용)
# ─────────────────────────────────────────────


def explain_anomaly(row: pd.Series, *, scenario_id: str = "default") -> str:
    """이상 항목 1줄 자연어 해석."""
    cat = row.get("카테고리", "")
    dept = row.get("부서", "")
    detail = row.get("세부항목", "")
    target = float(row.get("목표(억원)", 0) or 0)
    actual = float(row.get("실적(억원)", 0) or 0)
    pct = float(row.get("달성률(%)", 0) or 0)
    status = row.get("상태", "")


    prompt = (
        f"다음 경영성과 항목이 {status} 수준입니다. "
        f"카테고리={cat}, 부서={dept}, 세부항목={detail}, "
        f"목표={target:.1f}억원, 실적={actual:.1f}억원, 달성률={pct:.1f}%. "
        "원인 가능성 1~2개와 즉시 점검할 액션을 한 문장으로 작성하세요. (60자 이내)"
    )
    text = _llm_complete(
        prompt,
        cache_key=f"explain_anomaly::{cat}::{dept}::{detail}",
        scenario_id=scenario_id,
    )
    if not text:
        gap = target - actual
        if status == "위험":
            text = (
                f"{dept} {detail} 실적이 목표 대비 {gap:.0f}억원 부족({pct:.0f}%). "
                "단가 상승 또는 운영 차질 가능성, 담당 즉시 원인 점검 필요."
            )
        else:
            text = (
                f"{dept} {detail} 달성률 {pct:.0f}%, 추세 모니터링 권고. "
                "차주 회의에서 진척 확인."
            )

    return text


def executive_summary(
    *,
    totals: dict,
    counts: dict,
    anomalies_df: pd.DataFrame,
    missing: dict,
    period: str,
    scenario_id: str = "default",
) -> str:
    """임원 보고용 3~4문장 요약."""
    anomaly_briefs: List[str] = []
    for _, r in anomalies_df.head(3).iterrows():
        anomaly_briefs.append(f"{r['카테고리']} {r['부서']} ({r['달성률(%)']:.0f}%)")
    anomaly_text = ", ".join(anomaly_briefs) if anomaly_briefs else "없음"
    missing_count = sum(len(v) for v in missing.values())


    prompt = (
        f"{period} 경영성과 자동 집계 결과: "
        f"전체 달성률 {totals['달성률']:.1f}%, 항목 {totals['항목수']}개 "
        f"(정상 {counts['정상']}/경고 {counts['경고']}/위험 {counts['위험']}). "
        f"미회신 부서 {missing_count}개. 주요 이상 항목: {anomaly_text}. "
        "임원 보고용 요약을 3~4문장으로 작성하세요. 한국어, 객관적 톤, 숫자 강조."
    )
    text = _llm_complete(
        prompt, cache_key="executive_summary", scenario_id=scenario_id,
    )
    if not text:
        parts = [
            f"{period} 경영성과 자동 집계 결과, 전체 달성률은 "
            f"{totals['달성률']:.1f}% ({totals['실적']:.0f}/{totals['목표']:.0f}억원) 입니다."
        ]
        if counts["위험"] + counts["경고"] > 0:
            parts.append(
                f"총 {totals['항목수']}개 항목 중 위험 {counts['위험']}건, "
                f"경고 {counts['경고']}건이 감지되었습니다."
            )
            if anomaly_briefs:
                parts.append(f"우선 점검 대상: {anomaly_text}.")
        else:
            parts.append("모든 항목이 정상 범위 내에 있습니다.")
        if missing_count:
            parts.append(f"미회신 부서 {missing_count}개에 대해 follow-up 메일 자동 발송 예정입니다.")
        text = " ".join(parts)

    return text


def category_analysis(
    *, category: str, target: float, actual: float, pct: float,
    anomaly_count: int, scenario_id: str = "default",
) -> str:
    """카테고리별 1~2문장 분석 (보고서 슬라이드용)."""

    prompt = (
        f"카테고리={category}, 목표={target:.1f}억원, 실적={actual:.1f}억원, "
        f"달성률={pct:.1f}%, 이상항목수={anomaly_count}개. "
        "이 카테고리의 현황을 1~2문장으로 분석하시오. 한국어, 임원 보고체."
    )
    text = _llm_complete(
        prompt,
        cache_key=f"category_analysis::{category}",
        scenario_id=scenario_id,
    )
    if not text:
        status = "양호" if pct >= 95 else "주의" if pct >= 90 else "미달"
        if anomaly_count > 0:
            text = (
                f"{category} 전체 달성률 {pct:.1f}% ({status}). "
                f"세부 {anomaly_count}건 이상 감지, 부서별 원인 점검 필요."
            )
        else:
            text = f"{category} 전체 달성률 {pct:.1f}% ({status}). 세부 이상 없음."

    return text


def recommendations(
    *, totals: dict, counts: dict, anomalies_df: pd.DataFrame,
    missing: dict, scenario_id: str = "default",
) -> List[str]:
    """전체 데이터 기반 우선순위 액션 3~5건 (보고서 슬라이드용)."""
    missing_count = sum(len(v) for v in missing.values())
    ano_brief = ", ".join(
        f"{r['카테고리']}/{r['부서']}/{r['세부항목']} {r['달성률(%)']:.0f}%"
        for _, r in anomalies_df.head(5).iterrows()
    ) or "없음"


    prompt = (
        f"전체 달성률 {totals['달성률']:.1f}%, 위험 {counts['위험']}/경고 {counts['경고']}건, "
        f"미회신 부서 {missing_count}개. 이상 항목: {ano_brief}. "
        "차주 우선 액션 3~5건을 번호 매겨 한 줄씩 작성하시오. "
        "각 항목: '담당부서/액션' 형식. 한국어."
    )
    text = _llm_complete(
        prompt, cache_key="recommendations", scenario_id=scenario_id,
    )
    items: List[str] = []
    if text:
        items = _bullets(text)[:5]

    if not items:
        if counts["위험"] > 0:
            for _, r in anomalies_df[anomalies_df["상태"] == "위험"].head(3).iterrows():
                items.append(
                    f"{r['부서']} / {r['카테고리']} {r['세부항목']} 즉시 원인 점검 ({r['달성률(%)']:.0f}%)"
                )
        if missing_count > 0:
            for cat, depts in missing.items():
                items.append(f"{', '.join(depts)} / {cat} 회신 follow-up 메일 발송")
        if not items:
            items.append("전체 정상 — 추가 액션 없음, 다음 격주 모니터링 유지")

    return items


# ─────────────────────────────────────────────
# Agent 판단 #1: 이상 항목 클러스터링 (옵션 C)
# ─────────────────────────────────────────────


def cluster_anomalies(
    anomalies_df: pd.DataFrame, *, scenario_id: str = "default",
) -> Dict[str, Any]:
    """이상 항목 N건을 LLM 이 근본원인별로 그룹핑.

    Returns:
        {
            "observations": [str, ...],
            "reasoning": [str, ...],
            "clusters": [
                {"name": "원자재 비용 상승", "items": [0, 2], "reason": "..."},
                ...
            ],
        }
    """
    if anomalies_df.empty:
        return {"observations": [], "reasoning": [], "clusters": []}

    items_brief: List[str] = []
    for i, r in anomalies_df.iterrows():
        items_brief.append(
            f"#{i+1}. {r['카테고리']} / {r['부서']} / {r['세부항목']} "
            f"(달성률 {r['달성률(%)']:.0f}%, {r['상태']})"
        )
    items_text = "\n".join(items_brief)


    result_format = (
        "다음 항목을 근본원인이 비슷한 것끼리 2~3개 클러스터로 묶으세요.\n"
        "각 클러스터는 정확히 다음 형식:\n"
        "클러스터 1: <간결한 이름>\n"
        "- 포함 항목: #번호, #번호\n"
        "- 이유: <한 문장>\n"
        "\n"
        "클러스터 2: ...\n"
    )
    prompt = (
        f"다음은 이번 격주 집계에서 감지된 이상 항목입니다:\n{items_text}\n\n"
        + _COT_INSTRUCTION.format(result_format=result_format)
    )

    text = _llm_complete(
        prompt, cache_key="cluster_anomalies", scenario_id=scenario_id,
    )
    clusters: List[Dict[str, Any]] = []
    observations: List[str] = []
    reasoning: List[str] = []

    if text:
        parsed = _parse_cot(text)
        observations = parsed["observations"]
        reasoning = parsed["reasoning"]
        clusters = _parse_clusters(parsed["conclusion_raw"], len(anomalies_df))

    if not clusters:
        # Template fallback: 상태 기반 + 카테고리 부가 그룹핑
        danger_idxs = [int(i) for i, r in anomalies_df.iterrows() if r["상태"] == "위험"]
        warn_idxs = [int(i) for i, r in anomalies_df.iterrows() if r["상태"] == "경고"]
        if danger_idxs:
            cats = sorted({anomalies_df.iloc[i]["카테고리"] for i in danger_idxs})
            clusters.append({
                "name": "고위험 미달 — 즉시 점검 대상",
                "items": danger_idxs,
                "reason": (
                    f"달성률 80% 미만 항목 {len(danger_idxs)}건 ({', '.join(cats)}). "
                    "단가 급등·공정 차질·외주 품질 등 단기 충격 요인일 가능성, "
                    "담당 부서별 root cause 확인 필요."
                ),
            })
        if warn_idxs:
            cats = sorted({anomalies_df.iloc[i]["카테고리"] for i in warn_idxs})
            clusters.append({
                "name": "추세 모니터링 — 경고 라인",
                "items": warn_idxs,
                "reason": (
                    f"달성률 80~90% 항목 {len(warn_idxs)}건 ({', '.join(cats)}). "
                    "즉각 위험은 아니나 추세 악화 가능성, 차주 추가 데이터로 재확인."
                ),
            })
        if not observations:
            observations = [
                f"전체 이상 항목 {len(anomalies_df)}건 감지 (위험 {len(danger_idxs)} · 경고 {len(warn_idxs)})",
                f"위험 항목 카테고리: {', '.join(sorted({anomalies_df.iloc[i]['카테고리'] for i in danger_idxs})) or '없음'}",
                f"경고 항목 카테고리: {', '.join(sorted({anomalies_df.iloc[i]['카테고리'] for i in warn_idxs})) or '없음'}",
            ]
        if not reasoning:
            reasoning = [
                "이상 항목을 우선 영향도 기준 (위험 vs 경고) 으로 1차 분류",
                "위험 항목은 단기 외부 충격 (단가/공정/외주) 가능성, 즉각 점검 대상",
                "경고 항목은 추세 변화 신호, 차주 데이터로 패턴 재확인 권고",
                "두 그룹 모두 카테고리 분포를 명시하여 담당 부서 일괄 알림 가능",
            ]

    result = {"observations": observations, "reasoning": reasoning, "clusters": clusters}
    return result


def _parse_clusters(text: str, n_items: int) -> List[Dict[str, Any]]:
    clusters: List[Dict[str, Any]] = []
    blocks = re.split(r"클러스터\s*\d+\s*:", text)
    for block in blocks[1:]:
        block = block.strip()
        if not block:
            continue
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        name = re.sub(r"^[#\-\*\s]+", "", lines[0]).strip()
        name = re.sub(r"\*+", "", name).strip()  # 본문/꼬리에 박힌 markdown bold 마저 제거
        items: List[int] = []
        reason = ""
        for ln in lines[1:]:
            if "포함 항목" in ln or "포함항목" in ln:
                nums = re.findall(r"#?(\d+)", ln)
                items = [int(n) - 1 for n in nums if 1 <= int(n) <= n_items]
            elif "이유" in ln:
                reason = re.sub(r"^.*?이유\s*[:：]\s*", "", ln).strip()
                reason = re.sub(r"\*+", "", reason).strip()
        if name and items:
            clusters.append({"name": name, "items": items, "reason": reason})
    return clusters


# ─────────────────────────────────────────────
# Agent 판단 #2: Follow-up 전략 결정 (옵션 B)
# ─────────────────────────────────────────────

STRATEGY_LABELS = {
    "이메일": "표준 이메일 follow-up",
    "재요청": "재요청 (마감 임박)",
    "에스컬레이션": "임원 에스컬레이션",
}


def followup_strategy(
    *, missing: Dict[str, List[str]], anomalies_df: pd.DataFrame,
    scenario_id: str = "default",
) -> Dict[str, Any]:
    """미회신 부서별로 LLM 이 follow-up 전략 결정.

    Returns:
        {
            "observations": [str, ...],
            "reasoning": [str, ...],
            "strategies": [
                {
                    "department": "...",
                    "category": "...",
                    "strategy": "이메일" | "재요청" | "에스컬레이션",
                    "priority": "low" | "medium" | "high",
                    "reason": "...",
                },
                ...
            ],
        }
    """
    targets: List[Tuple[str, str]] = [
        (cat, dept) for cat, depts in missing.items() for dept in depts
    ]
    if not targets:
        return {"observations": [], "reasoning": [], "strategies": []}

    # Context: 미회신 부서가 이상 항목과 겹치는지
    affected_cats = set(anomalies_df["카테고리"].unique()) if not anomalies_df.empty else set()

    target_text = "\n".join(
        f"- {dept} ({cat}){' [이상감지 카테고리]' if cat in affected_cats else ''}"
        for cat, dept in targets
    )


    result_format = (
        "다음 부서들에 대해 정확히 다음 형식으로 답하시오:\n"
        "부서: <부서명>\n"
        "- 전략: <이메일 | 재요청 | 에스컬레이션 중 하나>\n"
        "- 우선순위: <low | medium | high 중 하나>\n"
        "- 이유: <한 문장>\n"
        "\n"
        "(부서마다 위 형식 반복)"
    )
    prompt = (
        f"다음은 이번 격주 실적 회신을 보내지 않은 부서 목록입니다.\n"
        f"같은 카테고리에서 이상 항목이 감지된 경우 [이상감지 카테고리] 로 표시:\n\n"
        f"{target_text}\n\n"
        "이상감지 카테고리에 속한 미회신 부서는 더 적극적 전략(재요청/에스컬레이션)을 권합니다.\n\n"
        + _COT_INSTRUCTION.format(result_format=result_format)
    )

    text = _llm_complete(
        prompt, cache_key="followup_strategy", scenario_id=scenario_id,
    )
    strategies: List[Dict[str, Any]] = []
    observations: List[str] = []
    reasoning: List[str] = []

    if text:
        parsed = _parse_cot(text)
        observations = parsed["observations"]
        reasoning = parsed["reasoning"]
        strategies = _parse_strategies(parsed["conclusion_raw"], targets)

    if not strategies:
        for cat, dept in targets:
            if cat in affected_cats:
                strategies.append({
                    "department": dept,
                    "category": cat,
                    "strategy": "에스컬레이션",
                    "priority": "high",
                    "reason": f"{cat} 영역에 이상 항목 존재 — 미회신 시 임원 보고 누락 위험",
                })
            else:
                strategies.append({
                    "department": dept,
                    "category": cat,
                    "strategy": "이메일",
                    "priority": "medium",
                    "reason": "정상 follow-up 절차 — 표준 이메일 발송",
                })
        if not observations:
            observations = [
                f"미회신 부서 {len(targets)}건",
                f"이상감지 카테고리 포함: {sum(1 for c, _ in targets if c in affected_cats)}건",
            ]
        if not reasoning:
            reasoning = [
                "이상 항목이 있는 카테고리는 보고 누락 영향이 크다",
                "해당 부서는 임원 에스컬레이션으로 우선순위 높임",
                "나머지는 표준 이메일 follow-up 으로 충분",
            ]

    result = {"observations": observations, "reasoning": reasoning, "strategies": strategies}
    return result


def _parse_strategies(text: str, targets: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    dept_to_cat = {dept: cat for cat, dept in targets}
    strategies: List[Dict[str, Any]] = []
    blocks = re.split(r"부서\s*[:：]", text)
    for block in blocks[1:]:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        dept_raw = re.sub(r"^[#\-\*\s]+", "", lines[0]).strip()
        dept_raw = re.sub(r"\*+", "", dept_raw).strip()
        # 부서명 fuzzy match
        dept = next((d for d in dept_to_cat if d in dept_raw or dept_raw in d), None)
        if not dept:
            continue
        strategy = "이메일"
        priority = "medium"
        reason = ""
        for ln in lines[1:]:
            if "전략" in ln:
                if "에스컬레이션" in ln or "에스컬" in ln:
                    strategy = "에스컬레이션"
                elif "재요청" in ln:
                    strategy = "재요청"
                elif "이메일" in ln:
                    strategy = "이메일"
            elif "우선순위" in ln:
                low = ln.lower()
                if "high" in low or "높" in ln:
                    priority = "high"
                elif "low" in low or "낮" in ln:
                    priority = "low"
                else:
                    priority = "medium"
            elif "이유" in ln:
                reason = re.sub(r"^.*?이유\s*[:：]\s*", "", ln).strip()
                reason = re.sub(r"\*+", "", reason).strip()
        strategies.append({
            "department": dept,
            "category": dept_to_cat[dept],
            "strategy": strategy,
            "priority": priority,
            "reason": reason,
        })
    return strategies


# ─────────────────────────────────────────────
# Follow-up email 본문 생성
# ─────────────────────────────────────────────


def followup_email(
    *, department: str, category: str, strategy: str, period: str, deadline: str,
    scenario_id: str = "default",
) -> Dict[str, str]:
    """부서별 follow-up 메일 본문 LLM 생성."""

    tone_hint = {
        "이메일": "정중하고 정형적인 톤",
        "재요청": "긴급함을 강조하되 정중한 톤",
        "에스컬레이션": "임원 보고 영향을 명시하는 단호한 톤",
    }.get(strategy, "정중한 톤")

    subject_hint = {
        "이메일": f"[격주 실적 회신 요청] {category} — {period}",
        "재요청": f"[재요청] {category} 실적 회신 부탁드립니다 — {period}",
        "에스컬레이션": f"[긴급/임원보고] {category} 실적 회신 누락 — {period}",
    }.get(strategy, f"[격주 실적] {category} — {period}")

    prompt = (
        f"부서: {department}, 카테고리: {category}, 기간: {period}, 마감일: {deadline}, "
        f"전략: {strategy} ({tone_hint}). "
        f"제목: '{subject_hint}'. "
        "이 부서에 보낼 follow-up 메일 본문을 한국어로 작성하시오. "
        "구성: 인사 → 회신 요청 이유 → 마감일 명시 → 정중한 마무리. "
        "100~150자 분량. 본문만 작성 (제목/서명 제외)."
    )

    body = _llm_complete(
        prompt,
        cache_key=f"followup_email::{department}::{category}::{strategy}",
        scenario_id=scenario_id,
    )
    if not body:
        if strategy == "에스컬레이션":
            body = (
                f"안녕하세요, {department} 담당자님.\n\n"
                f"{period} 격주 실적 회신 마감({deadline})이 경과하였습니다. "
                f"{category} 영역에서 이상 항목이 감지되어 본 부서의 회신이 임원 보고에 필수적입니다. "
                "본일 18시까지 회신 부탁드리며, 미회신 시 사업부장께 별도 보고드릴 예정입니다.\n\n"
                "감사합니다."
            )
        elif strategy == "재요청":
            body = (
                f"안녕하세요, {department} 담당자님.\n\n"
                f"{period} {category} 격주 실적 회신을 재요청드립니다. "
                f"마감({deadline})이 경과하였으니 금일 중 회신 부탁드립니다. "
                "차주 임원 보고 자료에 반영되어야 합니다.\n\n"
                "감사합니다."
            )
        else:
            body = (
                f"안녕하세요, {department} 담당자님.\n\n"
                f"{period} {category} 격주 실적 회신을 부탁드립니다. "
                f"마감일은 {deadline} 이며, 회신 양식은 기존과 동일합니다. "
                "확인 후 회신 부탁드립니다.\n\n"
                "감사합니다."
            )

    result = {"subject": subject_hint, "body": body, "strategy": strategy}
    return result


# ─────────────────────────────────────────────
# AI 어시스턴트 챗 — 결과 context 기반 Q&A
# ─────────────────────────────────────────────

# 프리셋 = LLM 없이도 항상 정확한 답을 보장하는 결정론적 핸들러.
# 자유 입력은 LLM 호출 (cache + template fallback).

PRESETS = {
    "status": "지금 몇 주차까지 데이터가 있어?",
    "missing": "미제출 항목 알려줘",
    "achievement": "전체 실적 달성률은?",
    "risk": "제일 미달인 항목은?",
}


# ── 도구 결과 → 한국어 답변 포맷 (presets + 결정론 fallback 공용) ──

def _n(v) -> str:
    return "—" if v is None else f"{round(float(v)):,}"


def _pct(v) -> str:
    return "—" if v is None else f"{v}%"


def _fmt_status(r: Dict[str, Any]) -> str:
    if r.get("error"):
        return r["error"]
    miss = r.get("미제출", [])
    lines = [f"현재 {r.get('현재_주차') or '—'}까지 데이터가 있습니다."]
    if miss:
        lines.append(f"미제출 {len(miss)}건: " + ", ".join(miss))
    else:
        lines.append("전 항목 제출 완료입니다.")
    late = [it for it in r.get("항목별", []) if not it.get("제출됨")]
    if late:
        lines.append("뒤처진 항목: " + ", ".join(f"{it['항목']}({it['최신']})" for it in late))
    return "\n".join(lines)


def _gap(d: Optional[dict]) -> str:
    """차이(실적-목표) → '목표까지 N 부족' / '목표 N 초과'."""
    v = (d or {}).get("차이")
    if v is None:
        return ""
    return f"목표까지 {_n(-v)} 부족" if v < 0 else f"목표 {_n(v)} 초과 달성"


def _fmt_achievement(r: Dict[str, Any]) -> str:
    if r.get("error"):
        return r["error"]
    if "항목" in r:  # 특정 항목
        c = r.get("누적") or {}
        t = c.get("목표")
        # 절감형(목표 음수) — 달성률=실적/목표 공식이 깨짐(음수%) → 모순 표현 대신 보류 안내.
        if t is not None and t < 0:
            return (f"{r['항목']} 누적 — 목표 {_n(t)} / 실적 {_n(c.get('실적'))} "
                    f"(절감형 항목: 목표가 음수라 달성률 비율은 보류)")
        return (f"{r['항목']} 누적 — 목표 {_n(t)} / 실적 {_n(c.get('실적'))} · "
                f"달성률 {_pct(c.get('달성률'))} ({_gap(c)})")
    ex = r.get("H제외_누적") or {}
    al = r.get("전체_누적") or {}
    return (f"{r.get('기준_월')}월 기준 누적 — 전체 달성률 {_pct(al.get('달성률'))} "
            f"(목표 {_n(al.get('목표'))} / 실적 {_n(al.get('실적'))}), "
            f"H제외 {_pct(ex.get('달성률'))}. {_gap(ex)}.")


def _fmt_risks(r: Dict[str, Any]) -> str:
    if r.get("error"):
        return r["error"]
    short = r.get("미달영향_top3", [])
    low = r.get("달성률최저_top3", [])
    lines: List[str] = []
    if short:
        lines.append("목표 미달 영향이 큰 항목:")
        for s in short:
            lines.append(f"- {s.get('항목')}: 부족 {_n(s.get('부족'))} (달성률 {_pct(s.get('달성률'))})")
    if low:
        lines.append("달성률 최저:")
        for s in low:
            lines.append(f"- {s.get('항목')}: {_pct(s.get('달성률'))}")
    return "\n".join(lines) or "현재 위험·미달 항목이 없습니다."


def _preset_status() -> Dict[str, Any]:
    from .tools import get_status
    return {"answer": _fmt_status(get_status()), "citations": []}


def _preset_missing() -> Dict[str, Any]:
    from .tools import get_status
    r = get_status()
    if r.get("error"):
        return {"answer": r["error"], "citations": []}
    miss = r.get("미제출", [])
    ans = ("미제출 " + str(len(miss)) + "건: " + ", ".join(miss)) if miss else "전 항목 제출 완료입니다."
    return {"answer": ans, "citations": []}


def _preset_achievement() -> Dict[str, Any]:
    from .tools import get_achievement
    return {"answer": _fmt_achievement(get_achievement()), "citations": []}


def _preset_risk() -> Dict[str, Any]:
    from .tools import get_risks
    return {"answer": _fmt_risks(get_risks()), "citations": []}


_PRESET_HANDLERS = {
    "status": _preset_status,
    "missing": _preset_missing,
    "achievement": _preset_achievement,
    "risk": _preset_risk,
}


def _build_system_context() -> str:
    """LLM 시스템 prompt 에 주입할 동적 정보 — 오늘 날짜 + 현재 데이터 상태(주차/미제출).

    LLM 은 시간/현재 상태를 모르므로 매 호출마다 주입. tool-use 못 하는 모델에서도
    "지금 몇 주차?" 같은 질문에 근거를 갖도록 최신 스냅샷 요약을 합친다.
    """
    from datetime import date

    lines = [f"오늘 날짜: {date.today().isoformat()}"]
    try:
        from . import store
        st = store.latest_status()
        miss = st.get("missing", [])
        lines.append(f"현재 데이터: {st.get('current_label') or '없음'}까지 적재")
        lines.append(f"미제출 {len(miss)}건" + (": " + ", ".join(miss) if miss else " (전 항목 제출)"))
    except Exception:
        pass
    return "\n".join(lines)


_TOOL_LIST_MESSAGE = """챗봇이 사용 가능한 도구입니다.

📊 정보 조회 — 현재 적재된 실데이터를 바로 조회
• get_status — 제출 현황 (몇 주차까지·미제출 항목)
• get_achievement — 실적/달성률 (목표 대비·남은 금액, 항목별 가능)
• get_risks — 위험/미달 항목 진단 (미달 영향·달성률 최저 top3)

🎮 UI 액션
• navigate — 페이지 이동 (실적관리/보고서운영/문서관리/제출관리/홈)
• remind — 미제출 항목 독촉 안내

🧪 자연어 예시
• "지금 몇 주차까지 있어?" → get_status
• "미제출 어디야?" → get_status
• "실적 얼마나 남았어?" / "Area_A 달성률?" → get_achievement
• "제일 미달인 항목은?" → get_risks
• "보고서 보여줘" → navigate

📝 도구가 더 필요하면? — "도구 메모: ~~~" 형식으로 입력하면 wishlist 에 기록됩니다."""


def _detect_command(question: str, has_context: bool = False) -> Optional[Dict[str, Any]]:
    """자연어 명령/질문 → 즉답 매핑 (실데이터 도구 직접 호출). 매칭 안 되면 None.

    has_context 는 레거시 인자(미사용). Returns: {"answer", "action", "bypass_llm"?} or None
    """
    q = question.strip()
    lower = q.lower()

    # ── 도구 목록 표시 ─────────────────────
    if any(k in q for k in ["도구 목록", "도구목록", "어떤 도구", "도구 보여", "툴 목록", "/tools"]) \
            or lower in {"tools", "/tools"}:
        return {
            "answer": _TOOL_LIST_MESSAGE,
            "action": {"type": "open_tool_catalog", "params": {}},
            "bypass_llm": True,
        }

    # ── wishlist 노트 추가 ─────────────────
    # "도구 메모: 격주 비교 보고서" / "도구 추가: ~~~" / "/note ~~~" 형식
    note_match = re.match(
        r"^\s*(?:도구\s*(?:메모|추가|요청|wishlist)|/note)\s*[:：]?\s*(.+)$",
        q,
        re.IGNORECASE,
    )
    if note_match:
        # leading ":" / 공백 / 콜론은 빈 메모로 취급 (정규식의 [:：]? 만으론 못 잡는 케이스)
        note = re.sub(r"^[:：\s]+", "", note_match.group(1)).strip()
        if not note:
            return {
                "answer": "메모 내용이 비어 있습니다. 예: \"도구 메모: 격주 비교 보고서 자동 생성\"",
                "action": {"type": "none", "params": {}},
            }
        # 파일 append — backend/tool_wishlist.md
        try:
            from datetime import datetime
            wishlist_path = Path(__file__).resolve().parents[1] / "tool_wishlist.md"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"- [{ts}] {note}\n"
            if not wishlist_path.exists():
                wishlist_path.write_text(
                    "# 모니 도구 wishlist\n\n"
                    "챗에서 \"도구 메모: ~~~\" 입력으로 추가됨. "
                    "Claude Code 와 작업할 때 이 파일 참고.\n\n",
                    encoding="utf-8",
                )
            with wishlist_path.open("a", encoding="utf-8") as f:
                f.write(entry)
            return {
                "answer": (
                    f"📝 wishlist 에 추가됨:\n"
                    f"• {note}\n\n"
                    f"저장 위치: `backend/tool_wishlist.md`\n"
                    f"다음 개발 세션에서 이 파일을 보고 도구 만들기 가능."
                ),
                "action": {"type": "none", "params": {}},
                "bypass_llm": True,
            }
        except Exception as exc:
            logger.warning("wishlist write failed: %s", exc)
            return {
                "answer": f"wishlist 저장 실패: {exc}",
                "action": {"type": "none", "params": {}},
            }

    # 질문에서 항목 추출 — 한글 라벨(재료비/고정비…) 또는 슬러그/시트명 매칭.
    # 긴 라벨 우선(예 '고정비(사업부Control)' 가 '고정비'보다 먼저) → 정확 매칭.
    from . import registry
    area = None
    for it in sorted(registry.ITEMS, key=lambda x: len(x["label"]), reverse=True):
        if it["label"] in q or it["sheet"] in q or it["slug"] in q:
            area = it["slug"]
            break

    # ── 페이지 이동 명령 ───────────────────
    # 이동 의도(보여/가줘/이동/페이지)가 있을 때만 — 정보 질문과 구분
    move = any(k in q for k in ["보여", "가줘", "가자", "이동", "열어", "페이지", "로 가", "으로 가", "띄워"])
    nav_map = [
        (["실적 관리", "실적관리", "데이터 업데이트", "제출 현황 화면"], "/data"),
        (["보고서", "리포트", "report"], "/reports"),
        (["문서 관리", "문서관리", "파일 관리"], "/documents"),
        (["제출 관리", "제출관리", "수신함", "inbox"], "/inbox"),
        (["홈으로", "메인", "home", "처음 화면"], "/"),
    ]
    if move:
        for kws, path in nav_map:
            if any(k in q for k in kws):
                return {
                    "answer": f"{kws[0]} 화면으로 이동합니다.",
                    "action": {"type": "navigate", "params": {"path": path}},
                    "bypass_llm": True,
                }

    # ── 독촉 명령 ──────────────────────────
    if any(k in q for k in ["독촉", "재요청", "리마인드", "remind"]):
        from .tools import remind_action
        r = remind_action(area)
        miss = r.get("미제출", [])
        ans = (("미제출 항목: " + ", ".join(miss) + "\n실적 관리 화면에서 독촉을 보낼 수 있습니다.")
               if miss else "현재 미제출 항목이 없습니다.")
        return {"answer": ans, "action": r.get("_chat_action", {"type": "none", "params": {}}),
                "bypass_llm": True}

    # ── 정보 조회 (결정론 fallback — tool-use 안 되는 모델/오프라인용) ──
    from .tools import get_achievement, get_risks, get_status
    NO_ACT = {"type": "none", "params": {}}
    # 제출 현황 / 주차 / 미제출
    if any(k in q for k in ["주차", "몇 주", "어디까지", "미제출", "안 낸", "안낸",
                            "제출 현황", "제출현황", "다 냈", "다냈", "제출 상태", "제출됐", "수집"]):
        return {"answer": _fmt_status(get_status()), "action": NO_ACT, "bypass_llm": True}
    # 위험 / 미달
    if any(k in q for k in ["위험", "미달", "제일 낮", "가장 낮", "최저", "문제", "리스크", "risk"]):
        return {"answer": _fmt_risks(get_risks()), "action": NO_ACT, "bypass_llm": True}
    # 실적 / 달성률 / 남은 금액
    if any(k in q for k in ["실적", "달성", "목표 대비", "얼마 남", "남았", "진척", "달성률"]):
        return {"answer": _fmt_achievement(get_achievement(area)), "action": NO_ACT, "bypass_llm": True}

    return None


_TOOLS_UNSUPPORTED = False  # 모델이 tools 파라미터를 거부하면 set → 이후 chat_with_tools skip


def chat_with_tools(
    *,
    question: str,
    context: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    scenario_id_default: str = "2026-05-2",
    max_iterations: int = 5,
) -> Optional[Dict[str, Any]]:
    """챗에서 진짜 tool-use agent — LLM 이 도구 선택해 정보 조회 / UI action 결정.

    Returns:
        {answer, action, tool_calls_trace} or None (LLM 도달 못 함 → caller 가 fallback)
    """
    global _TOOLS_UNSUPPORTED
    client = _llm_client()
    if client is None:
        return None  # caller fallback (chat_answer)
    # 한 번 "tools 지원 안 함" 에러 받았으면 이후 호출 skip
    # (EXAONE 3.5 처럼 OpenAI tools 파라미터를 거부하는 모델 대응 — 매번 400 안 던지게)
    if _TOOLS_UNSUPPORTED:
        return None

    # 지연 import (순환 회피)
    from .tools import CHAT_TOOL_FUNCTIONS, CHAT_TOOLS

    system = (
        "당신은 '챗봇' — 키친솔루션 한계돌파 플랫폼의 경영성과 모니터링 비서입니다.\n"
        "사용자의 질문에 답하거나 명령을 실행합니다. 친근하고 간결한 한국어로 답합니다.\n\n"
        "사용 가능한 도구 (현재 적재된 실데이터를 조회):\n"
        "- get_status — 제출 현황 (몇 주차까지·미제출 항목)\n"
        "- get_achievement — 실적/달성률 (목표 대비·남은 금액, area 인자로 특정 항목)\n"
        "- get_risks — 위험/미달 항목 진단 (미달 영향·달성률 최저 top3)\n"
        "- navigate — 페이지 이동 (/data /reports /documents /inbox /)\n"
        "- remind — 미제출 항목 독촉 안내\n\n"
        "원칙:\n"
        "1. 정보 질문 (몇 주차? 미제출 어디? 달성률? 위험 항목?) → 정보 도구 호출 → 결과로 한국어 답변\n"
        "2. 페이지 이동 명령 ('보고서 보여줘') → navigate 도구\n"
        "3. 독촉 명령 ('미제출한 데 독촉해줘') → remind 도구\n\n"
        "구분 예시:\n"
        "- '지금 몇 주차까지 있어?' / '미제출 어디?' → get_status\n"
        "- '실적 얼마나 남았어?' / 'Area_A 달성률?' → get_achievement\n"
        "- '제일 미달인 항목?' / '위험한 거?' → get_risks\n"
        "- '보고서 보여줘' → navigate /reports\n\n"
        "답변은 한국어, 3~5문장 이내, 임원 보고체. 데이터에 없는 숫자는 만들지 마세요.\n\n"
        "중요 규칙:\n"
        "- 도구 호출은 반드시 OpenAI 의 정식 tool_calls 형식으로만 하세요.\n"
        "- 텍스트로 '<tool_call>' 같은 가짜 호출 작성 금지.\n"
        "- 한 사용자 입력에 같은 도구를 반복 호출하지 마세요.\n"
        "- UI 액션 도구 (navigate/remind) 는 한 번만.\n\n"
        f"[동적 컨텍스트]\n{_build_system_context()}\n"
        f"\n{_LANG_GUARD}\n"
    )

    model = os.getenv("LLM_MODEL", "qwen2.5:14b-instruct")
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]

    chat_action: Optional[Dict[str, Any]] = None
    trace: List[Dict[str, Any]] = []

    for it in range(max_iterations):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=CHAT_TOOLS,
                tool_choice="auto",
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            )
        except Exception as exc:
            msg = str(exc)
            # 모델이 tools 파라미터 자체를 거부하면 — 이후 호출 영구 skip
            if "does not support tools" in msg or ("tool" in msg.lower() and "support" in msg.lower()):
                _TOOLS_UNSUPPORTED = True
                logger.warning(
                    "chat tool-use: model rejects 'tools' param → disabling tool-use, falling back to deterministic matching"
                )
            else:
                logger.warning("chat tool-use LLM call failed: %s", exc)
            return None

        msg = response.choices[0].message
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if not msg.tool_calls:
            text = _sanitize((msg.content or "").strip())
            # LLM 이 텍스트로 tool 호출 흉내 — fallback 으로
            if "<tool_call>" in text or '"name":' in text and '"arguments"' in text:
                logger.warning("chat tool-use: LLM faked tool_call in text — fallback")
                return None
            return {
                "answer": text or "답변을 생성하지 못했습니다.",
                "action": chat_action or {"type": "none", "params": {}},
                "tool_calls_trace": trace,
            }

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}

            fn = CHAT_TOOL_FUNCTIONS.get(name)
            if fn is None:
                result = {"error": f"unknown tool: {name}"}
            else:
                try:
                    result = fn(**args)
                except Exception as exc:
                    logger.warning("chat tool %s failed: %s", name, exc)
                    result = {"error": f"{type(exc).__name__}: {exc}"}

            if isinstance(result, dict) and "_chat_action" in result:
                chat_action = result["_chat_action"]

            trace.append({"tool": name, "args": args, "result_summary": _short_summary(result)})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False, default=str)[:4000],
            })

        # UI action 도구 호출됐으면 — LLM 한테 짧은 confirmation 요청 후 즉시 종료
        # (LLM 이 같은 action 도구 반복 호출하는 걸 방지)
        if chat_action is not None:
            try:
                confirm = client.chat.completions.create(
                    model=model,
                    messages=messages + [{
                        "role": "user",
                        "content": "위 action 을 frontend 가 처리할 예정입니다. 사용자에게 1~2문장으로 짧게 안내해 주세요. 도구는 더 호출하지 마세요.",
                    }],
                    max_tokens=200,
                    temperature=0.2,
                )
                text = _sanitize((confirm.choices[0].message.content or "").strip())
            except Exception:
                text = ""
            return {
                "answer": text or "요청을 처리하겠습니다.",
                "action": chat_action,
                "tool_calls_trace": trace,
            }

    # max_iterations 초과
    return {
        "answer": "분석이 길어져서 결론을 내지 못했습니다. 더 구체적으로 질문해 주세요.",
        "action": chat_action or {"type": "none", "params": {}},
        "tool_calls_trace": trace,
    }


def _short_summary(result: Any) -> str:
    if isinstance(result, dict):
        if "error" in result:
            return f"❌ {result['error']}"
        if "_chat_action" in result:
            act = result["_chat_action"]
            return f"→ {act.get('type')}({act.get('params', {})})"
        if "현재_주차" in result:
            return f"{result.get('현재_주차')} · 미제출 {result.get('미제출_수', 0)}건"
        if "미달영향_top3" in result:
            return f"미달 {len(result.get('미달영향_top3', []))}건"
        if "전체_누적" in result or "항목" in result:
            return "실적 집계"
    return str(result)[:80]


def chat_answer(
    *,
    question: str,
    preset: Optional[str] = None,
    **_ignore: Any,
) -> Dict[str, Any]:
    """모니 응답 — 실데이터 Q&A + 명령 처리.

    - preset 지정 → 결정론 핸들러 (실데이터 인용)
    - 자연어 명령/질문 매칭 (_detect_command) → 도구 직접 호출 즉답 (숫자 정확)
    - 그 외 자유 입력 → LLM (도달 시), 실패 시 안내
    Returns: {"answer", "citations", "preset_used", "action"}
    """
    NO_ACTION = {"type": "none", "params": {}}

    if preset and preset in _PRESET_HANDLERS:
        out = _PRESET_HANDLERS[preset]()
        return {
            "answer": out["answer"],
            "citations": out.get("citations", []),
            "preset_used": preset,
            "action": NO_ACTION,
        }

    q = (question or "").strip()
    if not q:
        return {
            "answer": "질문을 입력하거나 빠른 명령 버튼을 눌러주세요.",
            "citations": [],
            "preset_used": None,
            "action": NO_ACTION,
        }

    # 자연어 명령/질문 매칭 — 도구 직접 호출 (숫자 정확, LLM 불필요)
    cmd = _detect_command(q)
    if cmd:
        return {
            "answer": cmd["answer"],
            "citations": [],
            "preset_used": None,
            "action": cmd.get("action", NO_ACTION),
        }

    # 그 외 자유 입력 → LLM (모니 소개 등 메타 질문). 구체 수치는 위 매칭이 처리.
    sys_ctx = _build_system_context()
    prompt = (
        f"[시스템 컨텍스트]\n{sys_ctx}\n\n"
        f"[사용자 질문]\n{q}\n\n"
        "당신은 '챗봇' — 키친솔루션 한계돌파 플랫폼의 경영성과 모니터링 비서입니다. "
        "위 컨텍스트와 일반 지식으로 한국어로 간결히 답하세요 (3~5문장). "
        "구체적 수치는 '지금 몇 주차?', '미제출 알려줘', '실적 달성률?', '제일 미달인 항목?' "
        "같은 질문으로 조회할 수 있다고 안내하세요. 데이터에 없는 숫자는 만들지 마세요."
    )
    text = _llm_complete(prompt)
    if not text:
        text = (
            "답변을 생성하지 못했습니다. 다음 명령을 사용해 주세요 — "
            "'지금 몇 주차까지 있어?' · '미제출 알려줘' · '실적 달성률?' · "
            "'제일 미달인 항목?' · '도구 목록'."
        )
    return {"answer": text, "citations": [], "preset_used": None, "action": NO_ACTION}
