'use client';

import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Loader2, ChevronRight, ChevronDown, AlertTriangle } from 'lucide-react';
import {
  Bar, Cell, ComposedChart, Line, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

import PageHeader from '@/components/layout/PageHeader';
import { lgDataService, type LgMasterDetail, type LgDetailItem, type LgPerf, type LgMonthCell, type LgMasterTable, type LgTableCell, type LgMasterChartPoint, type LgAreaTable, type LgAreaRow, type LgAreaWeek, type LgLatestStatus } from '@/services/lgDataService';
import { areaLabel, DERIVED } from '@/config/areas';

// 음수 = 회계식 세모(△) 표기 (양수 그대로). 빨간색은 셀 className 에서.
const tri = (s: string, neg: boolean) => (neg ? `△${s}` : s);
// ── 숫자 표시 공통 규칙 (표·카드·요약·그래프 전부 동일) ──
//  금액: 정수 반올림 + 콤마. 단 |값|이 1 미만(0 제외)이면 소수 1자리(2번째 자리 반올림). 음수 → △(색은 className).
//  비율: 소수 1자리 %. 목표 대비 차이(KPI)만 부호 없이 ↑/↓+색(fmtDiff).
const fmtAmt = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '–';
  const neg = v < 0, abs = Math.abs(v);
  const s = (abs > 0 && abs < 1)
    ? abs.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    : Math.round(abs).toLocaleString();
  return tri(s, neg);
};
// 비율(%) — 값은 이미 퍼센트(예: 85.7). 소수 1자리 + 천단위 콤마(1,044.0%). 음수 → △.
const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined ? '–'
    : tri(`${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`, v < 0);
// 그래프 축 눈금 — 표/카드와 달리 음수는 부호(−) + 콤마(△ 아님). 색은 축 fill 설정 유지(음수라고 색 안 바꿈).
const axisTick = (v: number | string) => Number(v).toLocaleString();

// 그래프 마우스오버(툴팁) — 항목 순서·색을 규칙대로 커스텀.
//  실적: 목표 초과=녹 / 미달=빨강 / 동일=검정 (음수라도 초과면 △+녹 — fmtAmt 가 △ 처리).
//  달성률: 100↑ 녹 / 95~100 주황 / <95 빨강 (음수인데 |값|≥100 이면 △+녹 — 절감형).
//  순서: 전체=목표·실적(전체)·달성률(전체)·실적(H제외)·달성률(H제외) / 개별=목표·실적·달성률.
function ChartTooltip({ active, payload, label, master }: {
  active?: boolean; payload?: { payload?: Record<string, number | null> }[]; label?: string; master?: boolean;
}) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0]?.payload ?? {};
  const amtCls = (a?: number | null, t?: number | null) =>
    a == null || t == null ? 'text-slate-600'
      : a - t > 0 ? 'text-emerald-600' : a - t < 0 ? 'text-rose-600' : 'text-slate-900';
  const rateCls = (r?: number | null) =>
    r == null ? 'text-slate-600'
      : (r < 0 && Math.abs(r) >= 100) ? 'text-emerald-600'   // 절감형: 음수지만 100%↑ 달성
        : r >= 100 ? 'text-emerald-600' : r >= 95 ? 'text-amber-600' : 'text-rose-600';
  const rows = master ? [
    { k: '목표', v: fmtAmt(d['목표']), cls: 'text-slate-600' },
    { k: '실적(전체)', v: fmtAmt(d['실적(전체)']), cls: amtCls(d['실적(전체)'], d['목표']) },
    { k: '달성률(전체)', v: fmtPct(d['달성률(전체)']), cls: rateCls(d['달성률(전체)']) },
    { k: '실적(H제외)', v: fmtAmt(d['실적(H제외)']), cls: amtCls(d['실적(H제외)'], d['목표']) },
    { k: '달성률(H제외)', v: fmtPct(d['달성률(H제외)']), cls: rateCls(d['달성률(H제외)']) },
  ] : [
    { k: '목표', v: fmtAmt(d['목표']), cls: 'text-slate-600' },
    { k: '실적', v: fmtAmt(d['실적']), cls: amtCls(d['실적'], d['목표']) },
    { k: '달성률', v: fmtPct(d['달성률']), cls: rateCls(d['달성률']) },
  ];
  return (
    <div className="rounded-lg bg-white border border-slate-200 shadow-md px-3 py-2 text-xs min-w-[150px]">
      <div className="font-semibold text-slate-700 mb-1">{label}</div>
      {rows.map((r) => (
        <div key={r.k} className="flex items-center justify-between gap-4">
          <span className="text-slate-500">{r.k}</span>
          <span className={`tabular-nums font-medium ${r.cls}`}>{r.v}</span>
        </div>
      ))}
    </div>
  );
}
// 목표 대비 차이 — 부호(+/-) 없이 절댓값만(방향은 색+화살표로 표시). 목표=실적(차이 0)이면 검은 하이픈.
const fmtDiff = (v: number | null | undefined) =>
  v === null || v === undefined ? '–'
    : Math.round(v) === 0 ? '-'
      : Math.round(Math.abs(v)).toLocaleString();
// ── 잠정(공식 월계 미도착 → 주차 기준) 공통 표시 ── 표·카드·그래프 모두 동일 신호.
// 잠정 ※ — 마우스 올리면 실적관리 상태 호버와 같은 스타일 카드(표 셀·요약 카드 둘 다 적용).
const ProvMark = () => (
  <sup className="relative group text-amber-500 font-bold cursor-help ml-0.5">
    ※
    <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1 z-50 w-[230px] text-left font-normal normal-case align-baseline
      opacity-0 invisible translate-y-1 group-hover:opacity-100 group-hover:visible group-hover:translate-y-0 transition-all duration-150 ease-out
      rounded-lg bg-white ring-1 ring-amber-200 shadow-[0_10px_28px_-8px_rgba(15,23,42,0.22)]">
      <span className="flex items-start gap-1.5 px-3 py-2 text-[10.5px] leading-snug text-slate-600">
        <span className="mt-[3px] w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0" />
        <span className="min-w-0 break-keep whitespace-normal"><b className="text-amber-700">공식 월계(월 전체실적) 미도착</b> · 주차 기준 잠정값 (도착 시 자동 확정)</span>
      </span>
    </span>
  </sup>
);
const ProvNote = ({ inset }: { inset?: boolean }) => (
  <div className={`text-[11px] text-amber-600 ${inset ? 'px-4 py-2 bg-amber-50/60 border-t border-amber-100' : 'mt-2'}`}>
    ※ 공식 월계(월 전체실적) 미도착 → <b>주차 기준 잠정값</b>. 월계 도착 시 자동 확정.
  </div>
);
// 달성률 색 기준 (LG 지정): 100%↑ 녹색 / 95~100% 주황 / 95%↓ 빨강. 카드·표 달성률 공통.
function rateClass(r: number | null | undefined): string {
  if (r === null || r === undefined) return 'text-slate-300';
  if (r >= 100) return 'text-emerald-600 font-semibold';
  if (r >= 95) return 'text-amber-600 font-medium';
  return 'text-rose-600 font-semibold';
}
// 달성률 → 카드 tone (rateClass 와 같은 기준).
function rateTone(r: number | null | undefined): 'up' | 'orange' | 'down' | undefined {
  if (r === null || r === undefined) return undefined;
  return r >= 100 ? 'up' : r >= 95 ? 'orange' : 'down';
}
// 달성률 셀 배경(신호등) — 달성 셀에만. 그래프 음영(노랑 amber)과 구분되게 톤 분리.
function rateBg(r: number | null | undefined): string {
  if (r === null || r === undefined) return '';
  if (r >= 100) return 'bg-emerald-100';
  if (r >= 95) return 'bg-orange-100';
  return 'bg-rose-100';
}
// 잠정(예측치) 구간 점선 — 달성률 시리즈를 확정(__s 실선)/잠정(__d 점선)으로 분리.
//   경계의 '확정' 점은 양쪽(__s·__d)에 둬서 실선↔점선이 끊김 없이 이어진다. (잠정 막대 연한색과 짝)
function provDash<T extends Record<string, unknown>>(data: T[], pairs: [string, string][]): T[] {
  return data.map((d, i) => {
    const out: Record<string, unknown> = { ...d };
    for (const [vk, pk] of pairs) {
      const prov = !!d[pk];
      const nextProv = i < data.length - 1 && !!data[i + 1][pk];
      out[`${vk}__s`] = prov ? null : d[vk];          // 확정(실선)
      out[`${vk}__d`] = prov || nextProv ? d[vk] : null;  // 잠정(점선) + 직전 확정점(연결)
    }
    return out as T;
  });
}

type Mode = 'cum' | 'month' | 'quarter';
const modeLabel = (m: Mode) => (m === 'cum' ? '누적' : m === 'quarter' ? '분기' : '월별');
const QMONTHS = (q: number) => [q * 3 - 2, q * 3 - 1, q * 3];   // 분기 → 그 3개월 (Q1=1·2·3)
const Q_OF = (m: number) => Math.ceil(m / 3);                   // 월 → 분기
const ALL = '전체';   // 월별 주차 개수/시작 ISO·wOf 는 config/periods (단일 소스)

// 하위 top3(목표 미달 영향·달성율 최저) — **현재 모드 기준**으로 값 산출(KPI 카드와 동일 기준).
//   누적 = 1~현재월 합 / 월별 = 당월 / 분기 = 현재분기(목표 3개월 합·실적 현재월까지).
type RankCells = Record<string, { 목표?: number | null; 실적?: number | null } | undefined>;
function modeVal(cells: RankCells, k: '목표' | '실적', mode: Mode, curMonth: number, months: number[]): number {
  const g = (m: number) => cells[String(m)]?.[k] ?? 0;
  if (mode === 'month') return g(curMonth);
  if (mode === 'quarter') {
    // 목표 = 그 분기 3개월 전부 / 실적 = 현재월까지 (KPI 카드와 동일). 미도래 월 실적 제외.
    return QMONTHS(Q_OF(curMonth)).reduce((s, m) => s + (k === '실적' && m > curMonth ? 0 : g(m)), 0);
  }
  return months.filter((m) => m <= curMonth).reduce((s, m) => s + g(m), 0);   // 누적
}
function rankTop3(entries: { label: string; cells: RankCells }[], mode: Mode, curMonth: number, months: number[]) {
  const ranked = entries.map((e) => {
    const t = modeVal(e.cells, '목표', mode, curMonth, months);
    const a = modeVal(e.cells, '실적', mode, curMonth, months);
    return { label: e.label, 목표: t, 실적: a, 부족: t - a, 달성률: t ? Number(((a / t) * 100).toFixed(1)) : null };
  });
  return {
    shortfall: ranked.filter((r) => r.부족 > 0).sort((x, y) => y.부족 - x.부족).slice(0, 3),
    lowest: ranked.filter((r) => r.달성률 != null).sort((x, y) => (x.달성률 ?? 0) - (y.달성률 ?? 0)).slice(0, 3),
  };
}

// 요약 리스트(목표 미달 영향 / 달성율 최저) 행 빌더 — 색·화살표·하위표기 규칙 캡슐화.
type RankRow = { label: string; 목표: number; 실적: number; 부족: number; 달성률: number | null };
// 목표 미달 영향 — 값=차이(실적−목표): 부호 없이 |값|+화살표, 색=방향(대시보드 목표 대비 차이와 동일).
//   미달 ↓빨강 / 초과 ↑녹색 / 동일 검정. 하위 = 목표 / 실적 / 달성율.
const shortfallRow = (r: RankRow) => {
  const d = Math.round(r.실적 - r.목표);
  return {
    항목: r.label,
    main: fmtDiff(r.실적 - r.목표),
    arrow: d > 0 ? '↑' : d < 0 ? '↓' : undefined,
    mainCls: d > 0 ? 'text-emerald-600 font-bold' : d < 0 ? 'text-rose-600 font-bold' : 'text-slate-900 font-bold',
    sub: `목표 : ${fmtAmt(r.목표)} / 실적 : ${fmtAmt(r.실적)} / 달성율 ${fmtPct(r.달성률)}`,
  };
};
// 목표 달성율 최저 — 값=달성률(음수 △), 색=신호등(rateClass), 하위 = 목표 먼저 / 실적.
const lowestRow = (r: RankRow) => ({
  항목: r.label,
  main: fmtPct(r.달성률),
  mainCls: rateClass(r.달성률),
  sub: `목표 ${fmtAmt(r.목표)} / 실적 ${fmtAmt(r.실적)}`,
});

// 하위 top3(미달/최저) 순위 대상 = 각 항목의 **기여 지표 말단 leaf**.
//   기여 지표: 대부분 '개선금액', 재료비=VI금액, 투자비=저감금액. (LG 스펙)
//   말단 leaf = 그 지표를 포함하는 행 중 **더 깊은 행이 없는(터미널)** 것 + 집계 컨테이너 제외.
const CONTRIB_METRIC: Record<string, string> = {
  material_cost: 'VI 금액',
  investment: '저감금액',
};
// 집계 컨테이너 세그먼트(합계/전체/키친솔루션/제품1+제품2/외화($)/계) — 개별 기여가 아니라 합이라 제외.
const SUM_SEG = /합계|키친솔루션|전체|Total|지역 합계|\+|\$|^계$/;
// area_table 행들에서 기여 지표 말단 leaf 추출 → {label, cells} (rankTop3 소스).
function contribLeaves(area: string, rows: LgAreaRow[]): { label: string; cells: RankCells }[] {
  const contrib = CONTRIB_METRIC[area] ?? '개선금액';
  const paths = rows.map((r) => r.부서경로);
  const isTerm = (p: string) => !paths.some((q) => q !== p && q.startsWith(p + ' / '));
  return rows
    .filter((r) => !r.is_rate
      && r.부서경로.split(' / ').some((s) => s.includes(contrib))       // 기여 지표 포함
      && !r.부서경로.split(' / ').some((s) => SUM_SEG.test(s))          // 집계 컨테이너 제외
      && isTerm(r.부서경로))                                            // 더 깊은 행 없음
    .map((r) => ({
      // 라벨 = 기여 지표 세그먼트 뺀 나머지(제품/지역/부문 등 구분되게). 비면 전체 경로.
      label: r.부서경로.split(' / ').filter((s) => !s.includes(contrib)).join(' / ') || r.부서경로,
      cells: r.cells as unknown as RankCells,
    }));
}

// 보고서 본문 — /reports(기본)와 /simulation(sim=변경적용 항목들) 이 공유. 같은 화면 구성 보장.
//   sim         : 변경 적용할 항목 슬러그 목록(시뮬). 빈/생략 = 현재. 항목별 델타로 즉석 조립.
//   title       : PageHeader 제목.
//   headerExtra : 선택 표시줄 옆 추가 컨트롤(시뮬 체크박스 등).
export function ReportView({ sim, title = '보고서 운영', headerExtra }: {
  sim?: string[]; title?: string; headerExtra?: ReactNode;
}) {
  const simKey = (sim ?? []).join(',');   // 의존성 안정 키(배열 identity 회피)
  const [year, setYear] = useState('2026');
  const [latestMonth, setLatestMonth] = useState(0);
  const [month, setMonth] = useState(0);            // 선택 월 (1~최신)
  const [week, setWeek] = useState(0);              // 선택 주차 = **ISO 주차번호**(0=그 달 전체). 데이터에 있는 주차만.
  const [presentWeeks, setPresentWeeks] = useState<Record<number, number[]>>({});  // 월별 실제 데이터 있는 ISO 주차(드롭다운 소스)
  const [data, setData] = useState<LgMasterDetail | null>(null);
  const [table, setTable] = useState<LgMasterTable | null>(null);
  const [areaTbl, setAreaTbl] = useState<LgAreaTable | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string>(ALL);
  const [mode, setMode] = useState<Mode>('cum');    // cum=누적 현황 / month=월별 현황
  const [status, setStatus] = useState<LgLatestStatus | null>(null);  // 상단 항목별 현황 = 제출 상태(11개)

  // 월+주차 → 조회 period_id. 주차 선택 시 '2026-05-W18'(ISO 직접, 경계주 대응), 전체면 '2026-05'.
  const periodId = useMemo(() => {
    if (!month) return '';
    const mm = String(month).padStart(2, '0');
    return week ? `${year}-${mm}-W${week}` : `${year}-${mm}`;
  }, [year, month, week]);

  // 그 달 선택 가능한 ISO 주차(데이터 기준). 없으면 빈 배열 = 주차 드롭다운 없이 '전체'만.
  const weekOpts = presentWeeks[month] ?? [];

  useEffect(() => { lgDataService.status().then(setStatus).catch(() => setStatus(null)); }, []);

  useEffect(() => {
    // 드롭다운 월 = **데이터 기준 최신월**(폴더 이름 아님 → 월 진행 시 따라감). 기본 = 최신월·그 달 최신 주차.
    lgDataService.periodsInfo().then(({ periods: ps, latestMonth, year: yr, presentWeeks: pw }) => {
      let lm = latestMonth ?? undefined;
      if (lm == null) {   // 폴백 — 데이터 월 없으면 폴더 이름에서
        const m = ps[ps.length - 1]?.match(/^(\d{4})-(\d{1,2})/);
        if (m) { lm = Number(m[2]); yr = m[1]; }
      }
      if (lm == null) return;
      setYear(yr);
      setLatestMonth(lm);
      setPresentWeeks(pw ?? {});
      setMonth(lm);
      const wks = (pw ?? {})[lm] ?? [];
      setWeek(wks.length ? wks[wks.length - 1] : 0);   // 기본 = 그 달 최신 ISO 주차(데이터 기준), 없으면 전체
    }).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!periodId) return;  // periodId 정해지기 전엔 fetch 안 함 (미래월 요청 방지)
    setLoading(true);
    try {
      setData(await lgDataService.masterDetail(periodId, sim));
      try { setTable(await lgDataService.masterTable(periodId, sim)); } catch { setTable(null); }
    } catch { setData(null); }
    finally { setLoading(false); }
  }, [periodId, simKey]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  // 개별 Area → 그 시트를 엑셀 그대로 재현한 테이블(합계/소계/Rate 포함) 가져오기
  useEffect(() => {
    if (selected === ALL || !periodId) { setAreaTbl(null); return; }
    let alive = true;
    lgDataService.areaTable(periodId, selected, sim)
      .then((p) => alive && setAreaTbl(p)).catch(() => alive && setAreaTbl(null));
    return () => { alive = false; };
  }, [selected, periodId, simKey]);   // eslint-disable-line react-hooks/exhaustive-deps

  const items = data?.items ?? [];
  const months = data?.months ?? [];
  const curMonth = data?.current_month ?? (months[months.length - 1] ?? 0);

  // "전체" = 비파생·비component 항목 합산 (Master, 고정비제외). 누적/당월은 백엔드 summary 사용.
  // component(고정비 하위)는 고정비 롤업과 이중계산되므로 합산에서 제외.
  const aggItem: LgDetailItem | null = useMemo(() => {
    if (!data?.summary) return null;
    const live = items.filter((i) => !i.derived && !i.component);
    const mcells: Record<string, LgMonthCell> = {};
    for (const m of months) {
      let t = 0, a = 0, prov = false; const wk = new Map<string, { 목표: number; 실적: number }>();
      for (const it of live) {
        const c = it.months[String(m)]; if (!c) continue;
        if (c.목표 != null) t += c.목표; if (c.실적 != null) a += c.실적;
        if (c.잠정) prov = true;
        for (const w of c.weeks) {
          const cur = wk.get(w.주차) || { 목표: 0, 실적: 0 };
          if (w.목표 != null) cur.목표 += w.목표; if (w.실적 != null) cur.실적 += w.실적;
          wk.set(w.주차, cur);
        }
      }
      const weeks = Array.from(wk.entries())
        .map(([주차, v]) => ({ 주차, 목표: v.목표, 실적: v.실적, 달성률: v.목표 ? Number(((v.실적 / v.목표) * 100).toFixed(1)) : null }))
        .sort((x, y) => Number(x.주차.replace(/\D/g, '')) - Number(y.주차.replace(/\D/g, '')));
      mcells[String(m)] = { 목표: t, 실적: a, 달성률: t ? Number(((a / t) * 100).toFixed(1)) : null, 잠정: prov, weeks };
    }
    return { 항목: ALL, derived: false, months: mcells, 누적: data.summary.누적, 당월: data.summary.당월 };
  }, [data, items, months]);

  const sel = selected === ALL ? aggItem : (items.find((i) => i.항목 === selected) || null);

  // 셀 단위 누락 마킹 — 선택 시점(연초~그 차, ISO ≤ cutoff)까지 들어온 '부분 구멍'(받은 주차 안 일부 leaf 실적 빔).
  // status(latest_status)에 항목별 incomplete 가 실려 옴 → 표시 기간으로 필터.
  const cutoffIso = week;   // week = ISO 주차번호(0=전체). 데이터 기준이라 wOf 매핑 불필요.
  // 항목별 '현재 데이터 위치' — 빨간 테두리 대상. 마감 도착(latest='N월 마감')=그 달 월계 컬럼,
  // 진행 중(latest='N월 W##')=그 주차 컬럼. (item 마다 위치가 달라서 항목 단위로 잡음)
  const areaRed = useMemo(() => {
    const m = new Map<string, { month: number; week: number }>();
    for (const it of status?.items ?? []) {
      const c = it.latest_label.match(/^(\d+)월 마감$/);
      const w = it.latest_label.match(/(\d+)월 W(\d+)/);
      m.set(it.항목, c ? { month: Number(c[1]), week: 0 } : w ? { month: 0, week: Number(w[2]) } : { month: 0, week: 0 });
    }
    return m;
  }, [status]);
  const selLatest = (selected !== ALL && areaRed.get(selected)) || { month: 0, week: 0 };
  // 전체 표 빨간 테두리 = 전체 현재(마감 시작이면 그 달 월계, 아니면 현재 주차).
  const gMonth = status?.current_close ? (status.current_month ?? 0) : 0;
  const gWeek = status?.current_close ? 0 : (status?.current_week ?? 0);
  const incOf = useCallback((area: string) => {
    const it = status?.items.find((x) => x.항목 === area);
    const cells = (it?.incomplete ?? []).filter((c) => !cutoffIso || c.주차 <= cutoffIso);
    // 어디가 빠졌는지 명확히 — "2월 3차: 제품1/유상수익, 제품2/유상수익" (3개 초과는 '외 N')
    return {
      n: cells.reduce((s, c) => s + c.n, 0),
      labels: cells.map((c) => `${c.label}: ${c.leaves.slice(0, 3).join(', ')}${c.leaves.length > 3 ? ` 외 ${c.leaves.length - 3}` : ''}`),
    };
  }, [status, cutoffIso]);

  // 개별 Area 테이블 셀 하이라이트용 — 선택 항목의 빠진 (부서경로|ISO주차) 집합 (표시 기간 한정)
  const incCellSet = useMemo(() => {
    const s = new Set<string>();
    if (selected === ALL) return s;
    const it = status?.items.find((x) => x.항목 === selected);
    (it?.incomplete ?? []).filter((c) => !cutoffIso || c.주차 <= cutoffIso)
      .forEach((c) => c.leaves.forEach((lf) => s.add(`${lf}|${c.주차}`)));
    return s;
  }, [status, selected, cutoffIso]);

  return (
    <div className="px-10 py-8 max-w-[1200px] mx-auto">
      <PageHeader title={title} />
      {headerExtra}

      {/* 월 + 주차 선택 (연초~그 시점 누적) */}
      <div className="mb-5 flex items-center gap-2">
        <select value={month} onChange={(e) => {
            const m = Number(e.target.value);
            setMonth(m);
            const wks = presentWeeks[m] ?? [];
            setWeek(wks.length ? wks[wks.length - 1] : 0);   // 그 달 최신 ISO 주차(데이터), 없으면 전체
          }}
          className="px-2.5 py-1.5 border border-slate-200 rounded-md text-sm bg-white text-slate-700">
          {Array.from({ length: latestMonth }, (_, i) => i + 1).map((m) => (
            <option key={m} value={m}>{m}월</option>
          ))}
        </select>
        {/* 주차 = **데이터에 실제 있는 ISO 주차만**(config 고정 차수 아님). 없으면 '전체'만. */}
        <select value={week} onChange={(e) => setWeek(Number(e.target.value))}
          className="px-2.5 py-1.5 border border-slate-200 rounded-md text-sm bg-white text-slate-700">
          {weekOpts.length === 0 && <option value={0}>전체</option>}
          {weekOpts.map((iso) => (
            <option key={iso} value={iso}>W{iso}</option>
          ))}
        </select>
        {loading && <Loader2 className="w-4 h-4 animate-spin text-slate-400" />}
        {/* 누적 / 월별 / 분기 현황 토글 */}
        <div className="ml-auto inline-flex items-center gap-1 p-1 rounded-lg bg-slate-100 text-sm">
          {([['cum', '누적 현황'], ['month', '월별 현황'], ['quarter', '분기 현황']] as [Mode, string][]).map(([k, label]) => (
            <button key={k} onClick={() => setMode(k)}
              className={`px-3 py-1.5 rounded-md font-medium transition ${
                mode === k ? 'bg-white text-primary-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* 항목별 현황 — 11개 제출 상태 (1줄, 제출 여부 색) */}
      <section className="bg-white border border-slate-200 rounded-xl shadow-card p-5 mb-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-900">항목별 현황 <span className="text-[11px] font-normal text-slate-400">· 제출 여부</span></h2>
          <div className="flex items-center gap-3 text-[11px] text-slate-500">
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />제출 완료</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-rose-500" />미제출·오류</span>
          </div>
        </div>
        {!status ? (
          <div className="text-xs text-slate-400">불러오는 중…</div>
        ) : (
          <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-1.5">
            {status.items.filter((it) => !it.derived).map((it) => {
              const ok = it.state === '입력완료' || it.state === '재제출완료';
              const hasGap = !!it.gap_summary && it.gap_summary !== '—';
              return (
                <div key={it.항목} className="relative group">
                  <span
                    className={`inline-flex items-center justify-center gap-1.5 w-full px-2 py-1 rounded-md border text-xs font-medium cursor-help ${
                      ok ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-rose-50 text-rose-700 border-rose-200'}`}>
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${ok ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                    <span className="truncate">{areaLabel(it.항목)}</span>
                    {(it.incomplete_cells ?? 0) > 0 && <AlertTriangle className="w-3 h-3 flex-shrink-0 text-amber-500" />}
                  </span>
                  {/* 호버 카드 — 상태·최신 시점·이슈·빠진 데이터 (실적관리 상태 호버와 동일 스타일) */}
                  <span className={`pointer-events-none absolute top-full left-1/2 -translate-x-1/2 mt-1.5 z-50 w-[240px] text-left
                    opacity-0 invisible translate-y-1 group-hover:opacity-100 group-hover:visible group-hover:translate-y-0 transition-all duration-150 ease-out
                    rounded-lg bg-white ring-1 shadow-[0_10px_28px_-8px_rgba(15,23,42,0.22)] ${ok ? 'ring-emerald-200' : 'ring-rose-200'}`}>
                    <span className="block px-3 py-2 text-[10.5px] leading-snug">
                      <span className="flex items-center gap-1.5 font-semibold text-slate-800">
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${ok ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                        {areaLabel(it.항목)} · <span className={ok ? 'text-emerald-700' : 'text-rose-700'}>{it.state}</span>
                      </span>
                      <span className="block mt-1 text-slate-500">최신 시점: {it.latest_label}</span>
                      {it.issues.length > 0 && (
                        <span className="block mt-1.5 space-y-0.5">
                          {it.issues.map((m, i) => (
                            <span key={i} className="flex items-start gap-1.5 text-slate-600">
                              <span className="mt-[3px] w-1 h-1 rounded-full bg-rose-400 flex-shrink-0" />
                              <span className="min-w-0 break-keep whitespace-normal">{m}</span>
                            </span>
                          ))}
                        </span>
                      )}
                      {hasGap && (
                        <span className="block mt-1.5 text-rose-600"><b>빠진 데이터:</b> {it.gap_summary}</span>
                      )}
                      {ok && it.issues.length === 0 && (
                        <span className="block mt-1 text-emerald-600">제출 완료 · 빠진 데이터 없음</span>
                      )}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* 선택 — 항목 탭(균등 그리드) + 보기모드 토글, 같은 선상 */}
      {items.length > 0 && (
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          {/* 항목 선택 — 회색 음영 패널 위 균등 그리드(흰 버튼이 떠 보임) */}
          <div className="flex-1 min-w-0 grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-6 gap-2 bg-slate-200 p-2 rounded-lg">
            <button onClick={() => setSelected(ALL)} title="전체"
              className={`px-2 py-1.5 rounded-md border text-sm font-medium text-center truncate transition ${
                selected === ALL
                  ? 'bg-primary-600 text-white border-primary-600 shadow'
                  : 'bg-white text-slate-600 border-slate-200 shadow-sm hover:bg-slate-50 hover:border-slate-300'}`}>
              전체
            </button>
            {items.filter((i) => !i.derived || i.항목 === DERIVED).map((it) => (
              <button key={it.항목} onClick={() => setSelected(it.항목)} title={areaLabel(it.항목)}
                className={`px-2 py-1.5 rounded-md border text-sm font-medium text-center truncate transition ${
                  selected === it.항목
                    ? 'bg-primary-600 text-white border-primary-600 shadow'
                    : 'bg-white text-slate-600 border-slate-200 shadow-sm hover:bg-slate-50 hover:border-slate-300'}`}>
                {areaLabel(it.항목)}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 실적 일부 누락 마킹 — 받은 주차 안에 실적 빈 셀이 있는 항목(합계·달성률 과소집계 주의) */}
      {(() => {
        const entries = (selected === ALL
          ? items.filter((i) => !i.derived || i.항목 === DERIVED).map((i) => i.항목)
          : [selected]
        ).map((a) => ({ area: a, ...incOf(a) })).filter((e) => e.n > 0);
        if (!entries.length) return null;
        return (
          <div className="mb-5 flex items-start gap-2 px-4 py-3 rounded-lg border border-amber-300 bg-amber-50 text-amber-800">
            <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <div className="text-[12px] leading-relaxed">
              <b>실적 일부 누락</b> — 아래 항목은 받은 주차 안에 실적이 빈 셀이 있어 <b>합계·달성률이 과소 집계</b>될 수 있습니다. (빈 셀은 0으로 합산됨)
              <ul className="mt-1 space-y-0.5">
                {entries.map((e) => (
                  <li key={e.area}>· <b>{areaLabel(e.area)}</b>: {e.labels.join(', ')}</li>
                ))}
              </ul>
            </div>
          </div>
        );
      })()}

      {/* 상세 — 전체: Master / 개별 Area: 세부 항목 */}
      {selected === ALL ? (
        sel && (
          <>
            <ItemDetail item={sel} months={months} mode={mode} curMonth={curMonth} curWeek={gWeek} curCloseMonth={gMonth}
              masterChart={data?.summary?.chart ?? null} masterTable={table} weekItems={items} />
            {items.length > 0 && (() => {
              // 전체 하위 top3 = 8개 리포트 항목을 **현재 모드 기준**(누적/월별/분기)으로 순위 (KPI 카드와 동일 기준).
              const { shortfall, lowest } = rankTop3(
                items.map((it) => ({ label: areaLabel(it.항목), cells: it.months })), mode, curMonth, months);
              return (
                <div className="mt-5 grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <SummaryList
                    title={`목표 미달 영향 (${modeLabel(mode)}·금액)`}
                    hint="목표 대비 부족분(억원)이 큰 항목 — 전체 미달에 가장 크게 기여"
                    rows={shortfall.map(shortfallRow)}
                  />
                  <SummaryList
                    title={`목표 달성율 최저 (${modeLabel(mode)}·비율)`}
                    hint="달성율(%)이 낮은 항목 — 비율로 가장 부진"
                    rows={lowest.map(lowestRow)}
                  />
                </div>
              );
            })()}
          </>
        )
      ) : (
        sel && <AreaView area={selected} item={sel}
          months={months} mode={mode} curMonth={curMonth} curWeek={selLatest.week} curCloseMonth={selLatest.month} areaTbl={areaTbl} incCells={incCellSet} />
      )}
    </div>
  );
}


function ItemDetail({ item, months, mode, curMonth, curWeek, curCloseMonth, masterChart, masterTable }: {
  item: LgDetailItem; months: number[]; mode: Mode; curMonth: number; curWeek: number; curCloseMonth: number;
  masterChart: LgMasterChartPoint[] | null;
  masterTable: LgMasterTable | null;
  weekItems: LgDetailItem[];
}) {
  const [openMonth, setOpenMonth] = useState<Set<number>>(new Set());
  const toggle = (m: number) => setOpenMonth((p) => { const n = new Set(p); n.has(m) ? n.delete(m) : n.add(m); return n; });

  // 전체 카드 = 그래프와 동일 소스(masterChart=전체 g_full). 그래프 빨강(전체)과 카드 일치.
  const perf: LgPerf = useMemo(() => {
    const src = masterChart ?? [];
    const mk = (t: number, a: number): LgPerf => ({ 목표: t, 실적: a, 차이: a - t, 달성률: t ? Number(((a / t) * 100).toFixed(1)) : null });
    if (mode === 'quarter') {
      const qms = QMONTHS(Q_OF(curMonth));
      let t = 0, a = 0;
      src.forEach((c) => { if (qms.includes(c.월)) { t += c.목표; if (c.월 <= curMonth) a += c.실적; } });
      return mk(t, a);
    }
    if (mode === 'cum') {
      let t = 0, a = 0;
      src.forEach((c) => { if (c.월 <= curMonth) { t += c.목표; a += c.실적; } });
      return mk(t, a);
    }
    const c = src.find((x) => x.월 === curMonth);
    return mk(c?.목표 ?? 0, c?.실적 ?? 0);
  }, [mode, masterChart, curMonth]);
  // 잠정 여부 (전체 실적) — 표시 기간에 공식 월계 미도착 달이 섞였나
  const perfProv = useMemo(() => {
    const src = masterChart ?? [];
    if (mode === 'quarter') { const qms = QMONTHS(Q_OF(curMonth)); return src.some((c) => qms.includes(c.월) && c.월 <= curMonth && c.잠정); }
    if (mode === 'cum') return src.some((c) => c.월 <= curMonth && c.잠정);
    return !!src.find((x) => x.월 === curMonth)?.잠정;
  }, [mode, masterChart, curMonth]);
  const curCell = item.months[String(curMonth)];
  const period = mode === 'cum' ? '누적' : mode === 'quarter' ? '분기' : '당월';
  // 전체(Master) → H포함/H제외 멀티계열 차트 (전체현황=월별 / 당월=그 달 주차별)
  const isMaster = masterChart != null;

  const chart = useMemo(() => {
    if (mode === 'cum') {
      // 목표는 1~12월 쭉(없으면 0), 실적/달성률은 현재월까지만(미래월 null → 막대 안 그림)
      return months.map((m) => {
        const c = item.months[String(m)];
        const future = m > curMonth;
        return { x: `${m}월`, 목표: c?.목표 ?? 0, 실적: future ? null : (c?.실적 ?? 0), 달성률: future ? null : (c?.달성률 ?? 0), 잠정: future ? false : !!c?.잠정 };
      });
    }
    return (curCell?.weeks ?? []).map((w) => ({ x: w.주차, 목표: w.목표 ?? 0, 실적: w.실적 ?? 0, 달성률: w.달성률 ?? 0, 잠정: false }));
  }, [mode, months, item, curCell, curMonth]);

  // 전체(Master) 멀티계열 — 누적 현황 = 연초~그 달 러닝합(전체/H제외 각각 누적, 달성률=누적÷누적)
  //   / 월별 현황 = 각 달 자기 수치. 둘 다 x축=월(목표 12월까지·실적/달성률 현재월까지). (개별 Area 와 동일 로직)
  const masterData = useMemo(() => {
    const src = masterChart ?? [];
    if (mode === 'cum') {
      let t = 0, te = 0, a = 0, ae = 0, pf = false, pe = false;
      return src.map((c) => {
        const future = c.월 > curMonth;
        t += c.목표; te += c.목표_ex;
        if (!future) { a += c.실적; ae += c.실적_ex; pf = pf || !!c.잠정; pe = pe || !!c.잠정_ex; }
        return {
          x: `${c.월}월`, 목표: t,
          '실적(전체)': future ? null : a, '실적(H제외)': future ? null : ae,
          '달성률(전체)': future ? null : (t ? Number(((a / t) * 100).toFixed(1)) : null),
          '달성률(H제외)': future ? null : (te ? Number(((ae / te) * 100).toFixed(1)) : null),
          잠정: future ? false : pf, 잠정_ex: future ? false : pe,
        };
      });
    }
    if (mode === 'quarter') {
      // 분기 = 그 3개월 합 (전체/H제외 각각). 실적은 현재월까지 든 달만.
      return [1, 2, 3, 4].map((q) => {
        const ms = QMONTHS(q);
        let t = 0, te = 0, a = 0, ae = 0, pf = false, pe = false;
        ms.forEach((mo) => {
          const c = src.find((x) => x.월 === mo); if (!c) return;
          t += c.목표; te += c.목표_ex;
          if (mo <= curMonth) { a += c.실적; ae += c.실적_ex; pf = pf || !!c.잠정; pe = pe || !!c.잠정_ex; }
        });
        const future = ms[0] > curMonth;
        return {
          x: `${q}분기`, 목표: t,
          '실적(전체)': future ? null : a, '실적(H제외)': future ? null : ae,
          '달성률(전체)': future ? null : (t ? Number(((a / t) * 100).toFixed(1)) : null),
          '달성률(H제외)': future ? null : (te ? Number(((ae / te) * 100).toFixed(1)) : null),
          잠정: future ? false : pf, 잠정_ex: future ? false : pe,
        };
      });
    }
    return src.map((c) => {
      const future = c.월 > curMonth;
      return {
        x: `${c.월}월`, 목표: c.목표,
        '실적(전체)': future ? null : c.실적, '실적(H제외)': future ? null : c.실적_ex,
        '달성률(전체)': future ? null : (c.달성률 ?? 0), '달성률(H제외)': future ? null : (c.달성률_ex ?? 0),
        잠정: future ? false : !!c.잠정, 잠정_ex: future ? false : !!c.잠정_ex,
      };
    });
  }, [masterChart, curMonth, mode]);

  return (
    <div className="space-y-5">
      {/* 요약 카드 — 라벨 명확하게 */}
      <div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Card label={`목표(${period})`} value={fmtAmt(perf.목표)} />
          <Card label={`실적(${period})`} value={fmtAmt(perf.실적)} primary
            tone={perf.실적 != null && perf.실적 < 0 ? 'down' : undefined} prov={perfProv} />
          <Card label={`목표 대비 차이(${period})`} value={fmtDiff(perf.차이)}
            tone={perf.차이 == null ? undefined : Math.round(perf.차이) > 0 ? 'up' : Math.round(perf.차이) < 0 ? 'down' : 'flat'}
            arrow={perf.차이 == null ? undefined : Math.round(perf.차이) > 0 ? '↑' : Math.round(perf.차이) < 0 ? '↓' : undefined} prov={perfProv} />
          <Card label={`목표 대비 달성률(${period})`} value={fmtPct(perf.달성률)}
            tone={rateTone(perf.달성률)} prov={perfProv} />
        </div>
        {perfProv && <ProvNote />}
      </div>

      {/* 그래프 (막대 + 꺾은선) */}
      <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-card">
        <h3 className="font-semibold text-slate-900 text-sm mb-3">
          {areaLabel(item.항목)} · {modeLabel(mode)} 목표 vs 실적
          {isMaster && <span className="text-[11px] font-normal text-slate-400"> · 전체 / H제외 비교</span>}
        </h3>
        <ResponsiveContainer width="100%" height={280}>
          {isMaster ? (
            <ComposedChart data={provDash(masterData, [['달성률(전체)', '잠정'], ['달성률(H제외)', '잠정_ex']])} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="x" tick={{ fontSize: 11, fill: '#64748b' }} />
              <YAxis yAxisId="left" tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={axisTick} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: '#64748b' }} unit="%" domain={[0, 'auto']} tickFormatter={axisTick} />
              <Tooltip content={(p: any) =>
                <ChartTooltip active={p.active} payload={p.payload} label={p.label} master />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey="목표" fill="#94a3b8" radius={[3, 3, 0, 0]} />
              <Bar yAxisId="left" dataKey="실적(전체)" fill="#ef4444" radius={[3, 3, 0, 0]}>
                {masterData.map((d, i) => <Cell key={i} fill={d.잠정 ? '#fca5a5' : '#ef4444'} />)}
              </Bar>
              <Bar yAxisId="left" dataKey="실적(H제외)" fill="#10b981" radius={[3, 3, 0, 0]}>
                {masterData.map((d, i) => <Cell key={i} fill={d.잠정_ex ? '#86efac' : '#10b981'} />)}
              </Bar>
              <Line yAxisId="right" type="monotone" dataKey="달성률(전체)__s" name="달성률(전체)" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
              <Line yAxisId="right" type="monotone" dataKey="달성률(전체)__d" name="달성률(전체)" stroke="#ef4444" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 3 }} legendType="none" connectNulls={false} />
              <Line yAxisId="right" type="monotone" dataKey="달성률(H제외)__s" name="달성률(H제외)" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
              <Line yAxisId="right" type="monotone" dataKey="달성률(H제외)__d" name="달성률(H제외)" stroke="#10b981" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 3 }} legendType="none" connectNulls={false} />
            </ComposedChart>
          ) : (
            <ComposedChart data={provDash(chart, [['달성률', '잠정']])} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="x" tick={{ fontSize: 11, fill: '#64748b' }} />
              <YAxis yAxisId="left" tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={axisTick} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: '#64748b' }} unit="%" domain={[0, 'auto']} tickFormatter={axisTick} />
              <Tooltip content={(p: any) =>
                <ChartTooltip active={p.active} payload={p.payload} label={p.label} />} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey="목표" fill="#cbd5e1" radius={[3, 3, 0, 0]} />
              <Bar yAxisId="left" dataKey="실적" fill="#3b82f6" radius={[3, 3, 0, 0]} />
              <Line yAxisId="right" type="monotone" dataKey="달성률__s" name="달성률" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
              <Line yAxisId="right" type="monotone" dataKey="달성률__d" name="달성률" stroke="#f59e0b" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 3 }} legendType="none" connectNulls={false} />
            </ComposedChart>
          )}
        </ResponsiveContainer>
        {masterData.some((d) => d.잠정 || d.잠정_ex) && (
          <p className="mt-2 text-[11px] text-amber-600">※ 연한 막대 = 공식 월계 미도착, 주차 기준 잠정값 (도착 시 자동 확정)</p>
        )}
      </section>

      {/* 테이블: 전체현황=월별 / 당월=그 달 주차별 — 둘 다 세부 항목까지 (master_table) */}
      {masterTable && masterTable.rows.length > 0 ? (
        <MasterSheetTable table={masterTable} mode={mode} curMonth={curMonth} curWeek={curWeek} curCloseMonth={curCloseMonth} />
      ) : (
        <section className="bg-white border border-slate-200 rounded-xl shadow-card overflow-hidden">
          <div className="px-4 py-2.5 border-b border-slate-100">
            <h3 className="font-semibold text-slate-900 text-sm">
              {areaLabel(item.항목)} · {mode === 'cum' ? '월별 실적 (월 클릭 시 차수)' : `${curMonth}월 차수별 실적`}
            </h3>
          </div>
          <table className="w-full text-sm table-fixed">
            <thead className="bg-slate-50 text-[11px] text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left font-semibold w-[28%]">기간</th>
                <th className="px-4 py-2 text-right font-semibold w-[24%]">목표</th>
                <th className="px-4 py-2 text-right font-semibold w-[24%]">실적</th>
                <th className="px-4 py-2 text-center font-semibold w-[24%]">달성율</th>
              </tr>
            </thead>
            <tbody>
              {mode === 'cum' ? months.map((m) => {
                const c = item.months[String(m)];
                if (!c) return null;
                return <MonthRow key={m} month={m} cell={c} open={openMonth.has(m)} onToggle={() => toggle(m)} />;
              }) : (curCell?.weeks ?? []).map((w) => (
                <tr key={w.주차} className="border-t border-slate-100">
                  <td className="px-4 py-2.5 text-slate-700">{w.주차}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">{fmtAmt(w.목표)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-800 font-medium">{fmtAmt(w.실적)}</td>
                  <td className={`px-4 py-2.5 text-center tabular-nums ${rateClass(w.달성률)}`}>{w.달성률 == null ? '–' : `${w.달성률}%`}</td>
                </tr>
              ))}
              {mode === 'month' && (!curCell || curCell.weeks.length === 0) && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-400 text-xs">{curMonth}월 차수 데이터가 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function MonthRow({ month, cell, open, onToggle }: {
  month: number; cell: LgMonthCell; open: boolean; onToggle: () => void;
}) {
  const hasWeeks = cell.weeks.length > 0;
  return (
    <>
      <tr className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={onToggle}>
        <td className="px-4 py-2.5 font-medium text-slate-800">
          <span className="inline-flex items-center gap-1">
            {hasWeeks ? (open ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />) : <span className="w-3.5" />}
            {month}월
          </span>
        </td>
        <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">{fmtAmt(cell.목표)}</td>
        <td className="px-4 py-2.5 text-right tabular-nums text-slate-800 font-medium">{fmtAmt(cell.실적)}{cell.잠정 && <ProvMark />}</td>
        <td className={`px-4 py-2.5 text-center tabular-nums ${rateClass(cell.달성률)}`}>{cell.달성률 == null ? '–' : `${cell.달성률}%`}</td>
      </tr>
      {open && cell.weeks.map((w) => (
        <tr key={w.주차} className="border-t border-slate-50 bg-slate-50/40 text-xs">
          <td className="px-4 py-1.5 pl-10 text-slate-500">{w.주차}</td>
          <td className="px-4 py-1.5 text-right tabular-nums text-slate-500">{fmtAmt(w.목표)}</td>
          <td className="px-4 py-1.5 text-right tabular-nums text-slate-600">{fmtAmt(w.실적)}</td>
          <td className={`px-4 py-1.5 text-center tabular-nums ${rateClass(w.달성률)}`}>{w.달성률 == null ? '–' : `${w.달성률}%`}</td>
        </tr>
      ))}
    </>
  );
}

// 개별 Area 상세 — headline(대표총계) 목표/실적 막대 + 달성률 꺾은선 + 시트표 + 세부 top3
// 그래프 표시 방식이 확정된 항목만 차트 렌더 — 나머지는 임시 플레이스홀더(추후 LG 협의 후 정의).
// 새 항목 그래프가 정해지면 여기 slug 만 추가하면 됨.
// 항목별 그래프 = 지정 행(부서경로)의 목표/실적. 없는 항목은 플레이스홀더(추후 정의).
// 새 항목 그래프 정해지면 slug→행경로 한 줄 추가하면 됨.
const GRAPH_ROW: Record<string, string> = {
  material_cost: '시스템 반영 + 시스템 미반영 / 키친솔루션 / VI 금액',
  processing_cost: '개선금액 / 키친솔루션 / 제품1 + 제품2',
  logistics_cost: '합계 / 개선금액(원)',
  investment: 'Total',
  sales_region1: '매출증분 + 원가인상 + 매출차감',
  sales_region2: '키친솔루션 / 개선금액 / 계',
  quality: '키친솔루션 / 개선금액',
  fixed_cost: '전체 / 제품1 + 제품2 고정비 합계 / 개선금액',
};
function AreaView({ area, item, months, mode, curMonth, curWeek, curCloseMonth, areaTbl, incCells }: {
  area: string; item: LgDetailItem; months: number[]; mode: Mode; curMonth: number; curWeek: number; curCloseMonth: number;
  areaTbl: LgAreaTable | null; incCells: Set<string>;
}) {
  const period = mode === 'cum' ? '누적' : mode === 'quarter' ? '분기' : '당월';
  // 세부 top3 source = 이 항목의 **기여 지표(개선금액/VI금액/저감금액) 말단 leaf** (LG 스펙).
  //   (Master 세부=시스템반영/미반영 처럼 너무 상위 → 제품/지역/부문 단위로 순위내려면 area 시트 말단 필요.)
  const baseItems = useMemo(() => contribLeaves(area, areaTbl?.rows ?? []), [area, areaTbl]);

  // 그래프 = 이 Area 의 headline(대표총계 = Master 가 가리키는 행).
  //   재료비 = "시스템 반영 + 시스템 미반영 / 키친솔루션 / VI 금액" (상단 카드 목표/실적과 동일 소스).
  //   누적 현황 = 연초~그 달 러닝합(목표/실적 누적, 달성률=누적÷누적) / 월별 현황 = 각 달 자기 수치.
  //   둘 다 x축=월(1~12). 목표는 12월까지·실적/달성률은 현재월까지(미래월 null → 막대/점 없음).
  // 그래프 데이터 = 이 Area 의 지정 행(GRAPH_ROW)의 목표/실적. areaTbl 에서 그 행 cells 사용
  // (투자비 Total 처럼 headline 아닌 행도 가능). 못 찾으면 headline(item.months) fallback.
  const graphCells = useMemo<Record<string, LgMonthCell>>(() => {
    const row = areaTbl?.rows.find((r) => r.부서경로 === GRAPH_ROW[area]);
    return (row?.cells as unknown as Record<string, LgMonthCell>) ?? item.months;
  }, [areaTbl, area, item]);
  const chart = useMemo(() => {
    if (mode === 'cum') {
      let ct = 0, ca = 0, prov = false;
      return months.map((m) => {
        const c = graphCells[String(m)];
        const future = m > curMonth;
        ct += c?.목표 ?? 0;
        if (!future) { ca += c?.실적 ?? 0; if (c?.잠정) prov = true; }
        return { x: `${m}월`, 목표: ct, 실적: future ? null : ca,
          달성률: future ? null : (ct ? Number(((ca / ct) * 100).toFixed(1)) : null), 잠정: future ? false : prov };
      });
    }
    if (mode === 'quarter') {
      // 분기 = 그 3개월 합. 실적은 현재월까지 든 달만(마감 전 달은 최신값=그 달 실적).
      return [1, 2, 3, 4].map((q) => {
        const ms = QMONTHS(q);
        let t = 0, a = 0, prov = false;
        ms.forEach((m) => { const c = graphCells[String(m)]; t += c?.목표 ?? 0; if (m <= curMonth) { a += c?.실적 ?? 0; if (c?.잠정) prov = true; } });
        const future = ms[0] > curMonth;
        return { x: `${q}분기`, 목표: t, 실적: future ? null : a,
          달성률: future ? null : (t ? Number(((a / t) * 100).toFixed(1)) : null), 잠정: future ? false : prov };
      });
    }
    return months.map((m) => {
      const c = graphCells[String(m)];
      const future = m > curMonth;
      return { x: `${m}월`, 목표: c?.목표 ?? 0, 실적: future ? null : (c?.실적 ?? null), 달성률: future ? null : (c?.달성률 ?? null), 잠정: future ? false : !!c?.잠정 };
    });
  }, [mode, months, graphCells, curMonth]);

  // 요약 카드 = 그래프와 **같은 행(graphCells)** 기준 (각 항목 그래프와 카드 일치). 누적/월별/분기.
  const perf = useMemo<LgPerf>(() => {
    const sum = (pred: (m: number) => boolean) => {
      let t = 0, a = 0;
      months.forEach((m) => { const c = graphCells[String(m)]; t += c?.목표 ?? 0; if (pred(m)) a += c?.실적 ?? 0; });
      return { 목표: t, 실적: a, 차이: a - t, 달성률: t ? Number(((a / t) * 100).toFixed(1)) : null };
    };
    if (mode === 'cum') return sum((m) => m <= curMonth);   // 연초~현재월 누적
    if (mode === 'quarter') {                                // 현재 분기 3개월
      const qms = QMONTHS(Q_OF(curMonth));
      let t = 0, a = 0;
      qms.forEach((m) => { const c = graphCells[String(m)]; t += c?.목표 ?? 0; if (m <= curMonth) a += c?.실적 ?? 0; });
      return { 목표: t, 실적: a, 차이: a - t, 달성률: t ? Number(((a / t) * 100).toFixed(1)) : null };
    }
    const c = graphCells[String(curMonth)];                  // 당월
    const t = c?.목표 ?? 0, a = c?.실적 ?? 0;
    return { 목표: t, 실적: a, 차이: a - t, 달성률: t ? Number(((a / t) * 100).toFixed(1)) : null };
  }, [mode, graphCells, months, curMonth]);
  // 잠정 — 표시 기간에 공식 월계 미도착(주차값 대체) 달이 섞였나 (그래프 행 기준 = 카드와 동일 소스)
  const perfProv = useMemo(() => {
    if (mode === 'quarter') return QMONTHS(Q_OF(curMonth)).some((m) => m <= curMonth && graphCells[String(m)]?.잠정);
    if (mode === 'cum') return months.some((m) => m <= curMonth && graphCells[String(m)]?.잠정);
    return !!graphCells[String(curMonth)]?.잠정;
  }, [mode, graphCells, months, curMonth]);

  // 세부 top3 — **현재 모드 기준**(누적/월별/분기, KPI 카드와 동일). baseItems = 이 항목의 하위 세부.
  const { shortfall, lowest } = rankTop3(baseItems, mode, curMonth, months);

  return (
    <div className="space-y-5">
      {/* 요약 카드 */}
      <div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Card label={`목표(${period})`} value={fmtAmt(perf.목표)} />
          <Card label={`실적(${period})`} value={fmtAmt(perf.실적)} primary
            tone={perf.실적 != null && perf.실적 < 0 ? 'down' : undefined} prov={perfProv} />
          <Card label={`목표 대비 차이(${period})`} value={fmtDiff(perf.차이)}
            tone={perf.차이 == null ? undefined : Math.round(perf.차이) > 0 ? 'up' : Math.round(perf.차이) < 0 ? 'down' : 'flat'}
            arrow={perf.차이 == null ? undefined : Math.round(perf.차이) > 0 ? '↑' : Math.round(perf.차이) < 0 ? '↓' : undefined} prov={perfProv} />
          <Card label={`목표 대비 달성률(${period})`} value={fmtPct(perf.달성률)}
            tone={rateTone(perf.달성률)} prov={perfProv} />
        </div>
        {perfProv && <ProvNote />}
      </div>

      {/* 목표/실적(막대) + 달성률(꺾은선) — headline(대표총계) 기준. 누적=월별(1~12) / 월별현황=그 달 주차별 */}
      {GRAPH_ROW[area] ? (
      <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-card">
        <h3 className="font-semibold text-slate-900 text-sm mb-3">
          {areaLabel(area)} · {modeLabel(mode)} 목표 vs 실적
        </h3>
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={provDash(chart, [['달성률', '잠정']])} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="x" tick={{ fontSize: 11, fill: '#64748b' }} />
            <YAxis yAxisId="left" tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={axisTick} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: '#64748b' }} unit="%" domain={[0, 'auto']} tickFormatter={axisTick} />
            <Tooltip content={(p: any) =>
              <ChartTooltip active={p.active} payload={p.payload} label={p.label} />} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar yAxisId="left" dataKey="목표" fill="#94a3b8" radius={[3, 3, 0, 0]} />
            <Bar yAxisId="left" dataKey="실적" fill="#ef4444" radius={[3, 3, 0, 0]}>
              {chart.map((d, i) => <Cell key={i} fill={d.잠정 ? '#fca5a5' : '#ef4444'} />)}
            </Bar>
            <Line yAxisId="right" type="monotone" dataKey="달성률__s" name="달성률" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
            <Line yAxisId="right" type="monotone" dataKey="달성률__d" name="달성률" stroke="#10b981" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 3 }} legendType="none" connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
        {chart.some((d) => d.잠정) && (
          <p className="mt-2 text-[11px] text-amber-600">※ 연한 막대 = 공식 월계 미도착, 주차 기준 잠정값 (도착 시 자동 확정)</p>
        )}
      </section>
      ) : (
      <section className="bg-white border border-dashed border-slate-300 rounded-xl p-5 shadow-card">
        <h3 className="font-semibold text-slate-900 text-sm mb-3">{areaLabel(area)} · 그래프</h3>
        <div className="flex flex-col items-center justify-center gap-1.5 py-16 text-center">
          <span className="text-sm text-slate-400">그래프 표시 방식은 추후 정의 예정입니다</span>
          <span className="text-[11px] text-slate-300">항목별 그래프 기준 확정 후 반영</span>
        </div>
      </section>
      )}

      {/* Area 시트 그대로 — 합계/소계/Rate 행 포함, 부서경로 계층 × 월 / 당월=주차 */}
      <AreaSheetTable area={area} table={areaTbl} mode={mode} curMonth={curMonth} curWeek={curWeek} curCloseMonth={curCloseMonth} incCells={incCells} />

      {/* 세부 top3 (누적 기준) — 모든 Area 하단에 항상 표시 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SummaryList
          title={`${areaLabel(area)} 목표 미달 영향 (${modeLabel(mode)}·금액)`}
          hint="세부 항목 중 목표 대비 부족분이 큰 항목"
          rows={shortfall.map(shortfallRow)}
        />
        <SummaryList
          title={`${areaLabel(area)} 목표 달성율 최저 (${modeLabel(mode)}·비율)`}
          hint="세부 항목 중 달성율이 낮은 항목"
          rows={lowest.map(lowestRow)}
        />
      </div>
    </div>
  );
}

// Area 시트를 **엑셀 그대로** — 경로 레벨별 병합셀 컬럼 | 구분(목표/실적/달성) | 데이터.
// 합계/소계/Rate 행 포함. 전체현황=월(1~12) / 당월=그 달의 월계+주차(W#). (백엔드 area_table)
const PW = 96; // 경로(부서경로) 컬럼 고정폭
const GUN = 40; // 구분 컬럼 고정폭
const DW = 64; // 데이터(월/주차) 컬럼 고정폭
const TW = 76; // 합계(Total) 컬럼 고정폭

// ── 공유 표 디자인 (전체 표·각 항목 표 공통 — 한 곳만 고치면 둘 다 반영) ──
// 각 항목 표 디자인을 기준으로 통일. 두 표가 아래 상수/헬퍼를 그대로 씀.
const SHEET_TBL = 'text-xs border-separate [border-spacing:0] table-fixed';
const SHEET_STK = 'sticky z-10 shadow-[inset_-1px_0_0_#e2e8f0]';        // 고정열(가로 스크롤 시 값 위 덮음)
// 틀 고정(엑셀식): 스크롤 컨테이너 높이 제한 + 헤더 sticky. 2단 헤더라 1단=top-0, 2단=top-[H1].
const SHEET_SCROLL = 'overflow-auto max-h-[70vh]';                       // 표 자체 스크롤 영역(헤더·좌열 고정)
const H1 = 33;                                                          // 1단 헤더 높이(px) — 2단 top 오프셋
const SHEET_STK_CORNER = 'sticky top-0 z-30 shadow-[inset_-1px_0_0_#e2e8f0]';  // 좌상단 코너(가로+세로 동시 고정)
// sticky 헤더는 불투명 bg 필수(border-separate 라 tr bg 안 따라옴 → 스크롤 시 본문 비침).
const SHEET_TH_GROUP = 'px-3 py-2 text-center font-semibold border-b border-l border-slate-200 whitespace-nowrap sticky top-0 z-20 bg-slate-50';
const SHEET_TH_SUB = 'px-2 py-1.5 text-center font-normal border-b border-l border-slate-200 whitespace-nowrap sticky z-20 bg-slate-100';
const SHEET_TD = 'px-3 py-1.5 text-center tabular-nums whitespace-nowrap border-l border-slate-200';
// 행 그룹 가로 구분선 — 큰 그룹 끝=진하게 / 세부 끝=연하게 / 구분(목표·실적·달성) 사이=없음.
// (border-separate 라 tr 가 아닌 셀에 줘야 그려짐)
const sheetDivider = (groupLast: boolean, subLast: boolean) =>
  groupLast ? ' border-b border-slate-200' : subLast ? ' border-b border-slate-100' : '';
// 현재 주차(curWeek) 컬럼 빨간 박스 — 좌·우(+머리 상단/꼬리 하단)만, 가로 구분선은 회색 유지.
const sheetWeekBox = (isCur: boolean, head?: boolean, last?: boolean) =>
  isCur ? ` border-l-2 border-l-rose-400 border-r-2 border-r-rose-400${head ? ' border-t-2 border-t-rose-400' : ''}${last ? ' border-b-2 border-b-rose-400' : ''}` : '';

type AreaCol = { key: string; label: string; kind: 'month' | 'monthtotal' | 'week' | 'quarter' | 'qmonth'; m?: number; wk?: string; q?: number };
function AreaSheetTable({ area, table, mode, curMonth, curWeek, curCloseMonth, incCells }: {
  area: string; table: LgAreaTable | null; mode: Mode; curMonth: number; curWeek: number; curCloseMonth: number; incCells?: Set<string>;
}) {
  const rows: LgAreaRow[] = table?.rows ?? [];
  const months = table?.months ?? [];
  // 공통 숫자 규칙 사용 — 엑셀 pct(퍼센트) 판정만 살리고(값×100), 자릿수는 fmtAmt/fmtPct 로 통일.
  //   비율 셀은 분수(0.85)로 저장 → ×100 후 fmtPct(1자리%). 금액은 fmtAmt(정수·<1 소수1·△).
  const fmt = (v: number | null | undefined, rate: boolean) =>
    rate ? (v == null ? '–' : fmtPct(v * 100)) : fmtAmt(v);

  const maxDepth = Math.max(1, ...rows.map((r) => r.부서경로.split(' / ').length));

  // 데이터 컬럼 — 항상 월별(1~M). 월 헤더 클릭 시 그 달 주차(W1·W2…) 펼침. 기본 = 접힘.
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const toggleMonth = (m: number) => setExpanded((s) => { const n = new Set(s); n.has(m) ? n.delete(m) : n.add(m); return n; });
  const { cols, headGroups } = useMemo(() => {
    const weeksOfMonth = (m: number): string[] => {
      const order: string[] = []; const seen = new Set<string>();
      for (const r of rows) for (const w of r.cells[String(m)]?.weeks ?? []) {
        if (!seen.has(w.주차)) { seen.add(w.주차); order.push(w.주차); }
      }
      return order.sort((a, b) => (Number(a.replace(/\D/g, '')) || 0) - (Number(b.replace(/\D/g, '')) || 0));
    };
    const out: AreaCol[] = [];
    const groups: { m: number; label: string; expanded: boolean; span: number; hasWeeks: boolean }[] = [];
    if (mode === 'quarter') {
      // 분기 컬럼 — 데이터 있는 월이 속한 분기. 펼치면 그 분기의 (있는) 월들. (월→주차 펼치듯 분기→월)
      const quarters = Array.from(new Set(months.map(Q_OF))).sort((a, b) => a - b);
      for (const q of quarters) {
        const qms = QMONTHS(q).filter((m) => months.includes(m));   // 그 분기의 데이터 있는 월
        const showMs = expanded.has(q) ? qms : [];
        out.push({ key: `q${q}`, label: `${q}분기`, kind: 'quarter', q });
        showMs.forEach((m) => out.push({ key: `q${q}m${m}`, label: `${m}월`, kind: 'qmonth', m, q }));
        groups.push({ m: q, label: `${q}분기`, expanded: showMs.length > 0, span: 1 + showMs.length, hasWeeks: qms.length > 1 });
      }
      return { cols: out, headGroups: groups };
    }
    for (const m of months) {
      const monthWeeks = weeksOfMonth(m);            // 이 달 주차 데이터 유무 (펼침 무관)
      const wks = expanded.has(m) ? monthWeeks : [];
      out.push({ key: `m${m}`, label: `${m}월`, kind: 'month', m });   // 월계 leaf — 펼쳐도 유지
      wks.forEach((wk) => out.push({ key: `m${m}w${wk}`, label: wk, kind: 'week', m, wk }));   // 실제 ISO 주차번호(W14 등) — 경계주는 양쪽 월에 그대로
      groups.push({ m, label: `${m}월`, expanded: wks.length > 0, span: 1 + wks.length, hasWeeks: monthWeeks.length > 0 });
    }
    return { cols: out, headGroups: groups };
  }, [months, rows, expanded, mode]);

  // 현재 시점 = **현재 주차(curWeek) 컬럼 한 칸**만 빨간 박스(당월 전체 아님, 예: W18 데이터만).
  // 빨간 테두리 대상 — 마감이면 그 달 월계(month) 컬럼 / 주차면 그 주차(week) 컬럼(펼쳤을 때),
  // 접혀서 주차 컬럼이 없으면 그 달 월(month) 컬럼으로 폴백(접힘 기본 유지하면서 위치 표시).
  const wkShown = curWeek > 0 && cols.some((c) => c.kind === 'week' && (Number(String(c.wk).replace(/\D/g, '')) || 0) === curWeek);
  const isCurWk = (col: AreaCol) =>
    curCloseMonth ? (col.kind === 'month' && col.m === curCloseMonth)
      : curWeek ? (wkShown ? (col.kind === 'week' && (Number(String(col.wk).replace(/\D/g, '')) || 0) === curWeek)
        : (col.kind === 'month' && col.m === curMonth))
      : false;
  const wkBox = (col: AreaCol, pos: 'head' | 'body' | 'last') =>
    sheetWeekBox(isCurWk(col), pos === 'head', pos === 'last');

  const getCell = (r: LgAreaRow, col: AreaCol) => {
    if (col.kind === 'week') return r.cells[String(col.m)]?.weeks?.find((w) => w.주차 === col.wk) ?? null;
    return r.cells[String(col.m)] ?? null;
  };
  // 값 — 누적 현황: 월 컬럼은 1~m 월값 누적합 / 월별 현황: 그 달 값. 주차(W)는 항상 raw.
  // (비율 행은 누적 의미 없어 raw 유지)
  const valAt = (r: LgAreaRow, col: AreaCol, metric: '목표' | '실적' | '전년', cumulative: boolean, isRate?: boolean): number | null => {
    if (col.kind === 'week') {
      const c = getCell(r, col);   // 주차도 전년 있으면 표시 (양식에 주차별 전년 존재)
      return c ? (c as { 목표: number | null; 실적: number | null; 전년?: number | null })[metric] ?? null : null;
    }
    if (col.kind === 'quarter') {
      // 분기 = 그 분기 데이터 있는 월들의 합 (마감 전 달은 최신값=그 달 실적이 이미 들어있음).
      const qms = QMONTHS(col.q!).filter((m) => months.includes(m));
      if (isRate) {   // 비율은 합산 의미 없음 → 그 분기 마지막(최신) 월의 값
        let last: number | null = null;
        for (const m of qms) { const x = r.cells[String(m)]?.[metric]; if (x != null) last = x; }
        return last;
      }
      let acc: number | null = null;
      for (const m of qms) { const x = r.cells[String(m)]?.[metric]; if (x != null) acc = (acc ?? 0) + x; }
      return acc;
    }
    if (col.kind === 'qmonth') return r.cells[String(col.m!)]?.[metric] ?? null;
    if (cumulative) {
      let acc: number | null = null;
      for (const mm of months) {
        if (mm > col.m!) break;
        const x = r.cells[String(mm)]?.[metric];
        if (x != null) acc = (acc ?? 0) + x;
      }
      return acc;
    }
    return r.cells[String(col.m!)]?.[metric] ?? null;
  };
  // 잠정 — 그 컬럼이 가리키는 월(들) 중 공식 월계 미도착(주차값 대체)이 섞였나. 주차(W) 컬럼·미래 제외.
  const provAt = (r: LgAreaRow, col: AreaCol, isRate?: boolean): boolean => {
    if (col.kind === 'week') return false;
    if (col.kind === 'quarter') return QMONTHS(col.q!).filter((m) => months.includes(m)).some((m) => !!r.cells[String(m)]?.잠정);
    if (col.kind === 'qmonth') return !!r.cells[String(col.m!)]?.잠정;
    if (mode === 'cum' && !isRate) return months.some((m) => m <= col.m! && !!r.cells[String(m)]?.잠정);
    return !!r.cells[String(col.m!)]?.잠정;
  };
  const anyProv = rows.some((r) => cols.some((c) => provAt(r, c, r.is_rate)));
  // 엑셀 그대로 — 목표/실적. 달성률은 계산값이라 표에서 제외(요약 카드에만).
  // 전년 동기 실적은 **그 행에 전년 데이터가 있는 행만** 한 줄 더 (개선금액 등 전년 없는 행엔 안 붙임).
  type Metric = '목표' | '실적' | '전년';
  type MRow = { segs: string[]; metric: Metric; row: LgAreaRow; leaf: number; isLast: boolean };
  const mrows: MRow[] = [];
  rows.forEach((r, li) => {
    const segs = r.부서경로.split(' / ');
    const rowHasPrev = Object.values(r.cells).some((c) => c.전년 != null);
    const metrics: Metric[] = rowHasPrev ? ['전년', '목표', '실적'] : ['목표', '실적'];
    metrics.forEach((m, mi) => mrows.push({ segs, metric: m, row: r, leaf: li, isLast: mi === metrics.length - 1 }));
  });

  // (행 i, 경로깊이 d) 의 병합 키. null = 말단 colSpan 에 덮인 빈칸
  const keyAt = (i: number, d: number): string | null => {
    const { segs, leaf } = mrows[i];
    const term = segs.length - 1;
    if (d > term) return null; // 말단 colSpan 이 채움
    if (d === term) return `T|${leaf}`; // 말단 세그먼트 — 같은 leaf 의 metric 행들(목표/실적)만 병합
    return `A|${segs.slice(0, d + 1).join('')}`; // 조상 — 같은 prefix 형제끼리 병합
  };

  const STK = SHEET_STK;   // 공유 고정열 스타일

  // 합계 열 제거 — 누적 현황의 마지막 달이 곧 합계라 중복.
  const showTotal = false;
  const weekMonths = headGroups.filter((g) => g.hasWeeks).map((g) => g.m);  // 주차 데이터 있는 달만
  const anyExpanded = expanded.size > 0;   // 하나라도 펼쳐져 있으면 → "전체 접기"

  // 셀 단위 누락 — 받은 주차인데 그 (부서경로) 실적이 빈 셀. 주차 셀=직접 / 월·분기 셀=속한 주차 중 누락 있으면.
  const wkNum = (s: string) => Number(String(s).replace(/\D/g, '') || 0);
  const missAt = (r: LgAreaRow, col: AreaCol, metric: Metric): boolean => {
    if (metric !== '실적' || !incCells || incCells.size === 0) return false;
    if (col.kind === 'week') return incCells.has(`${r.부서경로}|${wkNum(col.wk!)}`);
    if (col.kind === 'month' || col.kind === 'qmonth')
      return (r.cells[String(col.m)]?.weeks ?? []).some((w) => incCells.has(`${r.부서경로}|${wkNum(w.주차)}`));
    if (col.kind === 'quarter')
      return QMONTHS(col.q!).some((m) => (r.cells[String(m)]?.weeks ?? []).some((w) => incCells.has(`${r.부서경로}|${wkNum(w.주차)}`)));
    return false;
  };

  // 시뮬 변경 셀 — 현재 대비 바뀐 실적 셀(chg)에 하이라이트. before=변경 전 값(툴팁).
  const chgAt = (r: LgAreaRow, col: AreaCol, metric: Metric): { before: number | null } | null => {
    if (metric !== '실적') return null;
    if (col.kind === 'week') {
      const c = getCell(r, col) as LgAreaWeek | null;
      return c?.chg ? { before: c.before ?? null } : null;
    }
    if (col.kind === 'month' || col.kind === 'qmonth') {
      if (mode === 'cum' && col.kind === 'month') {
        const any = months.some((mm) => mm <= (col.m ?? 0) && r.cells[String(mm)]?.chg);
        return any ? { before: null } : null;   // 누적은 합이라 단일 before 없음
      }
      const c = r.cells[String(col.m)];
      return c?.chg ? { before: c.before ?? null } : null;
    }
    if (col.kind === 'quarter')
      return QMONTHS(col.q!).some((m) => r.cells[String(m)]?.chg) ? { before: null } : null;
    return null;
  };

  return (
    <section className="bg-white border border-slate-200 rounded-xl shadow-card overflow-hidden">
      {weekMonths.length > 0 && (
        <div className="px-4 py-2 border-b border-slate-100 flex items-center justify-end">
          <button onClick={() => setExpanded(anyExpanded ? new Set() : new Set(weekMonths))}
            className="text-[11px] font-medium text-slate-500 hover:text-primary-600 border border-slate-200 rounded-md px-2 py-1 whitespace-nowrap">
            {anyExpanded ? '전체 접기' : '전체 펼치기'}
          </button>
        </div>
      )}
      <div className={SHEET_SCROLL}>
        {/* border-separate — 고정열(sticky)이 가로 스크롤 시 데이터 위를 덮음 + 헤더 sticky top 으로 틀 고정 */}
        <table className={SHEET_TBL} style={{ width: maxDepth * PW + GUN + cols.length * DW + (showTotal ? TW : 0) }}>
          <colgroup>
            {Array.from({ length: maxDepth }).map((_, d) => <col key={`p${d}`} style={{ width: PW }} />)}
            <col style={{ width: GUN }} />
            {cols.map((col) => <col key={col.key} style={{ width: DW }} />)}
            {showTotal && <col style={{ width: TW }} />}
          </colgroup>
          <thead>
            {/* 1단: 부서경로/구분(rowSpan2 고정) + 월 그룹(colSpan) + 합계(rowSpan2). 항상 2단 → 안 흔들림 */}
            <tr className="bg-slate-50 text-[11px] text-slate-500">
              <th rowSpan={2} className={`${SHEET_STK_CORNER} left-0 bg-slate-50 px-3 py-2 text-center font-semibold border-b`} colSpan={maxDepth}>부서경로</th>
              <th rowSpan={2} className={`${SHEET_STK_CORNER} bg-slate-50 px-2 py-2 text-center font-semibold border-b`} style={{ left: maxDepth * PW }}>구분</th>
              {headGroups.map((g) => (
                <th key={g.m} colSpan={g.span}
                  className={SHEET_TH_GROUP}>
                  {g.hasWeeks ? (
                    <button onClick={() => toggleMonth(g.m)} className="inline-flex items-center gap-0.5 hover:text-primary-600">
                      {g.label}<span className="text-[8px]">{g.expanded ? '▼' : '▶'}</span>
                    </button>
                  ) : (
                    <span>{g.label}</span>
                  )}
                </th>
              ))}
              {showTotal && <th rowSpan={2} className="px-3 py-2 text-center font-semibold border-b border-l border-slate-300 bg-slate-100 text-slate-600 whitespace-nowrap sticky top-0 z-20">합계</th>}
            </tr>
            {/* 2단: 각 달/분기의 실적(+펼치면 W1·W2… 또는 월). 항상 렌더 → 높이 고정 */}
            <tr className="bg-slate-100/70 text-[10px] text-slate-400">
              {cols.map((c) => (
                <th key={c.key} className={`${SHEET_TH_SUB}${wkBox(c, 'head')}`} style={{ top: H1 }}>
                  {c.kind === 'week' || c.kind === 'qmonth' ? c.label : '실적'}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {mrows.map((mr, i) => {
              const { metric, row, segs, isLast } = mr;
              const isRate = row.is_rate;
              const isGraphRow = row.부서경로 === GRAPH_ROW[area];   // 그래프 그린 행 → 핑크 음영
              const labelCls = metric === '실적' ? 'text-slate-700 font-medium'
                : metric === '전년' ? 'text-slate-400 italic' : 'text-slate-400';
              return (
                <tr key={i} className={`${isLast ? 'border-b border-slate-200' : ''} hover:bg-slate-50/40`}>
                  {Array.from({ length: maxDepth }).map((_, d) => {
                    const k = keyAt(i, d);
                    if (k === null) return null; // colSpan 에 덮임
                    if (i > 0 && keyAt(i - 1, d) === k) return null; // 위 행 rowSpan 에 병합됨
                    let span = 1;
                    while (i + span < mrows.length && keyAt(i + span, d) === k) span++;
                    const isTerm = k.startsWith('T|');
                    const colSpan = isTerm ? maxDepth - d : 1;
                    const bg = isGraphRow && isTerm ? 'bg-amber-100' : 'bg-slate-50'; // 그래프 그린 행 = 연한 노랑
                    return (
                      <td key={d} rowSpan={span} colSpan={colSpan}
                        className={`${STK} px-2 py-1.5 align-middle text-center whitespace-normal break-words leading-tight ${bg} border-b border-slate-200 ${isTerm ? 'text-slate-700' : 'font-medium text-slate-600'}`}
                        style={{ left: d * PW }} title={segs.slice(0, d + 1).join(' / ')}>
                        {segs[d]}
                      </td>
                    );
                  })}
                  <td className={`${STK} ${isGraphRow ? 'bg-amber-100' : 'bg-white'} px-2 py-1.5 text-center text-[11px] whitespace-nowrap ${labelCls}${isLast ? ' border-b border-slate-200' : ''}`}
                    style={{ left: maxDepth * PW }}>{metric}</td>
                  {cols.map((col) => {
                    const v = valAt(row, col, metric, mode === 'cum' && !isRate, isRate);
                    const neg = v != null && v < 0;   // 음수 = 빨간색 강조
                    // 표시 기준 통일 — '누락'(장미)은 **빈 셀이면서 중간 구멍**일 때만(주차·월 공통).
                    //   값이 있으면(집계에 다른 주차값 섞여도) 그냥 값 표시. 데이터 없음(미제출)=빈칸 '–'.
                    const isEmptyHole = missAt(row, col, metric) && v == null;
                    const chg = chgAt(row, col, metric);     // 시뮬 변경 셀 하이라이트
                    return (
                      <td key={col.key}
                        title={chg ? (chg.before != null ? `변경 전: ${fmt(chg.before, isRate)}` : '변경 반영됨')
                          : isEmptyHole ? '실적 누락(빈 셀) — 받은 시점인데 이 셀만 빔' : undefined}
                        className={`${SHEET_TD} ${
                          chg ? 'bg-indigo-100 ring-1 ring-inset ring-indigo-300'
                            : isEmptyHole ? 'bg-rose-100 ring-1 ring-inset ring-rose-300' : isGraphRow ? 'bg-amber-100' : ''} ${
                          neg ? 'text-rose-600' : metric === '실적' ? 'text-slate-800' : metric === '전년' ? 'text-slate-400' : 'text-slate-500'}${wkBox(col, i === mrows.length - 1 ? 'last' : 'body')}${isLast ? ' border-b border-slate-200' : ''}`}>
                        {isEmptyHole ? <span className="text-rose-500 font-semibold">누락</span> : fmt(v, isRate)}
                        {metric === '실적' && provAt(row, col, isRate) && <ProvMark />}
                      </td>
                    );
                  })}
                  {showTotal && (() => {
                    // 합계 열 — 전체현황(월별)에서 1~12월 합. 비율(Rate) 행은 합산 의미 없어 '–'.
                    if (isRate) return <td key="total" className="px-3 py-1.5 text-center text-slate-300 border-l border-slate-300 bg-slate-50">–</td>;
                    let sum = 0; let any = false;
                    for (const col of cols) {
                      if (col.kind === 'week') continue;
                      const c = getCell(row, col);
                      const v = c ? (c as { 목표: number | null; 실적: number | null; 전년?: number | null })[metric] : null;
                      if (v != null) { sum += v; any = true; }
                    }
                    return (
                      <td key="total" className={`px-3 py-1.5 text-center tabular-nums whitespace-nowrap border-l border-slate-300 bg-slate-50 font-semibold ${
                        metric === '실적' ? 'text-slate-800' : 'text-slate-600'}`}>
                        {any ? fmtAmt(sum) : '–'}
                      </td>
                    );
                  })()}
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr><td colSpan={maxDepth + cols.length + 2} className="px-4 py-8 text-center text-slate-400">상세 데이터가 없습니다.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {anyProv && <ProvNote inset />}
    </section>
  );
}

// 전체 종합 — 항목(병합) | 세부(병합) | 구분 | 월별(1~12월) 또는 당월 차수별(W#)
type WkCol = { key: string; label: string; m?: number; wk?: string; q?: number };
function MasterSheetTable({ table, mode, curMonth, curWeek, curCloseMonth }: { table: LgMasterTable; mode: Mode; curMonth: number; curWeek: number; curCloseMonth: number }) {
  // table.rows(level 0/1) → 그룹: {primary, bold, subs:[{sub, cells, metrics}]}
  type Sub = { sub: string; cells: Record<string, LgTableCell>; metrics: ('목표' | '실적' | '달성률')[] };
  const groups: { primary: string; bold: boolean; subs: Sub[] }[] = [];
  const rows = table.rows;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    if (r.level !== 0) continue;
    if (r.bold) {
      groups.push({ primary: r.label, bold: true, subs: [{ sub: '', cells: r.cells, metrics: ['목표', '실적', '달성률'] }] });
      continue;
    }
    // 하위(level 1) 모으기
    const children: typeof rows = [];
    let j = i + 1;
    while (j < rows.length && rows[j].level === 1) { children.push(rows[j]); j++; }
    if (children.length) {
      groups.push({ primary: r.label, bold: false, subs: children.map((c) => ({ sub: c.label, cells: c.cells, metrics: ['목표', '실적'] })) });
      i = j - 1;
    } else {
      groups.push({ primary: r.label, bold: false, subs: [{ sub: '', cells: r.cells, metrics: ['목표', '실적'] }] });
    }
  }

  // 컬럼 — 항상 월별(1~M). 월 헤더 클릭 시 그 달 주차(W1·W2…) 컬럼 펼침. 기본 = 접힘.
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const mWkBox = (c: WkCol, head: boolean, last?: boolean) => {
    const wkShown = curWeek > 0 && cols.some((x) => x.wk && (Number(String(x.wk).replace(/\D/g, '')) || 0) === curWeek);
    const red = curCloseMonth ? (!c.wk && c.m === curCloseMonth)
      : curWeek ? (wkShown ? (!!c.wk && (Number(String(c.wk).replace(/\D/g, '')) || 0) === curWeek)
        : (!c.wk && c.m === curMonth))
      : false;
    return sheetWeekBox(red, head, last);
  };
  const toggleMonth = (m: number) => setExpanded((s) => { const n = new Set(s); n.has(m) ? n.delete(m) : n.add(m); return n; });
  const weeksOfMonth = (m: number): string[] => {
    const order: string[] = []; const seen = new Set<string>();
    for (const r of table.rows) for (const w of r.cells[String(m)]?.weeks ?? []) {
      if (!seen.has(w.주차)) { seen.add(w.주차); order.push(w.주차); }
    }
    return order.sort((a, b) => (Number(a.replace(/\D/g, '')) || 0) - (Number(b.replace(/\D/g, '')) || 0));
  };
  const cols: WkCol[] = [];
  const headGroups: { m: number; label: string; expanded: boolean; span: number; hasWeeks: boolean }[] = [];
  if (mode === 'quarter') {
    // 분기 컬럼 — 데이터 있는 월이 속한 분기. 펼치면 그 분기 월들. (월→주차 펼치듯 분기→월)
    const quarters = Array.from(new Set(table.months.map(Q_OF))).sort((a, b) => a - b);
    for (const q of quarters) {
      const qms = QMONTHS(q).filter((m) => table.months.includes(m));
      const showMs = expanded.has(q) ? qms : [];
      cols.push({ key: `q${q}`, label: `${q}분기`, q });
      showMs.forEach((m) => cols.push({ key: `q${q}m${m}`, label: `${m}월`, m, q }));
      headGroups.push({ m: q, label: `${q}분기`, expanded: showMs.length > 0, span: 1 + showMs.length, hasWeeks: qms.length > 1 });
    }
  } else {
    for (const m of table.months) {
      const monthWeeks = weeksOfMonth(m);            // 이 달 주차 데이터 유무 (펼침 무관)
      const wks = expanded.has(m) ? monthWeeks : [];
      cols.push({ key: `m${m}`, label: `${m}월`, m });   // 월계 leaf — 펼쳐도 유지
      wks.forEach((wk) => cols.push({ key: `m${m}w${wk}`, label: wk, m, wk }));   // 연속 ISO 주차번호(1월 W1·2월 W6…)
      headGroups.push({ m, label: `${m}월`, expanded: wks.length > 0, span: 1 + wks.length, hasWeeks: monthWeeks.length > 0 });
    }
  }
  // 셀 → 해당 컬럼(월 or 주차)의 metric 셀 객체
  const cellOf = (cells: Record<string, LgTableCell>, col: WkCol): LgTableCell | LgAreaWeek | null => {
    if (col.wk) return cells[String(col.m)]?.weeks?.find((w) => w.주차 === col.wk) ?? null;
    return cells[String(col.m)] ?? null;
  };
  // 값 — 분기 컬럼이면 그 분기 월 합(달성률은 재계산), 아니면 cellOf 의 metric.
  const valOf = (cells: Record<string, LgTableCell>, col: WkCol, metric: string): number | null => {
    if (col.q != null && col.m == null) {
      const qms = QMONTHS(col.q).filter((m) => table.months.includes(m));
      if (metric === '달성률') {
        let t = 0, a = 0;
        qms.forEach((m) => { const c = cells[String(m)]; if (c?.목표 != null) t += c.목표; if (c?.실적 != null) a += c.실적; });
        return t ? Number(((a / t) * 100).toFixed(1)) : null;
      }
      let acc: number | null = null;
      qms.forEach((m) => { const x = (cells[String(m)] as unknown as Record<string, number | null>)?.[metric]; if (x != null) acc = (acc ?? 0) + x; });
      return acc;
    }
    // 누적 현황 = 월 컬럼은 연초~그 달 누적(주차·qmonth 제외). 달성률 = 누적실적÷누적목표.
    if (mode === 'cum' && col.m != null && col.q == null && !col.wk) {
      if (metric === '달성률') {
        let t = 0, a = 0;
        table.months.forEach((mm) => { if (mm <= col.m!) { const c = cells[String(mm)]; if (c?.목표 != null) t += c.목표; if (c?.실적 != null) a += c.실적; } });
        return t ? Number(((a / t) * 100).toFixed(1)) : null;
      }
      let acc: number | null = null;
      table.months.forEach((mm) => { if (mm <= col.m!) { const x = (cells[String(mm)] as unknown as Record<string, number | null>)?.[metric]; if (x != null) acc = (acc ?? 0) + x; } });
      return acc;
    }
    const c = cellOf(cells, col);
    return c ? (c as unknown as Record<string, number | null>)[metric] : null;
  };
  // 잠정 — 그 컬럼이 가리키는 월(들) 중 공식 월계 미도착(주차값 대체)이 섞였나. 주차(W) 컬럼은 잠정 아님.
  const provOf = (cells: Record<string, LgTableCell>, col: WkCol): boolean => {
    if (col.wk) return false;
    if (col.q != null && col.m == null)
      return QMONTHS(col.q).filter((m) => table.months.includes(m)).some((m) => !!cells[String(m)]?.잠정);
    if (mode === 'cum' && col.m != null && col.q == null)
      return table.months.some((mm) => mm <= col.m! && !!cells[String(mm)]?.잠정);
    return !!cells[String(col.m!)]?.잠정;
  };
  // 시뮬 변경 셀 — 현재 대비 바뀐 실적 셀(chg). before=변경 전(툴팁).
  const chgOf = (cells: Record<string, LgTableCell>, col: WkCol, metric: string): { before: number | null } | null => {
    if (metric !== '실적') return null;
    if (col.wk) {
      const w = cells[String(col.m)]?.weeks?.find((x) => x.주차 === col.wk);
      return w?.chg ? { before: w.before ?? null } : null;
    }
    if (col.q != null && col.m == null)
      return QMONTHS(col.q).filter((m) => table.months.includes(m)).some((m) => cells[String(m)]?.chg) ? { before: null } : null;
    if (mode === 'cum' && col.m != null && col.q == null)
      return table.months.some((mm) => mm <= col.m! && cells[String(mm)]?.chg) ? { before: null } : null;
    const c = cells[String(col.m!)];
    return c?.chg ? { before: c.before ?? null } : null;
  };

  const weekMonths = headGroups.filter((g) => g.hasWeeks).map((g) => g.m);  // 주차 데이터 있는 달만
  const anyProv = groups.some((g) => g.subs.some((s) => cols.some((c) => provOf(s.cells, c))));
  const anyExpanded = expanded.size > 0;   // 하나라도 펼쳐져 있으면 → "전체 접기"
  const STK = SHEET_STK;   // 공유 고정열 스타일 (DW 등은 모듈 상수)
  return (
    <section className="bg-white border border-slate-200 rounded-xl shadow-card overflow-hidden">
      {weekMonths.length > 0 && (
        <div className="px-4 py-2 border-b border-slate-100 flex items-center justify-end">
          <button onClick={() => setExpanded(anyExpanded ? new Set() : new Set(weekMonths))}
            className="text-[11px] font-medium text-slate-500 hover:text-primary-600 border border-slate-200 rounded-md px-2 py-1 whitespace-nowrap">
            {anyExpanded ? '전체 접기' : '전체 펼치기'}
          </button>
        </div>
      )}
      {cols.length === 0 ? (
        <div className="px-4 py-8 text-center text-slate-400 text-xs">데이터가 없습니다.</div>
      ) : (
      <div className={SHEET_SCROLL}>
        {/* 공유 표 디자인(SHEET_TBL) — 각 항목 표와 동일. 틀 고정: 헤더 sticky top + 좌열 sticky left */}
        <table className={SHEET_TBL} style={{ width: 250 + cols.length * DW }}>
          <colgroup>
            <col style={{ width: 96 }} />{/* 항목 */}
            <col style={{ width: 110 }} />{/* 세부 */}
            <col style={{ width: 44 }} />{/* 구분 */}
            {cols.map((c) => <col key={c.key} style={{ width: DW }} />)}
          </colgroup>
          <thead>
            {/* 1단: 항목/세부/구분(rowSpan2 고정) + 월 그룹(colSpan). 항상 2단이라 헤더 안 흔들림 */}
            <tr className="bg-slate-50 text-[11px] text-slate-500">
              <th rowSpan={2} className={`${SHEET_STK_CORNER} left-0 bg-slate-50 px-3 py-2 text-center font-semibold border-b`} style={{ minWidth: 96 }}>항목</th>
              <th rowSpan={2} className={`${SHEET_STK_CORNER} bg-slate-50 px-2 py-2 text-center font-semibold border-b`} style={{ left: 96, minWidth: 110 }}>세부</th>
              <th rowSpan={2} className={`${SHEET_STK_CORNER} bg-slate-50 px-2 py-2 text-center font-semibold border-b`} style={{ left: 206, minWidth: 44 }}>구분</th>
              {headGroups.map((g) => (
                <th key={g.m} colSpan={g.span}
                  className={SHEET_TH_GROUP} style={{ minWidth: 56 }}>
                  {g.hasWeeks ? (
                    <button onClick={() => toggleMonth(g.m)} className="inline-flex items-center gap-0.5 hover:text-primary-600">
                      {g.label}<span className="text-[8px]">{g.expanded ? '▼' : '▶'}</span>
                    </button>
                  ) : (
                    <span>{g.label}</span>
                  )}
                </th>
              ))}
            </tr>
            {/* 2단: 각 달/분기의 월계(+펼치면 W1·W2… 또는 월). 항상 렌더 → 헤더 높이 고정 */}
            <tr className="bg-slate-100/70 text-[10px] text-slate-400">
              {cols.map((c) => (
                <th key={c.key} className={`${SHEET_TH_SUB}${mWkBox(c, true)}`} style={{ minWidth: 48, top: H1 }}>
                  {c.wk || (c.q != null && c.m != null) ? c.label : '실적'}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((g, gi) => {
              const groupSpan = g.subs.reduce((s, sub) => s + sub.metrics.length, 0);
              const bg = g.bold ? 'bg-amber-100' : 'bg-white';     // 합계=그래프 데이터 → 연한 노랑(달성률 색 위에 보이게)
              const lblBg = g.bold ? 'bg-amber-100' : 'bg-slate-50';  // 항목/세부 라벨 열
              // 세부 없는 그룹(합계·단일항목) → 항목 칸이 세부까지 합쳐짐(colSpan 2)
              const flat = g.subs.length === 1 && !g.subs[0].sub;
              let firstOfGroup = true;
              return (
                <Fragment key={gi}>
                  {g.subs.map((sub, si) => (
                    <Fragment key={si}>
                      {sub.metrics.map((metric, mi) => {
                        const showPrimary = firstOfGroup; firstOfGroup = false;
                        const lastRow = si === g.subs.length - 1 && mi === sub.metrics.length - 1;
                        const subLast = mi === sub.metrics.length - 1;   // 세부 묶음 끝 (구분=목표/실적/달성 사이엔 선 X)
                        // border-separate 에선 tr border 무시 → 가로 구분선은 셀에 준다(공유 헬퍼).
                        const rowB = sheetDivider(lastRow, subLast);
                        const isTableLast = gi === groups.length - 1 && lastRow;   // 표 맨 마지막 행(빨간 박스 하단 닫기)
                        return (
                          <tr key={metric} className={`${g.bold ? 'bg-amber-100' : 'hover:bg-slate-50/40'}`}>
                            {showPrimary && (
                              <td rowSpan={groupSpan} colSpan={flat ? 2 : 1} className={`${STK} left-0 ${lblBg} px-3 py-1.5 text-center align-middle font-semibold whitespace-normal break-words leading-tight border-b border-slate-200 ${g.bold ? 'text-slate-800' : 'text-slate-700'}`} style={{ minWidth: flat ? 206 : 96 }}>
                                {g.primary}
                              </td>
                            )}
                            {!flat && mi === 0 && (
                              <td rowSpan={sub.metrics.length} className={`${STK} ${lblBg} px-2 py-1.5 text-center align-middle text-slate-600 whitespace-normal break-words leading-tight ${si === g.subs.length - 1 ? 'border-b border-slate-200' : 'border-b border-slate-100'}`} style={{ left: 96, minWidth: 110 }}>
                                {sub.sub || ''}
                              </td>
                            )}
                            <td className={`${STK} ${bg} px-2 py-1.5 text-center text-[11px] ${metric === '실적' ? 'text-slate-700 font-medium' : 'text-slate-400'}${rowB}`} style={{ left: 206, minWidth: 44 }}>
                              {metric === '달성률' ? '달성' : metric}
                            </td>
                            {cols.map((col) => {
                              const isRate = metric === '달성률';
                              const v = valOf(sub.cells, col, metric);
                              const chg = chgOf(sub.cells, col, metric);   // 시뮬 변경 셀
                              return (
                                <td key={col.key}
                                  title={chg ? (chg.before != null ? `변경 전: ${fmtAmt(chg.before)}` : '변경 반영됨') : undefined}
                                  className={`${SHEET_TD} ${
                                    chg ? 'bg-indigo-100 ring-1 ring-inset ring-indigo-300' : isRate ? rateBg(v) : ''} ${
                                    isRate ? rateClass(v) : v != null && v < 0 ? 'text-rose-600' : metric === '실적' ? 'text-slate-800' : 'text-slate-500'}${mWkBox(col, false, isTableLast)}${rowB}`}>
                                  {isRate ? fmtPct(v) : fmtAmt(v)}
                                  {metric === '실적' && provOf(sub.cells, col) && <ProvMark />}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </Fragment>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      )}
      {anyProv && <ProvNote inset />}
    </section>
  );
}

function SummaryList({ title, hint, rows }: {
  title: string; hint: string;
  rows: { 항목: string; main: string; sub: string; mainCls: string; arrow?: string }[];
}) {
  return (
    <section className="bg-white border border-slate-200 rounded-xl shadow-card p-5">
      <h3 className="font-semibold text-slate-900 text-sm">{title}</h3>
      <p className="text-[11px] text-slate-400 mt-0.5 mb-3">{hint}</p>
      {rows.length === 0 ? (
        <div className="py-4 text-center text-slate-400 text-xs">해당 항목 없음 (모두 달성)</div>
      ) : (
        <ol className="space-y-2">
          {rows.map((r, i) => (
            <li key={r.항목} className="flex items-center gap-3">
              <span className="w-5 h-5 rounded-full bg-slate-100 text-slate-500 text-[11px] font-bold flex items-center justify-center flex-shrink-0">{i + 1}</span>
              <span className="font-medium text-slate-800 flex-1">{r.항목}</span>
              <span className="text-right">
                <span className={`tabular-nums ${r.mainCls}`}>{r.main}{r.arrow && <span className="ml-0.5">{r.arrow}</span>}</span>
                <span className="block text-[10px] text-slate-400">{r.sub}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Card({ label, value, primary, tone, prov, arrow }: {
  label: string; value: string; primary?: boolean;
  tone?: 'up' | 'down' | 'orange' | 'flat'; prov?: boolean; arrow?: string;
}) {
  const valCls = tone === 'up' ? 'text-emerald-600'
    : tone === 'down' ? 'text-rose-600'
    : tone === 'orange' ? 'text-amber-600'
    : tone === 'flat' ? 'text-slate-900'
    : primary ? 'text-primary-700' : 'text-slate-900';
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-card text-center">
      <div className="text-sm font-medium text-slate-600">{label}</div>
      <div className={`text-2xl font-bold tabular-nums mt-1.5 ${valCls}`}>
        {value}{arrow && <span className="ml-0.5">{arrow}</span>}{prov && <ProvMark />}
      </div>
    </div>
  );
}
