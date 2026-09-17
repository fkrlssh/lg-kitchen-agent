'use client';

import { useEffect, useMemo, useState } from 'react';
import { Sparkles, ChevronDown } from 'lucide-react';

import { ReportView } from '@/components/reports/ReportView';
import { lgDataService, type LgSimItem } from '@/services/lgDataService';
import { areaLabel } from '@/config/areas';
import { periodLabelW } from '@/config/periods';

const periodLabel = periodLabelW;   // 'YYYY-MM-N' → 'M월 W##' (회차 라벨 통일)
const fmtAt = (iso?: string | null) => {
  const m = (iso || '').match(/^\d{4}-(\d{2})-(\d{2})/);
  return m ? `${m[1]}.${m[2]}` : '';
};
const verLabel = (i: number) => (i === 0 ? '원본' : `수정 ${i}`);   // 버전 인덱스 → 라벨
const chaText = (label: string) => label.replace(/^\d+월\s*/, '') || label;   // "3월 3차"→"3차"

// 변경 시뮬레이션 — 우측 상단 플로팅 패널에서 변경을 '차/마감 조각 칩'(실적요청 칩과 동일 방식)으로
// 펼쳐 차수 단위로 골라 반영. 고른 조각만 ReportView(=보고서 운영 동일 화면)에 즉시 적용·하이라이트.
export default function SimulationPage() {
  const [candidates, setCandidates] = useState<LgSimItem[]>([]);
  const [loaded, setLoaded] = useState(false);                       // 첫 로딩 완료 여부(로딩 중 '변경 없음' 오탐 방지)
  const [sel, setSel] = useState<Set<string>>(new Set());            // `${항목}::${조각key}`
  const [pick, setPick] = useState<Map<string, string>>(new Map());  // 항목 → 적용 버전 문서id
  const [open, setOpen] = useState(true);

  useEffect(() => {
    (async () => {
      const ps = await lgDataService.periods().catch(() => [] as string[]);
      const latest = ps[ps.length - 1];
      if (!latest) { setLoaded(true); return; }
      const r = await lgDataService.simulate(latest).catch(() => ({ items: [] as LgSimItem[] }));
      setCandidates(r.items);
      setLoaded(true);
      const s = new Set<string>();                                   // 기본 = 전 조각 선택
      r.items.forEach((i) => (i.pieces ?? []).forEach((p) => s.add(`${i.항목}::${p.key}`)));
      setSel(s);
      const m = new Map<string, string>();                           // 기본 버전 = 각 항목 최신
      r.items.forEach((i) => { const vs = i.versions ?? []; if (vs.length) m.set(i.항목, vs[vs.length - 1].id); });
      setPick(m);
    })();
  }, []);

  const pk = (area: string, key: string) => `${area}::${key}`;
  const togglePiece = (area: string, key: string) =>
    setSel((s) => { const n = new Set(s); const k = pk(area, key); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const toggleMany = (area: string, keys: string[]) =>     // 그룹/항목 라벨 클릭 = 전체 토글
    setSel((s) => {
      const n = new Set(s); const all = keys.length > 0 && keys.every((k) => n.has(pk(area, k)));
      keys.forEach((k) => (all ? n.delete(pk(area, k)) : n.add(pk(area, k)))); return n;
    });
  const setVer = (area: string, id: string) =>
    setPick((m) => { const n = new Map(m); n.set(area, id); return n; });

  // sim = 항목별 선택 조각 → 'area@docid~k1.k2' (버전 + 조각 선택 반영)
  const sim = useMemo(() => candidates.flatMap((c) => {
    const keys = (c.pieces ?? []).filter((p) => sel.has(pk(c.항목, p.key))).map((p) => p.key);
    if (!keys.length) return [];
    const id = pick.get(c.항목) ?? '';
    return [`${c.항목}@${id}~${keys.join('.')}`];
  }), [candidates, sel, pick]);

  const totalPieces = candidates.reduce((a, c) => a + (c.pieces?.length ?? 0), 0);
  const selectAll = () => {
    const s = new Set<string>();
    candidates.forEach((c) => (c.pieces ?? []).forEach((p) => s.add(pk(c.항목, p.key))));
    setSel(s);
  };

  const panel = (
    <div className="fixed top-5 right-6 z-40 flex flex-col items-end">
      {open ? (
        <div className="w-[320px] rounded-xl border border-indigo-200 bg-white shadow-xl overflow-hidden">
          <div className="flex items-center gap-2 px-3.5 py-2.5 bg-indigo-50 border-b border-indigo-100">
            <Sparkles className="w-4 h-4 text-indigo-600" />
            <span className="text-sm font-semibold text-slate-800">변경 적용</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-600 border border-indigo-200">베타</span>
            <button onClick={() => setOpen(false)} title="접기" className="ml-auto text-slate-400 hover:text-slate-600">
              <ChevronDown className="w-4 h-4" />
            </button>
          </div>
          <div className="px-3.5 py-1.5 text-[11px] text-slate-400 border-b border-slate-100">
            차수·마감 칩을 골라 보고서에 반영
          </div>
          <div className="p-2.5 max-h-[60vh] overflow-auto">
            {!loaded ? (
              <div className="text-[12px] text-slate-400 px-1 py-2">불러오는 중…</div>
            ) : candidates.length === 0 ? (
              <div className="text-[12px] text-slate-400 px-1 py-2">반영할 데이터 변경이 없습니다.</div>
            ) : candidates.map((c) => {
              const pieces = c.pieces ?? [];
              const close = pieces.filter((p) => p.kind === '마감');
              const wkByMonth = new Map<number, typeof pieces>();
              pieces.filter((p) => p.kind === '차').forEach((p) => {
                const m = p.월 ?? 0; const a = wkByMonth.get(m); if (a) a.push(p); else wkByMonth.set(m, [p]);
              });
              const vers = c.versions ?? [];
              const picked = pick.get(c.항목) ?? vers[vers.length - 1]?.id;
              const allKeys = pieces.map((p) => p.key);
              const anySel = allKeys.some((k) => sel.has(pk(c.항목, k)));
              const Chip = (p: typeof pieces[number], text: string, amber: boolean) => {
                const on = sel.has(pk(c.항목, p.key));
                return (
                  <button key={p.key} onClick={() => togglePiece(c.항목, p.key)} title={p.label}
                    className={`px-2.5 py-1 rounded-md text-[11px] border transition ${
                      on ? 'bg-indigo-600 text-white border-indigo-600'
                        : amber ? 'bg-amber-50 text-amber-700 border-amber-200 hover:border-amber-400'
                          : 'bg-white text-slate-600 border-slate-200 hover:border-indigo-400'}`}>
                    {text}</button>);
              };
              return (
                <div key={c.항목}
                  className={`rounded-lg mb-1.5 border px-2.5 py-2 transition ${
                    anySel ? 'bg-indigo-50/50 border-indigo-200' : 'bg-white border-slate-100'}`}>
                  <div className="flex items-center gap-1.5 flex-wrap mb-1.5">
                    <button onClick={() => toggleMany(c.항목, allKeys)} title="이 항목 전체 토글"
                      className="text-sm font-medium text-slate-800 hover:text-indigo-600">{areaLabel(c.항목)}</button>
                    <span className="text-[10px] text-slate-400">
                      {periodLabel(c.period_id)}{c.at ? ` · ${fmtAt(c.at)}` : ''}
                    </span>
                    {vers.length > 1 && (
                      <select value={picked} onChange={(e) => setVer(c.항목, e.target.value)}
                        className="ml-auto text-[10px] border border-slate-200 rounded px-1 py-0.5 bg-white text-slate-600">
                        {vers.map((v, i) => (<option key={v.id} value={v.id} title={v.label ?? ''}>{verLabel(i)}</option>))}
                      </select>
                    )}
                  </div>
                  {pieces.length === 0 ? (
                    <div className="text-[11px] text-slate-400">변경 조각 없음</div>
                  ) : (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                      {close.length > 0 && (
                        <span className="inline-flex items-center gap-2 rounded-lg bg-amber-50/60 border border-amber-100 px-2 py-1">
                          <button onClick={() => toggleMany(c.항목, close.map((p) => p.key))}
                            title="마감 전체" className="text-[10px] text-amber-600 hover:text-amber-800 font-medium">마감</button>
                          {close.map((p) => Chip(p, `${p.월}월`, true))}
                        </span>
                      )}
                      {[...wkByMonth.entries()].map(([m, gs]) => (
                        <span key={m} className="inline-flex items-center gap-2 rounded-lg bg-slate-50 border border-slate-100 px-2 py-1">
                          <button onClick={() => toggleMany(c.항목, gs.map((p) => p.key))}
                            title={`${m}월 전체`} className="text-[10px] text-slate-400 hover:text-indigo-600 font-medium">{m}월</button>
                          {gs.map((p) => Chip(p, chaText(p.label), false))}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {candidates.length > 0 && (
            <div className="flex items-center gap-2 px-3 py-2 border-t border-slate-100">
              <span className="text-[11px] text-slate-400">{sel.size}/{totalPieces} 조각 적용</span>
              <button onClick={() => setSel(new Set())} disabled={sel.size === 0}
                className="ml-auto text-[11px] text-slate-500 hover:text-slate-700 disabled:opacity-40">전체 해제</button>
              <button onClick={selectAll} className="text-[11px] text-indigo-600 hover:text-indigo-800">전체 선택</button>
            </div>
          )}
        </div>
      ) : (
        <button onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-indigo-600 text-white text-sm font-medium shadow-lg hover:bg-indigo-700">
          <Sparkles className="w-4 h-4" /> 변경 적용 {sel.size}/{totalPieces}
        </button>
      )}
    </div>
  );

  return (
    <>
      <ReportView sim={sim} title="변경 시뮬레이션" />
      {panel}
    </>
  );
}
