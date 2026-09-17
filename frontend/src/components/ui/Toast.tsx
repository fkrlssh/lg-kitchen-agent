'use client';

import { useEffect } from 'react';
import { CheckCircle2, AlertCircle, X } from 'lucide-react';

export interface ToastData {
  id: number;
  ok: boolean;
  text: string;
}

const TONE = {
  ok: { icon: CheckCircle2, ring: 'border-emerald-200', bar: 'bg-emerald-500', ic: 'text-emerald-600' },
  err: { icon: AlertCircle, ring: 'border-rose-200', bar: 'bg-rose-500', ic: 'text-rose-600' },
};

// 우측 하단 토스트 — 자동 사라짐(기본 3.2초). 여러 개 쌓임.
export default function ToastHost({ toasts, onClose }: { toasts: ToastData[]; onClose: (id: number) => void }) {
  return (
    <div className="fixed bottom-24 right-6 z-[60] flex flex-col gap-2 items-end pointer-events-none">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onClose={() => onClose(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onClose }: { toast: ToastData; onClose: () => void }) {
  const tone = toast.ok ? TONE.ok : TONE.err;
  const Icon = tone.icon;
  useEffect(() => {
    const t = setTimeout(onClose, 3200);
    return () => clearTimeout(t);
  }, [onClose]);

  return (
    <div
      className={`pointer-events-auto w-[320px] bg-white border ${tone.ring} rounded-lg shadow-lg overflow-hidden animate-[slideIn_0.2s_ease-out]`}
      style={{ animation: 'slideIn 0.2s ease-out' }}
    >
      <div className="flex items-start gap-2.5 px-4 py-3">
        <Icon className={`w-5 h-5 ${tone.ic} flex-shrink-0 mt-0.5`} />
        <p className="flex-1 text-sm text-slate-700 leading-snug">{toast.text}</p>
        <button onClick={onClose} className="text-slate-300 hover:text-slate-500 flex-shrink-0">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className={`h-0.5 ${tone.bar} opacity-70`} />
    </div>
  );
}
