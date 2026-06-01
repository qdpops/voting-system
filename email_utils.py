import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.jino.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "voting@jino.ru")
SMTP_PASS = os.getenv("SMTP_PASS", "")

def send_voting_link(email: str, voting_id: int, user_token: str, base_url: str):
    link = f"{base_url}/vote/{voting_id}/{user_token}"
    subject = "Приглашение к участию в голосовании"

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:2rem 1rem">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px">
        <tr>
          <td style="background:#1e1b4b;border-radius:16px 16px 0 0;padding:2rem;text-align:center">
            <div style="font-size:2.5rem;margin-bottom:0.5rem">&#128379;</div>
            <h1 style="color:white;font-size:1.25rem;font-weight:700;margin:0 0 0.5rem">Система голосования</h1>
            <p style="color:rgba(255,255,255,0.7);font-size:0.85rem;margin:0">Вы приглашены к участию в голосовании</p>
          </td>
        </tr>
        <tr>
          <td style="background:white;padding:2rem;border-radius:0 0 16px 16px">
            <p style="color:#1e293b;font-size:0.95rem;line-height:1.6;margin:0 0 1.5rem">
              Уважаемый участник,<br><br>
              Вам направлена персональная ссылка для участия в голосовании.
              Нажмите кнопку ниже для перехода.
            </p>
            <div style="text-align:center;margin:1.5rem 0">
              <a href="{link}"
                 style="display:inline-block;background:#4f46e5;color:white;text-decoration:none;
                        padding:1rem 2.5rem;border-radius:12px;font-weight:700;font-size:1rem">
                Перейти к голосованию &#8594;
              </a>
            </div>
            <p style="color:#64748b;font-size:0.8rem;text-align:center;margin:1rem 0 0;word-break:break-all">
              Если кнопка не работает, скопируйте ссылку:<br>
              <a href="{link}" style="color:#4f46e5">{link}</a>
            </p>
            <hr style="border:none;border-top:1px solid #e2e8f0;margin:1.5rem 0">
            <p style="color:#94a3b8;font-size:0.75rem;margin:0;line-height:1.6">
              &#128274; Ссылка персональная и предназначена только для вас.<br>
              Проголосовать можно только один раз.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    text_body = (
        f"Уважаемый участник,\n\n"
        f"Перейдите по ссылке для участия в голосовании:\n{link}\n\n"
        f"Проголосовать можно только один раз."
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
