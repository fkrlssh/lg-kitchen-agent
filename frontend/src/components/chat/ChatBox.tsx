'use client';

import { useEffect, useRef } from 'react';
import { Bot, Send, Sparkles, User as UserIcon, Wrench } from 'lucide-react';

import type {
  ChatCitation,
  ChatPreset,
  ChatPresetId,
} from '@/types';
import type { ChatMessage } from '@/hooks/useChat';

const CITATION_TONE: Record<string, string> = {
  category: 'bg-amber-50 text-amber-800 border-amber-200',
  anomaly: 'bg-rose-50 text-rose-800 border-rose-200',
  strategy: 'bg-violet-50 text-violet-800 border-violet-200',
  missing: 'bg-slate-100 text-slate-700 border-slate-200',
  totals: 'bg-primary-50 text-primary-700 border-primary-200',
  counts: 'bg-emerald-50 text-emerald-800 border-emerald-200',
};

export type ChatBoxProps = {
  messages: ChatMessage[];
  send: (args: { message?: string; preset?: ChatPresetId }) => void | Promise<void>;
  busy: boolean;
  presets: ChatPreset[];
  // 빠른 명령 버튼 (홈 화면용)
  quickCommands?: { label: string; message: string }[];
  // 입력란 placeholder
  placeholder?: string;
  // 입력 값 (controlled)
  input: string;
  setInput: (v: string) => void;
  // layout 마다 살짝 다른 스타일
  variant?: 'full' | 'panel';
};

export default function ChatBox({
  messages,
  send,
  busy,
  presets,
  quickCommands,
  placeholder,
  input,
  setInput,
  variant = 'panel',
}: ChatBoxProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, busy]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim()) {
      const v = input.trim();
      setInput('');
      send({ message: v });
    }
  };

  return (
    <div className={`flex flex-col h-full ${variant === 'full' ? 'bg-white' : ''}`}>
      {/* Quick commands (홈) */}
      {quickCommands && quickCommands.length > 0 && (
        <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
          <div className="text-[11px] text-slate-500 mb-2 flex items-center gap-1">
            <Sparkles className="w-3 h-3" />
            빠른 명령
          </div>
          <div className="flex flex-wrap gap-1.5">
            {quickCommands.map((q, i) => (
              <button
                key={i}
                onClick={() => send({ message: q.message })}
                disabled={busy}
                className="text-[11px] px-2.5 py-1.5 bg-white border border-slate-200 hover:border-violet-300 hover:bg-violet-50 text-slate-700 rounded-md disabled:opacity-50"
              >
                {q.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Presets (빠른 질문 — 현재 데이터 상태 조회) */}
      {presets.length > 0 && (
        <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
          <div className="text-[11px] text-slate-500 mb-2 flex items-center gap-1">
            <Sparkles className="w-3 h-3" />
            빠른 질문
          </div>
          <div className="flex flex-wrap gap-1.5">
            {presets.map((p) => (
              <button
                key={p.id}
                onClick={() => send({ preset: p.id })}
                disabled={busy}
                className="text-[11px] px-2.5 py-1.5 bg-white border border-slate-200 hover:border-violet-300 hover:bg-violet-50 text-slate-700 rounded-md disabled:opacity-50"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {messages.map((m) => (
          <MessageBubble key={m.id} msg={m} />
        ))}
      </div>

      {/* Input */}
      <div className="px-5 py-3 border-t border-slate-200">
        <form onSubmit={onSubmit} className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={placeholder || '예: 지금 몇 주차까지 있어? / 재료비 달성률?'}
            disabled={busy}
            className="flex-1 px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-violet-300 disabled:bg-slate-50"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="p-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg disabled:opacity-40"
            aria-label="보내기"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
        <div className="text-[10px] text-slate-400 mt-1.5 leading-snug">
          답변의 숫자는 적재된 실데이터 집계에서만 인용됩니다.
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  if (msg.role === 'user') {
    return (
      <div className="flex items-start gap-2 justify-end">
        <div className="max-w-[85%] bg-primary-500 text-white text-sm px-3 py-2 rounded-2xl rounded-tr-sm whitespace-pre-wrap">
          {msg.text}
        </div>
        <div className="w-7 h-7 rounded-full bg-slate-100 flex items-center justify-center flex-shrink-0">
          <UserIcon className="w-3.5 h-3.5 text-slate-500" />
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2">
      <div className="w-7 h-7 rounded-full bg-violet-100 flex items-center justify-center flex-shrink-0">
        <Bot className="w-3.5 h-3.5 text-violet-700" />
      </div>
      <div className="max-w-[85%]">
        <div
          className={`bg-slate-50 border border-slate-200 text-sm text-slate-800 px-3 py-2 rounded-2xl rounded-tl-sm whitespace-pre-wrap ${
            msg.loading ? 'animate-pulse' : ''
          }`}
        >
          {msg.text}
        </div>
        {msg.citations && msg.citations.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {msg.citations.map((c: ChatCitation, i) => (
              <span
                key={i}
                className={`text-[10px] px-1.5 py-0.5 border rounded ${CITATION_TONE[c.kind] || 'bg-slate-50 text-slate-700 border-slate-200'}`}
                title={`근거: ${c.kind}`}
              >
                {c.label}
              </span>
            ))}
          </div>
        )}
        {msg.usedTools && msg.toolCalls && msg.toolCalls.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {msg.toolCalls.map((t, i) => (
              <span
                key={i}
                className="text-[10px] px-1.5 py-0.5 border rounded bg-violet-50 text-violet-700 border-violet-200 inline-flex items-center gap-1"
                title={t.result_summary || ''}
              >
                <Wrench className="w-2.5 h-2.5" />
                {t.tool}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
