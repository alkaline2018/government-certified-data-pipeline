"""
pipeline/foodsafety.py
======================
식품의약품안전처(foodsafetykorea.go.kr) 데이터 수집 파이프라인.

[응답 구조 - 실제 API 호출로 확인]
  GET http://openapi.foodsafetykorea.go.kr/api/{KEY}/{SERVICE}/json/{시작}/{끝}

  I0580 (HACCP 적용업소) 응답 예시:
  {
    "I0580": {
      "total_count": "39008",
      "row": [
        {
          "PRSDNT_NM": "김**",
          "SITE_ADDR": "부산광역시 사하구 ...",
          "LCNS_NO": "19970144521",
          "HACCP_APPN_DT": "20260511",
          "PRDLST_NM": "기타 수산물가공품",
          "BSSH_NM": "(주)범우물산",
          "CRTFC_RETN_DT": "",
          "CLSBIZ_DT": "",
          "INDUTY_CD_NM": "식품제조가공업",
          "HACCP_APPN_NO": "2025-2-0278",
          "CRTFC_ENDDT": "20290510",
          "CLSBIZ_DVS_CD_NM": "정상",
          "ASGN_CANCL_DT": "20290510"
        }
      ],
      "RESULT": {"MSG": "정상처리되었습니다.", "CODE": "INFO-000"}
    }
  }

  I1590 (식품모범음식점) 응답 예시:
  {
    "I1590": {
      "total_count": "24832",
      "row": [
        {
          "OPERT_DT": "20060719",
          "LCNS_NO": "19970538581",
          "YEAR": "1997년",
          "APPN_DT": "20060719",
          "BSSH_NM": "강남숯불식당",
          "SIGNGU_NM": "경상북도 경주시",
          "APLC_DT": "20060719",
          "PNCPL_FOOD_NM": "숯불구이"
        }
      ],
      "RESULT": {"MSG": "정상처리되었습니다.", "CODE": "INFO-000"}
    }
  }

[페이징 방식]
  - URL Path Variable: /api/{KEY}/{SERVICE}/json/{시작번호}/{끝번호}
  - 시작번호=1, 끝번호=per_page 로 첫 페이지 호출 후 total_count 파악
  - 이후 per_page 단위로 시작/끝 번호를 증가시키며 전체 수집

[수집 주기]
  - 권장: 연 1회 (전체 갱신)
"""
import logging
import math
import os

from pipeline.base import BasePipeline
from pathlib import Path

logger = logging.getLogger(__name__)

# 식약처 API 공통 Base URL
_FOODSAFETY_BASE = "http://openapi.foodsafetykorea.go.kr/api"

# 수집 대상 서비스 코드 → (서비스코드, 한글명) 매핑
FOODSAFETY_SERVICES = {
    "haccp": ("I0580", "HACCP_적용업소"),
    "restaurant": ("I1590", "식품모범음식점"),
}


class FoodSafetyPipeline(BasePipeline):
    """
    식품의약품안전처 데이터 수집 파이프라인.

    Args:
        service_key (str): 수집할 서비스 키 ('haccp' | 'restaurant')
        per_page (int): 페이지당 수집 건수 (테스트: 1, 운영: 1000)
    """

    def __init__(self, service_key: str = "haccp", per_page: int = 1000, max_pages: int | None = None):
        super().__init__(per_page=per_page, max_pages=max_pages)

        if service_key not in FOODSAFETY_SERVICES:
            raise ValueError(
                f"service_key는 {list(FOODSAFETY_SERVICES.keys())} 중 하나여야 합니다."
            )

        self.service_key = service_key
        self.service_code, self.service_name = FOODSAFETY_SERVICES[service_key]
        self.api_key = os.environ["FOODSAFETYKOREA_API_KEY"]
        # 작업명을 서비스별로 구분
        self.job_name = f"FoodSafety_{self.service_name}"

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------

    def _build_url(self, start: int, end: int) -> str:
        """
        식약처 Path Variable 방식 URL을 구성한다.
        예: /api/{KEY}/I0580/json/1/1000
        """
        return f"{_FOODSAFETY_BASE}/{self.api_key}/{self.service_code}/json/{start}/{end}"

    def _fetch_page(self, start: int, end: int) -> dict:
        """단일 페이지 요청 → 응답 JSON dict 반환 (재시도 포함)."""
        url = self._build_url(start, end)
        logger.debug(f"[{self.job_name}] 요청: {url}")
        resp = self._get(url)
        data = resp.json()

        # 식약처 API 자체 오류 코드 체크
        result = data.get(self.service_code, {}).get("RESULT", {})
        code = result.get("CODE", "")
        if not code.startswith("INFO-"):
            raise RuntimeError(
                f"식약처 API 오류 응답: CODE={code}, MSG={result.get('MSG')}"
            )
        return data

    # ------------------------------------------------------------------
    # 파이프라인 3단계
    # ------------------------------------------------------------------

    def collect(self) -> None:
        """
        [1단계] 전체 페이지를 순회하며 원본 row 리스트를 self._raw_pages 에 누적.
        식약처는 페이지당 최대 1000건을 권장한다.
        """
        # 첫 페이지 호출로 total_count 파악
        first_data = self._fetch_page(1, self.per_page)
        body = first_data[self.service_code]
        total_count = int(body.get("total_count", 0))
        self.expected_total = total_count # 통계용 설정
        
        rows = body.get("row", [])
        self._raw_pages.append(rows)

        logger.info(f"[{self.job_name}] 전체 건수: {total_count:,}건 | per_page={self.per_page}")

        if total_count <= self.per_page:
            return  # 단일 페이지로 완료

        # 나머지 페이지 순회 (max_pages 제한 적용)
        total_pages = math.ceil(total_count / self.per_page)
        limit = min(total_pages, self.max_pages) if self.max_pages else total_pages
        if self.max_pages:
            logger.info(f"[{self.job_name}] max_pages={self.max_pages} 제한 적용 (전체 {total_pages}페이지 중 {limit}페이지만 수집)")

        for page_no in range(2, limit + 1):
            start = (page_no - 1) * self.per_page + 1
            end = min(page_no * self.per_page, total_count)
            logger.info(f"[{self.job_name}] 페이지 {page_no}/{limit} ({start}~{end})")

            page_data = self._fetch_page(start, end)
            page_rows = page_data[self.service_code].get("row", [])
            self._raw_pages.append(page_rows)

    def refine(self) -> None:
        """
        [2단계] 원본 데이터 정제.
        """
        for page_rows in self._raw_pages:
            for row in page_rows:
                refined = {}
                for k, v in row.items():
                    # 빈 문자열 → None
                    val = v.strip() if isinstance(v, str) else v
                    val = None if val == "" else val

                    # YYYYMMDD 형식 날짜 → YYYY-MM-DD
                    if isinstance(val, str) and len(val) == 8 and val.isdigit():
                        val = f"{val[:4]}-{val[4:6]}-{val[6:]}"

                    refined[k] = val

                # 메타 필드 추가
                refined["_source"] = "foodsafetykorea"
                refined["_service_code"] = self.service_code
                self._refined_records.append(refined)

    def extract(self) -> Path:
        """[3단계] 정제된 데이터를 CSV 파일로 저장."""
        filename = f"{self.job_name}_{self._today_str()}.csv"
        return self._save_csv(self._refined_records, filename)

