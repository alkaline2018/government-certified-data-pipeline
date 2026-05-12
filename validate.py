import csv
import glob
import sys
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv(Path(__file__).parent / ".env")

from pipeline.notifier import SlackNotifier

# 콘솔 출력을 UTF-8로 강제
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

def load_catalog():
    """Single Point of Truth인 dataset_catalog.yaml을 로드한다."""
    catalog_path = Path(__file__).parent / "dataset_catalog.yaml"
    with open(catalog_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["datasets"]

def validate():
    datasets_spec = load_catalog()
    
    print(f"{'데이터셋명':<38} {'실제':>8} {'기대':>8} {'달성률':>8}  상태")
    print("-" * 100)

    total_actual = 0
    total_expected = 0
    results = []
    
    # storage/output/ 폴더 내의 CSV 파일 탐색
    csv_files = sorted(glob.glob("storage/output/*.csv"))
    
    if not csv_files:
        print("검증할 CSV 파일이 storage/output/ 폴더에 없습니다.")
        return

    # 카탈로그에 정의된 각 데이터셋별로 파일 매칭 및 검증
    for spec in datasets_spec:
        name = spec["name"]
        prefix = spec["file_prefix"]
        expected = spec["expected_count"]
        required_cols = spec["columns"]
        tolerance = spec.get("tolerance_pct", 99)
        
        # 파일 찾기
        matched_file = None
        for f in csv_files:
            if Path(f).name.startswith(prefix):
                matched_file = f
                break
        
        if not matched_file:
            print(f"{name:<38} {'-':>8} {expected:>8,} {'0.0%':>8}  [MISSING] 파일없음")
            results.append({
                "name": name,
                "actual": 0,
                "expected": expected,
                "ratio": 0,
                "status": "MISSING",
                "col_error": "파일 없음"
            })
            total_expected += (expected or 0)
            continue

        # 파일 검증
        actual_rows = 0
        missing_cols = []
        extra_cols = []
        
        try:
            with open(matched_file, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f, delimiter='‡')
                actual_cols = reader.fieldnames
                
                # B안: 필수 컬럼 존재 여부 체크 (Required-only)
                for rc in required_cols:
                    if rc not in actual_cols:
                        missing_cols.append(rc)
                
                # 예상 외 추가 컬럼 (참고용)
                for ac in actual_cols:
                    if ac not in required_cols:
                        extra_cols.append(ac)
                
                for row in reader:
                    actual_rows += 1
        except Exception as e:
            print(f"파일 읽기 오류 ({name}): {e}")
            continue

        total_actual += actual_rows
        total_expected += (expected or 0)
        
        ratio = (actual_rows / expected * 100) if expected else 100
        
        # 상태 판정
        col_ok = len(missing_cols) == 0
        count_ok = ratio >= tolerance
        
        if col_ok and count_ok:
            status = "[OK] 완벽" if ratio >= 99.9 else "[OK] 양호"
        else:
            status = "[FAIL] 오류"
            if not col_ok:
                status += "(컬럼누락)"
            if not count_ok:
                status += "(건수부족)"

        print(f"{name:<38} {actual_rows:>8,} {expected:>8,} {ratio:>7.1f}%  {status}")
        
        results.append({
            "name": name,
            "actual": actual_rows,
            "expected": expected,
            "ratio": ratio,
            "status": status,
            "missing_cols": missing_cols,
            "extra_cols": extra_cols
        })

    print("-" * 100)
    print(f"{'합  계':<38} {total_actual:>8,} {total_expected:>8,}")
    print()

    # 상세 오류 출력
    has_critical_issue = False
    for res in results:
        if res.get("missing_cols"):
            has_critical_issue = True
            print(f"🚨 [{res['name']}] 필수 컬럼 누락: {', '.join(res['missing_cols'])}")
        if res.get("extra_cols"):
            # 추가 컬럼은 경고성으로만 출력 (B안)
            print(f"ℹ️ [{res['name']}] 정의 외 추가 컬럼: {', '.join(res['extra_cols'])}")

    # Slack 알림 전송
    if results:
        print("\nSlack으로 SPOT 기반 검증 리포트를 전송합니다...")
        SlackNotifier().send_validation_result(results, total_actual, total_expected)

    if not has_critical_issue:
        print("\n[성공] SPOT(YAML) 기준에 따른 데이터 구조 및 품질 검증이 완료되었습니다.")
    else:
        print("\n[경고] 일부 데이터셋의 구조(컬럼)가 기준서와 일치하지 않습니다. 확인이 필요합니다.")

if __name__ == "__main__":
    validate()
