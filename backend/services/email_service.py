"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Email Service
에너지 전달 시스템 (Energy Transmission System)
Gmail SMTP 기반 실제 이메일 발송
═══════════════════════════════════════════════════════
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional

from config import settings

logger = logging.getLogger("omega.civicflow.email")


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    attachments: Optional[List[str]] = None,
) -> bool:
    """
    Gmail SMTP를 통한 실제 이메일 발송
    .env에서 SMTP_USER, SMTP_PASSWORD(앱 비밀번호) 읽어 사용
    attachments: 첨부할 파일 경로 목록 (PDF 등)
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning(
            "⚠️ SMTP 설정이 비어있습니다. .env에 SMTP_USER와 SMTP_PASSWORD를 설정하세요.\n"
            "   Gmail 앱 비밀번호 발급: https://myaccount.google.com/apppasswords"
        )
        return False

    try:
        # 이메일 조립 — mixed로 변경하여 본문 + 첨부 모두 지원
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"Omega CivicFlow <{settings.SMTP_USER}>"
        msg["To"] = to_email

        # HTML 본문
        html_part = MIMEText(html_body, "html", "utf-8")
        msg.attach(html_part)

        # PDF 첨부 파일
        if attachments:
            for file_path in attachments:
                if not file_path or not os.path.exists(file_path):
                    logger.warning(f"  ├─ 첨부 파일 건너뜀 (파일 없음): {file_path}")
                    continue
                try:
                    filename = os.path.basename(file_path)
                    with open(file_path, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename= {filename}",
                    )
                    msg.attach(part)
                    logger.info(f"  ├─ PDF 첨부 완료: {filename}")
                except Exception as e:
                    logger.warning(f"  ├─ 첨부 실패 ({file_path}): {e}")

        # SMTP 연결 및 전송
        server = smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_USER, to_email, msg.as_string())
        server.quit()

        attached_count = len([a for a in (attachments or []) if a and os.path.exists(a)])
        logger.info(f"📧 이메일 발송 성공 → {to_email} (첨부 {attached_count}건)")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "🚨 SMTP 인증 실패! Gmail 앱 비밀번호를 확인하세요.\n"
            "   1. https://myaccount.google.com/apppasswords 접속\n"
            "   2. '앱 비밀번호' 생성 (앱: 메일, 기기: Windows 컴퓨터)\n"
            "   3. 생성된 16자리 비밀번호를 .env SMTP_PASSWORD에 입력"
        )
        return False
    except Exception as e:
        logger.error(f"🚨 이메일 발송 실패: {str(e)}")
        return False


def send_verification_email(to_email: str, token: str):
    """[1] 회원가입 이메일 인증 — 전기 블루 / 웰컴 톤"""
    verification_link = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    subject = "[Omega CivicFlow] 이메일 인증을 완료해주세요"
    html_body = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#060B18;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:40px 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- 상단 헤더 -->
  <tr><td style="background:linear-gradient(135deg,#0F172A 0%,#1E3A5F 100%);border-radius:16px 16px 0 0;padding:36px 40px;text-align:center;border-bottom:2px solid #3B82F6;">
    <div style="display:inline-block;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.4);border-radius:50px;padding:6px 18px;margin-bottom:16px;">
      <span style="color:#60A5FA;font-size:12px;font-weight:600;letter-spacing:2px;text-transform:uppercase;">OMEGA CIVICFLOW</span>
    </div>
    <div style="font-size:48px;margin:8px 0;">✦</div>
    <h1 style="color:#F1F5F9;margin:8px 0 4px;font-size:24px;font-weight:700;letter-spacing:-0.5px;">이메일 인증</h1>
    <p style="color:#64748B;margin:0;font-size:14px;">계정 활성화를 위해 이메일 인증이 필요합니다</p>
  </td></tr>

  <!-- 본문 -->
  <tr><td style="background:#0F172A;padding:40px;">
    <p style="color:#94A3B8;font-size:15px;line-height:1.7;margin:0 0 24px;">
      Omega CivicFlow에 가입해주셔서 감사합니다.<br>
      아래 버튼을 클릭하여 이메일 인증을 완료하면 서비스를 이용하실 수 있습니다.
    </p>

    <!-- 기능 안내 카드 -->
    <div style="background:#1E293B;border-radius:12px;padding:20px;margin-bottom:32px;border:1px solid #334155;">
      <p style="color:#60A5FA;font-size:13px;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin:0 0 14px;">인증 후 이용 가능한 서비스</p>
      <div style="display:flex;gap:8px;margin-bottom:10px;align-items:center;">
        <span style="color:#3B82F6;font-size:16px;">◆</span>
        <span style="color:#CBD5E1;font-size:14px;">공공 민원 문서 자동 분석</span>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:10px;align-items:center;">
        <span style="color:#3B82F6;font-size:16px;">◆</span>
        <span style="color:#CBD5E1;font-size:14px;">재무 지표 추출 및 요약 보고서</span>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <span style="color:#3B82F6;font-size:16px;">◆</span>
        <span style="color:#CBD5E1;font-size:14px;">AI 기반 문서 인사이트 시스템</span>
      </div>
    </div>

    <!-- CTA 버튼 -->
    <div style="text-align:center;margin:32px 0;">
      <a href="{verification_link}" style="display:inline-block;background:linear-gradient(135deg,#2563EB,#3B82F6);color:#fff;padding:16px 48px;text-decoration:none;border-radius:10px;font-size:16px;font-weight:700;letter-spacing:0.3px;box-shadow:0 4px 24px rgba(59,130,246,0.35);">
        이메일 인증 완료하기  →
      </a>
    </div>

    <div style="background:rgba(59,130,246,0.07);border:1px solid rgba(59,130,246,0.2);border-radius:8px;padding:14px 18px;margin-top:24px;">
      <p style="color:#64748B;font-size:12px;margin:0;line-height:1.6;">
        ⏱ 인증 링크 유효기간: <strong style="color:#94A3B8;">24시간</strong><br>
        본인이 가입을 요청하지 않았다면 이 이메일을 무시하세요.
      </p>
    </div>
  </td></tr>

  <!-- 푸터 -->
  <tr><td style="background:#060B18;border-radius:0 0 16px 16px;padding:24px 40px;text-align:center;border-top:1px solid #1E293B;">
    <p style="color:#334155;font-size:11px;margin:0;line-height:1.7;">
      본 메일은 Omega CivicFlow 시스템에서 자동 발송되었습니다.<br>
      문의: support@civicflow.ai &nbsp;|&nbsp; © 2025 Omega CivicFlow. All rights reserved.
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>
"""
    return send_email(to_email, subject, html_body)


def send_password_reset_email(to_email: str, token: str):
    """[2] 비밀번호 찾기 인증 — 앰버 경고 톤"""
    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    subject = "[Omega CivicFlow] 비밀번호 재설정 요청"
    html_body = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#060B18;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:40px 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- 경고 헤더 -->
  <tr><td style="background:linear-gradient(135deg,#1C1007 0%,#2D1A00 100%);border-radius:16px 16px 0 0;padding:36px 40px;text-align:center;border-bottom:2px solid #D97706;">
    <div style="display:inline-block;background:rgba(217,119,6,0.15);border:1px solid rgba(217,119,6,0.4);border-radius:50px;padding:6px 18px;margin-bottom:16px;">
      <span style="color:#FBBF24;font-size:12px;font-weight:600;letter-spacing:2px;text-transform:uppercase;">SECURITY ALERT</span>
    </div>
    <div style="font-size:48px;margin:8px 0;">🔐</div>
    <h1 style="color:#FEF3C7;margin:8px 0 4px;font-size:24px;font-weight:700;">비밀번호 재설정</h1>
    <p style="color:#78350F;margin:0;font-size:14px;">본인이 요청한 경우에만 아래 버튼을 클릭하세요</p>
  </td></tr>

  <!-- 본문 -->
  <tr><td style="background:#0F172A;padding:40px;">

    <!-- 알림 배너 -->
    <div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25);border-radius:10px;padding:16px 20px;margin-bottom:28px;display:flex;align-items:center;gap:12px;">
      <span style="font-size:20px;">⚠</span>
      <div>
        <p style="color:#FBBF24;font-size:13px;font-weight:600;margin:0 0 2px;">보안 알림</p>
        <p style="color:#92400E;font-size:12px;margin:0;">비밀번호 재설정이 귀하의 계정에 요청되었습니다.</p>
      </div>
    </div>

    <p style="color:#94A3B8;font-size:15px;line-height:1.7;margin:0 0 28px;">
      Omega CivicFlow 계정의 비밀번호 재설정 요청이 접수되었습니다.<br>
      아래 버튼을 통해 새 비밀번호를 안전하게 설정하세요.
    </p>

    <!-- CTA 버튼 -->
    <div style="text-align:center;margin:32px 0;">
      <a href="{reset_link}" style="display:inline-block;background:linear-gradient(135deg,#B45309,#D97706);color:#fff;padding:16px 48px;text-decoration:none;border-radius:10px;font-size:16px;font-weight:700;letter-spacing:0.3px;box-shadow:0 4px 24px rgba(217,119,6,0.35);">
        새 비밀번호 설정하기  →
      </a>
    </div>

    <!-- 본인 미요청 안내 -->
    <div style="background:#1E293B;border-radius:12px;padding:20px;border-left:4px solid #EF4444;margin-top:28px;">
      <p style="color:#F87171;font-size:13px;font-weight:600;margin:0 0 8px;">본인이 요청하지 않으셨나요?</p>
      <p style="color:#64748B;font-size:13px;margin:0;line-height:1.6;">
        이 이메일을 무시하시면 비밀번호는 변경되지 않습니다.<br>
        의심스러운 활동이 있다면 즉시 계정 보안을 점검하세요.
      </p>
    </div>

    <div style="background:rgba(217,119,6,0.07);border:1px solid rgba(217,119,6,0.2);border-radius:8px;padding:14px 18px;margin-top:20px;">
      <p style="color:#64748B;font-size:12px;margin:0;line-height:1.6;">
        ⏱ 링크 유효기간: <strong style="color:#FBBF24;">15분</strong> &nbsp;|&nbsp; 만료 후 재요청 필요
      </p>
    </div>
  </td></tr>

  <!-- 푸터 -->
  <tr><td style="background:#060B18;border-radius:0 0 16px 16px;padding:24px 40px;text-align:center;border-top:1px solid #1E293B;">
    <p style="color:#334155;font-size:11px;margin:0;line-height:1.7;">
      본 메일은 Omega CivicFlow 시스템에서 자동 발송되었습니다.<br>
      문의: support@civicflow.ai &nbsp;|&nbsp; © 2025 Omega CivicFlow. All rights reserved.
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>
"""
    return send_email(to_email, subject, html_body)


def send_password_change_email(to_email: str, token: str):
    """[3] 비밀번호 수정 인증 — 에메랄드 보안 확인 톤"""
    confirm_link = f"{settings.FRONTEND_URL}/verify-password-change?token={token}"
    subject = "[Omega CivicFlow] 비밀번호 변경 최종 확인"
    html_body = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#060B18;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:40px 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- 확인 헤더 -->
  <tr><td style="background:linear-gradient(135deg,#051A11 0%,#0D2E1A 100%);border-radius:16px 16px 0 0;padding:36px 40px;text-align:center;border-bottom:2px solid #059669;">
    <div style="display:inline-block;background:rgba(5,150,105,0.15);border:1px solid rgba(5,150,105,0.4);border-radius:50px;padding:6px 18px;margin-bottom:16px;">
      <span style="color:#34D399;font-size:12px;font-weight:600;letter-spacing:2px;text-transform:uppercase;">SECURITY VERIFICATION</span>
    </div>
    <div style="font-size:48px;margin:8px 0;">🛡️</div>
    <h1 style="color:#ECFDF5;margin:8px 0 4px;font-size:24px;font-weight:700;">비밀번호 변경 확인</h1>
    <p style="color:#065F46;margin:0;font-size:14px;">마지막 단계입니다. 아래 버튼으로 변경을 최종 확인하세요</p>
  </td></tr>

  <!-- 본문 -->
  <tr><td style="background:#0F172A;padding:40px;">

    <!-- 진행 단계 표시 — table 레이아웃 (이메일 클라이언트 호환) -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
      <tr>
        <!-- STEP 1 완료 -->
        <td width="80" style="text-align:center;vertical-align:top;">
          <div style="width:36px;height:36px;border-radius:50%;background:#10B981;margin:0 auto 6px;line-height:36px;text-align:center;">
            <span style="color:#fff;font-size:16px;font-weight:700;line-height:36px;">✓</span>
          </div>
          <span style="color:#34D399;font-size:11px;font-weight:600;display:block;">요청</span>
        </td>
        <!-- 연결선 1 -->
        <td style="vertical-align:middle;padding-bottom:22px;">
          <div style="height:2px;background:linear-gradient(90deg,#10B981,#059669);border-radius:2px;"></div>
        </td>
        <!-- STEP 2 현재 -->
        <td width="80" style="text-align:center;vertical-align:top;">
          <div style="width:36px;height:36px;border-radius:50%;background:#059669;margin:0 auto 6px;line-height:36px;text-align:center;box-shadow:0 0 16px rgba(5,150,105,0.6);">
            <span style="color:#fff;font-size:15px;font-weight:700;line-height:36px;">2</span>
          </div>
          <span style="color:#34D399;font-size:11px;font-weight:700;display:block;">인증</span>
        </td>
        <!-- 연결선 2 -->
        <td style="vertical-align:middle;padding-bottom:22px;">
          <div style="height:2px;background:#1E293B;border-radius:2px;"></div>
        </td>
        <!-- STEP 3 대기 -->
        <td width="80" style="text-align:center;vertical-align:top;">
          <div style="width:36px;height:36px;border-radius:50%;background:#1E293B;border:2px solid #334155;margin:0 auto 6px;line-height:32px;text-align:center;">
            <span style="color:#475569;font-size:15px;font-weight:700;line-height:32px;">3</span>
          </div>
          <span style="color:#475569;font-size:11px;display:block;">완료</span>
        </td>
      </tr>
    </table>

    <p style="color:#94A3B8;font-size:15px;line-height:1.7;margin:0 0 28px;">
      계정 보호를 위해 비밀번호 변경 전 본인 확인이 필요합니다.<br>
      아래 버튼을 클릭하시면 새 비밀번호가 즉시 적용됩니다.
    </p>

    <!-- CTA 버튼 -->
    <div style="text-align:center;margin:32px 0;">
      <a href="{confirm_link}" style="display:inline-block;background:linear-gradient(135deg,#047857,#059669);color:#fff;padding:16px 48px;text-decoration:none;border-radius:10px;font-size:16px;font-weight:700;letter-spacing:0.3px;box-shadow:0 4px 24px rgba(5,150,105,0.35);">
        비밀번호 변경 최종 확인  →
      </a>
    </div>

    <!-- 보안 안내 -->
    <div style="background:#1E293B;border-radius:12px;padding:20px;margin-top:28px;border:1px solid #334155;">
      <p style="color:#34D399;font-size:13px;font-weight:600;margin:0 0 12px;">🔒 보안 안내</p>
      <p style="color:#64748B;font-size:13px;margin:0 0 8px;line-height:1.6;">• 변경 후 모든 기기에서 다시 로그인이 필요합니다</p>
      <p style="color:#64748B;font-size:13px;margin:0 0 8px;line-height:1.6;">• 본인이 요청하지 않은 경우 즉시 고객센터로 문의하세요</p>
      <p style="color:#64748B;font-size:13px;margin:0;line-height:1.6;">• 정기적인 비밀번호 변경으로 계정을 안전하게 유지하세요</p>
    </div>

    <div style="background:rgba(5,150,105,0.07);border:1px solid rgba(5,150,105,0.2);border-radius:8px;padding:14px 18px;margin-top:20px;">
      <p style="color:#64748B;font-size:12px;margin:0;line-height:1.6;">
        ⏱ 링크 유효기간: <strong style="color:#34D399;">15분</strong> &nbsp;|&nbsp; 버튼 클릭 전까지 비밀번호는 변경되지 않습니다
      </p>
    </div>
  </td></tr>

  <!-- 푸터 -->
  <tr><td style="background:#060B18;border-radius:0 0 16px 16px;padding:24px 40px;text-align:center;border-top:1px solid #1E293B;">
    <p style="color:#334155;font-size:11px;margin:0;line-height:1.7;">
      본 메일은 Omega CivicFlow 시스템에서 자동 발송되었습니다.<br>
      문의: support@civicflow.ai &nbsp;|&nbsp; © 2025 Omega CivicFlow. All rights reserved.
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>
"""
    return send_email(to_email, subject, html_body)




def send_withdraw_confirmation_email(to_email: str, token: str):
    """[4] 회원탈퇴 최종 확인 인증 — 위험 영역 적색 톤"""
    confirm_link = f"{settings.FRONTEND_URL}/verify-withdraw?token={token}"
    subject = "[Omega CivicFlow] 회원탈퇴 최종 확인 — 되돌릴 수 없습니다"
    html_body = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#060B18;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:40px 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- 위험 헤더 -->
  <tr><td style="background:linear-gradient(135deg,#1A0606 0%,#2D0A0A 100%);border-radius:16px 16px 0 0;padding:36px 40px;text-align:center;border-bottom:2px solid #DC2626;">
    <div style="display:inline-block;background:rgba(220,38,38,0.15);border:1px solid rgba(220,38,38,0.4);border-radius:50px;padding:6px 18px;margin-bottom:16px;">
      <span style="color:#FCA5A5;font-size:12px;font-weight:600;letter-spacing:2px;text-transform:uppercase;">ACCOUNT WITHDRAWAL</span>
    </div>
    <div style="font-size:48px;margin:8px 0;">⚠</div>
    <h1 style="color:#FEE2E2;margin:8px 0 4px;font-size:24px;font-weight:700;">회원탈퇴 최종 확인</h1>
    <p style="color:#7F1D1D;margin:0;font-size:14px;">아래 버튼을 클릭하시면 계정이 즉시 익명화됩니다</p>
  </td></tr>

  <!-- 본문 -->
  <tr><td style="background:#0F172A;padding:40px;">

    <div style="background:rgba(220,38,38,0.08);border:1px solid rgba(220,38,38,0.25);border-radius:10px;padding:16px 20px;margin-bottom:28px;">
      <p style="color:#FCA5A5;font-size:13px;font-weight:600;margin:0 0 6px;">🚨 되돌릴 수 없는 작업입니다</p>
      <p style="color:#7F1D1D;font-size:12px;margin:0;line-height:1.6;">
        본인이 마이페이지에서 회원탈퇴를 요청하셨다면 아래 버튼을 클릭해 최종 확정해주세요.
        본인이 요청하지 않으셨다면 이 메일을 무시하시면 됩니다.
      </p>
    </div>

    <p style="color:#94A3B8;font-size:15px;line-height:1.7;margin:0 0 28px;">
      탈퇴가 확정되면 다음과 같이 처리됩니다:
    </p>

    <div style="background:#1E293B;border-radius:12px;padding:20px;margin-bottom:24px;border:1px solid #334155;">
      <p style="color:#E5E7EB;font-size:13px;margin:0 0 8px;line-height:1.6;">• 이메일 / 사용자명 / 비밀번호 즉시 익명화</p>
      <p style="color:#E5E7EB;font-size:13px;margin:0 0 8px;line-height:1.6;">• 계정 비활성화 (재로그인 불가)</p>
      <p style="color:#E5E7EB;font-size:13px;margin:0 0 8px;line-height:1.6;">• 업로드한 문서/분석 결과는 익명화된 계정에 연결되어 보존</p>
      <p style="color:#E5E7EB;font-size:13px;margin:0;line-height:1.6;">• 동일 이메일로 신규 가입 가능 (기존 데이터와 분리)</p>
    </div>

    <!-- CTA 버튼 -->
    <div style="text-align:center;margin:32px 0;">
      <a href="{confirm_link}" style="display:inline-block;background:linear-gradient(135deg,#991B1B,#DC2626);color:#fff;padding:16px 48px;text-decoration:none;border-radius:10px;font-size:16px;font-weight:700;letter-spacing:0.3px;box-shadow:0 4px 24px rgba(220,38,38,0.35);">
        회원탈퇴 영구 확정  →
      </a>
    </div>

    <div style="background:rgba(220,38,38,0.07);border:1px solid rgba(220,38,38,0.2);border-radius:8px;padding:14px 18px;margin-top:20px;">
      <p style="color:#64748B;font-size:12px;margin:0;line-height:1.6;">
        ⏱ 링크 유효기간: <strong style="color:#FCA5A5;">15분</strong> &nbsp;|&nbsp; 버튼 클릭 전까지 계정은 그대로 유지됩니다
      </p>
    </div>

    <div style="background:#1E293B;border-radius:12px;padding:20px;border-left:4px solid #FBBF24;margin-top:20px;">
      <p style="color:#FBBF24;font-size:13px;font-weight:600;margin:0 0 6px;">본인이 요청하지 않으셨나요?</p>
      <p style="color:#64748B;font-size:13px;margin:0;line-height:1.6;">
        이 이메일을 무시하시면 계정은 변경되지 않습니다. 의심스러운 활동이 있다면 즉시 비밀번호를 변경하세요.
      </p>
    </div>
  </td></tr>

  <!-- 푸터 -->
  <tr><td style="background:#060B18;border-radius:0 0 16px 16px;padding:24px 40px;text-align:center;border-top:1px solid #1E293B;">
    <p style="color:#334155;font-size:11px;margin:0;line-height:1.7;">
      본 메일은 Omega CivicFlow 시스템에서 자동 발송되었습니다.<br>
      문의: support@civicflow.ai &nbsp;|&nbsp; © 2025 Omega CivicFlow. All rights reserved.
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>
"""
    return send_email(to_email, subject, html_body)


def send_analysis_result_email(
    to_email: str,
    results: list,
    report_paths: Optional[List[str]] = None,
):
    """
    분석 완료된 문서 결과를 이메일로 전송 (PDF 요약 보고서 첨부)
    results: [{"filename": ..., "summary": ..., "category": ..., 
               "financial_metrics": ..., "insight_vectors": ...}, ...]
    report_paths: PDF 요약 보고서 파일 경로 목록
    """
    # 첨부 파일 수 계산
    valid_attachments = [p for p in (report_paths or []) if p and os.path.exists(p)]
    attach_info = f" + PDF {len(valid_attachments)}건 첨부" if valid_attachments else ""
    subject = f"[Omega CivicFlow] 문서 분석 결과 ({len(results)}건{attach_info})"

    # 각 문서별 결과 카드 생성
    cards_html = ""
    for i, r in enumerate(results, 1):
        cards_html += f"""
        <div style="background: #1E293B; border-radius: 8px; padding: 16px; margin-bottom: 16px; border-left: 4px solid #3B82F6;">
            <h3 style="color: #60A5FA; margin: 0 0 12px 0; font-size: 16px;">
                📄 {i}. {r.get('filename', '알 수 없는 파일')}
            </h3>
            <div style="margin-bottom: 8px;">
                <span style="color: #9CA3AF; font-size: 12px;">카테고리</span><br/>
                <span style="color: #34D399; font-weight: bold;">{r.get('category', '미분류')}</span>
            </div>
            <div style="margin-bottom: 8px;">
                <span style="color: #9CA3AF; font-size: 12px;">요약</span><br/>
                <span style="color: #E5E7EB;">{r.get('summary', '요약 없음')}</span>
            </div>
            <div style="margin-bottom: 8px;">
                <span style="color: #9CA3AF; font-size: 12px;">재무 지표</span><br/>
                <span style="color: #FBBF24;">{r.get('financial_metrics', '해당 없음')}</span>
            </div>
        </div>
        """

    # 첨부 안내 문구
    attachment_notice = ""
    if valid_attachments:
        attachment_notice = f"""
        <div style="background: rgba(59,130,246,0.1); border-radius: 8px; padding: 12px; margin-bottom: 16px; text-align: center;">
            <span style="color: #60A5FA; font-weight: bold;">📎 PDF 요약 보고서 {len(valid_attachments)}건이 첨부되어 있습니다</span>
        </div>
        """

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 24px; background-color: #0B0F19; color: #E5E7EB; border-radius: 12px;">
        <div style="text-align: center; margin-bottom: 24px;">
            <h1 style="color: #60A5FA; margin: 0;">Ω CivicFlow</h1>
            <p style="color: #9CA3AF; font-size: 14px;">문서 분석 결과 보고서 — {len(results)}건 처리 완료</p>
        </div>
        {attachment_notice}
        {cards_html}
        <div style="text-align: center; margin-top: 24px; padding-top: 16px; border-top: 1px solid #374151;">
            <p style="font-size: 12px; color: #6B7280;">
                본 메일은 Omega CivicFlow 시스템에서 자동 발송되었습니다.
            </p>
        </div>
    </div>
    """
    return send_email(to_email, subject, html_body, attachments=valid_attachments)
