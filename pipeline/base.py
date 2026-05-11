"""
pipeline/base.py
================
모든 기관별 파이프라인 클래스가 상속받는 추상 Base 클래스.

흐름: collect() -> refine() -> extract() -> run()
"""
import json
import logging
import os
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
        self.max_pages: int | None = max_pages  # None이면 전체 수집 (운영), 정수면 최대 페이지 수 제한 (테스트)
        self.output_dir: Path = Path("output") / self.job_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.notifier = SlackNotifier()

        # 공통 HTTP 세션 (Keep-Alive, 타임아웃 기본값 설정)
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

        # 수집된 원본 데이터 버퍼
        self._raw_pages: list[list[dict]] = []
        # 정제된 데이터 버퍼
        self._refined_records: list[dict] = []

    # ------------------------------------------------------------------
    # 추상 메서드 (각 기관 클래스에서 반드시 구현)
    # ------------------------------------------------------------------

    @abstractmethod
    def collect(self) -> None:
        """
        [1단계] API를 호출해 원본 데이터를 self._raw_pages 에 누적한다.
        페이징이 있는 경우 전체 페이지를 순회한다.
        """
        ...

    @abstractmethod
    def refine(self) -> None:
        """
        [2단계] self._raw_pages 를 읽어 불필요한 필드 제거, 타입 변환,
        null 처리 등 정제 작업을 수행하고 self._refined_records 에 저장한다.
        """
        ...

    @abstractmethod
    def extract(self) -> Path:
        """
        [3단계] self._refined_records 를 최종 출력 파일(JSON)로 저장하고
        저장된 경로(Path)를 반환한다.
        """
        ...

    # ------------------------------------------------------------------
    # 공통 HTTP 요청 (재시도 로직 내장)
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
        """
        GET 요청 + 자동 재시도.
        5xx 오류는 HTTPError를 raise해 재시도 대상으로 포함시킨다.
        """
        resp = self.session.get(url, params=params, timeout=30, **kwargs)
        if resp.status_code >= 500:
            resp.raise_for_status()  # 5xx → HTTPError → 재시도
        resp.raise_for_status()  # 4xx는 즉시 실패
        return resp

    # ------------------------------------------------------------------
    # 파이프라인 실행 진입점
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        collect → refine → extract 를 순서대로 실행하고,
        결과를 Slack으로 알린다.
        """
        start_ts = datetime.now()
        logger.info("=" * 60)
        logger.info(f"[{self.job_name}] 파이프라인 시작: {start_ts.isoformat()}")
        logger.info("=" * 60)

        try:
            # 1단계: 수집
            logger.info(f"[{self.job_name}] STEP 1/3 → collect() 시작")
            self.collect()
            total_raw = sum(len(p) for p in self._raw_pages)
            logger.info(f"[{self.job_name}] STEP 1/3 → collect() 완료 | 원본 {total_raw}건")

            # 2단계: 정제
            logger.info(f"[{self.job_name}] STEP 2/3 → refine() 시작")
            self.refine()
            logger.info(
                f"[{self.job_name}] STEP 2/3 → refine() 완료 | 정제 {len(self._refined_records)}건"
            )

            # 3단계: 추출
            logger.info(f"[{self.job_name}] STEP 3/3 → extract() 시작")
            output_path = self.extract()
            logger.info(f"[{self.job_name}] STEP 3/3 → extract() 완료 | 파일: {output_path}")

            # Slack 성공 알림
            elapsed = (datetime.now() - start_ts).seconds
            self.notifier.send_success(
                job_name=self.job_name,
                record_count=len(self._refined_records),
                output_path=str(output_path),
                elapsed_sec=elapsed,
            )

        except Exception as exc:
            elapsed = (datetime.now() - start_ts).seconds
            logger.exception(f"[{self.job_name}] 파이프라인 최종 실패: {exc}")
            # Slack 실패 알림
            self.notifier.send_failure(
                job_name=self.job_name,
                error_msg=str(exc),
                elapsed_sec=elapsed,
            )
            raise  # 상위(Airflow 등)에서 실패 감지할 수 있도록 재raise

    # ------------------------------------------------------------------
    # 공통 유틸리티
    # ------------------------------------------------------------------

    def _save_json(self, data: list[dict], filename: str) -> Path:
        """정제된 records를 output_dir 에 JSON 파일로 저장한다."""
        filepath = self.output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[{self.job_name}] JSON 저장 완료: {filepath} ({len(data)}건)")
        return filepath

    def _today_str(self) -> str:
        return datetime.now().strftime("%Y%m%d")
