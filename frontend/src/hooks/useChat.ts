'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { chatService } from '@/services/chatService';
import type {
  ChatAction,
  ChatCitation,
  ChatPresetId,
  ChatResponse,
  ChatToolCall,
} from '@/types';

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  citations?: ChatCitation[];
  preset?: ChatPresetId | null;
  action?: ChatAction;
  loading?: boolean;
  toolCalls?: ChatToolCall[];
  usedTools?: boolean;
};

let _msgIdCounter = 0;
const nextId = () => `m${++_msgIdCounter}_${Date.now()}`;

export type Conversation = {
  id: string;
  title: string;
  messages: ChatMessage[];
  created_at: number;
  updated_at: number;
};

const STORAGE_KEY = 'lks-chat-conversations';
const LEGACY_SINGLE_KEY = 'lks-chat-messages';

type Persisted = {
  conversations: Conversation[];
  activeId: string | null;
};

function newConvId() {
  return `c_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
}

function deriveTitle(messages: ChatMessage[]): string {
  const firstUser = messages.find((m) => m.role === 'user' && (m.text || '').trim());
  if (firstUser && firstUser.text) {
    const t = firstUser.text.trim().replace(/\s+/g, ' ');
    return t.length > 30 ? t.slice(0, 30) + '…' : t;
  }
  return '새 대화';
}

function load(): Persisted {
  if (typeof window === 'undefined') return { conversations: [], activeId: null };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Persisted;
      if (parsed && Array.isArray(parsed.conversations)) return parsed;
    }
    // legacy single-thread → migration
    const legacy = localStorage.getItem(LEGACY_SINGLE_KEY);
    if (legacy) {
      const msgs = JSON.parse(legacy) as ChatMessage[];
      if (Array.isArray(msgs) && msgs.length > 0) {
        const id = newConvId();
        const now = Date.now();
        return {
          conversations: [{ id, title: deriveTitle(msgs), messages: msgs, created_at: now, updated_at: now }],
          activeId: id,
        };
      }
    }
  } catch {
    // ignore
  }
  return { conversations: [], activeId: null };
}

function save(state: Persisted) {
  if (typeof window === 'undefined') return;
  try {
    // loading 메시지는 영속화 안 함
    const clean: Persisted = {
      ...state,
      conversations: state.conversations.map((c) => ({
        ...c,
        messages: c.messages.filter((m) => !m.loading),
      })),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(clean));
  } catch {
    // ignore
  }
}

// 프리셋 버튼 클릭 시 대화에 표시할 사용자 메시지 라벨
const PRESET_LABELS: Record<string, string> = {
  status: '제출 현황',
  missing: '미제출 항목',
  achievement: '전체 달성률',
  risk: '미달 항목',
};

export function useChat(_opts: { taskId?: string | null } = {}) {
  const router = useRouter();
  const [persisted, setPersisted] = useState<Persisted>(load);
  const [busy, setBusy] = useState(false);

  const conversations = persisted.conversations;
  const activeId = persisted.activeId;
  const activeConv = conversations.find((c) => c.id === activeId) ?? null;
  const messages = activeConv?.messages ?? [];

  // persisted 변경 시 localStorage 영속화
  useEffect(() => {
    save(persisted);
  }, [persisted]);

  // active conversation 이 없으면 항상 새 대화 하나 자동 생성 (전부 삭제한 경우까지).
  // setPersisted 안에서 최신 상태로 다시 판정 → StrictMode 이중호출에도 중복 생성 안 됨(idempotent).
  useEffect(() => {
    if (activeId && conversations.some((c) => c.id === activeId)) return;
    setPersisted((p) => {
      if (p.activeId && p.conversations.some((c) => c.id === p.activeId)) return p;
      const id = newConvId();
      const now = Date.now();
      return {
        conversations: [
          ...p.conversations,
          { id, title: '새 대화', messages: [], created_at: now, updated_at: now },
        ],
        activeId: id,
      };
    });
  }, [activeId, conversations]);

  // 외부 호환 setMessages — 현재 active conversation 의 messages 만 갱신
  const setMessages = useCallback(
    (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
      setPersisted((p) => {
        const aid = p.activeId;
        if (!aid) return p;
        return {
          ...p,
          conversations: p.conversations.map((c) => {
            if (c.id !== aid) return c;
            const next = typeof updater === 'function' ? updater(c.messages) : updater;
            return {
              ...c,
              messages: next,
              title: c.title === '새 대화' || !c.title ? deriveTitle(next) : c.title,
              updated_at: Date.now(),
            };
          }),
        };
      });
    },
    [],
  );

  const createNew = useCallback(() => {
    const id = newConvId();
    const now = Date.now();
    setPersisted((p) => ({
      conversations: [...p.conversations, { id, title: '새 대화', messages: [], created_at: now, updated_at: now }],
      activeId: id,
    }));
  }, []);

  const selectConv = useCallback((id: string) => {
    setPersisted((p) => ({ ...p, activeId: id }));
  }, []);

  const deleteConv = useCallback((id: string) => {
    setPersisted((p) => {
      const next = p.conversations.filter((c) => c.id !== id);
      let aid = p.activeId;
      if (aid === id) {
        aid = next.length > 0 ? next[next.length - 1].id : null;
      }
      return { conversations: next, activeId: aid };
    });
  }, []);

  // UI 액션 처리 — 페이지 이동만 (옛 파이프라인 실행/메일 액션은 폐기)
  const handleAction = useCallback(
    (action: ChatAction) => {
      if (!action || action.type === 'none') return;
      if (action.type === 'navigate') {
        const path = action.params.path || '/';
        // 짧은 딜레이로 사용자가 답변 읽을 시간 줌
        setTimeout(() => router.push(path), 600);
      }
      // open_tool_catalog 등 그 외 액션은 AssistantPanel 이 메시지 action 으로 처리
    },
    [router],
  );

  const send = useCallback(
    async ({
      message,
      preset,
    }: {
      message?: string;
      preset?: ChatPresetId;
    }) => {
      if (busy) return;
      const userText = message?.trim();
      const presetLabel = preset ? PRESET_LABELS[preset] : undefined;

      if (!userText && !preset) return;

      const userMsg: ChatMessage = {
        id: nextId(),
        role: 'user',
        text: userText || presetLabel || '',
      };
      const loadingMsg: ChatMessage = {
        id: nextId(),
        role: 'assistant',
        text: '…',
        loading: true,
      };
      setMessages((prev) => [...prev, userMsg, loadingMsg]);
      setBusy(true);

      try {
        const res: ChatResponse = await chatService.ask({
          message: userText || '',
          preset: preset || null,
        });
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = {
            id: loadingMsg.id,
            role: 'assistant',
            text: res.answer,
            citations: res.citations,
            preset: res.preset_used,
            action: res.action,
            toolCalls: res.tool_calls,
            usedTools: res.used_tools,
          };
          return copy;
        });
        handleAction(res.action);
      } catch (e) {
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = {
            id: loadingMsg.id,
            role: 'assistant',
            text: `오류: ${String(e)}`,
          };
          return copy;
        });
      } finally {
        setBusy(false);
      }
    },
    [busy, handleAction, setMessages],
  );

  const reset = useCallback(() => {
    // 새 대화 시작 (기존 대화는 history 에 보관)
    createNew();
  }, [createNew]);

  return {
    messages,
    send,
    busy,
    reset,
    setMessages,
    // history sidebar
    conversations,
    activeId,
    createNew,
    selectConv,
    deleteConv,
  };
}
