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
├── DATA_SPEC.md            # [분석가용] 데이터 정제 및 변환 상세 사양서
├── storage/
│   ├── raw/                # API 원본 응답 저장 (JSON/XML)
│   └── output/             # 정제된 CSV 결과물 (구분자: ‡)
└── pipeline/
    ├── base.py             # 추상 Base 클래스 (원본 저장, 재처리 로직 포함)
```

---

## 🚀 설치 및 실행

### 1. 의존성 설치

```bash
python -m pip install -r requirements.txt
```

### 2. 환경변수 설정

`.env` 파일에 API 키와 Slack Webhook URL을 설정하세요.

### 3. CLI 실행 모드

#### A. 스케줄 자동 실행 (권장)
`schedule_config.py`에 정의된 주기에 따라 오늘 실행해야 할 작업을 자동으로 골라 실행합니다.
```bash
# 오늘 실행 대상 Job 자동 실행
python main.py --schedule

# 수집 주기 설정표 확인
python main.py --show-schedule
```

#### B. 개별 Job 수동 실행
```bash
# 식약처 HACCP 전체 수집 (기본 per_page 사용)
python main.py --job foodsafety_haccp

# 공공데이터포털 7종 일괄 수집
python main.py --job dataportal_all

# 테스트 실행 (5건, 1페이지만)
python main.py --job foodsafety_haccp --perpage 5 --maxpages 1

#### C. 로컬 원본 데이터 기반 재처리 (Reprocessing)
API를 호출하지 않고, 로컬에 저장된 `storage/raw/` 데이터를 사용하여 CSV를 다시 생성합니다. (추출 로직 변경 시 유용)
```bash
python main.py --job foodsafety_haccp --from-raw
```
```

---

## ⚙️ CLI 옵션 목록

| 옵션 | 설명 | 기본값 |
|------|------|-------|
| `--job ID` | 실행할 특정 작업 ID 지정 | - |
| `--schedule` | 오늘 스케줄에 해당하는 Job 자동 실행 | - |
| `--show-schedule` | 현재 수집 주기 설정을 출력하고 종료 | - |
| `--perpage N` | 페이지당 수집 건수 (미지정 시 설정값 사용) | config 참조 |
| `--maxpages N` | 최대 N페이지만 수집 (테스트용) | None (전체) |
| `--from-raw` | 로컬 원본 데이터를 사용하여 재추출 실행 | - |
| `--loglevel` | 로그 레벨 (DEBUG/INFO/WARNING/ERROR) | INFO |

---

## 📊 데이터 규격 (CSV)

모든 데이터는 분석 편의를 위해 다음과 같은 공통 규격을 따릅니다. 상세 내용은 [DATA_SPEC.md](DATA_SPEC.md)를 참조하세요.

*   **구분자(Delimiter)**: `‡` (Double Dagger)
*   **인코딩**: `UTF-8 with BOM` (엑셀 호환)
*   **날짜 형식**: `YYYY-MM-DD` 정규화 완료
*   **특이사항**: 사업자번호 등 식별자의 문자열 포맷 유지, 결측치 Null 처리 완료

---

## 🔗 Airflow / Cron 연동

### Crontab 등록 (매일 새벽 2시 자동 스케줄 실행)
```cron
0 2 * * * cd /path/to/project && python main.py --schedule
```

### Airflow 연동
`PythonOperator`에서 `main.run_schedule()` 또는 `main.run_job()`을 호출하여 간단히 연동할 수 있습니다.

---

## 🔔 Slack 알림 (Block Kit)

수집이 완료되면 Slack을 통해 시각화된 리포트를 전송합니다.
*   **개별 리포트**: 수집 달성률(%), 요청 성공률, 소요 시간, 파일명 포함.
*   **요약 리포트**: 여러 작업 실행 시 전체 성공/실패 현황 및 총 수집량을 합산하여 보고.

---

## 🔧 엔드포인트 및 주기 관리

*   **URL 변경**: `pipeline/dataportal.py` 내 `DATAPORTAL_ENDPOINTS` 수정
*   **수집 주기 변경**: `pipeline/schedule_config.py` 내 `SCHEDULE_CONFIG` 수정 (yearly/monthly 등)

---

## 🔑 주요 의존성
*   `requests`, `tenacity` (재시도), `xmltodict` (고용24), `python-dotenv`
