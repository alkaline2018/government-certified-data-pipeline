import os
import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def run_command(command):
    logger.info(f"실행 중: {command}")
    try:
        subprocess.run(command, shell=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"명령어 실패: {command} (에러: {e})")
        return False

def main():
    logger.info("=== [전체 데이터 수집 프로세스 시작] ===")

    # 1. 수집 작업 목록
    jobs = [
        "python main.py --job foodsafety_haccp",
        "python main.py --job foodsafety_restaurant",
        "python main.py --job dataportal_all",
        "python main.py --job work24_youth_friendly",
        "python main.py --job work24_small_giants"
    ]

    for job in jobs:
        run_command(job)

    # 1-1. 강소기업 명단 수집 실패 시 S3 이전 달 파일로 대체
    try:
        from pipeline.small_giants_fallback import DATASET_NAME, ensure_small_giants
        src_key = ensure_small_giants()
        if src_key:
            # validate.py(하위 프로세스)의 Slack 리포트에 '전월 파일 복사' 표시용
            os.environ["FALLBACK_COPIED_DATASETS"] = f"{DATASET_NAME}={src_key}"
    except Exception as e:
        logger.error(f"강소기업 명단 대체 로직 오류 (무시하고 계속): {e}")

    # 2. 데이터 사양서 갱신
    logger.info("=== [데이터 사양서(DATA_SPEC.md) 갱신 중] ===")
    run_command("python generate_spec.py")

    # 3. 데이터 검증 및 Slack 알림
    logger.info("=== [데이터 검증 및 Slack 알림 전송 중] ===")
    run_command("python validate.py")

    logger.info("=== [모든 작업이 완료되었습니다!] ===")

if __name__ == "__main__":
    main()
