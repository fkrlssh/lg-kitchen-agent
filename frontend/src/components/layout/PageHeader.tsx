'use client';

import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

/**
 * 모든 페이지의 헤더 — 일관된 디자인.
 *
 * 구성:
 *   [← back link]                          ← 선택
 *   [EYEBROW (키친솔루션 · …)]                    ← 선택, 작은 라벨
 *   [큰 제목]               [actions]
 *   [부제 / 설명]
 */
export default function PageHeader({
  eyebrow,
  title,
  description,
  backHref,
  backLabel,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  backHref?: string;
  backLabel?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 pb-5 border-b border-slate-200">
      {backHref && (
        <Link
          href={backHref}
          className="text-xs text-slate-500 hover:text-slate-900 inline-flex items-center gap-1 mb-3"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          {backLabel || '뒤로'}
        </Link>
      )}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          {eyebrow && (
            <div className="text-[11px] font-medium text-slate-500 uppercase tracking-wider mb-1.5">
              {eyebrow}
            </div>
          )}
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{title}</h1>
          {description && (
            <p className="text-sm text-slate-500 mt-1.5 max-w-2xl">{description}</p>
          )}
        </div>
        {actions && <div className="flex-shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
