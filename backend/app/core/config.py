# backend/app/core/config.py
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # 기본 설정
    APP_NAME: str = "LG Kitchen Agent"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    # 서버 설정
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS 설정 (개발용 - 실제 배포시 수정 필요)
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*"
    ]

    # 데이터베이스 (필요시 추가)
    DATABASE_URL: str = "sqlite:///./app.db"

    # 보안 (실제 배포시 변경 필요)
    SECRET_KEY: str = "change-this-secret-key"

    # LLM (OpenAI-compatible — LG 내부망 endpoint)
    # ⚠️ 외부 API 호출 금지. base_url은 반드시 내부 endpoint로.
    LLM_BASE_URL: str = "http://localhost:11434/v1"  # dev: local Ollama
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "qwen2.5:7b"
    LLM_MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.2

    # ── Demo mode (AWS EC2 배포용 — LLM 없이 pre-recorded narrative 재생) ──
    # DEMO_MODE=true  → LLM 호출 skip. mock_narratives/{period_id}.json 있으면 그걸 재생,
    #                   없으면 각 함수의 template fallback. 외부 의존 zero.
    # RECORD_NARRATIVES=true → 라이브 LLM 결과를 mock_narratives 에 저장 (record 스크립트 전용)
    DEMO_MODE: bool = False
    RECORD_NARRATIVES: bool = False
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # narrative.py 가 os.getenv 로 직접 읽는 env (LLM_TIMEOUT 등) 허용

# 전역 설정 인스턴스
settings = Settings()