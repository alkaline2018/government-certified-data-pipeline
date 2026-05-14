"""
pipeline/work24.py
==================
고용24(워크넷, www.work24.go.kr) 데이터 수집 파이프라인.

[응답 구조 - 실제 API 호출로 확인]
  GET {URL}?authKey={KEY}&returnType=XML&startPage=1&display=1

  XML 응답 구조 (청년친화강소기업, smallGiantsList):
  <?xml version="1.0" encoding="UTF-8"?>
  <smallGiantsList>
    <total>224</total>           <!-- 전체 건수 -->
    <startPage>1</startPage>
    <display>1</display>
    <smallGiant>
      <coNm>주식회사 지씨</coNm>
      <busiNo>6058141445</busiNo>
      <reperNm>이상길</reperNm>
      <superIndTpCd>J</superIndTpCd>
      <superIndTpNm>정보통신업</superIndTpNm>
      <indTpCd>62</indTpCd>
      <indTpNm>컴퓨터 프로그래밍, 시스템 통합 및 관리업</indTpNm>
    </smallGiant>
  </smallGiantsList>

[페이징 방식]
  - Query Parameter: startPage (1-indexed), display (per page)
  - <total> 태그에서 전체 건수 파악 후 페이징

[응답 포맷 특이사항]
  - xmltodict 파싱 시:
    · 단건: smallGiant 가 dict로 반환됨
    · 다건: smallGiant 가 list로 반환됨
    → 항상 list로 정규화하여 처리

[수집 주기]
  - 권장: 월 1회
"""
import logging
import math
import os
import zipfile         # 추가
import shutil          # 추가
from typing import Dict, Tuple, Optional, List, Any, Union # Any, Union 추가

import xmltodict
import requests        # 추가
import openpyxl        # 추가

from pipeline.base import BasePipeline
from pathlib import Path

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 수집 대상 엔드포인트 레지스트리
# ------------------------------------------------------------------
WORK24_ENDPOINTS: Dict[str, Tuple[str, str, str]] = {
    "youth_friendly": (
        "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo216L31.do",
        "smallGiantsList",   # XML 루트 태그명
        "smallGiant",        # XML 레코드 태그명
    ),
}


class Work24Pipeline(BasePipeline):
    """
    고용24 데이터 수집 파이프라인 (XML 응답).

    Args:
        endpoint_key (str): WORK24_ENDPOINTS 딕셔너리의 키
        per_page (int): 페이지당 수집 건수 (테스트: 1, 운영: 100)
    """

    def __init__(self, endpoint_key: str = "youth_friendly", per_page: int = 100, max_pages: Optional[int] = None):
        # 고용24 API는 한 번에 최대 100건(display)까지만 지원함.
        # 만약 그 이상이 입력되면 100으로 제한하여 페이징이 정상 동작하게 함.
        per_page = min(per_page, 100)
        super().__init__(per_page=per_page, max_pages=max_pages)

        if endpoint_key not in WORK24_ENDPOINTS:
            raise ValueError(
                f"endpoint_key는 {list(WORK24_ENDPOINTS.keys())} 중 하나여야 합니다."
            )

        self.endpoint_key = endpoint_key
        self.endpoint_url, self.root_tag, self.record_tag = WORK24_ENDPOINTS[endpoint_key]
        self.api_key = os.environ["WORK24_API_KEY"]

        self.job_name = "Work24_청년친화강소기업" if endpoint_key == "youth_friendly" else f"Work24_{endpoint_key}"

        # Accept 헤더를 XML로 덮어씌움
        self.session.headers.update({"Accept": "application/xml, text/xml, */*"})

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------

    def _build_params(self, start_page: int) -> Dict:
        return {
            "authKey": self.api_key,
            "returnType": "XML",
            "startPage": start_page,
            "display": self.per_page,
        }

    def _fetch_and_parse(self, start_page: int) -> Tuple[int, List[Dict]]:
        """
        단일 페이지 요청 → (total, records) 반환.
        xmltodict로 XML을 파싱한 후 레코드 리스트를 반환한다.
        """
        params = self._build_params(start_page)
        logger.debug(f"[{self.job_name}] 요청: {self.endpoint_url} startPage={start_page}")

        resp = self._get(self.endpoint_url, params=params)
        # XML 파싱
        parsed = xmltodict.parse(resp.text)
        root = parsed.get(self.root_tag, {})

        total = int(root.get("total", 0))
        raw_records = root.get(self.record_tag, [])

        # xmltodict는 단건일 때 dict, 다건일 때 list를 반환
        # → 항상 list로 정규화
        if isinstance(raw_records, dict):
            raw_records = [raw_records]
        elif raw_records is None:
            raw_records = []

        return total, raw_records

    def _extract_records_from_raw(self, raw_data: Dict) -> List[Dict]:
        """워크넷 응답 dict에서 레코드 리스트를 추출한다."""
        root = raw_data.get(self.root_tag, {})
        raw_records = root.get(self.record_tag, [])
        if isinstance(raw_records, dict):
            return [raw_records]
        return raw_records or []

    # ------------------------------------------------------------------
    # 파이프라인 3단계
    # ------------------------------------------------------------------

    def collect(self) -> None:
        """
        [1단계] startPage=1 호출로 <total> 파악 후 전체 페이지 순회.
        """
        params = self._build_params(1)
        resp = self._get(self.endpoint_url, params=params)
        first_data = xmltodict.parse(resp.text)
        self.save_raw(first_data, 1) # 원본 저장

        root = first_data.get(self.root_tag, {})
        total_count = int(root.get("total", 0))
        self.expected_total = total_count
        
        rows = self._extract_records_from_raw(first_data)
        self._raw_pages.append(rows)

        logger.info(
            f"[{self.job_name}] 전체 건수: {total_count:,}건 | display(per_page)={self.per_page}"
        )

        if total_count <= self.per_page:
            return

        total_pages = math.ceil(total_count / self.per_page)
        limit = min(total_pages, self.max_pages) if self.max_pages else total_pages
        if self.max_pages:
            logger.info(f"[{self.job_name}] max_pages={self.max_pages} 제한 적용")
        for page_no in range(2, limit + 1):
            logger.info(f"[{self.job_name}] 페이지 {page_no}/{limit}")
            params = self._build_params(page_no)
            resp = self._get(self.endpoint_url, params=params)
            page_data = xmltodict.parse(resp.text)
            self.save_raw(page_data, page_no)
            
            rows = self._extract_records_from_raw(page_data)
            self._raw_pages.append(rows)

    def refine(self) -> None:
        """
        [2단계] XML → dict 로 변환된 원본 데이터 정제.
        """
        for page_records in self._raw_pages:
            for record in page_records:
                # OrderedDict → dict (Python 3.7+ dict는 순서 보장)
                refined = {}
                for k, v in record.items():
                    # xmltodict의 None은 Python None
                    if v is None or v == "":
                        v = None
                    elif isinstance(v, str):
                        v = v.strip() or None

                    refined[k] = v

                # 메타 필드 추가 (_source, _collected_at, _guid 등)
                refined["_source"] = "work24"
                refined["_endpoint_key"] = self.endpoint_key
                self._add_metadata(refined)
                
                self._refined_records.append(refined)

    def extract(self) -> Path:
        """[3단계] 정제된 데이터를 CSV 파일로 저장."""
        filename = f"{self.job_name}_{self._today_str()}.csv"
        return self._save_csv(self._refined_records, filename)


class EmploymentSmallGiantsPipeline(BasePipeline):
    """
    고용노동부 강소기업 명단 수집 파이프라인.
    """

    DOWNLOAD_URL = "https://www.work.go.kr/framework/filedownload/keisDownload.do?filePathName=oHBzib3Tsgxld0j94wJVE8nwpmxv7UvLLE4wk5KpcRJkPBYwuwPkQyPbUrhz2gBDKrWsM8stQ85pK%2BgLzEJ2wQ%3D%3D&realFileNm=MjAyNOuFhOuPhCDqs6Dsmqnrhbjrj5nrtoAg7ISg7KCVIOqwleyGjOq4sOyXhSDrqoXri6go6rKM7Iuc7JqpKS56aXA%3D"
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "Referer": "https://www.work.go.kr/jobyoung/smallGiants/corpInfoSrchList.do?coGbCd=small",
        "Cookie": "WMONID=N0s2yj-_qNl; PCID=17782056277088037627321; isOffer=Y; WORKNETSESSIONID=47ElPEbwuhZD9hj7lI9JHSY3I47nxbYhYyK8jnW7sbbq7-HMbN7C!-1500919948!440871721"
    }

    def __init__(self, per_page: int = 1000, max_pages: Optional[int] = None):
        super().__init__(per_page=per_page, max_pages=max_pages)
        self.job_name = "Work24_강소기업_명단"
        self._extracted_files: List[Path] = []

    def collect(self) -> None:
        """[1단계] ZIP 파일 다운로드 및 압축 해제."""
        logger.info(f"[{self.job_name}] 다운로드 시작: {self.DOWNLOAD_URL}")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        zip_path = self.raw_dir / "downloaded_data.zip"

        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        resp = requests.get(self.DOWNLOAD_URL, headers=self.HEADERS, verify=False, timeout=60)
        resp.raise_for_status()

        with open(zip_path, "wb") as f:
            f.write(resp.content)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(self.raw_dir)
            self._extracted_files = [self.raw_dir / name for name in zip_ref.namelist()]
        
        logger.info(f"[{self.job_name}] 다운로드 및 압축 해제 완료")

    def refine(self) -> None:
        """[2단계] 해제된 파일 중 엑셀 파일을 찾아 데이터 정제."""
        excel_files = [f for f in self._extracted_files if f.suffix.lower() in ('.xlsx', '.xls')]
        if not excel_files:
            logger.error(f"[{self.job_name}] 엑셀 파일 없음")
            return

        target_file = excel_files[0]
        try:
            wb = openpyxl.load_workbook(target_file, data_only=True)
            sheet = wb.active
            rows = list(sheet.rows)
            if not rows: return

            # 실제 헤더 행 찾기 (예: '연번' 단어가 포함된 행)
            header_idx = 0
            for i, row in enumerate(rows):
                vals = [str(cell.value) if cell.value else "" for cell in row]
                if "연번" in vals:
                    header_idx = i
                    break
            
            header = [str(cell.value).strip() if cell.value else None for cell in rows[header_idx]]
            
            for row in rows[header_idx + 1:]:
                # 모든 셀이 비어있으면 건너뜀
                if not any(cell.value for cell in row):
                    continue

                record = {}
                for i, cell in enumerate(row):
                    if i < len(header) and header[i]:
                        key = header[i]
                        val = cell.value
                        if isinstance(val, str): val = val.strip()
                        record[key] = val
                
                record["_source"] = "work_go_kr"
                self._add_metadata(record)
                self._refined_records.append(record)
            wb.close()
        except Exception as e:
            logger.error(f"[{self.job_name}] 엑셀 파싱 실패: {e}")
            raise

    def extract(self) -> Path:
        """[3단계] 정제된 데이터를 CSV로 저장."""
        filename = f"{self.job_name}_{self._today_str()}.csv"
        return self._save_csv(self._refined_records, filename)

    def _extract_records_from_raw(self, raw_data: Any) -> List[dict]:
        return []

