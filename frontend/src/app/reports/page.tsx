'use client';

import { ReportView } from '@/components/reports/ReportView';

// /reports 라우트 — 기본 보고서 본문(현재 데이터). 시뮬레이션(/simulation)은 같은 ReportView 를 snap 으로 재사용.
export default function ReportsPage() {
  return <ReportView />;
}
