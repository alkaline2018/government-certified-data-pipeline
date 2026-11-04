"""
pipeline/small_giants_fallback.py
=================================
강소기업 명단 수집 실패 시 S3의 이전 달 파일로 이번 달 파일을 채우는 대체 로직.

클라우드(Glue/SageMaker)에서는 고용24 다운로드가 실패해 이번 달 CSV가 생성되지 않을 수 있다.
그 경우 S3에 업로드된 이전 달 파일 중 가장 최근 것을 storage/output/YYYY/MM/ 으로 내려받는다.
실행 래퍼가 storage/ 를 그대로 S3 di/nice_scb/ 에 올리므로 이번 달 경로로 업로드된다.
S3 경로는 업로드 규칙(prefix/output/YYYY/MM/파일명)으로 추정한다.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

S3_BUCKET = "zinidata-prod-apne2-datalake"
S3_PREFIX = "di/nice_scb"
# 2026-05-27 이전 업로드분은 구 프리픽스에 있음
SEARCH_PREFIXES = [S3_PREFIX, "di/government-certified-data-pipeline"]

DATASET_NAME = "Work24_강소기업_명단"
FILENAME = f"{DATASET_NAME}.csv"
LOOKBACK_MONTHS = 12


def _previous_months(base: datetime, count: int) -> List[Tuple[str, str]]:
    """base 월의 직전 달부터 count개월 전까지 (YYYY, MM) 목록을 최신순으로 반환."""
    months = []
    year, month = base.year, base.month
    for _ in range(count):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        months.append((f"{year:04d}", f"{month:02d}"))
    return months


def _s3_key_exists(s3_client, bucket: str, key: str) -> bool:
    from botocore.exceptions import ClientError
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        # ListBucket 권한이 없으면 없는 객체도 403으로 응답하므로 함께 '없음'으로 처리
        return False


def _find_key(s3_client, bucket: str, year: str, month: str) -> Optional[str]:
    """해당 연/월에 업로드된 강소기업 명단 CSV의 S3 키를 찾는다."""
    from botocore.exceptions import ClientError
    for prefix in SEARCH_PREFIXES:
        # 1) 현재 파일명 규칙으로 직접 확인
        key = f"{prefix}/output/{year}/{month}/{FILENAME}"
        if _s3_key_exists(s3_client, bucket, key):
            return key

        # 2) 날짜가 붙은 파일명(Work24_강소기업_명단_YYYYMMDD.csv) 등은 목록 조회로 확인
        try:
            resp = s3_client.list_objects_v2(
                Bucket=bucket, Prefix=f"{prefix}/output/{year}/{month}/{DATASET_NAME}"
            )
        except ClientError as e:
            logger.warning(f"[{DATASET_NAME}] 목록 조회 불가 ({prefix}/output/{year}/{month}): {e}")
            continue
        csv_objs = [o for o in resp.get("Contents", []) if o["Key"].endswith(".csv") and o["Size"] > 0]
        if csv_objs:
            return max(csv_objs, key=lambda o: o["LastModified"])["Key"]
    return None


def ensure_small_giants(
    storage_dir: Path = Path("storage"),
    bucket: str = S3_BUCKET,
    s3_client=None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """
    이번 달 강소기업 명단 CSV가 없으면 S3 이전 달 파일로 채운다.

    Returns:
        복사해 온 원본 S3 키. 복사하지 않았으면 None.
    """
    now = now or datetime.now()
    year, month = f"{now.year:04d}", f"{now.month:02d}"
    local_path = Path(storage_dir) / "output" / year / month / FILENAME

    if local_path.exists() and local_path.stat().st_size > 0:
        logger.info(f"[{DATASET_NAME}] 이번 달 수집 성공, 대체 불필요: {local_path}")
        return None

    if s3_client is None:
        try:
            import boto3
        except ImportError:
            logger.warning(f"[{DATASET_NAME}] boto3 미설치로 S3 대체 로직을 건너뜁니다.")
            return None
        s3_client = boto3.client("s3")

    from botocore.exceptions import ClientError

    dst_key = f"{S3_PREFIX}/output/{year}/{month}/{FILENAME}"
    if _s3_key_exists(s3_client, bucket, dst_key):
        logger.info(f"[{DATASET_NAME}] 이번 달 파일이 이미 S3에 있음, 대체 불필요: {dst_key}")
        return None

    logger.info(f"[{DATASET_NAME}] 이번 달 수집 실패 → S3 이전 파일 탐색")
    for prev_year, prev_month in _previous_months(now, LOOKBACK_MONTHS):
        src_key = _find_key(s3_client, bucket, prev_year, prev_month)
        if src_key is None:
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            s3_client.download_file(bucket, src_key, str(local_path))
        except ClientError as e:
            logger.error(f"[{DATASET_NAME}] 기준 파일 다운로드 실패: {src_key} | {e}")
            return None
        logger.info(f"[{DATASET_NAME}] 전월 파일 복사: s3://{bucket}/{src_key} → {local_path}")
        return src_key

    logger.error(f"[{DATASET_NAME}] 최근 {LOOKBACK_MONTHS}개월 내 파일을 S3에서 찾지 못했습니다.")
    return None
