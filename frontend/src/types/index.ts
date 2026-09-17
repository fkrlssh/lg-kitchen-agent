/** 백엔드 Pydantic 스키마 미러 (backend/app/models/schemas.py). */

// ─────────────────────────────────────────────
// Chat — 챗봇 어시스턴트
// ─────────────────────────────────────────────

export type ChatPresetId = 'status' | 'missing' | 'achievement' | 'risk';

export interface ChatPreset {
  id: ChatPresetId;
  label: string;
  question: string;
}

export interface ChatRequest {
  task_id?: string;
  message?: string;
  preset?: ChatPresetId | null;
}

export type ChatCitationKind =
  | 'category'
  | 'anomaly'
  | 'strategy'
  | 'missing'
  | 'totals'
  | 'counts';

export interface ChatCitation {
  label: string;
  kind: ChatCitationKind;
}

export type ChatActionType =
  | 'none'
  | 'navigate'
  | 'open_tool_catalog';

export interface ChatAction {
  type: ChatActionType;
  params: Record<string, string>;
}

export interface ChatToolCall {
  tool: string;
  args: Record<string, unknown>;
  result_summary?: string | null;
}

export interface ChatResponse {
  answer: string;
  citations: ChatCitation[];
  preset_used: ChatPresetId | null;
  action: ChatAction;
  tool_calls?: ChatToolCall[];
  used_tools?: boolean;
}
