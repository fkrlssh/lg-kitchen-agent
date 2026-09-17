// 항목 레지스트리 (프론트 미러) — 백엔드 src/registry.py 와 1:1 대응.
// 내부 키 = 슬러그(영문, API/CSV 키). 화면 표시 = label(한글).
// ⚠️ LG 가 시트명/라벨을 바꾸면 backend src/registry.py + 이 파일 둘 다 수정
//    (백엔드는 GET /api/lgdata/registry 로도 노출 — 동적 확인용).

export interface AreaInfo {
  slug: string;
  label: string;
  source: '부서' | '운영자' | '파생';
  unit: '주차' | '월';
  derived: boolean;
}

export const AREAS: AreaInfo[] = [
  { slug: 'material_cost',      label: '재료비',                source: '부서',   unit: '주차', derived: false },
  { slug: 'processing_cost',    label: '가공비',                source: '부서',   unit: '주차', derived: false },
  { slug: 'logistics_cost',     label: '물류비',                source: '운영자', unit: '주차', derived: false },
  { slug: 'investment',         label: '투자비',                source: '부서',   unit: '주차', derived: false },
  { slug: 'sales_region1',      label: '매출(지역1)',           source: '운영자', unit: '주차', derived: false },
  { slug: 'sales_region2',      label: '매출(지역2)',           source: '운영자', unit: '월',   derived: false },
  { slug: 'quality',            label: '품질',                  source: '부서',   unit: '주차', derived: false },
  { slug: 'fixed_cost',         label: '고정비',                source: '파생',   unit: '월',   derived: true },
  { slug: 'fixed_div_control',  label: '고정비·사업부',         source: '운영자', unit: '월',   derived: false },
  { slug: 'fixed_prod_control', label: '고정비·생산제판',       source: '운영자', unit: '월',   derived: false },
  { slug: 'fixed_uncontrol',    label: '고정비·UnControl',      source: '운영자', unit: '월',   derived: false },
  { slug: 'fixed_rawdata',      label: '고정비·Rawdata',        source: '부서',   unit: '월',   derived: false },
];

const _BY_SLUG: Record<string, AreaInfo> = Object.fromEntries(AREAS.map((a) => [a.slug, a]));

/** 슬러그 → 표시용 한글 라벨. 미등록(예 '기타')이면 그대로 반환. */
export function areaLabel(slug: string | null | undefined): string {
  if (!slug) return '';
  return _BY_SLUG[slug]?.label ?? slug;
}

/** 파생 항목 슬러그 (보통 고정비 1개) — '합계(고정비 제외)' 등에서 제외. */
export const DERIVED = 'fixed_cost';

/** 제출/수집 대상 = 파생 제외 전 항목(슬러그). 데이터 없어도 화면에 항상 표시. */
export const ALL_AREAS: string[] = AREAS.filter((a) => !a.derived).map((a) => a.slug);

/** 표준양식(부서 직접제출) 슬러그 집합 — 양식 뱃지/검증용. */
export const STANDARD: Set<string> = new Set(AREAS.filter((a) => a.source === '부서').map((a) => a.slug));

/** 월 단위(주차 없음) 슬러그 집합. */
export const MONTH_UNIT: Set<string> = new Set(AREAS.filter((a) => a.unit === '월' && !a.derived).map((a) => a.slug));
