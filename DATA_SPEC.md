# [기술 사양서] 데이터 수집 및 정제 정의 (Data Transformation Spec)

본 문서는 공공기관 API로부터 수집된 원본 데이터의 변환 규격 및 정제 규칙을 정의합니다. 분석가는 본 문서를 참조하여 데이터를 로드하십시오.

---

## 1. 파일 규격 (Output Specs)
*   **포맷**: CSV (Flat File)
*   **인코딩**: UTF-8 with BOM (`utf-8-sig`)
*   **구분자(Delimiter)**: `‡` (Double Dagger, U+2021)
*   **저장 경로**: `output/csv_export/{JOB_NAME}_{YYYYMMDD}.csv`

## 2. 공통 정제 규칙 (General Normalization)
| 항목 | 적용 내용 |
| :--- | :--- |
| **공백 처리** | 모든 필드 값 Leading/Trailing Whitespace 제거 |
| **결측값** | 빈 문자열(`""`) → `NULL` (None) 변환 |
| **타입 보존** | 사업자번호, 인가번호 등 숫자형 식별자의 문자열(String) 포맷 강제 유지 |
| **추적 필드** | `_source`, `_service_code`, `_endpoint_key` 메타 필드 추가 |

## 3. 기관별 세부 변환 (Specific Transformations)

### A. 식품의약품안전처 (FoodSafety)
*   **날짜 정규화**: `YYYYMMDD` (String) → `YYYY-MM-DD` (ISO 8601) 변환
*   **매핑 필드**: `haccp` (I0580), `restaurant` (I1590)

### B. 공공데이터포털 (DataPortal)
*   **컬럼 재구성**: 원본 내 탭(`\t`) 구분 문자열 감지 시 개별 컬럼으로 파싱 및 확장
*   **수치 보정**: 연번, 사업자등록번호 등의 지수 표기법(Scientific Notation) 방지 및 문자열화

### C. 고용24 (Work24)
*   **데이터 모델**: XML 계층 구조 → 비정규화된 단일 테이블(Denormalized Table) 변환
*   **레코드 처리**: 단건(Object) 및 다건(List) 응답 포맷의 리스트 구조 일관화

## 4. 운영 환경 및 제약 사항 (Operational Context)
*   **수집 방식**: API 페이지당 100~1,000건 단위 페이징 처리
*   **데이터 누락**: 식약처 '식품모범음식점'의 경우 기관 API 서버 제한으로 인해 약 1.7k 건의 데이터 수급 불가 (원본 이슈)
*   **수집 주기**: 연간(Yearly), 월간(Monthly) 스케줄링 기반 자동 수집
