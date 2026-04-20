"""
Gmail email notification module for Cancun deal alerts.
Uses Python's built-in smtplib — no extra packages needed.
Requires a Gmail App Password (not your real password).
"""

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)

HOTEL_NAME = "Crown Paradise Club Cancun"


class EmailNotifier:
    def __init__(self, gmail_address: str, gmail_app_password: str, recipient_email: str):
        self.sender = gmail_address
        self.password = gmail_app_password
        self.recipient = recipient_email

    def _send(self, subject: str, html_body: str, plain_body: str) -> bool:
        """Send an email via Gmail SMTP (port 465, SSL)."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Cancun Monitor <{self.sender}>"
        msg["To"] = self.recipient
        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipient, msg.as_string())
            logger.info(f"✅ Email sent to {self.recipient}")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "Gmail auth failed. Make sure you're using an App Password, "
                "not your real Gmail password. "
                "See: https://myaccount.google.com/apppasswords"
            )
            return False
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False

    def send_deal_alert(self, deals: list[dict]) -> bool:
        if not deals:
            return True

        now_str = datetime.now().strftime("%B %d, %Y at %H:%M ET")
        count = len(deals)
        subject = f"🌴 Cancun Deal Alert — {count} package{'s' if count > 1 else ''} under $1,200 CAD!"

        deal_rows = ""
        for i, deal in enumerate(deals, 1):
            date_str = deal.get("departure_date", "TBD")
            nights = deal.get("nights", "?")
            price = deal.get("price_per_person", 0)
            url = deal.get("booking_url", "#")
            source = deal.get("source", "").replace("_", " ").title()

            try:
                dep_date = datetime.strptime(date_str, "%Y-%m-%d")
                date_display = dep_date.strftime("%a, %B %d %Y")
                ret_day = dep_date.day + (nights if isinstance(nights, int) else 7)
                return_display = dep_date.replace(day=ret_day).strftime("%B %d")
            except Exception:
                date_display = date_str
                return_display = "?"

            savings = 1200 - price
            savings_color = "#16a34a" if savings > 200 else "#d97706"
            savings_label = f"Save ${savings:.0f}!" if savings > 0 else "At limit"

            deal_rows += f"""
            <tr>
              <td style="padding:20px;background:#f0fdf4;border-radius:10px;display:block;margin-bottom:12px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td><span style="font-size:16px;font-weight:600;color:#111;">Deal #{i}</span></td>
                    <td align="right">
                      <span style="background:#dcfce7;color:{savings_color};font-size:13px;font-weight:600;
                                   padding:4px 10px;border-radius:20px;">{savings_label}</span>
                    </td>
                  </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;">
                  <tr>
                    <td style="padding:5px 0;color:#6b7280;font-size:14px;width:40%;">Departure</td>
                    <td style="padding:5px 0;font-weight:600;font-size:14px;color:#111;">{date_display}</td>
                  </tr>
                  <tr>
                    <td style="padding:5px 0;color:#6b7280;font-size:14px;">Duration</td>
                    <td style="padding:5px 0;font-weight:600;font-size:14px;color:#111;">{nights} nights (return ~{return_display})</td>
                  </tr>
                  <tr>
                    <td style="padding:5px 0;color:#6b7280;font-size:14px;">Price/person</td>
                    <td style="padding:5px 0;font-weight:700;font-size:18px;color:#16a34a;">${price:.0f} CAD</td>
                  </tr>
                  <tr>
                    <td style="padding:5px 0;color:#6b7280;font-size:14px;">Includes</td>
                    <td style="padding:5px 0;font-size:14px;color:#374151;">All taxes &amp; fees</td>
                  </tr>
                </table>
                <a href="{url}"
                   style="display:inline-block;margin-top:14px;background:#0f766e;color:#fff;
                          text-decoration:none;padding:10px 22px;border-radius:8px;
                          font-size:14px;font-weight:600;">
                  Book Now on {source} →
                </a>
              </td>
            </tr>
            <tr><td style="height:12px;"></td></tr>
            """

        html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f9fafb;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:30px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;overflow:hidden;
                    box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <tr>
          <td style="background:#0f766e;padding:30px;text-align:center;">
            <div style="font-size:28px;margin-bottom:8px;">🌴 ✈️ 🌴</div>
            <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">Cancun Deal Alert!</h1>
            <p style="color:#ccfbf1;margin:8px 0 0;font-size:14px;">{HOTEL_NAME}</p>
            <p style="color:#99f6e4;margin:4px 0 0;font-size:13px;">Toronto (YYZ) → Cancun (CUN)</p>
          </td>
        </tr>
        <tr>
          <td style="background:#ecfdf5;padding:16px 30px;border-bottom:1px solid #d1fae5;">
            <p style="margin:0;font-size:15px;color:#065f46;text-align:center;">
              Found <strong>{count} package{'s' if count > 1 else ''}</strong> under
              <strong>$1,200 CAD/person</strong> (taxes &amp; fees included) 🎉
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:24px 30px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              {deal_rows}
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:0 30px 24px;">
            <div style="background:#fffbeb;border:1px solid #fde68a;
                        border-radius:8px;padding:14px 18px;">
              <p style="margin:0;font-size:13px;color:#92400e;">
                ⚡ <strong>Prices change fast</strong> — these deals can sell out within hours.
                Click "Book Now" to lock in the price.
              </p>
            </div>
          </td>
        </tr>
        <tr>
          <td style="background:#f9fafb;border-top:1px solid #e5e7eb;
                     padding:20px 30px;text-align:center;">
            <p style="margin:0;font-size:12px;color:#9ca3af;">
              Cancun Price Monitor &nbsp;|&nbsp; Checked: {now_str}<br>
              5–7 nights · All-inclusive · ≤$1,200 CAD/pp
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        plain_lines = [
            f"CANCUN DEAL ALERT — {HOTEL_NAME}",
            f"Toronto (YYZ) -> Cancun (CUN) | Checked: {now_str}",
            f"Found {count} deal(s) under $1,200 CAD/person\n",
        ]
        for i, deal in enumerate(deals, 1):
            plain_lines += [
                f"Deal #{i}",
                f"  Departure: {deal.get('departure_date', 'TBD')}",
                f"  Nights:    {deal.get('nights', '?')}",
                f"  Price:     ${deal.get('price_per_person', 0):.0f} CAD/person (taxes incl.)",
                f"  Book:      {deal.get('booking_url', '')}",
                "",
            ]
        plain_lines.append("Prices change fast — book ASAP!")

        return self._send(subject, html, "\n".join(plain_lines))

    def send_error_alert(self, error: str) -> bool:
        subject = "⚠️ Cancun Monitor — Error"
        html = f"""<div style="font-family:sans-serif;padding:20px;">
          <h2 style="color:#dc2626;">Monitor Error</h2>
          <p>The Cancun price monitor hit an error and will retry next scheduled run.</p>
          <pre style="background:#f3f4f6;padding:12px;border-radius:6px;
                      font-size:13px;white-space:pre-wrap;">{error[:1000]}</pre>
        </div>"""
        return self._send(subject, html, f"Cancun Monitor Error:\n\n{error[:1000]}")

    def test_connection(self) -> bool:
        subject = "✅ Cancun Monitor — Email connected!"
        html = f"""<div style="font-family:sans-serif;padding:20px;max-width:500px;">
          <h2 style="color:#0f766e;">Monitor is active!</h2>
          <p>Your Cancun price monitor email notifications are working correctly.</p>
          <ul>
            <li>Hotel: <strong>{HOTEL_NAME}</strong></li>
            <li>Route: YYZ → CUN · All-inclusive</li>
            <li>Duration: 5–7 nights</li>
            <li>Alert threshold: ≤$1,200 CAD/person (taxes incl.)</li>
            <li>Schedule: every 6 hours via GitHub Actions</li>
          </ul>
          <p>You'll get an email whenever a qualifying deal is found. 🌴</p>
        </div>"""
        return self._send(
            subject, html,
            f"Cancun Monitor active! Watching {HOTEL_NAME} — YYZ->CUN — 5-7 nights — ≤$1,200 CAD/pp"
        )
