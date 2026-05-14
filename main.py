"""
main.py
=======
공공기관 데이터 수집 파이프라인 CLI 진입점.

사용법:
  # 도움말
  python main.py --help

  # 개별 Job 실행
  python main.py --job foodsafety_haccp --perpage 1000
  python main.py --job dataportal_all --perpage 1000
  python main.py --job work24_youth_friendly

  # 테스트 (5건만, 1페이지만)
  python main.py --job foodsafety_haccp --perpage 5 --maxpages 1

  # 스케줄 모드: 오늘 실행 대상 Job을 schedule_config.py 기준으로 자동 선택
  python main.py --schedule

  # 수집 주기 설정 확인
  python main.py --show-schedule

환경 변수:
  .env 파일에 API 키와 Slack Webhook URL을 설정하세요.

Airflow / Cron 연동 예시:
  # Crontab - 매일 새벽 2시 스케줄 자동 실행
  0 2 * * * cd /path/to/project && python main.py --schedule
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Union, Optional

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

    registry: Dict[str, Tuple] = {}

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
  python main.py --job foodsafety_haccp --perpage 1000
  python main.py --job dataportal_all --perpage 1000
  python main.py --schedule
  python main.py --show-schedule
        """,
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--job",
        choices=job_choices,
        metavar="JOB",
        help=f"실행할 수집 작업 ID. 선택지: {', '.join(job_choices)}",
    )
    mode_group.add_argument(
        "--schedule",
        action="store_true",
        help="schedule_config.py 기준으로 오늘 실행 대상 Job을 자동 선택하여 실행",
    )
    mode_group.add_argument(
        "--show-schedule",
        action="store_true",
        dest="show_schedule",
        help="현재 수집 주기 설정을 출력하고 종료",
    )
    parser.add_argument(
        "--perpage",
        type=int,
        default=None,
        help="페이지당 수집 건수. 미지정 시 schedule_config.py의 per_page 사용",
    )
    parser.add_argument(
        "--maxpages",
        type=int,
        default=None,
        metavar="N",
        help="테스트용: 최대 N페이지만 수집. 예) --maxpages 1 → 1페이지만",
    )
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="API를 호출하지 않고 로컬 storage/raw/ 에 저장된 원본 데이터를 사용하여 재추출",
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

def _run_single_job(
    job_id: str,
    pipeline_cls,
    kwargs: dict,
    per_page: int,
    max_pages: Optional[int],
    from_raw: bool = False,
) -> Optional[Dict]:
    """단일 파이프라인 인스턴스를 실행하고 stats dict를 반환한다."""
    try:
        pipeline = pipeline_cls(**kwargs, per_page=per_page, max_pages=max_pages)
        return pipeline.run(from_raw=from_raw)
    except Exception:
        return None


def run_job(
    job_id: str,
    per_page: int,
    registry: dict,
    max_pages: Optional[int] = None,
    from_raw: bool = False,
    send_summary: bool = False,
    batch_name: str = "전체 수집 작업",
) -> list[dict]:
    """
    지정된 job_id 파이프라인을 실행하고 결과 리스트를 반환한다.
    dataportal_all 같은 multi-job의 경우 요약 Slack도 전송한다.
    """
    from pipeline.dataportal import DataPortalPipeline, DATAPORTAL_ENDPOINTS
    from pipeline.notifier import SlackNotifier
    from pipeline.schedule_config import SCHEDULE_CONFIG
    from datetime import datetime

    spec = registry[job_id]
    pipeline_cls, kwargs = spec
    results: List[Dict] = []
    start_time = datetime.now()
    logger = logging.getLogger(__name__)

    # dataportal_all — 7개 엔드포인트 순차 실행 + 요약
    if pipeline_cls == "__special__" and kwargs.get("type") == "dataportal_all":
        logger.info(f"dataportal_all: {len(DATAPORTAL_ENDPOINTS)}개 엔드포인트 순차 실행")
        for ep_key in DATAPORTAL_ENDPOINTS:
            ep_per_page = per_page or SCHEDULE_CONFIG.get(f"dataportal_{ep_key}", {}).get("per_page", 1000)
            try:
                pipeline = DataPortalPipeline(endpoint_key=ep_key, per_page=ep_per_page, max_pages=max_pages)
                res = pipeline.run(from_raw=from_raw)
                results.append(res)
            except Exception as exc:
                logger.error(f"dataportal_{ep_key} 실패: {exc}")

        total_elapsed = int((datetime.now() - start_time).total_seconds())
        SlackNotifier().send_summary(results, total_elapsed, batch_name="공공데이터포털 전체 수집")
        return results

    # 일반 단일 Job
    job_per_page = per_page or SCHEDULE_CONFIG.get(job_id, {}).get("per_page", 1000)
    res = _run_single_job(job_id, pipeline_cls, kwargs, job_per_page, max_pages, from_raw=from_raw)
    if res:
        results.append(res)

    # 외부에서 send_summary=True를 요청한 경우 (배치 스케줄 실행)
    if send_summary:
        total_elapsed = int((datetime.now() - start_time).total_seconds())
        SlackNotifier().send_summary(results, total_elapsed, batch_name=batch_name)

    return results


def run_schedule(per_page: Optional[int], max_pages: Optional[int], registry: dict, from_raw: bool = False) -> None:
    """schedule_config.py 기준으로 오늘 실행 대상 Job을 모두 실행한다."""
    from pipeline.schedule_config import get_jobs_due_today, SCHEDULE_CONFIG
    from pipeline.notifier import SlackNotifier
    from datetime import datetime

    logger = logging.getLogger(__name__)
    today_jobs = get_jobs_due_today()

    if not today_jobs:
        logger.info("오늘 실행 대상 Job이 없습니다.")
        return

    logger.info(f"오늘 실행 대상 {len(today_jobs)}개 Job: {today_jobs}")
    all_results: List[Dict] = []
    start_time = datetime.now()

    for job_id in today_jobs:
        cfg = SCHEDULE_CONFIG.get(job_id, {})
        job_per_page = per_page or cfg.get("per_page", 1000)
        logger.info(f"[스케줄] {job_id} 실행 (per_page={job_per_page})")
        results = run_job(job_id, job_per_page, registry, max_pages=max_pages, from_raw=from_raw)
        all_results.extend(results)

    total_elapsed = int((datetime.now() - start_time).total_seconds())
    SlackNotifier().send_summary(all_results, total_elapsed, batch_name="일일 스케줄 수집")


def main() -> None:
    registry = build_job_registry()
    parser = build_parser(registry)
    args = parser.parse_args()

    setup_logging(args.loglevel)
    logger = logging.getLogger(__name__)

    # ── 수집 주기 확인 모드
    if args.show_schedule:
        from pipeline.schedule_config import print_schedule_table, get_jobs_due_today
        from datetime import date
        print_schedule_table()
        due = get_jobs_due_today()
        print(f"\n오늘({date.today()}) 실행 대상: {due if due else '없음'}")
        sys.exit(0)

    # ── 스케줄 자동 실행 모드
    if args.schedule:
        logger.info("스케줄 모드 실행")
        try:
            run_schedule(args.perpage, args.maxpages, registry, from_raw=args.from_raw)
            sys.exit(0)
        except Exception as exc:
            logger.error(f"스케줄 실행 실패: {exc}")
            sys.exit(1)

    # ── 개별 Job 실행 모드
    if not args.job:
        parser.error("--job, --schedule, --show-schedule 중 하나를 지정해야 합니다.")

    logger.info(f"실행 요청: job={args.job}, perpage={args.perpage}")
    try:
        run_job(args.job, args.perpage, registry, max_pages=args.maxpages, from_raw=args.from_raw)
        logger.info(f"[{args.job}] 완료")
        sys.exit(0)
    except Exception as exc:
        logger.error(f"[{args.job}] 최종 실패: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
