# -*- coding: ascii -*-
"""
CWO SPC Daily Outlook Emailer v8
Colletti Weather Office - LOT / MKX / DVN
"""

import smtplib
import urllib.request
import urllib.parse
import json
import re
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, timezone

# -- CONFIG -------------------------------------------------------------------
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_PASS"]
TO_EMAIL   = os.environ.get("TO_EMAIL", GMAIL_USER)
REPLY_TO   = "collettiweather@gmail.com"
UNSUB_URL  = "https://forms.gle/Jg5opiANhsZfBGYT9"
YT_URL     = "https://www.youtube.com/@MidwestMeteorology"

SPC_BASE   = "https://www.spc.noaa.gov"

CWO_XMIN, CWO_XMAX = -91.5, -86.5
CWO_YMIN, CWO_YMAX =  40.5,  44.0

TEXT_URLS = {
    1: "https://tgftp.nws.noaa.gov/data/raw/ac/acus01.kwns.swo.dy1.txt",
    2: "https://tgftp.nws.noaa.gov/data/raw/ac/acus02.kwns.swo.dy2.txt",
    3: "https://tgftp.nws.noaa.gov/data/raw/ac/acus03.kwns.swo.dy3.txt",
}

OUTLOOK_PAGES = {
    1: SPC_BASE + "/products/outlook/day1otlk.html",
    2: SPC_BASE + "/products/outlook/day2otlk.html",
    3: SPC_BASE + "/products/outlook/day3otlk.html",
}

TSTM_OUTLOOK_PAGE = SPC_BASE + "/products/exper/enhtstm/"

FEATURE_BASE = (
    "https://mapservices.weather.noaa.gov"
    "/vector/rest/services/outlooks/SPC_wx_outlks/FeatureServer"
)

# Layer IDs on NOAA FeatureServer
# 1  = Day 1 Categorical
# 3  = Day 1 Tornado prob
# 4  = Day 1 Wind prob
# 5  = Day 1 Hail prob
# 9  = Day 2 Categorical
# 16 = Day 3 Categorical

CAT_ORDER = ["HIGH", "MDT", "ENH", "SLGT", "MRGL", "TSTM"]

# Risk label, color circle HTML entity, hex color
CAT_META = {
    "HIGH": ("High Risk",              "&#128308;", "#e74c3c"),
    "MDT":  ("Moderate Risk",          "&#128992;", "#e67e22"),
    "ENH":  ("Enhanced Risk",          "&#128993;", "#f1c40f"),
    "SLGT": ("Slight Risk",            "&#128993;", "#f1c40f"),
    "MRGL": ("Marginal Risk",          "&#128994;", "#2ecc71"),
    "TSTM": ("General Thunderstorms",  "&#9898;",   "#95a5a6"),
}
NO_RISK = ("No Thunder / Below Threshold", "&#9898;", "#bdc3c7")

PROB_VALUES = {
    "2": 2, "5": 5, "10": 10, "15": 15, "30": 30, "45": 45, "60": 60,
    "0.02": 2, "0.05": 5, "0.10": 10, "0.15": 15,
    "0.30": 30, "0.45": 45, "0.60": 60,
}

# Probability color thresholds
def prob_color(pct):
    if pct >= 45: return "#e74c3c"
    if pct >= 30: return "#e67e22"
    if pct >= 15: return "#f39c12"
    if pct >= 10: return "#f1c40f"
    if pct >=  5: return "#2ecc71"
    return "#95a5a6"

# -----------------------------------------------------------------------------


def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CWO-SPC-Emailer/8.0 (collettiweather@gmail.com)",
        "Accept": "text/plain, text/html, application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_json(url):
    return json.loads(fetch_text(url))


# -- OUTLOOK TEXT -------------------------------------------------------------

def get_outlook_text(day=1):
    try:
        raw   = fetch_text(TEXT_URLS[day])
        lines = raw.splitlines()
        body, in_body = [], False
        for line in lines:
            if re.match(r"SWODY\d", line.strip()):
                in_body = True
                continue
            if in_body:
                body.append(line)
        text = "\n".join(body).strip()
        text = re.sub(r"\$\$.*", "", text, flags=re.DOTALL).strip()
        return text if text else raw[:3000]
    except Exception as e:
        return "[Could not retrieve Day " + str(day) + " text: " + str(e) + "]"


def get_national_category(text):
    upper = text.upper()
    pairs = [
        ("PARTICULARLY DANGEROUS SITUATION", "HIGH"),
        ("HIGH RISK",     "HIGH"),
        ("MODERATE RISK", "MDT"),
        ("ENHANCED RISK", "ENH"),
        ("SLIGHT RISK",   "SLGT"),
        ("MARGINAL RISK", "MRGL"),
        ("THUNDERSTORMS", "TSTM"),
    ]
    for kw, key in pairs:
        if kw in upper:
            return key
    return None


def cat_label(key):
    if key and key in CAT_META:
        return CAT_META[key][0]
    return NO_RISK[0]


def cat_circle(key):
    if key and key in CAT_META:
        return CAT_META[key][1]
    return NO_RISK[1]


def cat_color(key):
    if key and key in CAT_META:
        return CAT_META[key][2]
    return NO_RISK[2]


def extract_section(text, keyword):
    m = re.search(
        r"\.\.\." + keyword + r"\.\.\..*?(?=\.\.\.[A-Z]{3,}\.\.\.|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )
    if m:
        s = m.group(0).strip()
        return (s[:700] + "...") if len(s) > 700 else s
    return "No " + keyword.lower() + " section found in this outlook."


# -- CWO AREA RISK ------------------------------------------------------------

def query_layer(layer_id):
    envelope = (str(CWO_XMIN) + "," + str(CWO_YMIN) + ","
                + str(CWO_XMAX) + "," + str(CWO_YMAX))
    params = urllib.parse.urlencode({
        "geometry":       envelope,
        "geometryType":   "esriGeometryEnvelope",
        "spatialRel":     "esriSpatialRelIntersects",
        "inSR":           "4326",
        "outFields":      "*",
        "returnGeometry": "false",
        "f":              "json",
    })
    try:
        data = fetch_json(FEATURE_BASE + "/" + str(layer_id) + "/query?" + params)
        return [f.get("attributes", {}) for f in data.get("features", [])]
    except Exception as e:
        print("[CWO] Layer " + str(layer_id) + " failed: " + str(e))
        return []


def best_cat_key(feats):
    found = {str(f.get("dn", f.get("DN", ""))).upper() for f in feats}
    for lvl in CAT_ORDER:
        if lvl in found:
            return lvl
    return None


def best_prob(feats):
    vals = []
    for f in feats:
        raw = str(f.get("dn", f.get("DN", ""))).strip()
        if raw in PROB_VALUES:
            vals.append(PROB_VALUES[raw])
    return max(vals) if vals else 0


def get_cwo_risks():
    cat_key = best_cat_key(query_layer(1))
    torn    = best_prob(query_layer(3))
    wind    = best_prob(query_layer(4))
    hail    = best_prob(query_layer(5))
    return {
        "cat_key": cat_key,
        "torn":    torn,
        "wind":    wind,
        "hail":    hail,
    }


# -- MESOSCALE DISCUSSIONS ----------------------------------------------------

def get_active_mds():
    results = []
    try:
        html  = fetch_text(SPC_BASE + "/products/md/")
        links = re.findall(r'href="(?:\./)?md(\d{4})\.html"', html)
        seen  = set()
        for num in links:
            if num in seen:
                continue
            seen.add(num)
            results.append({
                "num": str(int(num)),
                "url": SPC_BASE + "/products/md/md" + num + ".html",
            })
            if len(results) >= 6:
                break
    except Exception as e:
        print("[CWO] MD scrape failed: " + str(e))
    return results


# -- HTML HELPERS -------------------------------------------------------------

def a(url, text, style=""):
    if style:
        return '<a href="' + url + '" style="' + style + '">' + text + "</a>"
    return '<a href="' + url + '">' + text + "</a>"


def section_card(title, body_html, border_color="#1a1f5e"):
    out  = '<div style="background:#fff;margin:10px 14px 0;border-radius:8px;'
    out += 'padding:20px 22px;border-top:4px solid ' + border_color + ';">'
    out += '<h2 style="margin:0 0 14px;font-size:14px;color:#1a1f5e;'
    out += 'text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">'
    out += title + "</h2>"
    out += body_html
    out += "</div>"
    return out


def risk_pill(circle, label, color):
    """Colored pill badge showing a risk level."""
    out  = '<span style="display:inline-flex;align-items:center;gap:6px;'
    out += 'background:' + color + '18;border:1px solid ' + color + ';'
    out += 'border-radius:20px;padding:4px 12px;font-size:13px;font-weight:600;'
    out += 'color:' + color + ';">'
    out += circle + " " + label
    out += "</span>"
    return out


def prob_bar(label, pct, icon):
    """Visual probability bar row."""
    color   = prob_color(pct)
    bar_w   = str(min(pct * 2, 100)) + "%"   # scale: 50% pct = full bar
    pct_str = str(pct) + "%" if pct else "< 2%"
    out  = '<div style="margin-bottom:12px;">'
    out += '<div style="display:flex;justify-content:space-between;'
    out += 'align-items:center;margin-bottom:4px;">'
    out += '<span style="font-size:13px;font-weight:600;color:#333;">' + icon + " " + label + "</span>"
    out += '<span style="font-size:13px;font-weight:700;color:' + color + ';">' + pct_str + "</span>"
    out += "</div>"
    out += '<div style="background:#eee;border-radius:4px;height:10px;width:100%;">'
    if pct:
        out += '<div style="background:' + color + ';width:' + bar_w + ';'
        out += 'height:10px;border-radius:4px;"></div>'
    out += "</div>"
    out += "</div>"
    return out


def pre_block(text, border_color, bg_color):
    out  = '<pre style="background:' + bg_color + ';border-left:3px solid ' + border_color + ';'
    out += 'padding:10px 14px;font-size:12px;white-space:pre-wrap;'
    out += 'border-radius:0 4px 4px 0;margin:0;color:#333;'
    out += 'line-height:1.6;font-family:monospace;">'
    out += text
    out += "</pre>"
    return out


# -- BUILD EMAIL --------------------------------------------------------------

def build_html(day1_text, day2_text, day3_text, cwo, mds):

    now_utc  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")

    nat1_key = get_national_category(day1_text)
    nat2_key = get_national_category(day2_text)
    nat3_key = get_national_category(day3_text)

    torn_txt = extract_section(day1_text, "TORNADO")
    wind_txt = extract_section(day1_text, "WIND")
    hail_txt = extract_section(day1_text, "HAIL")
    tstm_txt = extract_section(day1_text, "THUNDERSTORMS")
    summary  = day1_text[:1400].strip()

    # -- National risk card --
    def nat_row(day_label, key, page_url, bg=""):
        circle = cat_circle(key)
        label  = cat_label(key)
        color  = cat_color(key)
        pill   = risk_pill(circle, label, color)
        view   = a(page_url, "View", "font-size:11px;color:#1a3a5c;text-decoration:none;")
        row    = ('<td style="padding:10px 14px;font-weight:700;color:#1a1f5e;'
                  'font-size:14px;width:120px;">' + day_label + "</td>"
                  '<td style="padding:10px 14px;">' + pill + "</td>"
                  '<td style="padding:10px 14px;text-align:right;">' + view + "</td>")
        if bg:
            return '<tr style="background:' + bg + ';">' + row + "</tr>"
        return "<tr>" + row + "</tr>"

    nat_body  = '<table style="width:100%;border-collapse:collapse;">'
    nat_body += nat_row("Day 1 Outlook", nat1_key, OUTLOOK_PAGES[1], "#eef1f8")
    nat_body += nat_row("Day 2 Outlook", nat2_key, OUTLOOK_PAGES[2])
    nat_body += nat_row("Day 3 Outlook", nat3_key, OUTLOOK_PAGES[3], "#eef1f8")
    nat_body += "</table>"
    nat_card  = section_card("National Categorical Risk", nat_body)

    # -- CWO area risk card --
    cwo_cat_key  = cwo["cat_key"]
    cwo_circle   = cat_circle(cwo_cat_key)
    cwo_lbl      = cat_label(cwo_cat_key)
    cwo_color    = cat_color(cwo_cat_key)
    cwo_pill     = risk_pill(cwo_circle, cwo_lbl, cwo_color)

    cwo_body  = '<div style="margin-bottom:16px;">'
    cwo_body += '<p style="margin:0 0 8px;font-weight:700;font-size:13px;color:#1a1f5e;">Categorical</p>'
    cwo_body += cwo_pill
    cwo_body += "</div>"
    cwo_body += prob_bar("Tornado",   cwo["torn"], "&#127754;")
    cwo_body += prob_bar("Wind",      cwo["wind"], "&#128168;")
    cwo_body += prob_bar("Hail",      cwo["hail"], "&#129514;")
    cwo_body += '<p style="font-size:11px;color:#bbb;margin:10px 0 0;">'
    cwo_body += "Based on SPC probability contours intersecting the LOT/MKX/DVN bounding box.</p>"
    cwo_card  = section_card("CWO Area Risk (LOT / MKX / DVN)", cwo_body, "#d4a843")

    # -- Hazard text card --
    haz_body  = '<p style="font-weight:700;color:#c0392b;font-size:13px;margin:0 0 4px;">Tornado</p>'
    haz_body += pre_block(torn_txt, "#c0392b", "#fdf2f0")
    haz_body += '<p style="font-weight:700;color:#2471a3;font-size:13px;margin:14px 0 4px;">Wind</p>'
    haz_body += pre_block(wind_txt, "#2471a3", "#eaf4fb")
    haz_body += '<p style="font-weight:700;color:#1e8449;font-size:13px;margin:14px 0 4px;">Hail</p>'
    haz_body += pre_block(hail_txt, "#1e8449", "#eafaf1")
    haz_body += '<p style="font-weight:700;color:#6c3483;font-size:13px;margin:14px 0 4px;">Thunderstorms</p>'
    haz_body += pre_block(tstm_txt, "#6c3483", "#f5eef8")
    haz_card  = section_card("Day 1 Hazard Text", haz_body)

    # -- Full text card --
    full_body  = '<pre style="background:#f4f6f8;padding:14px;font-size:12px;'
    full_body += 'white-space:pre-wrap;border-radius:6px;margin:0;color:#222;'
    full_body += 'line-height:1.65;font-family:monospace;">' + summary + "</pre>"
    full_body += '<p style="font-size:12px;color:#888;margin:8px 0 0;">'
    full_body += "Full product: " + a(OUTLOOK_PAGES[1], "SPC Day 1 Outlook", "color:#1a3a5c;") + "</p>"
    full_card  = section_card("Day 1 Outlook Full Text", full_body)

    # -- MD card --
    if mds:
        md_inner  = '<table style="width:100%;border-collapse:collapse;background:#fffdf2;'
        md_inner += 'border-radius:6px;overflow:hidden;border:1px solid #f0e8c8;">'
        md_inner += ('<tr style="background:#fff3cd;">'
                     '<td style="padding:8px 12px;font-size:11px;color:#7a5200;'
                     'font-weight:700;text-transform:uppercase;width:70px;">MD #</td>'
                     '<td style="padding:8px 12px;font-size:11px;color:#7a5200;'
                     'font-weight:700;text-transform:uppercase;">Link</td>'
                     '</tr>')
        for m in mds:
            md_inner += ('<tr style="border-bottom:1px solid #f0e8c8;">'
                         '<td style="padding:8px 12px;font-size:13px;color:#7a5200;'
                         'font-weight:700;">#' + m["num"] + "</td>"
                         '<td style="padding:8px 12px;font-size:13px;">'
                         + a(m["url"], "Mesoscale Discussion #" + m["num"],
                             "color:#1a3a5c;text-decoration:none;")
                         + "</td></tr>")
        md_inner += "</table>"
    else:
        md_inner = ('<p style="color:#888;font-style:italic;font-size:13px;margin:0;">'
                    "No active mesoscale discussions at time of send.</p>")

    md_body  = md_inner
    md_body += '<p style="font-size:12px;color:#888;margin:10px 0 0;">'
    md_body += a(SPC_BASE + "/products/md/", "All active MDs on SPC", "color:#1a3a5c;") + "</p>"
    md_card  = section_card("Active Mesoscale Discussions", md_body)

    # -- Links card --
    btn_style = ("display:inline-block;margin:4px 5px 4px 0;padding:7px 13px;"
                 "background:#1a1f5e;color:#d4a843;border-radius:5px;"
                 "font-size:12px;font-weight:700;text-decoration:none;")
    btns = ""
    for name, url in [
        ("Day 1 Outlook", OUTLOOK_PAGES[1]),
        ("Day 2 Outlook", OUTLOOK_PAGES[2]),
        ("Day 3 Outlook", OUTLOOK_PAGES[3]),
        ("Active MDs",    SPC_BASE + "/products/md/"),
        ("SPC Homepage",  SPC_BASE),
    ]:
        btns += a(url, name, btn_style)
    links_card = section_card("SPC Links", btns)

    # -- Footer --
    footer  = '<div style="background:#1a1f5e;margin:14px 14px 0;border-radius:8px;'
    footer += 'padding:22px 24px;text-align:center;">'
    footer += '<p style="margin:0 0 4px;color:#d4a843;font-weight:700;font-size:15px;">'
    footer += "Colletti Weather Office</p>"
    footer += '<p style="margin:0 0 4px;color:#8fa8d8;font-size:12px;">'
    footer += a("mailto:" + REPLY_TO, REPLY_TO, "color:#aac4ee;") + "</p>"
    footer += '<p style="margin:0 0 14px;">'
    footer += a(YT_URL, "YouTube.com/@MidwestMeteorology",
                "color:#d4a843;font-size:13px;font-weight:700;text-decoration:none;")
    footer += "</p>"
    footer += '<hr style="border:none;border-top:1px solid #2a3270;margin:12px 0;" />'
    footer += '<p style="margin:0;color:#5566aa;font-size:11px;line-height:1.8;">'
    footer += "You are subscribed to CWO weather alerts.<br />"
    footer += "Per federal law (CAN-SPAM Act), you may unsubscribe at any time.<br />"
    footer += a(UNSUB_URL, "Click here to unsubscribe", "color:#aac4ee;") + "</p>"
    footer += '<p style="margin:8px 0 0;color:#3a4488;font-size:10px;">'
    footer += "Automated digest - always verify with official NWS/SPC products.</p>"
    footer += "</div>"

    # -- Assemble --
    out  = "<!DOCTYPE html>"
    out += '<html><body style="margin:0;padding:0;background:#eef0f5;'
    out += 'font-family:Arial,Helvetica,sans-serif;">'
    out += '<div style="max-width:680px;margin:0 auto;">'

    # Header
    out += '<div style="background:#1a1f5e;padding:28px 28px 22px;text-align:center;">'
    out += '<img src="cid:cwo_logo" alt="Colletti Weather Office" '
    out += 'style="max-width:130px;height:auto;display:block;margin:0 auto 14px;" />'
    out += '<h1 style="margin:0;color:#d4a843;font-size:20px;letter-spacing:1.5px;'
    out += 'text-transform:uppercase;font-weight:700;">Daily SPC Outlook Brief</h1>'
    out += '<p style="margin:6px 0 2px;color:#8fa8d8;font-size:13px;">'
    out += "NWS Chicago (LOT) &middot; NWS Milwaukee (MKX) &middot; NWS Quad Cities (DVN)</p>"
    out += '<p style="margin:0;color:#5566aa;font-size:11px;">' + now_utc + "</p>"
    out += "</div>"

    out += nat_card
    out += cwo_card
    out += haz_card
    out += full_card
    out += md_card
    out += links_card
    out += footer
    out += '<div style="height:18px;"></div>'
    out += "</div></body></html>"

    return out


# -- SEND ---------------------------------------------------------------------

def send_email(subject, html_body):
    msg = MIMEMultipart("related")
    msg["Subject"]  = subject
    msg["From"]     = GMAIL_USER
    msg["To"]       = TO_EMAIL
    msg["Reply-To"] = REPLY_TO

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    msg.attach(alt)

    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cwo_logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo = MIMEImage(f.read())
        logo.add_header("Content-ID", "<cwo_logo>")
        logo.add_header("Content-Disposition", "inline", filename="cwo_logo.png")
        msg.attach(logo)
        print("[CWO] Logo attached.")
    else:
        print("[CWO] WARNING: cwo_logo.png not found at " + logo_path)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print("[CWO] Email sent to " + TO_EMAIL)


# -- MAIN ---------------------------------------------------------------------

def main():
    print("[CWO] Fetching outlook texts...")
    day1_text = get_outlook_text(1)
    day2_text = get_outlook_text(2)
    day3_text = get_outlook_text(3)

    nat1_key = get_national_category(day1_text)
    print("[CWO] Day 1 national: " + cat_label(nat1_key))

    print("[CWO] Querying CWO area risks...")
    cwo = get_cwo_risks()
    print("[CWO] CWO categorical: " + cat_label(cwo["cat_key"]))
    print("[CWO] CWO tornado: " + str(cwo["torn"]) + "%")

    print("[CWO] Fetching MDs...")
    mds = get_active_mds()
    print("[CWO] " + str(len(mds)) + " active MD(s)")

    # Subject line: CWO SPC Digest | Mar 29, 2026 | National: Slight Risk | Area: Marginal Risk
    now_ct  = datetime.now(timezone.utc)
    date_str = now_ct.strftime("%b %d, %Y")
    subject  = ("CWO SPC Digest | " + date_str
                + " | National: " + cat_label(nat1_key)
                + " | Area: " + cat_label(cwo["cat_key"]))

    html = build_html(day1_text, day2_text, day3_text, cwo, mds)
    send_email(subject, html)
    print("[CWO] Done.")


if __name__ == "__main__":
    main()
