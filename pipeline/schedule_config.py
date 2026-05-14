"""
pipeline/schedule_config.py
============================
각 Job의 수집 주기(schedule)를 중앙에서 관리하는 설정 모듈.

수집 주기 변경 시 이 파일의 SCHEDULE_CONFIG 딕셔너리만 수정하면 됩니다.

schedule_type:
  - "yearly"  : 연 1회 (매년 1월 1일 기준)
  - "monthly" : 월 1회 (매월 1일 기준)
  - "weekly"  : 주 1회
  - "daily"   : 매일

run_month: yearly 스케줄에서 실행할 월 (1~12, 기본값 1)
run_day:   yearly/monthly 에서 실행할 일 (1~28, 기본값 1)
"""

from typing import Dict, List, Optional

SCHEDULE_CONFIG: Dict[str, Dict] = {
    # ────────────────────────────────────────────
    # 식품의약품안전처 — 연 1회 (매년 1월)
    # ────────────────────────────────────────────
    "foodsafety_haccp": {
        "schedule_type": "yearly",
        "run_month": 1,
        "run_day": 1,
        "description": "HACCP 적용업소 (연 1회)",
        "per_page": 1000,
    },
    "foodsafety_restaurant": {
        "schedule_type": "yearly",
        "run_month": 1,
        "run_day": 1,
        "description": "식품모범음식점 (연 1회)",
        "per_page": 1000,
    },

    # ────────────────────────────────────────────
    # 공공데이터포털 — 월 1회 (매월 1일)
    # ────────────────────────────────────────────
    "dataportal_tech_excellence": {
        "schedule_type": "monthly",
        "run_day": 1,
        "description": "기술개발 우수기업 (월 1회)",
        "per_page": 1000,
    },
    "dataportal_performance_cert": {
        "schedule_type": "monthly",
        "run_day": 1,
        "description": "성능인증 발급현황 (월 1회)",
        "per_page": 1000,
    },
    "dataportal_startup_cert": {
        "schedule_type": "monthly",
        "run_day": 1,
        "description": "창업기업확인서 정보 (월 1회)",
        "per_page": 1000,
    },
    "dataportal_century_store": {
        "schedule_type": "monthly",
        "run_day": 1,
        "description": "전국 백년가게 현황 (월 1회)",
        "per_page": 1000,
    },
    "dataportal_century_craftsman": {
        "schedule_type": "monthly",
        "run_day": 1,
        "description": "전국 백년소공인 지정 (월 1회)",
        "per_page": 1000,
    },
    "dataportal_talent_sme": {
        "schedule_type": "monthly",
        "run_day": 1,
        "description": "인재육성형 중소기업 (월 1회)",
        "per_page": 1000,
    },
    "dataportal_tech_product_cert": {
        "schedule_type": "monthly",
        "run_day": 1,
        "description": "기술개발제품 인증 (월 1회)",
        "per_page": 1000,
    },

    # ────────────────────────────────────────────
    # 고용24 — 월 1회 (매월 1일)
    # ────────────────────────────────────────────
    "work24_youth_friendly": {
        "schedule_type": "monthly",
        "run_day": 1,
        "description": "청년친화강소기업 (월 1회)",
        "per_page": 100,
    },
    "work24_small_giants": {
        "schedule_type": "yearly",
        "run_month": 1,
        "run_day": 1,
        "description": "고용노동부 강소기업 명단 (연 1회)",
        "per_page": 1,
    },
}


def get_jobs_due_today(today: Optional[object] = None) -> List[str]:
    """
    오늘 실행해야 할 Job ID 목록을 반환한다.

    Args:
        today: datetime.date 객체 (기본값: 오늘 날짜). 테스트 시 날짜 주입 가능.

    Returns:
        오늘 실행 대상인 job_id 리스트
    """
    from datetime import date

    if today is None:
        today = date.today()

    due_jobs = []
    for job_id, cfg in SCHEDULE_CONFIG.items():
        schedule_type = cfg.get("schedule_type", "monthly")

        if schedule_type == "daily":
            due_jobs.append(job_id)

        elif schedule_type == "weekly":
            # run_weekday: 0=월요일 ~ 6=일요일 (기본: 월요일)
            run_weekday = cfg.get("run_weekday", 0)
            if today.weekday() == run_weekday:
                due_jobs.append(job_id)

        elif schedule_type == "monthly":
            run_day = cfg.get("run_day", 1)
            if today.day == run_day:
                due_jobs.append(job_id)

        elif schedule_type == "yearly":
            run_month = cfg.get("run_month", 1)
            run_day = cfg.get("run_day", 1)
            if today.month == run_month and today.day == run_day:
                due_jobs.append(job_id)

    return due_jobs


def print_schedule_table() -> None:
    """현재 설정된 수집 주기를 콘솔에 출력한다."""
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 70)
    print(f"{'Job ID':<40} {'주기':<10} {'설명'}")
    print("=" * 70)
    for job_id, cfg in SCHEDULE_CONFIG.items():
        stype = cfg.get("schedule_type", "monthly")
        if stype == "yearly":
            schedule_str = f"연1회({cfg.get('run_month',1)}월{cfg.get('run_day',1)}일)"
        elif stype == "monthly":
            schedule_str = f"월1회({cfg.get('run_day',1)}일)"
        elif stype == "weekly":
            days = ["월","화","수","목","금","토","일"]
            schedule_str = f"주1회({days[cfg.get('run_weekday',0)]})"
        else:
            schedule_str = "매일"
        print(f"{job_id:<40} {schedule_str:<10} {cfg.get('description','')}")
    print("=" * 70)


if __name__ == "__main__":
    print_schedule_table()

    from datetime import date
    today = date.today()
    due = get_jobs_due_today(today)
    print(f"\n오늘({today}) 실행 대상: {due if due else '없음'}")
