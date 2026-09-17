'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LineChart, FileText, FolderOpen, Sparkles } from 'lucide-react';
import { clsx } from 'clsx';

const NAV = [
  { href: '/data', label: '실적 관리', icon: LineChart },
  { href: '/reports', label: '보고서 운영', icon: FileText },
  { href: '/documents', label: '문서 관리', icon: FolderOpen },
  { href: '/simulation', label: '변경 시뮬레이션', icon: Sparkles },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-60 fixed left-0 top-0 h-screen border-r border-slate-200 bg-white flex flex-col">
      <Link
        href="/"
        className="px-6 py-5 border-b border-slate-100 block hover:bg-slate-50 transition-colors"
        aria-label="홈으로"
      >
        <div className="flex items-center">
          <div>
            <div className="text-sm font-semibold text-slate-900 leading-tight">키친솔루션</div>
            <div className="text-[10px] text-slate-500 leading-tight">한계돌파 플랫폼</div>
          </div>
        </div>
      </Link>

      <nav className="flex-1 px-3 py-4">
        {NAV.map((item) => {
          const active = pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                active
                  ? 'bg-primary-50 text-primary-700 font-medium'
                  : 'text-slate-600 hover:bg-slate-50',
              )}
            >
              <Icon className="w-4 h-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="px-6 py-4 border-t border-slate-100 text-[10px] text-slate-400 leading-relaxed">
        키친솔루션 한계돌파 플랫폼
      </div>
    </aside>
  );
}
