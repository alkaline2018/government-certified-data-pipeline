"""
pipeline/base.py
================
모든 기관별 파이프라인 클래스가 상속받는 추상 Base 클래스.

흐름: collect() -> refine() -> extract() -> run()
"""
import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from pipeline.notifier import SlackNotifier

logger = logging.getLogger(__name__)


class BasePipeline(ABC):
    """
    데이터 수집 파이프라인 추상 기반 클래스.

    Attributes:
        job_name (str): 작업 식별자 (CLI --job 인자와 동일)
        per_page (int): 페이지당 수집 건수 (테스트: 1, 운영: 1000)
        output_dir (Path): 추출 결과 JSON 파일 저장 경로
        notifier (SlackNotifier): Slack 알림 전송 객체
    """

    # 네트워크/일시 오류에만 재시도 적용
    RETRYABLE_EXCEPTIONS = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    )

    def __init__(self, per_page: int = 1000, max_pages: int | None = None):
        self.job_name: str = self.__class__.__name__
        self.per_page: int = per_page
        self.max_pages: int | None = max_pages
        
        # 저장 구조 개편: storage/output
        self.output_dir = Path("storage") / "output"
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.notifier = SlackNotifier()

        # 수집 시점 고정 (모든 레코드에 동일하게 적용)
        self.collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 공통 HTTP 세션
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

        # 수집 통계 및 버퍼
        self.total_requests = 0
        self.success_requests = 0
        self.expected_total = 0  # API에서 제공하는 전체 건수
        self._raw_pages: list[list[dict]] = []
        self._refined_records: list[dict] = []

    @property
    def raw_dir(self) -> Path:
        """현재 작업명과 날짜에 기반한 원본 데이터 저장 경로."""
        return Path("storage") / "raw" / self.job_name / self._today_str()

    # ------------------------------------------------------------------
    # 추상 메서드
    # ------------------------------------------------------------------

    @abstractmethod
    def collect(self) -> None:
        ...

    @abstractmethod
    def refine(self) -> None:
        ...

    @abstractmethod
    def extract(self) -> Path:
        """[3단계] 정제된 데이터를 CSV 파일로 저장하고 경로 반환."""
        ...

    @abstractmethod
    def _extract_records_from_raw(self, raw_data: Any) -> list[dict]:
        """원본 데이터(JSON/XML)에서 실제 레코드 리스트를 추출한다."""
        ...

    # ------------------------------------------------------------------
    # 로컬 저장 및 로드 (Persistence)
    # ------------------------------------------------------------------

    def save_raw(self, data: list[dict] | dict, page_no: int) -> None:
        """API에서 받은 원본 데이터를 로컬 storage/raw/ 에 저장한다."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.raw_dir / f"page_{page_no:04d}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"[{self.job_name}] 원본 저장 완료: {file_path}")
        except Exception as e:
            logger.error(f"[{self.job_name}] 원본 저장 실패: {e}")

    def load_raw(self) -> bool:
        """로컬 storage/raw/ 에서 오늘 원본 데이터를 읽어온다."""
        if not self.raw_dir.exists():
            logger.error(f"[{self.job_name}] 로드할 원본 데이터가 없습니다: {self.raw_dir}")
            return False

        files = sorted([f for f in os.listdir(self.raw_dir) if f.endswith(".json")])
        if not files:
            return False

        self._raw_pages = []
        for filename in files:
            file_path = self.raw_dir / filename
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                records = self._extract_records_from_raw(data)
                self._raw_pages.append(records)

        logger.info(f"[{self.job_name}] 로컬 파일 {len(self._raw_pages)}개 로드 완료")
        return True

    def _add_metadata(self, record: dict) -> dict:
        """레코드에 공통 메타데이터(_collected_at, _guid)를 추가한다."""
        record["_collected_at"] = self.collected_at
        record["_guid"] = str(uuid.uuid4())
        return record

    # ------------------------------------------------------------------
    # 공통 HTTP 요청
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,
            )
        ),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get(self, url: str, params: dict | None = None, **kwargs) -> requests.Response:
        self.total_requests += 1
        try:
            resp = self.session.get(url, params=params, timeout=30, **kwargs)
            if resp.status_code >= 500:
                resp.raise_for_status()
            resp.raise_for_status()
            self.success_requests += 1
            return resp
        except Exception:
            raise

    # ------------------------------------------------------------------
    # 파이프라인 실행 진입점
    # ------------------------------------------------------------------

    def run(self, from_raw: bool = False) -> dict:
        """
        collect -> refine -> extract 를 순차 실행.
        from_raw=True 이면 API를 호출하지 않고 로컬 파일에서 로드한다.
        """
        start_ts = datetime.now()
        logger.info("=" * 60)
        mode_str = "REPROCESS" if from_raw else "COLLECT"
        logger.info(f"[{self.job_name}] [{mode_str}] 파이프라인 시작: {start_ts.isoformat()}")
        logger.info("=" * 60)

        try:
            if from_raw:
                if not self.load_raw():
                    raise RuntimeError("로컬 원본 데이터 로드 실패")
            else:
                self.collect()

            total_raw = sum(len(p) for p in self._raw_pages)
            logger.info(f"[{self.job_name}] 데이터 확보 완료 | 원본 {total_raw}건")

            self.refine()
            logger.info(f"[{self.job_name}] refine() 완료 | 정제 {len(self._refined_records)}건")

            output_path = self.extract()
            logger.info(f"[{self.job_name}] extract() 완료 | 파일: {output_path}")

            # S3 업로드 (현재는 비활성화)
            self._upload_to_s3(output_path)

            elapsed = (datetime.now() - start_ts).seconds
            
            stats = {
                "job_name": self.job_name,
                "record_count": len(self._refined_records),
                "expected_total": self.expected_total,
                "total_requests": self.total_requests,
                "success_requests": self.success_requests,
                "output_path": str(output_path),
                "elapsed_sec": elapsed,
                "status": "SUCCESS"
            }

            # 개별 작업 Slack 알림
            self.notifier.send_success(**stats)
            return stats

        except Exception as exc:
            elapsed = (datetime.now() - start_ts).seconds
            logger.exception(f"[{self.job_name}] 파이프라인 최종 실패: {exc}")
            
            stats = {
                "job_name": self.job_name,
                "error_msg": str(exc),
                "total_requests": self.total_requests,
                "success_requests": self.success_requests,
                "elapsed_sec": elapsed,
                "status": "FAILURE"
            }
            
            self.notifier.send_failure(**stats)
            raise

    # ------------------------------------------------------------------
    # 공통 유틸리티
    # ------------------------------------------------------------------

    def _save_csv(self, data: list[dict], filename: str) -> Path:
        """정제된 records를 CSV 파일로 저장 (탭 구분자 사용)."""
        import csv
        filepath = self.output_dir / filename
        
        if not data:
            logger.warning(f"[{self.job_name}] 저장할 데이터가 없습니다.")
            return filepath

        keys = data[0].keys()
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            # ‡ 를 구분자로 사용하여 데이터 내 특수문자 문제를 방지
            writer = csv.DictWriter(f, fieldnames=keys, delimiter="‡")
            writer.writeheader()
            writer.writerows(data)
            
        logger.info(f"[{self.job_name}] CSV 저장 완료: {filepath} ({len(data)}건)")
        return filepath

    def _upload_to_s3(self, file_path: Path) -> None:
        """S3 업로드 로직 (현재는 동작하지 않음)."""
        # TODO: AWS 설정 및 boto3 클라이언트 초기화 필요
        # s3_enabled = os.getenv("S3_UPLOAD_ENABLED", "FALSE").upper() == "TRUE"
        s3_enabled = False # 명시적으로 비활성화
        
        if s3_enabled:
            logger.info(f"[{self.job_name}] S3 업로드 시도: {file_path.name}")
            # upload_file_to_s3(file_path)
        else:
            logger.info(f"[{self.job_name}] S3 업로드가 비활성화되어 있습니다.")

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y%m%d")
