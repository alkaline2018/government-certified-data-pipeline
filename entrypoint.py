"""
entrypoint.py
=============
SageMaker Notebook / Docker 컨테이너 전용 진입점.

main.py와 동일한 로직이지만 컨테이너 환경에 맞게 조정:
  - stdout 전용 로깅 (파일 핸들러 없음 → CloudWatch/Notebook 로그 친화적)
  - .env 파일 없이 환경변수만으로 동작
  - 기본 모드: --schedule (오늘 날짜 기준 자동 실행)

사용법 (SageMaker Notebook):
  docker run --env-file .env \\
    -v /home/ec2-user/SageMaker/storage:/app/storage \\
    alkaline2018/govt-data-pipeline:latest

  # 개별 job 실행
  docker run --env-file .env \\
    -v /home/ec2-user/SageMaker/storage:/app/storage \\
    alkaline2018/govt-data-pipeline:latest \\
    --job foodsafety_haccp

  # 테스트 (1페이지만)
  docker run --env-file .env \\
    -v /home/ec2-user/SageMaker/storage:/app/storage \\
    alkaline2018/govt-data-pipeline:latest \\
    --job foodsafety_haccp --maxpages 1
"""
import argparse
import logging
import sys
from pathlib import Path


# ------------------------------------------------------------------
# 로깅 설정 — stdout 전용 (파일 핸들러 없음)
# ------------------------------------------------------------------

def setup_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
        force=True,  # 기존 핸들러 초기화 후 재설정
    )


# ------------------------------------------------------------------
# CLI 파서
# ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="entrypoint.py",
        description="공공기관 데이터 수집 파이프라인 (컨테이너 진입점)",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--job",
        metavar="JOB_ID",
        help="실행할 특정 Job ID (예: foodsafety_haccp, dataportal_all)",
    )
    mode_group.add_argument(
        "--schedule",
        action="store_true",
        default=True,
        help="오늘 날짜 기준으로 실행 대상 Job 자동 선택 (기본값)",
    )
    parser.add_argument(
        "--maxpages",
        type=int,
        default=None,
        metavar="N",
        help="테스트용: 최대 N페이지만 수집",
    )
    parser.add_argument(
        "--loglevel",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨 (기본값: INFO)",
    )
    return parser


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(args.loglevel)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("공공기관 데이터 수집 파이프라인 시작 (컨테이너 모드)")
    logger.info("=" * 60)

    # main.py의 job registry / run 함수 재사용
    from main import build_job_registry, run_job, run_schedule

    registry = build_job_registry()

    try:
        if args.job:
            # --job 지정 시 단일 Job 실행
            if args.job not in registry:
                logger.error(f"알 수 없는 Job ID: {args.job}")
                logger.info(f"사용 가능한 Job: {sorted(registry.keys())}")
                sys.exit(1)

            logger.info(f"[개별 실행] job={args.job}, maxpages={args.maxpages}")
            run_job(
                job_id=args.job,
                per_page=None,       # schedule_config.py의 per_page 사용
                registry=registry,
                max_pages=args.maxpages,
            )
        else:
            # 기본: 스케줄 모드
            logger.info("[스케줄 모드] 오늘 실행 대상 Job 자동 선택")
            run_schedule(
                per_page=None,
                max_pages=args.maxpages,
                registry=registry,
            )

        logger.info("=" * 60)
        logger.info("파이프라인 정상 완료")
        logger.info("=" * 60)
        sys.exit(0)

    except Exception as exc:
        logger.exception(f"파이프라인 실패: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
