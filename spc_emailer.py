# -*- coding: utf-8 -*-
"""
CWO SPC Daily Outlook Emailer v9.1.2
Colletti Weather Office - LOT / MKX / DVN
"Nado Nomad's Convective Compass"
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

FEATURE_BASE = (
    "https://mapservices.weather.noaa.gov"
    "/vector/rest/services/outlooks/SPC_wx_outlks/FeatureServer"
)
LAYER_CAT  = 1
LAYER_TORN = 2
LAYER_WIND = 3
LAYER_HAIL = 4

CAT_ORDER = ["HIGH", "MDT", "ENH", "SLGT", "MRGL", "TSTM"]

CAT_NUM_MAP = {
    "2": "TSTM",
    "3": "MRGL",
    "4": "SLGT",
    "5": "ENH",
    "6": "MDT",
    "8": "HIGH",
}

CAT_META = {
    "HIGH": ("High Risk",             "&#128308;", "#e74c3c"),
    "MDT":  ("Moderate Risk",         "&#128992;", "#e67e22"),
    "ENH":  ("Enhanced Risk",         "&#128993;", "#f1c40f"),
    "SLGT": ("Slight Risk",           "&#128993;", "#f39c12"),
    "MRGL": ("Marginal Risk",         "&#128994;", "#27ae60"),
    "TSTM": ("General Thunderstorms", "&#9898;",   "#7f8c8d"),
}
NO_RISK = ("No Thunder / Below Threshold", "&#9898;", "#bdc3c7")

TORN_PROB_VALUES = {
    "2": 2, "5": 5, "10": 10, "15": 15, "30": 30, "45": 45, "60": 60,
    "0.02": 2, "0.05": 5, "0.10": 10, "0.15": 15, "0.30": 30, "0.45": 45, "0.60": 60,
}
WIND_PROB_VALUES = {
    "5": 5, "15": 15, "30": 30, "45": 45, "60": 60, "75": 75, "90": 90,
    "0.05": 5, "0.15": 15, "0.30": 30, "0.45": 45, "0.60": 60, "0.75": 75, "0.90": 90,
}
HAIL_PROB_VALUES = {
    "5": 5, "15": 15, "30": 30, "45": 45, "60": 60,
    "0.05": 5, "0.15": 15, "0.30": 30, "0.45": 45, "0.60": 60,
}

def prob_color(pct):
    if pct >= 45: return "#e74c3c"
    if pct >= 30: return "#e67e22"
    if pct >= 15: return "#f39c12"
    if pct >= 10: return "#f1c40f"
    if pct >=  5: return "#27ae60"
    return "#95a5a6"

def fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "CWO-SPC-Emailer/9.0 (collettiweather@gmail.com)",
        "Accept": "text/plain, text/html, application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def fetch_json(url):
    return json.loads(fetch_text(url))

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
        return "[Could not retrieve Day " + str(day) + " text: " + str(e)]

def get_national_cat_key(text):
    upper = text.upper()
    for kw, key in [
        ("PARTICULARLY DANGEROUS SITUATION", "HIGH"),
        ("HIGH RISK", "HIGH"),
        ("MODERATE RISK", "MDT"),
        ("ENHANCED RISK", "ENH"),
        ("SLIGHT RISK", "SLGT"),
        ("MARGINAL RISK", "MRGL"),
        ("THUNDERSTORMS", "TSTM"),
    ]:
        if kw in upper:
            return key
    return None

def cat_label(key):
    return CAT_META[key][0] if key in CAT_META else NO_RISK[0]

def cat_circle(key):
    return CAT_META[key][1] if key in CAT_META else NO_RISK[1]

def cat_color(key):
    return CAT_META[key][2] if key in CAT_META else NO_RISK[2]

# -------- FIXED FUNCTION --------
def best_cat_key(feats):
    found = set()

    for f in feats:
        raw = f.get("dn", f.get("DN", None))
        if raw is None:
            continue

        raw_str = str(raw).strip()

        if raw_str.endswith(".0"):
            raw_str = raw_str[:-2]

        mapped = CAT_NUM_MAP.get(raw_str)

        if mapped:
            found.add(mapped)

    print("[CWO] Cat values found (normalized): " + str(found))

    for lvl in CAT_ORDER:
        if lvl in found:
            return lvl

    return None

def best_prob(feats, prob_map, layer_name=""):
    vals = []
    for f in feats:
        for field in ["valid", "dn", "DN"]:
            raw = str(f.get(field, "")).strip()
            if raw in prob_map:
                vals.append(prob_map[raw])
                break
    return max(vals) if vals else 0

def query_layer(layer_id):
    envelope = f"{CWO_XMIN},{CWO_YMIN},{CWO_XMAX},{CWO_YMAX}"
    params = urllib.parse.urlencode({
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    })
    url = f"{FEATURE_BASE}/{layer_id}/query?{params}"
    try:
        data = fetch_json(url)
        return [f.get("attributes", {}) for f in data.get("features", [])]
    except:
        return []

# -------- FIXED FALLBACK --------
def get_cwo_risks():
    cat_feats  = query_layer(LAYER_CAT)
    torn_feats = query_layer(LAYER_TORN)
    hail_feats = query_layer(LAYER_HAIL)
    wind_feats = query_layer(LAYER_WIND)

    cat_key = best_cat_key(cat_feats)
    torn    = best_prob(torn_feats, TORN_PROB_VALUES)
    wind    = best_prob(wind_feats, WIND_PROB_VALUES)
    hail    = best_prob(hail_feats, HAIL_PROB_VALUES)

    if not cat_key and torn == 0 and wind == 0 and hail == 0:
        print("[CWO] WARNING: No data returned, defaulting to TSTM")
        cat_key = "TSTM"

    return {"cat_key": cat_key, "torn": torn, "hail": hail, "wind": wind}
