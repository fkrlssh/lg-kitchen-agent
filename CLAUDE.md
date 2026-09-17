# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

- **What**: 경영성과 금액 집계 및 Early Sensing Agent (Sentinel)
- **공식 프로젝트명** (보고서/대외 노출용): **경영 성과 금액 실시간 모니터링**
- **Domain**: LG Electronics — Kitchen Appliance Division (LGE Internal Use Only)
- **Form factor**: 챗봇 ❌ — **데이터 파이프라인 + 보고서 자동화 + 모니 챗봇(실데이터 Q&A) 보조** ⭕
- **Status**: **AWS EC2 데모 배포 완료 (2026-06-05)** · DEMO_MODE + Docker + nginx basic auth. **LG 협의 회신 진행 중 (~2026-06-10)** — LLM=Azure OpenAI 확정 / 메일=**IMAP 미지원·SMTP 발송만 가능** → **수신은 웹 수동 업로드로 결정** (Graph 자동 수신은 추후) / 배포=웹 사내서버 1대 / 엑셀 양식+레이아웃=금요일 LG 제공 / 미팅=차주 화·목 (LG 창원대 방문).
- **Collaboration**: WDSLab = 개발/기술 지원. LG = 요구사항 정의.
- **Demo URL**: EC2 public IP (ARM64 Ubuntu 24.04 + t4g 인스턴스) · basic auth `demo` · GitHub `ijaehun/lg-kitchen-agent` (private)

### 팀 구성 (보고서/문서 노출용)

| 구분 | 인원 |
|---|---|
| **WDSLab** | 박사과정 이재훈 · 석사과정 이승우 |
| **컴퓨터공학과** | 학부 유동현 · 학부 안병일 |
| **LG전자** | 조민 선임 · 김가희 책임 |

⚠️ WDSLab 은 **박사 이재훈 + 석사 이승우 둘뿐**. 학부생 (유동현·안병일) 은 WDSLab 소속 X → 보고서에 분리 표기 필수.

### 비즈니스 컨텍스트

**주별(매주)** 단위로 비용 카테고리 × 10+ 부서의 실적을 이메일/엑셀로 취합하던 매뉴얼 프로세스를 자동화. (⚠️ 과거 "격주" 로 적혀있었으나 2026-06-22 **주별로 정정** — 회차=주, "N월 M주차". mock 시스템(`mock_data`/`periods.py`)은 별개로 아직 격주 데모.)

- **Input**: 부서별 엑셀 (이메일 첨부)
- **Output**: (1) 영역별 실적 집계 (2) 목표 달성 Sensing (3) 이상 징후 Monitoring (4) 보고자료 자동 생성
- **Reference**: `docs/requirements/01_early-sensing-agent-overview.png`

## 🚨 핵심 제약: 내부망 전용 (CRITICAL)

이 시스템은 **LG 내부망에서 deploy** 됨. 외부 LLM API (`api.anthropic.com`, `api.openai.com`) **호출 절대 불가**.

**규칙:**
- `anthropic` SDK 사용 금지 (외부 호출).
- LLM 호출은 **OpenAI-compatible 클라이언트** (`openai` 패키지) + `LLM_BASE_URL` 환경변수.
- 모든 LLM 관련 설정은 환경변수 — 코드에 하드코딩 금지.
- LG endpoint 도달 불가 시 `src/narrative.py` 의 각 함수가 **template fallback** 자동 적용. 데모는 LLM 없이도 동작.
- **EC2 데모 모드**: `DEMO_MODE=true` 면 LLM 호출 자체 skip → `narrative.py` 각 함수의 template fallback. 데모 데이터는 `setup_weeks.py` 로 생성(`mock_narratives`/`record_narratives.py` 는 2026-06-23 삭제됨). 외부 의존 zero.

## 아키텍처 결정: Deterministic Pipeline + LLM Narrative

**Full LLM agent (tool-use) 가 아님.** 결정론적 파이프라인 + LLM 은 텍스트 생성 + 일부 판단(cluster/strategy)에만.

**Why:**
- 비용 집계는 본질적으로 결정론적 (sum, %, 임계값)
- 임원 보고는 일관성 중요 — LLM 자유도 높으면 숫자 hallucinate 위험
- 디버깅 / 비용 / 보안 검토 측면에서 유리
- 분석 agent (tool-use loop) 는 한 번 만들었다가 **B+ 정리에서 제거** (오염 위험 + 검증 부담)

**적용:** (⚠️ 2026-06-23: 옛 `pipeline.py:run_pipeline` 삭제됨)
- 집계/분류/재현 = 코드로 결정론적 — `src/parsing_lg`(raw 추출) + `store`(CSV DB) + `master_lg`(수식 평가기로 합계/소계 재현) + `aggregate_lg`(master_detail/overview), 오케스트레이션은 `app/api/lgdata.py` 라우터.
- LLM 호출 = `narrative.py` — 챗봇(chat_with_tools) + 7 report 함수(executive_summary 등, 현재 미사용·재사용가치로 보존, template fallback).
- 챗봇 = 실데이터 Q&A tool-use (숫자는 결정론 값만 인용).
- 새 기능 추가 시 결정론적 로직 우선, LLM 은 자연어 출력에만.

## Agent 이름

**비서/챗봇 이름 = "챗봇"** (⚠️ **2026-06-25 LG 요청으로 "모니" → "챗봇" 변경**). 플랫폼명 = "키친솔루션 한계돌파 플랫폼". 구 이름 "모니"/"Sentinel"/"LKS".

화면/코드에서 챗봇을 부를 때 **"챗봇"** 사용. "AI Agent", "AI", 구 "모니"/"Sentinel"/"LKS" 표현 금지. (자세한 규칙: 메모리 `agent_name.md`)
⚠️ **"모니터링"(플랫폼 실시간 모니터링 기능명)은 유지** — 모니 아님. docgen 보고서빌더·wishlist 헤더의 옛 "모니"는 미사용이라 잔존.
⚠️ localStorage 키만 예외 — 소문자 `lks-chat-conversations`/`lks-chat-messages` 는 데이터 호환 위해 그대로 유지.

## Stack

- **Backend**: FastAPI + Pydantic + Uvicorn · pandas + openpyxl · python-pptx + python-docx + xlsxwriter · matplotlib · `openai` (OpenAI-compatible **+ AzureOpenAI**)
- **Frontend**: Next.js 14 (App Router) + TypeScript + Tailwind + Pretendard · recharts · lucide-react · axios
- **LLM**: 개발 = LG **EXAONE 3.5 7.8B** (로컬 Ollama, RTX 4090) · 운영 = **Azure OpenAI** (LG 사내, `LLM_PROVIDER=azure`) — `.env` 4줄로 전환.
- **Future**: PostgreSQL (격주 이력), APScheduler (자동 트리거), MS Graph or IMAP (이메일)

## 디렉토리 구조 (⚠️ 2026-06-05 기준 — 아래 트리는 2026-06-23 삭제분 미반영)

> **삭제됨(2026-06-23)**: `record_narratives.py`, `mock_narratives/`, `mock_data/`, `src/mock/`, `app/services/pipeline.py`+`task_manager.py`, `app/api/{alerts,dashboard,ingest,reports,scenarios}.py`, 프론트 `app/{dashboard,archive,history}/`·`components/dashboard/`·`{MasterOverview,PivotPanel,MasterReport,ProgressModal}`·서비스 `{scenarios,dashboard,alerts,ingest}Service`. `tools.py`=실데이터 5도구(11개 아님). `data/`·`documents/`=정식 추적(gitignore 풀림). `parsing_lg`=ver0.1 Master+Area(마커 폐기).

```
lg-kitchen-agent/
├── docker-compose.yml               # demo 배포 — backend + frontend + nginx 3 컨테이너
├── nginx/
│   ├── nginx.conf                   # / → frontend, /api → backend, 전 경로 basic auth
│   └── htpasswd (gitignored)        # docker run --rm httpd:alpine htpasswd -nbB demo … 로 생성
├── backend/
│   ├── Dockerfile                   # python:3.12-slim + matplotlib 의존성
│   ├── .dockerignore                # .env / tasks / temp 등 제외
│   ├── .env.example                 # 개발용 env (라이브 LLM)
│   ├── .env.demo                    # EC2 데모용 env — DEMO_MODE=true, ALLOWED_ORIGINS=["*"]
│   ├── record_narratives.py         # 격주별 LLM 호출 후 mock_narratives JSON 저장
│   ├── mock_narratives/             # pre-recorded LLM 출력 (6 격주, DEMO_MODE 가 재생)
│   │   └── 2026-{03-2,04-1,04-2,05-1,05-2,06-1}.json
│   ├── app/                         # FastAPI 얇은 layer
│   │   ├── api/
│   │   │   ├── alerts.py            # POST /api/alerts/followup
│   │   │   ├── chat.py              # POST /api/chat
│   │   │   ├── dashboard.py         # GET /api/dashboard/latest (홈 위젯)
│   │   │   ├── ingest.py            # POST /api/ingest, GET /api/ingest/{tid}
│   │   │   ├── lgdata.py            # [LG real] upload/periods/sources/rows/items/pivot/overview/master(detail·table)/area/{area}/table/submission/consistency/remind
│   │   │   ├── reports.py           # GET /api/reports/{tid}/download/{fmt}
│   │   │   └── scenarios.py         # GET /api/scenarios, /inbox, /email/{id}
│   │   ├── services/
│   │   │   ├── pipeline.py          # run_pipeline 결정론 오케스트레이션
│   │   │   └── task_manager.py      # 비동기 task state (메모리 dict + disk JSON)
│   │   ├── models/schemas.py        # Pydantic 요청/응답
│   │   ├── core/config.py           # Settings (DEMO_MODE / RECORD_NARRATIVES 포함)
│   │   └── main.py                  # FastAPI entry, CORS, 라우터 등록
│   ├── src/                         # 도메인 로직 (production-ready)
│   │   ├── schema.py                # 카테고리/부서/임계값
│   │   ├── parsing.py               # 엑셀 → DataFrame
│   │   ├── aggregation.py           # 영역/부서별 집계, missing_departments
│   │   ├── sensing.py               # 정상/경고/위험 분류, anomalies
│   │   ├── periods.py               # 격주 6개 정의 + label 생성 ("2026년 X월 Y차" 형식)
│   │   ├── narrative.py             # LLM 호출 + sanitize + 7 함수 + 챗봇 + record/replay
│   │   ├── tools.py                 # CHAT_TOOLS 11개 + TOOL_FUNCTIONS (챗봇이 호출)
│   │   ├── parsing_lg.py            # [LG real] 실제 양식 파서 (당월>> 마커 → long)
│   │   ├── store.py                 # [LG real] CSV DB — 항목별 분할 저장/조회/병합
│   │   ├── aggregate_lg.py          # [LG real] pivot_achievement 즉석 집계(재현)
│   │   ├── docgen/                  # PPT/Word/Excel 보고서 + 차트
│   │   └── mock/                    # data_generator + emails (mock 이메일 본문/메타)
│   ├── mock_data/                   # 격주 6 폴더 (2026-XX-X) × 7 카테고리 xlsx
│   ├── data/                        # [LG real] 항목별 CSV (gitignored) — store.py 가 기록
│   ├── temp/                        # 생성된 보고서 (per task_id, gitignored, docker volume)
│   ├── tasks/                       # task JSON 메타데이터 (gitignored, docker volume)
│   └── tool_wishlist.md             # 챗에서 "도구 메모: ~~~" 입력으로 누적 (gitignored)
├── frontend/
│   ├── Dockerfile                   # node:20-alpine multi-stage, Next.js standalone
│   ├── .dockerignore
│   ├── next.config.js               # output: 'standalone' (Docker 배포 필수)
│   └── src/
│       ├── app/                     # page.tsx · inbox · data(데이터 업데이트) · dashboard · reports · history · layout
│       ├── components/              # layout/ui/home/inbox/dashboard/reports/chat/data(MasterOverview·PivotPanel)
│       ├── hooks/useChat.ts         # 챗봇 conversation 단위 (Claude desktop 식 history)
│       ├── services/                # api/scenariosService/ingestService/alertsService/chatService/dashboardService
│       ├── types/index.ts           # 백엔드 Pydantic 미러
│       └── config/env.ts            # NEXT_PUBLIC_API_URL — 빈 문자열 = nginx same-origin
└── docs/ (gitignored)               # LG 제공 자료 + deploy_ec2.md — 로컬 only, GitHub 비공개
    ├── deploy_ec2.md                # EC2 배포 절차
    ├── lg_samples/                  # [LG real] 실제 양식 ver0.2 xlsx + 분석문서 + raw_2026.csv
    ├── requirements/                # LG 제공 요구사항 자료
    └── weekly/                      # 교수님 제출용 주차별 진행 보고
        ├── INDEX.md                 # 전체 목차 + 팀 구성 + 프로젝트 배경
        ├── build_report.py          # markdown → Word(.docx) 변환기 (재사용)
        └── {시작월}월{시작일}일_{종료월}월{종료일}일_경영성과팀_보고서.{md,docx}
```

## 큰 결정 (B+ 정리 + 챗봇 강화 + AWS EC2 데모 + Azure adapter + 주차별 보고 + LG 실데이터 파이프라인, 2026-05-26 ~ 2026-06-16)

상세는 메모리 `architecture_b_plus.md`, `aws_ec2_demo.md`, `llm_setup.md`, `demo_strategy.md`, `report_style.md`, `team.md`, `lg_data_pipeline.md` 참고. **⚠️ LG 데이터 파이프라인 최신 상태는 모두 메모리 `lg_data_pipeline.md` 에 — 아래 항목들은 ver0.2 시절이라 일부 outdated.**

**🔵🔵🔵🔵 2026-07-02 (이어서, 긴 세션 — 프론트 숫자표기 전면통일 + 그래프 툴팁 커스텀 + 예측치/미수집 데이터모델. 커밋·푸시·CI/CD·zip. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **프론트 숫자표기 통일**(`ReportView.tsx`): 공통 `fmtAmt`(정수반올림+콤마, |값|<1이면 소수1, 음수 △)·`fmtPct`(소수1+콤마, 음수 △)로 KPI카드·요약리스트·전체표·개별표·그래프툴팁 **전부 통일**. 목표대비차이=부호제거+↑↓+색(목표=실적이면 검은 하이픈). 요약 "미달영향"=차이 |값|+↑↓+방향색(대시보드 차이와 동일), "달성율최저"=신호등색+하위순서(목표/실적). 그래프 축=음수 **부호(−, △아님)**+콤마, 우Y축 색=좌축과 통일. 표는 엑셀 number_format의 **%판정만 유지**하고 자릿수는 규칙으로 통일(dec 무시). 절감형 이상%(-1043.8% 등)는 포맷무관=공식 deferred.
- **커스텀 그래프 툴팁**(`ChartTooltip`, recharts content 교체): 실적=목표대비색(초과녹/미달빨강/동일검정, 음수라도 초과면 △+녹), 달성률=신호등(음수인데 |r|≥100이면 △녹), 표시순서 전체=목표·실적(전체)·달성률(전체)·실적(H제외)·달성률(H제외)/개별=목표·실적·달성률. **△는 음수에만** — 전체 그래프는 값 양수라 △없음이 정상, 개별 절감형 음수달(매출1 전월·물류비1월·품질2/4월·가공비1/4월 등)에만.
- **폰트 셀프호스팅**: globals.css 외부 CDN `@import` → `next/font/local`(PretendardVariable.woff2, `src/app/fonts/`). 내부망 폰트 미표시 버그 + FOUT 해결.
- **로딩 깜빡임 수정**: /data·/simulation 초기 `st===null`을 "요청 없음"으로 오탐 → notLoaded 가드("불러오는 중"). 실적요청 칩=월/주차 오름차순(과거 먼저).
- **예측치/미수집 데이터모델**(핵심, `aggregate_lg`·`store`): ⓐ**마감(월계) 없음+주차 있음** → 주차값으로 잠정(대표총계 수식이 0으로 떨어지는 것까지 `a==0 & 주차≠0` 폴백). ⓑ**완전 미수집(실적 전무)** → 개별 공란 + **전체(합계) 그 달 잠정(불완전)**. ⓒ목표까지 없으면 목표도 공란. `store.mask_missing_actual`(미수집 항목 area_table 실적/목표 공란화, 소계 0잔여 제거) + `fix_prov_current` 확장(전체표 개별행도 실적0/None+주차값 있으면 잠정 마킹+채움). 데모=**물류비 4월 마감제거(4월 잠정)** + 3월 W11(정합성경고, 재료비→물류비 이동), **재료비=정상복원**. 검증: 전체그래프 4월 잠정·전체표 합계=개별 일치·개별 area_table 일치.
- **⚠️** setup_weeks 여러 번 → `data/`·`documents/` churn 큼(정합 위해 전부 커밋). 미해결: 절감형 달성률 공식(deferred).

**🟢 2026-07-02 (짧은 세션, 커밋 ec4cbfd 푸시·CI/CD) — 데모 캐시 재생성. 코드 변경 없음. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **top3 하위항목이 화면서 이상 = stale 캐시 탓**: 디스크 캐시 `data/2026-04-5/_area_tables.json`가 fe2c156 de-collapse **이전** 상태(고정비 사업부내 Control 1개=leaf 9)로 남아있었음. 코드는 이미 정상 → `setup_weeks.py` 재실행으로 캐시 갱신 → 고정비 leaf **9→12**(Control×3+Uncontrol×2, 값 다른 실제 사업단위).
- **leaf 수 전수 재검증**(원본 엑셀): 재료비8·가공비10·물류비5·투자비3·매출1 11·**매출2 7**(제품2 판가개선=목표·실적 둘 다 None 빈 템플릿 행이라 스킵, 8 아님)·품질2·**고정비12** — 전부 실데이터 일치.
- **커밋**: `setup_weeks`가 documents/ 40개 랜덤해시 재생성(11MB churn) → 문서 churn은 checkout/clean 되돌리고 `data/2026-04-5`만 커밋(사용자 선택). 메시지 첫 줄 stray `@`(Bash서 PS here-string 안 먹힘) — force-push는 main pull배포 위험이라 안 함(cosmetic).
- **🔑 교훈**: **area_table 생성 코드(de-collapse/서식 등) 바꾸면 반드시 `setup_weeks.py` 재실행**해야 디스크 캐시(=배포 데모 진실) 반영.
- **📦 코드 압축본(LG 수동 반입용)**: LG 내부망 GitHub 불가 → `git archive HEAD`로 `../lg-kitchen-agent_20260702.zip`(3.6MB, 185파일) 생성. tracked만 포함=실 `.env`·`nginx/htpasswd` 등 secret 제외. 예전에도 동일 방식(`20260701.zip`)으로 메일/USB 반입.
- **커밋 상태**: `ec4cbfd`(data 캐시) 푸시됨. `b3e3b09`(CLAUDE.md 문서 기록) = 로컬만·미푸시(문서 단독 푸시는 CI/CD 낭비 → 다음 코드 변경 때 배치).

**🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴 2026-07-01 (이어서, 긴 세션·테스터 버그리포트 대응·검증에이전트 통과·커밋 fe2c156) — number_format 미러링 + 고정비 de-collapse + IFERROR + 빈행스킵 + top3 모드별/기여leaf + phantom주차 + 신규시점 상태. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **🅐 엑셀 number_format 미러링**: `master_lg._fmt_spec(number_format)`→(pct,dec). `area_table`가 행별 `_row_nf`로 서식 캡처→`pct`/`dec` 실어보냄, `is_rate`를 pct로 확장. 프론트 `fmt(v,rate,dec)`가 그대로 미러(퍼센트 ×100·소수자리·정수). → 매출1 반올림·%, 매출2/품질 정수, 재료비 VI율 % 해결.
- **🅑 고정비 de-collapse**: `area_table` items 키를 경로→**병합블록 시그니처**(block_seq, 라벨 없는 반복블록 사업부내 Control×3 분리) + **leaf-gating**(말단 라벨 재등장은 안 나눔 — 투자비/매출2 dtype순환 leaf 보호) + **빈행 스킵**(ffill dtype가 실데이터 row_a를 빈행으로 덮던 것 → 재료비 제품2 아웃소싱 None 복원). changelog/mark_area_changes 인덱스 매칭(중복 부서경로 안전).
- **IFERROR**: `_strip_iferror`가 `IFERROR(inner,fallback)→(inner)` 벗김 → 투자비 저감율 0%(설비=IFERROR수식) 복원. **전 수식 8748/8748 셀 엑셀캐시 일치 재검증.**
- **phantom 주차 제거**: `store.mask_headline_to_present`/`mask_table_to_present`(빈 템플릿셀 0평가 주차 제거) + `present_weeks_by_month`(드롭다운 데이터기반 ISO) + `target_week` `YYYY-MM-W##` 파싱. → 5월 W18만 있을 때 W19~ phantom·타항목 실적 안 뜸.
- **신규시점 "재제출완료" 버그**: `_submission_kind`/`last_kind` 제출로그 기록 → 신규 시점 제출은 '제출완료'(재제출완료 아님).
- **top3 모드별 + 기여leaf**: `rankTop3`/`modeVal`(누적/월별/분기 KPI와 동일기준) + `contribLeaves`(항목별 기여지표 말단leaf — 재료비=VI금액·투자비=저감금액·나머지=개선금액, 집계컨테이너 SUM_SEG 제외). 전체=8항목, 개별필터=기여leaf.
- **UI**: 문서삭제 모달 잠금(ConfirmDialog busy) · 부서경로 조상셀 border-b(4단↑ 가로선 빠짐 수정) · 누락표시 통일(빈셀+구멍만 '누락') · 데이터기반 주차 드롭다운.
- **⚠️ 미반영**: **백엔드 재시작 + 재업로드**(캐시 재생성, setup_weeks 불필요) 해야 화면 반영. **미커밋/미푸시**. 🅓(누적/월별 "버그")=누적모드 정상(수정 X). known-minor(검증에이전트): mask가 과거월 실목표주차 드롭(cosmetic)·contribLeaves 혼합깊이(스펙대로)·절감형 달성률공식 여전히 deferred.

**🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴 2026-06-30~07-01 (긴 세션·"마지막 수정일"·실사용테스트 기반) — 단일 현재상태 데이터모델 + (월,주차) 경계주 구분 + 미리보기 시점/구분 + 변동이력 added 제외. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **단일 현재상태 데이터모델**(4d66944): 업로드는 한 폴더로 머지(`current_period()=latest_stored_period()`), 시점=데이터 파생 뷰. 삭제 시 이전 버전 되돌림/마지막이면 제거(`store.remove_area`, 동기 처리 — 백그라운드는 연속삭제 레이스라 반려). 삭제 가속=`_load_two` 1회 공유.
- **(월,ISO주차) 쌍 감지 리팩터**(651f72b): 경계주 **4월 W18 ≠ 5월 W18**·**3월 W14 ≠ 4월 W14** 를 값 다르게 각각 추적. `WEEK_MONTH=_build_week_month(2026)`(일~토·목요일 속한 월·W1-53 전연도 자동). 5월 W19 넣으면 현재=5월 W19 + **월형 항목(매출지역2·고정비 4종) 미제출** 전환.
- **미리보기 '인식된 시점' 버그수정**(07-01): `preview_excel`이 옛 `infer_period_id`(solid-month+`WEEK_MONTH[18]=4월`)라 5월 W18 올려도 "4월 W18"로 뭉갬 → 신규 `_df_latest(df)`가 **데이터 실제 월 컬럼** 그대로 `(5,18)→"5월 W18"` + `kind`(첫제출/신규시점/재제출). 프론트 `DocPreview`+PreviewModal.
- **변동이력 added 제외**(07-01): `changelog.revision_timeline`이 신규 셀(W19)까지 변동 집계하던 것 → **`changed`(겹치는 구간 정정)+`removed`만**, `added` 제외(`diff_dfs`가 W19를 주차키 차이로 added 분류).
- **기타**: 달성률 셀색상(전체 표만 100↑녹/95~100주황/95↓빨강)+그래프행 연노랑+잠정 점선, 표 틀고정, 데모 마감 lag 제거(다운로드==보고서), 데이터 없는 항목 공란행(`ensure_report_items`).
- **⚠️ 미완**: 데모 `data/`·`documents/` working tree 오염(테스트 업로드)=파괴적 정리라 **허락 대기**. **백엔드 재시작 필요**(Dropbox `--reload` 놓침). 미결: 절감형 달성률 공식·고정비 partial 롤업·parsing_lg 추가.

**🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴 2026-06-29 (맨 이어서, 커밋 349f990·푸시·CI·EC2 배포 완료) — 수식 평가기 데이터 전수 검증 + 가로 SUM 범위 버그 수정. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **데이터 검증**: 대상 양식 `docs/lg_samples/excel/260624_데이터양식_창원대공유_주차추가_ver0.1.xlsx`로 Master부터 전 항목까지 raw→수식 계산 전수 검증. 방법 = `master_lg._make_evaluator`(평가기) vs 엑셀 자체 캐시값(`data_only=True`)을 **전 시트·전 수식 셀 셀단위 대조**(실파일은 캐시 살아있어 정답지).
- **🐞 가로 SUM 범위 버그 수정**: `고정비_Rawdata`만 138셀 불일치 → 원인 = `ev_range_or_cell`가 범위를 세로(행)로만 순회·컬럼 c1 고정 → 가로 SUM(`=SUM(D5:O5)`)서 첫 칸만 합산. **2D(컬럼×행) 순회로 수정** → **8748/8748 전부 일치**(Master 626 포함 13시트 0불일치). **영향 = 화면 값 0**(버그는 Total 컬럼 P·AC 월가로합에만, 보고서는 월별 세로합만 읽음) — 잠복 버그 선제 수정.
- **보고서 정합 재확인**: 표(`master_table`) 합계(H제외) == 카드/그래프(`master_detail`) 전 월 일치.
- **데이터 흐름(확인)**: ① raw만 읽고 수식 전부 재실행(엑셀 캐시 안 베낌→트림 파일 동작) ② 항목 대표총계(고정비 포함)=엑셀 수식 사슬 따라감(고정비→Rawdata) ③ Master 전체 합계=우리 코드가 항목 직접 합산(엑셀 합계수식 1월만 배선). ⚠️ `master_lg __main__` 자가검증은 구 익명파일 glob라 stale(무시).

**🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴 2026-06-29 (이어서, 긴 세션·전부 푸시·EC2 b30bcaa) — 마감 마일스톤 모델 + 디자인 공통화 + 시뮬 칩 + 라벨 W##. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **마감 마일스톤 모델(핵심)**: 데이터 흐름 = **W1→W2→…→마감**(마감=그 달 최종, 다음 달 늦게 도착). 어느 항목이든 **현재월이 완전 마감(area_table 그 달 잠정 0)되면 현재="N월 마감"**(`current_close`)·**현재월 마감 미완 항목은 "N월 마감" 요청 대상**. `store.latest_status`+`_prov_months_all`(area_table 잠정=마감완성도 단일소스). 데모: 투자비=마감완비(`setup_weeks CLOSED_DEMO`)→"4월 마감", 나머지 4월 잠정→요청.
- **per-item 빨간 테두리(현재 데이터 위치)**: 각 항목 표=그 항목 실제 위치(마감=월계 컬럼/진행중=W## 컬럼, **접히면 그 달 월계 컬럼 폴백**), 전체 표=전체 현재. ReportView `areaRed`(latest_label 파싱)/`gMonth·gWeek`.
- **디자인 공통화**: 전체 표·각 항목 표가 **별도 컴포넌트**라 계속 어긋남 → 각 항목 표 기준 공유 상수/헬퍼(`SHEET_TBL/STK/TH_GROUP/TH_SUB/TD`·`sheetWeekBox`·`sheetDivider`). ⚠️**border-separate 에선 `<tr>` border 무시**→가로 구분선 전부 셀(td)에. 합계행 고정열 반투명bg→스크롤 겹침→불투명.
- **시뮬 칩(차/마감 조각선택)**: `/simulation` 패널을 실적요청 칩처럼 마감(`m{월}`)/차(`w{ISO}`) 조각 단위 선택. `changelog._change_pieces`/`_apply_pieces`, `_sim_picks` `area@docid~k1.k2`. ⚠️월계·주차 독립(주차변경=월계 안 움직임).
- **잠정 ※ 호버 = 상태 카드**(흰카드+불릿, 표·요약 둘 다). ⚠️표 가로스크롤 컨테이너라 셀 안 카드는 잘림 주의.
- **#1 고정비 컴포넌트 교차오염 해결**: LG=4컴포넌트 각각 풀워크북 파일(확정). `store._merged_component_source`=나머지 컴포넌트 최신 시트 병합 재평가(master_lg 수식평가). 합성+e2e 통과.
- **라벨/UI**: 회차 N월M차→**N월 W##**(`config/periods.ts` 공유, 경계주 W14=3·4월, 한 주=일~토 `week_dates` W1=2025-12-28). 주차 드롭다운 ‘W18’. ‘월계’→**‘마감’**. 실적요청 버튼 정리+**요청 횟수**. parsing_lg **dtype ffill**(invest 11→22). 휴지통/문서설명 제거·‘입력완료’→‘제출 완료’·상태헤더 호버.
- **미결**: 절감형 달성률 공식(LG)·전체 표 빨간테두리 per-item 여부(사용자 결정 대기)·고정비 partial 롤업·parsing_lg 추가.

**🔴🔴🔴🔴🔴🔴🔴🔴🔴 2026-06-29 변경 시뮬레이션 탭(실사용 배선) + 당월 표=그래프 정합 + 교차오염 방지 (오전). 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **변경 시뮬레이션 `/simulation` 탭(신규)**: 보고서운영과 **동일 화면**(보고서 본문을 `components/reports/ReportView.tsx`로 추출 → `/reports`·`/simulation` 공유) + **우측 상단 플로팅 패널**(항목별 체크박스·시점(회차·날짜)·변경 셀·**적용 버전 드롭다운**(원본/수정N)·변경 시점 라벨 차/마감). 표 변경 셀 **하이라이트**(chg/before 툴팁, 남보라). 사이드바 4번째 메뉴.
- **실사용 배선**: 합본 스냅샷 X → 각 항목의 **실제 (선택)버전 문서에서 '변경월만' 조립**(`changelog.compose_*` = 현재 캐시 ⊕ 선택항목 변경월 셀 교체 + 합계 재합산, per-doc 사이드카 캐시 `documents/_headlines·_doc_mtables·_doc_atables`). sim 쿼리=`area@docid`. 부서가 항목마다 다른 파일 올려도 자동 반영. **캐시 조립이라 즉시**(엑셀 재계산 X). setup_weeks 가 워밍.
- **당월(잠정) 표=그래프 완전 정합**: master_detail(카드/그래프)은 월계 미도착 시 마지막 주차값으로 채우는데 표(master_lg)는 합계행이 0으로 떨어져 4월 표(2210)≠그래프(1983)였음. `store.fix_prov_current`(잠정 셀=마지막 주차값, 닫힌 달 무관) + **`store.sync_bold_to_detail`(표 합계행 = master_detail = 엑셀 Master 합계 미러 → 단일 진실원천)**. 엑셀 합계 수식이 매출_지역2 포함 확인. 전 월 표=카드=그래프 일치(시뮬 포함).
- **교차오염 방지**: `save_excel(only_area)` 시 보고서 캐시를 '전체 덮기'→**'항목별 머지'**(`_affected_areas`, headline/master_table 합계재합산/area_tables). A 파일 올려도 그 안 낡은 B 시트가 B 캐시 안 덮음(합성 테스트 통과). 잔여: 고정비(파생) 컴포넌트 개별파일이면 롤업은 마지막 파일 기준(LG 고정비 파일구조 확정 후).
- **정리/기타**: 죽은 컴포넌트 10개·죽은 타입 26개·`store.compose_*` 제거(tsc 통과). 실적관리 **삭제 버튼** 완성. 재료비 데모 fix(G29/G33=대표총계 닿는 셀). **미결**: sales_region2 월형 처리는 sync로 해결됨 / 절감형 달성률 공식·parsing_lg dtype(기존, LG)·고정비 컴포넌트 교차오염.

**🔴🔴🔴🔴🔴🔴🔴🔴 2026-06-28 셀 단위 누락 감지 + 회차 정밀차수 + 상태 말풍선. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **셀 단위 누락(부분 구멍) 감지**: 받은 주차 안에서 한 leaf(부서경로)가 활동구간 사이인데 그 주차만 실적 빔 = 진짜 누락. ⚠️**area_table(수식 평가본) 기준**(raw CSV는 수식 셀을 버려 오판 → 버그 수정). `store._incomplete_cells`(leaves 동반)→`latest_status` issues/`incomplete[]`. **요청 조각 `{area}:부분:{ISO}`** 추가(메일에 빠진 항목명, `_piece_sig` 조각 dict 리팩→채워지면 자동해제). 보고서 `/reports` **빈 셀 하이라이트**(AreaSheetTable incCells) + 누락 배너. "어디 빠졌나" leaf명 표기.
- **회차 폴더명 정밀 차수**: `infer_period_id` 거친 1/2차 → 정밀(월중 몇째 주, `WEEK_MONTH[w][1]`). `setup_weeks PERIOD=2026-04-5`. 보고서 드롭다운·`target_week`는 이미 정밀(무손상).
- **변동이력 cap** `_ROW_CAP=2000`. **(확인) 변동이력에 빈 셀→값(added) 포함됨**.
- **`/data` 상태칸 UX**: 텍스트 줄 제거 → 배지+ⓘ+**흰 카드 말풍선**(호버, 색점=미수신 장미/오류 호박). 데모 진짜 빈 셀 1개(`setup_weeks` HOLE=품질 2월2차). **문서관리 변동이력=월 필터 미적용**(전 기간, 결정). **미결**: 절감형 달성률 공식·월형 현재월 마감·parsing_lg dtype·보고서 통째 시점비교(LG 미팅 후).

**🔴🔴🔴🔴🔴🔴🔴 2026-06-27~28 실적 요청 조각화/UI + 정합성 경고 + 변경 이력→문서관리 통합. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **/data 실적 요청**: 빠진 것을 **조각(월계=종류·월 / 주차=차수별 `{area}:주차:{ISO}`)** 으로 → **항목당 한 줄 칩**(마감/월 그룹 박스, 그룹라벨·항목명 클릭=전체선택). **요청 확인 팝업**, 재발송도 선택식, 선택 해제, 스크롤(max 3), 입력완료 박스 글씨 **cqh 스케일**. 요청추적=`_remindlog` 조각 key별.
- **정합성 경고**: 마감(월계) 든 달의 빠진 주차도 **요청 가능** + **"N월 마감 있으나 주차 불완전"=제출오류** 표시.
- **변경 이력→문서관리 통합**: `changelog.revision_timeline`(셀별 최초→현재+시점, **changelog 집계=빠름**, 재파싱X) + `/api/documents/timeline`. **`/documents` 재작성=항목별 [파일(버전)+변동이력] 한 화면(전 항목)**. **`/changes`·"변경 추적" 메뉴 삭제**(흡수). `setup_weeks`가 `make_change_samples`로 v2 생성(재적재해도 변동 이력 유지). 사이드바=실적관리/보고서운영/문서관리.
- **미결**: 문서관리 월필터 vs 변동이력 스코프(4월 선택해도 3월 변동 나옴) · `record_on_upload` changed[:50] cap · 보고서 통째 시점비교 보류(LG 미팅 후).

**🔴🔴🔴🔴🔴🔴 2026-06-26(이어서) 마감 실적 lag 잠정 + /data 빠진 데이터 요청. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **도메인**: 각 월 = 주차값(W1·W2…) 진행 중 + **마감 실적(월계)은 다음 달 2차쯤 늦게** 도착. 규칙 = **마감 있으면 확정 / 없으면 주차 마지막값으로 잠정**(현재월 무조건 잠정은 사용자 반려).
- **/data 실적 요청**: 빠진 것 세밀 감지 = 누락 주차 + **닫힌 달인데 안 온 월계**. **조각(piece=종류·월) 단위 체크리스트**로 각각 따로 요청(예 품질 "3월 월계"·"4월 2~5차" 독립). 요청 추적(`_remindlog.json` 조각 key 단위, 서명 일치 → 데이터/내용 바뀌면 자동 해제, [다시 보내기]). `store.latest_status`+`_gap_pieces`, lgdata remind=keys.
- **/reports 잠정 통일**: 월계 없어 주차값으로 채운 셀 `잠정` 마킹 → 표(※)·카드(※)·그래프(연한 막대) 동일. master_lg/aggregate_lg + **headline 0행 버그수정**(빈 셀 0행 만들어 카드=0 vs 표=잠정 어긋나던 것 → 실적 월계 빈 셀이면 행 생략, 목표는 항상 emit=축 1~12 유지).
- **데모 사실화** `setup_weeks`: 마감 성숙도(M월 마감=(M+1)월 2차 도착)로 각 항목 미성숙 달 마감 비움. 세 경로 합집합(leaf=/data·대표총계=전체종합·행단위 실적행=개별그래프행), 시트구조 무관 → 전 주차항목 4월 잠정·품질 3·4월. **🆕 주차별 전년**(`_weeks_at`, 양식에 주차 전년 존재).
- **미결**: 절감형 달성률 공식·월형 항목 현재월 마감(주차 폴백 불가)·parsing_lg dtype.

**🔴🔴🔴🔴🔴 2026-06-26 보고서 마감 폴리시 — 항목별 그래프 8개 + 분기 현황 + 정합성 수정. 상세는 메모리 `lg_data_pipeline.md` 맨 위.**
- **항목별 그래프 8개 정의**(`GRAPH_ROW`=slug→부서경로 행, areaTbl 에서 소싱 — 투자비처럼 headline 아닌 행도 OK). 대부분 개선금액/절감액(절감형).
- **분기 현황 모드**(누적/월별/분기 토글, 분기=3개월 합, 분기→월 펼침, W까진 안 감). 마감 전 달=최신값.
- **🔑 정합성 수정**: `trim_headline_to_period`가 당월 월계를 주차값으로 치환하던 것 제거 → 표(`trim_table_to_period`)와 통일. **전체 표=카드=그래프 누적 일치**(전엔 4월 실적 1422 vs 1983 어긋남). 카드=그래프 동일소스(전체 카드=전체 g_full).
- **전체 표 누적 모드 = 진짜 누적**. **음수=세모(△)+빨강**. **그래프 행 핑크 음영**. 달성률 신호등(초록/빨강) 제거. 그래프 제목 복귀+표 제목 제거.
- **⚠️ store.py trim 변경 → 백엔드 재시작 필요.** 미결: 절감형 달성률 공식(LG)·마감 지연·parsing_lg dtype.

**🔴🔴🔴🔴 2026-06-25 보고서 개선 + 전년동기대비 + 변경추적(신규) + 대표총계 점검 + 모니→챗봇. 상세는 메모리 `lg_data_pipeline.md` 맨 위 블록.**
- **보고서 `/reports`**: 누적/월별 그래프 분리(누적=러닝합/월별=per-month) · 개별 그래프=headline(대표총계) 막대+달성률 꺾은선 · 표 소수점(10↑정수/10↓2자리/비율1자리) · **음수=빨강** · 전체펼치기/접기 버튼 · 월+주차 드롭다운(N차(W##)).
- **🔑 대표총계 점검**: Master는 우리가 합친게 아니라 **LG Master 직접 파싱**(수식 cross-sheet 평가). **전 항목 대표 = "절감액"**(개선금액/저감금액/VI금액) — **이 보고서 = 절감 성과 모니터링**. 값 작고/음수도 정상, **계산 다 맞음**. 남은 건 **절감형(절감액) 달성률% 공식 정의 1개**(LG 도메인, deferred).
- **전년동기대비**: master_lg 전년 실적 추출(row-dtype row_prev + year-block), 표에 전년 행. 연도 하드코딩X(2027 자동이월).
- **버그수정**: VI율 4자리 반올림·is_rate=leaf판정 · dtype ffill(투자비/매출2 실적누락) · 고정비 테이블 캐시. ⚠️parsing_lg엔 dtype ffill 미적용(별개).
- **환율**: 가공비/물류비 환율 **수식** 동적계산 검증(새 환율 파일 → 자동 재계산). 투자비=원화.
- **🆕 변경추적**: 문서 버전간 셀 diff — `src/changelog.py` + `documents.py`(/changelog·/versions·/compare)+업로드훅 + 프론트 `/changes` 페이지 + 사이드 메뉴 "변경 추적".
- **모니 → 챗봇** rename(LG 요청). **미결**: 절감형 달성률 공식·parsing_lg dtype·마감 지연 처리·월별만 W펼치기.

**🔴🔴🔴 2026-06-24 신 양식 전면 마이그레이션 — 항목 식별이 `Area_A~L` → 영문 슬러그(`material_cost` 등)로 전환. 상세는 메모리 `lg_data_pipeline.md` 맨 위 블록.**
- LG 신규 양식(`260624_…주차추가_ver0.1.xlsx`): 시트명 **한글 실명**(재료비/가공비/…/고정비) + 월별 주차 추가 + 1~4월 데이터. 사용자: "신 양식으로 다 만들자".
- **신규 `src/registry.py` = 단일 진실원천**: 12항목 slug↔sheet↔label(한글)↔meta. **LG가 시트명 바꾸면 registry.py `sheet` 값만 수정.** 백엔드 전부 슬러그로 항목 식별(`항목`=slug), 시트명 해석은 워크북 경계에서만. `master_lg` 시트참조 정규식 동적화(한글·쉼표 시트 대응). `store.WEEK_MONTH` 신스킴(1월W1-5~4월W14-18). 프론트 `config/areas.ts`=registry 미러 + `areaLabel(slug)`, API `GET /api/lgdata/registry`. 데모=`setup_weeks.py` 재적재(회차 `2026-04-2`). **검증: 엑셀 캐시값 정확일치 + 라이브 HTTP. 미커밋(working tree).**
- ⚠️ 절감형(음수목표) 달성률 = **여전히 deferred**. 5월+ WEEK_MONTH 미매핑(데이터 오면 확장). GRAPH_EXCLUDE_SEGS 비움(LG 대시보드 피드백 후 정교화).

**🔴🔴 2026-06-23 대규모 변경 — 아래 "큰 결정" 히스토리 + Mock vs Real + 챗봇 섹션 상당수 STALE. 현재 진실은 메모리 `lg_data_pipeline.md` 맨 위 블록.**
- **① 보고서 월 네비게이션**: `/reports` 드롭다운 **차수→월(1~최신월)**. M월 선택=그 달 시점(전체현황 1..M / 당월 M월 주차). `master_lg`가 모든 월 주차 저장, `store.target_month/trim_table_to_month`, lgdata 엔드포인트 월컷. period_id `"2026-05"`(2-part) 지원.
- **② mock/옛 파이프라인 전면 삭제**: **삭제됨** — `app/services/pipeline.py`·`task_manager.py`, 라우터 `scenarios/dashboard/alerts/ingest/reports`, `src/mock/`·`mock_data/`·`mock_narratives/`·`record_narratives.py`, 프론트 죽은페이지(dashboard/archive/history)+컴포넌트(components/dashboard/*, MasterOverview·PivotPanel·MasterReport, ProgressModal)+서비스(scenarios/dashboard/alerts/ingestService). backend 29 routes. **유지**(미사용·재사용가치): narrative 7 report함수(template fallback) + `src/docgen`.
- **③ 모니 챗봇 = 실데이터 Q&A**: mock 도구 폐기 → 실데이터 도구 **5개**(get_status/get_achievement/get_risks/navigate/remind), store+aggregate_lg 인용. 하이브리드(결정론 매칭 우선→LLM tool-use). 격주/scenario/task_id/분석실행 개념 폐기. 숫자는 결정론 값만 인용. RAG 보류.
- **④ 후속 수정(같은날, 전부 push·EC2배포)**: documents 버전버그 FIX(area+period_id 한정) · 보고서 기본월 버그 FIX(periodId '2026-06' 미래월→최신월 5월, 안 그러면 그래프·표가 6월로 뜸) · 챗UI 정리(빠른명령 중복제거, 헤더부제 제거, 이력 항상1개+X버튼) · 챗봇 검토(절감형 음수목표 모순 제거=비율보류, 없는항목 안내). ⚠️**절감형(목표 음수) 달성률 공식 = deferred**(LG 협의 필요, /reports도 동일).
- ⚠️ **데모데이터(`data/`·`documents/`) = 2026-06-23 gitignore 풀고 정식 추적 전환** (블라인드 데모라 커밋, EC2 월네비용). 실데이터 들어오면 다시 ignore 검토.
- **⑤ 마무리 폴리시(2026-06-24)**: 월네비 차트 ≤M 클립(전체·개별·Area 3곳, 표와 일관) · CI action 버전업(checkout@v5/setup-node@v5/setup-python@v6, Node20 해소) · **EC2 IP 43.202.253.42로 변경**(구 15.165.37.24, GitHub Secret `EC2_HOST` 갱신=`gh secret set`, yml 무관).
- **📋 다음 세션 계획**: 폴리시 거의 완료, 남은 건 LG 인풋 대기. 🟡**LG 미팅 후 묶음**(절감형 달성률 공식·Azure 키 전환·운영자원천 양식 어댑터·Rate 스케일·레이아웃) → 🔵**큰 기능**(부분제출 정확성·RAG 문서Q&A·자동수신/스케줄러·livestore). 상세 메모리 `lg_data_pipeline.md` 맨 위.

**⭐⭐ 주별 전환 + 부서별 최신 모델 + 실적/문서관리 재작성 (2026-06-22)** — 상세 메모리 `lg_data_pipeline.md`
- **격주 → 주별(매주)**: 회차=주("N월 M주차"). 주↔월 매핑 `store.WEEK_MONTH`(경계주 W14·W22=새 달 1주차). `week_label`.
- **부서별 최신(latest-wins)**: 회차별관리 X, 각 부서 최신 한 벌. 현재주차=가장 앞선 부서 자동, 뒤처진 부서=미제출(부서별 시점 달라도 정상). 새 값이 진실(과거값 변경은 표시만).
- **"운영자 입력" 폐기**: 전 항목(A~L, H제외=11) 부서제출+독촉 대상(다 부서가 메일로 보내고 운영자가 업로드). 차이는 양식뿐 — **표준양식**(A·B·D·G·L)/**별도양식**(C·E·F·I·J·K). H=파생. `store.area_format`.
- **실적관리 `/data`** 재작성: `store.latest_status` + `GET /api/lgdata/status`. 부서|양식뱃지|최신시점|상태|업로드. 전 항목 항상 표시(없으면 미수집). 디자인=기존 느낌 유지, 값 가운데정렬.
- **문서관리 `/documents`** 재작성: 이름 자동정규화(`store.submission_filename`→`{부서}_{주차}_제출.xlsx`), 재업로드=`_v2` 버전, 깔끔한 표(부서당 한 줄+버전 펼침), 전 항목+미업로드.
- **신규 `backend/setup_weeks.py`**: 데모(부서별 다른 주차, data+docstore 둘 다). `app/api/documents.py`(정규화+버전).
- **⚠️ 반려**: `feat/data-model` 브랜치(livestore+집계표보고서) 사용자 반려·삭제 → main(엑셀표 화면) 유지 + 데이터흐름만 개선.
- **상태**: 실적·문서관리 완료. **보고서운영 `/reports` = 다음 세션**(현재 main 원본=엑셀표·차트·회차별, 새 모델과 정렬 필요). 미커밋(working tree).

**⭐ 양식 전면교체(ver0.1 Master+Area_A~L) + 보고서 운영 재구축 (2026-06-19~21)** — 상세 메모리 `lg_data_pipeline.md`
- 양식 ver0.2(`당월>>`마커)→**ver0.1 Master+Area_A~L** 전면교체, 마커폐기. `parsing_lg` 재작성(raw-vs-수식, leaf만 적재). `master_lg` 신규(**수식 평가기**로 Master 재현, 캐시 비의존 → 트림/수정 파일도 동작). `store`=회차자동판단(`infer_period_id`)·정합성검증(`compare_periods`)·`master_table`/`master_headline` 저장.
- **3섹션 IA**: 실적관리(`/data` 항목별 드래그업로드+미리보기모달+제출현황) / 보고서운영(`/reports` 신호등칩+전체/A~H탭+전체현황/당월토글, 전체=멀티계열차트+MasterSheetTable 병합셀+top3, 개별Area=**AreaSheetTable**) / 문서관리(`/documents` 업로드허브+양식검증).
- 양식검증 `validate_master_format`, 토스트 `ui/Toast.tsx`, 샘플 `make_samples.py`(트림파일).

**⭐ Area 시트 그대로 재현 — AreaSheetTable + area_table (2026-06-21)** — 상세 메모리 `lg_data_pipeline.md`
- 문제: 개별 Area 상세표가 `pivot`(=`parsing_lg` 가 수식 셀 버리고 raw leaf만) 기반 → 엑셀의 **합계·소계 행(전부 수식)이 통째로 빠짐**. 사용자 강한 불만("Group_B+Group_C 합계 빼먹었어, 각 Area 테이블 엑셀 그대로 빼다 박아").
- 백엔드 `src/master_lg.py:area_table(file, area, cur)` 신규 — Area 시트를 **엑셀 그대로 재현(수식 평가기로 합계/소계/Rate 행 포함)**. row-dtype(A·B·C·D·G)·year-block(E·L) 두 양식 한 함수. **소계 판정 = 수식이 다른 행/시트 참조(세로집계)** (`=AJ6`/같은행 가로합은 leaf). **월계 없으면 주차합 롤업.** 검증: 소계 1월 값 엑셀 캐시 정확일치(트림파일도 동작). store 가 ingest 때 `_area_tables.json` 저장(`load_area_table`), API `GET /{period}/area/{area}/table`.
- 프론트 `app/reports/page.tsx:AreaSheetTable` — **부서경로 레벨별 병합셀 컬럼**(깊이 2~4단 가변·짧은 말단 colSpan, MasterSheetTable 식) | 구분(목표/실적/**달성률** 3행) | 데이터. **합계·소계 행 음영+굵게**(`is_subtotal`), **Rate경로 %**(`is_rate`), 전체현황=월1~12 / **당월=그 달 월계+주차(W#)**. 하단 미달영향/달성율최저 top3 **모든 Area 항상**. 구 AreaPivotTable/`pivot` 폐기.
- **전체 종합 표/그래프도 당월=주차** — `master_table` 각 셀에 당월 주차(weeks) 추가, `MasterSheetTable`이 전체현황=월/당월=주차 분기(세부까지). 당월 그래프도 멀티계열(목표/실적전체/실적H제외+달성률2선) 주차 기준. "Master 시트"→**"전체 종합 실적"** 포멀 명칭, 표 위 설명글 제거.

**⭐ 문서 관리 = 회차+항목별 파일 그룹 (2026-06-21)** — 상세 메모리 `lg_data_pipeline.md`
- `/documents` = **실적관리에서 항목(부서)별로 올린 파일을 회차 드롭다운 + 항목별 그룹으로 열람**(업로드 UI 없음, 데이터 입구는 실적관리 한 곳). docstore.save 에 `area` 저장. 부서제출 대상(A·B·D·G·L) 먼저+source뱃지+버전묶음+미업로드 표시. 삭제=원본만.

**⭐ 데이터 모델 미결 (2026-06-21, 메모만·미작업)** — 다음 세션 핵심. 상세 메모리 `lg_data_pipeline.md`
- 사용자 통찰: 양식은 1~12월 다 있고 제출 누적 → 최신 파일이 과거+수정 다 포함 → **latest-wins(항목 단위)**. 교차오염: A 파일 속 낡은 B 시트가 B 데이터 덮을 위험.
- **현재 됨**: 항목별 `only_area` 적재 → 덮어쓰기 사고 방지. **미작업 3개**: ⓐ통짜 적재 차단(항목 지정만 허용) ⓑ살아있는 데이터 전환(현재 회차=스냅샷) ⓒ불일치 알림. 추천 ⓐ→ⓑ→ⓒ.

**LG 실데이터 파이프라인 + 데이터 업데이트 + 제출 관리 (2026-06-16, ver0.2 — 일부 outdated)**
- LG 실제 양식(ver0.2, `docs/lg_samples/excel/…ver0.2.xlsx`) → mock(`parsing.py`/`mock_data`)과 **별개의 real 파이프라인** 신설 (mock 은 그대로). 상세 메모리 `lg_data_pipeline.md`.
- `src/parsing_lg.py` — `당월>>` 마커 자동 감지 → tidy **long** DF. 15시트 중 7 파싱(항목1·2·3·4·5·7·항목8_4_수정), skip = 항목6(마커 없음)·항목8(`(당월)` 다른 양식)·Master(요약). `_split_dtype` 가 `` `25실적 `` → (2025,실적) 분리. 원본이 항목마다 제각각인 걸 한 스키마로 정규화.
- `src/store.py` — **CSV DB**(DB 없이). **회차=스냅샷** → `data/{회차}/{항목}.csv` (평탄, 연도/월은 컬럼). `load_period` 가 회차 폴더 CSV 합쳐 반환. **부분 제출 자연 병합**(자기 항목만 갱신·latest-wins·빈 시트 안 덮음). 과거 회차 스냅샷 보존(드롭다운에서 골라봄). `submission_status`=기대 항목(EXPECTED_ITEMS 항목1~8) 대비 수신/미수신. `data/` gitignore → 커밋은 코드만, CSV 는 원본 엑셀에서 재생성.
- `src/aggregate_lg.py` (저장 X, 재현) — `pivot_achievement`(항목별 부서경로×월), `overview`(전 항목×월+종합, **종합=YTD**: 실적 있는 달만), `clip_future`(스냅샷 회차 이후 미래 월 제거 → 달성률 오염 방지).
- `app/api/lgdata.py` — upload·periods·sources(=항목)·rows·items·pivot·**overview**·**submission**·**remind**(독촉 초안) + DELETE.
- 프론트: `app/data/page.tsx`="**데이터 업데이트**"(회차 드롭다운·기본 최신 + 업로드 + **3토글 [전체/항목별/원천], 전체 기본** + 삭제 ConfirmDialog). `MasterOverview`=전체(KPI + 항목별 달성률 막대 + 항목×월 표). `PivotPanel`=항목별(부서 계층 트리·롤업·색상). `app/inbox/page.tsx`="**제출 관리**"(구 이메일 수신함: 수신현황 칩 + 첨부 등록→DB + **항목 단위 독촉** 미수신→초안→발송 SMTP 시뮬). `GlobalAssistant` client-only(SSR 하이드레이션 수정), main `min-w-0`(표 잘림), 표 값 중앙정렬.
- **설계 결정**: 저장=long(피벗 wide X) / **회차=스냅샷**(이력 보존, 연도 덮어쓰기 X) / Master=모든 항목 모인 최종 집계(=자동 생성 대상) / "입구 여러 파서·경로 → 출구 하나(항목별 long DB)" / 수신=수동 업로드(IMAP 불가)·발송=SMTP.
- **보류**: ① 항목6·8 월별형 파서 — LG 정규화 양식 대기. ② SMTP 실발송 + LLM 독촉 본문 — LG 계정 후. ③ 부서 단위 독촉 — 부서↔항목 마스터(기대 제출 목록) 받아야. ④ 웹 inline 편집 / 음수(절감형) 항목 비율 깨짐 — 추후. ⚠️ uvicorn `--reload` 가 Win+Dropbox 에서 변경 자주 놓침 → **백엔드 수동 재시작** 필요.

**주차별 보고서 시스템 신설 (2026-06-09)**
- `docs/weekly/` 폴더 — 교수님 제출용 주차별 진행 보고
- 파일명 패턴: `{시작월}월{시작일}일_{종료월}월{종료일}일_경영성과팀_보고서.{md,docx}` (예: `6월2일_6월9일_경영성과팀_보고서.md`)
- `build_report.py` — markdown → Word(.docx) 변환기 (재사용). 표지 + 정보 박스 + 본문 표/리스트/헤더 자동 처리, 표 너비 페이지 100%, 진남색 (#1F3864) 헤더 + 줄무늬 본문
- 보고서 작성 규칙: 개조식 (~함/~됨/~예정), 주차 표현 자연어 (W1 X), 요약은 글머리 기호 (산문 X), 제목 컴팩트, LG 측 톤 부드럽게 ("안내해 주실 예정"), 확인 안 된 사실 자제 — 상세 메모리 `report_style.md`
- 사용법: `conda activate lg-kitchen && python docs/weekly/build_report.py "<파일명>.md"`

**LG 협의 1차 회신 + Azure OpenAI adapter (2026-06-08)**
- **LG 회신 도착**: LLM = **Azure OpenAI** (`https://****.openai.azure.com`) / 이메일 = M365 Outlook (MS Graph 신청·심사 중) / 배포 = 웹 + 사내 서버 1대 + 다중 접속 / 엑셀 = CPC 통해 공유 예정 / 미팅 정례 (LG 자발 추가, 익일 확정)
- **Azure OpenAI 분기** — `narrative.py:_llm_client` 에 `LLM_PROVIDER` env 추가. `openai_compatible` (기본) / `azure` 분기. Azure 면 `AzureOpenAI(azure_endpoint, api_version)`. `from openai import OpenAI, AzureOpenAI`.
- **`.env.example` 갱신** — `LLM_PROVIDER` + Azure 블록 (LLM_API_VERSION + deployment 이름 안내). 옛 qwen2.5:3b default 코멘트 → EXAONE 3.5 7.8B 로 정정.
- **운영 전환 절차**: `.env` 5줄 (PROVIDER=azure / BASE_URL / API_KEY / MODEL=deployment / API_VERSION) + `DEMO_MODE=false` + `docker compose restart backend`. 코드 0 추가 변경.
- **다음 단계 (대기)**: B (수동 업로드 fallback UI) — MS Graph 신청 결과와 무관하게 가치 유지. Graph 풀려도 보완재.

**AWS EC2 데모 배포 (2026-06-05)**
- **DEMO_MODE 추가** — `narrative.py:_llm_complete` 에 `cache_key=` `scenario_id=` 인자 추가. recorded JSON 우선 → DEMO_MODE 면 LLM 호출 skip → 없으면 template fallback. 7개 LLM 함수 모두 패턴 적용.
- **record_narratives.py** — 로컬 (Ollama up) 에서 6 격주 × 7 함수 LLM 호출하고 결과를 `mock_narratives/{period_id}.json` 으로 dump. RECORD_NARRATIVES=true 플래그.
- **Docker 3컨테이너** — `docker-compose.yml` (backend + frontend + nginx). backend env `ALLOWED_ORIGINS=["*"]` JSON 형식 필수 (pydantic-settings List[str] 파싱).
- **nginx basic auth** — `/`, `/api`, `/docs` 전 경로 htpasswd 보호. 시연 끝나면 인스턴스 종료 필수.
- **EC2 ARM64 t4g** — Ubuntu 24.04 + Graviton. docker image 다 multi-arch (python:3.12-slim / node:20-alpine / nginx:alpine) 라 그대로 동작.
- **GitHub** — `ijaehun/lg-kitchen-agent` private. docs/ gitignore (LG 자료 + 내부 가이드 GitHub 비노출).
- **챗봇 DEMO_MODE 대응** — 자유 질문 → "데모 모드입니다. '5월 1차 분석해줘' 같은 명령 사용" 친화 안내. 결정론 명령은 그대로 작동.

**B+ 정리 (2026-05-26)**
- **분석 agent (`backend/src/agent.py`) 통째 제거** — tool-use loop 폐기, 결정론 `run_pipeline` 만 사용
- **cache 메커니즘 통째 제거** — `llm_cache/` 폴더 + `narrative.py` 의 `_cache_*` 함수 + 각 LLM 함수의 cache 호출 17곳 + `cache_prebuild.py` 모두 삭제. 매 호출 라이브 LLM.
- **mock_data 재구조화** — `scenario_normal`/`scenario_anomaly` → 격주 6 폴더 (`2026-XX-X`). scenario_id = period_id.
- **챗봇 history sidebar** — Conversation 단위 분리 (localStorage `lks-chat-conversations`). legacy 단일 스레드 자동 migration.
- **LLM 모델 = EXAONE 3.5 7.8B** — qwen2.5 한자/일본어 누출로 폐기 → LG 자체 모델로 교체

**챗봇/UI 강화 (2026-05-27)**
- **라벨 형식 통일** — `2026 · 5월 2차` → `2026년 5월 2차`. backend `_normalize_period` 가 frontend 어떤 형식 줘도 자동 변환, `(이번 격주)` suffix 제거 (시간 지나도 깨지지 않게)
- **markdown/빈 bullet 방어** — `_llm_complete` 항상 `_sanitize` 거침 (markdown bold/header 제거). `_bullets` 가 빈 bullet (`- *`, `* *`) + punctuation-only 라인 필터. `_parse_clusters`/`_parse_strategies` 가 name·reason 의 trailing `**` 도 안전망으로 한 번 더 제거.
- **분석 실행 확인 단계** — 챗에서 "5월 1차 분석해줘" → 즉시 실행 X. `confirm_run_ingest` action + [예/취소] 버튼 inline. [예] → run_ingest 변환 실행, [취소] → "취소되었습니다" 메시지.
- **분석 도중 STOP** — `task_manager.cancel()` + `pipeline._check_cancel()`. phase 사이 + `explain_anomaly` 행 사이에서 협조적 cancel. 체감 1~3초 내. ProgressModal 에 [중단] 버튼.
- **EXAONE tool-use 미지원 대응** — `exaone3.5:7.8b does not support tools` 400 에러 한 번 받으면 `_TOOLS_UNSUPPORTED=True` 플래그로 이후 호출 영구 skip. 결정론 매칭 fallback 강화 — "회신 현황", "위험 카테고리", "메일 가져와" 등 정보 조회 명령은 LLM 거치지 않고 도구 직접 호출 + 결과 답변.
- **system context 동적 주입** — `_build_system_context()` 가 오늘 날짜, 현재 격주, 최근 task 요약을 LLM prompt 마다 합침. LLM 이 "이번 격주" 같은 시간 정보를 알게 됨. `chat_answer` 가 context 없을 때도 LLM 자유 답변 허용 (이전: fallback 안내).
- **현재 격주 동적 인식** — 정보 조회/fetch_emails 매칭에서 default sid 를 `current_period().id` 동적 사용. 사용자가 격주 명시 시 그것 우선 (5월 1차, 4월 2차 등).
- **도구 카탈로그 UI** — `ToolCatalog.tsx` 신규. AssistantPanel 헤더 🛠️ 버튼 / 챗에서 "도구 목록" → 자동 오픈. 11개 도구를 카테고리별 (정보 조회 7 + UI 액션 4) 카드로 표시, 예시 명령 클릭 시 자동 전송.
- **wishlist 노트** — 챗에서 "도구 메모: ~~~" / "/note ~~~" → `backend/tool_wishlist.md` 에 append. Claude Code 와 작업 시 그 파일 참고.
- **챗 삭제 dialog 통일** — 브라우저 native `confirm()` → `ConfirmDialog` (danger variant) 로 다른 곳과 통일. 사이드바 + 버튼 중복 제거 (헤더 + 만 유지).
- **dead code 제거** — `IngestRequest.mode`, `IngestResult.agent_mode/trace/iterations`, `AgentTraceItem`, `TaskHistoryItem.agent_mode`, frontend `AgentTraceKind/AgentMode/AgentTraceItem` 타입, `RecentTasksWidget` 의 isAgentic 분기 + Workflow 아이콘. backend `__pycache__` 의 `agent.cpython-312.pyc`, `cache_prebuild.cpython-312.pyc` 잔재 정리.

## 현재 Mock vs Real

> ⚠️ **2026-06-23 대부분 STALE** — mock(이메일/엑셀/녹화 narrative)·옛 pipeline·task DB 전부 삭제됨. 현재는 LG 실양식 파이프라인(parsing_lg/store/master_lg/aggregate_lg) + 실데이터 챗봇만. 아래 표는 옛 격주 시스템 기준 기록.

### ✅ 진짜 동작 (그대로 production 가능)
- `src/` 도메인 로직 (parsing, aggregation, sensing) — 실제 xlsx 처리
- `src/docgen/` — 실제 PPT/Word/Excel 파일 생성
- FastAPI 라우터 + 비동기 task 패턴
- Frontend UI 전체 (5 페이지: 홈 / 인박스 / dashboard / reports / history)
- 챗봇 conversation 단위 history

### ❌ Mock인 부분 (LG 정보 받아 real로 전환)
| 영역 | Mock | Real 전환 |
|---|---|---|
| 이메일 수신 | hardcoded 7건/격주 | MS Graph / IMAP (LG 답변 대기) |
| 엑셀 데이터 | pre-generated 격주 6 폴더 × 7 카테고리 | 메일 첨부 자동 다운로드 (또는 수동 업로드 fallback) |
| LLM endpoint | 로컬 Ollama (EXAONE 3.5) · EC2 데모는 pre-recorded JSON 재생 | LG 내부 endpoint (`.env` 의 `DEMO_MODE=false` + `LLM_BASE_URL`/`LLM_MODEL` 한 줄 교체) |
| 스케줄 | 수동 트리거 | APScheduler 격주 |
| DB | 메모리 dict + 디스크 JSON (`backend/tasks/`) | PostgreSQL |
| Follow-up 메일 | 본문 LLM 작성 + UI 시뮬레이션 | SMTP/Graph 실제 발송 |

### LLM 함수 7개 (`src/narrative.py`)
- `executive_summary` — 임원 요약 (대시보드/PPT)
- `category_analysis` — 카테고리별 1~2문장 분석
- `explain_anomaly` — 이상 항목별 1줄 해석
- `recommendations` — 차주 우선순위 액션 3~5건
- `cluster_anomalies` ← Sentinel 판단: 이상 항목 근본원인 클러스터링 (관찰/추론 trace 포함)
- `followup_strategy` ← Sentinel 판단: 부서별 follow-up 전략 (이메일/재요청/에스컬레이션) 결정
- `followup_email` — 부서별 메일 본문 LLM 작성

각 함수 안에 **template fallback** 있음 — LLM 도달 불가 시 자동 대체.

### LLM 오염 방어 (`narrative.py:_sanitize`)
- `<|im_start|>` 등 special token 제거
- 연속 4자 이상 한자 블록 제거 (중국어 문장)
- 히라가나/가타카나 제거 (일본어 누출)
- `**` markdown bold + `## 헤더` 제거
- 모든 system prompt 에 `_LANG_GUARD` 자동 합쳐짐 (한국어만 강제)
- `openai` 호출에 `stop=["<|im_start|>","<|im_end|>","<|endoftext|>"]`
- 오염 감지 시 retry 1회

## 모니 챗봇 — 실데이터 Q&A (2026-06-23 재작성)

"현재 LG 데이터 상태를 자연어로 묻는 비서". 항상 **최신 스냅샷**(store) 조회. 격주/scenario/task 개념 없음.
`tools.py` = 실데이터 도구 5개, `narrative.py:chat_with_tools` = LLM tool-use 루프. **숫자는 store/aggregate 결정론 값만 인용**(hallucinate 방지).

| 카테고리 | Tool | 설명 |
|---|---|---|
| 정보 조회 | `get_status` | 제출 현황 — 현재 주차·미제출 항목 (`store.latest_status`) |
| 정보 조회 | `get_achievement(area?)` | 실적/달성률 — 목표/실적/차이/달성률 (`aggregate_lg.master_detail`) |
| 정보 조회 | `get_risks` | 위험/미달 — 미달영향·달성률최저 top3 |
| UI 액션 | `navigate` | 페이지 이동 (`/data`, `/reports`, `/documents`, `/inbox`, `/`) |
| UI 액션 | `remind` | 미제출 독촉 안내 |

**하이브리드**: `chat.py` 가 결정론 매칭(`_detect_command` — "주차/미제출/실적/위험" 키워드 + Area_X 추출) 우선 → 매칭 안 되면 LLM tool-use → 도달 못 하면 chat_answer 안내.
PRESETS = 현황/미제출/달성률/미달. 도구 추가 = `tools.py` 함수+schema 한 쌍 + `_detect_command` 키워드 (확장 쉬움). "도구 메모: ~~~" → `tool_wishlist.md`. ⚠️ RAG는 보류(구조화 숫자는 결정론이 정확).

## Development Commands

### 환경 — conda env `lg-kitchen` 사용 (base 오염 회피)
```bash
conda activate lg-kitchen
```

⚠️ 윈도우 user-level site-packages 가 bleed-through 가능 — 의존성 디버깅 시 `PYTHONNOUSERSITE=1` 또는 `python -s` 로 격리.

### 데모 실행
```bash
conda activate lg-kitchen

# Backend (터미널 1)
cd backend && python -m uvicorn app.main:app --reload --port 8000

# Frontend (터미널 2 — conda env 불필요)
cd frontend && npm run dev

# 브라우저: http://localhost:3000
```

### 데모 데이터 재적재 (LG 실양식 → CSV DB + 캐시)
```bash
cd backend && C:/Users/lee/.conda/envs/lg-kitchen/python.exe -s setup_weeks.py
# → data/2026-05-3/ (부서별 다른 주차: A·D·L=3차/B=2차/G=1차) + documents/ 정규화 보관.
#   원본 = docs/lg_samples/excel/*Master*ver0.1.xlsx. 캐시(master_table/area_table) 재생성됨.
# ⚠️ 코드 변경(master_lg 주차구조 등) 후 반드시 재실행해야 캐시 갱신됨.
```
(옛 mock 데이터 생성기 `src/mock/data_generator` 는 2026-06-23 삭제됨)

### LLM 모델 (개발 / 운영)
- **개발 (현재)**: Ollama + `exaone3.5:7.8b` (RTX 4090)
  - `.env`: `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=exaone3.5:7.8b`
- **운영 (LG 사내, 2026-06-08 회신 확정)**: **Azure OpenAI** (`https://****.openai.azure.com`)
  - `.env`: `LLM_PROVIDER=azure`, `LLM_BASE_URL=https://<resource>.openai.azure.com`, `LLM_API_KEY=<key>`, `LLM_MODEL=<deployment-name>` (실제 모델 ID 아님), `LLM_API_VERSION=2024-08-01-preview`
  - 구현 위치: `narrative.py:_llm_client` 의 `provider == "azure"` 분기 → `AzureOpenAI` 클라이언트
- 모델 교체: `.env` 만 수정 → 백엔드 재시작 (uvicorn `--reload` 는 `.env` 미감지)

### EC2 데모 배포 (DEMO_MODE)
- 외부 시연용 — Ollama 없이 동작 (LLM 미도달 시 template/안내 fallback)
- 한 줄로 켬: `backend/.env` 의 `DEMO_MODE=true` (또는 `cp backend/.env.demo backend/.env`)
- ⚠️ `record_narratives.py`/`mock_narratives` 는 2026-06-23 삭제됨. 데모 데이터는 `setup_weeks.py` 로 생성(위 참조).
- Docker compose: `docker compose build && docker compose up -d` → 3 컨테이너 (backend / frontend / nginx)
- nginx basic auth: `docker run --rm httpd:alpine htpasswd -nbB <user> <pwd> > nginx/htpasswd`
- 상세 가이드: 로컬 `docs/deploy_ec2.md` (gitignored — GitHub 비공개)

### NaN / JSON 직렬화 주의
pandas DataFrame → JSON 변환 시 NaN 그대로 두면 FastAPI/starlette 가 strict JSON 에서 거부.
`.astype(object).where(df.notna(), None)` 패턴 사용 (`.where()` 만으로는 float 컬럼에서 NaN 복귀).

## Conventions

### Backend
- **얇은 라우터 / 두꺼운 src/** — `app/api/` 는 thin, 도메인 로직은 `src/`
- `app/api/lgdata.py`·`documents.py` 라우터가 `src/`(parsing_lg/store/master_lg/aggregate_lg) 오케스트레이션 (옛 `app/services/pipeline.py` 는 2026-06-23 삭제)
- LLM 호출은 반드시 `src/narrative.py` 통해서 (sanitize + LANG_GUARD + retry + template fallback 자동)
- Pydantic 스키마는 `app/models/schemas.py` 단일 파일
- API 응답 키는 한글 그대로 (`카테고리`, `목표_억원` 등) — 도메인 친화

### Frontend
- 페이지: `app/<feature>/page.tsx`, query string 으로 `taskId` 전달 (dynamic route 안 씀)
- 컴포넌트는 feature 별 폴더 (`components/{inbox,dashboard,reports,chat,home,layout,ui}/`)
- API 호출은 `services/<feature>Service.ts` — 컴포넌트에서 직접 axios 호출 금지
- 타입은 `types/index.ts` 한 곳, 백엔드 Pydantic 미러
- 차트는 recharts. 단순 막대/수평 막대만 사용

### Naming
- Agent 동작 표현 시 무조건 **"모니"** — "AI Agent"·구 "Sentinel"/"LKS" 표현 금지 (메모리 `agent_name.md`). 단 localStorage 키 `lks-` 는 유지

### Environment variables
- `.env.example` always tracked, `.env*` (실 값) always gitignored
- **절대 커밋 금지**: `LLM_API_KEY`, DB password, 사내 endpoint URL

### 한글 / 인코딩
- 윈도우 콘솔 cp949 이슈 — 사용자에게 보일 문자열에 non-BMP char 회피
- Python print 디버깅 시 `PYTHONIOENCODING=utf-8` 또는 `sys.stdout.reconfigure(encoding='utf-8')`
- curl 로 한글 JSON body 보낼 때 cp949 변환됨 — Python `urllib.request` 또는 SDK 권장

## LG 협의 (2026-06-05 송부 → 2026-06-08 / 2026-06-10 회신)

자세한 톤과 히스토리는 메모리 `demo_strategy.md`.

| # | 항목 | LG 회신 | 우리 측 후속 |
|---|---|---|---|
| 1 | **LLM endpoint** | (06-08) **Azure OpenAI** (`https://****.openai.azure.com`) 키 발급 예정 | ✅ `narrative.py:_llm_client` 에 `LLM_PROVIDER=azure` 분기 추가 완료. 키 받으면 `.env` 4줄 (PROVIDER/BASE_URL/API_KEY/MODEL=deployment) + `LLM_API_VERSION` 만 채우면 켜짐 |
| 2 | **이메일 인프라** | (06-08) M365 Outlook · Graph 심사 중. **(06-10) IMAP 미지원 / SMTP 는 별도 신청 후 사용 가능** → 발송만 확정, 수신 IMAP 불가 | ✅ **결정: 수신 = 웹 수동 업로드.** 자동 수신(Graph)은 추후 같이 고민. 다음 작업 = `/inbox` dropzone + `POST /api/ingest/upload` multipart + `pipeline._scenario_files` 분기 |
| 3 | **사용 형태 + 배포** | (06-08) **웹 + 사내 서버 1대 + 다중 접속** 확정. **(06-10) 화면 레이아웃·메뉴 금요일까지 확정 공유** | ✅ Docker compose 그대로 사내 deploy. 데스크톱 패키징 skip. 레이아웃 = 금요일 LG 안 도착 후 반영 |
| 4 | **엑셀/메일 샘플** | (06-08) CPC 통해 공유. **(06-10) 엑셀 양식 = 중요값 블라인드 처리해 금요일 제공 / 요청 메일 = 차주 미팅 때 시연** | 🟡 금요일 도착 시 `backend/src/parsing.py` 컬럼 매핑 검증, 다르면 `read_many` 안에서 normalize |
| 5 | **주별 미팅 정례** (LG 추가) | **(06-10) 이번주 어려움 → 차주 화/목 희망, LG 가 창원대 방문 예정** | 🟡 이재훈 일정 확정 필요 (화/목 중 택1) |
| — | **service account 문의** (LG 역질문) | (06-10) "요청 메일 수발신용 공용 계정 별도 필요 이유?" | 답변: 발송만이면 **SMTP 계정이 겸함** → 별도 불필요 / 자동 수신까지면 전용 수신함이 깔끔. **필수 아님** |

**시연 후 협의로 미룬 사항** (운영 단계):
- 이상 감지 임계값 (현재 <80%/<90%)
- 임원 보고 양식 (PPT/Word — 현재 generic)

## Notes for Claude Code

- **외부 API 호출 코드 작성 금지** — `anthropic.com`, `openai.com` 등 외부 도메인 하드코딩 X
- 코드 외부 공개 금지. GitHub repo: **private only**
- 도메인 디테일 (목표 산정, 임계값) 모르면 user에게 확인 후 진행 — LG 인풋 필요
- 엑셀 포맷이 부서마다 다를 가능성 큼 → 추후 LLM normalize 단계 추가 검토
- Mock 데이터/이메일은 단순 시연용. 실제 LG 데이터 받으면 mock 폴더는 archive
- **시연 시 솔직히**: "데모 골격이고, 메일/DB/LLM 통합은 LG 인프라 정보 받은 후 즉시 가능" — 과장 금지
- **destructive 행동 사전 확인** — 사용자 명시 동의 없이 파일 삭제/git reset 등 금지 (사용자 소통 메모리 참고)
