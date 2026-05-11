"""
pipeline/notifier.py
====================
Slack Webhook을 통한 성공/실패 알림 전송 모듈.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)


class SlackNotifier:
    """
    Slack Incoming Webhook으로 파이프라인 상태를 알립니다.
    SLACK_WEBHOOK_URL 환경변수가 없으면 알림을 건너뜁니다.
    """

    def __init__(self):
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
        if not self.webhook_url:
            logger.warning(
                "SLACK_WEBHOOK_URL 환경변수가 설정되지 않아 Slack 알림이 비활성화됩니다."
            )

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
            # 알림 전송 실패가 파이프라인 전체를 실패시키면 안 됨
            logger.error(f"Slack 알림 전송 실패 (무시됨): {exc}")

    def send_success(
        self,
        job_name: str,
        record_count: int,
        output_path: str,
        elapsed_sec: int,
    ) -> None:
        """파이프라인 성공 시 Slack에 녹색 메시지를 전송한다."""
        payload = {
            "attachments": [
                {
                    "color": "#36a64f",  # 녹색
                    "title": f"✅ [{job_name}] 파이프라인 성공",
                    "fields": [
                        {"title": "수집 건수", "value": f"{record_count:,}건", "short": True},
                        {"title": "소요 시간", "value": f"{elapsed_sec}초", "short": True},
                        {"title": "출력 파일", "value": output_path, "short": False},
                    ],
                    "footer": "Government Data Pipeline",
                    "ts": int(__import__("time").time()),
                }
            ]
        }
        self._send(payload)

    def send_failure(
        self,
        job_name: str,
        error_msg: str,
        elapsed_sec: int,
    ) -> None:
        """파이프라인 최종 실패 시 Slack에 빨간 메시지를 전송한다."""
        payload = {
            "attachments": [
                {
                    "color": "#ff0000",  # 빨간색
                    "title": f"🚨 [{job_name}] 파이프라인 최종 실패",
                    "fields": [
                        {"title": "에러 메시지", "value": f"```{error_msg[:500]}```", "short": False},
                        {"title": "소요 시간", "value": f"{elapsed_sec}초", "short": True},
                    ],
                    "footer": "Government Data Pipeline",
                    "ts": int(__import__("time").time()),
                }
            ]
        }
        self._send(payload)

    def send_retry_warning(self, job_name: str, attempt: int, error_msg: str) -> None:
        """재시도 발생 시 Slack에 노란색 경고를 전송한다."""
        payload = {
            "attachments": [
                {
                    "color": "#ffcc00",  # 노란색
                    "title": f"⚠️ [{job_name}] 재시도 발생 (시도 #{attempt})",
                    "text": f"```{error_msg[:300]}```",
                    "footer": "Government Data Pipeline",
                }
            ]
        }
        self._send(payload)
