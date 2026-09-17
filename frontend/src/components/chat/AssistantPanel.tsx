'use client';

import { useEffect, useState } from 'react';
import { Bot, X, Plus, MessageSquare, Trash2, History, Wrench } from 'lucide-react';

import { chatService } from '@/services/chatService';
import { useChat, type Conversation } from '@/hooks/useChat';
import type { ChatPreset } from '@/types';
import ChatBox from './ChatBox';
import ConfirmDialog from '../ui/ConfirmDialog';
import ToolCatalog from './ToolCatalog';

export default function AssistantPanel({
  taskId,
  open,
  onClose,
}: {
  taskId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [presets, setPresets] = useState<ChatPreset[]>([]);
  const [input, setInput] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const {
    messages,
    send,
    busy,
    setMessages,
    conversations,
    activeId,
    createNew,
    selectConv,
    deleteConv,
  } = useChat({ taskId });

  useEffect(() => {
    chatService.presets().then(setPresets).catch(() => setPresets([]));
  }, []);

  // 마지막 assistant 메시지가 open_tool_catalog action 이면 카탈로그 자동 오픈
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (last?.role === 'assistant' && last.action?.type === 'open_tool_catalog') {
      setCatalogOpen(true);
    }
  }, [messages]);

  useEffect(() => {
    if (open && messages.length === 0 && activeId) {
      const greeting = '안녕하세요, 챗봇입니다. 현재 데이터에 대해 무엇이든 물어보세요.';
      setMessages([
        {
          id: 'welcome',
          role: 'assistant',
          text: greeting,
        },
      ]);
    }
  }, [open, taskId, messages.length, setMessages, activeId]);

  // 최신 대화 위로
  const sortedConvs = [...conversations].sort((a, b) => b.updated_at - a.updated_at);

  const formatTime = (ts: number) => {
    const d = new Date(ts);
    const today = new Date();
    if (d.toDateString() === today.toDateString()) {
      return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
    }
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  return (
    <>
      <aside
        className={`fixed bottom-6 right-6 w-[calc(100vw-3rem)] sm:w-[640px] h-[calc(100vh-6rem)] sm:h-[640px] max-h-[calc(100vh-3rem)] bg-white border border-slate-200 rounded-2xl shadow-2xl z-50 flex origin-bottom-right transition-all duration-200 overflow-hidden ${
          open
            ? 'opacity-100 scale-100 pointer-events-auto'
            : 'opacity-0 scale-95 pointer-events-none'
        }`}
        aria-hidden={!open}
      >
        {/* History sidebar */}
        <div
          className={`flex-shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col transition-all duration-200 ${
            historyOpen ? 'w-56' : 'w-0'
          }`}
        >
          {historyOpen && (
            <>
              <div className="px-3 py-3 border-b border-slate-200 flex items-center justify-between">
                <div className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
                  <History className="w-3.5 h-3.5" />
                  대화 이력
                </div>
                <button
                  type="button"
                  onClick={() => setHistoryOpen(false)}
                  className="p-1 hover:bg-slate-200 rounded text-slate-400 hover:text-slate-600"
                  aria-label="대화 이력 닫기"
                  title="닫기"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
                {sortedConvs.length === 0 ? (
                  <div className="text-[11px] text-slate-400 px-2 py-3 text-center">기록 없음</div>
                ) : (
                  sortedConvs.map((c) => {
                    const isActive = c.id === activeId;
                    return (
                      <div
                        key={c.id}
                        className={`group flex items-center gap-1 px-2 py-1.5 rounded-md cursor-pointer transition ${
                          isActive
                            ? 'bg-violet-100 text-violet-900'
                            : 'hover:bg-white text-slate-700'
                        }`}
                        onClick={() => selectConv(c.id)}
                      >
                        <MessageSquare className="w-3 h-3 flex-shrink-0 opacity-60" />
                        <div className="flex-1 min-w-0">
                          <div className="text-[12px] font-medium truncate leading-tight">
                            {c.title || '새 대화'}
                          </div>
                          <div className="text-[10px] text-slate-400">{formatTime(c.updated_at)}</div>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteTarget(c);
                          }}
                          className="p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-rose-100 hover:text-rose-600 transition"
                          aria-label="삭제"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
            </>
          )}
        </div>

        {/* Main chat panel */}
        <div className="flex-1 flex flex-col min-w-0 relative">
          <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between bg-gradient-to-r from-violet-50 to-white">
            <div className="flex items-center gap-2 min-w-0">
              <button
                type="button"
                onClick={() => setHistoryOpen(true)}
                className={`p-1.5 rounded-md transition ${
                  historyOpen ? 'bg-violet-100 text-violet-700' : 'hover:bg-slate-100 text-slate-500'
                }`}
                aria-label="대화 이력 열기"
                title="대화 이력"
              >
                <History className="w-4 h-4" />
              </button>
              <div className="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center flex-shrink-0">
                <Bot className="w-4 h-4 text-violet-700" />
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-slate-900 text-sm">챗봇</div>
              </div>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              <button
                onClick={() => setCatalogOpen(true)}
                className="p-1.5 hover:bg-slate-100 rounded-md text-slate-500"
                aria-label="도구 카탈로그"
                title="챗봇 도구 카탈로그"
              >
                <Wrench className="w-4 h-4" />
              </button>
              <button
                onClick={createNew}
                className="p-1.5 hover:bg-slate-100 rounded-md text-slate-500"
                aria-label="새 대화"
                title="새 대화 시작"
              >
                <Plus className="w-4 h-4" />
              </button>
              <button
                onClick={onClose}
                className="p-1.5 hover:bg-slate-100 rounded-md text-slate-500"
                aria-label="닫기"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 min-h-0">
            <ChatBox
              messages={messages}
              send={send}
              busy={busy}
              presets={presets}
              input={input}
              setInput={setInput}
              variant="panel"
            />
          </div>

          <ToolCatalog
            open={catalogOpen}
            onClose={() => setCatalogOpen(false)}
            onSendExample={(msg) => send({ message: msg })}
          />
        </div>
      </aside>

      <ConfirmDialog
        open={!!deleteTarget}
        variant="danger"
        title="대화 삭제"
        message={
          deleteTarget
            ? `"${deleteTarget.title || '새 대화'}" 를 삭제하시겠습니까?\n\n메시지 이력이 모두 사라집니다.`
            : ''
        }
        confirmLabel="삭제"
        cancelLabel="취소"
        onConfirm={() => {
          if (deleteTarget) deleteConv(deleteTarget.id);
          setDeleteTarget(null);
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  );
}
