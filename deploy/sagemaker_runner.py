"""
deploy/sagemaker_runner.py
==========================
SageMaker Processing Job (Script Mode) 전용 실행 스크립트.

이 파일 하나만 S3에 올려두고, SageMaker Processing Job의
"S3 script location"에 지정하면 됩니다.

실행 흐름:
  1. GitHub에서 최신 코드 클론 (항상 최신 코드 보장)
  2. pip install (requirements.txt 기반)
  3. main.py --schedule 실행 (오늘 날짜 기준 Job 자동 결정)
  4. 수집 결과물을 /opt/ml/processing/output/ 으로 이동
     → SageMaker가 Job 종료 후 자동으로 S3에 업로드

SageMaker Job 환경변수 설정 (콘솔 UI에서 입력):
  - FOODSAFETYKOREA_API_KEY
  - DATAPORTAL_ENCODING_API_KEY
  - DATAPORTAL_DECODING_API_KEY
  - WORK24_API_KEY
  - SLACK_WEBHOOK_URL

SageMaker Output 설정 (콘솔 UI에서 입력):
  - Local path  : /opt/ml/processing/output
  - S3 location : s3://[버킷명]/[원하는 경로]/

S3 최종 저장 구조:
  s3://[버킷]/[경로]/output/YYYY/MM/[파일명].csv
  s3://[버킷]/[경로]/raw/YYYY/MM/[job명]_YYYYMMDD/[페이지].json
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------

REPO_URL = "https://github.com/alkaline2018/government-certified-data-pipeline.git"
REPO_DIR = Path("/tmp/govt-pipeline")                 # 코드를 클론할 임시 디렉토리
SM_OUTPUT = Path("/opt/ml/processing/output")          # SageMaker 표준 출력 경로

# SageMaker Job 환경변수에서 읽어올 키 목록
ENV_KEYS = [
    "FOODSAFETYKOREA_API_KEY",
    "DATAPORTAL_ENCODING_API_KEY",
    "DATAPORTAL_DECODING_API_KEY",
    "WORK24_API_KEY",
    "SLACK_WEBHOOK_URL",
]


# ------------------------------------------------------------------
# 유틸리티
# ------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def run(cmd: list[str], cwd: Path | None = None) -> None:
    """명령어를 실행하고 실패 시 즉시 예외를 발생시킵니다."""
    logging.info(f"$ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


# ------------------------------------------------------------------
# 단계별 함수
# ------------------------------------------------------------------

def step1_clone() -> None:
    """1단계: GitHub에서 최신 코드를 클론합니다."""
    logging.info("=" * 60)
    logging.info("1단계: GitHub 코드 클론")
    logging.info("=" * 60)

    # SageMaker 컨테이너에 git이 없는 경우 설치
    import shutil as _shutil
    if not _shutil.which("git"):
        logging.info("git이 없습니다. apt-get으로 설치합니다...")
        run(["apt-get", "update", "-qq"])
        run(["apt-get", "install", "-y", "-qq", "git"])
        logging.info("git 설치 완료")

    # 이전 실행 잔여물 정리
    if REPO_DIR.exists():
        shutil.rmtree(REPO_DIR)

    run(["git", "clone", REPO_URL, str(REPO_DIR)])
    logging.info(f"클론 완료: {REPO_DIR}")


def step2_install() -> None:
    """2단계: 필요한 패키지를 설치합니다."""
    logging.info("=" * 60)
    logging.info("2단계: 패키지 설치 (pip install)")
    logging.info("=" * 60)

    run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-r", "requirements.txt"],
        cwd=REPO_DIR,
    )
    logging.info("패키지 설치 완료")


def step3_run_pipeline() -> None:
    """3단계: 데이터 수집 파이프라인을 실행합니다.

    - main.py는 load_dotenv()로 .env를 읽으려 하지만,
      .env 파일이 없어도 os.environ에 이미 환경변수가 설정되어 있으면 정상 동작합니다.
    - SageMaker Job의 '환경변수' 설정값이 os.environ에 자동으로 주입됩니다.
    """
    logging.info("=" * 60)
    logging.info("3단계: 데이터 수집 파이프라인 실행")
    logging.info("=" * 60)

    # 환경변수 확인 (누락된 키가 있으면 경고)
    for key in ENV_KEYS:
        val = os.environ.get(key, "")
        if not val:
            logging.warning(f"환경변수가 설정되지 않았습니다: {key}")
        else:
            logging.info(f"환경변수 확인: {key} = {'*' * 8} (설정됨)")

    run(
        [sys.executable, "main.py", "--schedule"],
        cwd=REPO_DIR,
    )
    logging.info("파이프라인 실행 완료")


def step4_export_output() -> None:
    """4단계: 수집 결과물을 SageMaker 출력 경로로 복사합니다.

    storage/output/ → /opt/ml/processing/output/output/
    storage/raw/    → /opt/ml/processing/output/raw/

    SageMaker가 Job 종료 후 /opt/ml/processing/output/ 전체를
    ProcessingOutputConfig에 지정된 S3 경로로 자동 업로드합니다.
    """
    logging.info("=" * 60)
    logging.info("4단계: 결과물 → /opt/ml/processing/output/ 복사")
    logging.info("=" * 60)

    storage_dir = REPO_DIR / "storage"

    if not storage_dir.exists():
        logging.error(f"storage 디렉토리가 존재하지 않습니다: {storage_dir}")
        raise FileNotFoundError(f"수집 결과물 없음: {storage_dir}")

    # output/, raw/ 각각 복사 (storage/ 경로명은 제외)
    for sub in ["output", "raw"]:
        src = storage_dir / sub
        dst = SM_OUTPUT / sub

        if not src.exists():
            logging.warning(f"폴더가 없습니다 (스킵): {src}")
            continue

        if dst.exists():
            shutil.rmtree(dst)

        shutil.copytree(src, dst)

        # 복사된 파일 수 확인
        file_count = sum(1 for _ in dst.rglob("*") if _.is_file())
        logging.info(f"복사 완료: {src} → {dst} ({file_count}개 파일)")


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------

def main() -> None:
    setup_logging()
    logging.info("=" * 60)
    logging.info("SageMaker Processing Job 시작")
    logging.info("=" * 60)

    try:
        step1_clone()
        step2_install()
        step3_run_pipeline()
        step4_export_output()

        logging.info("=" * 60)
        logging.info("모든 작업 완료")
        logging.info("SageMaker가 /opt/ml/processing/output/ → S3로 자동 업로드합니다.")
        logging.info("=" * 60)
        sys.exit(0)

    except Exception as exc:
        logging.exception(f"작업 실패: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
