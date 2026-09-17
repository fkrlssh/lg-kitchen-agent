"""API 요청/응답 Pydantic 스키마."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Scenarios / Inbox
# ─────────────────────────────────────────────


class ScenarioInfo(BaseModel):
    id: str                # 'normal' | 'anomaly' 또는 period_id (예: '2026-05-1')
    label: str             # 표시명
    description: str
    email_count: int
    received_count: int
    missing_count: int
    is_current: bool = False
    status: Literal["fetched", "pending"] = "fetched"


class EmailListItem(BaseModel):
    id: str
    category: str
    from_name: str
    from_addr: str
    subject: str
    sent_at: str
    received: bool
    missing_departments: List[str] = Field(default_factory=list)


class EmailDetail(EmailListItem):
    body: str
    attachment_filename: Optional[str] = None
    attachment_preview: Optional[List[Dict]] = None  # 첨부 엑셀 첫 N 행


# ─────────────────────────────────────────────
# Ingest / Pipeline
# ─────────────────────────────────────────────


class IngestRequest(BaseModel):
    scenario_id: str = Field(..., description="격주 period_id (예: '2026-05-2')")
    period: str = Field("2026년 5월 1차", description="보고서 기간 라벨 — 백엔드가 자동 정규화하므로 frontend 가 어떤 형식 줘도 됨")


class IngestStartResponse(BaseModel):
    task_id: str


class TaskProgress(BaseModel):
    task_id: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    progress: int  # 0~100
    phase: str
    error: Optional[str] = None


class CategoryAgg(BaseModel):
    카테고리: str
    목표_억원: float
    실적_억원: float
    달성률_pct: float
    상태: str


class AnomalyItem(BaseModel):
    카테고리: str
    부서: str
    세부항목: str
    목표_억원: float
    실적_억원: float
    달성률_pct: float
    상태: str
    ai_해석: str


class CategoryInsight(BaseModel):
    카테고리: str
    분석: str


class AgentReasoning(BaseModel):
    """LLM agent 의 사고 과정 — 'AI 사고 과정' UI 패널이 표시."""
    observations: List[str] = Field(default_factory=list)
    reasoning: List[str] = Field(default_factory=list)


class AnomalyCluster(BaseModel):
    name: str
    items: List[int]          # anomalies 배열의 인덱스
    reason: str


class AnomalyClustering(AgentReasoning):
    clusters: List[AnomalyCluster] = Field(default_factory=list)


class FollowupStrategyItem(BaseModel):
    department: str
    category: str
    strategy: Literal["이메일", "재요청", "에스컬레이션"]
    priority: Literal["low", "medium", "high"]
    reason: str


class FollowupStrategy(AgentReasoning):
    strategies: List[FollowupStrategyItem] = Field(default_factory=list)


class IngestResult(BaseModel):
    task_id: str
    period: str
    scenario_id: str
    totals: Dict[str, float]              # 목표 / 실적 / 달성률 / 항목수
    counts: Dict[str, int]                # 정상 / 경고 / 위험 / 총
    by_category: List[CategoryAgg]
    anomalies: List[AnomalyItem]
    missing_departments: Dict[str, List[str]]
    narrative_summary: str
    reports: Dict[str, str]               # format -> download url
    # LLM-augmented 출력
    category_insights: List[CategoryInsight] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    anomaly_clustering: AnomalyClustering = Field(default_factory=AnomalyClustering)
    followup_strategy: FollowupStrategy = Field(default_factory=FollowupStrategy)


# ─────────────────────────────────────────────
# Alerts
# ─────────────────────────────────────────────


class FollowupRequest(BaseModel):
    task_id: str


class FollowupEmailDraft(BaseModel):
    department: str
    category: str
    strategy: Literal["이메일", "재요청", "에스컬레이션"]
    priority: Literal["low", "medium", "high"]
    subject: str
    body: str
    reason: str


class FollowupResponse(BaseModel):
    sent_count: int
    targets: List[Dict[str, str]]
    message: str
    drafts: List[FollowupEmailDraft] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Chat — AI 어시스턴트 사이드 패널
# ─────────────────────────────────────────────


class ChatPreset(BaseModel):
    id: str
    label: str
    question: str


class ChatRequest(BaseModel):
    task_id: Optional[str] = Field(None, description="대상 ingest task — 있으면 결과를 context 로 사용")
    message: str = Field("", description="사용자 자유 입력. preset 지정 시 무시 가능")
    preset: Optional[str] = Field(None, description="escalation | top_risk | missing | summary")


class ChatCitation(BaseModel):
    label: str
    kind: str  # category | anomaly | strategy | missing | totals | counts


class ChatAction(BaseModel):
    """챗이 실행할 행동. frontend 가 이걸 받아서 navigate / run_ingest / followup 등 처리.

    confirm_run_ingest: run_ingest 전에 사용자 확인을 받기 위한 중간 단계.
    frontend 가 메시지에 [예/취소] 버튼을 표시하고, [예] 클릭 시 run_ingest 로 변환해서 실행.
    """
    type: Literal[
        "none", "navigate", "run_ingest", "call_followup",
        "ask_scenario", "recheck_emails", "confirm_run_ingest",
        "open_tool_catalog",
    ]
    params: Dict[str, str] = Field(default_factory=dict)


class ChatToolCall(BaseModel):
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    result_summary: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    citations: List[ChatCitation] = Field(default_factory=list)
    preset_used: Optional[str] = None
    action: ChatAction = Field(default_factory=lambda: ChatAction(type="none"))
    tool_calls: List[ChatToolCall] = Field(default_factory=list)
    used_tools: bool = False  # True면 진짜 tool-use agent 동작


# ─────────────────────────────────────────────
# Home dashboard — 운영 현황
# ─────────────────────────────────────────────


class TrendPoint(BaseModel):
    """추세 차트 1점 — mock 또는 향후 PostgreSQL 격주 이력."""
    period: str               # "5월 1차" 같은 라벨
    달성률: float
    위험: int
    경고: int


class LastRunSummary(BaseModel):
    task_id: str
    period: str
    scenario_id: str
    finished_at: str          # ISO 8601 한국시 (yyyy-mm-dd HH:MM)
    totals: Dict[str, float]
    counts: Dict[str, int]
    missing_count: int
    anomaly_count: int


class SystemStatus(BaseModel):
    llm_endpoint: str         # "Ollama (로컬)" / "LG 내부 endpoint" / "미설정"
    llm_model: str
    llm_reachable: bool
    next_run: str             # 다음 격주 자동 실행 예정 (mock)
    email_source: str         # "Mock 7건 대기" / "MS Graph 연결됨" 등
    last_report_at: Optional[str] = None


class CategoryTrendPoint(BaseModel):
    period: str          # "4월 1차"
    달성률: float


class CategoryTrend(BaseModel):
    """카테고리별 격주 추세 — multi-line 차트용."""
    category: str
    points: List[CategoryTrendPoint] = Field(default_factory=list)


class LateResponder(BaseModel):
    department: str
    category: str
    late_count: int           # 미회신 누적 횟수
    total_periods: int        # 집계 대상 격주 수


class PeriodCalendarItem(BaseModel):
    id: str
    label: str
    deadline: str
    is_current: bool
    fetched: bool
    pattern: str
    received_count: int = 0
    total_count: int = 0
    missing_count: int = 0


class TaskHistoryItem(BaseModel):
    task_id: str
    created_at: str          # ISO yyyy-mm-dd HH:MM
    period: str
    scenario_id: str
    totals: Dict[str, float]
    counts: Dict[str, int]
    missing_count: int


class HomeDashboard(BaseModel):
    last_run: Optional[LastRunSummary] = None
    system: SystemStatus
    trend: List[TrendPoint] = Field(default_factory=list)
    category_trends: List[CategoryTrend] = Field(default_factory=list)
    late_responders: List[LateResponder] = Field(default_factory=list)
    period_calendar: List[PeriodCalendarItem] = Field(default_factory=list)
    recent_tasks: List[TaskHistoryItem] = Field(default_factory=list)
