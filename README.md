# LG Kitchen Agent

LG 키친 사업부 공동 개발 — **경영성과 금액 집계 및 Early Sensing Agent** 데모.

> 격주 단위로 7개 비용 카테고리 × 10+ 부서의 실적을 이메일로 받아 집계하던 매뉴얼 프로세스를 자동화.
> Form factor: **풀스택 웹 (FastAPI + Next.js)** · 내부망 전용, **외부 API 호출 금지**.

## 데모 실행 (1분 셋업)

```bash
# 1. 백엔드 (터미널 1)
cd backend
# (의존성 이미 설치되어 있다면 skip) pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000

# 2. 프론트엔드 (터미널 2)
cd frontend
# (의존성 이미 설치되어 있다면 skip) npm install
npm run dev

# 3. 브라우저
open http://localhost:3000
```

### LLM 활용 (선택 — cache 가 이미 있으면 skip)

**LLM 없이 시연 가능** — 두 시나리오의 LLM 응답이 `backend/llm_cache/` 에 사전 생성되어 있어요. 그래도 라이브 LLM 호출 결과를 보고 싶다면:

```bash
# 1. Ollama 설치 + 모델 (사무용 PC 권장: qwen2.5:3b ~2GB)
ollama serve
ollama pull qwen2.5:3b-instruct

# 2. backend/.env 작성 (.env.example 복사)
#    LLM_BASE_URL=http://localhost:11434/v1
#    LLM_MODEL=qwen2.5:3b-instruct

# 3. cache 재생성 (LLM 호출 결과로 덮어씀)
cd backend && rm -rf llm_cache && python -m src.cache_prebuild

# 4. 백엔드 재시작
```

LG 내부망 endpoint 받으면 `.env` 의 `LLM_BASE_URL` 만 LG endpoint 로 바꾸면 됨.

### 데모 흐름

1. **홈** (`/`) — As-Is / To-Be 비교 + 워크플로우 안내. [시작하기] 클릭
2. **이메일 수신함** (`/inbox`) — 시나리오 선택 (정상 / 이상 감지)
   - 부서별 회신 메일 7통 자동 수신 시각화
   - 메일 클릭 시 첨부 엑셀 미리보기
   - 이상 감지 시나리오에서는 미회신 부서 표시
   - **[🤖 자동 취합 및 분석 시작]** 클릭
3. 진행률 모달 (이메일 수신 → 파싱 → 집계 → 이상 감지 → AI 해석 → 보고서 생성)
4. **대시보드** (`/dashboard?taskId=...`)
   - 메트릭 4종 (전체 달성률 / 정상 / 경고 / 위험)
   - AI 분석 요약
   - ① 영역별 실적 집계 (recharts)
   - ② 카테고리별 AI 분석 (LLM 생성)
   - ③ 이상 징후 + AI 해석
   - ④ **이상 항목 근본원인 클러스터 (AI Agent 판단)** — 사고 과정 패널 + 클러스터 시각화
   - ⑤ **미회신 부서 Follow-up 전략 (AI Agent 판단)** — 부서별 전략/우선순위 + LLM 작성 메일 미리보기 모달
   - ⑥ **AI 권장 액션** — 차주 우선순위 3~5건
5. **보고서** (`/reports?taskId=...`)
   - **PPT** (임원 보고, 8~9 슬라이드, 약 93KB) — AI 분석/클러스터/권장 액션 슬라이드 포함
   - **Word** (상세 분석, 약 39KB) — AI Agent 사고 과정 섹션 포함
   - **Excel** (10시트 내외, 약 17KB) — AI 클러스터 / 사고과정 / 전략 / 권장 액션 시트 포함
   - 클릭하면 즉시 다운로드 (백엔드 `/api/reports/{task_id}/download/{format}`)

## 핵심 제약 — 내부망 전용

- **외부 LLM API (`api.anthropic.com`, `api.openai.com`) 호출 절대 금지**
- LLM 호출은 **OpenAI-compatible 클라이언트** + `LLM_BASE_URL` 환경변수 (LG 내부 endpoint 또는 로컬 Ollama)
- LG endpoint 도달 불가 시 **template 기반 mock narrative** 자동 fallback — 데모 자체는 LLM 없이도 동작

## 스택

### Backend
- **FastAPI** + Pydantic + Uvicorn
- **pandas + openpyxl** — 엑셀 파싱/집계
- **python-pptx / python-docx / xlsxwriter** — 보고서 자동 생성
- **matplotlib** — PPT 임베디드 차트
- **openai** — OpenAI-compatible 클라이언트 (내부 endpoint 용)

### Frontend
- **Next.js 14** (App Router) + TypeScript
- **Tailwind CSS** + **Pretendard** 폰트
- **recharts** — 인터랙티브 차트
- **lucide-react** — 아이콘
- **axios** — API 클라이언트

## 디렉토리 구조

```
lg-kitchen-agent/
├── backend/
│   ├── app/                          # FastAPI 얇은 layer
│   │   ├── api/                      # scenarios, ingest, reports, alerts
│   │   ├── services/                 # task_manager, pipeline
│   │   ├── models/schemas.py         # Pydantic 요청/응답
│   │   └── main.py
│   ├── src/                          # 도메인 로직 (HADS 패턴)
│   │   ├── schema.py                 # 카테고리/부서/임계값
│   │   ├── parsing.py                # 엑셀 → DataFrame
│   │   ├── aggregation.py            # 집계 (영역별/부서별/총합)
│   │   ├── sensing.py                # 정상/경고/위험 분류
│   │   ├── narrative.py              # LLM/mock narrative
│   │   ├── docgen/                   # pptx/docx/xlsx builders + matplotlib charts
│   │   └── mock/                     # data_generator + emails
│   ├── mock_data/
│   │   ├── scenario_normal/          # 7 xlsx — 정상 케이스
│   │   └── scenario_anomaly/         # 7 xlsx — 이상 감지
│   └── temp/                         # 생성된 보고서 (per task_id)
├── frontend/
│   └── src/
│       ├── app/{page,inbox,dashboard,reports}/
│       ├── components/{inbox,dashboard,reports,layout,ui}/
│       ├── services/                 # API 클라이언트
│       └── types/                    # 백엔드 스키마 미러
└── docs/requirements/                # LG 제공 자료
```

## LG에 확인 받아야 할 사항 (블로커)

1. **LLM endpoint**: 사내 게이트웨이 URL + 인증 + 모델명 (EXAONE? 오픈웨이트?)
2. **이메일 인프라**: MS Graph (Outlook) vs IMAP, 인증 방식
3. **보고서 양식**: PPT 임원 보고 양식 샘플 (현재 mock 디자인)
4. **부서/카테고리/세부항목 매핑**: 현재 mock data 의 부서명/금액 스케일 검증
5. **이상 감지 임계값**: 현재 < 90% 경고 / < 80% 위험, LG 기준 확인
6. **Deploy 환경**: 자체 서버 / Azure 사내 테넌트 / on-prem k8s

## 보안 / 라이선스

- LGE Internal Use Only — **외부 공개 금지**
- GitHub repo: **private only**
- 모든 LLM 관련 키 / endpoint URL — `.env*` (gitignored), 절대 커밋 금지

## 관련 프로젝트

- `web/lg/AIRTECH` — ES VPD 경쟁사 인텔리전스 RAG PoC
- `web/lg/LG-simul` — 에어컨 3D 시뮬레이터
- `web/changwon/HADS` — 한글 보고서 자동화 (이 프로젝트 구조 패턴 차용)
