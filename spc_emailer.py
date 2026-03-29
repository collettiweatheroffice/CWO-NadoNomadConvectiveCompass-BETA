# -*- coding: ascii -*-
"""
CWO SPC Daily Outlook Emailer v7
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

#  CONFIG 
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

FEATURE_BASE = "https://mapservices.weather.noaa.gov/vector/rest/services/outlooks/SPC_wx_outlks/FeatureServer"

CAT_ORDER  = ["HIGH", "MDT", "ENH", "SLGT", "MRGL", "TSTM"]
CAT_LABELS = {
    "HIGH": "High Risk",
    "MDT":  "Moderate Risk",
    "ENH":  "Enhanced Risk",
    "SLGT": "Slight Risk",
    "MRGL": "Marginal Risk",
    "TSTM": "General Thunderstorms",
}
PROB_VALUES = {
    "2": 2, "5": 5, "10": 10, "15": 15, "30": 30, "45": 45, "60": 60,
    "0.02": 2, "0.05": 5, "0.10": 10, "0.15": 15,
    "0.30": 30, "0.45": 45, "0.60": 60,
}
# 


def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CWO-SPC-Emailer/7.0 (collettiweather@gmail.com)",
        "Accept": "text/plain, text/html, application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_bytes(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CWO-SPC-Emailer/7.0 (collettiweather@gmail.com)",
        "Accept": "image/gif, image/png, image/*",
        "Referer": "https://www.spc.noaa.gov/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_json(url):
    return json.loads(fetch_text(url))


#  OUTLOOK TEXT 

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
        ("PARTICULARLY DANGEROUS SITUATION", "PDS - Particularly Dangerous Situation"),
        ("HIGH RISK",     "High Risk"),
        ("MODERATE RISK", "Moderate Risk"),
        ("ENHANCED RISK", "Enhanced Risk"),
        ("SLIGHT RISK",   "Slight Risk"),
        ("MARGINAL RISK", "Marginal Risk"),
        ("THUNDERSTORMS", "General Thunderstorms"),
    ]
    for kw, label in pairs:
        if kw in upper:
            return label
    return "No Thunder / Below Threshold"


def extract_section(text, keyword):
    m = re.search(
        r"\.\.\." + keyword + r"\.\.\..*?(?=\.\.\.[A-Z]{3,}\.\.\.|\Z)",
        text, re.DOTALL | re.IGNORECASE
    )
    if m:
        s = m.group(0).strip()
        return (s[:700] + "...") if len(s) > 700 else s
    return "No " + keyword.lower() + " section found in this outlook."


#  IMAGE FETCHING 

def fetch_convective_image():
    candidates = [
        SPC_BASE + "/products/outlook/day1otlk_prt.gif",
        SPC_BASE + "/products/outlook/day1otlk_2000_prt.gif",
        SPC_BASE + "/products/outlook/day1otlk_1630_prt.gif",
        SPC_BASE + "/products/outlook/day1otlk_1200_prt.gif",
        SPC_BASE + "/products/outlook/day1otlk_0100_prt.gif",
    ]
    for url in candidates:
        try:
            data = fetch_bytes(url)
            if data and len(data) > 2000:
                print("[CWO] Convective image: " + url)
                return data
        except Exception as e:
            print("[CWO] Tried " + url + ": " + str(e))
    print("[CWO] Could not fetch convective image.")
    return None


def fetch_thunderstorm_image():
    candidates = [
        SPC_BASE + "/products/exper/enhtstm/imgs/enhtstm.gif",
        SPC_BASE + "/products/exper/enhtstm/imgs/enhtstm_latest.gif",
        SPC_BASE + "/products/exper/enhtstm/enhtstm.gif",
    ]
    for url in candidates:
        try:
            data = fetch_bytes(url)
            if data and len(data) > 2000:
                print("[CWO] Thunderstorm image: " + url)
                return data
        except Exception as e:
            print("[CWO] Tried " + url + ": " + str(e))
    print("[CWO] Could not fetch thunderstorm image.")
    return None


#  CWO AREA RISK 

def query_layer(layer_id):
    envelope = str(CWO_XMIN) + "," + str(CWO_YMIN) + "," + str(CWO_XMAX) + "," + str(CWO_YMAX)
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


def best_cat(feats):
    found = {str(f.get("dn", f.get("DN", ""))).upper() for f in feats}
    for lvl in CAT_ORDER:
        if lvl in found:
            return CAT_LABELS[lvl]
    return "No Thunder / Below Threshold"


def best_prob(feats):
    vals = []
    for f in feats:
        raw = str(f.get("dn", f.get("DN", ""))).strip()
        if raw in PROB_VALUES:
            vals.append(PROB_VALUES[raw])
    return max(vals) if vals else 0


def get_cwo_risks():
    cat  = best_cat(query_layer(1))
    torn = best_prob(query_layer(3))
    wind = best_prob(query_layer(4))
    hail = best_prob(query_layer(5))
    torn_str = str(torn) + "% tornado probability over CWO area" if torn else "Less than 2% (no contour over CWO area)"
    wind_str = str(wind) + "% wind probability over CWO area"    if wind else "Less than 5% (no contour over CWO area)"
    hail_str = str(hail) + "% hail probability over CWO area"    if hail else "Less than 5% (no contour over CWO area)"
    return {"cat": cat, "torn": torn_str, "wind": wind_str, "hail": hail_str}


#  MESOSCALE DISCUSSIONS 

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


#  HTML HELPERS 

def h(tag, content, style=""):
    if style:
        return "<" + tag + ' style="' + style + '">' + content + "</" + tag + ">"
    return "<" + tag + ">" + content + "</" + tag + ">"


def td(content, style=""):
    return h("td", content, style)


def tr(content, style=""):
    return h("tr", content, style)


def a(url, text, style=""):
    if style:
        return '<a href="' + url + '" style="' + style + '">' + text + "</a>"
    return '<a href="' + url + '">' + text + "</a>"


def section_card(title, body_html, border_color="#1a1f5e"):
    lines = []
    lines.append('<div style="background:#fff;margin:10px 14px 0;border-radius:8px;')
    lines.append('padding:20px 22px;border-top:4px solid ' + border_color + ';">')
    lines.append('<h2 style="margin:0 0 14px;font-size:14px;color:#1a1f5e;')
    lines.append('text-transform:uppercase;letter-spacing:0.8px;font-weight:700;">')
    lines.append(title + "</h2>")
    lines.append(body_html)
    lines.append("</div>")
    return "\n".join(lines)


def risk_table_row(label, value, bg=""):
    style_td1 = "padding:10px 14px;font-weight:700;color:#1a1f5e;font-size:14px;width:120px;"
    style_td2 = "padding:10px 14px;font-size:14px;"
    if bg:
        return tr(td(label, style_td1) + td(value, style_td2), 'style="background:' + bg + ';"')
    return tr(td(label, style_td1) + td(value, style_td2))


def cwo_risk_row(label, value, label_color, bg=""):
    style_td1 = "padding:10px 14px;font-weight:700;color:" + label_color + ";font-size:13px;width:120px;"
    style_td2 = "padding:10px 14px;font-size:13px;"
    if bg:
        return tr(td(label, style_td1) + td(value, style_td2), 'style="background:' + bg + ';"')
    return tr(td(label, style_td1) + td(value, style_td2))


def pre_block(text, border_color, bg_color):
    lines = []
    lines.append('<pre style="background:' + bg_color + ';border-left:3px solid ' + border_color + ';')
    lines.append('padding:10px 14px;font-size:12px;white-space:pre-wrap;')
    lines.append('border-radius:0 4px 4px 0;margin:0;color:#333;')
    lines.append('line-height:1.6;font-family:monospace;">')
    lines.append(text)
    lines.append("</pre>")
    return "\n".join(lines)


def img_section(cid, alt_text, fallback_url, fallback_label):
    lines = []
    lines.append('<p style="font-size:13px;color:#555;margin:0 0 8px;">')
    lines.append("Downloaded fresh at send time:</p>")
    lines.append('<img src="cid:' + cid + '" alt="' + alt_text + '"')
    lines.append('style="max-width:100%;height:auto;border-radius:6px;')
    lines.append('border:1px solid #ddd;display:block;" />')
    lines.append('<p style="font-size:11px;color:#aaa;margin:6px 0 0;text-align:right;">')
    lines.append(a(fallback_url, "View " + fallback_label + " on SPC", "color:#1a3a5c;"))
    lines.append("</p>")
    return "\n".join(lines)


def img_fallback_section(fallback_url, fallback_label):
    lines = []
    lines.append('<p style="color:#888;font-style:italic;font-size:13px;margin:4px 0;">')
    lines.append("Image unavailable - ")
    lines.append(a(fallback_url, "View " + fallback_label + " on SPC", "color:#1a3a5c;"))
    lines.append("</p>")
    return "\n".join(lines)


#  BUILD EMAIL 

def build_html(day1_text, day2_text, day3_text, cwo_risks, mds,
               has_conv_img, has_tstm_img):

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    nat1    = get_national_category(day1_text)
    nat2    = get_national_category(day2_text)
    nat3    = get_national_category(day3_text)

    torn_txt = extract_section(day1_text, "TORNADO")
    wind_txt = extract_section(day1_text, "WIND")
    hail_txt = extract_section(day1_text, "HAIL")
    tstm_txt = extract_section(day1_text, "THUNDERSTORMS")
    summary  = day1_text[:1400].strip()

    #  National risk table 
    nat_rows  = risk_table_row("Day 1 Outlook", nat1, "#eef1f8")
    nat_rows += risk_table_row("Day 2 Outlook", nat2)
    nat_rows += risk_table_row("Day 3 Outlook", nat3, "#eef1f8")
    nat_table = '<table style="width:100%;border-collapse:collapse;">' + nat_rows + "</table>"
    nat_card  = section_card("National Categorical Risk", nat_table)

    #  CWO risk table 
    cwo_rows  = cwo_risk_row("Categorical", cwo_risks["cat"], "#1a1f5e", "#eef1f8")
    cwo_rows += cwo_risk_row("Tornado",     cwo_risks["torn"], "#c0392b")
    cwo_rows += cwo_risk_row("Wind",        cwo_risks["wind"], "#2471a3", "#eef1f8")
    cwo_rows += cwo_risk_row("Hail",        cwo_risks["hail"], "#1e8449")
    cwo_note  = '<p style="font-size:11px;color:#bbb;margin:10px 0 0;">'
    cwo_note += "Based on SPC probability contours intersecting LOT/MKX/DVN bounding box.</p>"
    cwo_table = '<table style="width:100%;border-collapse:collapse;">' + cwo_rows + "</table>" + cwo_note
    cwo_card  = section_card("CWO Area Risk (LOT / MKX / DVN)", cwo_table, "#d4a843")

    #  Convective outlook image 
    if has_conv_img:
        conv_body = img_section("conv_img", "SPC Day 1 Convective Outlook", OUTLOOK_PAGES[1], "Convective Outlook")
    else:
        conv_body = img_fallback_section(OUTLOOK_PAGES[1], "Convective Outlook")
    conv_card = section_card("Day 1 Convective Outlook Map", conv_body)

    #  Thunderstorm outlook image 
    if has_tstm_img:
        tstm_img_body = img_section("tstm_img", "SPC Thunderstorm Outlook", TSTM_OUTLOOK_PAGE, "Thunderstorm Outlook")
    else:
        tstm_img_body = img_fallback_section(TSTM_OUTLOOK_PAGE, "Thunderstorm Outlook")
    tstm_card = section_card("SPC Thunderstorm Outlook", tstm_img_body)

    #  Hazard text 
    hazard_lines = []
    hazard_lines.append('<p style="font-weight:700;color:#c0392b;font-size:13px;margin:0 0 4px;">Tornado</p>')
    hazard_lines.append(pre_block(torn_txt, "#c0392b", "#fdf2f0"))
    hazard_lines.append('<p style="font-weight:700;color:#2471a3;font-size:13px;margin:14px 0 4px;">Wind</p>')
    hazard_lines.append(pre_block(wind_txt, "#2471a3", "#eaf4fb"))
    hazard_lines.append('<p style="font-weight:700;color:#1e8449;font-size:13px;margin:14px 0 4px;">Hail</p>')
    hazard_lines.append(pre_block(hail_txt, "#1e8449", "#eafaf1"))
    hazard_lines.append('<p style="font-weight:700;color:#6c3483;font-size:13px;margin:14px 0 4px;">Thunderstorms</p>')
    hazard_lines.append(pre_block(tstm_txt, "#6c3483", "#f5eef8"))
    hazard_card = section_card("Day 1 Hazard Text", "\n".join(hazard_lines))

    #  Full Day 1 text 
    full_lines = []
    full_lines.append('<pre style="background:#f4f6f8;padding:14px;font-size:12px;')
    full_lines.append('white-space:pre-wrap;border-radius:6px;margin:0;color:#222;')
    full_lines.append('line-height:1.65;font-family:monospace;">')
    full_lines.append(summary)
    full_lines.append("</pre>")
    full_lines.append('<p style="font-size:12px;color:#888;margin:8px 0 0;">')
    full_lines.append("Full product: " + a(OUTLOOK_PAGES[1], "SPC Day 1 Outlook", "color:#1a3a5c;"))
    full_lines.append("</p>")
    full_card = section_card("Day 1 Outlook Full Text", "\n".join(full_lines))

    #  MDs 
    if mds:
        md_rows = ""
        for m in mds:
            md_rows += tr(
                td("#" + m["num"], "padding:8px 12px;font-size:13px;color:#7a5200;font-weight:700;width:70px;") +
                td(a(m["url"], "Mesoscale Discussion #" + m["num"], "color:#1a3a5c;text-decoration:none;"),
                   "padding:8px 12px;font-size:13px;"),
                'style="border-bottom:1px solid #f0e8c8;"'
            )
        md_html  = '<table style="width:100%;border-collapse:collapse;background:#fffdf2;'
        md_html += 'border-radius:6px;overflow:hidden;border:1px solid #f0e8c8;">'
        md_html += tr(
            td("MD #", "padding:8px 12px;font-size:11px;color:#7a5200;font-weight:700;text-transform:uppercase;width:70px;") +
            td("Link", "padding:8px 12px;font-size:11px;color:#7a5200;font-weight:700;text-transform:uppercase;"),
            'style="background:#fff3cd;"'
        )
        md_html += md_rows + "</table>"
    else:
        md_html = '<p style="color:#888;font-style:italic;font-size:13px;margin:0;">'
        md_html += "No active mesoscale discussions at time of send.</p>"

    md_link  = '<p style="font-size:12px;color:#888;margin:10px 0 0;">'
    md_link += a(SPC_BASE + "/products/md/", "All active MDs on SPC", "color:#1a3a5c;") + "</p>"
    md_card  = section_card("Active Mesoscale Discussions", md_html + md_link)

    #  SPC links 
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

    #  Footer 
    footer_lines = []
    footer_lines.append('<div style="background:#1a1f5e;margin:14px 14px 0;border-radius:8px;')
    footer_lines.append('padding:22px 24px;text-align:center;">')
    footer_lines.append('<p style="margin:0 0 4px;color:#d4a843;font-weight:700;font-size:15px;">')
    footer_lines.append("Colletti Weather Office</p>")
    footer_lines.append('<p style="margin:0 0 4px;color:#8fa8d8;font-size:12px;">')
    footer_lines.append(a("mailto:" + REPLY_TO, REPLY_TO, "color:#aac4ee;") + "</p>")
    footer_lines.append('<p style="margin:0 0 14px;">')
    footer_lines.append(a(YT_URL, "YouTube.com/@MidwestMeteorology",
                          "color:#d4a843;font-size:13px;font-weight:700;text-decoration:none;") + "</p>")
    footer_lines.append('<hr style="border:none;border-top:1px solid #2a3270;margin:12px 0;" />')
    footer_lines.append('<p style="margin:0;color:#5566aa;font-size:11px;line-height:1.8;">')
    footer_lines.append("You are subscribed to CWO weather alerts.<br />")
    footer_lines.append("Per federal law (CAN-SPAM Act), you may unsubscribe at any time.<br />")
    footer_lines.append(a(UNSUB_URL, "Click here to unsubscribe", "color:#aac4ee;") + "</p>")
    footer_lines.append('<p style="margin:8px 0 0;color:#3a4488;font-size:10px;">')
    footer_lines.append("Automated digest - always verify with official NWS/SPC products.</p>")
    footer_lines.append("</div>")
    footer = "\n".join(footer_lines)

    #  Assemble 
    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html><body style="margin:0;padding:0;background:#eef0f5;font-family:Arial,Helvetica,sans-serif;">')
    parts.append('<div style="max-width:680px;margin:0 auto;">')

    # Header
    parts.append('<div style="background:#1a1f5e;padding:28px 28px 22px;text-align:center;">')
    parts.append('<img src="cid:cwo_logo" alt="Colletti Weather Office"')
    parts.append('style="max-width:130px;height:auto;display:block;margin:0 auto 14px;" />')
    parts.append('<h1 style="margin:0;color:#d4a843;font-size:20px;letter-spacing:1.5px;')
    parts.append('text-transform:uppercase;font-weight:700;">Daily SPC Outlook Brief</h1>')
    parts.append('<p style="margin:6px 0 2px;color:#8fa8d8;font-size:13px;">')
    parts.append("NWS Chicago (LOT) &middot; NWS Milwaukee (MKX) &middot; NWS Quad Cities (DVN)</p>")
    parts.append('<p style="margin:0;color:#5566aa;font-size:11px;">' + now_utc + "</p>")
    parts.append("</div>")

    parts.append(nat_card)
    parts.append(cwo_card)
    parts.append(conv_card)
    parts.append(tstm_card)
    parts.append(hazard_card)
    parts.append(full_card)
    parts.append(md_card)
    parts.append(links_card)
    parts.append(footer)
    parts.append('<div style="height:18px;"></div>')
    parts.append("</div>")
    parts.append("</body></html>")

    return "\n".join(parts)


#  SEND 

def send_email(subject, html_body, conv_img=None, tstm_img=None):
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

    if conv_img:
        img = MIMEImage(conv_img, _subtype="gif")
        img.add_header("Content-ID", "<conv_img>")
        img.add_header("Content-Disposition", "inline", filename="day1outlook.gif")
        msg.attach(img)
        print("[CWO] Convective image attached.")

    if tstm_img:
        img2 = MIMEImage(tstm_img, _subtype="gif")
        img2.add_header("Content-ID", "<tstm_img>")
        img2.add_header("Content-Disposition", "inline", filename="thunderstorm_outlook.gif")
        msg.attach(img2)
        print("[CWO] Thunderstorm image attached.")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())
    print("[CWO] Email sent to " + TO_EMAIL)


#  MAIN 

def main():
    print("[CWO] Fetching outlook texts...")
    day1_text = get_outlook_text(1)
    day2_text = get_outlook_text(2)
    day3_text = get_outlook_text(3)
    print("[CWO] Day 1: " + get_national_category(day1_text))

    print("[CWO] Querying CWO area risks...")
    cwo_risks = get_cwo_risks()
    print("[CWO] CWO: " + cwo_risks["cat"])

    print("[CWO] Fetching MDs...")
    mds = get_active_mds()
    print("[CWO] " + str(len(mds)) + " active MD(s)")

    print("[CWO] Fetching convective outlook image...")
    conv_img = fetch_convective_image()

    print("[CWO] Fetching thunderstorm outlook image...")
    tstm_img = fetch_thunderstorm_image()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nat1    = get_national_category(day1_text)
    subject = "[CWO] SPC Brief - " + now_str + " | Day 1: " + nat1 + " | CWO: " + cwo_risks["cat"]

    html = build_html(day1_text, day2_text, day3_text, cwo_risks, mds,
                      conv_img is not None, tstm_img is not None)
    send_email(subject, html, conv_img, tstm_img)
    print("[CWO] Done.")


if __name__ == "__main__":
    main()
