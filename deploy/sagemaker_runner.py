import subprocess
import os
import sys
import boto3
import shutil
from pathlib import Path

# ==========================================
# 1. 환경 설정 및 경로 정의
# ==========================================
S3_BUCKET = "zinidata-prod-apne2-datalake"
S3_PREFIX = "di/government-certified-data-pipeline"

# 모든 작업은 /tmp 내부에서 수행 (권한 보장)
BASE_DIR  = "/tmp/pipeline_job"
REPO_DIR  = os.path.join(BASE_DIR, "government-certified-data-pipeline")
LOCAL_STORAGE = os.path.join(REPO_DIR, "storage")

# 깨끗한 환경을 위해 기존 폴더 삭제 후 생성
if os.path.exists(BASE_DIR):
    shutil.rmtree(BASE_DIR)
os.makedirs(BASE_DIR)

print(f">>> 작업 시작 디렉토리: {BASE_DIR}")

# ==========================================
# 2. 소스코드 및 라이브러리 준비
# ==========================================

# 1) Git Clone
subprocess.run(
    f"git clone https://github.com/alkaline2018/government-certified-data-pipeline.git {REPO_DIR}",
    shell=True, check=True
)

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

# ==========================================
# 4. S3 업로드 로직
# ==========================================
s3_client = boto3.client('s3')

def upload_to_s3(local_dir, bucket, prefix):
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
