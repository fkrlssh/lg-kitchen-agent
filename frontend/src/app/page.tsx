'use client';

import Link from 'next/link';
import { LineChart, FileText, FolderOpen, ArrowRight } from 'lucide-react';

// 키친솔루션 한계돌파 플랫폼 — 진입 랜딩.
// 3개 블록(실적 관리 / 보고서 운영 / 문서 관리)으로 각 섹션 진입.
// 구 홈("운영 현황")은 /archive 로 보존(추후 재활용).

const BLOCKS = [
  {
    href: '/data',
    label: '실적 관리',
    desc: '요청 발송, 제출 현황, 마감을 관리합니다.',
    icon: LineChart,
    accent: 'from-primary-500 to-primary-700',
    iconBg: 'bg-primary-50 text-primary-700',
  },
  {
    href: '/reports',
    label: '보고서 운영',
    desc: '차수, 월, 분기별 실적 보고서를 관리합니다.',
    icon: FileText,
    accent: 'from-violet-500 to-violet-700',
    iconBg: 'bg-violet-50 text-violet-700',
  },
  {
    href: '/documents',
    label: '문서 관리',
    desc: '만회 대책 등 문서를 관리, 확인합니다.',
    icon: FolderOpen,
    accent: 'from-emerald-500 to-emerald-700',
    iconBg: 'bg-emerald-50 text-emerald-700',
  },
];

export default function HomePage() {
  return (
    <div className="px-10 py-10 max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 leading-tight">
          키친솔루션 한계돌파 플랫폼
        </h1>
      </div>

      <div className="flex flex-col gap-4">
        {BLOCKS.map((b) => {
          const Icon = b.icon;
          return (
            <Link
              key={b.href}
              href={b.href}
              className="group relative flex items-center gap-5 bg-white border border-slate-200 rounded-2xl px-8 py-7 shadow-card hover:shadow-lg hover:border-primary-300 transition-all overflow-hidden"
            >
              <div className={`absolute left-0 top-0 bottom-0 w-1.5 bg-gradient-to-b ${b.accent} opacity-0 group-hover:opacity-100 transition-opacity`} />
              <div className={`w-14 h-14 rounded-xl ${b.iconBg} flex items-center justify-center flex-shrink-0`}>
                <Icon className="w-7 h-7" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-xl font-semibold text-slate-900">{b.label}</h2>
                <p className="text-sm text-slate-500 leading-relaxed mt-1">{b.desc}</p>
              </div>
              <ArrowRight className="w-6 h-6 text-slate-300 group-hover:text-primary-600 group-hover:translate-x-1 transition-all flex-shrink-0" />
            </Link>
          );
        })}
      </div>
    </div>
  );
}
