'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Bot } from 'lucide-react';

import AssistantPanel from './AssistantPanel';

function GlobalAssistantInner() {
  const params = useSearchParams();
  const [open, setOpen] = useState(false);
  const taskId = params.get('taskId');

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={`fixed bottom-6 right-6 z-40 flex items-center gap-2 pl-3 pr-4 py-3 bg-violet-600 hover:bg-violet-700 text-white rounded-full shadow-lg transition-all ${
          open ? 'opacity-0 scale-90 pointer-events-none' : 'opacity-100 scale-100'
        }`}
        aria-label="챗봇 열기"
      >
        <Bot className="w-5 h-5" />
        <span className="text-sm font-medium">챗봇</span>
      </button>
      <AssistantPanel taskId={taskId} open={open} onClose={() => setOpen(false)} />
    </>
  );
}

export default function GlobalAssistant() {
  // 챗은 localStorage(대화 이력)에 의존 → 마운트 후에만 렌더해서 SSR 하이드레이션 불일치 방지
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  return (
    <Suspense fallback={null}>
      <GlobalAssistantInner />
    </Suspense>
  );
}
