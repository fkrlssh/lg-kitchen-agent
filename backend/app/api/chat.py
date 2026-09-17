"""모니 챗 — 현재 LG 데이터 상태를 자연어로 묻는 Q&A 비서.

설계 (2026-06-23 재작성 — 옛 격주/파이프라인 의존 제거):
- 항상 최신 스냅샷(store)을 본다. task_id/scenario/context 개념 없음.
- 하이브리드: 결정론 매칭(_detect_command, 숫자 정확) 우선 → 모호하면 LLM tool-use.
- 자연어 명령 매칭은 narrative._detect_command, 도구는 src/tools.py.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import ChatAction, ChatPreset, ChatRequest, ChatResponse, ChatToolCall
from src.narrative import PRESETS, _detect_command, chat_answer, chat_with_tools

router = APIRouter()


@router.get("/presets", response_model=list[ChatPreset])
async def list_presets():
    """프리셋 버튼용 — 프론트가 라벨 하드코딩 안 하게."""
    labels = {
        "status": "제출 현황",
        "missing": "미제출 항목",
        "achievement": "전체 달성률",
        "risk": "미달 항목",
    }
    return [
        ChatPreset(id=k, label=labels.get(k, k), question=v)
        for k, v in PRESETS.items()
    ]


def _action(raw: dict | None) -> ChatAction:
    raw = raw or {"type": "none", "params": {}}
    return ChatAction(type=raw.get("type", "none"), params=raw.get("params", {}))


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest):
    msg = req.message or ""

    # 1) preset 버튼 → 결정론 핸들러 (실데이터 인용)
    if req.preset:
        out = chat_answer(question=msg, preset=req.preset)
        return ChatResponse(
            answer=out["answer"], citations=out.get("citations", []),
            preset_used=out.get("preset_used"), action=_action(out.get("action")),
            tool_calls=[], used_tools=False,
        )

    # 2) 결정론 매칭 (메타 명령 + 데이터 질문) — 숫자 정확, LLM 불필요
    cmd = _detect_command(msg)
    if cmd:
        return ChatResponse(
            answer=cmd["answer"], citations=[], preset_used=None,
            action=_action(cmd.get("action")), tool_calls=[], used_tools=False,
        )

    # 3) 자유/모호 입력 → LLM tool-use agent
    tool_out = chat_with_tools(question=msg)
    if tool_out is not None:
        tcs = [
            ChatToolCall(tool=t["tool"], args=t.get("args", {}),
                         result_summary=t.get("result_summary"))
            for t in tool_out.get("tool_calls_trace", [])
        ]
        return ChatResponse(
            answer=tool_out["answer"], citations=[], preset_used=None,
            action=_action(tool_out.get("action")), tool_calls=tcs, used_tools=True,
        )

    # 4) LLM 도달 못 함 → chat_answer (LLM 자유답변 or 안내)
    out = chat_answer(question=msg)
    return ChatResponse(
        answer=out["answer"], citations=out.get("citations", []),
        preset_used=out.get("preset_used"), action=_action(out.get("action")),
        tool_calls=[], used_tools=False,
    )
