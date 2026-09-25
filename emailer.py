# emailer.py — Send a polished HTML report of scored congressional trades
# Uses Gmail SMTP with an App Password (stored in .env).

import html
import smtplib
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv

from config import SCORED_TRADES_FILE, EMAIL_TIERS, SMTP_SERVER, SMTP_PORT

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

TIERS = EMAIL_TIERS


def load_scored_trades():
    """Load scored trades from disk."""
    if os.path.exists(SCORED_TRADES_FILE):
        with open(SCORED_TRADES_FILE, "r") as f:
            return json.load(f)
    return []


def compute_disclosure_delay(trade):
    """Calculate days between transaction and disclosure."""
    tx = trade.get("transaction_date", "")
    disc = trade.get("notification_date", "")
    if not tx or not disc:
        return "—"
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            tx_dt = datetime.strptime(tx, fmt)
            disc_dt = datetime.strptime(disc, fmt)
            return str((disc_dt - tx_dt).days)
        except ValueError:
            continue
    return "—"


def build_error_banner(errors):
    """
    Build a visible warning banner listing pipeline step failures.
    Without this, a step that crashed (e.g. scraper/parser raising an
    exception) looks identical in the email to a genuinely quiet day with
    nothing new to report — the run log shows "PARTIAL" but the person
    reading their inbox has no way to know anything went wrong.
    """
    if not errors:
        return ""
    items = "".join(f"<li>{html.escape(str(e))}</li>" for e in errors)
    return f"""
    <div style="background-color: #fef2f2; border: 1px solid #fca5a5; border-radius: 4px; padding: 12px 14px; margin-bottom: 20px;">
        <strong style="color: #dc2626;">&#9888; Pipeline error{'s' if len(errors) != 1 else ''} occurred during this run</strong>
        <p style="color: #7f1d1d; font-size: 12px; margin: 6px 0 4px 0;">
            The results below may be incomplete — one or more steps failed before finishing:
        </p>
        <ul style="margin: 0; padding-left: 20px; color: #7f1d1d; font-size: 12px;">
            {items}
        </ul>
    </div>"""


def build_trade_row(trade):
    """Build an HTML table row for a single trade."""
    ticker = trade.get("ticker", "")
    ticker_display = f"<strong>{ticker}</strong>" if ticker else "—"
    tx_type = trade.get("transaction_type", "N/A")
    committees = ", ".join(trade.get("committees", [])) or "—"
    delay = compute_disclosure_delay(trade)
    score = trade.get("score", 0)
    reason = trade.get("reason", "")
    pdf_url = trade.get("pdf_url", "")

    if "Purchase" in tx_type:
        type_color = "#22863a"
        type_label = "BUY"
    elif "Sale" in tx_type:
        type_color = "#cb2431"
        type_label = "SELL (partial)" if "partial" in tx_type else "SELL"
    else:
        type_color = "#555"
        type_label = tx_type

    return f"""
    <tr style="border-bottom: 1px solid #e2e8f0;">
        <td style="padding: 10px 8px; vertical-align: top;">
            <strong>{trade.get('representative', 'Unknown')}</strong><br>
            <span style="color: #666; font-size: 12px;">{committees}</span>
        </td>
        <td style="padding: 10px 8px; vertical-align: top;">
            {trade.get('asset', 'N/A')}<br>
            <span style="font-size: 13px;">Ticker: {ticker_display}</span>
        </td>
        <td style="padding: 10px 8px; vertical-align: top; color: {type_color}; font-weight: bold;">
            {type_label}
        </td>
        <td style="padding: 10px 8px; vertical-align: top;">{trade.get('amount', 'N/A')}</td>
        <td style="padding: 10px 8px; vertical-align: top;">
            {trade.get('transaction_date', 'N/A')}<br>
            <span style="color: #888; font-size: 12px;">{delay} day delay</span>
        </td>
        <td style="padding: 10px 8px; vertical-align: top; text-align: center;">
            <strong style="font-size: 18px;">{score}</strong>
        </td>
    </tr>
    <tr style="border-bottom: 2px solid #e2e8f0;">
        <td colspan="6" style="padding: 4px 8px 12px 8px;">
            <span style="font-size: 12px; color: #555;">{reason}</span>
            {f'<br><a href="{pdf_url}" style="font-size: 12px; color: #2563eb;">View original PDF</a>' if pdf_url else ''}
        </td>
    </tr>"""


def build_tier_section(tier_tag, tier_label, tier_color, tier_bg, trades):
    """Build the HTML for one score tier section."""
    rows = ""
    for t in trades:
        rows += build_trade_row(t)

    return f"""
    <div style="margin-bottom: 28px;">
        <div style="background-color: {tier_color}; color: white; padding: 8px 12px; border-radius: 4px 4px 0 0;">
            <strong>{tier_label}</strong> — {len(trades)} trade(s)
        </div>
        <table style="border-collapse: collapse; width: 100%; font-size: 13px; background-color: {tier_bg}; border: 1px solid #e2e8f0; border-top: none;">
            <thead>
                <tr style="background-color: rgba(0,0,0,0.05);">
                    <th style="padding: 6px 8px; text-align: left; width: 20%;">Member</th>
                    <th style="padding: 6px 8px; text-align: left; width: 25%;">Asset</th>
                    <th style="padding: 6px 8px; text-align: left; width: 8%;">Type</th>
                    <th style="padding: 6px 8px; text-align: left; width: 15%;">Amount</th>
                    <th style="padding: 6px 8px; text-align: left; width: 15%;">Date</th>
                    <th style="padding: 6px 8px; text-align: center; width: 7%;">Score</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>"""


def build_report_body(scored_trades, total_filings, errors=None):
    """Build the full HTML email report from scored trades."""
    errors = errors or []
    date_str = datetime.now().strftime("%B %d, %Y")
    error_banner = build_error_banner(errors)

    # Split trades into tiers
    tier_buckets = {tag: [] for tag, _, _, _ in TIERS}
    routine_count = 0
    for t in scored_trades:
        tag = t.get("tag", "routine")
        if tag in tier_buckets:
            tier_buckets[tag].append(t)
        else:
            routine_count += 1

    # Count flagged (above routine)
    flagged = sum(len(v) for v in tier_buckets.values())
    routine_count += len(scored_trades) - flagged

    # If nothing noteworthy, send the short version
    if flagged == 0:
        if errors and not scored_trades:
            # A step crashed before anything could be scored — don't claim
            # "all scored 25 or below" when scoring never actually happened.
            summary_line = (
                f"Scanned {total_filings} filing(s), but no trades could be scored "
                "this run due to the error(s) above."
            )
        else:
            summary_line = (
                f"Scanned {total_filings} filing(s), {len(scored_trades)} trade(s) extracted.<br>"
                "All scored 25 or below (routine)."
            )
        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 16px;">
            <h2 style="color: #1a365d;">Congressional Trade Alert</h2>
            <p style="color: #555;">{date_str}</p>
            <hr style="border: none; border-top: 2px solid #1a365d; margin-bottom: 20px;">
            {error_banner}
            <p style="font-size: 16px; color: #333;">No noteworthy trades today.</p>
            <p style="color: #888; font-size: 13px;">
                {summary_line}
            </p>
            <p style="color: #aaa; font-size: 11px; margin-top: 24px;">
                Source: disclosures-clerk.house.gov
            </p>
        </body>
        </html>"""

    # Build tier sections (only non-empty tiers)
    tier_html = ""
    for tier_tag, tier_label, tier_color, tier_bg in TIERS:
        if tier_buckets[tier_tag]:
            tier_html += build_tier_section(
                tier_tag, tier_label, tier_color, tier_bg, tier_buckets[tier_tag]
            )

    # Summary footer
    summary_parts = []
    for tier_tag, tier_label, _, _ in TIERS:
        count = len(tier_buckets[tier_tag])
        if count:
            summary_parts.append(f"<strong>{count}</strong> {tier_label.lower()}")
    summary_parts.append(f"<strong>{routine_count}</strong> routine (not shown)")
    summary_str = " &bull; ".join(summary_parts)

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 750px; margin: 0 auto; padding: 16px;">
        <h2 style="color: #1a365d; margin-bottom: 4px;">Congressional Trade Alert</h2>
        <p style="color: #555; margin-top: 0;">
            {date_str} &mdash; <strong>{flagged}</strong> trade(s) flagged above routine
        </p>
        <hr style="border: none; border-top: 2px solid #1a365d; margin-bottom: 20px;">
        {error_banner}
        {tier_html}

        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 12px; margin-top: 8px;">
            <strong style="font-size: 13px;">Summary</strong><br>
            <span style="font-size: 12px; color: #555;">
                {total_filings} filing(s) scanned &bull; {len(scored_trades)} trade(s) extracted<br>
                {summary_str}
            </span>
        </div>

        <p style="color: #aaa; font-size: 11px; margin-top: 24px;">
            Source: disclosures-clerk.house.gov &bull; Parsed from official PTR filings
        </p>
    </body>
    </html>"""


def build_no_filings_body(errors=None):
    """Build the HTML email for days with no new PTR filings."""
    errors = errors or []
    date_str = datetime.now().strftime("%B %d, %Y")
    error_banner = build_error_banner(errors)

    if errors:
        # Both scrapers may have failed outright (e.g. a site outage) before
        # any filings could actually be checked — this is NOT the same as a
        # confirmed quiet day, so don't claim the sites were successfully
        # checked when they weren't.
        headline = "Pipeline errors prevented a full check for new filings today."
        detail = (
            "One or more disclosure sites could not be checked successfully this run "
            "(see the error details above). This is different from a confirmed "
            "\"no new filings\" day — the pipeline may not have actually looked."
        )
    else:
        headline = "No new congressional trade filings today."
        detail = (
            "The pipeline checked House and Senate disclosure sites and found no new PTR "
            "filings since the last run."
        )

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; padding: 16px;">
        <h2 style="color: #1a365d;">Congressional Trade Alert</h2>
        <p style="color: #555;">{date_str}</p>
        <hr style="border: none; border-top: 2px solid #1a365d; margin-bottom: 20px;">
        {error_banner}
        <p style="font-size: 16px; color: #333;">{headline}</p>
        <p style="color: #888; font-size: 13px;">
            {detail}
        </p>
        <p style="color: #aaa; font-size: 11px; margin-top: 24px;">
            Source: disclosures-clerk.house.gov &bull; efdsearch.senate.gov
        </p>
    </body>
    </html>"""


def build_subject(scored_trades, no_new_filings=False, has_errors=False):
    """Build the email subject line."""
    date_str = datetime.now().strftime("%m/%d")
    # Surface errors in the subject itself so they're visible from the inbox
    # list view, without needing to open an email that otherwise looks like
    # a routine "nothing to report" day.
    prefix = "\u26a0 " if has_errors else ""
    if no_new_filings:
        return f"{prefix}Congressional Trade Alert ({date_str}): No new filings"
    flagged = sum(1 for t in scored_trades if t.get("tag", "routine") != "routine")
    if flagged:
        return f"{prefix}Congressional Trade Alert ({date_str}): {flagged} flagged trade(s)"
    return f"{prefix}Congressional Trade Alert ({date_str}): No noteworthy trades"


def _credentials_error(setting_name):
    if os.getenv("GITHUB_ACTIONS"):
        print(f"ERROR: {setting_name} secret is missing or empty.")
        print("Add it under: Settings → Secrets and variables → Actions → Repository secrets")
    else:
        print(f"ERROR: Set {setting_name} in your .env file.")
    return False


def _send(subject, html_body):
    """Internal: send an HTML email via Gmail SMTP."""
    if not GMAIL_ADDRESS or GMAIL_ADDRESS == "your_email@gmail.com":
        return _credentials_error("GMAIL_ADDRESS")
    if not GMAIL_APP_PASSWORD or "xxxx" in GMAIL_APP_PASSWORD.lower():
        return _credentials_error("GMAIL_APP_PASSWORD")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS
    msg.attach(MIMEText(html_body, "html"))

    print(f"Sending email to {GMAIL_ADDRESS}...")

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())
        print("Email sent successfully!")
        return True
    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail authentication failed.")
        print("Make sure you're using an App Password, not your regular password.")
        print("Set one up: Google Account → Security → 2-Step Verification → App Passwords")
        return False
    except Exception as e:
        print(f"ERROR sending email: {e}")
        return False


def send_report(scored_trades, total_filings=None, no_new_filings=False, errors=None):
    """
    Send the scored trade report.
    Called by main.py with scored trade data.

    `errors` is an optional list of human-readable messages describing any
    pipeline steps that failed this run — when present, the email visibly
    flags that the results may be incomplete instead of silently looking
    like a normal, fully-successful "nothing to report" day.
    """
    errors = errors or []
    if no_new_filings:
        subject = build_subject([], no_new_filings=True, has_errors=bool(errors))
        body = build_no_filings_body(errors=errors)
        return _send(subject, body)

    if total_filings is None:
        total_filings = len(set(t.get("filing_id", "") for t in scored_trades))

    subject = build_subject(scored_trades, has_errors=bool(errors))
    body = build_report_body(scored_trades, total_filings, errors=errors)
    return _send(subject, body)


# ─── RUN DIRECTLY FOR TESTING ───
if __name__ == "__main__":
    trades = load_scored_trades()
    if trades:
        print(f"Loaded {len(trades)} scored trade(s)")
        send_report(trades)
    else:
        print("No scored trades found. Run scorer.py first.")
