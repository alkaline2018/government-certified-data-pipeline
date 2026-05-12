# [기술 사양서] 데이터 수집 및 정제 정의 (Data Transformation Spec)

## 1. 파일 규격 (Output Specs)
*   **포맷**: CSV (Flat File)
*   **인코딩**: UTF-8 with BOM (`utf-8-sig`)
*   **구분자(Delimiter)**: `‡` (Double Dagger)
*   **저장 경로**: `output/csv_export/{JOB_NAME}_{YYYYMMDD}.csv` 

## 2. 공통 정제 규칙 (General Normalization)
| 항목 | 적용 내용 |
| :--- | :--- |
| **공백 처리** | 모든 필드 값 Leading/Trailing Whitespace 제거 |
| **결측값** | 빈 문자열("") → `NULL` (None) 변환 |
| **타입 보존** | 사업자번호, 인가번호 등 숫자형 식별자의 문자열(String) 포맷 유지 |
| **추적 필드** | `_source`, `_service_code`, `_endpoint_key` 메타 필드 추가 |

## 3. 기관별 세부 변환 (Specific Transformations)
### A. 식품의약품안전처 (FoodSafety)
*   **날짜 정규화**: `YYYYMMDD` (String) → `YYYY-MM-DD` (ISO 8601) 변환
### B. 공공데이터포털 (DataPortal)
*   **컬럼 재구성**: 원본 내 탭(`\t`) 구분 문자열 감지 시 개별 컬럼으로 파싱 및 확장
### C. 고용24 (Work24)
*   **데이터 모델**: XML 계층 구조 → 비정규화된 단일 테이블 변환

## 4. 운영 환경 및 제약 사항
*   **수집 방식**: API 페이지당 100~1,000건 단위 페이징 처리
*   **데이터 누락**: 식약처 모범음식점 등 기관 서버 제한으로 인한 실 수집량 차이 발생 가능

---
## 5. 데이터셋별 전체 컬럼 명세 (Full Column List)
각 데이터셋별 실제 CSV에 포함된 전체 컬럼 목록입니다.

### 📂 DataPortal_기술개발_우수기업
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

### 📂 DataPortal_기술개발제품_인증
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

### 📂 DataPortal_성능인증_발급현황
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

### 📂 DataPortal_인재육성형_중소기업
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

### 📂 DataPortal_전국_백년가게_현황
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

### 📂 DataPortal_전국_백년소공인_지정
| 순번 | 컬럼명 |
| :--- | :--- |
| 1 | 업체명 |
| 2 | 업체주소 |
| 3 | 연락처 |
| 4 | 연번 |
| 5 | _source |
| 6 | _endpoint_key |

### 📂 DataPortal_창업기업확인서_정보
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

### 📂 FoodSafety_HACCP_적용업소
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

### 📂 FoodSafety_식품모범음식점
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

### 📂 Work24_youth_friendly
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
