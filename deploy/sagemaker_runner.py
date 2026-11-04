import subprocess
import os
import sys
import boto3
import shutil
import urllib.request  # 추가
import zipfile         # unzip 명령어 대신 안전하게 사용
from datetime import datetime
from pathlib import Path
from typing import List, Union, Optional, Tuple  # Python 3.9 호환성을 위해 추가
from botocore.exceptions import ClientError

# ==========================================
# 1. 환경 설정 및 경로 정의
# ==========================================
S3_BUCKET = "zinidata-prod-apne2-datalake"
S3_PREFIX = "di/nice_scb"

# 모든 작업은 /tmp 내부에서 수행 (권한 보장)
BASE_DIR  = "/tmp/pipeline_job"
ZIP_PATH  = os.path.join(BASE_DIR, "repo.zip")
# GitHub ZIP 해제 시 생성되는 폴더명: {repo-name}-{branch}
REPO_DIR  = os.path.join(BASE_DIR, "government-certified-data-pipeline-main")
LOCAL_STORAGE = os.path.join(REPO_DIR, "storage")

# 깨끗한 환경을 위해 기존 폴더 삭제 후 생성
if os.path.exists(BASE_DIR):
    shutil.rmtree(BASE_DIR)
os.makedirs(BASE_DIR)

print(f">>> 작업 시작 디렉토리: {BASE_DIR}")

# ==========================================
# 2. 소스코드 및 라이브러리 준비
# ==========================================

# 1) urllib로 ZIP 다운로드 (git/wget/curl 모두 불필요)
ZIP_URL = "https://github.com/alkaline2018/government-certified-data-pipeline/archive/refs/heads/main.zip"
print(f">>> 코드 다운로드 중... ({ZIP_URL})")
urllib.request.urlretrieve(ZIP_URL, ZIP_PATH)

# 2) 파이썬 내장 zipfile 모듈로 압축 해제 (unzip 명령어 불필요)
print(f">>> 압축 해제 중...")
with zipfile.ZipFile(ZIP_PATH, 'r') as zip_ref:
    zip_ref.extractall(BASE_DIR)
print(f">>> 코드 준비 완료: {REPO_DIR}")

# 2) 라이브러리 설치
subprocess.run(
    f"{sys.executable} -m pip install -q -r {REPO_DIR}/requirements.txt",
    shell=True, check=True
)

# 3) .env 파일 생성
# SageMaker Job 환경변수(콘솔 UI에서 설정)를 읽어서 .env로 저장합니다.
# load_dotenv()는 이미 설정된 환경변수를 덮어쓰지 않으므로,
# 환경변수가 os.environ에 있으면 .env 파일이 없어도 동작하지만
# 명시적으로 파일을 만들어 두면 더 안전합니다.
ENV_KEYS = [
    "FOODSAFETYKOREA_API_KEY",
    "DATAPORTAL_ENCODING_API_KEY",
    "DATAPORTAL_DECODING_API_KEY",
    "WORK24_API_KEY",
    "SLACK_WEBHOOK_URL",
]

env_lines = []
for key in ENV_KEYS:
    val = os.environ.get(key, "")
    if not val:
        print(f"⚠️  환경변수 미설정: {key}")
    env_lines.append(f"{key}={val}")

with open(os.path.join(REPO_DIR, ".env"), "w") as f:
    f.write("\n".join(env_lines) + "\n")

print(">>> .env 파일 생성 완료")

# ==========================================
# 3. 파이프라인 실행 (cwd 설정이 핵심!)
# ==========================================
print(">>> 파이프라인 실행 중...")
subprocess.run(
    f"{sys.executable} run_all.py",
    shell=True, check=True, cwd=REPO_DIR
)

s3_client = boto3.client('s3')

# ==========================================
# 3-1. 강소기업 명단 대체 로직
# ==========================================
# SageMaker 환경에서는 고용24 다운로드가 실패해 이번 달 CSV가 생성되지 않을 수 있다.
# 그 경우 S3에 이전 달 업로드분 중 가장 최근 파일을 찾아 이번 달 경로로 가져온다.
# 경로는 업로드 규칙(prefix/output/YYYY/MM/파일명)으로 추정한다.
SMALL_GIANTS_FILENAME = "Work24_강소기업_명단.csv"
SMALL_GIANTS_LOOKBACK_MONTHS = 12
# 2026-05-27 이전 업로드분은 구 프리픽스에 있음
SMALL_GIANTS_SEARCH_PREFIXES = [S3_PREFIX, "di/government-certified-data-pipeline"]


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


def _s3_key_exists(bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        # ListBucket 권한이 없으면 없는 객체도 403으로 응답하므로 함께 '없음'으로 처리
        return False


def _find_small_giants_key(bucket: str, year: str, month: str) -> Optional[str]:
    """해당 연/월에 업로드된 강소기업 명단 CSV의 S3 키를 찾는다."""
    stem = SMALL_GIANTS_FILENAME[:-len(".csv")]
    for prefix in SMALL_GIANTS_SEARCH_PREFIXES:
        # 1) 현재 파일명 규칙으로 직접 확인
        key = f"{prefix}/output/{year}/{month}/{SMALL_GIANTS_FILENAME}"
        if _s3_key_exists(bucket, key):
            return key

        # 2) 날짜가 붙은 파일명(Work24_강소기업_명단_YYYYMMDD.csv) 등은 목록 조회로 확인
        try:
            resp = s3_client.list_objects_v2(
                Bucket=bucket, Prefix=f"{prefix}/output/{year}/{month}/{stem}"
            )
        except ClientError as e:
            print(f"⚠️  목록 조회 불가 ({prefix}/output/{year}/{month}): {e}")
            continue
        csv_objs = [o for o in resp.get("Contents", []) if o["Key"].endswith(".csv") and o["Size"] > 0]
        if csv_objs:
            return max(csv_objs, key=lambda o: o["LastModified"])["Key"]
    return None


def ensure_small_giants(bucket: str) -> None:
    now = datetime.now()
    year, month = f"{now.year:04d}", f"{now.month:02d}"
    local_path = Path(LOCAL_STORAGE) / "output" / year / month / SMALL_GIANTS_FILENAME

    if local_path.exists() and local_path.stat().st_size > 0:
        print(f">>> 강소기업 명단 이번 달 수집 성공, 대체 불필요: {local_path}")
        return

    dst_key = f"{S3_PREFIX}/output/{year}/{month}/{SMALL_GIANTS_FILENAME}"
    if _s3_key_exists(bucket, dst_key):
        print(f">>> 강소기업 명단 이번 달 파일이 이미 S3에 있음, 대체 불필요: {dst_key}")
        return

    print(">>> 강소기업 명단 이번 달 수집 실패 → S3 이전 파일 탐색")
    for prev_year, prev_month in _previous_months(now, SMALL_GIANTS_LOOKBACK_MONTHS):
        src_key = _find_small_giants_key(bucket, prev_year, prev_month)
        if src_key is None:
            continue
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            s3_client.download_file(bucket, src_key, str(local_path))
        except ClientError as e:
            print(f"❌ 강소기업 명단 기준 파일 다운로드 실패: {src_key} | {e}")
            return
        # 이후 업로드 단계에서 dst_key 로 올라감
        print(f"✅ 강소기업 명단 대체: s3://{bucket}/{src_key} → {dst_key}")
        return

    print(f"❌ 최근 {SMALL_GIANTS_LOOKBACK_MONTHS}개월 내 강소기업 명단 파일을 S3에서 찾지 못했습니다.")


try:
    ensure_small_giants(S3_BUCKET)
except Exception as e:
    # 대체 로직 실패가 전체 업로드를 막지 않도록 함
    print(f"❌ 강소기업 명단 대체 로직 오류: {e}")

# ==========================================
# 4. S3 업로드 로직
# ==========================================

def upload_to_s3(local_dir: Union[str, Path], bucket: str, prefix: str) -> bool:
    path_root = Path(local_dir)
    if not path_root.exists():
        print(f"❌ 데이터 폴더가 생성되지 않았습니다: {local_dir}")
        return False

    for file_path in path_root.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(path_root)
            s3_key = f"{prefix}/{str(relative_path)}".replace("\\", "/")
            try:
                s3_client.upload_file(str(file_path), bucket, s3_key)
                print(f"✅ Uploaded: {s3_key}")
            except Exception as e:
                print(f"❌ Failed: {s3_key} | {e}")
    return True

print(f">>> S3 업로드 시작... 대상: {LOCAL_STORAGE}")
if upload_to_s3(LOCAL_STORAGE, S3_BUCKET, S3_PREFIX):
    print("\n>>> 업로드 완료. 로컬 정리 중...")
    shutil.rmtree(BASE_DIR)

print("\n✨ Job Finished!")
