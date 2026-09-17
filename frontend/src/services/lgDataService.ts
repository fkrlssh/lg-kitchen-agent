/**
 * LG 양식 데이터 서비스 — 업로드 / 회차·출처 조회 / raw 행 조회.
 * 백엔드 app/api/lgdata.py 미러.
 */
import api from './api';

export interface LgUploadResult {
  period_id: string;
  auto_detected: boolean;
  saved_items: string[];
  rows: number;
  parsed_sheets: Record<string, { rows: number; 데이터종류: string[]; 월수: number }>;
  skipped_sheets: string[];
}

export interface LgRowsResult {
  period_id: string;
  total_all: number;
  total_filtered: number;
  offset: number;
  limit: number;
  columns: string[];
  rows: Record<string, string | number | null>[];
}

export interface LgRowsQuery {
  항목?: string;
  부서?: string;
  월?: number | string;
  종류?: string;
  구분?: string;
  offset?: number;
  limit?: number;
}

export interface LgItemsResult {
  period_id: string;
  items: string[];
  years: number[];
}

export interface LgPivotCell {
  목표: number | null;
  실적: number | null;
  달성률: number | null;
}

export interface LgPivotRow {
  부서경로: string;
  cells: Record<string, LgPivotCell>;
}

export interface LgPivotResult {
  항목: string;
  연도: number | null;
  months: number[];
  rows: LgPivotRow[];
}

export interface LgOverviewRow {
  항목: string;
  cells: Record<string, LgPivotCell>;
  종합: LgPivotCell;
}

export interface LgOverviewResult {
  연도: number | null;
  months: number[];
  rows: LgOverviewRow[];
}

export interface LgMasterRow {
  항목: string;
  derived?: boolean;
  cells: Record<string, LgPivotCell>;
  종합: LgPivotCell;
}

export interface LgMasterResult {
  months: number[];
  rows: LgMasterRow[];
  total: LgMasterRow;       // 합계 (전체, H 포함)
  total_ex: LgMasterRow;    // 합계 (Area_H 제외)
}

// Master 시트형 계층 테이블
// 잠정 = 공식 월계(월 전체실적) 미도착으로 주차값에서 채운 값 (오면 자동 확정)
export interface LgTableCell { 목표: number | null; 실적: number | null; 전년?: number | null; 달성률: number | null; 잠정?: boolean; weeks?: LgAreaWeek[]; chg?: boolean; before?: number | null; }
export interface LgTableRow {
  label: string;
  level: number;   // 0=주항목/합계, 1=하위
  bold: boolean;   // 합계 줄
  area?: string | null;  // 출처 Area (합계는 null)
  cells: Record<string, LgTableCell>;
}
export interface LgMasterTable {
  months: number[];
  current_month?: number;
  rows: LgTableRow[];
}

// 개별 Area 시트 엑셀 그대로 재현 (합계/소계/Rate 행 포함, 부서경로 계층 × 월 + 당월 주차)
export interface LgAreaWeek { 주차: string; 목표: number | null; 실적: number | null; 전년?: number | null; 달성률: number | null; chg?: boolean; before?: number | null; }
export interface LgAreaCell {
  목표: number | null; 실적: number | null; 전년?: number | null; 달성률: number | null;
  잠정?: boolean;   // 공식 월계 미도착 → 주차값 잠정
  weeks: LgAreaWeek[];
  chg?: boolean; before?: number | null;   // 시뮬: 현재 대비 바뀐 셀 + 변경 전 실적
}
export interface LgAreaRow {
  부서경로: string;
  level: number;
  is_subtotal: boolean;   // 합계/소계/롤업 (세로 집계)
  is_rate: boolean;       // Rate(비율) 경로 → % 표기
  pct?: boolean;          // 엑셀 셀 서식 = 퍼센트(0.0%) → 값×100 후 % (is_rate 와 동일 신호)
  dec?: number | null;    // 엑셀 표시 소수 자리수(#,##0=0, 0.0%=1). null=명시 서식 없음(폴백 규칙)
  cells: Record<string, LgAreaCell>;
}
export interface LgAreaTable {
  area: string;
  months: number[];
  current_month?: number;
  rows: LgAreaRow[];
}

// 보고서 운영 — 항목별 월/주차 상세 + 누적/당월 요약
export interface LgPerf { 목표: number | null; 실적: number | null; 차이: number | null; 달성률: number | null; 잠정?: boolean; }
export interface LgWeekCell { 주차: string; 목표: number | null; 실적: number | null; 달성률: number | null; }
export interface LgMonthCell { 목표: number | null; 실적: number | null; 달성률: number | null; 잠정?: boolean; weeks: LgWeekCell[]; }
export interface LgDetailItem {
  항목: string;
  derived: boolean;
  component?: boolean;   // 고정비 하위 4종 — 표시만, 합계 합산 제외(이중계산 방지)
  months: Record<string, LgMonthCell>;
  누적: LgPerf;
  당월: LgPerf;
}
export interface LgMasterChartPoint {
  월: number;
  목표: number; 실적: number; 달성률: number | null;          // 전체(H포함)
  목표_ex: number; 실적_ex: number; 달성률_ex: number | null; // H제외
  잠정?: boolean;     // 그 달 실적(전체)이 공식 월계 미도착으로 주차값 잠정
  잠정_ex?: boolean;  // H제외 실적 잠정
}
export interface LgMasterDetail {
  months: number[];
  current_month: number;
  items: LgDetailItem[];
  summary: {
    누적: LgPerf;          // H제외
    당월: LgPerf;          // H제외
    누적_전체: LgPerf;      // H포함
    당월_전체: LgPerf;      // H포함
    chart: LgMasterChartPoint[];
    shortfall_top3: { 항목: string; 부족: number; 목표: number; 실적: number; 달성률: number | null }[];
    lowest_top3: { 항목: string; 달성률: number | null; 목표: number | null; 실적: number | null }[];
  } | null;
}

export interface LgSubmissionProgress {
  unit: '주차' | '월';
  filled: number;
  expected: number;
}

export interface LgSubmissionItem {
  항목: string;
  source: '부서' | '운영자' | '파생';
  unit: '주차' | '월';
  derived: boolean;
  received: boolean;
  progress: LgSubmissionProgress | null;
  count: number;
  last_at: string | null;
  derived_from?: string[];
}

export interface LgSubmissionResult {
  period_id: string;
  expected: string[];
  received: string[];
  missing: string[];
  items: LgSubmissionItem[];
}

export interface LgConsistencyDiff {
  항목: string;
  부서경로: string;
  연도: number;
  월: number;
  주차: string | null;
  old: number | null;
  new: number | null;
  delta: number | null;
}

export interface LgConsistencyResult {
  prev: string | null;
  curr: string;
  compared: number;
  changed: LgConsistencyDiff[];
  removed: LgConsistencyDiff[];
  no_previous?: boolean;
}

export interface LgReminderDraft {
  항목: string;
  to: string;
  subject: string;
  body: string;
}

export interface LgRemindResult {
  period_id: string;
  sent: number;
  drafts: LgReminderDraft[];
}

// 빠진 데이터 '조각' — 종류·월 단위로 따로 요청 (예: '3월 월계', '4월 2~5차')
export interface LgGap {
  key: string;          // '{area}:{종류}:{월/주차}'
  kind: '월계' | '주차' | '부분';
  월: number;
  label: string;        // '3월 월계' | '4월 2차' | '2월 3차 일부'
  weeks: number[];
  requested: boolean;
  requested_at: string | null;
  request_count?: number;   // 누적 요청 횟수(반복 미제출 가시화)
  n?: number;           // 부분: 빈 셀 수
  leaves?: string[];    // 부분: 빠진 부서경로(어느 항목이 비었는지)
}

// 부서별 '최신 주차' 상태 (실적 관리 화면 — latest-wins)
export interface LgLatestItem {
  항목: string;
  source: '부서' | '운영자' | '파생';
  format: '표준양식' | '별도양식' | '자동';  // 제출 양식 종류 (둘 다 부서 제출)
  unit: '주차' | '월';
  derived: boolean;
  latest_week: number | null;
  latest_month: number | null;
  latest_label: string;       // "5월 3주차" | "5월" | "데이터 없음"
  received: boolean;          // 현재 시점 도달 여부
  last_at: string | null;
  count: number;              // 제출 횟수 (1=입력완료, 2+=재제출완료)
  state: '입력완료' | '재제출완료' | '미제출' | '제출오류' | '파생';
  issues: string[];           // 제출오류 사유 (예: ["W2 누락"]) — 없으면 빈 배열
  // 빠진 데이터 세밀 감지 — 주차 누락 + 지난 달 월계(월 전체실적) 누락 (월계는 늦게 도착)
  missing_weeks: number[];    // 현재 주차까지인데 안 들어온 ISO 주차들
  missing_months: number[];   // 닫힌 달인데 월계 안 들어온 달들
  gap_summary: string;        // "1월 월계, 2월 2~4차" | "전체 미제출" | "—"
  has_gap: boolean;           // 빠진 것 있음 = 요청 대상
  gaps: LgGap[];              // 빠진 조각들 (각각 따로 요청)
  requested: boolean;         // 모든 조각 요청됨 (표 메일버튼용)
  requested_at: string | null;
  // 셀 단위 누락 — 받은 주차 안에 일부 leaf 실적만 빈 '부분 구멍' (issues 에도 문구 포함)
  incomplete?: { 월: number; 주차: number; label: string; n: number; leaves: string[] }[];
  incomplete_cells?: number;
  derived_from?: string[];
}
// [프로토타입] 변경 데이터 시뮬레이션 — 버전 변경(v1→최신)이 항목 대표총계를 어떻게 바꾸나
export interface LgSimPerf { 목표: number; 실적: number; 달성률: number | null; }
export interface LgSimChange {
  부서경로: string; 월: number; 구분?: string | null; 주차?: string | null;
  when?: string;               // 변경 시점 라벨 — 'N월 M차'(주차) 또는 'N월 마감'(월계)
  old: number | null; new: number | null;
}
export interface LgSimVersion { id: string; label?: string | null; at?: string | null; }
// 변경 조각 — 실적요청 칩처럼 차수 단위 선택. key='m{월}'(마감) / 'w{ISO}'(차).
export interface LgSimPiece {
  key: string; kind: '마감' | '차'; 월: number | null; iso?: number; label: string;
}
export interface LgSimItem {
  항목: string;
  before: LgSimPerf;
  after: LgSimPerf;
  changes: LgSimChange[];
  pieces?: LgSimPiece[];       // 차/마감 조각 — 칩 단위 선택용
  period_id?: string | null;   // 변경 시점(회차) — 언제 데이터인지
  at?: string | null;          // 변경 제출 시각
  versions?: LgSimVersion[];   // 적용 버전 선택용 (최신순 아님, 오래된→최신)
}

export interface LgLatestStatus {
  current_week: number | null;
  current_label: string;
  current_month: number | null;
  current_close?: boolean;     // 현재월 마감 시작됨(현재 마일스톤=마감) → 빨간 테두리=월계 컬럼
  expected: string[];         // 제출 대상 전 항목 (H 제외)
  missing: string[];
  items: LgLatestItem[];
}

export const lgDataService = {
  // 부서별 최신 주차 상태
  async status(): Promise<LgLatestStatus> {
    const { data } = await api.get('/api/lgdata/status');
    return data;
  },

  // periodId 생략 시 백엔드가 파일 내용으로 회차 자동 판단
  async upload(file: File, periodId?: string): Promise<LgUploadResult> {
    const fd = new FormData();
    fd.append('file', file);
    if (periodId) fd.append('period_id', periodId);
    const { data } = await api.post('/api/lgdata/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60_000, // 파싱이 오래 걸릴 수 있음
    });
    return data;
  },

  async periods(): Promise<string[]> {
    const { data } = await api.get('/api/lgdata/periods');
    return data.periods ?? [];
  },

  // 보고서 시점 드롭다운용 — latestMonth/year 는 **데이터 기준**(폴더 이름 아님).
  //   presentWeeks = 월별 실제 데이터가 있는 ISO 주차(config 고정 차수 아님, 최신·경계주까지 정확).
  async periodsInfo(): Promise<{ periods: string[]; latestMonth: number | null; year: string; presentWeeks: Record<number, number[]> }> {
    const { data } = await api.get('/api/lgdata/periods');
    return { periods: data.periods ?? [], latestMonth: data.latest_month ?? null,
             year: data.year ?? '2026', presentWeeks: data.present_weeks ?? {} };
  },

  async sources(periodId: string): Promise<string[]> {
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/sources`);
    return data.sources ?? [];
  },

  async rows(periodId: string, query: LgRowsQuery): Promise<LgRowsResult> {
    const params: Record<string, string | number> = {};
    Object.entries(query).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') params[k] = v;
    });
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/rows`, { params });
    return data;
  },

  async items(periodId: string): Promise<LgItemsResult> {
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/items`);
    return data;
  },

  async pivot(periodId: string, 항목: string, 연도?: number): Promise<LgPivotResult> {
    const params: Record<string, string | number> = { 항목 };
    if (연도 !== undefined && 연도 !== null) params['연도'] = 연도;
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/pivot`, { params });
    return data;
  },

  async overview(periodId: string, 연도?: number): Promise<LgOverviewResult> {
    const params: Record<string, string | number> = {};
    if (연도 !== undefined && 연도 !== null) params['연도'] = 연도;
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/overview`, { params });
    return data;
  },

  async master(periodId: string): Promise<LgMasterResult> {
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/master`);
    return data;
  },

  // sim = 변경 적용할 항목 슬러그 목록(시뮬레이션 — 항목별 델타 조립). 생략/빈 배열 = 현재(미적용).
  async masterDetail(periodId: string, sim?: string[]): Promise<LgMasterDetail> {
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/master/detail`,
      { params: sim?.length ? { sim: sim.join(',') } : {} });
    return data;
  },

  async simulate(periodId: string): Promise<{ items: LgSimItem[] }> {
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/simulate`);
    return data;
  },

  async masterTable(periodId: string, sim?: string[]): Promise<LgMasterTable> {
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/master/table`,
      { params: sim?.length ? { sim: sim.join(',') } : {} });
    return data;
  },

  async areaTable(periodId: string, area: string, sim?: string[]): Promise<LgAreaTable> {
    const { data } = await api.get(
      `/api/lgdata/${encodeURIComponent(periodId)}/area/${encodeURIComponent(area)}/table`,
      { params: sim?.length ? { sim: sim.join(',') } : {} });
    return data;
  },

  async submission(periodId: string): Promise<LgSubmissionResult> {
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/submission`);
    return data;
  },

  async consistency(periodId: string, prev?: string): Promise<LgConsistencyResult> {
    const params = prev ? { prev } : {};
    const { data } = await api.get(`/api/lgdata/${encodeURIComponent(periodId)}/consistency`, { params });
    return data;
  },

  // keys = 빠진 조각 key 목록 ('{area}:{종류}:{월}'). 비우면 미요청 조각 전체.
  async remind(periodId: string, keys?: string[]): Promise<LgRemindResult> {
    const { data } = await api.post(`/api/lgdata/${encodeURIComponent(periodId)}/remind`, {
      keys: keys ?? null,
    });
    return data;
  },

  async deleteSource(periodId: string, sourceName: string): Promise<void> {
    await api.delete(
      `/api/lgdata/${encodeURIComponent(periodId)}/sources/${encodeURIComponent(sourceName)}`,
    );
  },
};

export default lgDataService;
