'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Loader2, FileSpreadsheet, FileText, Download, Trash2, FolderOpen,
  ChevronDown, ChevronRight, GitCompare, ArrowRight,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import ConfirmDialog from '@/components/ui/ConfirmDialog';
import {
  documentsService, type DocItem, type TimelineItem, type TimelineCell,
} from '@/services/documentsService';
import { areaLabel, ALL_AREAS, STANDARD } from '@/config/areas';

function fmtAt(iso: string | null): string {
  if (!iso) return '–';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso;
}
const num = (v: number | null) =>
  v == null ? '–' : Math.abs(v) >= 10 ? Math.round(v).toLocaleString()
    : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const tlLabel = (c: TimelineCell) => {
  const wk = c.주차 ? ` ${c.주차}` : '';
  const mo = c.월 != null ? `${c.월}월${wk}` : '';
  return `${c.부서경로} · ${mo}${c.종류 ? ` · ${c.종류}` : ''}`;
};

const SRC_CLS: Record<string, string> = {
  부서: 'bg-sky-50 text-sky-700 border-sky-200',
  운영자: 'bg-violet-50 text-violet-600 border-violet-200',
};
const FMT_LABEL: Record<string, string> = { 부서: '표준양식', 운영자: '별도양식' };
const sourceOf = (area: string): string | null =>
  area === '기타' ? null : STANDARD.has(area) ? '부서' : '운영자';
const monthOf = (pid: string | null): number | null => {
  const m = (pid || '').match(/^\d{4}-(\d{1,2})/);
  return m ? Number(m[1]) : null;
};

export default function DocumentsPage() {
  const [allDocs, setAllDocs] = useState<DocItem[]>([]);
  const [timeline, setTimeline] = useState<Record<string, TimelineItem>>({});
  const [month, setMonth] = useState<number | 'all'>('all');
  const [areaFilter, setAreaFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [pendingDelete, setPendingDelete] = useState<DocItem | null>(null);
  const [deleting, setDeleting] = useState(false);   // 삭제 처리 중: 모달 잠금(업로드 미리보기와 동일 UX)
  const [notice, setNotice] = useState<string | null>(null);   // 삭제 후 인라인 안내(자동 사라짐)
  const [openVer, setOpenVer] = useState<Set<string>>(new Set());      // 파일 버전 펼침 (항목)
  const [openChg, setOpenChg] = useState<Set<string>>(new Set());      // 변동 이력 펼침 (항목)
  const [openCell, setOpenCell] = useState<Set<string>>(new Set());    // 변동 셀 펼침 (셀 key)
  const toggle = (set: Set<string>, k: string, fn: (s: Set<string>) => void) =>
    fn((() => { const n = new Set(set); n.has(k) ? n.delete(k) : n.add(k); return n; })());

  const load = useCallback(async () => {
    setLoading(true);
    const [d, t] = await Promise.allSettled([documentsService.list(), documentsService.timeline()]);
    if (d.status === 'fulfilled') setAllDocs(d.value.documents);
    if (t.status === 'fulfilled') {
      const map: Record<string, TimelineItem> = {};
      t.value.timeline.forEach((x) => { map[x.항목] = x; });
      setTimeline(map);
    }
    setLoading(false);
    return d.status === 'fulfilled' ? d.value.documents : [];
  }, []);

  useEffect(() => {
    (async () => {
      const docs = await load();
      const ms = Array.from(new Set(docs.map((d) => monthOf(d.period_id)).filter((m): m is number => m != null))).sort((a, b) => a - b);
      setMonth(ms.length ? ms[ms.length - 1] : 'all');
    })();
  }, [load]);

  const availMonths = Array.from(new Set(allDocs.map((d) => monthOf(d.period_id)).filter((m): m is number => m != null))).sort((a, b) => a - b);

  // 월 필터로 거른 파일을 항목별로
  const byArea = new Map<string, DocItem[]>();
  for (const d of allDocs.filter((x) => month === 'all' || monthOf(x.period_id) === month)) {
    const k = d.area || '기타';
    (byArea.get(k) ?? byArea.set(k, []).get(k)!).push(d);
  }
  const byDate = (a: DocItem, b: DocItem) => (a.uploaded_at < b.uploaded_at ? 1 : -1);

  // 전 항목 나열 (+ 파일만 있는 '기타')
  const showAreas = areaFilter === 'all'
    ? [...ALL_AREAS, ...(byArea.has('기타') ? ['기타'] : [])]
    : [areaFilter];

  return (
    <div className="px-10 py-8 max-w-[1100px] mx-auto">
      <PageHeader title="문서 관리" />

      <div className="mb-4 flex items-center gap-2">
        <select value={areaFilter} onChange={(e) => setAreaFilter(e.target.value)}
          className="px-2.5 py-1.5 border border-slate-200 rounded-md text-sm bg-white text-slate-700">
          <option value="all">전체 항목</option>
          {ALL_AREAS.map((a) => <option key={a} value={a}>{areaLabel(a)}</option>)}
        </select>
        <select value={month} onChange={(e) => setMonth(e.target.value === 'all' ? 'all' : Number(e.target.value))}
          className="px-2.5 py-1.5 border border-slate-200 rounded-md text-sm bg-white text-slate-700">
          <option value="all">전체 월</option>
          {availMonths.map((m) => <option key={m} value={m}>{m}월</option>)}
        </select>
        {loading && <Loader2 className="w-4 h-4 animate-spin text-slate-400" />}
      </div>

      <div className="space-y-3">
        {showAreas.map((area) => {
          const files = (byArea.get(area) ?? []).sort(byDate);
          const latest = files[0];
          const older = files.slice(1);
          const tl = timeline[area];
          const src = sourceOf(area);
          const verOpen = openVer.has(area);
          const chgOpen = openChg.has(area);
          return (
            <div key={area} className="bg-white border border-slate-200 rounded-xl shadow-card overflow-hidden">
              {/* 헤더 — 항목 / 양식 */}
              <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-100 bg-slate-50/50">
                <span className="text-sm font-semibold text-slate-800">{areaLabel(area)}</span>
                {src && <span className={`text-[10px] px-1.5 py-0.5 rounded border ${SRC_CLS[src]}`}>{FMT_LABEL[src]}</span>}
              </div>

              {/* 파일(버전) */}
              <div className="px-4 py-2.5 border-b border-slate-50">
                {latest ? (
                  <>
                    <div className="flex items-center gap-2">
                      <FileSpreadsheet className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                      <span className="text-sm text-slate-800 truncate flex-1 min-w-0" title={latest.filename}>{latest.filename}</span>
                      <span className="text-[11px] text-slate-400 tabular-nums flex-shrink-0">{fmtAt(latest.uploaded_at)}</span>
                      {older.length > 0 && (
                        <button onClick={() => toggle(openVer, area, setOpenVer)}
                          className="inline-flex items-center gap-0.5 text-[11px] text-primary-600 hover:text-primary-700 font-medium flex-shrink-0">
                          {verOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}{files.length}개 버전
                        </button>
                      )}
                      <a href={documentsService.downloadUrl(latest.id)} title="다운로드" className="p-1.5 rounded text-slate-400 hover:text-primary-600 hover:bg-primary-50 flex-shrink-0">
                        <Download className="w-4 h-4" />
                      </a>
                      <button onClick={() => setPendingDelete(latest)} title="삭제" className="p-1.5 rounded text-slate-300 hover:text-rose-500 hover:bg-rose-50 flex-shrink-0">
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                    {verOpen && older.map((d) => (
                      <div key={d.id} className="flex items-center gap-2 mt-1.5 pl-6 text-slate-500">
                        <FileText className="w-3.5 h-3.5 text-slate-300 flex-shrink-0" />
                        <span className="text-xs truncate flex-1 min-w-0" title={d.filename}>{d.filename}</span>
                        <span className="text-[10px] text-slate-400">이전 버전</span>
                        <span className="text-[10px] tabular-nums">{fmtAt(d.uploaded_at)}</span>
                        <a href={documentsService.downloadUrl(d.id)} title="다운로드" className="p-1 rounded text-slate-300 hover:text-primary-600"><Download className="w-3.5 h-3.5" /></a>
                        <button onClick={() => setPendingDelete(d)} title="삭제" className="p-1 rounded text-slate-200 hover:text-rose-500"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                    ))}
                  </>
                ) : (
                  <span className="text-[12px] text-slate-300">미업로드</span>
                )}
              </div>

              {/* 변동 이력 — 의도적으로 월 필터 미적용(전 기간 전체 표시).
                  파일 월(제출 회차)과 셀 월(데이터 시점)이 다른 축이라, 늦게 도착한
                  과거월 마감 변동을 놓치지 않도록 항상 전체를 보여준다. */}
              <div className="px-4 py-2.5">
                {tl && tl.cells.length > 0 ? (
                  <>
                    <button onClick={() => toggle(openChg, area, setOpenChg)}
                      className="inline-flex items-center gap-1 text-[12px] text-amber-700 font-medium hover:text-amber-800">
                      {chgOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      <GitCompare className="w-3.5 h-3.5" /> 변동 {tl.cells.length}건 <span className="text-slate-400 font-normal">(버전 {tl.versions})</span>
                    </button>
                    {chgOpen && (
                      <div className="mt-1.5 divide-y divide-slate-50">
                        {tl.cells.map((c, i) => {
                          const k = `${area}-${i}`;
                          const cOpen = openCell.has(k);
                          return (
                            <div key={k} className="py-1.5">
                              <button onClick={() => toggle(openCell, k, setOpenCell)} className="w-full flex items-center justify-between gap-3 text-[12px]">
                                <span className="flex items-center gap-1 text-slate-600 truncate min-w-0">
                                  {cOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />}
                                  <span className="truncate" title={tlLabel(c)}>{tlLabel(c)}</span>
                                </span>
                                <span className="flex items-center gap-1.5 flex-shrink-0 tabular-nums">
                                  <span className="text-slate-400">{num(c.최초)}</span>
                                  <ArrowRight className="w-3 h-3 text-slate-300" />
                                  <span className={`font-medium ${(c.현재 ?? 0) < 0 ? 'text-rose-600' : 'text-slate-800'}`}>{num(c.현재)}</span>
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${c.count > 1 ? 'bg-amber-50 text-amber-700' : 'bg-slate-50 text-slate-400'}`}>변동 {c.count}회</span>
                                </span>
                              </button>
                              {cOpen && (
                                <div className="mt-1 ml-5 pl-3 border-l border-slate-200 space-y-1">
                                  {c.events.map((ev, j) => (
                                    <div key={j} className="flex items-center justify-between gap-3 text-[11px] text-slate-500">
                                      <span className="truncate" title={ev.version}>{fmtAt(ev.at)} · {ev.version}</span>
                                      <span className="flex items-center gap-1 tabular-nums flex-shrink-0">
                                        <span className="text-slate-400">{num(ev.old)}</span>
                                        <ArrowRight className="w-2.5 h-2.5 text-slate-300" />
                                        <span className="text-slate-700">{num(ev.new)}</span>
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </>
                ) : (
                  <span className="text-[12px] text-slate-300 inline-flex items-center gap-1"><GitCompare className="w-3.5 h-3.5" /> 변동 없음</span>
                )}
              </div>
            </div>
          );
        })}
        {showAreas.length === 0 && !loading && (
          <div className="bg-white border border-slate-200 rounded-xl p-16 text-center text-slate-400">
            <FolderOpen className="w-8 h-8 mx-auto text-slate-300 mb-2" />
            항목이 없습니다.
          </div>
        )}
      </div>

      <p className="mt-3 text-[11px] text-slate-400">
        파일 삭제 시 보고서 데이터도 함께 정리됩니다 (이전 버전이 있으면 그 버전으로 복원 · 없으면 미수신) · 변동 이력은 업로드(버전업) 시 자동 기록됩니다
      </p>

      <ConfirmDialog
        open={pendingDelete !== null}
        variant="danger"
        title="파일 삭제"
        message={`'${pendingDelete?.filename}' 파일을 삭제합니다.\n최신 버전이면 이전 버전으로 보고서가 복원되고, 마지막 버전이면 해당 항목이 미수신 처리됩니다.\n되돌릴 수 없습니다.`}
        confirmLabel="삭제"
        cancelLabel="취소"
        busy={deleting}
        busyLabel="삭제 중"
        onConfirm={async () => {
          if (!pendingDelete || deleting) return;
          setDeleting(true);
          try {
            const res = await documentsService.remove(pendingDelete.id);
            await load();   // 문서 목록은 즉시 갱신(파일 사라짐)
            if (res.area) {
              const who = areaLabel(res.area);
              const what = res.removed
                ? `${who} 항목이 미수신 처리됩니다`
                : res.reverted_to
                  ? `${who}이(가) 이전 버전으로 복원됩니다`
                  : `${who} 보고서가 갱신됩니다`;
              setNotice(`삭제됨 · ${what} (보고서 반영까지 몇 초 소요)`);
              setTimeout(() => setNotice(null), 6000);
            }
            setPendingDelete(null);
          } finally {
            setDeleting(false);
          }
        }}
        onCancel={() => { if (!deleting) setPendingDelete(null); }}
      />

      {notice && (
        <div className="fixed bottom-6 right-6 z-50 max-w-sm px-4 py-3 rounded-lg bg-slate-800 text-white text-sm shadow-lg">
          {notice}
        </div>
      )}
    </div>
  );
}
