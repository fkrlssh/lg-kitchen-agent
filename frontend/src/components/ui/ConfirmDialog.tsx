'use client';

import { AlertCircle, Info, Loader2 } from 'lucide-react';

type Variant = 'default' | 'danger' | 'info';

const VARIANT_STYLE: Record<Variant, { iconColor: string; bg: string; confirmBtn: string }> = {
  default: {
    iconColor: 'text-primary-600',
    bg: 'bg-primary-50',
    confirmBtn: 'bg-primary-500 hover:bg-primary-600',
  },
  danger: {
    iconColor: 'text-rose-600',
    bg: 'bg-rose-50',
    confirmBtn: 'bg-rose-600 hover:bg-rose-700',
  },
  info: {
    iconColor: 'text-violet-600',
    bg: 'bg-violet-50',
    confirmBtn: 'bg-violet-600 hover:bg-violet-700',
  },
};

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = '확인',
  cancelLabel = '취소',
  variant = 'default',
  busy = false,
  busyLabel,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: Variant;
  busy?: boolean;          // 처리 중: 바깥클릭·버튼 잠금(업로드 미리보기 모달과 동일 UX)
  busyLabel?: string;      // 처리 중 확인 버튼 문구(기본=confirmLabel)
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  const style = VARIANT_STYLE[variant];
  const Icon = variant === 'danger' ? AlertCircle : Info;

  return (
    <div className={`fixed inset-0 z-[60] flex items-center justify-center ${busy ? 'cursor-wait' : ''}`}>
      {/* Backdrop — 처리 중엔 바깥 클릭으로 안 닫힘(완료까지 유지) */}
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
        onClick={busy ? undefined : onCancel}
      />

      {/* Dialog */}
      <div className="relative bg-white rounded-2xl shadow-2xl w-[420px] max-w-[calc(100vw-2rem)] overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="px-5 py-5">
          <div className="flex items-start gap-3">
            <div className={`w-10 h-10 rounded-full ${style.bg} flex items-center justify-center flex-shrink-0`}>
              <Icon className={`w-5 h-5 ${style.iconColor}`} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-base font-semibold text-slate-900">{title}</h3>
              <p className="mt-2 text-sm text-slate-600 leading-relaxed whitespace-pre-line">{message}</p>
            </div>
          </div>
        </div>
        <div className="px-5 py-3 bg-slate-50 flex items-center justify-between gap-2 border-t border-slate-100">
          <span className="text-xs text-slate-500 inline-flex items-center gap-1">
            {busy && (<><Loader2 className="w-3.5 h-3.5 animate-spin" /> 처리 중 — 완료까지 닫지 마세요</>)}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onCancel}
              disabled={busy}
              className="px-4 py-2 text-sm text-slate-700 hover:bg-slate-100 rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {cancelLabel}
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={busy}
              className={`inline-flex items-center gap-2 px-4 py-2 text-sm text-white rounded-lg font-medium disabled:opacity-60 disabled:cursor-wait ${style.confirmBtn}`}
            >
              {busy && <Loader2 className="w-4 h-4 animate-spin" />}
              {busy ? (busyLabel ?? confirmLabel) : confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
