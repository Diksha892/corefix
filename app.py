"""
Corefix - Intelligent Facility Management and Infrastructure Issue Reporting System
Stack: Python Flask + SQLite + HTML/CSS/JavaScript  (deployable on Render)
Target: Python 3.15 (latest stable); also runs on Python 3.10+
"""
import os
import re
import hmac
import base64
import json
import uuid
import urllib.request
import urllib.error
import random
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, jsonify, abort, send_from_directory)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "corefix.db"))
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(BASE_DIR, "uploads"))
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_IMAGE_COUNT = 5
os.makedirs(UPLOAD_DIR, exist_ok=True)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 26 * 1024 * 1024

# ----------------------------------------------------------------------------
# CONFIGURATION  (the "configurable" part of the scoring + tagging rules)
# ----------------------------------------------------------------------------
STATUSES = ["Submitted", "Under Review", "In Progress", "Resolved"]
CATEGORIES = ["Electrical", "Plumbing", "Furniture", "Cleaning", "Equipment", "Other"]
SEVERITIES = ["Minor", "Moderate", "Major", "Severe"]

# Facility locations, grouped by zone (used by the form and the heatmap)
LOCATIONS = {
    "Academic": ["Academic Block A", "Academic Block B", "Computer Lab", "Physics Lab", "Library"],
    "Residential": ["Boys Hostel", "Girls Hostel", "Mess / Cafeteria"],
    "Common": ["Admin Office", "Auditorium", "Sports Complex", "Parking Area"],
}
ALL_LOCATIONS = [loc for group in LOCATIONS.values() for loc in group]

# --- Dynamic Priority Scoring: points per factor --------------------------
CATEGORY_POINTS = {"Electrical": 30, "Plumbing": 20, "Equipment": 15,
                   "Furniture": 8, "Cleaning": 5, "Other": 5}
SEVERITY_POINTS = {"Minor": 5, "Moderate": 15, "Major": 25, "Severe": 35}
SAFETY_POINTS = 30
# Total score (max 95) -> priority level. Checked from the top down.
PRIORITY_THRESHOLDS = [(70, "Critical"), (50, "High"), (30, "Medium"), (0, "Low")]

# --- Smart Issue Capture & Auto-Tagging: keyword rules ---------------------
CATEGORY_KEYWORDS = {
    "Electrical": ["electric", "power", "socket", "switch", "wire", "wiring", "spark",
                   "short circuit", "fan", "light", "bulb", "tube", "mcb", "fuse", "voltage",
                   "shock", "outlet", "transformer", "ups", "led", "lamp", "no electricity"],
    "Plumbing": ["water", "leak", "leakage", "pipe", "tap", "drain", "drainage", "flush",
                 "toilet", "washroom", "sink", "overflow", "seepage", "tank", "clog", "sewage",
                 "faucet", "geyser", "bathroom"],
    "Furniture": ["chair", "table", "desk", "bench", "door", "window", "cupboard", "locker",
                  "shelf", "cabinet", "bed", "hinge", "broken seat", "lock", "furniture", "board", "sofa", "couch"],
    "Cleaning": ["dirty", "clean", "garbage", "trash", "dust", "smell", "stink", "waste",
                 "sanitation", "sweep", "mop", "pest", "cockroach", "rat", "mosquito", "dustbin"],
    "Equipment": ["projector", "computer", "pc", "ac", "air conditioner", "cooler", "printer",
                  "lift", "elevator", "generator", "router", "wifi", "network", "monitor",
                  "keyboard", "screen", "cctv", "camera", "equipment", "machine", "purifier", "ro", "hvac", "filter", "air conditioning"],
}
SAFETY_KEYWORDS = ["spark", "sparking", "shock", "electrocut", "fire", "smoke", "burning",
                   "gas leak", "exposed wire", "short circuit", "flood", "collapse", "collapsed",
                   "broken glass", "sewage", "injury", "injured", "hazard", "dangerous", "unsafe",
                   "live wire", "falling", "cracked ceiling", "stuck in lift"]


# ----------------------------------------------------------------------------
# CORE LOGIC
# ----------------------------------------------------------------------------
def _contains(text, word):
    """Whole-word / whole-phrase match so 'ac' does not match 'place'."""
    return re.search(r"(?<![a-z])" + re.escape(word) + r"(?:s|es)?(?![a-z])", text) is not None


def auto_tag(text):
    """Rule-based tagging. Returns (best_category, matched_keywords, safety_detected)."""
    text = (text or "").lower()
    best, best_hits, best_n = "Other", [], 0
    for cat, words in CATEGORY_KEYWORDS.items():
        hits = [w for w in words if _contains(text, w)]
        if len(hits) > best_n:
            best, best_hits, best_n = cat, hits, len(hits)
    safety_hits = [w for w in SAFETY_KEYWORDS if _contains(text, w)]
    return best, best_hits, bool(safety_hits)


def priority_score(category, severity, safety_risk):
    """Total = category points + severity points + safety points."""
    score = CATEGORY_POINTS.get(category, 5) + SEVERITY_POINTS.get(severity, 5)
    if safety_risk:
        score += SAFETY_POINTS
    return score


def priority_level(score):
    for threshold, name in PRIORITY_THRESHOLDS:
        if score >= threshold:
            return name
    return "Low"


# ----------------------------------------------------------------------------
# DATABASE
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket TEXT UNIQUE,
    reporter_name TEXT NOT NULL,
    reporter_email TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    category_source TEXT NOT NULL DEFAULT 'selected',
    tags TEXT DEFAULT '',
    location TEXT NOT NULL,
    severity TEXT NOT NULL,
    safety_risk INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Submitted',
    resolution_note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    note TEXT DEFAULT '',
    changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS issue_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    stored_name TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachments_issue ON issue_attachments(issue_id);
CREATE INDEX IF NOT EXISTS idx_issues_location ON issues(location);
CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def now_str(dt=None):
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def insert_issue(db, name, email, title, description, category, source, tags,
                 location, severity, safety, created=None, status="Submitted", note=""):
    score = priority_score(category, severity, safety)
    prio = priority_level(score)
    ts = now_str(created)
    cur = db.execute(
        """INSERT INTO issues (reporter_name, reporter_email, title, description, category,
           category_source, tags, location, severity, safety_risk, score, priority, status,
           resolution_note, created_at, updated_at, resolved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, email, title, description, category, source, ",".join(tags), location,
         severity, int(safety), score, prio, status, note, ts, ts,
         ts if status == "Resolved" else None))
    issue_id = cur.lastrowid
    ticket = f"CF-{issue_id:04d}"
    db.execute("UPDATE issues SET ticket=? WHERE id=?", (ticket, issue_id))
    db.execute("INSERT INTO status_history (issue_id,status,note,changed_at) VALUES (?,?,?,?)",
               (issue_id, "Submitted", "Report received", ts))
    if status != "Submitted":
        db.execute("INSERT INTO status_history (issue_id,status,note,changed_at) VALUES (?,?,?,?)",
                   (issue_id, status, note or "Status updated", ts))
    return issue_id, ticket


init_db()


# ----------------------------------------------------------------------------
# HELPERS: CSRF, auth, template globals
# ----------------------------------------------------------------------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST" and request.endpoint != "api_suggest":
        sent = request.headers.get("X-CSRF-Token", "") or request.form.get("_csrf", "")
        if not hmac.compare_digest(sent, session.get("_csrf", "x")):
            abort(400, "Invalid or missing form token. Go back and reload the page.")


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapper


@app.context_processor
def inject_globals():
    return dict(csrf_token=csrf_token, is_admin=bool(session.get("admin")),
                STATUSES=STATUSES, CATEGORIES=CATEGORIES, SEVERITIES=SEVERITIES)


@app.template_filter("nice_dt")
def nice_dt(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return value or "-"


@app.template_filter("slug")
def slug(value):
    return re.sub(r"[^a-z]+", "-", (value or "").lower()).strip("-")


# ----------------------------------------------------------------------------
# ISSUE PHOTOS + OPTIONAL VISION ANALYSIS
# ----------------------------------------------------------------------------
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (".jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (".webp", lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}


def _read_issue_images(file_items):
    """Validate uploaded image bytes, not just the browser-supplied MIME type."""
    files = [f for f in (file_items or []) if f and f.filename]
    if len(files) > MAX_IMAGE_COUNT:
        raise ValueError(f"Please upload no more than {MAX_IMAGE_COUNT} photos.")
    clean = []
    for item in files:
        data = item.read(MAX_IMAGE_SIZE + 1)
        item.stream.seek(0)
        if not data:
            raise ValueError("One of the selected photos is empty.")
        if len(data) > MAX_IMAGE_SIZE:
            raise ValueError("Each photo must be 5 MB or smaller.")
        match = next(((mime, ext) for mime, (ext, check) in ALLOWED_IMAGE_TYPES.items() if check(data)), None)
        if not match:
            raise ValueError("Use JPG, PNG or WEBP photos only. The file contents must be a valid image.")
        mime, ext = match
        clean.append({"file": item, "data": data, "mime": mime, "ext": ext,
                      "original": (item.filename or "issue-photo")[:180]})
    return clean


def _save_issue_images(db, issue_id, images):
    saved = []
    try:
        for image in images:
            stored = f"{uuid.uuid4().hex}{image['ext']}"
            target = os.path.join(UPLOAD_DIR, stored)
            with open(target, "wb") as out:
                out.write(image["data"])
            saved.append(target)
            db.execute("""INSERT INTO issue_attachments
                (issue_id, stored_name, original_name, mime_type, size_bytes, uploaded_at)
                VALUES (?,?,?,?,?,?)""",
                (issue_id, stored, image["original"], image["mime"], len(image["data"]), now_str()))
    except Exception:
        for target in saved:
            try: os.remove(target)
            except OSError: pass
        raise


def _openai_vision_analysis(images, title="", description=""):
    """Use the OpenAI Responses API when OPENAI_API_KEY is configured."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Visual AI is not connected yet. Add OPENAI_API_KEY in your environment to enable image analysis. You can still attach photos and submit your report.")
    content = [{"type": "input_text", "text": (
        "You are Corefix's visual issue-intake assistant for a facilities maintenance service desk. "
        "Inspect the attached facility photos and help the reporter describe the visible maintenance issue. "
        "Do not claim certainty about hidden causes, structural integrity, electrical safety, or anything not clearly visible. "
        "If there may be immediate danger, say to keep away and contact onsite emergency/facilities staff; never tell them to touch or repair it. "
        "Return ONLY valid JSON with keys: visual_summary (1-3 sentences), suggested_title (under 100 chars), "
        "suggested_description (clear factual wording, no invented details), suggested_category (one of Electrical, Plumbing, Furniture, Cleaning, Equipment, Other), "
        "suggested_severity (one of Minor, Moderate, Major, Severe), safety_flag (boolean), safety_reason (short string), "
        "confidence_note (short caveat). Treat the reporter's notes as context, not proof. "
        f"Reporter title: {title[:120]}\nReporter description: {description[:2000]}"
    )}]
    for image in images:
        encoded = base64.b64encode(image["data"]).decode("ascii")
        content.append({"type": "input_image", "image_url": f"data:{image['mime']};base64,{encoded}", "detail": "high"})
    payload = json.dumps({
        "model": os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": 700,
    }).encode("utf-8")
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=50) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Image analysis service returned an error ({exc.code}). {detail}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("The image analysis service could not be reached. Please try again.") from exc
    output_text = result.get("output_text")
    if not output_text:
        chunks = []
        for item in result.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text": chunks.append(part.get("text", ""))
        output_text = "\n".join(chunks)
    if not output_text:
        raise RuntimeError("The image analysis service returned an empty result. Please try again.")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        start, end = output_text.find("{"), output_text.rfind("}")
        if start < 0 or end <= start: raise RuntimeError("The image analysis result could not be read. Please try again.")
        parsed = json.loads(output_text[start:end+1])
    if not isinstance(parsed, dict):
        raise RuntimeError("The image analysis result was not in the expected format. Please try again.")
    if parsed.get("suggested_category") not in CATEGORIES: parsed["suggested_category"] = "Other"
    if parsed.get("suggested_severity") not in SEVERITIES: parsed["suggested_severity"] = "Moderate"
    parsed["safety_flag"] = bool(parsed.get("safety_flag"))
    return parsed


def _local_demo_analysis(images, title="", description="", reason="", severity_override="", safety_override=False):
    """Free, transparent rule-based fallback. It does not inspect image pixels."""
    filenames = " ".join((img.get("original") or "") for img in images)
    text = f"{title} {description} {filenames}".lower()
    category, hits, safety = auto_tag(text)
    if category == "Other" and any(x in text for x in ("sofa", "couch", "chair", "desk")):
        category = "Furniture"
    if category == "Other" and any(x in text for x in ("hvac", "filter", "air conditioning")):
        category = "Equipment"
    severe_terms = ("exposed wire", "sparking", "smoke", "fire", "shock", "short circuit", "live wire")
    major_terms = ("leak", "broken", "cracked", "damaged", "overflow", "not working", "failure")
    if any(term in text for term in severe_terms):
        severity = "Severe" if category == "Electrical" else "Major"
    elif any(term in text for term in major_terms):
        severity = "Major"
    else:
        severity = "Moderate"
    if category == "Electrical" and safety:
        severity = "Severe"
    if severity_override in SEVERITIES and severity_override != "Moderate":
        severity = severity_override
    safety = safety or bool(safety_override)
    clean_title = (title or "").strip()
    if not clean_title:
        clean_title = {
            "Furniture": "Damaged furniture requires inspection",
            "Plumbing": "Water leak requires maintenance",
            "Electrical": "Electrical issue requires inspection",
            "Equipment": "Equipment maintenance required",
            "Cleaning": "Cleaning issue requires attention",
        }.get(category, "Facility issue requires inspection")
    summary = (description or "").strip()
    if not summary:
        summary = f"A {category.lower()} issue has been selected for the free Corefix demonstration."
    return {
        "visual_summary": summary[:500],
        "suggested_title": clean_title[:100],
        "suggested_description": summary[:1000],
        "suggested_category": category,
        "suggested_severity": severity,
        "safety_flag": bool(safety),
        "safety_reason": "The issue notes contain a potential hazard keyword. Keep away and contact onsite facilities staff." if safety else "",
        "confidence_note": "FREE DEMO MODE: suggestions are based on the issue text and filename using local rules. The image pixels were not analysed. Verify all details onsite.",
        "analysis_mode": "demo",
        "analysis_label": "FREE DEMO · RULE-BASED",
        "fallback_reason": reason[:220],
        "matched_keywords": hits[:6],
    }


@app.route("/api/analyze-images", methods=["POST"])
def api_analyze_images():
    try:
        images = _read_issue_images(request.files.getlist("images"))
        if not images:
            return jsonify(error="Choose at least one photo to analyse."), 400
        title = request.form.get("title", "")
        description = request.form.get("description", "")
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        demo_only = os.environ.get("COREFIX_DEMO_MODE", "0").lower() in ("1", "true", "yes", "on")
        if demo_only or not api_key:
            reason = "Demo mode is enabled." if demo_only else "No OpenAI API key is configured."
            return jsonify(result=_local_demo_analysis(images, title, description, reason,
                request.form.get("severity", ""), request.form.get("safety") == "true"), mode="demo")
        try:
            result = _openai_vision_analysis(images, title, description)
            result["analysis_mode"] = "openai"
            result["analysis_label"] = "OPENAI VISION"
            return jsonify(result=result, mode="openai")
        except RuntimeError as exc:
            message = str(exc)
            # A quota/billing response should not block the academic demo.
            if "429" in message or "insufficient_quota" in message or "credit_balance_exhausted" in message:
                demo = _local_demo_analysis(images, title, description,
                    "OpenAI API credits are unavailable; local demo rules were used instead.",
                    request.form.get("severity", ""), request.form.get("safety") == "true")
                return jsonify(result=demo, mode="demo", notice="OpenAI credits are unavailable. Showing transparent free demo analysis instead.")
            raise
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503


@app.route("/issue-image/<int:issue_id>/<filename>")
def issue_image(issue_id, filename):
    db = get_db()
    row = db.execute("SELECT stored_name FROM issue_attachments WHERE issue_id=? AND stored_name=?",
                     (issue_id, filename)).fetchone()
    if not row: abort(404)
    return send_from_directory(UPLOAD_DIR, row["stored_name"], as_attachment=False,
                               max_age=3600, conditional=True)


# ----------------------------------------------------------------------------
# PUBLIC ROUTES: home, report, track
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    resolved = db.execute("SELECT COUNT(*) FROM issues WHERE status='Resolved'").fetchone()[0]
    urgent = db.execute("SELECT COUNT(*) FROM issues WHERE status!='Resolved' "
                        "AND priority IN ('Critical','High')").fetchone()[0]
    return render_template("index.html", total=total, resolved=resolved,
                           open_count=total - resolved, urgent=urgent)


@app.route("/report", methods=["GET", "POST"])
def report():
    form = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in
                ("name", "email", "title", "description", "category", "location", "severity")}
        form["safety"] = request.form.get("safety") == "on"
        errors = []
        try:
            uploaded_images = _read_issue_images(request.files.getlist("images"))
        except ValueError as exc:
            uploaded_images = []
            errors.append(str(exc))
        if len(form["name"]) < 2:
            errors.append("Please enter your name.")
        if form["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", form["email"]):
            errors.append("That email address doesn't look valid.")
        if len(form["title"]) < 5:
            errors.append("Title must be at least 5 characters.")
        if len(form["description"]) < 10:
            errors.append("Please describe the problem in at least 10 characters.")
        if form["location"] not in ALL_LOCATIONS:
            errors.append("Please choose a location.")
        if form["severity"] not in SEVERITIES:
            errors.append("Please choose a severity.")
        if form["category"] not in CATEGORIES + ["Auto-detect"]:
            errors.append("Please choose a category.")
        for key, limit in (("name", 80), ("email", 120), ("title", 120), ("description", 2000)):
            if len(form[key]) > limit:
                errors.append(f"{key.title()} is too long (max {limit} characters).")

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            text = f"{form['title']} {form['description']}"
            detected, hits, safety_detected = auto_tag(text)
            if form["category"] == "Auto-detect":
                category, source = detected, "auto"
            else:
                category, source = form["category"], "selected"
            tags = hits[:6]
            safety = form["safety"] or safety_detected
            db = get_db()
            _id, ticket = insert_issue(db, form["name"], form["email"], form["title"],
                                       form["description"], category, source, tags,
                                       form["location"], form["severity"], safety)
            try:
                _save_issue_images(db, _id, uploaded_images)
                db.commit()
            except Exception:
                db.rollback()
                flash("Your report could not save its photos. Please try again.", "error")
                return render_template("report.html", form=form, LOCATIONS=LOCATIONS)
            return redirect(url_for("track", ticket=ticket, new=1))
    return render_template("report.html", form=form, LOCATIONS=LOCATIONS)


@app.route("/track")
def track():
    ticket = request.args.get("ticket", "").strip().upper()
    issue, history, attachments = None, [], []
    if ticket:
        db = get_db()
        issue = db.execute("SELECT * FROM issues WHERE ticket=?", (ticket,)).fetchone()
        if issue:
            history = db.execute("SELECT * FROM status_history WHERE issue_id=? ORDER BY id",
                                 (issue["id"],)).fetchall()
            attachments = db.execute("SELECT * FROM issue_attachments WHERE issue_id=? ORDER BY id",
                                     (issue["id"],)).fetchall()
        else:
            flash(f"No report found with ID '{ticket}'. Please check and try again.", "error")
    return render_template("track.html", ticket=ticket, issue=issue, history=history,
                           attachments=attachments, is_new=request.args.get("new") == "1")


@app.route("/api/suggest", methods=["POST"])
def api_suggest():
    """Live preview used by the report form (auto-tag + priority score)."""
    data = request.get_json(silent=True) or {}
    text = f"{data.get('title', '')} {data.get('description', '')}"
    detected, hits, safety_detected = auto_tag(text)
    chosen = data.get("category")
    category = chosen if chosen in CATEGORIES else detected
    severity = data.get("severity") if data.get("severity") in SEVERITIES else "Moderate"
    safety = bool(data.get("safety")) or safety_detected
    score = priority_score(category, severity, safety)
    return jsonify(detected=detected, keywords=hits[:6], safety_detected=safety_detected,
                   category=category, score=score, priority=priority_level(score),
                   max_score=max(CATEGORY_POINTS.values()) + max(SEVERITY_POINTS.values()) + SAFETY_POINTS)


# ----------------------------------------------------------------------------
# HEATMAP
# ----------------------------------------------------------------------------
@app.route("/heatmap")
def heatmap():
    return render_template("heatmap.html", LOCATIONS=LOCATIONS)


@app.route("/api/heatmap")
def api_heatmap():
    mode = request.args.get("mode", "open")      # open | all
    category = request.args.get("category", "")
    db = get_db()
    where, params = [], []
    if mode == "open":
        where.append("status != 'Resolved'")
    if category in CATEGORIES:
        where.append("category = ?")
        params.append(category)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(f"SELECT * FROM issues {w} ORDER BY score DESC, created_at DESC", params).fetchall()

    result = {}
    for zone, locs in LOCATIONS.items():
        for loc in locs:
            result[loc] = dict(name=loc, zone=zone, count=0, critical=0, score_sum=0,
                               categories={}, issues=[])
    for r in rows:
        d = result.get(r["location"])
        if not d:
            continue
        d["count"] += 1
        d["score_sum"] += r["score"]
        d["critical"] += 1 if r["priority"] in ("Critical", "High") else 0
        d["categories"][r["category"]] = d["categories"].get(r["category"], 0) + 1
        if len(d["issues"]) < 5:
            d["issues"].append(dict(ticket=r["ticket"], title=r["title"], priority=r["priority"],
                                    status=r["status"], category=r["category"]))
    peak = max([d["count"] for d in result.values()] + [1])
    out = []
    for d in result.values():
        top = max(d["categories"], key=d["categories"].get) if d["categories"] else None
        out.append(dict(name=d["name"], zone=d["zone"], count=d["count"], urgent=d["critical"],
                        avg_score=round(d["score_sum"] / d["count"]) if d["count"] else 0,
                        intensity=round(d["count"] / peak, 2), top_category=top,
                        recurring=d["count"] >= 3, issues=d["issues"]))
    out.sort(key=lambda x: (-x["count"], x["name"]))
    return jsonify(locations=out, total=len(rows), peak=peak)


# ----------------------------------------------------------------------------
# ADMIN
# ----------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/admin") else url_for("dashboard"))
        flash("Incorrect password.", "error")
    return render_template("login.html")


@app.route("/admin/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    flash("You have been logged out.", "ok")
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def dashboard():
    db = get_db()
    f = {k: request.args.get(k, "") for k in ("status", "priority", "category", "q")}
    where, params = [], []
    if f["status"] in STATUSES:
        where.append("status = ?"); params.append(f["status"])
    if f["priority"] in ("Critical", "High", "Medium", "Low"):
        where.append("priority = ?"); params.append(f["priority"])
    if f["category"] in CATEGORIES:
        where.append("category = ?"); params.append(f["category"])
    if f["q"]:
        where.append("(title LIKE ? OR description LIKE ? OR ticket LIKE ? OR location LIKE ?)")
        params += [f"%{f['q']}%"] * 4
    w = ("WHERE " + " AND ".join(where)) if where else ""
    issues = db.execute(f"SELECT * FROM issues {w} ORDER BY (status='Resolved'), score DESC, "
                        f"created_at ASC", params).fetchall()
    by_status = {s: 0 for s in STATUSES}
    for r in db.execute("SELECT status, COUNT(*) c FROM issues GROUP BY status"):
        by_status[r["status"]] = r["c"]
    by_priority = {p: 0 for p in ("Critical", "High", "Medium", "Low")}
    for r in db.execute("SELECT priority, COUNT(*) c FROM issues WHERE status!='Resolved' GROUP BY priority"):
        by_priority[r["priority"]] = r["c"]
    return render_template("dashboard.html", issues=issues, f=f, by_status=by_status,
                           by_priority=by_priority, total=sum(by_status.values()))


@app.route("/admin/issue/<int:issue_id>", methods=["GET", "POST"])
@admin_required
def issue_detail(issue_id):
    db = get_db()
    issue = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if not issue:
        abort(404)
    if request.method == "POST":
        status = request.form.get("status", "")
        note = request.form.get("note", "").strip()[:500]
        if status not in STATUSES:
            flash("Invalid status.", "error")
        else:
            ts = now_str()
            resolved_at = ts if status == "Resolved" else None
            db.execute("UPDATE issues SET status=?, resolution_note=?, updated_at=?, resolved_at=? WHERE id=?",
                       (status, note or issue["resolution_note"], ts, resolved_at, issue_id))
            db.execute("INSERT INTO status_history (issue_id,status,note,changed_at) VALUES (?,?,?,?)",
                       (issue_id, status, note or "Status updated", ts))
            db.commit()
            flash(f"{issue['ticket']} updated to '{status}'.", "ok")
            return redirect(url_for("issue_detail", issue_id=issue_id))
    history = db.execute("SELECT * FROM status_history WHERE issue_id=? ORDER BY id", (issue_id,)).fetchall()
    attachments = db.execute("SELECT * FROM issue_attachments WHERE issue_id=? ORDER BY id", (issue_id,)).fetchall()
    return render_template("detail.html", issue=issue, history=history, attachments=attachments)


@app.route("/admin/seed", methods=["POST"])
@admin_required
def seed():
    n = seed_demo_data(get_db())
    flash(f"Loaded {n} demo reports.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/admin/clear", methods=["POST"])
@admin_required
def clear():
    db = get_db()
    db.execute("DELETE FROM status_history")
    db.execute("DELETE FROM issues")
    db.execute("DELETE FROM sqlite_sequence WHERE name IN ('issues','status_history')")
    db.commit()
    flash("All reports deleted.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/health")
def health():
    return {"status": "ok"}


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, msg="That page doesn't exist."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, msg=getattr(e, "description", "Bad request")), 400


# ----------------------------------------------------------------------------
# DEMO DATA (so the heatmap and dashboard look meaningful in a presentation)
# ----------------------------------------------------------------------------
DEMO = [
    ("Ceiling fan not working", "The ceiling fan in the room stopped and makes a humming noise.", "Boys Hostel", "Moderate", False),
    ("Sparking socket near desk", "There is sparking from the wall socket near the third bench, looks dangerous.", "Computer Lab", "Severe", False),
    ("Water leakage from pipe", "Pipe above the sink is leaking water all day and the floor is wet.", "Boys Hostel", "Major", False),
    ("Broken chairs in classroom", "Three chairs and one desk are broken and unusable.", "Academic Block A", "Moderate", False),
    ("Projector not turning on", "The projector in room 204 shows no display and the remote is dead.", "Academic Block B", "Moderate", False),
    ("Washroom tap leaking", "Tap in the ground floor washroom keeps dripping continuously.", "Academic Block A", "Minor", False),
    ("Garbage not collected", "Dustbins are overflowing and there is a bad smell near the entrance.", "Mess / Cafeteria", "Moderate", False),
    ("AC not cooling", "Air conditioner in the library reading hall is not cooling at all.", "Library", "Moderate", False),
    ("Tube light flickering", "Tube light flickers constantly and gives headaches.", "Library", "Minor", False),
    ("Exposed wire in corridor", "A live wire is hanging from the corridor ceiling, risk of electric shock.", "Academic Block A", "Severe", False),
    ("Drain overflow near hostel", "Drainage is clogged and sewage is overflowing near the gate.", "Girls Hostel", "Major", False),
    ("Geyser not working", "Hot water geyser in the bathroom is not heating.", "Girls Hostel", "Moderate", False),
    ("Lift stuck between floors", "The lift stops between floors and the door will not open.", "Admin Office", "Severe", False),
    ("Wi-Fi router down", "Network is down in the whole lab, no internet since morning.", "Computer Lab", "Major", False),
    ("Keyboard keys not working", "Several keyboards in the lab have broken keys.", "Computer Lab", "Minor", False),
    ("Door lock broken", "The locker room door lock is broken and cannot be secured.", "Sports Complex", "Moderate", False),
    ("Light bulbs fused in parking", "Most lamps are not working so the parking is dark at night.", "Parking Area", "Major", False),
    ("Stage light short circuit", "Burning smell and smoke from the stage light panel, possible short circuit.", "Auditorium", "Severe", False),
    ("Water purifier not working", "The RO water purifier near the mess has stopped.", "Mess / Cafeteria", "Moderate", False),
    ("Dust and cobwebs in lab", "Lab has not been cleaned for weeks, lots of dust on equipment.", "Physics Lab", "Minor", False),
    ("Table wobbling in lab", "Experiment table is wobbling and unstable.", "Physics Lab", "Minor", False),
    ("Power outage in block", "Whole floor has no electricity since evening, MCB keeps tripping.", "Boys Hostel", "Major", False),
    ("Window glass broken", "Window pane is broken and shards are on the floor.", "Academic Block B", "Major", True),
    ("Cockroaches in mess", "Cockroaches spotted in the kitchen area, pest control needed.", "Mess / Cafeteria", "Major", False),
    ("Water tank overflowing", "Overhead tank overflows every morning and wastes water.", "Boys Hostel", "Minor", False),
    ("Fan regulator broken", "Regulator knob is broken, fan stuck on full speed.", "Academic Block A", "Minor", False),
]


def seed_demo_data(db):
    rng = random.Random(42)
    base = datetime.now() - timedelta(days=20)
    count = 0
    for i, (title, desc, loc, sev, safety) in enumerate(DEMO):
        cat, hits, safety_auto = auto_tag(f"{title} {desc}")
        created = base + timedelta(days=rng.randint(0, 19), hours=rng.randint(0, 23))
        status = rng.choices(STATUSES, weights=[3, 2, 3, 4])[0]
        note = "Fixed by maintenance team." if status == "Resolved" else ""
        insert_issue(db, rng.choice(["Aarav", "Diya", "Rohan", "Meera", "Kabir", "Ananya"]),
                     "", title, desc, cat, "auto", hits[:6], loc, sev,
                     safety or safety_auto, created=created, status=status, note=note)
        count += 1
    db.commit()
    return count


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
