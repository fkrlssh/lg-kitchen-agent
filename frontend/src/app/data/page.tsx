'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Loader2, Send, CheckCircle2, Clock, Mail, Upload, FileSpreadsheet, AlertTriangle, XCircle, RefreshCw, CalendarClock,
} from 'lucide-react';

// 상태 4단계 스타일 — 입력완료(녹)/재제출완료(주황)/미제출(빨)/제출오류(빨)
const STATE_STYLE: Record<string, { cls: string; label: string }> = {
  입력완료: { cls: 'text-emerald-600', label: '제출 완료' },
  재제출완료: { cls: 'text-amber-600', label: '재제출 완료' },
  미제출: { cls: 'text-rose-600', label: '미제출' },
  제출오류: { cls: 'text-rose-600', label: '제출 오류' },
};

import PageHeader from '@/components/layout/PageHeader';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import ToastHost, { type ToastData } from '@/components/ui/Toast';
import { lgDataService, type LgLatestStatus, type LgLatestItem } from '@/services/lgDataService';
import { documentsService, type DocPreview } from '@/services/documentsService';
import { areaLabel, ALL_AREAS, STANDARD, MONTH_UNIT } from '@/config/areas';
import { wOf } from '@/config/periods';

function periodLabel(id?: string | null): string {
  if (!id) return '–';
  const m = id.match(/^(\d{4})-(\d{1,2})-(\d+)$/);
  return m ? `${m[1]}년 ${Number(m[2])}월 W${wOf(Number(m[2]), Number(m[3]))}` : id;
}
function fmtLastAt(iso: string | null): string {
  if (!iso) return '—';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso;
}
function fmtSentAt(iso: string | null): string {
  if (!iso) return '';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[2]}-${m[3]}` : iso;
}
const areaName = areaLabel; // 항목 표시 = 한글 라벨(registry 미러 @/config/areas)

// 제출 대상 전 항목 (파생 제외) — 데이터 없어도 항상 이 칸들을 보여준다 (업로드 입구).
// 목록·양식·단위는 registry 미러(@/config/areas)에서.
function emptyDept(area: string): LgLatestItem {
  const std = STANDARD.has(area);
  return {
    항목: area, source: std ? '부서' : '운영자', format: std ? '표준양식' : '별도양식',
    unit: MONTH_UNIT.has(area) ? '월' : '주차', derived: false,
    latest_week: null, latest_month: null, latest_label: '데이터 없음', received: false, last_at: null,
    count: 0, state: '미제출', issues: [],
    missing_weeks: [], missing_months: [], gap_summary: '전체 미제출', has_gap: true,
    gaps: [], requested: false, requested_at: null,
  };
}

export default function PerformancePage() {
  const [st, setSt] = useState<LgLatestStatus | null>(null);
  const [latestPeriod, setLatestPeriod] = useState<string>('');
  const [loading, setLoading] = useState(true);   // 마운트 즉시 fetch → 초기엔 로딩 상태로 시작

  const [toasts, setToasts] = useState<ToastData[]>([]);
  const toast = (ok: boolean, text: string) =>
    setToasts((ts) => [...ts, { id: Date.now() + Math.random(), ok, text }]);

  const [sending, setSending] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pendingReq, setPendingReq] = useState<string[] | null>(null);   // 요청 확인 팝업(보낼 조각 key들)
  const [uploadingArea, setUploadingArea] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ area: string; file: File; summary: DocPreview } | null>(null);
  const [committing, setCommitting] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [s, ps] = await Promise.all([lgDataService.status(), lgDataService.periods()]);
      setSt(s);
      setLatestPeriod(ps[ps.length - 1] || '');
    } catch {
      setSt(null);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const handleAreaSelect = async (area: string, file: File) => {
    setUploadingArea(area);
    try {
      const summary = await documentsService.preview(file, area);
      setPreview({ area, file, summary });
    } catch (e: any) {
      toast(false, e?.response?.data?.detail || `${areaName(area)} 미리보기 실패`);
    } finally {
      setUploadingArea(null);
    }
  };

  const commitUpload = async () => {
    if (!preview) return;
    const { area, file } = preview;
    setCommitting(true);
    try {
      await documentsService.upload(file, '부서 제출', area);
      toast(true, `${areaName(area)} 제출 완료 — 차수 자동 인식`);
      setPreview(null);
      await refresh();
    } catch (e: any) {
      toast(false, e?.response?.data?.detail || `${areaName(area)} 적재 실패`);
    } finally {
      setCommitting(false);
    }
  };

  const sendRequest = async (items?: string[]) => {
    if (!latestPeriod) return;
    if (items && items.length === 0) return;
    setSending(true);
    try {
      const r = await lgDataService.remind(latestPeriod, items);
      toast(true, `요청을 발송했습니다 (${r.sent}건)`);
      setSelected(new Set());
      await refresh();
    } catch (e: any) {
      toast(false, `요청 실패: ${e?.response?.data?.detail || String(e)}`);
    } finally {
      setSending(false);
    }
  };

  // 아직 서버 상태를 못 받았으면(첫 로딩) '데이터 없음'이 아니라 '로딩 중'으로 취급.
  // (st===null 인데 파생값을 계산하면 emptyDept 로 다 채워져 "빠진 데이터 없음"이 잠깐 뜨는 버그 방지)
  const notLoaded = st === null;

  // 전 항목 칸 항상 표시 — 상태가 있으면 그걸로, 없으면 빈 칸(업로드 가능)
  const byArea = new Map((st?.items ?? []).map((it) => [it.항목, it]));
  const deptItems = ALL_AREAS.map((a) => byArea.get(a) ?? emptyDept(a));
  const gapItems = deptItems.filter((it) => !it.derived && it.has_gap);      // 빠진 것 있는 항목
  // 빠진 '조각'(종류·월) 펼치기 — 각각 따로 체크/요청
  const gapPieces = gapItems.flatMap((it) => (it.gaps ?? []).map((g) => ({ ...g, area: it.항목 })));
  const doneCount = deptItems.filter((it) => !it.derived && !it.has_gap).length;
  const missingCount = gapItems.length;                                      // 항목 기준(입력완료 카드)
  // 항목별로 조각 묶기 — 항목당 한 줄(마감 칩 + 월별 차수 칩)로 압축 표시
  const byAreaGaps = new Map<string, typeof gapPieces>();
  for (const g of gapPieces) {
    const arr = byAreaGaps.get(g.area);
    if (arr) arr.push(g); else byAreaGaps.set(g.area, [g]);
  }
  const toggleKey = (key: string) =>
    setSelected((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const toggleAreaSel = (keys: string[]) =>   // 항목명 클릭 = 그 항목 미요청 조각 전체 토글
    setSelected((s) => { const n = new Set(s); const all = keys.length > 0 && keys.every((k) => n.has(k)); keys.forEach((k) => (all ? n.delete(k) : n.add(k))); return n; });
  const chaText = (label: string) => label.replace(/^\d+월\s*/, '') || label;  // "4월 2차"→"2차"
  const pieceByKey = new Map(gapPieces.map((g) => [g.key, g]));               // key→조각 (확인 팝업 라벨용)
  const reqMsg = (keys: string[]) =>                                          // 확인 팝업 메시지(보낼 목록)
    keys.map((k) => { const g = pieceByKey.get(k); return g ? `· ${areaName(g.area)} — ${g.label}` : `· ${k}`; }).join('\n');
  // 상태 헤더 호버용 — 문제 있는(누락/오류) 항목 전체 한눈에. 각 항목별 사유 줄.
  const problemItems = deptItems
    .filter((it) => !it.derived && (it.has_gap || (it.issues ?? []).length > 0))
    .map((it) => ({
      항목: it.항목,
      lines: [
        ...(it.has_gap && it.gap_summary && it.gap_summary !== '—'
          ? [{ text: `미수신 · ${it.gap_summary}`, tone: 'gap' as const }] : []),
        ...(it.issues ?? []).map((x) => ({ text: x, tone: 'issue' as const })),
      ],
    }))
    .filter((p) => p.lines.length > 0);

  return (
    <div className="px-10 py-8 max-w-[1100px] mx-auto">
      <PageHeader title="실적 관리" />

      {/* ── 상단 2블록: 실적 요청 | 입력 완료 ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-card flex flex-col">
          <h2 className="text-sm font-semibold text-slate-900 flex items-center gap-2 mb-3">
            <Mail className="w-4 h-4 text-primary-600" /> 실적 요청
            <span className="ml-auto text-[11px] font-normal text-slate-400">
              현재 {st?.current_label || '–'}
            </span>
          </h2>

          {notLoaded ? (
            <div className="flex-1 flex items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-400 text-sm py-10">
              <Loader2 className="w-4 h-4 mr-2 animate-spin" /> 불러오는 중…
            </div>
          ) : gapPieces.length === 0 ? (
            <div className="flex-1 flex items-center justify-center rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 text-sm py-10">
              <CheckCircle2 className="w-4 h-4 mr-2" /> 빠진 데이터 없음 — 전 항목 최신
            </div>
          ) : (
            <>
              <ul className="space-y-1.5 mb-3 max-h-[168px] overflow-auto pr-1">   {/* 3개 초과 시 스크롤 */}
                {[...byAreaGaps.entries()].map(([area, pcs]) => {
                  const isoOf = (g: typeof pcs[number]) => g.weeks?.[0] ?? 0;   // 조각의 ISO 주차(정렬 기준)
                  // 과거 먼저 — 마감·주차 모두 월 오름차순, 월 내부는 주차 오름차순 (예: 2월 W7 → 4월 W15)
                  const mon = pcs.filter((g) => g.kind === '월계').sort((a, b) => a.월 - b.월);
                  const wkByMonth = new Map<number, typeof pcs>();
                  for (const g of pcs.filter((x) => x.kind === '주차' || x.kind === '부분')) {
                    const a = wkByMonth.get(g.월); if (a) a.push(g); else wkByMonth.set(g.월, [g]);
                  }
                  wkByMonth.forEach((gs) => gs.sort((a, b) => isoOf(a) - isoOf(b)));   // 월 내 주차 오름차순
                  const pendKeys = pcs.filter((g) => !g.requested).map((g) => g.key);
                  // 칩 렌더 — 모두 토글 선택식. 요청함=초록✓(선택=파랑 재발송) / 미선택=흰(마감 호박, 부분 장미)
                  const Chip = (g: typeof pcs[number], text: string, amber: boolean) => {
                    const sel = selected.has(g.key);
                    const partial = g.kind === '부분';
                    const title = partial && g.leaves?.length
                      ? `실적 빈 항목: ${g.leaves.join(', ')} · 선택 후 [선택 요청]`
                      : g.requested ? `요청함${(g.request_count ?? 0) >= 1 ? ` ${g.request_count}회` : ''}${g.requested_at ? ` (${fmtSentAt(g.requested_at)})` : ''} · 선택 후 [선택 요청]으로 재발송` : undefined;
                    const reqN = g.request_count ?? 0;
                    if (g.requested) return (
                      <button key={g.key} onClick={() => toggleKey(g.key)} title={title}
                        className={`inline-flex items-center gap-0.5 px-2.5 py-1 rounded-md text-[11px] border transition ${
                          sel ? 'bg-primary-600 text-white border-primary-600'
                            : 'bg-emerald-50 text-emerald-600 border-emerald-200 hover:border-emerald-400'}`}>
                        <CheckCircle2 className="w-3 h-3" />{text}{reqN >= 2 && <span className="ml-0.5 text-[9px] font-bold opacity-80">{reqN}회</span>}</button>);
                    return (
                      <button key={g.key} onClick={() => toggleKey(g.key)} title={title}
                        className={`px-2.5 py-1 rounded-md text-[11px] border transition ${
                          sel ? 'bg-primary-600 text-white border-primary-600'
                            : partial ? 'bg-rose-50 text-rose-600 border-rose-200 hover:border-rose-400'
                              : amber ? 'bg-amber-50 text-amber-700 border-amber-200 hover:border-amber-400'
                                : 'bg-white text-slate-600 border-slate-200 hover:border-primary-400'}`}>
                        {text}</button>);
                  };
                  return (
                    <li key={area} className="flex items-start gap-2 rounded-lg border border-slate-200 px-3 py-2">
                      <button onClick={() => toggleAreaSel(pendKeys)} title="이 항목 빠진 것 전체 선택"
                        className="font-medium text-sm text-slate-800 w-14 shrink-0 text-left truncate hover:text-primary-600 pt-1">
                        {areaName(area)}</button>
                      {/* 그룹(마감/월)들을 별도 컨테이너로 — 줄바꿈돼도 왼쪽 열 정렬 */}
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 flex-1 min-w-0">
                      {mon.length > 0 && (
                        <span className="inline-flex items-center gap-2 rounded-lg bg-amber-50/60 border border-amber-100 px-2 py-1">
                          <button onClick={() => toggleAreaSel(mon.filter((g) => !g.requested).map((g) => g.key))}
                            title="마감 전체 선택" className="text-[10px] text-amber-600 hover:text-amber-800 font-medium">마감</button>
                          {mon.map((g) => Chip(g, `${g.월}월`, true))}
                        </span>
                      )}
                      {[...wkByMonth.entries()].sort((a, b) => a[0] - b[0]).map(([m, gs]) => (
                        <span key={m} className="inline-flex items-center gap-2 rounded-lg bg-slate-50 border border-slate-100 px-2 py-1">
                          <button onClick={() => toggleAreaSel(gs.filter((g) => !g.requested).map((g) => g.key))}
                            title={`${m}월 전체 선택`} className="text-[10px] text-slate-400 hover:text-primary-600 font-medium">{m}월</button>
                          {gs.map((g) => Chip(g, chaText(g.label), false))}
                        </span>
                      ))}
                      </div>
                    </li>
                  );
                })}
              </ul>
              <div className="flex items-center gap-2">
                {/* 선택 요청 — 고정폭(min-w)으로 카운트 (N) 떠도 크기 안 흔들림 */}
                <button onClick={() => setPendingReq([...selected])} disabled={sending || selected.size === 0}
                  className="inline-flex items-center justify-center gap-2 min-w-[150px] px-4 py-2 rounded-md text-sm font-medium bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-40 transition">
                  {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  <span>선택 요청{selected.size > 0 ? ` (${selected.size})` : ''}</span>
                </button>
                {/* 전체 선택 · 선택 해제 — 붙인 세그먼트 그룹 */}
                <div className="ml-auto inline-flex rounded-md border border-slate-200 overflow-hidden text-sm">
                  <button onClick={() => setSelected(new Set(gapPieces.map((g) => g.key)))} disabled={gapPieces.length === 0}
                    title="이미 보낸 것 포함 전체 선택 (재독촉)"
                    className="px-3.5 py-2 text-slate-600 hover:bg-slate-50 disabled:opacity-40 border-r border-slate-200 transition">전체 선택</button>
                  <button onClick={() => setSelected(new Set())} disabled={selected.size === 0}
                    className="px-3.5 py-2 text-slate-500 hover:bg-slate-50 disabled:opacity-40 transition">선택 해제</button>
                </div>
              </div>
            </>
          )}
        </section>

        <section className="bg-white border border-slate-200 rounded-xl p-5 shadow-card flex flex-col">
          <h2 className="text-sm font-semibold text-slate-900 flex items-center gap-2 mb-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" /> 제출 완료
          </h2>
          <div className="flex items-end gap-2 mb-3">
            <span className="text-4xl font-bold text-slate-900 tabular-nums leading-none">{notLoaded ? '–' : doneCount}</span>
            <span className="text-sm text-slate-400 mb-0.5">/ {deptItems.length} 항목</span>
          </div>
          {/* 미제출 박스 — 남는 높이를 채우며 내용 가운데 분배 (실적 요청 길어지면 같이 커짐) */}
          {/* 박스 높이에 비례해 글씨가 커지고 작아짐 — 컨테이너 쿼리 단위(cqh) + clamp 로 상·하한 */}
          <div className={`flex-1 flex flex-col justify-center rounded-lg border p-5 [container-type:size] ${
            notLoaded ? 'bg-slate-50 text-slate-400 border-slate-200'
              : missingCount ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-emerald-50 text-emerald-700 border-emerald-200'}`}>
            {notLoaded ? (
              <div className="flex items-center justify-center gap-2 text-sm py-6">
                <Loader2 className="w-4 h-4 animate-spin" /> 불러오는 중…
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 mb-2">
                  <Clock className="w-5 h-5 shrink-0" />
                  <span className="font-semibold text-[clamp(0.72rem,5cqh,1rem)]">미제출</span>
                </div>
                <div className="font-bold tabular-nums leading-none text-[clamp(1.5rem,18cqh,3.75rem)]">{missingCount}</div>
                <div className="opacity-80 mt-3 line-clamp-3 break-keep leading-snug text-[clamp(0.68rem,4cqh,0.95rem)]" title={st?.missing.map(areaName).join(', ')}>
                  {missingCount ? st?.missing.map(areaName).join(', ') : '전 항목 최신'}
                </div>
              </>
            )}
          </div>
        </section>
      </div>

      {/* ── 제출 현황 / 업로드 (부서별 최신 차수) ── */}
      <section className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-card">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
          <Upload className="w-4 h-4 text-primary-600" />
          <h2 className="text-sm font-semibold text-slate-900">제출 현황 · 실적 업로드</h2>
        </div>
        <table className="w-full text-sm table-fixed">
          <thead className="bg-slate-50 text-[11px] text-slate-500">
            <tr>
              <th className="px-4 py-2 text-center font-semibold w-[26%]">항목 / 양식</th>
              <th className="px-4 py-2 text-center font-semibold w-[16%]">최신 시점</th>
              <th className="px-4 py-2 text-center font-semibold w-[14%]">
                <span className="relative group inline-flex items-center gap-1 cursor-help">
                  상태 <span className="text-[9px] opacity-50">ⓘ</span>
                  {/* 헤더 호버 = 전체 문제 항목 한눈에 */}
                  <span className="pointer-events-none absolute top-full left-1/2 -translate-x-1/2 mt-2 z-40 w-max max-w-[320px] text-left
                    opacity-0 invisible translate-y-1 group-hover:opacity-100 group-hover:visible group-hover:translate-y-0 transition-all duration-150 ease-out
                    rounded-xl bg-white ring-1 ring-slate-200 shadow-[0_10px_28px_-8px_rgba(15,23,42,0.22)] normal-case">
                    <span className="block px-3 py-2.5 space-y-2">
                      <span className="block text-[9px] font-semibold uppercase tracking-wide text-slate-400">전체 상태 — 미수신·오류 요약</span>
                      {problemItems.length === 0 ? (
                        <span className="block text-[11px] text-emerald-600 font-medium">모든 항목 정상</span>
                      ) : problemItems.map((p) => (
                        <span key={p.항목} className="block">
                          <span className="block text-[11px] font-semibold text-slate-700">{areaName(p.항목)}</span>
                          {p.lines.map((l, i) => (
                            <span key={i} className="flex items-start gap-1.5 text-[10px] leading-snug text-slate-500 pl-1.5">
                              <span className={`mt-[3px] w-1.5 h-1.5 rounded-full flex-shrink-0 ${l.tone === 'gap' ? 'bg-rose-500' : 'bg-amber-500'}`} />
                              <span className="whitespace-pre-wrap break-keep">{l.text}</span>
                            </span>
                          ))}
                        </span>
                      ))}
                    </span>
                  </span>
                </span>
              </th>
              <th className="px-4 py-2 text-center font-semibold w-[16%]">마지막 제출</th>
              <th className="px-4 py-2 text-center font-semibold w-[28%]">업로드 / 관리</th>
            </tr>
          </thead>
          <tbody>
            {notLoaded ? (
              <tr><td colSpan={5} className="px-4 py-12 text-center text-slate-400">
                <span className="inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> 불러오는 중…</span>
              </td></tr>
            ) : (
              deptItems.map((it) => (
                <DeptRow key={it.항목} it={it}
                  uploading={uploadingArea === it.항목}
                  onUpload={(f) => handleAreaSelect(it.항목, f)}
                  onRemind={() => { const gs = it.gaps ?? []; const ks = gs.filter((g) => !g.requested).map((g) => g.key); setPendingReq(ks.length ? ks : gs.map((g) => g.key)); }} />
              ))
            )}
          </tbody>
        </table>
      </section>

      <ConfirmDialog
        open={pendingReq !== null} variant="default" title="실적 요청 발송"
        message={pendingReq ? `아래 데이터에 제출을 요청합니다 (${pendingReq.length}건).\n\n${reqMsg(pendingReq.slice(0, 12))}${pendingReq.length > 12 ? `\n…외 ${pendingReq.length - 12}건` : ''}` : ''}
        confirmLabel="요청 보내기" cancelLabel="취소"
        onConfirm={() => { const ks = pendingReq; setPendingReq(null); if (ks && ks.length) sendRequest(ks); }}
        onCancel={() => setPendingReq(null)} />

      {preview && (
        <PreviewModal area={preview.area} summary={preview.summary} committing={committing}
          onConfirm={commitUpload} onCancel={() => setPreview(null)} />
      )}

      <ToastHost toasts={toasts} onClose={(id) => setToasts((ts) => ts.filter((t) => t.id !== id))} />
    </div>
  );
}

function DeptRow({ it, uploading, onUpload, onRemind }: {
  it: LgLatestItem; uploading: boolean;
  onUpload: (file: File) => void; onRemind: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  return (
    <tr className={`border-t border-slate-100 transition-colors ${dragOver ? 'bg-primary-50 ring-1 ring-primary-300' : 'hover:bg-slate-50/60'}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) onUpload(f); }}
    >
      <td className="px-4 py-3">
        <div className="flex items-center justify-center gap-2">
          <span className="font-medium text-slate-800">{areaName(it.항목)}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${
            it.format === '표준양식' ? 'bg-sky-50 text-sky-600 border-sky-200' : 'bg-violet-50 text-violet-600 border-violet-200'}`}>
            {it.format}
          </span>
        </div>
      </td>
      <td className={`px-4 py-3 text-center text-xs font-medium ${(it.latest_week || it.latest_month) ? 'text-slate-700' : 'text-slate-300'}`}>{it.latest_label}</td>
      <td className="px-4 py-3 text-center">
        {(() => {
          const s = STATE_STYLE[it.state] ?? STATE_STYLE['미제출'];
          const Icon = it.state === '입력완료' ? CheckCircle2
            : it.state === '재제출완료' ? RefreshCw
              : it.state === '제출오류' ? AlertTriangle : XCircle;
          // 상태 배지 하나만 — 세부(누락/오류 사유)는 마우스 호버 말풍선으로.
          const lines: { text: string; tone: 'gap' | 'issue' }[] = [];
          if (it.has_gap && it.gap_summary !== '—') lines.push({ text: it.gap_summary, tone: 'gap' });
          it.issues.forEach((x) => lines.push({ text: x, tone: 'issue' }));
          const hasDetail = lines.length > 0;
          return (
            <div className="inline-flex flex-col items-center gap-0.5">
              <span className={`relative group inline-flex items-center gap-1 text-[11px] font-medium ${s.cls} ${hasDetail ? 'cursor-help' : ''}`}>
                <Icon className="w-3.5 h-3.5" /> {s.label}
                {hasDetail && <span className="text-[9px] opacity-50">ⓘ</span>}
                {hasDetail && (
                  <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-30 w-max max-w-[260px] text-left
                    opacity-0 invisible translate-y-1 group-hover:opacity-100 group-hover:visible group-hover:translate-y-0 transition-all duration-150 ease-out
                    rounded-xl bg-white ring-1 ring-slate-200 shadow-[0_10px_28px_-8px_rgba(15,23,42,0.22)]">
                    <span className="block px-3 py-2 space-y-1.5">
                      <span className="block text-[9px] font-semibold uppercase tracking-wide text-slate-400">{s.label} 사유</span>
                      {lines.map((l, i) => (
                        <span key={i} className="flex items-start gap-2 text-[10.5px] leading-snug text-slate-600">
                          <span className={`mt-[3px] w-1.5 h-1.5 rounded-full flex-shrink-0 ${l.tone === 'gap' ? 'bg-rose-500' : 'bg-amber-500'}`} />
                          <span className="whitespace-pre-wrap break-keep">{l.tone === 'gap' ? `미수신 · ${l.text}` : l.text}</span>
                        </span>
                      ))}
                    </span>
                    {/* 꼬리 — 흰 사각 회전 + 아래·오른쪽 테두리만 보여 카드 외곽선과 연결 */}
                    <span className="absolute top-full left-1/2 -translate-x-1/2 -mt-1 w-2.5 h-2.5 rotate-45 bg-white border-b border-r border-slate-200" />
                  </span>
                )}
              </span>
              {it.requested && (() => {
                const reqMax = Math.max(0, ...(it.gaps ?? []).map((g) => g.request_count ?? 0));
                return (
                  <span className="text-[10px] text-slate-400">
                    요청함{reqMax >= 2 ? <b className="text-amber-600"> {reqMax}회</b> : ''} {it.requested_at ? `(${fmtSentAt(it.requested_at)})` : ''}
                  </span>
                );
              })()}
            </div>
          );
        })()}
      </td>
      <td className="px-4 py-3 text-center text-xs text-slate-500 tabular-nums">{fmtLastAt(it.last_at)}</td>
      <td className="px-4 py-3">
        <div className="flex items-center justify-center gap-2">
          <button onClick={() => fileRef.current?.click()} disabled={uploading}
            title="클릭하거나 파일을 이 행에 드래그 — 차수 자동 인식"
            className={`inline-flex items-center justify-center gap-1.5 w-28 py-1.5 rounded-lg text-xs font-medium border-2 border-dashed transition ${
              dragOver ? 'bg-primary-600 text-white border-primary-600'
                : it.received ? 'text-slate-500 border-slate-300 hover:border-primary-400 hover:text-primary-600'
                  : 'text-primary-700 border-primary-300 bg-primary-50/60 hover:bg-primary-100'}`}>
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            {dragOver ? '여기에 놓기' : '파일 올리기'}
          </button>
          <input ref={fileRef} type="file" accept=".xlsx,.xlsm" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ''; }} />
          <button onClick={onRemind} disabled={!it.has_gap}
            title={!it.has_gap ? '이미 최신' : it.requested ? '다시 보내기' : '제출 요청'}
            className={`p-1.5 rounded transition ${
              !it.has_gap ? 'text-slate-200 cursor-not-allowed'
                : it.requested ? 'text-emerald-500 hover:bg-emerald-50' : 'text-amber-500 hover:bg-amber-50'}`}>
            <Mail className="w-4 h-4" />
          </button>
        </div>
      </td>
    </tr>
  );
}

function PreviewModal({ area, summary, committing, onConfirm, onCancel }: {
  area: string; summary: DocPreview; committing: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  const rows = [
    { label: '항목', value: areaName(area) },
    { label: '인식된 시점', value: summary.latest_label || periodLabel(summary.period_id) },
    { label: '적재 행수', value: `${(summary.rows ?? 0).toLocaleString()}행` },
    { label: '구분', value: summary.kind || (summary.is_new ? '첫 제출' : '재제출') },
  ];
  return (
    <div className={`fixed inset-0 z-[55] flex items-center justify-center bg-slate-900/40 px-4 ${committing ? 'cursor-wait' : ''}`}
      onClick={committing ? undefined : onCancel}>{/* 적재 중엔 바깥 클릭으로 안 닫힘(업로드 끝까지 유지) */}
      <div className="w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-slate-100">
          <h3 className="text-base font-semibold text-slate-900 flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-primary-600" /> 업로드 미리보기
          </h3>
          <p className="text-xs text-slate-500 mt-1">아래 내용으로 적재됩니다. 차수는 파일에서 자동 인식.</p>
        </div>
        <div className="px-5 py-4 space-y-2">
          {rows.map((r) => (
            <div key={r.label} className="flex items-center justify-between text-sm">
              <span className="text-slate-500">{r.label}</span>
              <span className="font-medium text-slate-800">{r.value}</span>
            </div>
          ))}
          {summary.changed_past > 0 && (
            <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700">
              <CalendarClock className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>이미 제출된 과거 실적 <b>{summary.changed_past}개</b>가 이 업로드로 변경됩니다. 정정이 맞는지 확인하세요.</span>
            </div>
          )}
        </div>
        <div className="px-5 py-3 bg-slate-50 border-t border-slate-100 flex items-center justify-between gap-2">
          <span className="text-xs text-amber-600 inline-flex items-center gap-1">
            {committing && (<><Loader2 className="w-3.5 h-3.5 animate-spin" /> 적재 중 — 완료까지 닫지 마세요</>)}
          </span>
          <div className="flex gap-2">
            <button onClick={onCancel} disabled={committing}
              className="px-4 py-2 rounded-md text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed">취소</button>
            <button onClick={onConfirm} disabled={committing}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50 disabled:cursor-wait">
              {committing ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />} 적용
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
