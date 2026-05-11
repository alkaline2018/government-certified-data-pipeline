# Government Certified Data Pipeline

공공기관 3종 API(식품의약품안전처, 공공데이터포털, 고용24) 데이터 수집 파이프라인

---

## 📁 프로젝트 구조

```
government-certified-data-pipeline/
├── .env                    # API 키 환경변수 (Git 제외)
├── .gitignore
├── requirements.txt
├── main.py                 # CLI 진입점
├── pipeline/
│   ├── __init__.py
│   ├── base.py             # 추상 Base 클래스 (collect/refine/extract + 재시도)
│   ├── notifier.py         # Slack Webhook 알림
│   ├── foodsafety.py       # 식품의약품안전처 파이프라인
│   ├── dataportal.py       # 공공데이터포털 파이프라인
│   └── work24.py           # 고용24(워크넷) 파이프라인
└── output/                 # 수집 결과 JSON 저장 디렉토리 (자동 생성)
    ├── FoodSafety_HACCP_적용업소/
    ├── FoodSafety_식품모범음식점/
    ├── DataPortal_기술개발_우수기업/
    └── Work24_youth_friendly/
```

---

## 🚀 설치 및 실행

### 1. 의존성 설치

```bash
python -m pip install -r requirements.txt
```

### 2. 환경변수 설정

`.env` 파일에 API 키와 Slack Webhook URL이 미리 설정되어 있습니다.
Slack 알림을 사용하려면 `SLACK_WEBHOOK_URL`을 실제 값으로 교체하세요.

### 3. CLI 실행

```bash
# 도움말
python main.py --help

# ────────────────────────────────────
# 식품의약품안전처
# ────────────────────────────────────

# HACCP 적용업소 - 테스트 (5건, 1페이지만)
python main.py --job foodsafety_haccp --perpage 5 --maxpages 1

# HACCP 적용업소 - 운영 (전체 약 39,000건)
python main.py --job foodsafety_haccp --perpage 1000

# 식품모범음식점 - 운영 (전체 약 24,000건)
python main.py --job foodsafety_restaurant --perpage 1000

# ────────────────────────────────────
# 공공데이터포털 (개별)
# ────────────────────────────────────

python main.py --job dataportal_tech_excellence --perpage 1000
python main.py --job dataportal_performance_cert --perpage 1000
python main.py --job dataportal_startup_cert --perpage 1000
python main.py --job dataportal_century_store --perpage 1000
python main.py --job dataportal_century_craftsman --perpage 1000
python main.py --job dataportal_talent_sme --perpage 1000
python main.py --job dataportal_tech_product_cert --perpage 1000

# 공공데이터포털 전체 7개 엔드포인트 일괄 실행
python main.py --job dataportal_all --perpage 1000

# ────────────────────────────────────
# 고용24 (워크넷)
# ────────────────────────────────────

# 청년친화강소기업 - 테스트
python main.py --job work24_youth_friendly --perpage 5 --maxpages 1

# 청년친화강소기업 - 운영 (전체 약 224건)
python main.py --job work24_youth_friendly --perpage 100
```

---

## ⚙️ CLI 옵션 전체 목록

| 옵션 | 설명 | 기본값 |
|------|------|-------|
| `--job` | 실행할 작업 ID (필수) | - |
| `--perpage` | 페이지당 수집 건수 | 1000 |
| `--maxpages N` | 최대 N페이지만 수집 (테스트용) | None (전체) |
| `--loglevel` | 로그 레벨: DEBUG/INFO/WARNING/ERROR | INFO |

---

## 🏗️ 아키텍처 설명

### 파이프라인 흐름

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  collect()  │ →  │  refine()   │ →  │  extract()  │
│             │    │             │    │             │
│ API 호출    │    │ 타입변환    │    │ JSON 저장   │
│ 페이징 처리 │    │ null 정규화 │    │ 파일 경로   │
│ raw_pages   │    │ 날짜 포맷   │    │ 반환        │
│ 에 누적     │    │ 메타 추가   │    │             │
└─────────────┘    └─────────────┘    └─────────────┘
                   └──────────── run() 에서 순서 실행 ────────────┘
                                  ↓ 성공/실패 시 Slack 알림
```

### 재시도 로직 (tenacity)

- **대상 오류**: `Timeout`, `ConnectionError`, `HTTPError(5xx)`
- **최대 시도**: 5회
- **대기 전략**: Exponential backoff (2초 → 4초 → 8초 → 16초 → 30초 상한)
- **4xx 오류**: 재시도 없이 즉시 실패 (잘못된 키/권한 문제)

### API 패턴별 페이징

| 기관 | 방식 | 총건수 필드 |
|------|------|-----------|
| 식약처 | URL Path: `/json/{시작}/{끝}` | `total_count` (문자열) |
| 공공데이터포털 | Query: `page`, `perPage` | `totalCount` (정수) |
| 고용24 | Query: `startPage`, `display` | `<total>` XML 태그 |

---

## 🔗 Airflow / Cron 연동

### Crontab 예시

```cron
# 매년 1월 1일 새벽 2시 - 식약처 HACCP 전체 수집
0 2 1 1 * cd /path/to/project && python main.py --job foodsafety_haccp --perpage 1000

# 매월 1일 새벽 3시 - 공공데이터포털 전체 수집
0 3 1 * * cd /path/to/project && python main.py --job dataportal_all --perpage 1000

# 매월 15일 새벽 4시 - 고용24 수집
0 4 15 * * cd /path/to/project && python main.py --job work24_youth_friendly --perpage 100
```

### Airflow PythonOperator 예시

```python
from pipeline.foodsafety import FoodSafetyPipeline
from pipeline.dataportal import DataPortalPipeline
from pipeline.work24 import Work24Pipeline

def run_haccp(**ctx):
    FoodSafetyPipeline(service_key="haccp", per_page=1000).run()

def run_dataportal_all(**ctx):
    from pipeline.dataportal import DATAPORTAL_ENDPOINTS
    for ep_key in DATAPORTAL_ENDPOINTS:
        DataPortalPipeline(endpoint_key=ep_key, per_page=1000).run()

def run_work24(**ctx):
    Work24Pipeline(endpoint_key="youth_friendly", per_page=100).run()

# DAG 정의 시 각각 독립된 Task로 등록
```

---

## 📦 출력 형식 (JSON)

### 식약처 HACCP (`foodsafety_haccp`)

```json
{
  "PRSDNT_NM": "김**",
  "SITE_ADDR": "부산광역시 사하구 장평로83번길 15",
  "LCNS_NO": "19970144521",
  "HACCP_APPN_DT": "2026-05-11",
  "PRDLST_NM": "기타 수산물가공품",
  "BSSH_NM": "(주)범우물산",
  "CRTFC_RETN_DT": null,
  "CLSBIZ_DT": null,
  "INDUTY_CD_NM": "식품제조가공업",
  "HACCP_APPN_NO": "2025-2-0278",
  "CRTFC_ENDDT": "2029-05-10",
  "CLSBIZ_DVS_CD_NM": "정상",
  "ASGN_CANCL_DT": "2029-05-10",
  "_source": "foodsafetykorea",
  "_service_code": "I0580"
}
```

### 공공데이터포털 (`dataportal_tech_excellence`)

```json
{
  "개발품목명": "발전소 적합형 물윤활식 공기압축기 국산화 개발",
  "과제번호": "S2194946",
  "기술개발 시작일": "2014-07-01",
  "기술개발 종료일": "2015-06-30",
  "사업자번호": "306-81-18106",
  "우수사례 선정년도": 2022,
  "주관기관": "한국에어로(주)",
  "_source": "dataportal",
  "_endpoint_key": "tech_excellence"
}
```

### 고용24 (`work24_youth_friendly`)

```json
{
  "coNm": "주식회사 지씨",
  "busiNo": "6058141445",
  "reperNm": "이상길",
  "superIndTpCd": "J",
  "superIndTpNm": "정보통신업",
  "indTpCd": "62",
  "indTpNm": "컴퓨터 프로그래밍, 시스템 통합 및 관리업",
  "_source": "work24",
  "_endpoint_key": "youth_friendly"
}
```

---

## 🔧 엔드포인트 URL 변경 방법

공공데이터포털 URL이 변경될 경우, `pipeline/dataportal.py` 내 `DATAPORTAL_ENDPOINTS` 딕셔너리만 수정합니다:

```python
DATAPORTAL_ENDPOINTS: dict[str, tuple[str, str]] = {
    "tech_excellence": (
        "https://api.odcloud.kr/api/NEW_ID/v1/uddi:NEW-UUID",  # ← URL 변경
        "기술개발_우수기업",
    ),
    # ... 나머지 항목
}
```

---

## 🔑 의존성

```
requests>=2.31.0    # HTTP 클라이언트
tenacity>=8.2.3     # 재시도 로직
xmltodict>=0.13.0   # XML → dict 변환 (고용24)
python-dotenv>=1.0.0 # .env 파일 로드
```
