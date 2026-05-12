"""
pipeline/dataportal.py
======================
공공데이터포털(api.odcloud.kr / apis.data.go.kr) 데이터 수집 파이프라인.

[응답 구조 - 실제 API 호출로 확인]
  GET {URL}?page=1&perPage=1&returnType=JSON&serviceKey={KEY}

  공통 JSON 응답 구조:
  {
    "currentCount": 1,        # 현재 페이지 실제 건수
    "data": [ {...}, ... ],   # 레코드 리스트
    "matchCount": 111,        # 검색 결과 총 건수
    "page": 1,
    "perPage": 1,
    "totalCount": 111         # 전체 데이터 건수 (페이징 기준)
  }

  주의: 성능인증 발급현황(15001979)의 data 필드 안에 탭(\t) 구분자로 된
        단일 문자열 컬럼이 있음. refine 단계에서 자동 감지하여 분리 처리함.

[페이징 방식]
  - Query Parameter: page (1-indexed), perPage
  - totalCount 기준으로 전체 페이지 계산

[수집 주기]
  - 권장: 월 1회 (URL이 수시로 변경될 수 있으므로 설정에서 관리)
"""
import logging
import math
import os

from pipeline.base import BasePipeline
from pathlib import Path

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 수집 대상 엔드포인트 레지스트리
# job_key → (endpoint_url, 한글명)
# URL이 변경될 경우 이 딕셔너리만 수정하면 된다.
# ------------------------------------------------------------------
DATAPORTAL_ENDPOINTS: dict[str, tuple[str, str]] = {
    "tech_excellence": (
        "https://api.odcloud.kr/api/15025589/v1/uddi:0dc2205a-331b-4b9a-89ea-86819ccb30c7",
        "기술개발_우수기업",
    ),
    "performance_cert": (
        "https://api.odcloud.kr/api/15001979/v1/uddi:62d398da-ff52-4ecc-b90e-a9b20cfe7e1e",
        "성능인증_발급현황",
    ),
    "startup_cert": (
        "https://apis.data.go.kr/B552735/kisedCertService/getCorporateInformation",
        "창업기업확인서_정보",
    ),
    "century_store": (
        "https://api.odcloud.kr/api/15102255/v1/uddi:c198d295-7df7-49ad-a7a4-a70c8967d23e",
        "전국_백년가게_현황",
    ),
    "century_craftsman": (
        "https://api.odcloud.kr/api/15132698/v1/uddi:d6fa41d1-87cc-41cd-a3e9-a6575914b9a1",
        "전국_백년소공인_지정",
    ),
    "talent_sme": (
        "https://api.odcloud.kr/api/15018880/v1/uddi:d6782e0a-614c-4436-ba26-a7a4cc8b230a",
        "인재육성형_중소기업",
    ),
    "tech_product_cert": (
        "https://api.odcloud.kr/api/3033913/v1/uddi:27bb6889-e56d-4cdc-a222-9f02900c81e7",
        "기술개발제품_인증",
    ),
}


class DataPortalPipeline(BasePipeline):
    """
    공공데이터포털 데이터 수집 파이프라인.

    Args:
        endpoint_key (str): DATAPORTAL_ENDPOINTS 딕셔너리의 키
        per_page (int): 페이지당 수집 건수 (테스트: 1, 운영: 1000)
    """

    def __init__(self, endpoint_key: str = "tech_excellence", per_page: int = 1000, max_pages: int | None = None):
        super().__init__(per_page=per_page, max_pages=max_pages)

        if endpoint_key not in DATAPORTAL_ENDPOINTS:
            raise ValueError(
                f"endpoint_key는 {list(DATAPORTAL_ENDPOINTS.keys())} 중 하나여야 합니다."
            )

        self.endpoint_key = endpoint_key
        self.endpoint_url, self.dataset_name = DATAPORTAL_ENDPOINTS[endpoint_key]
        # 인코딩된 키를 그대로 사용 (requests가 추가 인코딩하지 않도록 params 직접 주입)
        self.api_key = os.environ["DATAPORTAL_ENCODING_API_KEY"]

        self.job_name = f"DataPortal_{self.dataset_name}"

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------

    def _build_params(self, page: int) -> dict:
        """공통 쿼리 파라미터 딕셔너리를 반환한다."""
        return {
            "page": page,
            "perPage": self.per_page,
            "returnType": "JSON",
            "serviceKey": self.api_key,
        }

    def _fetch_page(self, page: int) -> dict:
        """단일 페이지 요청 → JSON dict 반환."""
        params = self._build_params(page)
        logger.debug(f"[{self.job_name}] 요청: {self.endpoint_url} page={page}")

        # serviceKey가 이미 인코딩된 상태이므로, requests의 자동 인코딩을 우회하기 위해
        # URL에 직접 쿼리스트링을 붙인다.
        from urllib.parse import urlencode
        query_string = urlencode({k: v for k, v in params.items() if k != "serviceKey"})
        full_url = f"{self.endpoint_url}?{query_string}&serviceKey={self.api_key}"

        resp = self._get(full_url)
        data = resp.json()

        if "data" not in data:
            raise RuntimeError(
                f"공공데이터포털 응답에 'data' 필드 없음: {str(data)[:200]}"
            )
        return data

    # ------------------------------------------------------------------
    # 탭 구분자 컬럼 감지 및 분리 (성능인증 API 특수 처리)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_tab_column(row: dict) -> dict:
        """
        컬럼명에 탭(\t)이 포함된 경우 분리한다.
        예: "신청구분\t신청번호\t..." 형태의 키를 개별 필드로 분리.
        """
        new_row = {}
        for key, val in row.items():
            if "\t" in key and isinstance(val, str) and "\t" in val:
                col_names = key.split("\t")
                col_vals = val.split("\t")
                # 컬럼 수와 값 수가 맞지 않을 수 있으므로 zip으로 안전하게 처리
                for col_name, col_val in zip(col_names, col_vals):
                    col_name = col_name.strip()
                    col_val = col_val.strip() if isinstance(col_val, str) else col_val
                    new_row[col_name] = None if col_val == "" else col_val
            else:
                new_row[key] = val
        return new_row

    # ------------------------------------------------------------------
    # 파이프라인 3단계
    # ------------------------------------------------------------------

    def collect(self) -> None:
        """
        [1단계] page=1 호출로 totalCount 파악 후 전체 페이지 순회.
        """
        first_data = self._fetch_page(1)
        total_count = first_data.get("totalCount", 0)
        self.expected_total = total_count
        
        self._raw_pages.append(first_data["data"])

        logger.info(
            f"[{self.job_name}] 전체 건수: {total_count:,}건 | per_page={self.per_page}"
        )

        if total_count <= self.per_page:
            return

        total_pages = math.ceil(total_count / self.per_page)
        limit = min(total_pages, self.max_pages) if self.max_pages else total_pages
        if self.max_pages:
            logger.info(f"[{self.job_name}] max_pages={self.max_pages} 제한 적용")
        for page_no in range(2, limit + 1):
            logger.info(f"[{self.job_name}] 페이지 {page_no}/{limit}")
            page_data = self._fetch_page(page_no)
            self._raw_pages.append(page_data["data"])

    def refine(self) -> None:
        """
        [2단계] 원본 데이터 정제.
        """
        for page_rows in self._raw_pages:
            for row in page_rows:
                # 탭 구분자 컬럼 처리
                refined = self._split_tab_column(row)

                # 필드별 타입 정규화
                normalized = {}
                for k, v in refined.items():
                    if isinstance(v, str):
                        v = v.strip()
                        v = None if v == "" else v
                    elif isinstance(v, (int, float)) and k in (
                        "사업자번호", "사업자등록번호", "사업자번호", "연번"
                    ):
                        # 사업자번호 등은 문자열로 보관 (앞자리 0 손실 방지)
                        v = str(int(v))

                    normalized[k] = v

                # 메타 필드
                normalized["_source"] = "dataportal"
                normalized["_endpoint_key"] = self.endpoint_key
                self._refined_records.append(normalized)

    def extract(self) -> Path:
        """[3단계] 정제된 데이터를 CSV 파일로 저장."""
        filename = f"{self.job_name}_{self._today_str()}.csv"
        return self._save_csv(self._refined_records, filename)

