import os
import yaml
from pathlib import Path

def load_catalog():
    """Single Point of Truth인 dataset_catalog.yaml을 로드한다."""
    catalog_path = Path(__file__).parent / "dataset_catalog.yaml"
    with open(catalog_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["datasets"]

def generate_spec():
    datasets_spec = load_catalog()
    
    md = []
    md.append('# [기술 사양서] 데이터 수집 및 정제 정의 (Data Transformation Spec)\n')
    md.append('## 1. 파일 규격 (Output Specs)')
    md.append('*   **포맷**: CSV (Flat File)')
    md.append('*   **인코딩**: UTF-8 with BOM (`utf-8-sig`)')
    md.append('*   **구분자(Delimiter)**: `‡` (Double Dagger)')
    md.append('*   **저장 경로**: `storage/output/{JOB_NAME}_{YYYYMMDD}.csv` \n')

    md.append('## 2. 공통 정제 규칙 (General Normalization)')
    md.append('| 항목 | 적용 내용 |')
    md.append('| :--- | :--- |')
    md.append('| **공백 처리** | 모든 필드 값 Leading/Trailing Whitespace 제거 |')
    md.append('| **결측값** | 빈 문자열("") → `NULL` (None) 변환 |')
    md.append('| **타입 보존** | 사업자번호, 인가번호 등 숫자형 식별자의 문자열(String) 포맷 유지 |')
    md.append('| **추적 필드** | `_source`, `_collected_at`, `_guid` 메타 필드 추가 |\n')

    md.append('## 3. 기관별 세부 변환 (Specific Transformations)')
    md.append('### A. 식품의약품안전처 (FoodSafety)')
    md.append('*   **날짜 정규화**: `YYYYMMDD` (String) → `YYYY-MM-DD` (ISO 8601) 변환')
    md.append('### B. 공공데이터포털 (DataPortal)')
    md.append('*   **컬럼 재구성**: 원본 내 탭(`\\t`) 구분 문자열 감지 시 개별 컬럼으로 파싱 및 확장')
    md.append('### C. 고용24 (Work24)')
    md.append('*   **데이터 모델**: XML 계층 구조 → 비정규화된 단일 테이블 변환\n')

    md.append('## 4. 운영 환경 및 제약 사항')
    md.append('*   **수집 방식**: API 페이지당 100~1,000건 단위 페이징 처리')
    md.append('*   **데이터 누락**: 식약처 모범음식점 등 기관 서버 제한으로 인한 실 수집량 차이 발생 가능\n')

    md.append('---')
    md.append('## 5. 데이터셋별 전체 컬럼 명세 (Full Column List)')
    md.append('**[SPOT 가이드]** 이 명세는 `dataset_catalog.yaml` 정의를 기반으로 자동 생성되었습니다.\n')

    for spec in datasets_spec:
        name = spec["name"]
        columns = spec["columns"]
        notes = spec.get("notes", "")
        source = spec.get("source", "N/A")
        
        md.append(f'### 📂 {name}')
        md.append(f'*   **출처**: {source}')
        if notes:
            md.append(f'*   **비고**: {notes}')
        
        md.append('\n| 순번 | 컬럼명 |')
        md.append('| :--- | :--- |')
        for i, col in enumerate(columns, 1):
            md.append(f'| {i} | {col} |')
        md.append('')

    with open('DATA_SPEC.md', 'w', encoding='utf-8') as out:
        out.write('\n'.join(md))
    print("DATA_SPEC.md (SPOT Version) generated successfully.")

if __name__ == "__main__":
    generate_spec()
