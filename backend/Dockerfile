# backend/Dockerfile — 키친솔루션 한계돌파 플랫폼 demo backend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# matplotlib / lxml / Pillow 빌드용 시스템 라이브러리.
# wheel 이 있어 대부분 컴파일 안 일어나지만, slim 이라 fontconfig / libgomp 등은 깔아야 차트 렌더 됨.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        fontconfig \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# 앱 코드 — mock_data, mock_narratives, src/, app/ 전부 포함
# (.dockerignore 가 temp/, tasks/, .env, __pycache__ 제외)
COPY . .

# task JSON / 보고서 파일 저장 경로 — compose volume 이 mount
RUN mkdir -p /app/tasks /app/temp

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
