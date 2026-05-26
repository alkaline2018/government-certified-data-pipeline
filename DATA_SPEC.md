# [기술 사양서] 데이터 수집 및 정제 정의 (Data Transformation & Validation Spec)

## 1. 파일 규격 (Output Specs)
*   **포맷**: CSV (Flat File)
*   **인코딩**: UTF-8 with BOM (`utf-8-sig`)
*   **구분자(Delimiter)**: `‡` (Double Dagger)
*   **저장 경로**: `storage/output/YYYY/MM/{JOB_NAME}.csv` 

## 2. 데이터 검증 규칙 (Validation Spec)
모든 데이터 수집이 완료되면 `validate.py`가 실행되어 `dataset_catalog.yaml` (Single Point of Truth)을 기준으로 데이터의 무결성과 품질을 검증합니다.

### A. 무결성 검증 (컬럼 누락 체크)
*   **검증 방식**: YAML 카탈로그의 `columns` 목록과 실제 생성된 CSV 파일의 헤더를 1:1로 비교합니다.
*   **실패 조건**: 카탈로그에 명시된 필수 컬럼이 단 하나라도 누락되어 있으면 `[FAIL] (컬럼누락)`으로 판정합니다.
*   **허용 조건**: API 변경으로 인해 카탈로그에 없는 "새로운 추가 컬럼"이 들어오는 것은 정상으로 간주하되 (경고성 정보), 필수 컬럼이 없어지는 것은 치명적인 오류로 처리하여 Slack으로 즉각 경고합니다.

### B. 품질 검증 (동적 기준선 기반 데이터 양 검증)
*   **검증 방식**: 이전 수집 시점의 기준 건수(`expected_count`) 대비 이번에 수집된 실제 행(row) 수의 달성률(%)을 계산합니다.
*   **판정 기준**:
    *   **정상 범위 (97% ~ 103%)**: `[OK] 완벽`으로 판정합니다. 데이터의 자연스러운 증가/감소로 판단하여, **이번에 수집된 건수로 YAML의 `expected_count`를 자동 갱신(학습)** 합니다. (다음 수집 시 새로운 기준점이 됨)
    *   **97% 미만 (과소수집)**: 기관 API 오류, 네트워크 단절 등으로 데이터가 누락되었다고 판단하여 `[FAIL] 과소수집` 오류를 발생시킵니다. (기준 수치는 갱신되지 않음)
    *   **103% 초과 (이상치/과다수집)**: 비정상적인 중복 데이터 발생 또는 시스템 오류로 간주하여 `[FAIL] 과다수집(이상치)` 오류를 발생시킵니다. (기준 수치 갱신 안 함)
*   **예외 처리**: 기대 건수(`expected_count`)가 `null`인 경우 (예: 한 번에 전체 다운로드하는 엑셀 명단 등), 기준치를 판단하지 않고 무조건 100% (정상)로 처리합니다.

---
## 3. 데이터 변환 규칙 (Transformation Spec)
API에서 수신한 원본(Raw) 데이터는 `storage/raw` 폴더에 JSON/XML 형태로 보존되며, 이후 파이프라인(`pipeline/`)의 정제(Refine) 과정을 거쳐 분석하기 좋은 형태의 CSV로 변환됩니다.

### A. 공통 메타데이터 주입
모든 데이터셋의 개별 레코드(행) 단위로 다음 메타데이터가 자동 추가되어 추적성(Traceability)을 확보합니다.
*   `_source`: 수집 출처 식별자 (예: `공공데이터포털`, `식품의약품안전처`, `work_go_kr`)
*   `_collected_at`: 수집이 수행된 시점의 타임스탬프 (형식: `YYYY-MM-DD HH:MM:SS`)
*   `_guid`: 각 레코드의 무결성을 증명하는 고유 UUID (UUIDv4)

### B. 구조 평탄화 (Flattening)
*   **XML → Dict**: 고용24 등 XML 포맷으로 반환되는 API 응답을 `xmltodict`를 사용하여 파이썬 딕셔너리로 파싱합니다.
*   **JSON Depth 제거**: API 응답 내부에 중첩(Nested)된 JSON 구조가 있을 경우, 이를 CSV 형식에 맞게 단일 레벨의 평탄한(Flat) 구조로 변환합니다.

### C. 데이터 클렌징 및 포맷팅 (Cleansing)
*   **날짜 정규화**: 식약처 등에서 제공하는 `YYYYMMDD` (예: 20260514) 형식의 날짜 문자열을 ISO 표준인 `YYYY-MM-DD` (예: 2026-05-14) 포맷으로 일괄 변환합니다.
*   **화이트스페이스 제거**: 모든 문자열 값의 앞뒤 공백(Whitespace, 줄바꿈)을 자동으로 제거(Strip)합니다.
*   **엑셀 불필요 행 제거**: 파일로 제공되는 데이터(예: 강소기업 명단)의 경우 상단에 표기된 단순 텍스트 타이틀이나 빈 줄을 자동으로 건너뛰고, 실제 '연번' 컬럼을 감지하여 데이터를 추출합니다.
*   **구분자 충돌 방지**: 일부 공공 API(예: 성능인증 발급현황) 응답 본문에 포함된 잘못된 탭(`\t`)이나 쉼표(`,`) 문자가 CSV 구조를 망가뜨리지 않도록 제어하며, 최종 파일의 열 구분자로 쉼표 대신 특수 기호 `‡` (Double Dagger)를 사용하여 데이터 밀림 현상을 원천 차단합니다.

## 4. 기관별 세부 변환 (Specific Transformations)
### A. 식품의약품안전처 (FoodSafety)
*   **날짜 정규화**: `YYYYMMDD` (String) → `YYYY-MM-DD` (ISO 8601) 변환
### B. 공공데이터포털 (DataPortal)
*   **컬럼 재구성**: 원본 내 탭(`\t`) 구분 문자열 감지 시 개별 컬럼으로 파싱 및 확장
### C. 고용24 (Work24)
*   **데이터 모델**: XML 계층 구조 → 비정규화된 단일 테이블 변환 및 엑셀 헤더 감지 파싱

## 5. 운영 환경 및 제약 사항
*   **수집 방식**: API 페이지당 100~1,000건 단위 페이징 처리
*   **데이터 누락**: 식약처 모범음식점 등 기관 서버 제한으로 인한 실 수집량 차이 발생 가능

---
## 6. 데이터셋별 전체 컬럼 명세 (Full Column List)
**[SPOT 가이드]** 이 명세는 `dataset_catalog.yaml` 정의를 기반으로 자동 생성되었습니다.

### 📂 DataPortal_기술개발_우수기업
*   **출처**: 공공데이터포털
*   **비고**: 중소기업 기술개발 우수기업 현황. 과제번호(S/C 접두 코드) 포함.

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | 개발품목명 |
| 2 | 과제번호 |
| 3 | 기술개발 시작일 |
| 4 | 기술개발 종료일 |
| 5 | 내역사업명 |
| 6 | 사업명 |
| 7 | 사업자번호 |
| 8 | 우수사례 선정년도 |
| 9 | 주관기관 |
| 10 | 지역 |
| 11 | _source |
| 12 | _endpoint_key |
| 13 | _collected_at |
| 14 | _guid |

### 📂 DataPortal_기술개발제품_인증
*   **출처**: 공공데이터포털

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | 대표자 |
| 2 | 만료일자 |
| 3 | 사업자등록번호 |
| 4 | 업체명 |
| 5 | 인증구분 |
| 6 | 인증번호 |
| 7 | 인증일자 |
| 8 | 인증제품명 |
| 9 | _source |
| 10 | _endpoint_key |
| 11 | _collected_at |
| 12 | _guid |

### 📂 DataPortal_성능인증_발급현황
*   **출처**: 공공데이터포털
*   **비고**: 원본 API 응답에 탭(\t) 구분자 문자열 포함. 파이프라인이 자동 분리 처리함.

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | 신청구분 |
| 2 | 신청번호 |
| 3 | 차수 |
| 4 | 발급일자 |
| 5 | 사업자등록번호 |
| 6 | 업체명 |
| 7 | 신청품목 |
| 8 | 유효기간 |
| 9 | _source |
| 10 | _endpoint_key |
| 11 | _collected_at |
| 12 | _guid |

### 📂 DataPortal_인재육성형_중소기업
*   **출처**: 공공데이터포털

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | 대표자명 |
| 2 | 사업자번호 |
| 3 | 상호 |
| 4 | 선정일 |
| 5 | 연번 |
| 6 | 유효기간 종료일 |
| 7 | 주생산품 |
| 8 | 주소 |
| 9 | _source |
| 10 | _endpoint_key |
| 11 | _collected_at |
| 12 | _guid |

### 📂 DataPortal_전국_백년가게_현황
*   **출처**: 공공데이터포털

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | 기본주소 |
| 2 | 상세주소 |
| 3 | 시군구 |
| 4 | 시도 |
| 5 | 업체명 |
| 6 | 연락처 |
| 7 | 연번 |
| 8 | 주요사업 |
| 9 | _source |
| 10 | _endpoint_key |
| 11 | _collected_at |
| 12 | _guid |

### 📂 DataPortal_전국_백년소공인_지정
*   **출처**: 공공데이터포털

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | 업체명 |
| 2 | 업체주소 |
| 3 | 연락처 |
| 4 | 연번 |
| 5 | _source |
| 6 | _endpoint_key |
| 7 | _collected_at |
| 8 | _guid |

### 📂 DataPortal_창업기업확인서_정보
*   **출처**: 공공데이터포털
*   **비고**: KISED(한국창업진흥원) API. 필드명이 영문 약어로 제공됨.

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | brno |
| 2 | confmdoc_expr_dt |
| 3 | confmdoc_isu_dt |
| 4 | confmdoc_isu_no |
| 5 | crno |
| 6 | ntrp_nm |
| 7 | ntrp_type_nm |
| 8 | repr_nm |
| 9 | unin_repr_nm |
| 10 | _source |
| 11 | _endpoint_key |
| 12 | _collected_at |
| 13 | _guid |

### 📂 FoodSafety_HACCP_적용업소
*   **출처**: 식품의약품안전처
*   **비고**: 날짜 필드(YYYYMMDD)는 수집 시 YYYY-MM-DD 포맷으로 자동 변환됨.

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | PRSDNT_NM |
| 2 | SITE_ADDR |
| 3 | LCNS_NO |
| 4 | HACCP_APPN_DT |
| 5 | PRDLST_NM |
| 6 | BSSH_NM |
| 7 | CRTFC_RETN_DT |
| 8 | CLSBIZ_DT |
| 9 | INDUTY_CD_NM |
| 10 | HACCP_APPN_NO |
| 11 | CRTFC_ENDDT |
| 12 | CLSBIZ_DVS_CD_NM |
| 13 | ASGN_CANCL_DT |
| 14 | _source |
| 15 | _service_code |
| 16 | _collected_at |
| 17 | _guid |

### 📂 FoodSafety_식품모범음식점
*   **출처**: 식품의약품안전처
*   **비고**: 기관 서버 제한으로 실제 수집량이 기대치에 미달할 수 있음.


| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | OPERT_DT |
| 2 | LCNS_NO |
| 3 | YEAR |
| 4 | APPN_DT |
| 5 | BSSH_NM |
| 6 | SIGNGU_NM |
| 7 | APLC_DT |
| 8 | PNCPL_FOOD_NM |
| 9 | _source |
| 10 | _service_code |
| 11 | _collected_at |
| 12 | _guid |

### 📂 Work24_청년친화강소기업
*   **출처**: 고용24 (워크넷)
*   **비고**: XML API 응답을 xmltodict로 파싱. 필드명이 영문 camelCase로 제공됨.

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | coNm |
| 2 | busiNo |
| 3 | reperNm |
| 4 | superIndTpCd |
| 5 | superIndTpNm |
| 6 | indTpCd |
| 7 | indTpNm |
| 8 | _source |
| 9 | _endpoint_key |
| 10 | _collected_at |
| 11 | _guid |

### 📂 Work24_강소기업_명단
*   **출처**: 고용노동부
*   **비고**: 고용노동부 선정 강소기업 명단 (ZIP 내 엑셀 데이터 추출).

| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | 연번 |
| 2 | 사업자명 |
| 3 | 사업자등록번호 |
| 4 | 업종명(대분류) |
| 5 | 소재지 |
| 6 | _source |
| 7 | _collected_at |
| 8 | _guid |
