/**
 * 문서 관리 서비스 — 만회 대책 등 일반 문서 업로드/목록/다운로드/삭제.
 * 백엔드 app/api/documents.py 미러.
 */
import api from './api';
import { config } from '@/config/env';

export interface DocItem {
  id: string;
  filename: string;
  stored: string;
  category: string;
  period_id: string | null;
  area: string | null;
  size: number;
  uploaded_at: string;
  ingested?: boolean;
  saved_items?: string[];
  rows?: number;
}

export interface DocListResult {
  documents: DocItem[];
  categories: string[];
}

export interface DeleteResult {
  status: string;
  id: string;
  area: string | null;
  reverted_to: string | null;   // 남은 최신 버전으로 되돌림(파일명)
  removed: boolean;             // 마지막 버전 삭제 → 항목 완전 제거(미수신)
  processing: boolean;          // 보고서 재계산 백그라운드 진행 중
}

export interface DocPreview {
  period_id: string;
  latest_label: string;   // 데이터의 실제 최신 시점 (예: '2026년 5월 W18')
  kind: string;           // 구분: 첫 제출 / 신규 시점 / 재제출 (정정) / 재제출
  areas: string[];
  rows: number;
  per_area: Record<string, number>;
  changed_past: number;
  is_new: boolean;
}

// ── 변경 추적 (버전 간 diff) ──
export interface ChangeRow {
  항목: string; 부서경로: string; 연도: number | null; 월: number | null;
  구분: string | null; 주차: string | null; 종류: string | null;
  old: number | null; new: number | null; delta: number | null;
}
export interface ChangeEntry {
  at: string; 항목: string;
  from: { id: string; filename: string; uploaded_at: string | null };
  to: { id: string; filename: string; uploaded_at: string | null };
  summary: { changed: number; added: number; removed: number };
  changed: ChangeRow[]; added: ChangeRow[]; removed: ChangeRow[];
}
export interface VersionItem { id: string; filename: string; uploaded_at: string | null; period_id: string | null; }
export interface CompareResult {
  changed: ChangeRow[]; added: ChangeRow[]; removed: ChangeRow[];
  compared?: number; summary?: { changed: number; added: number; removed: number };
  a?: { id: string; filename: string; uploaded_at: string | null };
  b?: { id: string; filename: string; uploaded_at: string | null };
  area?: string | null; error?: string;
}

// ── 최신 기준 변동 이력 (버전 체인 따라 셀별 최초→현재 + 변동 시점) ──
export interface TimelineEvent { at: string | null; version: string; old: number | null; new: number | null; }
export interface TimelineCell {
  항목: string; 부서경로: string; 연도: number | null; 월: number | null;
  구분: string | null; 주차: string | null; 종류: string | null;
  최초: number | null; 현재: number | null; count: number; events: TimelineEvent[];
}
export interface TimelineItem { 항목: string; versions: number; cells: TimelineCell[]; }

export const documentsService = {
  async list(): Promise<DocListResult> {
    const { data } = await api.get('/api/documents');
    return data;
  },

  async preview(file: File, area?: string): Promise<DocPreview> {
    const fd = new FormData();
    fd.append('file', file);
    if (area) fd.append('area', area);
    const { data } = await api.post('/api/documents/preview', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60_000,
    });
    return data;
  },

  async upload(file: File, category: string, area?: string): Promise<DocItem> {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('category', category);
    if (area) fd.append('area', area);  // 지정 시 그 항목만 적재 (부서별 업로드)
    const { data } = await api.post('/api/documents/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60_000,
    });
    return data;
  },

  downloadUrl(docId: string): string {
    return `${config.apiUrl}/api/documents/${encodeURIComponent(docId)}/download`;
  },

  async remove(docId: string): Promise<DeleteResult> {
    // 삭제 = 동기 처리(응답 전 보고서 데이터 반영 완료). 복원 재적재는 수식 재평가라 수 초 걸려 타임아웃 상향.
    const { data } = await api.delete<DeleteResult>(`/api/documents/${encodeURIComponent(docId)}`, { timeout: 60_000 });
    return data;
  },

  async changelog(limit = 100): Promise<{ feed: ChangeEntry[] }> {
    const { data } = await api.get('/api/documents/changelog', { params: { limit } });
    return data;
  },

  async versions(): Promise<{ versions: Record<string, VersionItem[]> }> {
    const { data } = await api.get('/api/documents/versions');
    return data;
  },

  async compare(docA: string, docB: string): Promise<CompareResult> {
    const { data } = await api.post('/api/documents/compare', { doc_a: docA, doc_b: docB });
    return data;
  },

  async timeline(area?: string): Promise<{ timeline: TimelineItem[] }> {
    const { data } = await api.get('/api/documents/timeline', { params: area ? { area } : {} });
    return data;
  },
};

export default documentsService;
