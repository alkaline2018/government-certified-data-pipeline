"""
pipeline/notifier.py
====================
Slack Webhook을 통한 성공/실패/요약 알림 전송 모듈.
Block Kit 기반의 구조화된 메시지로 가독성을 높였습니다.
"""
import logging
import os
import time
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


def _now_kst() -> str:
    """현재 시각을 KST 문자열로 반환."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SlackNotifier:
    """
    Slack Incoming Webhook으로 파이프라인 상태를 알립니다.
    SLACK_WEBHOOK_URL 환경변수가 없으면 알림을 건너뜁니다.
    """

    def __init__(self):
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
        if not self.webhook_url:
            logger.warning("SLACK_WEBHOOK_URL 환경변수가 설정되지 않아 Slack 알림이 비활성화됩니다.")

    def _send(self, payload: dict) -> None:
        """Slack Webhook에 POST 요청을 전송한다."""
        if not self.webhook_url:
            logger.debug("Slack 알림 건너뜀 (Webhook URL 없음)")
            return
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Slack 알림 전송 완료")
        except Exception as exc:
            logger.error(f"Slack 알림 전송 실패 (무시됨): {exc}")

    # ------------------------------------------------------------------
    # 개별 작업 성공 알림
    # ------------------------------------------------------------------

    def send_success(
        self,
        job_name: str,
        record_count: int,
        expected_total: int,
        total_requests: int,
        success_requests: int,
        output_path: str,
        elapsed_sec: int,
        **kwargs,
    ) -> None:
        """파이프라인 성공 시 Block Kit 기반 상세 메시지를 전송한다."""
        # 달성률 계산
        if expected_total > 0:
            ratio = record_count / expected_total * 100
            ratio_str = f"{ratio:.1f}%"
            bar = self._progress_bar(ratio)
            count_line = f"*{record_count:,}건* / {expected_total:,}건  {bar}  `{ratio_str}`"
        else:
            count_line = f"*{record_count:,}건* (예상 건수 없음)"

        # 파일명만 추출 (경로 제거)
        filename = output_path.split("\\")[-1] if "\\" in output_path else output_path.split("/")[-1]

        mins, secs = divmod(elapsed_sec, 60)
        elapsed_str = f"{mins}분 {secs}초" if mins else f"{secs}초"

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"✅  수집 완료 — {job_name}", "emoji": True},
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*📦 수집 건수*\n{count_line}"},
                        {"type": "mrkdwn", "text": f"*📡 API 요청*\n성공 *{success_requests}* / 총 {total_requests}회"},
                    ],
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*⏱ 소요 시간*\n{elapsed_str}"},
                        {"type": "mrkdwn", "text": f"*📁 출력 파일*\n`{filename}`"},
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"🕐 {_now_kst()} KST  |  Government Data Pipeline"},
                    ],
                },
            ],
            "attachments": [{"color": "#2eb886"}],  # 왼쪽 녹색 바
        }
        self._send(payload)

    # ------------------------------------------------------------------
    # 개별 작업 실패 알림
    # ------------------------------------------------------------------

    def send_failure(
        self,
        job_name: str,
        error_msg: str,
        total_requests: int,
        success_requests: int,
        elapsed_sec: int,
        **kwargs,
    ) -> None:
        """파이프라인 실패 시 Block Kit 기반 에러 메시지를 전송한다."""
        mins, secs = divmod(elapsed_sec, 60)
        elapsed_str = f"{mins}분 {secs}초" if mins else f"{secs}초"

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"🚨  수집 실패 — {job_name}", "emoji": True},
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*📡 API 요청*\n성공 *{success_requests}* / 총 {total_requests}회"},
                        {"type": "mrkdwn", "text": f"*⏱ 소요 시간*\n{elapsed_str}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*🔍 에러 메시지*\n```{error_msg[:400]}```"},
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"🕐 {_now_kst()} KST  |  Government Data Pipeline"},
                    ],
                },
            ],
            "attachments": [{"color": "#e01e5a"}],  # 왼쪽 빨간 바
        }
        self._send(payload)

    # ------------------------------------------------------------------
    # 전체 요약 알림 (dataportal_all 또는 배치 실행 시)
    # ------------------------------------------------------------------

    def send_summary(self, results: list[dict], total_elapsed: int, batch_name: str = "전체 수집 작업") -> None:
        """복수 작업의 결과를 하나의 요약 메시지로 전송한다."""
        if not results:
            logger.warning("send_summary: 결과가 없어 전송 건너뜀")
            return

        success_list = [r for r in results if r.get("status") == "SUCCESS"]
        failure_list = [r for r in results if r.get("status") != "SUCCESS"]
        total_records = sum(r.get("record_count", 0) for r in success_list)
        total_expected = sum(r.get("expected_total", 0) for r in success_list)

        overall_ratio = (total_records / total_expected * 100) if total_expected > 0 else 0
        bar = self._progress_bar(overall_ratio)

        mins, secs = divmod(total_elapsed, 60)
        elapsed_str = f"{mins}분 {secs}초" if mins else f"{secs}초"

        # 상단 헤더 색상: 실패 있으면 주황, 전체 성공이면 파랑
        header_emoji = "📊" if not failure_list else "⚠️"
        sidebar_color = "#439fe0" if not failure_list else "#e8a020"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{header_emoji}  {batch_name} 결과 요약", "emoji": True},
            },
            {"type": "divider"},
            # 전체 통계
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*📦 총 수집량*\n"
                            f"*{total_records:,}건* / {total_expected:,}건\n"
                            f"{bar}  `{overall_ratio:.1f}%`"
                        ),
                    },
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*📋 작업 현황*\n"
                            f"✅ 성공  *{len(success_list)}개*\n"
                            f"🚨 실패  *{len(failure_list)}개*"
                        ),
                    },
                ],
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*⏱ 전체 소요 시간*\n{elapsed_str}"},
                    {"type": "mrkdwn", "text": f"*🗂 실행된 작업 수*\n총 {len(results)}개"},
                ],
            },
            {"type": "divider"},
            # 각 작업별 세부 결과
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*📌 작업별 상세 결과*"},
            },
        ]

        # 작업 목록 (2개씩 묶어서 fields로 표시)
        job_fields = []
        for r in results:
            if r.get("status") == "SUCCESS":
                cnt = r.get("record_count", 0)
                exp = r.get("expected_total", 0)
                r_pct = f"{cnt/exp*100:.0f}%" if exp > 0 else "N/A"
                job_fields.append({
                    "type": "mrkdwn",
                    "text": f"✅ *{r['job_name']}*\n{cnt:,}건 / {exp:,}건  `{r_pct}`",
                })
            else:
                job_fields.append({
                    "type": "mrkdwn",
                    "text": f"🚨 *{r['job_name']}*\n수집 실패",
                })

        # Slack blocks의 fields는 한 번에 최대 10개까지 지원 → 2개씩 나눠 추가
        for i in range(0, len(job_fields), 2):
            blocks.append({"type": "section", "fields": job_fields[i:i+2]})

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🕐 {_now_kst()} KST  |  Government Data Pipeline"},
            ],
        })

        payload = {
            "blocks": blocks,
            "attachments": [{"color": sidebar_color}],
        }
        self._send(payload)

    # ------------------------------------------------------------------
    # 재시도 경고 알림
    # ------------------------------------------------------------------

    def send_retry_warning(self, job_name: str, attempt: int, error_msg: str) -> None:
        """재시도 발생 시 경고를 전송한다."""
        payload = {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"⚠️ *[{job_name}] 재시도 발생 — 시도 #{attempt}*\n"
                            f"```{error_msg[:300]}```"
                        ),
                    },
                }
            ],
            "attachments": [{"color": "#e8a020"}],
        }
        self._send(payload)

    # ------------------------------------------------------------------
    # 유틸
    # ------------------------------------------------------------------

    @staticmethod
    def _progress_bar(ratio: float, length: int = 10) -> str:
        """비율(0~100)을 텍스트 프로그레스 바로 변환한다."""
        filled = round(ratio / 100 * length)
        filled = max(0, min(length, filled))
        return "█" * filled + "░" * (length - filled)

    def send_validation_result(self, results: list[dict], total_actual: int, total_expected: int):
        """데이터 검증 결과를 Slack으로 전송한다."""
        if not self.webhook_url:
            return

        overall_ratio = (total_actual / total_expected * 100) if total_expected > 0 else 0
        status_emoji = "✅" if overall_ratio >= 99 else "⚠️" if overall_ratio >= 90 else "🚨"

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{status_emoji} 데이터 품질 검증 리포트", "emoji": True},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*📦 총 수집량*\n*{total_actual:,}건* / {total_expected:,}건"},
                    {"type": "mrkdwn", "text": f"*📈 전체 달성률*\n`{overall_ratio:.1f}%`"},
                ],
            },
            {"type": "divider"},
        ]

        # 개별 파일 결과 추가
        for res in results:
            name = res["name"]
            actual = res["actual"]
            expected = res["expected"]
            ratio = res["ratio"]
            missing = res.get("missing_cols", [])
            
            # 아이콘 결정 (컬럼 누락은 무조건 빨간색)
            if missing:
                status = "🔴"
                msg = f"*{name}* (컬럼 누락)\n누락됨: `{', '.join(missing)}`"
            else:
                status = "🟢" if ratio >= 99 else "🟡" if ratio >= 90 else "🔴"
                msg = f"*{name}*\n{actual:,} / {expected:,} 건  `{ratio:.1f}%`"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{status} {msg}"
                }
            })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🕐 {_now_kst()} KST  |  Government Data Pipeline"},
            ],
        })

        payload = {
            "blocks": blocks,
            "attachments": [{"color": "#4bb543" if overall_ratio >= 99 else "#e8a020"}],
        }
        self._send(payload)
