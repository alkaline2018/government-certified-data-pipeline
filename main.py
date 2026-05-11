"""
main.py
=======
공공기관 데이터 수집 파이프라인 CLI 진입점.

사용법:
  # 도움말
  python main.py --help

  # 식약처 HACCP - 테스트 (1건만 수집)
  python main.py --job foodsafety_haccp --perpage 1

  # 식약처 모범음식점 - 운영
  python main.py --job foodsafety_restaurant --perpage 1000

  # 공공데이터포털 - 기술개발 우수기업 테스트
  python main.py --job dataportal_tech_excellence --perpage 1

  # 공공데이터포털 - 전체 7개 엔드포인트 한 번에 실행
  python main.py --job dataportal_all --perpage 1000

  # 고용24 - 청년친화강소기업
  python main.py --job work24_youth_friendly --perpage 1

  # 로그 레벨 조정 (기본: INFO)
  python main.py --job work24_youth_friendly --perpage 1 --loglevel DEBUG

환경 변수:
  .env 파일에 API 키와 Slack Webhook URL을 설정하세요. (.env.example 참조)

Airflow / Cron 연동 예시:
  # Crontab (매월 1일 새벽 2시에 식약처 전체 수집)
  0 2 1 * * cd /path/to/project && python main.py --job foodsafety_haccp --perpage 1000

  # Airflow PythonOperator
  from pipeline.foodsafety import FoodSafetyPipeline
  def run_haccp(**ctx):
      FoodSafetyPipeline(service_key="haccp", per_page=1000).run()
"""
import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# .env 파일 로드 (스크립트 위치 기준)
load_dotenv(Path(__file__).parent / ".env")

# ------------------------------------------------------------------
# 로깅 설정
# ------------------------------------------------------------------

def setup_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("pipeline.log", encoding="utf-8"),
        ],
    )


# ------------------------------------------------------------------
# 잡(Job) 레지스트리
# job_id → (PipelineClass, kwargs)
# ------------------------------------------------------------------

def build_job_registry() -> dict:
    """
    사용 가능한 모든 Job을 등록하는 함수.
    파이프라인을 추가할 때 이 함수에만 등록하면 된다.
    """
    from pipeline.foodsafety import FoodSafetyPipeline, FOODSAFETY_SERVICES
    from pipeline.dataportal import DataPortalPipeline, DATAPORTAL_ENDPOINTS
    from pipeline.work24 import Work24Pipeline, WORK24_ENDPOINTS

    registry: dict[str, tuple] = {}

    # --- 식약처 ---
    for svc_key in FOODSAFETY_SERVICES:
        job_id = f"foodsafety_{svc_key}"
        registry[job_id] = (FoodSafetyPipeline, {"service_key": svc_key})

    # --- 공공데이터포털 (개별) ---
    for ep_key in DATAPORTAL_ENDPOINTS:
        job_id = f"dataportal_{ep_key}"
        registry[job_id] = (DataPortalPipeline, {"endpoint_key": ep_key})

    # --- 공공데이터포털 (전체 일괄) ---
    registry["dataportal_all"] = ("__special__", {"type": "dataportal_all"})

    # --- 고용24 ---
    for ep_key in WORK24_ENDPOINTS:
        job_id = f"work24_{ep_key}"
        registry[job_id] = (Work24Pipeline, {"endpoint_key": ep_key})

    return registry


# ------------------------------------------------------------------
# CLI 파서
# ------------------------------------------------------------------

def build_parser(registry: dict) -> argparse.ArgumentParser:
    job_choices = sorted(registry.keys())
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="공공기관 데이터 수집 파이프라인 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
사용 가능한 Job 목록:
{chr(10).join(f'  {j}' for j in job_choices)}

예시:
  python main.py --job foodsafety_haccp --perpage 1
  python main.py --job dataportal_all --perpage 1000
  python main.py --job work24_youth_friendly --perpage 1
        """,
    )
    parser.add_argument(
        "--job",
        required=True,
        choices=job_choices,
        metavar="JOB",
        help=f"실행할 수집 작업 ID. 선택지: {', '.join(job_choices)}",
    )
    parser.add_argument(
        "--perpage",
        type=int,
        default=1000,
        help="페이지당 수집 건수 (테스트: 1, 운영: 1000). 기본값: 1000",
    )
    parser.add_argument(
        "--maxpages",
        type=int,
        default=None,
        metavar="N",
        help="테스트용: 최대 N페이지만 수집. 미지정시 전체 수집 (운영). 예) --maxpages 1 → 1페이지만",
    )
    parser.add_argument(
        "--loglevel",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨 (기본값: INFO)",
    )
    return parser


# ------------------------------------------------------------------
# 실행
# ------------------------------------------------------------------

def run_job(job_id: str, per_page: int, registry: dict, max_pages: int | None = None) -> None:
    """지정된 job_id에 해당하는 파이프라인을 실행한다."""
    from pipeline.dataportal import DataPortalPipeline, DATAPORTAL_ENDPOINTS

    spec = registry[job_id]
    pipeline_cls, kwargs = spec

    # 특수 케이스: dataportal_all (전체 엔드포인트 순차 실행)
    if pipeline_cls == "__special__" and kwargs.get("type") == "dataportal_all":
        logging.getLogger(__name__).info(
            f"dataportal_all: {len(DATAPORTAL_ENDPOINTS)}개 엔드포인트 순차 실행"
        )
        for ep_key in DATAPORTAL_ENDPOINTS:
            pipeline = DataPortalPipeline(endpoint_key=ep_key, per_page=per_page, max_pages=max_pages)
            pipeline.run()
        return

    # 일반 케이스
    pipeline = pipeline_cls(**kwargs, per_page=per_page, max_pages=max_pages)
    pipeline.run()


def main() -> None:
    registry = build_job_registry()
    parser = build_parser(registry)
    args = parser.parse_args()

    setup_logging(args.loglevel)
    logger = logging.getLogger(__name__)

    logger.info(f"실행 요청: job={args.job}, perpage={args.perpage}")

    try:
        run_job(args.job, args.perpage, registry, max_pages=args.maxpages)
        logger.info(f"[{args.job}] 완료")
        sys.exit(0)
    except Exception as exc:
        logger.error(f"[{args.job}] 최종 실패: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
