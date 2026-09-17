// 회차/주차 표기 — store.WEEK_MONTH 미러 (단일 소스). 라벨은 'N월 W##'(주차번호)로 통일.
//   월별 차수 개수 + 그 달 1차의 ISO 주차번호. LG ver0.1('주차추가') 양식: 1월 W1-5 … 4월 W14-18.
// 전 연도(1~12월) 월별 주차 수 + 그 달 1차의 ISO 주차. 규칙 = 그 주 목요일이 속한 월(store.WEEK_MONTH 와 일치).
export const MONTH_WEEKS: Record<number, number> = { 1: 5, 2: 4, 3: 4, 4: 5, 5: 4, 6: 4, 7: 5, 8: 4, 9: 4, 10: 5, 11: 4, 12: 5 };
export const MONTH_WEEK_START: Record<number, number> = { 1: 1, 2: 6, 3: 10, 4: 14, 5: 19, 6: 23, 7: 27, 8: 32, 9: 36, 10: 40, 11: 45, 12: 49 };

// (월, N차) → ISO 주차번호. 예: (4, 5) → 18.
export const wOf = (m: number, n: number) => (MONTH_WEEK_START[m] ?? 0) + n - 1;

// period_id → 회차 라벨. 'YYYY-MM-N'(N=차) → 'M월 W##' / 'YYYY-MM' → 'M월' / 그 외 원문.
export function periodLabelW(id?: string | null): string {
  const w = (id || '').match(/^\d{4}-(\d{1,2})-(\d+)$/);
  if (w) { const m = Number(w[1]); return `${m}월 W${wOf(m, Number(w[2]))}`; }
  const mm = (id || '').match(/^\d{4}-(\d{1,2})$/);
  if (mm) return `${Number(mm[1])}월`;
  return id || '';
}
