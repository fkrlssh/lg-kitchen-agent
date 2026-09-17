'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Upload, CheckCircle2, Loader2, Send, AlertCircle, MailX, Inbox as InboxIcon,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import { lgDataService, type LgSubmissionResult, type LgReminderDraft } from '@/services/lgDataService';

function periodLabel(id: string): string {
  const m = id.match(/^(\d{4})-(\d{1,2})-(\d)$/);
  return m ? `${m[1]}년 ${Number(m[2])}월 ${m[3]}차` : id;
}

export default function InboxPage() {
  const [periodId, setPeriodId] = useState('2026-06-1');
  const [periods, setPeriods] = useState<string[]>([]);
  const [sub, setSub] = useState<LgSubmissionResult | null>(null);
  const [loading, setLoading] = useState(false);

  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [drafts, setDrafts] = useState<LgReminderDraft[] | null>(null);
  const [reminding, setReminding] = useState(false);
  const [sendState, setSendState] = useState<'idle' | 'sending' | 'sent'>('idle');

  useEffect(() => {
    lgDataService
      .periods()
      .then((ps) => {
        setPeriods(ps);
        setPeriodId((prev) => (ps.includes(prev) ? prev : ps[ps.length - 1] ?? prev));
      })
      .catch(() => {});
  }, []);

  const loadSub = useCallback(async () => {
    setLoading(true);
    try {
      setSub(await lgDataService.submission(periodId));
    } catch {
      setSub(null);
    } finally {
      setLoading(false);
    }
  }, [periodId]);

  useEffect(() => {
    loadSub();
    setDrafts(null);
    setSendState('idle');
    setMsg(null);
  }, [loadSub]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setMsg(null);
    try {
      const r = await lgDataService.upload(file, periodId);
      setMsg({ ok: true, text: `${r.saved_items.length}개 항목 수신 — ${r.rows.toLocaleString()}행 (${r.skipped_sheets.length}개 시트 skip)` });
      await loadSub();
    } catch (e: any) {
      setMsg({ ok: false, text: `실패: ${e?.response?.data?.detail || String(e)}` });
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) handleUpload(f);
  };

  const genDrafts = async () => {
    setReminding(true);
    try {
      const r = await lgDataService.remind(periodId);
      setDrafts(r.drafts);
      setSendState('idle');
    } catch {
      /* noop */
    } finally {
      setReminding(false);
    }
  };

  const send = async () => {
    setSendState('sending');
    await new Promise((r) => setTimeout(r, 800));
    setSendState('sent');
  };

  const received = sub?.items.filter((i) => i.received).length ?? 0;
  const total = sub?.items.length ?? 0;
  const missing = sub?.missing ?? [];

  return (
    <div className="px-10 py-8 max-w-5xl mx-auto">
      <PageHeader eyebrow="키친솔루션 · 데이터 수집" title="제출 관리" />

      {/* 차수 + 요약 */}
      <div className="mb-5 flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-[11px] font-medium text-slate-500 mb-1">차수</label>
          <input
            list="inbox-period-list"
            value={periodId}
            onChange={(e) => setPeriodId(e.target.value)}
            className="w-[200px] px-3 py-2 border border-slate-200 rounded-md text-sm"
            placeholder="2026-06-1"
          />
          <datalist id="inbox-period-list">
            {periods.map((p) => (
              <option key={p} value={p}>
                {periodLabel(p)}
              </option>
            ))}
          </datalist>
        </div>
        <div className="text-sm text-slate-600 pb-2">
          {periodLabel(periodId)} · <span className="font-semibold text-slate-900">{received}/{total}</span> 항목 수신
          {loading && <Loader2 className="inline w-3.5 h-3.5 animate-spin ml-2 text-slate-400" />}
        </div>
      </div>

      {/* 제출 현황 */}
      <div className="mb-5 bg-white rounded-xl border border-slate-200 p-5 shadow-card">
        <div className="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-1.5">
          <InboxIcon className="w-4 h-4 text-slate-400" /> 제출 현황
        </div>
        <div className="flex flex-wrap gap-2">
          {(sub?.items ?? []).map((it) => (
            <span
              key={it.항목}
              className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border ${
                it.received
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                  : 'bg-slate-50 border-slate-200 text-slate-400'
              }`}
            >
              {it.received ? <CheckCircle2 className="w-3.5 h-3.5" /> : <span className="w-3.5 h-3.5 inline-block rounded-full border border-slate-300" />}
              {it.항목}
              <span className="text-[10px]">{it.received ? '수신' : '미수신'}</span>
            </span>
          ))}
          {!sub && !loading && <span className="text-xs text-slate-400">백엔드 연결을 확인하세요.</span>}
        </div>
      </div>

      {/* 첨부 등록 (메일/직접 공통 — 파일 → DB) */}
      <div className="mb-5 bg-white rounded-xl border border-slate-200 p-5 shadow-card">
        <div className="text-sm font-semibold text-slate-900 mb-1">첨부 등록</div>
        <div className="text-[11px] text-slate-500 mb-3">
          부서가 메일로 보낸 첨부(또는 직접 받은 엑셀)를 올리면 파싱되어 DB에 반영됩니다. (메일 자동수신 불가 → 수동 등록)
        </div>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
          className={`h-[64px] flex items-center justify-center gap-2 border-2 border-dashed rounded-lg text-sm cursor-pointer transition ${
            dragOver ? 'border-primary-400 bg-primary-50' : 'border-slate-300 hover:border-slate-400'
          }`}
        >
          {uploading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin text-primary-600" />
              <span className="text-slate-600">파싱 중…</span>
            </>
          ) : (
            <>
              <Upload className="w-4 h-4 text-slate-400" />
              <span className="text-slate-500">엑셀(.xlsx) 드래그 또는 클릭</span>
            </>
          )}
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xlsm"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleUpload(f);
              e.target.value = '';
            }}
          />
        </div>
        {msg && (
          <div
            className={`mt-3 px-3 py-2 rounded-md text-sm border ${
              msg.ok ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-rose-50 border-rose-200 text-rose-700'
            }`}
          >
            {msg.text}
          </div>
        )}
      </div>

      {/* 미수신 독촉 */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-card">
        <div className="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-1.5">
          <MailX className="w-4 h-4 text-rose-500" /> 미수신 독촉
        </div>

        {missing.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-emerald-700">
            <CheckCircle2 className="w-4 h-4" /> 모든 항목이 수신되었습니다.
          </div>
        ) : (
          <>
            <div className="text-xs text-slate-600 mb-2">
              미수신 <span className="font-semibold text-rose-600">{missing.length}건</span> — {missing.join(', ')}
            </div>
            <button
              onClick={genDrafts}
              disabled={reminding}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white rounded-lg text-xs font-medium"
            >
              {reminding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <AlertCircle className="w-3.5 h-3.5" />}
              챗봇 한테 독촉 메일 작성시키기
            </button>

            {drafts && (
              <div className="mt-4 space-y-2">
                <div className="text-[11px] text-slate-500">독촉 메일 초안 {drafts.length}건 (발송은 SMTP 연결 후 실제 전송)</div>
                {drafts.map((d) => (
                  <div key={d.항목} className="border border-slate-200 rounded-lg p-3 bg-slate-50">
                    <div className="text-xs text-slate-500 mb-1">
                      받는 사람: <span className="text-slate-700">{d.to}</span>
                    </div>
                    <div className="text-sm font-medium text-slate-900 mb-1">{d.subject}</div>
                    <div className="text-xs text-slate-600 whitespace-pre-line leading-relaxed">{d.body}</div>
                  </div>
                ))}
                <div className="pt-1">
                  {sendState === 'sent' ? (
                    <span className="inline-flex items-center gap-1.5 px-3 py-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg text-xs font-medium">
                      <CheckCircle2 className="w-3.5 h-3.5" /> {drafts.length}건 발송 완료 (시뮬)
                    </span>
                  ) : (
                    <button
                      onClick={send}
                      disabled={sendState === 'sending'}
                      className="inline-flex items-center gap-1.5 px-3 py-2 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded-lg text-xs font-medium"
                    >
                      {sendState === 'sending' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                      발송 (SMTP 시뮬)
                    </button>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <p className="mt-4 text-[11px] text-slate-400">
        수신 = 항목별 데이터가 DB에 들어온 상태 · 메일 자동수신은 불가(IMAP) → 첨부 수동 등록 · 발송(독촉)은 SMTP로 실제 전송 가능(현재 시뮬)
      </p>
    </div>
  );
}
