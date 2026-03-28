"""
CWO SPC Daily Outlook Emailer v2.2
Proprietary Code - Copyright (c) 2026 Jonathan Colletti
Authorized Use: Colletti Weather Office
"""

import smtplib
import urllib.request
import json
import re
import os
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

# ── CONFIG ─────────────────────────────────────────────────────────────────────
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_PASS"]
TO_EMAIL   = os.environ.get("TO_EMAIL", GMAIL_USER)
REPLY_TO   = "collettiweather@gmail.com"
UNSUB_URL  = "https://forms.gle"

# CWO coverage bounding box (LOT + MKX + DVN combined)
LAT_MIN, LAT_MAX = 40.5, 44.0
LON_MIN, LON_MAX = -91.5, -86.5

SPC_BASE    = "https://www.spc.noaa.gov"
MD_JSON_URL = f"https://www.spc.noaa.gov?{int(time.time())}"

# CWO logo as base64 inline image
CWO_LOGO_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAAHIAAAAAAQwAABtbnRyUkdCIFhZWiAH4AABAAEAAAAAAABhY3NwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA9tYAAQAAAADTLQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAlkZXNjAAAA8AAAACRyWFlaAAABFAAAABRnWFlaAAABKAAAABRiWFlaAAABPAAAABR3dHB0AAABUAAAABRyVFJDAAABZAAAAChnVFJDAAABZAAAAChiVFJDAAABZAAAAChjcHJ0AAABjAAAADxtbHVjAAAAAAAAAAEAAAAMZW5VUwAAAAgAAAAcAHMAUgBHAEJYWVogAAAAAAAAb6IAADj1AAADkFhZWiAAAAAAAABimQAAt4UAABjaWFlaIAAAAAAAACSgAAAPhAAAts9YWVogAAAAAAAA9tYAAQAAAADTLXBhcmEAAAAAAAQAAAACZmYAAPKnAAANWQAAE9AAAApbAAAAAAAAAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAAACAAAAAcAEcAbwBvAGcAbABlACAASQBuAGMALgAgADIAMAAxADb/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoH"
# ── END CONFIG ─────────────────────────────────────────────────────────────────

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "CWO-SPC-Emailer/2.2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def fetch_json(url):
    return json.loads(fetch(url))

def get_central_timestamp():
    """Generates the timestamp for the subject line in Central Time."""
    # Manual offset for CDT (UTC-5) as GitHub runners default to UTC.
    now_utc = datetime.now(timezone.utc)
    central_time = now_utc - timedelta(hours=5) 
    return central_time.strftime("%m/%d/%Y %I:%M %p CT")

def get_outlook_text(day=1):
    text_url = f"{SPC_BASE}/products/outlook/day{day}otlk_txt.html"
    try:
        raw = fetch(text_url)
        clean = re.sub(r"<[^>]+>", "", raw)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        # Fixed regex to capture the summary more reliably
        match = re.search(r"(SUMMARY.*?)(\$\$)", clean, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else clean[:3000]
    except Exception as e:
        return f"[Could not retrieve Day {day} outlook: {e}]"

def get_outlook_category(day=1):
    text = get_outlook_text(day)
    categories = [
        ("PARTICULARLY DANGEROUS SITUATION", "🔴 PDS — Particularly Dangerous Situation"),
        ("HIGH RISK",    "🔴 HIGH RISK"),
        ("MODERATE RISK","🟠 MODERATE RISK"),
        ("ENHANCED RISK","🟡 ENHANCED RISK"),
        ("SLIGHT RISK",  "🟡 SLIGHT RISK"),
        ("MARGINAL RISK","🟢 MARGINAL RISK"),
        ("ANY",          "🟢 MARGINAL / ANY RISK AREA"),
        ("POINTS",       "🟢 RISK AREA DEFINED"),
        ("THUNDERSTORMS","⚪ GENERAL THUNDERSTORMS"),
    ]
    upper = text.upper()
    for keyword, label in categories:
        if keyword in upper:
            return label, text
    return "⚪ NO THUNDER / BELOW THRESHOLD", text

def get_graphic_links():
    return {
        "Day 1 Outlook": f"{SPC_BASE}/products/outlook/day1otlk.html",
        "Day 2 Outlook": f"{SPC_BASE}/products/outlook/day2otlk.html",
        "Day 3 Outlook": f"{SPC_BASE}/products/outlook/day3otlk.html",
        "Mesoscale MDs": f"{SPC_BASE}/products/md/",
    }

def get_active_mds():
    try:
        data = fetch_json(MD_JSON_URL)
        mds = data.get("mds", [])
    except Exception:
        return []
    
    results = []
    for md in mds:
        try:
            lat1, lat2 = float(md.get("lat1", 0)), float(md.get("lat2", 0))
            lon1, lon2 = float(md.get("lon1", 0)), float(md.get("lon2", 0))
            if lon1 > 0: lon1 = -lon1
            if lon2 > 0: lon2 = -lon2
            lon_lo, lon_hi = min(lon1, lon2), max(lon1, lon2)
            lat_lo, lat_hi = min(lat1, lat2), max(lat1, lat2)
            overlaps = (lat_lo < LAT_MAX and lat_hi > LAT_MIN and
                        lon_lo < LON_MAX and lon_hi > LON_MIN)
        except Exception:
            overlaps = False

        results.append({
            "num":      md.get("mdnum", "???"),
            "title":    md.get("title", "Mesoscale Discussion"),
            "url":      f"{SPC_BASE}/products/md/md{str(md.get('mdnum','')).zfill(4)}.html",
            "near_cwo": overlaps,
        })
    return results

def extract_prob_text(outlook_text, hazard="TORNADO"):
    pattern = rf"\.\.\.{hazard}\.\.\..*?(?=\.\.\.[A-Z]{{3,}}\.\.\.|\Z)"
    match = re.search(pattern, outlook_text, re.DOTALL | re.IGNORECASE)
    if match:
        section = match.group(0).strip()
        return section[:600] + ("..." if len(section) > 600 else "")
    return f"No specific {hazard.lower()} section found in Day 1 outlook."

def build_email_html(day1_cat, day1_text, day2_cat, day3_cat, mds, graphics):
    subject_ts = get_central_timestamp()
    torn_prob = extract_prob_text(day1_text, "TORNADO")
    wind_prob = extract_prob_text(day1_text, "WIND")
    hail_prob = extract_prob_text(day1_text, "HAIL")
    
    md_section = ""
    if mds:
        near = [m for m in mds if m.get("near_cwo")]
        if near:
            md_section += f"<div style='border:2px solid #D4AF37;padding:10px;background:#002d5c;color:white;'><h3>⚠️ ACTIVE MDs (Near CWO Area)</h3>"
            for m in near:
                md_section += f"<p><a href='{m['url']}' style='color:white;'>MD #{m['num']} - {m['title']}</a></p>"
            md_section += "</div>"
    else:
        md_section = "<p>No active mesoscale discussions.</p>"

    graphic_buttons = ""
    for name, url in graphics.items():
        graphic_buttons += f'<a href="{url}" style="background:#D4AF37;color:#001F3F;padding:10px;text-decoration:none;font-weight:bold;margin:5px;display:inline-block;">{name}</a>'

    return f"""
    <html>
    <body style="font-family:Arial;background:#f4f4f4;">
        <table width="100%" style="background:#001F3F;color:white;padding:20px;">
            <tr><td align="center"><h1>COLLETTI WEATHER OFFICE</h1><p>{subject_ts}</p></td></tr>
            <tr><td style="background:white;color:black;padding:20px;">
                <h2>RISK LEVELS</h2>
                <p><b>Day 1:</b> {day1_cat}</p>
                <p><b>Day 2:</b> {day2_cat}</p>
                <p><b>Day 3:</b> {day3_cat}</p>
                {md_section}
                <h2>DAY 1 SUMMARY</h2><p>{day1_text[:1200]}...</p>
                <div style="text-align:center;">{graphic_buttons}</div>
            </td></tr>
        </table>
    </body>
    </html>
    """

def send_email():
    day1_cat, day1_text = get_outlook_category(1)
    day2_cat, _ = get_outlook_category(2)
    day3_cat, _ = get_outlook_category(3)
    mds = get_active_mds()
    graphics = get_graphic_links()
    
    subject_ts = get_central_timestamp()
    body = build_email_html(day1_cat, day1_text, day2_cat, day3_cat, mds, graphics)
    
    msg = MIMEMultipart()
    msg["From"] = f"Colletti Weather Office <{GMAIL_USER}>"
    msg["To"] = TO_EMAIL
    msg["Subject"] = f"CWO: {subject_ts} SPC Outlook Summary"
    msg.attach(MIMEText(body, "html"))

    server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
    server.login(GMAIL_USER, GMAIL_PASS)
    server.send_message(msg)
    server.quit()

if __name__ == "__main__":
    send_email()
