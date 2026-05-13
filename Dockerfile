FROM python:3.11-slim

# 시스템 의존성 최소 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 복사 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스코드 복사
COPY . .

# storage 디렉토리 구조 사전 생성
RUN mkdir -p storage/output storage/raw

ENTRYPOINT ["python", "entrypoint.py"]
