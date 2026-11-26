import csv
import json
import os
import re
import shutil
import hashlib
import secrets
import string
import subprocess
import sys
import webbrowser
import zipfile
from urllib.parse import urlparse
from datetime import datetime, time, timedelta
from pathlib import Path

import flet as ft

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "studytrack_data"
FILES_DIR = DATA_DIR / "attachments"
SUBMISSIONS_DIR = DATA_DIR / "submissions"

TABLES = {
    "users": ["id", "username", "password_hash", "role", "full_name", "last_login",
              "first_name", "middle_initial", "last_name", "approved", "failed_attempts", "locked_until", "theme", "suffix",
              "active"],
    "school_years": ["id", "name", "active", "created_at"],
    "sections": ["id", "name", "school_year", "active", "created_at"],
    "subjects": ["id", "name", "created_at", "course", "active"],
    "classes": ["id", "code", "name", "subject", "school_year", "teacher_id", "teacher_name", "created_at",
                "archived"],
    "enrollments": ["id", "class_id", "student_id", "student_name", "joined_at"],
    "announcements": ["id", "class_id", "title", "description", "file_path", "posted_at", "link"],
    "activities": ["id", "class_id", "title", "category", "number", "label", "term", "instructions",
                   "max_points", "deadline", "file_path", "created_at", "source"],
    "submissions": ["id", "activity_id", "class_id", "student_id", "student_name", "file_path",
                    "submitted_at", "score", "graded_at", "mark"],
    "grade_settings": ["id", "class_id", "semester", "midterm_weights", "finals_weights", "midterm_share",
                       "max_absences"],
    "activity_log": ["id", "time", "user_id", "user_name", "role", "kind", "action", "class_id", "details",
                     "student_id"],
    "reads": ["id", "user_id", "class_id", "seen_at"],
    "settings": ["id", "key", "value"],
}
COURSES = ("BSIT", "BSENTRE", "BSBA")
ALL_COURSES = "ALL"
CATEGORIES = ("Attendance", "Recitation", "Quiz", "Activity", "Laboratory", "Performance", "Exam")
TERMS = ("Midterm", "Finals")
SEMESTERS = ("1st Semester", "2nd Semester")
SCHOOL_NAME = "NUEVA ECIJA UNIVERSITY OF SCIENCE AND TECHNOLOGY"
SCHOOL_LOCATION = "Atate Campus, Palayan City, Nueva Ecija"
PASSING_GRADE = 75.0
MAX_FAILED_LOGINS = 5   
LOCKOUT_MINUTES = 5     
DEFAULT_ABSENCE_LIMIT = 3
MARKS = {"L": "Late", "M": "Make-up"}
DARK = {"on": False}
DARK_MAP = {
    "#FFFFFF": "#172033", "#F4F7FB": "#0E1522", "#F7F9FD": "#131C2D", "#F4F8FF": "#15213A",
    "#EEF2FF": "#1F2C4D", "#E8EEFF": "#233159", "#E8F8F4": "#12332F", "#FEE4E2": "#3A1C1C",
    "#EEF2F8": "#2A3650", "#E7ECF4": "#2A3650", "#E3E9F3": "#2E3A55", "#DCE3EF": "#34425F",
    "#18243A": "#E6EBF5", "#17243A": "#0A111D", "#24324A": "#E6EBF5",
    "#748198": "#9AA8BD", "#6B7890": "#9AA8BD", "#526078": "#B6C2D6", "#4B5B73": "#B6C2D6",
    "#344054": "#CBD5E5", "#B42318": "#F97066", "#B54708": "#F5A524", "#0D9488": "#2DD4BF",
}
DARK_TEXT_MAP = {"#3157D5": "#8FA8FF", "#7C3AED": "#B197FC", "#DB2777": "#F472B6"}


def C(hex_color, text=False):
    """Pick the light or dark version of a colour (text=True for text/icon colours)."""
    if not DARK["on"]:
        return hex_color
    key = hex_color.upper()
    if text and key in DARK_TEXT_MAP:
        return DARK_TEXT_MAP[key]
    return DARK_MAP.get(key, hex_color)


LATE_CREDIT = 0.5

# ---------- CSV storage and utility functions ----------

_READY = {"done": False}


def id_key(row):
    try:
        return int(row["id"])
    except (KeyError, ValueError, TypeError):
        return 0


def _upgrade_rows(table, rows):
    fields = TABLES[table]
    for r in rows:
        for f in fields:
            if r.get(f) is None:
                r[f] = ""
    if table in ("sections", "subjects") and "active" in fields:
        for r in rows:
            if r["active"] == "":
                r["active"] = "1"
    if table == "users":
        for r in rows:
            if r["approved"] == "":
                r["approved"] = "1"
            if r["active"] == "":
                r["active"] = "1"
    if table == "activities":
        counters = {}
        for r in sorted(rows, key=id_key):
            cat = r["category"] or "Activity"
            r["category"] = cat
            if not r["source"] and r["instructions"] == "Recorded in the record sheet.":
                r["source"] = "record"
            if not r["term"]:
                r["term"] = "Midterm"
            key = (r["class_id"], cat)
            counters[key] = counters.get(key, 0) + 1
            if not r["number"]:
                r["number"] = str(counters[key])
            if not r["label"]:
                r["label"] = f"{cat} {r['number']}"
    return rows


def ensure_storage():
    if _READY["done"]:
        return
    DATA_DIR.mkdir(exist_ok=True)
    FILES_DIR.mkdir(exist_ok=True)
    SUBMISSIONS_DIR.mkdir(exist_ok=True)
    for table, fields in TABLES.items():
        path = DATA_DIR / f"{table}.csv"
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=fields).writeheader()
            continue
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = list(reader) if header != fields else None
        if rows is not None:
            rows = _upgrade_rows(table, rows)
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
    _READY["done"] = True


def read_rows(table):
    ensure_storage()
    with (DATA_DIR / f"{table}.csv").open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_rows(table, rows):
    ensure_storage()
    target = DATA_DIR / f"{table}.csv"
    temp = DATA_DIR / f"{table}.csv.tmp"
    with temp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TABLES[table], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp, target)


def next_id(table):
    ids = [int(r["id"]) for r in read_rows(table) if (r.get("id") or "").isdigit()]
    return str(max(ids, default=0) + 1)


def add_row(table, row):
    rows = read_rows(table)
    rows.append({field: str(row.get(field, "")) for field in TABLES[table]})
    write_rows(table, rows)


def update_row(table, row_id, updates):
    rows = read_rows(table)
    for row in rows:
        if row.get("id") == str(row_id):
            row.update({k: str(v) for k, v in updates.items() if k in TABLES[table]})
            break
    write_rows(table, rows)


def remove_row(table, row_id):
    write_rows(table, [r for r in read_rows(table) if r.get("id") != str(row_id)])


def by_id(table, item_id):
    return next((r for r in read_rows(table) if r.get("id") == str(item_id)), None)


# School-wide settings
DEFAULT_SETTINGS = {
    "school_name": SCHOOL_NAME,
    "school_location": SCHOOL_LOCATION,
    "report_line3": "",                      
    "logo_path": "",                         
    "courses": ",".join(COURSES),
    "inactive_courses": "",
    "passing_grade": "75",
}


def get_setting(key):
    row = next((r for r in read_rows("settings") if r["key"] == key), None)
    if row is not None and (row["value"] or "").strip() != "":
        return row["value"]
    return DEFAULT_SETTINGS.get(key, "")


def set_setting(key, value):
    row = next((r for r in read_rows("settings") if r["key"] == key), None)
    if row:
        update_row("settings", row["id"], {"value": value})
    else:
        add_row("settings", {"id": next_id("settings"), "key": key, "value": value})


def get_courses():
    """Course codes (e.g. BSIT) the school offers, from School settings."""
    items = [c.strip().upper() for c in get_setting("courses").replace(";", ",").split(",")]
    return tuple(c for c in items if c) or tuple(COURSES)


def get_inactive_courses():
    """Course codes the admin has set to inactive (they stay listed but are hidden from pickers)."""
    items = [c.strip().upper() for c in get_setting("inactive_courses").replace(";", ",").split(",")]
    return tuple(c for c in items if c)


def get_active_courses():
    """Courses currently offered (all courses minus the inactive ones)."""
    inactive = get_inactive_courses()
    return tuple(c for c in get_courses() if c not in inactive)


def get_passing_grade():
    try:
        return float(get_setting("passing_grade"))
    except (TypeError, ValueError):
        return PASSING_GRADE


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()
        return secrets.compare_digest(check, digest)
    except (ValueError, TypeError):
        return False


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def unique_code(existing_codes):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if code not in existing_codes:
            return code


def plural(word, n):
    """1 class / 2 classes, 1 student / 2 students."""
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word}es" if word.endswith(("s", "ch", "sh", "x")) else f"{n} {word}s"


def fmt(value):
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def name_parts(user):
    """Return (last, first, middle_initial). Old accounts without the new fields are
    split from full_name (last word = last name)."""
    first = (user.get("first_name") or "").strip()
    mi = (user.get("middle_initial") or "").strip()
    last = (user.get("last_name") or "").strip()
    if not (first or last):
        words = (user.get("full_name") or "").split()
        if len(words) > 1:
            first, last = " ".join(words[:-1]), words[-1]
        else:
            first = " ".join(words)
    return last, first, mi


def clean_suffix(text):
    """Tidy a typed suffix: jr -> Jr., sr -> Sr., iii -> III."""
    t = (text or "").strip()
    key = t.rstrip(".").casefold()
    if key in ("jr", "sr"):
        return key.capitalize() + "."
    if key in ("ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"):
        return key.upper()
    return t


def normalize_link(text):
    """Return a clean http(s) link, "" if empty, or raise ValueError for something that isn't a web link."""
    t = (text or "").strip()
    if not t:
        return ""
    if " " in t:
        raise ValueError("A link cannot contain spaces. Paste just the web address.")
    if "://" not in t:
        t = "https://" + t
    parts = urlparse(t)
    if parts.scheme not in ("http", "https") or "." not in parts.netloc:
        raise ValueError("Please paste a web link that starts with http:// or https:// (for example a YouTube link).")
    return t


def validate_contact(text):
    """Account username must be a Gmail address (name@gmail.com) or a 12-digit phone number.
    Returns an error message, or "" when valid."""
    t = (text or "").strip()
    if not t:
        return "Please enter your Gmail address or phone number."
    if "@" in t:
        if re.fullmatch(r"[A-Za-z0-9._%+\-]+@gmail\.com", t, flags=re.IGNORECASE) is None:
            return "Email must be a valid Gmail address ending in @gmail.com (example: juan@gmail.com)."
        return ""
    if not t.isdigit():
        return "Enter a Gmail address ending in @gmail.com, or a 12-digit phone number (numbers only)."
    if len(t) != 12:
        return f"Phone number must be exactly 12 digits (you entered {len(t)})."
    return ""


def link_site(url):
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def subject_courses(row):
    """Courses a subject belongs to, e.g. ['BSIT', 'BSBA'] or ['ALL'] ([] for an old subject with no course)."""
    return [c for c in (row.get("course") or "").replace(";", ",").split(",") if c.strip()]


def course_label(row):
    cs = subject_courses(row)
    if ALL_COURSES in cs:
        return "All courses"
    return ", ".join(cs) if cs else "No course"


def section_course(section_name):
    """'BSIT 1A' -> 'BSIT'."""
    return (section_name or "").strip().split(" ")[0].upper()


def subject_fits_course(row, course):
    """A subject is offered to a course if it is tagged for it, tagged 'All courses', or has no course yet."""
    cs = subject_courses(row)
    return not cs or ALL_COURSES in cs or course in cs


def user_suffix(user):
    return (user.get("suffix") or "").strip()


def format_full_name(first, mi, last, suffix=""):
    """'Juan D. Dela Cruz Jr.'"""
    return " ".join(p for p in (first, f"{mi}." if mi else "", last, suffix) if p)


def format_sheet_name(user):
    """'Dela Cruz, Juan D. Jr.'"""
    last, first, mi = name_parts(user)
    given = " ".join(p for p in (first, f"{mi}." if mi else "", user_suffix(user)) if p)
    return f"{last}, {given}" if last and given else (last or given)


def copy_attachment(source, folder, prefix):
    if not source:
        return ""
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError("The selected file could not be found.")
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in source_path.name)
    destination = folder / f"{prefix}_{safe_name}"
    counter = 1
    while destination.exists():
        destination = folder / f"{prefix}_{counter}_{safe_name}"
        counter += 1
    shutil.copy2(source_path, destination)
    try:
        return destination.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:
        return str(destination.resolve())


def resolve_path(path):
    """Find a stored attachment path: relative to the data folder, or an old absolute path
    (falls back to the attachments/submissions folders if the project was moved)."""
    if not path:
        return ""
    p = Path(path)
    if p.is_absolute():
        if p.exists():
            return str(p)
        for folder in (FILES_DIR, SUBMISSIONS_DIR):
            alt = folder / p.name
            if alt.exists():
                return str(alt)
        return str(p)
    return str(DATA_DIR / p)


def open_path(path):
    path = resolve_path(path)
    if not path or not os.path.exists(path):
        return False, "The attached file/path is no longer available."
    try:
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True, "Opening file..."
    except Exception as exc:
        return False, str(exc)


_DIALOG_SCRIPT = r"""
import sys, json
import tkinter as tk
from tkinter import filedialog
mode = sys.argv[1]
opts = json.loads(sys.argv[2])
if "filetypes" in opts:
    opts["filetypes"] = [tuple(x) for x in opts["filetypes"]]
root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
fn = filedialog.askopenfilename if mode == "open" else filedialog.asksaveasfilename
result = fn(**opts)
root.destroy()
sys.stdout.buffer.write((result or "").encode("utf-8"))
"""


def native_file_dialog(mode, **opts):
    """Run Tk's native file dialog in a separate process (Tk can't run in Flet's threads)."""
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        res = subprocess.run(
            [sys.executable, "-c", _DIALOG_SCRIPT, mode, json.dumps(opts)],
            capture_output=True, env=env, timeout=600,
        )
        return res.stdout.decode("utf-8", errors="replace").strip()
    except Exception as exc:
        print("File dialog error:", repr(exc))
        return ""

def deadline_passed(activity):
    d = (activity.get("deadline") or "").strip()
    if not d:
        return False
    try:
        return datetime.now() > datetime.strptime(d, "%Y-%m-%d %H:%M")
    except ValueError:
        return False


def is_excused(score):
    return str(score).strip().upper() == "EXC"


def is_record_item(activity):
    return activity.get("source") == "record"


def is_date_item(activity):
    """An attendance column created in the record sheet (its title is the date)."""
    return (is_record_item(activity) and cat_of(activity) == "Attendance"
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", activity.get("title") or "") is not None)


def score_to_text(score, date_item, mark=""):
    """Stored score (+ late/make-up mark) -> what the record sheet shows."""
    if score == "" or score is None:
        return ""
    if is_excused(score):
        return "E" if date_item else "EXC"
    if date_item:
        try:
            v = float(score)
        except ValueError:
            return str(score)
        if v == 1:
            return "P"
        if v == 0:
            return "A"
        if abs(v - LATE_CREDIT) < 1e-9:
            return "L"
    return fmt(score) + (mark if mark in MARKS and not date_item else "")


def parse_entry(text, date_item, max_points):
    """What was typed -> (stored score, mark). Raises ValueError with a readable message."""
    t = (text or "").strip().upper()
    if not t:
        return "", ""
    if t in ("E", "EXC"):
        return "EXC", ""
    if date_item:
        codes = {"P": 1.0, "L": LATE_CREDIT, "A": 0.0}
        if t not in codes:
            raise ValueError(f"\"{text.strip()}\" is not valid. Use P, L, A or E.")
        return fmt(codes[t]), ""
    mark = ""
    if len(t) > 1 and t[-1] in MARKS:
        mark, t = t[-1], t[:-1].strip()
    try:
        v = float(t)
    except ValueError:
        raise ValueError(f"\"{text.strip()}\" is not a valid score (examples: 18, 18L = late, 18M = make-up, EXC).")
    if v < 0 or v > max_points:
        raise ValueError(f"scores must be from 0 to {fmt(max_points)}.")
    return fmt(v), mark


def mark_label(mark):
    return MARKS.get(mark or "", "")


_SESSION = {"user": None}


def log_events(entries):
    """entries: list of (kind, action, details, class_id[, student_id]). Written in one go.
    student_id is the student an entry is about (e.g. whose score was changed) so that the
    student can see it in their own activity log."""
    if not entries:
        return
    try:
        u = _SESSION["user"] or {}
        rows = read_rows("activity_log")
        nid = max([int(r["id"]) for r in rows if (r.get("id") or "").isdigit()] + [0]) + 1
        now = timestamp()
        for entry in entries:
            kind, action, details, class_id = entry[:4]
            student_id = entry[4] if len(entry) > 4 else ""
            rows.append({"id": str(nid), "time": now, "user_id": u.get("id", ""),
                         "user_name": u.get("full_name", ""), "role": u.get("role", ""), "kind": kind,
                         "action": action, "class_id": str(class_id or ""), "details": details,
                         "student_id": str(student_id or "")})
            nid += 1
        write_rows("activity_log", rows[-20000:])
    except Exception as exc:  # logging must never break the app
        print("Activity log error:", repr(exc))


def log_event(kind, action, details="", class_id="", student_id=""):
    log_events([(kind, action, details, class_id, student_id)])

_LOCAL_FAILS = {}  


def _parse_time(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def lock_minutes_left(until_text):
    until = _parse_time(until_text)
    if not until or until <= datetime.now():
        return 0
    return int((until - datetime.now()).total_seconds() // 60) + 1


def register_failed_login(user, typed_name):
    """Count a wrong password. Returns (locked_now, tries_left)."""
    if user:
        fails = int(user.get("failed_attempts") or 0) + 1
    else:
        fails = _LOCAL_FAILS.get(typed_name.casefold(), 0) + 1
    if fails >= MAX_FAILED_LOGINS:
        until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        if user:
            update_row("users", user["id"], {"failed_attempts": "0", "locked_until": until})
            user["failed_attempts"], user["locked_until"] = "0", until
        else:
            _LOCAL_FAILS[typed_name.casefold()] = 0
            _LOCAL_FAILS[("until", typed_name.casefold())] = until
        return True, 0
    if user:
        update_row("users", user["id"], {"failed_attempts": str(fails)})
    else:
        _LOCAL_FAILS[typed_name.casefold()] = fails
    return False, MAX_FAILED_LOGINS - fails


def remove_student_from_class(class_id, student_id):
    cid, sid = str(class_id), str(student_id)
    write_rows("enrollments", [e for e in read_rows("enrollments")
                               if not (e["class_id"] == cid and e["student_id"] == sid)])
    write_rows("submissions", [x for x in read_rows("submissions")
                               if not (x["class_id"] == cid and x["student_id"] == sid)])


def make_backup_zip(destination):
    ensure_storage()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(DATA_DIR.rglob("*")):
            if path.is_file() and not path.name.endswith(".tmp"):
                z.write(path, path.relative_to(DATA_DIR).as_posix())


def validate_backup(path):
    """Return a list of the files inside a StudyTrack backup, or raise ValueError."""
    if not zipfile.is_zipfile(path):
        raise ValueError("That file is not a ZIP backup.")
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if "users.csv" not in names:
            raise ValueError("This ZIP does not look like a StudyTrack backup (users.csv is missing).")
        for n in names:
            parts = Path(n).parts
            if n.startswith(("/", "\\")) or ".." in parts or ":" in n:
                raise ValueError("The backup contains unsafe file paths.")
            if len(parts) == 1:
                table = Path(n).stem
                if n.endswith(".csv") and table in TABLES:
                    with z.open(n) as f:
                        header = f.readline().decode("utf-8-sig").strip().split(",")
                    if "id" not in header or not set(header) <= set(TABLES[table]):
                        raise ValueError(f"{n} has an unexpected format.")
                elif n.endswith(".tmp"):
                    continue
                else:
                    raise ValueError(f"Unexpected file in the backup: {n}")
            elif parts[0] not in ("attachments", "submissions"):
                raise ValueError(f"Unexpected folder in the backup: {parts[0]}")
        return names


def restore_backup_zip(path):
    """Replace all data with the backup. The current data folder is kept as a safety copy."""
    names = validate_backup(path)
    ensure_storage()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    work = BASE_DIR / "studytrack_backups"
    work.mkdir(exist_ok=True)
    incoming = work / f"incoming_{stamp}"
    with zipfile.ZipFile(path) as z:
        for n in names:
            if n.endswith(".tmp"):
                continue
            target = incoming / n
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    safety = work / f"data_before_restore_{stamp}"
    shutil.move(str(DATA_DIR), str(safety))
    shutil.move(str(incoming), str(DATA_DIR))
    _READY["done"] = False
    ensure_storage()
    ensure_admin()
    ensure_school_years()
    return safety


def unread_announcements(user_id):
    """{class_id: [announcement ids]} the student has not opened yet."""
    reads = {r["class_id"]: r["seen_at"] for r in read_rows("reads") if r["user_id"] == user_id}
    anns = read_rows("announcements")
    archived = {c["id"] for c in read_rows("classes") if is_archived(c)}
    out = {}
    for e in read_rows("enrollments"):
        if e["student_id"] != user_id or e["class_id"] in archived:
            continue
        seen = reads.get(e["class_id"]) or e.get("joined_at") or ""
        new = [a["id"] for a in anns if a["class_id"] == e["class_id"] and (a["posted_at"] or "") > seen]
        if new:
            out[e["class_id"]] = new
    return out


def is_archived(c):
    return (c.get("archived") or "") == "1"


def mark_announcements_seen(user_id, class_id):
    row = next((r for r in read_rows("reads") if r["user_id"] == user_id and r["class_id"] == class_id), None)
    if row:
        update_row("reads", row["id"], {"seen_at": timestamp()})
    else:
        add_row("reads", {"id": next_id("reads"), "user_id": user_id, "class_id": class_id,
                          "seen_at": timestamp()})


def cat_of(activity):
    c = activity.get("category") or "Activity"
    return c if c in CATEGORIES else "Activity"


def activity_label(a):
    return a.get("label") or a.get("title") or "Activity"


def next_activity_number(class_id, category):
    nums = []
    for a in read_rows("activities"):
        if a["class_id"] == str(class_id) and (a.get("category") or "Activity") == category:
            try:
                nums.append(int(a.get("number") or 0))
            except ValueError:
                pass
    return max(nums, default=0) + 1


def term_activities(class_id, term):
    acts = [a for a in read_rows("activities")
            if a["class_id"] == str(class_id) and (a.get("term") or "Midterm") == term]

    def key(a):
        try:
            n = int(a.get("number") or 0)
        except ValueError:
            n = 0
        return (CATEGORIES.index(cat_of(a)), n, id_key(a))
    return sorted(acts, key=key)


def class_enrollments(class_id):
    users = {u["id"]: u for u in read_rows("users")}

    def key(e):
        u = users.get(e["student_id"]) or {"full_name": e["student_name"]}
        last, first, mi = name_parts(u)
        return (last.casefold(), first.casefold(), mi.casefold())

    return sorted((e for e in read_rows("enrollments") if e["class_id"] == str(class_id)), key=key)


def subs_index():
    return {(s["activity_id"], s["student_id"]): s for s in read_rows("submissions")}


def parse_weights(raw):
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    out = {}
    for k, v in data.items():
        try:
            if k in CATEGORIES:
                out[k] = float(v)
        except (TypeError, ValueError):
            pass
    return out


def get_settings(class_id):
    out = {"semester": SEMESTERS[0], "Midterm": {}, "Finals": {}, "midterm_share": 50.0}
    row = next((r for r in read_rows("grade_settings") if r["class_id"] == str(class_id)), None)
    if row:
        out["semester"] = row.get("semester") or SEMESTERS[0]
        out["Midterm"] = parse_weights(row.get("midterm_weights"))
        out["Finals"] = parse_weights(row.get("finals_weights"))
        try:
            out["midterm_share"] = float(row.get("midterm_share") or 50)
        except ValueError:
            pass
    return out


def get_absence_limit(class_id):
    row = next((r for r in read_rows("grade_settings") if r["class_id"] == str(class_id)), None)
    try:
        return max(0, int((row or {}).get("max_absences") or DEFAULT_ABSENCE_LIMIT))
    except ValueError:
        return DEFAULT_ABSENCE_LIMIT


def set_absence_limit(class_id, limit):
    row = next((r for r in read_rows("grade_settings") if r["class_id"] == str(class_id)), None)
    if row:
        update_row("grade_settings", row["id"], {"max_absences": limit})
    else:
        add_row("grade_settings", {"id": next_id("grade_settings"), "class_id": class_id, "max_absences": limit})


def save_settings(class_id, semester, term, weights, share=None):
    row = next((r for r in read_rows("grade_settings") if r["class_id"] == str(class_id)), None)
    key = "midterm_weights" if term == "Midterm" else "finals_weights"
    data = {"semester": semester, key: json.dumps(weights)}
    if share is not None:
        data["midterm_share"] = share
    if row:
        update_row("grade_settings", row["id"], data)
    else:
        data.update({"id": next_id("grade_settings"), "class_id": class_id})
        add_row("grade_settings", data)


def term_detail(acts, subs, student_id, weights):
    """Return (scores, per-category detail, final or None).

    Per category: TOT = points earned, TR = earned / total possible x 100
    (blank scores count as 0), WS = TR x category weight / 100.
    Final grade = sum of WS over the weighted categories.
    """
    has_acts = {cat_of(a) for a in acts}
    if weights:
        wmap = dict(weights)
    else:
        wmap = {c: 100.0 / len(has_acts) for c in has_acts} if has_acts else {}
    earned = {c: 0.0 for c in CATEGORIES}
    possible = {c: 0.0 for c in CATEGORIES}
    scores = []
    for a in acts:
        s = subs.get((a["id"], student_id))
        sc = s["score"] if s else ""
        scores.append(sc)
        cat = cat_of(a)
        if is_excused(sc):
            continue
        possible[cat] += float(a["max_points"])
        if sc != "":
            earned[cat] += float(sc)
    detail = {}
    for cat in CATEGORIES:
        tr = earned[cat] / possible[cat] * 100 if possible[cat] else None
        wt = wmap.get(cat, 0)
        detail[cat] = {"earned": earned[cat], "possible": possible[cat], "tr": tr,
                       "weight": wt, "ws": (tr or 0.0) * wt / 100}
    counted = [c for c in CATEGORIES if c in wmap]
    final = sum(detail[c]["ws"] for c in counted) if any(detail[c]["tr"] is not None for c in counted) else None
    return scores, detail, final


def term_result(acts, subs, student_id, weights):
    """Return (scores list, category percentages, weighted final or None)."""
    scores, detail, final = term_detail(acts, subs, student_id, weights)
    return scores, {c: detail[c]["tr"] for c in CATEGORIES}, final


def gwa_of(p):
    if p is None:
        return None
    for limit, g in ((97, "1.00"), (94, "1.25"), (91, "1.50"), (88, "1.75"), (85, "2.00"),
                     (82, "2.25"), (79, "2.50"), (76, "2.75"), (75, "3.00")):
        if p >= limit:
            return g
    return "5.00"


def status_of(final, missing):
    if final is None:
        return "Incomplete"
    if final < get_passing_grade():
        return "Incomplete" if missing else "Failed"
    return "Conditional" if missing else "Pass"


def build_sheet_grid(c, term, weights):
    """Grouped grade sheet: one band per category with its items + TOT / TR / WS."""
    acts = term_activities(c["id"], term)
    subs = subs_index()
    has_acts = {cat_of(a) for a in acts}
    cats = [cat for cat in CATEGORIES if (cat in weights if weights else cat in has_acts)]
    eq = 100.0 / len(cats) if cats else 0
    groups = []
    for cat in cats:
        wt = weights.get(cat, 0) if weights else eq
        groups.append({"cat": cat, "weight": wt, "acts": [a for a in acts if cat_of(a) == cat]})
    students = []
    users = {u["id"]: u for u in read_rows("users")}
    for e in class_enrollments(c["id"]):
        scores, detail, final = term_detail(acts, subs, e["student_id"], weights)
        by_act = {a["id"]: s for a, s in zip(acts, scores)}
        cells = []
        for g in groups:
            d = detail[g["cat"]]
            cells.append({
                "scores": [score_to_text(by_act[a["id"]], False,
                                         (subs.get((a["id"], e["student_id"])) or {}).get("mark", ""))
                           for a in g["acts"]],
                "tot": fmt(round(d["earned"], 2)),
                "tr": fmt(round(d["tr"], 1)) if d["tr"] is not None else "0",
                "ws": f"{d['ws']:.2f}",
            })
        u = users.get(e["student_id"]) or {"full_name": e["student_name"]}
        students.append({"name": format_sheet_name(u), "cells": cells,
                         "final": f"{final:.2f}" if final is not None else "—",
                         "gwa": gwa_of(final) or "—"})
    return {"groups": groups, "students": students}


def grid_to_table(grid):
    """Flatten a grid into header rows, body rows and reportlab SPAN commands."""
    groups = grid["groups"]
    ncols = 1 + sum(len(g["acts"]) + 3 for g in groups) + 2
    h0, h1, h2 = [[""] * ncols for _ in range(3)]
    h0[0] = "STUDENT NAME"
    spans = [("SPAN", (0, 0), (0, 2))]
    col = 1
    for g in groups:
        n = len(g["acts"])
        end = col + n + 2
        h0[col] = f"{g['cat'].upper()} ({fmt(round(g['weight'], 2))}%)"
        spans.append(("SPAN", (col, 0), (end, 0)))
        for i, a in enumerate(g["acts"]):
            h1[col + i] = activity_label(a).replace("Attendance", "Att").replace("Laboratory", "Lab") \
                .replace("Recitation", "Rec").replace("Activity", "Act").replace("Performance", "Perf")
            h2[col + i] = fmt(a["max_points"])
        h1[col + n] = "RESULT"
        spans.append(("SPAN", (col + n, 1), (end, 1)))
        h2[col + n], h2[col + n + 1], h2[col + n + 2] = "TOT", "TR", "WS"
        col = end + 1
    h0[col], h0[col + 1] = "FINAL GRADE", "GWA"
    spans += [("SPAN", (col, 0), (col, 2)), ("SPAN", (col + 1, 0), (col + 1, 2))]
    body = []
    for s in grid["students"]:
        row = [s["name"]]
        for cell in s["cells"]:
            row += cell["scores"] + [cell["tot"], cell["tr"], cell["ws"]]
        row += [s["final"], s["gwa"]]
        body.append(row)
    return {"header": [h0, h1, h2], "body": body, "spans": spans, "ncols": ncols}


def build_status_rows(c, term):
    settings = get_settings(c["id"])
    subs = subs_index()
    terms = TERMS if term == "Overall" else (term,)
    rows = []
    users = {u["id"]: u for u in read_rows("users")}
    for e in class_enrollments(c["id"]):
        finals, by_term, missing = [], {}, 0
        for t in terms:
            acts = term_activities(c["id"], t)
            scores, _pct, final = term_result(acts, subs, e["student_id"], settings[t])
            missing += sum(1 for s in scores if s == "")
            if final is not None:
                finals.append(final)
                by_term[t] = final
        if term == "Overall" and len(by_term) == 2:
            share = settings["midterm_share"] / 100.0
            final = by_term["Midterm"] * share + by_term["Finals"] * (1 - share)
        else:
            final = sum(finals) / len(finals) if finals else None
        rows.append((student_label(e, users), f"{final:.2f}%" if final is not None else "—",
                     gwa_of(final) or "—", status_of(final, missing)))
    return ["Student", "Weighted Grade (%)", "GWA", "Benchmark / Status"], rows


def student_label(e, users):
    u = users.get(e["student_id"]) or {"full_name": e["student_name"]}
    return format_sheet_name(u)


def build_attendance_rows(c, term, allowed):
    """Per student: days present / late / absent / excused, and a flag against the allowed absences."""
    terms = TERMS if term == "Overall" else (term,)
    items = [a for t in terms for a in term_activities(c["id"], t) if is_date_item(a)]
    subs = subs_index()
    users = {u["id"]: u for u in read_rows("users")}
    rows = []
    for e in class_enrollments(c["id"]):
        present = late = absent = excused = blank = 0
        for a in items:
            sc = (subs.get((a["id"], e["student_id"])) or {}).get("score", "")
            if sc == "":
                blank += 1
            elif is_excused(sc):
                excused += 1
            else:
                v = float(sc)
                if v >= 1:
                    present += 1
                elif v <= 0:
                    absent += 1
                else:
                    late += 1
        counted = present + late + absent
        pct = (present + late * LATE_CREDIT) / counted * 100 if counted else None
        if absent > allowed:
            flag = "OVER LIMIT"
        elif allowed and absent == allowed:
            flag = "At limit"
        else:
            flag = "OK"
        rows.append((student_label(e, users), len(items), present, late, absent, excused, blank,
                     f"{pct:.1f}%" if pct is not None else "—", flag))
    cols = ["Student", "Days", "Present", "Late", "Absent", "Excused", "Not recorded", "Attendance", "Status"]
    return cols, rows


def build_incomplete_rows(c):
    subs = subs_index()
    by_term = {t: term_activities(c["id"], t) for t in TERMS}
    rows = []
    users = {u["id"]: u for u in read_rows("users")}
    for e in class_enrollments(c["id"]):
        cells, any_missing = [], False
        for t in TERMS:
            miss = [activity_label(a) for a in by_term[t]
                    if (subs.get((a["id"], e["student_id"])) or {}).get("score", "") == ""]
            any_missing = any_missing or bool(miss)
            cells.append(", ".join(miss) if miss else "—")
        if any_missing:
            rows.append((student_label(e, users), cells[0], cells[1]))
    return ["Student", "Missing assessments — Midterm", "Missing assessments — Finals"], rows


def class_context(c, term=None):
    sem = get_settings(c["id"])["semester"]
    parts = [f"School Year: {c.get('school_year') or '—'}", sem]
    if term:
        parts.append(term)
    parts += [f"Section: {c['name']}", f"Subject: {c['subject']}"]
    return "   |   ".join(parts)


def export_report_pdf(destination, c, context, table_title, cols, rows, grid_table=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, legal, letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
    from xml.sax.saxutils import escape

    ncols_total = grid_table["ncols"] if grid_table else len(cols)
    pagesize = landscape(legal) if ncols_total > 7 else letter
    styles = getSampleStyleSheet()
    head = ParagraphStyle("head", parent=styles["Title"], fontSize=15, leading=18, spaceAfter=2, alignment=1)
    loc = ParagraphStyle("loc", parent=styles["Normal"], alignment=1, fontSize=10)
    ctx = ParagraphStyle("ctx", parent=styles["Normal"], alignment=1, fontSize=10, spaceBefore=10)
    ttl = ParagraphStyle("ttl", parent=styles["Heading2"], alignment=1, spaceBefore=10, spaceAfter=8)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    doc = SimpleDocTemplate(destination, pagesize=pagesize, rightMargin=.4 * inch, leftMargin=.4 * inch,
                            topMargin=.5 * inch, bottomMargin=.5 * inch, title=f"{c['name'] if c else 'StudyTrack'} {table_title}")
    story = []
    logo = resolve_path(get_setting("logo_path"))
    if logo and os.path.isfile(logo):
        try:
            from reportlab.lib.utils import ImageReader
            from reportlab.platypus import Image
            iw, ih = ImageReader(logo).getSize()
            height = .8 * inch
            story.append(Image(logo, width=height * iw / ih, height=height, hAlign="CENTER"))
            story.append(Spacer(1, 4))
        except Exception as exc:  # a bad logo file must not block the export
            print("Logo error:", repr(exc))
    story += [
        Paragraph(f"<b>{escape(get_setting('school_name'))}</b>", head),
        Paragraph(escape(get_setting("school_location")), loc),
    ]
    if get_setting("report_line3"):
        story.append(Paragraph(escape(get_setting("report_line3")), loc))
    story += [
        Paragraph(escape(context), ctx),
        Paragraph(f"<b>{escape(table_title)}</b>", ttl),
    ]
    usable = pagesize[0] - .8 * inch
    if grid_table:
        tiny = ParagraphStyle("tiny", parent=styles["Normal"], fontSize=6.5, leading=8)
        tinyc = ParagraphStyle("tinyc", parent=tiny, alignment=1)
        data = []
        for hi, hr in enumerate(grid_table["header"]):
            pre, post = ("<font color='white'><b>", "</b></font>") if hi == 0 else ("<b>", "</b>")
            data.append([Paragraph(f"{pre}{escape(str(v))}{post}", tinyc) if v != "" else "" for v in hr])
        for r in grid_table["body"]:
            data.append([Paragraph(escape(str(v)), tiny if i == 0 else tinyc) for i, v in enumerate(r)])
        first = 1.7 * inch
        rest = (usable - first) / max(1, ncols_total - 1)
        table = LongTable(data, colWidths=[first] + [rest] * (ncols_total - 1), repeatRows=3)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17243A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 1), (-1, 2), colors.HexColor("#E8EEFF")),
            ("GRID", (0, 0), (-1, -1), .35, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 3), (-1, -1), [colors.white, colors.HexColor("#F4F7FB")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ] + list(grid_table["spans"]) + [
            ("BACKGROUND", (0, 0), (0, 2), colors.HexColor("#17243A")),
            ("BACKGROUND", (ncols_total - 2, 0), (-1, 2), colors.HexColor("#17243A")),
        ]))
    else:
        data = [[Paragraph(f"<b>{escape(h)}</b>", small) for h in cols]]
        for r in rows:
            data.append([Paragraph(escape(str(v)), small) for v in r])
        first = 2.0 * inch
        rest = (usable - first) / max(1, len(cols) - 1)
        table = LongTable(data, colWidths=[first] + [rest] * (len(cols) - 1), repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEFF")),
            ("GRID", (0, 0), (-1, -1), .35, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7FB")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
    story += [table, Spacer(1, 14),
              Paragraph((f"Teacher: {escape(c['teacher_name'])} &nbsp;|&nbsp; " if c else "")
                        + f"Date generated: {timestamp()}", small)]

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(pagesize[0] - .4 * inch, .25 * inch, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def invite_link(code):
    return f"studytrack://join/{code}"


def invite_text(c):
    return (f"Join my class \"{c['name']} - {c['subject']}\" on StudyTrack.\n"
            f"Class code: {c['code']}\nInvite link: {invite_link(c['code'])}")


def extract_code(value):
    v = (value or "").strip()
    if "/" in v:
        v = v.rstrip("/").split("/")[-1]
    return v.upper()


def _first_attr(owner, name):
    return getattr(owner, name, None) if owner is not None else None


def _call_helper(class_name, module_name, method, *args, **kwargs):
    cls = getattr(ft, class_name, None)
    fn = _first_attr(cls, method)
    if callable(fn):
        return fn(*args, **kwargs)
    return getattr(getattr(ft, module_name), method)(*args, **kwargs)


def border_all(width, color):
    return _call_helper("Border", "border", "all", width, color)


def border_only(**kwargs):
    return _call_helper("Border", "border", "only", **kwargs)


def pad_sym(horizontal=0, vertical=0):
    return _call_helper("Padding", "padding", "symmetric", horizontal=horizontal, vertical=vertical)


def pad_only(**kwargs):
    return _call_helper("Padding", "padding", "only", **kwargs)


def margin_sym(horizontal=0, vertical=0):
    return _call_helper("Margin", "margin", "symmetric", horizontal=horizontal, vertical=vertical)


def margin_only(**kwargs):
    return _call_helper("Margin", "margin", "only", **kwargs)


def center_alignment():
    cls = getattr(ft, "Alignment", None)
    value = _first_attr(cls, "CENTER")
    return value if value is not None else ft.alignment.center


def open_control(page, control):
    if hasattr(page, "open"):
        page.open(control)
        return
    if hasattr(page, "show_dialog"):
        page.show_dialog(control)
        return
    if isinstance(control, ft.SnackBar):
        page.snack_bar = control
        control.open = True
    else:
        page.dialog = control
        control.open = True
    page.update()


def close_control(page, control):
    if hasattr(page, "close"):
        page.close(control)
        return
    if hasattr(page, "pop_dialog"):
        page.pop_dialog()
        return
    control.open = False
    if getattr(page, "dialog", None) is control:
        page.dialog = None
    page.update()


def compatible_button(content, on_click, icon=None, style=None, **kwargs):
    if hasattr(ft, "ElevatedButton"):
        try:
            return ft.ElevatedButton(text=content, on_click=on_click, icon=icon, style=style, **kwargs)
        except TypeError:
            pass
    if hasattr(ft, "Button"):
        return ft.Button(content=content, on_click=on_click, icon=icon, style=style, **kwargs)
    return ft.ElevatedButton(content=ft.Text(content), on_click=on_click, icon=icon, style=style, **kwargs)


# ---------------------------------------------------------------------------
# Welcome / landing page artwork
# The artwork is written as small SVG files (shapes only, no text) the first time the app runs.
# To use official logos instead, drop PNG/SVG files with these names into studytrack_data/landing/:
#   studytrack_logo  (e.g. studytrack_logo.png)
# ---------------------------------------------------------------------------
LANDING_DIR = DATA_DIR / "landing"

LANDING_SVG = {
    "waves": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E3EEFF"/><stop offset="0.55" stop-color="#F4F8FF"/><stop offset="1" stop-color="#FFFFFF"/></linearGradient>
<linearGradient id="w1" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5B8DF7"/><stop offset="1" stop-color="#2F5BD6"/></linearGradient>
<linearGradient id="w2" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#9DBDFB"/><stop offset="1" stop-color="#6F9AF4"/></linearGradient>
</defs>
<rect width="1440" height="900" fill="url(#bg)"/>
<path d="M0 0 H520 C430 40 360 120 270 150 C170 185 80 150 0 230 Z" fill="url(#w2)" opacity="0.55"/>
<path d="M0 0 H330 C270 30 220 90 150 105 C80 120 40 100 0 140 Z" fill="url(#w1)" opacity="0.85"/>
<path d="M1440 0 V210 C1370 150 1290 110 1230 70 C1190 45 1170 15 1160 0 Z" fill="url(#w2)" opacity="0.45"/>
<path d="M0 900 V660 C90 600 190 640 290 700 C400 765 480 790 600 760 C720 730 800 790 900 840 C960 870 1010 890 1060 900 Z" fill="url(#w2)" opacity="0.5"/>
<path d="M0 900 V760 C80 720 170 745 260 800 C340 850 420 860 500 900 Z" fill="url(#w1)" opacity="0.9"/>
<path d="M1440 900 V470 C1370 500 1330 560 1290 640 C1240 740 1160 790 1050 800 C1000 805 960 850 930 900 Z" fill="url(#w2)" opacity="0.55"/>
<path d="M1440 900 V640 C1390 670 1360 730 1320 790 C1280 850 1220 880 1160 900 Z" fill="url(#w1)" opacity="0.9"/>
<circle cx="1330" cy="210" r="6" fill="#9DBDFB" opacity="0.6"/>
<circle cx="150" cy="520" r="9" fill="#9DBDFB" opacity="0.35"/>
<circle cx="1210" cy="400" r="4" fill="#5B8DF7" opacity="0.4"/>
</svg>""",
    "studytrack_logo": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5B8DF7"/><stop offset="1" stop-color="#2848C2"/></linearGradient></defs>
<rect width="200" height="200" rx="48" fill="url(#g)"/>
<path d="M100 70 C85 58 62 56 44 62 L44 138 C62 132 85 134 100 146 Z" fill="#FFFFFF"/>
<path d="M100 70 C115 58 138 56 156 62 L156 138 C138 132 115 134 100 146 Z" fill="#EAF1FF"/>
<path d="M58 86 H86 M58 102 H86 M58 118 H76" stroke="#B9CDFB" stroke-width="6" stroke-linecap="round" fill="none"/>
<path d="M117 100 L128 111 L147 86" stroke="#2F5BD6" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
<path d="M100 70 V146" stroke="#C7D8FC" stroke-width="2" fill="none"/>
</svg>""",
}


def landing_asset(name):
    """Absolute path of a landing-page image (custom PNG/SVG if provided, else the built-in SVG)."""
    try:
        LANDING_DIR.mkdir(parents=True, exist_ok=True)
        for ext in (".png", ".jpg", ".jpeg", ".svg"):
            custom = LANDING_DIR / f"{name}{ext}"
            if custom.exists():
                return str(custom)
        path = LANDING_DIR / f"{name}.svg"
        path.write_text(LANDING_SVG[name], encoding="utf-8")
        return str(path)
    except OSError:
        return ""


def image_fit(kind):
    """ft.ImageFit (older Flet) or ft.BoxFit (newer Flet): 'COVER' or 'CONTAIN'."""
    for owner in ("ImageFit", "BoxFit"):
        value = getattr(getattr(ft, owner, None), kind, None)
        if value is not None:
            return value
    return None


def landing_image(name, **kwargs):
    path = landing_asset(name)
    if not path:
        return ft.Container(**{k: v for k, v in kwargs.items() if k in ("width", "height", "expand")})
    fit = kwargs.pop("fit", None)
    if fit is not None:
        kwargs["fit"] = fit
    return ft.Image(src=path, **kwargs)



DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"


def ensure_admin():
    users = read_rows("users")
    if any(u["role"] == "admin" for u in users):
        return
    username = DEFAULT_ADMIN_USER
    taken = {u["username"].casefold() for u in users}
    while username.casefold() in taken:
        username += "_"
    add_row("users", {
        "id": next_id("users"), "username": username,
        "password_hash": hash_password(DEFAULT_ADMIN_PASSWORD),
        "role": "admin", "full_name": "Administrator",
    })


def ensure_school_years():
    """First run after this update: build the School Year list from the old sections / classes,
    and merge sections that only differed by school year."""
    sections = read_rows("sections")
    years = read_rows("school_years")
    if not years:
        names = {(s.get("school_year") or "").strip() for s in sections}
        names |= {(c.get("school_year") or "").strip() for c in read_rows("classes")}
        names.discard("")
        for i, n in enumerate(sorted(names), start=1):
            years.append({"id": str(i), "name": n, "active": "1", "created_at": timestamp()})
        if years:
            write_rows("school_years", years)
    seen, kept, changed = {}, [], False
    for s in sorted(sections, key=id_key):
        key = s["name"].casefold()
        if key in seen:
            changed = True
            if s.get("active") != "0":
                seen[key]["active"] = "1"
            continue
        if s.get("school_year"):
            s["school_year"] = ""
            changed = True
        seen[key] = s
        kept.append(s)
    if changed:
        write_rows("sections", kept)


def _student_counts():
    counts = {}
    for e in read_rows("enrollments"):
        counts[e["class_id"]] = counts.get(e["class_id"], 0) + 1
    return counts


def _report_classes(year="all", section="all", active_only=False):
    out = []
    for c in read_rows("classes"):
        if year != "all" and (c.get("school_year") or "") != year:
            continue
        if section != "all" and c["name"] != section:
            continue
        if active_only and is_archived(c):
            continue
        out.append(c)
    return out


def build_year_report(year="all"):
    """School year -> how many sections (and classes / students) it has."""
    counts = _student_counts()
    classes = read_rows("classes")
    rows = []
    for y in sorted(read_rows("school_years"), key=lambda r: r["name"], reverse=True):
        if year != "all" and y["name"] != year:
            continue
        cs = [c for c in classes if (c.get("school_year") or "") == y["name"]]
        rows.append((y["name"], "Active" if y.get("active") != "0" else "Inactive",
                     len({c["name"] for c in cs}), len(cs), sum(counts.get(c["id"], 0) for c in cs)))
    return ["School year", "Status", "Sections", "Classes", "Students enrolled"], rows


def build_section_report(year="all"):
    """Section -> how many subjects it has."""
    counts = _student_counts()
    rows = []
    for s in sorted(read_rows("sections"), key=lambda r: r["name"].casefold()):
        cs = _report_classes(year, s["name"])
        rows.append((s["name"], "Active" if s.get("active") != "0" else "Inactive",
                     len({c["subject"] for c in cs}), len(cs), sum(counts.get(c["id"], 0) for c in cs)))
    return ["Section", "Status", "Subjects", "Classes", "Students enrolled"], rows


def build_subject_report(year="all", section="all"):
    """Subject (inside a section) -> how many students are enrolled."""
    counts = _student_counts()
    groups = {}
    for c in _report_classes(year, section):
        g = groups.setdefault((c["name"], c["subject"]), {"classes": 0, "students": 0, "teachers": set()})
        g["classes"] += 1
        g["students"] += counts.get(c["id"], 0)
        g["teachers"].add(c["teacher_name"])
    rows = [(sec, sub, ", ".join(sorted(g["teachers"])), g["classes"], g["students"])
            for (sec, sub), g in sorted(groups.items(), key=lambda kv: (kv[0][0].casefold(), kv[0][1].casefold()))]
    return ["Section", "Subject", "Teacher", "Classes", "Students enrolled"], rows


def build_active_class_report(year="all", section="all"):
    """Every active class: its section's subject count and the students enrolled in it."""
    counts = _student_counts()
    cs = _report_classes(year, section, active_only=True)
    subjects_in = {}
    for c in cs:
        subjects_in.setdefault((c.get("school_year") or "", c["name"]), set()).add(c["subject"])
    cs.sort(key=lambda c: (c["name"].casefold(), c["subject"].casefold()))
    cs.sort(key=lambda c: c.get("school_year") or "", reverse=True)
    rows = [(c.get("school_year") or "—", c["name"], c["subject"], c["teacher_name"], counts.get(c["id"], 0))
            for c in cs]
    return ["School year", "Section", "Subject", "Teacher", "Students enrolled"], rows


def main(page: ft.Page):
    ensure_storage()
    ensure_admin()
    ensure_school_years()
    page.title = "StudyTrack | Student Academic Task and Progress Monitoring System"
    page.padding = 0
    try:
        page.window.width = 1180
        page.window.height = 780
        page.window.min_width = 900
        page.window.min_height = 620
    except Exception:
        pass
    def apply_theme():
        page.theme_mode = ft.ThemeMode.DARK if DARK["on"] else ft.ThemeMode.LIGHT
        page.bgcolor = C("#F4F7FB")
        page.theme = ft.Theme(
            color_scheme=ft.ColorScheme(primary=C("#3157D5"), secondary=C("#14B8A6"), surface=C("#FFFFFF")),
            use_material3=True,
        )

    apply_theme()

    state = {"user": None, "class": None, "view": "welcome", "term": "Midterm"}

    def toast(message, error=False):
        """Card-style notification: icon + title + message, slides up at the bottom of the content area
        (clear of the sidebar and its Log out button), hides itself, and can be dismissed with the X."""
        import threading
        import time as _time
        message = str(message)
        accent = C("#B42318", True) if error else C("#0D9488", True)
        tint = C("#FEE4E2") if error else C("#E8F8F4")
        sidebar_w = (76 if state.get("sidebar_collapsed") else 235) if state.get("user") else 0
        room = (page.width or 1180) - sidebar_w - 80
        longest = max((len(x) for x in message.split("\n")), default=0)
        box_w = max(260, min(longest * 6.8 + 126, 560, max(room, 260)))
        t = state.setdefault("toast", {"token": 0, "holder": None})
        t["token"] += 1
        mine = t["token"]
        holder = t["holder"]
        if holder is None:
            holder = ft.Container(
                visible=False, opacity=0, offset=ft.Offset(0, 0.25), left=0, right=0, bottom=24,
                animate_opacity=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
                animate_offset=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            )
            t["holder"] = holder

        def dismiss():
            try:
                if t["token"] != mine:
                    return
                holder.opacity, holder.offset = 0, ft.Offset(0, 0.25)
                page.update()
                _time.sleep(0.22)
                if t["token"] == mine:
                    holder.visible = False
                    page.update()
            except Exception:
                pass   # the page changed meanwhile

        def close(_=None):
            threading.Thread(target=dismiss, daemon=True).start()

        def auto_hide():
            _time.sleep(5.0 if error else 3.5)
            dismiss()

        box = ft.Container(
            content=ft.Row([
                ft.Container(content=ft.Icon(ft.Icons.ERROR_OUTLINE if error else ft.Icons.CHECK_CIRCLE_OUTLINE,
                                             size=20, color=accent),
                             width=36, height=36, border_radius=18, bgcolor=tint, alignment=center_alignment()),
                ft.Column([
                    ft.Text("Please check this" if error else "Done", size=13, weight=ft.FontWeight.BOLD,
                            color=C("#18243A")),
                    ft.Text(message, size=12, color=C("#526078")),
                ], spacing=2, expand=True),
                ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, icon_color=C("#748198"),
                              tooltip="Dismiss", on_click=close),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            width=box_w, padding=pad_sym(14, 10), bgcolor=C("#FFFFFF"), border_radius=14,
            border=border_all(1.5, accent),
            shadow=ft.BoxShadow(blur_radius=24, color="#40000000", offset=ft.Offset(0, 8)),
        )
        holder.content = ft.Row([box], alignment=ft.MainAxisAlignment.CENTER)
        holder.left = sidebar_w
        # keep the toast above everything else (including an open dialog): move it to the end of the overlay
        if holder in page.overlay:
            page.overlay.remove(holder)
        page.overlay.append(holder)
        if not holder.visible:
            holder.opacity, holder.offset, holder.visible = 0, ft.Offset(0, 0.25), True
            page.update()
            _time.sleep(0.03)
        holder.opacity, holder.offset = 1, ft.Offset(0, 0)
        page.update()
        threading.Thread(target=auto_hide, daemon=True).start()

    def text_field(label, password=False, width=None, hint=None, multiline=False, value=""):
        return ft.TextField(
            label=label, password=password, can_reveal_password=password,
            width=width, hint_text=hint, multiline=multiline, min_lines=3 if multiline else 1,
            value=value, border_radius=12, filled=True, bgcolor=C("#FFFFFF"),
            border_color=C("#DCE3EF"), focused_border_color=C("#3157D5"),
        )

    def button(label, on_click, icon=None, primary=False):
        return compatible_button(
            content=label, on_click=on_click, icon=icon,
            style=ft.ButtonStyle(
                bgcolor=C("#3157D5") if primary else C("#FFFFFF"),
                color="#FFFFFF" if primary else C("#24324A"),
                side=None if primary else ft.BorderSide(1, C("#DCE3EF")),
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=pad_sym(18, 12),
            ),
        )

    def fill_button(label, on_click, icon=None, primary=False):
        """Same look as button() but stretches to share the row evenly (no empty space on the right)."""
        return compatible_button(
            content=label, on_click=on_click, icon=icon, expand=True,
            style=ft.ButtonStyle(
                bgcolor=C("#3157D5") if primary else C("#FFFFFF"),
                color="#FFFFFF" if primary else C("#24324A"),
                side=None if primary else ft.BorderSide(1, C("#DCE3EF")),
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=pad_sym(12, 14),
            ),
        )

    def card(content_control, padding=20, expand=False):
        box = ft.Container(
            content=content_control, padding=padding, expand=expand,
            bgcolor=C("#FFFFFF"), border=border_all(1, C("#E7ECF4")), border_radius=18,
        )
        if expand:
            return ft.Row([box], expand=True, vertical_alignment=ft.CrossAxisAlignment.START)
        return box

    def section_title(title, subtitle=None):
        items = [ft.Text(title, size=25, weight=ft.FontWeight.BOLD, color=C("#18243A"))]
        if subtitle:
            items.append(ft.Text(subtitle, size=13, color=C("#6B7890")))
        return ft.Column(items, spacing=4)

    def close_dialog(dlg):
        close_control(page, dlg)
        page.update()

    def show_dialog(title, body, actions=None, width=600):
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text(title, weight=ft.FontWeight.BOLD),
            content=ft.Container(content=body, width=width),
            actions=actions or [ft.TextButton("Close", on_click=lambda e: close_dialog(dlg))],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=18),
        )
        open_control(page, dlg)
        page.update()
        return dlg

    def ask_confirm(title, message, on_yes, on_no=None):
        def yes(_):
            close_dialog(dlg)
            on_yes()

        def no(_):
            close_dialog(dlg)
            if on_no:
                on_no()

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text(title, weight=ft.FontWeight.BOLD),
            content=ft.Container(content=ft.Text(message, size=13), width=440),   # keep the dialog compact
            actions=[ft.TextButton("Cancel", on_click=no), compatible_button("Confirm", on_click=yes)],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=18),
        )
        open_control(page, dlg)
        page.update()

    def copy_text(value, message):
        try:
            page.set_clipboard(value)
            toast(message)
        except Exception as exc:
            toast(f"Could not copy: {exc}", True)

    def table_view(columns, rows, fill=True, cell_builder=None):
        """Full-width table: every column gets a share of the width that matches how much text it holds,
        so no space is left empty on the right and short words (Teacher, dates) do not wrap.
        cell_builder(col_index, col_name, row, value) may return a control for special cells (e.g. buttons)."""
        rows = [tuple(r) for r in rows]
        weights = []
        for i, col in enumerate(columns):
            longest = max([len(str(r[i])) for r in rows if i < len(r)] + [0])
            chars = max(len(col) + 2, min(longest, 40), 4)
            weights.append(chars * 7 + 16)     # roughly the pixels the text needs, so extra space is shared fairly

        def cells(values, header=False, row=None):
            out = []
            for i, col in enumerate(columns):
                v = values[i] if i < len(values) else ""
                if header:
                    ctl = ft.Text(col, weight=ft.FontWeight.BOLD, size=12)
                else:
                    ctl = cell_builder(i, col, row, v) if cell_builder else None
                    if ctl is None:
                        ctl = ft.Text(str(v), size=12, selectable=True)
                out.append(ft.Container(content=ctl, expand=weights[i]))
            return ft.Row(out, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        header = ft.Container(content=cells(columns, header=True), padding=pad_sym(16, 14),
                              border=border_only(bottom=ft.BorderSide(1, C("#E7ECF4"))))
        body_rows = [ft.Container(content=cells(r, row=r), padding=pad_sym(16, 10),
                                  border=border_only(bottom=ft.BorderSide(1, C("#EEF2F8"))))
                     for r in rows]
        table = ft.Container(
            content=ft.Column([header] + body_rows, spacing=0, tight=True,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            border=border_all(1, C("#E7ECF4")), border_radius=12,
            clip_behavior=ft.ClipBehavior.HARD_EDGE)
        # the table is only as tall as its rows (no empty box underneath); the page scrolls if it is long
        return ft.Column([table], scroll=ft.ScrollMode.AUTO, expand=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def empty_card(icon, title, text):
        box = card(ft.Column([
            ft.Icon(icon, size=30, color=C("#9AA5B5")),
            ft.Text(title, weight=ft.FontWeight.BOLD, color=C("#344054")),
            ft.Text(text, size=12, color=C("#748198")),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8), padding=26)
        box.expand = True   # stretch across the full width
        return ft.Row([box], vertical_alignment=ft.CrossAxisAlignment.START)

    def shell(title, subtitle, body, nav_key="dashboard"):
        state["unsaved"] = None
        user = state["user"]
        role = user["role"]
        nav_items = [("dashboard", "Dashboard", ft.Icons.DASHBOARD_OUTLINED)]
        if role == "admin":
            nav_items += [
                ("school_years", "School years", ft.Icons.CALENDAR_MONTH_OUTLINED),
                ("courses", "Courses", ft.Icons.WORKSPACES_OUTLINED),
                ("sections", "Class sections", ft.Icons.GROUPS_OUTLINED),
                ("subjects", "Class subjects", ft.Icons.MENU_BOOK_OUTLINED),
                ("users", "Manage users", ft.Icons.ALTERNATE_EMAIL),
                ("admin_reports", "Reports", ft.Icons.SUMMARIZE_OUTLINED),
                ("school_settings", "School settings", ft.Icons.SETTINGS_OUTLINED),
                ("log", "Activity log", ft.Icons.HISTORY),
            ]
        elif role == "teacher":
            nav_items += [
                ("classes", "My classes", ft.Icons.SCHOOL_OUTLINED),
                ("records", "Record sheet", ft.Icons.EDIT_NOTE),
                ("grade_settings", "Grade settings", ft.Icons.TUNE),
                ("grades", "Grade sheet", ft.Icons.ASSESSMENT_OUTLINED),
                ("reports", "Reports", ft.Icons.SUMMARIZE_OUTLINED),
                ("log", "Activity log", ft.Icons.HISTORY),
            ]
        else:
            nav_items += [
                ("classes", "My classes", ft.Icons.SCHOOL_OUTLINED),
                ("scores", "My scores", ft.Icons.QUERY_STATS_OUTLINED),
                ("log", "Activity log", ft.Icons.HISTORY),
            ]

        unread_total = (sum(len(v) for v in unread_announcements(user["id"]).values())
                        if role == "student" else 0)

        def nav_click(key):
            check = state.get("unsaved")
            if check and check():
                ask_confirm("Unsaved changes", "You have scores that are not saved yet. Leave without saving?",
                            lambda: nav_go(key))
                return
            nav_go(key)

        def nav_go(key):
            if key == "dashboard":
                dashboard()
            elif key == "classes":
                teacher_classes() if role == "teacher" else student_classes()
            elif key == "records":
                record_sheet_view()
            elif key == "grades":
                choose_grade_class()
            elif key == "reports":
                reports_view()
            elif key == "scores":
                student_score_view()
            elif key == "grade_settings":
                grade_settings_view()
            elif key == "school_years":
                admin_manage_view("school_years")
            elif key == "admin_reports":
                admin_reports_view()
            elif key == "school_settings":
                school_settings_view()
            elif key == "courses":
                courses_view()
            elif key == "sections":
                admin_manage_view("sections")
            elif key == "subjects":
                admin_manage_view("subjects")
            elif key == "users":
                admin_users_view()
            elif key == "log":
                activity_log_view()

        def toggle_theme(_=None):
            def go():
                DARK["on"] = not DARK["on"]
                value = "dark" if DARK["on"] else "light"
                update_row("users", user["id"], {"theme": value})
                user["theme"] = value
                apply_theme()
                nav_go(nav_key)
            check = state.get("unsaved")
            if check and check():
                ask_confirm("Unsaved changes", "You have scores that are not saved yet. Switch theme and discard them?",
                            go)
            else:
                go()

        import threading
        import time as _time
        SB_FULL, SB_MINI = 235, 76            # expanded / collapsed sidebar width
        HDR_H, ITEM_H, FOOT_H, PROF_H = 92, 44, 48, 64   # fixed heights used in collapsed mode (tooltip alignment)
        TIP_W, TIP_H = 304, 96

        if state.get("sidebar_collapsed") is None:
            state["sidebar_collapsed"] = (page.width or 1200) < 820   # small windows start collapsed

        def is_collapsed():
            return bool(state.get("sidebar_collapsed"))

        # ---- what each menu does (shown in the floating cards while the sidebar is collapsed) ----
        role_desc = {
            "dashboard": {
                "admin": "Overview of teachers, students, classes, school years, sections and subjects, with admin shortcuts.",
                "teacher": "See your classes, students, activities and submissions at a glance, with quick actions.",
                "student": "See your joined classes, assigned activities and graded work, and join a class with a code.",
            },
            "classes": {
                "teacher": "Create classes, share class codes, and open a class to post announcements and manage work.",
                "student": "View your enrolled classes, join a new one with a code, and open announcements and activities.",
            },
            "log": {
                "admin": "See who changed what and when across teachers, students and the admin.",
                "teacher": "Review score changes and activity in your classes, with date and time filters.",
                "student": "Check your logins, class activity, submissions and score updates by date or time.",
            },
        }
        plain_desc = {
            "school_years": "Add, edit and activate the school years teachers can pick when creating a class.",
            "courses": "Add courses / programs the school offers, like BSIT or BSBA, and set them active or inactive.",
            "sections": "Manage class sections like BSIT 1A. Inactive sections are hidden from teachers.",
            "subjects": "Manage subjects by course. Teachers only see the subjects of their section's course.",
            "users": "Approve teacher accounts, edit names, unlock logins and set accounts active or inactive.",
            "admin_reports": "School year, section, subject and active class reports with student counts. Export to PDF.",
            "school_settings": "Set the report heading and logo and the passing grade.",
            "records": "Enter attendance and scores per category and term in a spreadsheet-style record sheet.",
            "grade_settings": "Set category weights, semester, midterm share and allowed absences for each class.",
            "grades": "Open a class's digital grade sheet with weighted grades and GWA. Export to PDF or CSV.",
            "reports": "Grade status, incomplete work and attendance summary per class. Export to PDF.",
            "scores": "Check your recorded scores, maximum points and grading status for each class activity.",
        }

        def describe(key):
            by_role = role_desc.get(key)
            return by_role[role] if by_role else plain_desc.get(key, "")

        entries = {}
        for i, (key, label, icon) in enumerate(nav_items):
            entries[key] = {"title": label, "desc": describe(key), "icon": icon,
                            "action": lambda k=key: nav_click(k), "center_top": 123 + 50 * i}
        entries["__theme"] = {
            "title": "Light mode" if DARK["on"] else "Dark mode",
            "desc": "Switch to the light appearance. Your choice is saved to your account." if DARK["on"]
                    else "Switch to the dark appearance. Your choice is saved to your account.",
            "icon": ft.Icons.LIGHT_MODE if DARK["on"] else ft.Icons.DARK_MODE,
            "action": toggle_theme, "center_bottom": 140}
        entries["__profile"] = {
            "title": user["full_name"], "desc": f"{role.title()} account. Edit your name or change your password.",
            "icon": ft.Icons.PERSON_OUTLINE, "action": profile_dialog, "center_bottom": 82}
        entries["__logout"] = {
            "title": "Log out", "desc": "Sign out of StudyTrack. You will be asked to confirm first.",
            "icon": ft.Icons.LOGOUT,
            "action": lambda: ask_confirm("Log out", "Do you want to log out of StudyTrack?", logout),
            "center_bottom": 24}

        # ---- floating tooltip card ----
        tip_state = {"key": None, "token": 0}

        def tip_gradient():
            try:
                begin, end = ft.Alignment(-1, -1), ft.Alignment(1, 1)
            except Exception:
                begin, end = ft.alignment.top_left, ft.alignment.bottom_right
            return ft.LinearGradient(begin=begin, end=end, colors=["#3157D5", "#7C3AED", "#17243A"])

        def build_tip(entry, shift):
            def go(_=None):
                hide_now()
                entry["action"]()

            card_box = ft.Container(
                content=ft.Row([
                    ft.Container(content=ft.Icon(entry["icon"], size=22, color="#FFFFFF"), width=40, height=40,
                                 border_radius=12, bgcolor="#26FFFFFF", alignment=center_alignment()),
                    ft.Column([
                        ft.Text(entry["title"], size=14, weight=ft.FontWeight.BOLD, color="#FFFFFF",
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(entry["desc"], size=11, color="#DCE6FF", max_lines=3,
                                overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                left=12, top=0, width=TIP_W - 12, height=TIP_H, padding=14, border_radius=16,
                gradient=tip_gradient(), on_click=go, on_hover=tip_hover,
                shadow=ft.BoxShadow(blur_radius=24, color="#59000000", offset=ft.Offset(0, 8)),
            )
            pointer = ft.Container(width=14, height=14, left=5, top=TIP_H / 2 - 7 + shift, rotate=0.785398,
                                   bgcolor="#3157D5", border_radius=3)
            return ft.Stack([pointer, card_box], width=TIP_W, height=TIP_H)

        def tip_hover(e):
            if str(e.data).lower() == "true":
                tip_state["token"] += 1          # cursor is on the card: cancel any pending hide
            else:
                hide_tip(0.25)

        tip = ft.Container(
            visible=False, opacity=0, offset=ft.Offset(-0.08, 0), width=TIP_W, height=TIP_H,
            left=SB_MINI - 2, top=0,
            animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
            animate_offset=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        )

        def show_tip(key):
            entry = entries[key]
            tip_state["token"] += 1
            tip_state["key"] = key
            shift = 0
            if "center_top" in entry:
                tip.top, tip.bottom = max(8, entry["center_top"] - TIP_H / 2), None
            else:
                bottom = entry["center_bottom"] - TIP_H / 2
                if bottom < 8:
                    shift, bottom = 8 - bottom, 8
                tip.top, tip.bottom = None, bottom
            tip.content = build_tip(entry, shift)
            tip.left = (SB_MINI if is_collapsed() else SB_FULL) - 2
            if not tip.visible:
                tip.opacity, tip.offset, tip.visible = 0, ft.Offset(-0.08, 0), True
                page.update()
                _time.sleep(0.03)
            tip.opacity, tip.offset = 1, ft.Offset(0, 0)
            page.update()

        def hide_tip(delay=0.0):
            tip_state["token"] += 1
            mine = tip_state["token"]

            def run():
                try:
                    if delay:
                        _time.sleep(delay)
                    if tip_state["token"] != mine or not tip.visible:
                        return
                    tip.opacity, tip.offset = 0, ft.Offset(-0.08, 0)
                    page.update()
                    _time.sleep(0.2)
                    if tip_state["token"] == mine:
                        tip.visible = False
                        tip_state["key"] = None
                        page.update()
                except Exception:
                    pass   # the page changed while fading: nothing to do
            threading.Thread(target=run, daemon=True).start()

        def hide_now():
            tip_state["token"] += 1
            tip_state["key"] = None
            tip.visible, tip.opacity = False, 0

        def icon_hover(key, e):
            state["hover_seen"] = True           # a mouse is present, so taps are not "first tap shows the card"
            if not is_collapsed():
                return
            if str(e.data).lower() == "true":
                show_tip(key)
            else:
                hide_tip(0.3)

        def item_click(key):
            entry = entries[key]
            if is_collapsed() and not state.get("hover_seen"):
                # touch screen: the first tap reveals the description, a second tap (or tapping the card) opens it
                if not (tip.visible and tip_state["key"] == key):
                    show_tip(key)
                    hide_tip(3.5)
                    return
            hide_now()
            entry["action"]()

        # ---- sidebar content (expanded = original look, collapsed = icons only) ----
        def build_nav():
            mini = is_collapsed()
            logo = ft.Container(content=ft.Icon(ft.Icons.AUTO_STORIES_ROUNDED, color="#FFFFFF", size=25),
                                bgcolor=C("#3157D5"), padding=10, border_radius=12)
            if mini:
                head = ft.Container(content=logo, width=SB_MINI, height=HDR_H, alignment=center_alignment())
            else:
                head = ft.Container(
                    content=ft.Row([
                        logo,
                        ft.Column([
                            ft.Text("StudyTrack", size=19, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                            ft.Text("CLASSROOM", size=9, color=C("#9FB4E8"), weight=ft.FontWeight.BOLD),
                        ], spacing=1),
                    ], spacing=10),
                    padding=pad_only(left=20, top=22, bottom=24),
                )
            controls = [head, ft.Container(height=1, bgcolor=C("#293954"), margin=margin_sym(16, 0))]
            for key, label, icon in nav_items:
                selected = key == nav_key
                color = "#FFFFFF" if selected else C("#A9B7CC")
                if mini:
                    glyph = ft.Icon(icon, size=19, color=color)
                    if key == "classes" and unread_total:
                        glyph = ft.Stack([ft.Container(content=glyph, left=2, top=2),
                                          ft.Container(width=9, height=9, border_radius=5,
                                                       bgcolor=C("#E5484D"), right=0, top=0)],
                                         width=24, height=24)
                    controls.append(ft.Container(
                        content=glyph, alignment=center_alignment(), width=SB_MINI - 24, height=ITEM_H,
                        bgcolor=C("#3157D5") if selected else None, border_radius=10,
                        margin=margin_only(left=12, right=12, top=4),
                        on_click=lambda e, k=key: item_click(k), on_hover=lambda e, k=key: icon_hover(k, e),
                        ink=True,
                    ))
                else:
                    controls.append(ft.Container(
                        content=ft.Row([
                            ft.Icon(icon, size=19, color=color),
                            ft.Text(label, color=color,
                                    weight=ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL),
                        ] + ([ft.Container(content=ft.Text(str(unread_total), size=10, color="#FFFFFF",
                                                           weight=ft.FontWeight.BOLD),
                                           bgcolor=C("#E5484D"), padding=pad_sym(7, 2), border_radius=10)]
                             if key == "classes" and unread_total else []), spacing=13),
                        bgcolor=C("#3157D5") if selected else None,
                        border_radius=10, padding=pad_sym(14, 12),
                        margin=margin_only(left=12, right=12, top=4),
                        on_click=lambda e, k=key: nav_click(k), ink=True,
                    ))
            split = len(controls)    # everything before this scrolls; the footer below stays pinned
            theme_icon = ft.Icons.LIGHT_MODE if DARK["on"] else ft.Icons.DARK_MODE
            theme_label = "Light mode" if DARK["on"] else "Dark mode"
            avatar = ft.CircleAvatar(content=ft.Text(user["full_name"][:1].upper(), color="#FFFFFF"),
                                     bgcolor=C("#4768D8"), radius=20)
            if mini:
                controls += [
                    ft.Container(content=ft.Icon(theme_icon, size=18, color=C("#A9B7CC")), width=SB_MINI,
                                 height=FOOT_H, alignment=center_alignment(), ink=True,
                                 on_click=lambda e: item_click("__theme"),
                                 on_hover=lambda e: icon_hover("__theme", e)),
                    ft.Container(content=avatar, width=SB_MINI, height=PROF_H, alignment=center_alignment(),
                                 ink=True, on_click=lambda e: item_click("__profile"),
                                 on_hover=lambda e: icon_hover("__profile", e)),
                    ft.Container(content=ft.Icon(ft.Icons.LOGOUT, size=18, color=C("#FCA5A5")), width=SB_MINI,
                                 height=FOOT_H, alignment=center_alignment(), ink=True,
                                 on_click=lambda e: item_click("__logout"),
                                 on_hover=lambda e: icon_hover("__logout", e)),
                ]
            else:
                controls += [
                    ft.Container(
                        content=ft.Row([ft.Icon(theme_icon, size=18, color=C("#A9B7CC")),
                                        ft.Text(theme_label, color=C("#A9B7CC"))], spacing=12),
                        padding=pad_sym(25, 12), on_click=toggle_theme, ink=True,
                    ),
                    ft.Container(
                        content=ft.Row([
                            avatar,
                            ft.Column([
                                ft.Text(user["full_name"], size=12, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                                ft.Text(role.title(), size=11, color=C("#A9B7CC")),
                            ], spacing=2, expand=True),
                        ], spacing=10),
                        padding=18, on_click=lambda e: profile_dialog(), ink=True, tooltip="Edit my profile",
                    ),
                    ft.Container(
                        content=ft.Row([ft.Icon(ft.Icons.LOGOUT, size=18, color=C("#FCA5A5")),
                                        ft.Text("Log out", color=C("#FCA5A5"))], spacing=12),
                        padding=pad_sym(25, 14),
                        on_click=lambda e: ask_confirm("Log out", "Do you want to log out of StudyTrack?", logout),
                        ink=True,
                    ),
                ]
            # logo header + divider stay on top; only the menu items scroll; the footer stays at the bottom
            menu = ft.Column(controls[2:split], spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
            return controls[:2] + [menu] + controls[split:]

        slide = ft.Animation(250, ft.AnimationCurve.EASE_IN_OUT)
        sidebar_col = ft.Column(build_nav(), spacing=2, expand=True)
        sidebar = ft.Container(content=sidebar_col, width=SB_MINI if is_collapsed() else SB_FULL,
                               bgcolor=C("#17243A"), animate=slide,
                               clip_behavior=ft.ClipBehavior.HARD_EDGE)

        def chevron():
            return ft.Icon(ft.Icons.CHEVRON_RIGHT if is_collapsed() else ft.Icons.CHEVRON_LEFT,
                           size=18, color=C("#3157D5", True))

        toggle_btn = ft.Container(
            content=chevron(), width=28, height=28, border_radius=14, bgcolor=C("#FFFFFF"),
            border=border_all(1, C("#DCE3EF")), alignment=center_alignment(),
            left=(SB_MINI if is_collapsed() else SB_FULL) - 14, top=30, ink=True,
            tooltip="Expand sidebar" if is_collapsed() else "Collapse sidebar",
            shadow=ft.BoxShadow(blur_radius=10, color="#33000000", offset=ft.Offset(0, 3)),
            animate_position=slide,
        )

        def set_collapsed(value, user_set=False):
            if user_set:
                state["sidebar_user_set"] = True
            if value == is_collapsed():
                return
            hide_now()
            state["sidebar_collapsed"] = value

            def apply():
                try:
                    if value:      # collapse: swap to icons first, then shrink
                        sidebar_col.controls = build_nav()
                        sidebar.width = SB_MINI
                    else:          # expand: grow first, then show the labels
                        sidebar.width = SB_FULL
                    toggle_btn.left = (SB_MINI if value else SB_FULL) - 14
                    toggle_btn.content = chevron()
                    toggle_btn.tooltip = "Expand sidebar" if value else "Collapse sidebar"
                    page.update()
                    if not value:
                        _time.sleep(0.26)
                        sidebar_col.controls = build_nav()
                        page.update()
                except Exception:
                    pass   # the page changed while animating
            threading.Thread(target=apply, daemon=True).start()

        toggle_btn.on_click = lambda e: set_collapsed(not is_collapsed(), user_set=True)

        header = ft.Container(
            content=ft.Row([
                ft.Column([
                    ft.Text(title, size=23, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                    ft.Text(subtitle or "", size=12, color=C("#748198")),
                ], spacing=3, expand=True),
            ]),
            padding=pad_only(left=28, right=28, top=22, bottom=18),
            border=border_only(bottom=ft.BorderSide(1, C("#E7ECF4"))),
            bgcolor=C("#FFFFFF"),
        )
        if isinstance(body, ft.Column):
            body.expand = True
        page_content = ft.Container(content=body, expand=True, padding=28, bgcolor=C("#F4F7FB"))
        layout = ft.Row([sidebar, ft.Column([header, page_content], expand=True, spacing=0)],
                        expand=True, spacing=0, left=0, top=0, right=0, bottom=0)
        root = ft.Stack([layout, toggle_btn, tip], expand=True)   # button and tooltip float above the layout

        def on_resize(e=None):
            """Narrow windows collapse the sidebar automatically (until the user picks a state themselves)."""
            if state.get("sidebar_user_set") or root not in page.controls:
                return
            narrow = (page.width or 1200) < 820
            if narrow != is_collapsed():
                set_collapsed(narrow)

        try:
            page.on_resize = on_resize
        except Exception:
            pass
        page.controls.clear()
        page.add(root)
        page.update()

    def logout():
        log_event("security", "Logout", "")
        _SESSION["user"] = None
        state["user"] = None
        state["class"] = None
        login_view()

    def welcome_view():
        """Screen 1 of 2: the welcome / landing page. 'Get Started' opens the login page."""
        import threading
        import time as _time
        state["view"] = "welcome"
        state["welcome_token"] = state.get("welcome_token", 0) + 1
        token = state["welcome_token"]
        NAVY, BLUE = "#14224A", "#3157D5"      # always light: the landing page ignores dark mode

        def icon_of(*names):
            for n in names:
                v = getattr(ft.Icons, n, None)
                if v is not None:
                    return v
            return ft.Icons.STAR_ROUNDED

        ease = ft.Animation(650, ft.AnimationCurve.EASE_OUT)

        def reveal(control, dx=0.0, dy=0.12):
            """Start hidden + nudged; the entrance sequence below slides/fades it into place."""
            return ft.Container(content=control, opacity=0, offset=ft.Offset(dx, dy),
                                animate_opacity=ease, animate_offset=ease)

        # --- Get Started button (hover: grows, glows, arrow slides) ---
        arrow = ft.Container(content=ft.Icon(ft.Icons.ARROW_FORWARD_ROUNDED, color="#FFFFFF", size=26),
                             offset=ft.Offset(0, 0),
                             animate_offset=ft.Animation(250, ft.AnimationCurve.EASE_OUT))
        rest_shadow = ft.BoxShadow(blur_radius=18, color="#553157D5", offset=ft.Offset(0, 6))
        hover_shadow = ft.BoxShadow(blur_radius=30, spread_radius=1, color="#883157D5", offset=ft.Offset(0, 10))

        def go_login(_=None):
            login_view()

        def on_hover(e):
            hovering = str(e.data).lower() == "true"
            start.scale = 1.07 if hovering else 1.0
            start.bgcolor = "#2748BD" if hovering else BLUE
            start.shadow = hover_shadow if hovering else rest_shadow
            arrow.offset = ft.Offset(0.25, 0) if hovering else ft.Offset(0, 0)
            start.update()

        start = ft.Container(
            content=ft.Row([ft.Text("Get Started", size=17, weight=ft.FontWeight.W_600, color="#FFFFFF"), arrow],
                           tight=True, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=pad_sym(30, 16), border_radius=40, bgcolor=BLUE, shadow=rest_shadow,
            ink=True, on_click=go_login, on_hover=on_hover, tooltip="Go to the login page",
            scale=1.0, animate_scale=ft.Animation(250, ft.AnimationCurve.EASE_OUT),
            animate=ft.Animation(250, ft.AnimationCurve.EASE_OUT),
        )

        # --- Left side: big logo with soft rings and floating icon badges ---
        SIZE = 420
        float_anim = ft.Animation(1800, ft.AnimationCurve.EASE_IN_OUT)

        def badge(icon_names, color, left, top):
            return ft.Container(
                content=ft.Icon(icon_of(*icon_names), size=28, color=color),
                width=60, height=60, left=left, top=top, border_radius=30, bgcolor="#FFFFFF",
                alignment=center_alignment(), offset=ft.Offset(0, 0), animate_offset=float_anim,
                shadow=ft.BoxShadow(blur_radius=22, color="#333157D5", offset=ft.Offset(0, 8)),
            )

        badges = [
            badge(("TASK_ALT_ROUNDED", "CHECK_CIRCLE_ROUNDED"), BLUE, 318, 58),
            badge(("CALENDAR_MONTH_ROUNDED", "EVENT_ROUNDED"), "#0D9488", 12, 262),
            badge(("INSIGHTS_ROUNDED", "TRENDING_UP_ROUNDED"), "#7C3AED", 296, 316),
            badge(("SCHOOL_ROUNDED", "AUTO_STORIES_ROUNDED"), "#DB2777", 46, 60),
        ]
        logo_art = ft.Container(
            content=landing_image("studytrack_logo", width=220, height=220),
            width=220, height=220, left=100, top=100, border_radius=54,
            shadow=ft.BoxShadow(blur_radius=44, color="#4D3157D5", offset=ft.Offset(0, 20)),
        )
        ring_outer = ft.Container(width=SIZE, height=SIZE, left=0, top=0, border_radius=SIZE // 2,
                                  border=border_all(1, "#C9DBFB"))
        ring_mid = ft.Container(width=340, height=340, left=40, top=40, border_radius=170,
                                bgcolor="#8CFFFFFF", border=border_all(1, "#E1EBFD"))
        logo_area = ft.Container(content=ft.Stack([ring_outer, ring_mid, logo_art] + badges,
                                                  width=SIZE, height=SIZE),
                                 width=SIZE, height=SIZE)

        # --- Right side: name, tagline, welcome message, feature chips ---
        name = ft.Text("StudyTrack", size=66, weight=ft.FontWeight.W_800, color=NAVY)
        accent_bar = ft.Container(width=76, height=6, border_radius=3, bgcolor=BLUE)
        tagline = ft.Text(
            size=28, color="#24324A", weight=ft.FontWeight.W_500,
            spans=[ft.TextSpan("Plan. Study. Track. "),
                   ft.TextSpan("Achieve.", ft.TextStyle(color=BLUE, italic=True, weight=ft.FontWeight.BOLD))],
        )
        message = ft.Container(
            content=ft.Column([
                ft.Text("Welcome to StudyTrack!", size=24, weight=ft.FontWeight.BOLD, color=NAVY),
                ft.Text("Your classroom, your progress, your success. Stay organized, manage your "
                        "academic activities, and keep track of your learning journey in one place.",
                        size=15, color="#4B5B73"),
            ], spacing=8),
            width=540, padding=pad_only(left=18, top=2, bottom=2),
            border=border_only(left=ft.BorderSide(4, "#8FB0FA")),
        )

        def chip(icon_names, label):
            return ft.Container(
                content=ft.Row([ft.Icon(icon_of(*icon_names), size=18, color=BLUE),
                                ft.Text(label, size=13, weight=ft.FontWeight.W_600, color="#24324A")],
                               tight=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=pad_sym(14, 9), border_radius=22, bgcolor="#E6FFFFFF",
                border=border_all(1, "#DCE6F8"),
                shadow=ft.BoxShadow(blur_radius=12, color="#143157D5", offset=ft.Offset(0, 4)),
            )

        chips = ft.Row([chip(("CLASS_ROUNDED", "SCHOOL_ROUNDED"), "Classes"),
                        chip(("ASSIGNMENT_TURNED_IN_ROUNDED", "TASK_ALT_ROUNDED"), "Activities"),
                        chip(("INSIGHTS_ROUNDED", "TRENDING_UP_ROUNDED"), "Grades & progress")],
                       spacing=10, wrap=True)

        r_name = reveal(ft.Column([name, accent_bar], spacing=8), dy=0.15)
        r_tag = reveal(tagline)
        r_msg = reveal(message)
        r_chips = reveal(chips)
        r_logo = reveal(logo_area, dx=-0.08, dy=0.0)
        r_btn = reveal(start, dx=0.0, dy=0.3)

        text_side = ft.Column([r_name, r_tag, ft.Container(height=10), r_msg, ft.Container(height=4), r_chips],
                              spacing=8, alignment=ft.MainAxisAlignment.CENTER)

        main_row = ft.Row([
            ft.Container(content=r_logo, expand=4, alignment=center_alignment()),
            ft.Container(content=text_side, expand=6, padding=pad_only(right=40)),
        ], expand=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        foreground = ft.Container(
            content=ft.Column([main_row, ft.Row([r_btn], alignment=ft.MainAxisAlignment.END)],
                              expand=True, spacing=0),
            expand=True, padding=pad_only(left=60, right=64, top=30, bottom=48),
        )

        layers = [ft.Container(expand=True, bgcolor="#EAF2FF")]       # fallback if the artwork can't load
        fit = image_fit("COVER")
        waves = landing_asset("waves")
        if waves:
            layers.append(ft.Image(src=waves, expand=True, **({"fit": fit} if fit is not None else {})))
        layers.append(foreground)

        page.controls.clear()
        page.add(ft.Stack(layers, expand=True))
        page.update()

        def animate_in():
            """Slide + fade the pieces in one after another, then gently float the icon badges."""
            try:
                for item in (r_logo, r_name, r_tag, r_msg, r_chips, r_btn):
                    if state.get("welcome_token") != token or state["view"] != "welcome":
                        return
                    item.opacity = 1
                    item.offset = ft.Offset(0, 0)
                    item.update()
                    _time.sleep(0.14)
                _time.sleep(0.6)
                up = False
                while state.get("welcome_token") == token and state["view"] == "welcome":
                    up = not up
                    for i, b in enumerate(badges):
                        b.offset = ft.Offset(0, -0.1 if (up != (i % 2 == 1)) else 0.1)
                        b.update()
                    _time.sleep(1.8)
            except Exception:
                # the page changed while animating (user clicked Get Started): just stop
                for item in (r_logo, r_name, r_tag, r_msg, r_chips, r_btn):
                    item.opacity = 1
                    item.offset = ft.Offset(0, 0)

        threading.Thread(target=animate_in, daemon=True).start()

    def login_view():
        state["view"] = "login"
        username = text_field("Email or phone", width=360, hint="Enter your registered username")
        password = text_field("Password", password=True, width=360)

        def do_login(_=None):
            u_name, pwd = (username.value or "").strip(), password.value or ""
            user = next((u for u in read_rows("users")
                         if u["username"].casefold() == u_name.casefold()), None)
            until = user.get("locked_until") if user else _LOCAL_FAILS.get(("until", u_name.casefold()), "")
            left = lock_minutes_left(until)
            if left:
                toast(f"Too many wrong tries. Please wait about {left} minute(s) and try again.", True)
                return
            if not user or not verify_password(pwd, user["password_hash"]):
                locked, tries = register_failed_login(user, u_name)
                if locked:
                    if user:
                        log_event("security", "Account locked",
                                  f"{user['username']} was locked for {LOCKOUT_MINUTES} minutes after "
                                  f"{MAX_FAILED_LOGINS} wrong passwords.")
                    toast(f"Too many wrong tries. Login is locked for {LOCKOUT_MINUTES} minutes.", True)
                else:
                    word = "try" if tries == 1 else "tries"
                    toast(f"Incorrect username or password. {tries} {word} left before a "
                          f"{LOCKOUT_MINUTES}-minute lock.", True)
                return
            if user.get("active") == "0":
                toast("Your account is inactive. Please contact the administrator.", True)
                return
            if user["role"] == "teacher" and user.get("approved") == "0":
                toast("Your teacher account is still waiting for admin approval.", True)
                return
            user["last_login"] = timestamp()
            update_row("users", user["id"], {"last_login": user["last_login"], "failed_attempts": "",
                                             "locked_until": ""})
            state["user"] = user
            _SESSION["user"] = user
            log_event("security", "Login", user["username"])
            DARK["on"] = user.get("theme") == "dark"
            apply_theme()
            dashboard()

        username.on_submit = do_login
        password.on_submit = do_login
        form = ft.Column([
            ft.Container(
                content=ft.Row([
                    ft.Container(content=ft.Icon(ft.Icons.AUTO_STORIES_ROUNDED, size=30, color="#FFFFFF"),
                                 bgcolor=C("#3157D5"), padding=14, border_radius=16),
                    ft.Column([
                        ft.Text("StudyTrack", size=30, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                        ft.Text("YOUR CLASSROOM, ORGANIZED.", size=10, weight=ft.FontWeight.BOLD,
                                color=C("#3157D5", True)),
                    ], spacing=2),
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=12),
                padding=pad_only(bottom=10),
            ),
            ft.Text("Welcome back", size=25, weight=ft.FontWeight.BOLD, color=C("#18243A")),
            ft.Text("Sign in to continue to your classroom.", color=C("#748198"), size=13),
            ft.Container(height=8),
            username, password,
            button("Log in", do_login, ft.Icons.LOGIN_ROUNDED, primary=True),
            ft.Row([
                ft.Text("New to StudyTrack?", color=C("#748198"), size=12),
                ft.TextButton("Create an account", on_click=lambda e: register_view()),
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Text("Offline classroom management", size=10, color=C("#9AA5B5"),
                    text_align=ft.TextAlign.CENTER),
            ft.TextButton("Back to welcome", icon=ft.Icons.ARROW_BACK_ROUNDED,
                          on_click=lambda e: welcome_view()),
        ], spacing=14, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)
        login_card = ft.Container(content=form, width=440, padding=38, bgcolor=C("#FFFFFF"),
                                  border_radius=24, border=border_all(1, C("#E7ECF4")))
        page.controls.clear()
        page.add(ft.Container(content=login_card, alignment=center_alignment(),
                              expand=True, bgcolor=C("#F4F7FB"), padding=20))
        page.update()

    def register_view():
        first_name = text_field("First name", width=380)
        middle_initial = text_field("Middle initial (optional)", width=380)
        middle_initial.max_length = 1
        last_name = text_field("Last name", width=380)
        suffix_field = text_field("Suffix (optional, e.g. Jr., Sr., III)", width=380)
        suffix_field.max_length = 6
        username = text_field("Gmail or 12-digit phone number", width=380, hint="name@gmail.com or 123456789012")
        password = text_field("Password (at least 6 characters)", password=True, width=380)
        confirm_password = text_field("Confirm password", password=True, width=380)
        role = ft.Dropdown(label="Account type", value="student", width=380,
                           options=[ft.dropdown.Option("student", "Student"),
                                    ft.dropdown.Option("teacher", "Teacher")],
                           border_radius=12, filled=True, bgcolor=C("#FFFFFF"))

        def register(_=None):
            try:
                f = (first_name.value or "").strip()
                m = (middle_initial.value or "").strip().rstrip(".").upper()[:1]
                l = (last_name.value or "").strip()
                sfx = clean_suffix(suffix_field.value)
                u = (username.value or "").strip()
                pwd = password.value or ""
                if not f or not l or not u or not pwd:
                    toast("Please complete all required fields.", True)
                    return
                contact_error = validate_contact(u)
                if contact_error:
                    toast(contact_error, True)
                    return
                if len(pwd) < 6:
                    toast("Use at least 6 characters for your password.", True)
                    return
                if pwd != (confirm_password.value or ""):
                    toast("The passwords do not match.", True)
                    return
                if any(x["username"].casefold() == u.casefold() for x in read_rows("users")):
                    toast("That username is already registered.", True)
                    return
                add_row("users", {
                    "id": next_id("users"), "username": u, "password_hash": hash_password(pwd),
                    "role": role.value or "student",
                    "full_name": format_full_name(f, m, l, sfx),
                    "first_name": f, "middle_initial": m, "last_name": l, "suffix": sfx,
                    "approved": "0" if role.value == "teacher" else "1",
                })
                log_event("account", "Account created", f"{format_full_name(f, m, l, sfx)} ({role.value or 'student'})")
                login_view()
                if role.value == "teacher":
                    toast("Account created. An admin must approve your teacher account before you can log in.")
                else:
                    toast("Account created successfully. You can now log in.")
            except Exception as exc:
                print("Registration error:", repr(exc))
                toast(f"Registration failed: {exc}", True)

        form = ft.Column([
            ft.Icon(ft.Icons.PERSON_ADD_ALT_1_ROUNDED, size=38, color=C("#3157D5", True)),
            ft.Text("Create your account", size=25, weight=ft.FontWeight.BOLD, color=C("#18243A")),
            ft.Text("Choose a role to get started.", size=13, color=C("#748198")),
            first_name, middle_initial, last_name, suffix_field, username, password, confirm_password, role,
            button("Register", register, ft.Icons.CHECK_CIRCLE_OUTLINE, primary=True),
            ft.TextButton("Back to login", on_click=lambda e: login_view()),
        ], spacing=14, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)
        page.controls.clear()
        page.add(ft.Container(
            content=ft.Column([
                ft.Row([ft.Container(content=form, width=460, padding=36, bgcolor=C("#FFFFFF"),
                                     border_radius=24, border=border_all(1, C("#E7ECF4")))],
                       alignment=ft.MainAxisAlignment.CENTER),
            ], alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                scroll=ft.ScrollMode.AUTO, expand=True),
            expand=True, bgcolor=C("#F4F7FB"), padding=20,
        ))
        page.update()

    ADMIN_COLS = {"xs": 12, "sm": 6, "lg": 4, "xl": 2}

    def stat_card(label, value, icon, accent=C("#3157D5"), cols=None, on_click=None):
        return ft.Container(
            col=cols or {"xs": 12, "sm": 6, "lg": 3},
            on_click=on_click, ink=bool(on_click),
            tooltip="Click to see the list" if on_click else None,
            content=ft.Row([
                ft.Container(content=ft.Icon(icon, color=accent, size=23),
                             bgcolor=accent + "18", padding=13, border_radius=14),
                ft.Column([
                    ft.Text(str(value), size=26, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                    ft.Text(label, size=12, color=C("#748198")),
                ], spacing=2),
            ], spacing=14),
            padding=18, bgcolor=C("#FFFFFF"), border_radius=16,
            border=border_all(1, C("#E7ECF4")),
        )

    def admin_stat_dialog(kind):
        """Pop-up list behind an admin dashboard number (teachers, students, classes, ...)."""
        users = read_rows("users")
        classes = read_rows("classes")
        enrollments = read_rows("enrollments")
        icons = {"teachers": ft.Icons.PERSON_OUTLINE, "students": ft.Icons.GROUP_OUTLINED,
                 "classes": ft.Icons.SCHOOL_OUTLINED, "years": ft.Icons.CALENDAR_MONTH_OUTLINED,
                 "sections": ft.Icons.GROUPS_OUTLINED, "subjects": ft.Icons.MENU_BOOK_OUTLINED}
        titles = {"teachers": "Teachers", "students": "Students", "classes": "Classes",
                  "years": "School years", "sections": "Active sections", "subjects": "Subjects"}
        nouns = {"teachers": "teacher", "students": "student", "classes": "class", "years": "school year",
                 "sections": "section", "subjects": "subject"}
        accent = C("#3157D5", True)
        entries = []   # (title, subtitle, badge_text, badge_color, badge_bg)

        def account_state(u):
            if u["role"] == "teacher" and u.get("approved") == "0":
                return "Waiting for approval", C("#B54708"), C("#FEE4E2")
            if u.get("active") == "0":
                return "Inactive", C("#B42318"), C("#FEE4E2")
            return "Active", C("#0D9488"), C("#E8F8F4")

        if kind in ("teachers", "students"):
            role = "teacher" if kind == "teachers" else "student"
            people = sorted((u for u in users if u["role"] == role),
                            key=lambda u: tuple(x.casefold() for x in name_parts(u)))
            for u in people:
                if role == "teacher":
                    n = sum(1 for c in classes if c["teacher_id"] == u["id"])
                    sub = f"{u['username']} • {n} class(es)"
                else:
                    n = sum(1 for e in enrollments if e["student_id"] == u["id"])
                    sub = f"{u['username']} • enrolled in {n} class(es)"
                txt, col, bg = account_state(u)
                entries.append((format_sheet_name(u), sub, txt, col, bg))
        elif kind == "classes":
            counts = _student_counts()
            for c in sorted(classes, key=lambda c: ((c.get("school_year") or ""), c["name"].casefold(),
                                                    c["subject"].casefold())):
                sub = (f"S.Y. {c.get('school_year') or '—'} • {c['teacher_name']} • "
                       f"{plural('student', counts.get(c['id'], 0))}")
                if is_archived(c):
                    entries.append((c["subject"], sub, "Archived", C("#B54708"), C("#FEE4E2"), c))
                else:
                    entries.append((c["subject"], sub, "Active", C("#0D9488"), C("#E8F8F4"), c))
        elif kind == "years":
            for y in sorted(read_rows("school_years"), key=lambda r: r["name"], reverse=True):
                if y.get("active") == "0":
                    continue
                n = sum(1 for c in classes if (c.get("school_year") or "") == y["name"])
                entries.append((y["name"], f"{n} class(es)", "Active", C("#0D9488"), C("#E8F8F4")))
        elif kind == "sections":
            for r in sorted(read_rows("sections"), key=lambda r: r["name"].casefold()):
                if r.get("active") == "0":
                    continue
                n = sum(1 for c in classes if c["name"] == r["name"])
                entries.append((r["name"], f"Used in {n} class(es)", "Active", C("#0D9488"), C("#E8F8F4")))
        else:
            for r in sorted(read_rows("subjects"), key=lambda r: r["name"].casefold()):
                n = sum(1 for c in classes if c["subject"] == r["name"])
                entries.append((r["name"], f"Used in {n} class(es)", course_label(r), accent, C("#EEF2FF"), r))

        is_subjects = kind == "subjects"
        search = text_field("Search", width=300 if is_subjects else 480, hint="Type to filter the list")
        course_filter = ft.Dropdown(label="Course", width=220, value="all", border_radius=12, filled=True,
                                    bgcolor=C("#FFFFFF"),
                                    options=[ft.dropdown.Option("all", "All courses")] +
                                            [ft.dropdown.Option(c) for c in get_active_courses()])
        list_col = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, tight=True, height=360)
        count_chip = ft.Container(bgcolor=C("#EEF2FF"), padding=pad_sym(9, 4), border_radius=10,
                                  content=ft.Text("", size=11, weight=ft.FontWeight.BOLD, color=accent))

        def build_item(i, e):
            title, sub, badge, bcol, bbg = e[:5]
            row = [ft.Text(str(i), size=11, color=C("#9AA5B5"), width=26),
                   ft.Container(content=ft.Icon(icons[kind], size=17, color=accent), bgcolor=C("#EEF2FF"),
                                padding=9, border_radius=10),
                   ft.Column([ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                              ft.Text(sub, size=11, color=C("#748198"))], spacing=2, expand=True)]
            if badge:
                row.append(ft.Container(content=ft.Text(badge, size=11, weight=ft.FontWeight.BOLD, color=bcol),
                                        bgcolor=bbg, padding=pad_sym(10, 4), border_radius=10))
            return ft.Container(content=ft.Row(row, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=pad_sym(12, 9), bgcolor=C("#F7F9FD"), border_radius=12,
                                border=border_all(1, C("#E7ECF4")))

        def render(e=None, push=True):
            q = (search.value or "").strip().casefold()
            def hay(x):
                extra = x[5]["name"] if kind == "classes" else ""
                return f"{x[0]} {x[1]} {x[2]} {extra}".casefold()
            shown = [x for x in entries if not q or q in hay(x)]
            if is_subjects and course_filter.value not in (None, "all"):
                shown = [x for x in shown if subject_fits_course(x[5], course_filter.value)]
            n = len(shown)
            count_chip.content.value = plural(nouns[kind], n)
            if shown:
                def band(text, count_text, icon, sub=False):
                    return ft.Container(
                        content=ft.Row([
                            ft.Icon(icon, size=15 if sub else 16, color=accent if sub else "#FFFFFF"),
                            ft.Text(text, size=12, weight=ft.FontWeight.BOLD,
                                    color=accent if sub else "#FFFFFF", expand=True),
                            ft.Text(count_text, size=11, color=C("#748198") if sub else "#DCE6FF"),
                        ], spacing=8),
                        padding=pad_sym(12, 7 if sub else 8),
                        bgcolor=C("#E8EEFF") if sub else C("#3157D5"), border_radius=10,
                        margin=margin_only(top=4) if sub else None)

                controls = []
                if kind in ("sections", "subjects"):
                    groups = {}
                    for x in shown:
                        key = section_course(x[0]) if kind == "sections" else course_label(x[5])
                        groups.setdefault(key, []).append(x)
                    for key in sorted(groups, key=lambda k: (k == "All courses", k.casefold())):
                        items = groups[key]
                        controls.append(band(key, plural(nouns[kind], len(items)), ft.Icons.SCHOOL_OUTLINED))
                        controls += [build_item(i, x) for i, x in enumerate(items, start=1)]
                elif kind == "classes":
                    sections_map = {}
                    for x in shown:
                        sections_map.setdefault(x[5]["name"], []).append(x)
                    for sec in sorted(sections_map, key=str.casefold):
                        items = sections_map[sec]
                        controls.append(band(sec, plural("class", len(items)), ft.Icons.GROUPS_OUTLINED))
                        controls += [build_item(i, x) for i, x in enumerate(items, start=1)]
                else:
                    controls = [build_item(i, x) for i, x in enumerate(shown, start=1)]
                list_col.controls = controls
            else:
                list_col.controls = [ft.Text("Nothing to show." if not entries else "No match for your search.",
                                             size=12, color=C("#748198"))]
            if push:
                page.update()

        search.on_change = render
        course_filter.on_change = render
        render(push=False)
        header = ft.Row([
            ft.Container(content=ft.Icon(icons[kind], size=24, color="#FFFFFF"), bgcolor=C("#3157D5"),
                         padding=12, border_radius=14),
            ft.Column([ft.Text(titles[kind], size=19, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                       ft.Text("Admin overview", size=12, color=C("#748198"))], spacing=2, expand=True),
            count_chip,
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        content = ft.Container(content=ft.Column([ft.Row([search, course_filter], spacing=12) if is_subjects else search,
                                                  ft.Divider(height=1, color=C("#E7ECF4")), list_col],
                                                 spacing=12, tight=True), width=540)
        dlg = ft.AlertDialog(
            modal=True, title=header, content=content,
            actions=[compatible_button("Close", on_click=lambda e: close_dialog(dlg), icon=ft.Icons.CLOSE,
                                       style=ft.ButtonStyle(bgcolor=C("#3157D5"), color="#FFFFFF",
                                                            shape=ft.RoundedRectangleBorder(radius=10),
                                                            padding=pad_sym(18, 12)))],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=20), bgcolor=C("#FFFFFF"))
        open_control(page, dlg)
        page.update()

    def teacher_stat_dialog(kind):
        """Pop-up list behind a teacher dashboard number (classes, students, activities, submissions)."""
        me = state["user"]
        classes = [c for c in read_rows("classes") if c["teacher_id"] == me["id"] and not is_archived(c)]
        class_ids = {c["id"] for c in classes}
        cmap = {c["id"]: c for c in classes}
        users = {u["id"]: u for u in read_rows("users")}
        icons = {"classes": ft.Icons.SCHOOL_OUTLINED, "students": ft.Icons.GROUP_OUTLINED,
                 "activities": ft.Icons.ASSIGNMENT_OUTLINED, "submissions": ft.Icons.UPLOAD_FILE_OUTLINED}
        titles = {"classes": "Classes created", "students": "Students enrolled",
                  "activities": "Activities", "submissions": "Submissions"}
        nouns = {"classes": "class", "students": "student", "activities": "activity", "submissions": "submission"}
        accent = C("#3157D5", True)
        blue_bg = C("#EEF2FF")
        entries = []   # (title, subtitle, badge, badge_color, badge_bg, class_to_open)
        student_of = {}   # id(entry) -> student's name (for grouping the submissions list)
        counts = _student_counts()

        if kind == "classes":
            for c in sorted(classes, key=lambda c: ((c.get("school_year") or ""), c["name"].casefold(),
                                                    c["subject"].casefold())):
                entries.append((c["name"], plural("student", counts.get(c["id"], 0)),
                                c["code"], accent, blue_bg, c))
        elif kind == "students":
            for e in read_rows("enrollments"):
                c = cmap.get(e["class_id"])
                if not c:
                    continue
                u = users.get(e["student_id"]) or {"full_name": e["student_name"]}
                entries.append((format_sheet_name(u), f"{c['name']} — {c['subject']}",
                                (users.get(e["student_id"]) or {}).get("username", ""), accent, blue_bg, c))
            entries.sort(key=lambda x: x[0].casefold())
        elif kind == "activities":
            acts = [a for a in read_rows("activities") if a["class_id"] in class_ids and not is_record_item(a)]
            for a in sorted(acts, key=id_key, reverse=True):
                c = cmap[a["class_id"]]
                entries.append((f"{activity_label(a)}: {a['title']}",
                                f"{c['name']} — {c['subject']} • {a.get('term') or 'Midterm'} • "
                                f"Deadline: {a['deadline'] or 'None'}",
                                cat_of(a), accent, blue_bg, c))
        else:
            acts = {a["id"]: a for a in read_rows("activities")}
            subs = [x for x in read_rows("submissions") if x["class_id"] in class_ids]
            for x in sorted(subs, key=id_key, reverse=True):
                c = cmap[x["class_id"]]
                a = acts.get(x["activity_id"])
                what = activity_label(a) if a else "Activity"
                how = f"Submitted {x['submitted_at']}" if x["submitted_at"] else "Encoded in record sheet"
                if x["score"] == "":
                    badge, bcol, bbg = "Not graded", C("#B54708"), C("#FEE4E2")
                else:
                    badge, bcol, bbg = ("EXC" if is_excused(x["score"]) else fmt(x["score"])), C("#0D9488"), C("#E8F8F4")
                u = users.get(x["student_id"]) or {"full_name": x["student_name"]}
                entry = (what, how, badge, bcol, bbg, c)
                student_of[id(entry)] = format_sheet_name(u) or x["student_name"]
                entries.append(entry)

        search = text_field("Search", width=540, hint="Type to filter the list")
        class_dd = student_dd = None
        if kind == "submissions":
            class_keys = sorted({(x[5]["id"], f"{x[5]['name']} — {x[5]['subject']}") for x in entries},
                                key=lambda k: k[1].casefold())
            class_dd = ft.Dropdown(label="Class", width=265, value="all", border_radius=12, filled=True,
                                   bgcolor=C("#FFFFFF"),
                                   options=[ft.dropdown.Option("all", "All classes")] +
                                           [ft.dropdown.Option(k, v) for k, v in class_keys])
            student_dd = ft.Dropdown(label="Student", width=265, value="all", border_radius=12, filled=True,
                                     bgcolor=C("#FFFFFF"), options=[])

            def fill_students():
                names = sorted({student_of[id(x)] for x in entries
                                if class_dd.value in (None, "all") or x[5]["id"] == class_dd.value},
                               key=str.casefold)
                student_dd.options = [ft.dropdown.Option("all", "All students")] + \
                                     [ft.dropdown.Option(n) for n in names]
                student_dd.value = "all"
        list_col = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, tight=True,
                             height=300 if kind == "submissions" else 360)
        count_chip = ft.Container(bgcolor=blue_bg, padding=pad_sym(9, 4), border_radius=10,
                                  content=ft.Text("", size=11, weight=ft.FontWeight.BOLD, color=accent))
        dlg = None

        def go(c):
            close_dialog(dlg)
            open_class(c)

        def build_item(i, e):
            title, sub, badge, bcol, bbg, c = e
            row = [ft.Text(str(i), size=11, color=C("#9AA5B5"), width=26),
                   ft.Container(content=ft.Icon(icons[kind], size=17, color=accent), bgcolor=blue_bg,
                                padding=9, border_radius=10),
                   ft.Column([ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                              ft.Text(sub, size=11, color=C("#748198"))], spacing=2, expand=True)]
            if badge:
                row.append(ft.Container(content=ft.Text(badge, size=11, weight=ft.FontWeight.BOLD, color=bcol),
                                        bgcolor=bbg, padding=pad_sym(10, 4), border_radius=10))
            return ft.Container(content=ft.Row(row, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=pad_sym(12, 9), bgcolor=C("#F7F9FD"), border_radius=12,
                                border=border_all(1, C("#E7ECF4")), ink=True,
                                tooltip="Click to open this class",
                                on_click=lambda ev, cl=c: go(cl))

        def render(e=None, push=True):
            q = (search.value or "").strip().casefold()
            shown = [x for x in entries if not q or q in f"{x[0]} {x[1]} {x[2]} {x[5]['subject']} {x[5]['name']} {student_of.get(id(x), '')}".casefold()]
            if class_dd is not None:
                shown = [x for x in shown if class_dd.value in (None, "all") or x[5]["id"] == class_dd.value]
                shown = [x for x in shown if student_dd.value in (None, "all")
                         or student_of[id(x)] == student_dd.value]
            n = len(shown)
            count_chip.content.value = plural(nouns[kind], n)
            if shown:
                controls = []

                def band(text, count_text, icon, sub=False):
                    return ft.Container(
                        content=ft.Row([
                            ft.Icon(icon, size=15 if sub else 16, color=accent if sub else "#FFFFFF"),
                            ft.Text(text, size=12, weight=ft.FontWeight.BOLD,
                                    color=accent if sub else "#FFFFFF", expand=True),
                            ft.Text(count_text, size=11, color=C("#748198") if sub else "#DCE6FF"),
                        ], spacing=8),
                        padding=pad_sym(12, 7 if sub else 8),
                        bgcolor=C("#E8EEFF") if sub else C("#3157D5"), border_radius=10,
                        margin=margin_only(top=4) if sub else None)

                if kind == "classes":
                    years = {}
                    for x in shown:
                        c = x[5]
                        years.setdefault(c.get("school_year") or "—", {}).setdefault(c["subject"], []).append(x)
                    for yr in sorted(years, reverse=True):
                        subjects = years[yr]
                        total = sum(len(v) for v in subjects.values())
                        controls.append(band(f"S.Y. {yr}", plural("class", total), ft.Icons.CALENDAR_MONTH_OUTLINED))
                        for subj in sorted(subjects, key=str.casefold):
                            items = subjects[subj]
                            controls.append(band(subj, plural("section", len(items)), ft.Icons.MENU_BOOK_OUTLINED,
                                                 sub=True))
                            controls += [build_item(i, x) for i, x in enumerate(items, start=1)]
                elif kind == "submissions":
                    by_class = {}
                    for x in shown:
                        cl = x[5]
                        by_class.setdefault(f"{cl['name']} — {cl['subject']}", []).append(x)
                    for cname in sorted(by_class, key=str.casefold):
                        citems = by_class[cname]
                        controls.append(band(cname, plural("submission", len(citems)), ft.Icons.SCHOOL_OUTLINED))
                        by_student = {}
                        for x in citems:
                            by_student.setdefault(student_of[id(x)], []).append(x)
                        for nm in sorted(by_student, key=str.casefold):
                            items = by_student[nm]
                            controls.append(band(nm, plural("submission", len(items)),
                                                 ft.Icons.PERSON_OUTLINE, sub=True))
                            controls += [build_item(i, x) for i, x in enumerate(items, start=1)]
                else:
                    groups = {}
                    for x in shown:
                        c = x[5]
                        groups.setdefault(f"{c['name']} — {c['subject']}", []).append(x)
                    for key in sorted(groups, key=str.casefold):
                        items = groups[key]
                        controls.append(band(key, plural(nouns[kind], len(items)), ft.Icons.SCHOOL_OUTLINED))
                        controls += [build_item(i, x) for i, x in enumerate(items, start=1)]
                list_col.controls = controls
            else:
                list_col.controls = [ft.Text("Nothing to show yet." if not entries else "No match for your search.",
                                             size=12, color=C("#748198"))]
            if push:
                page.update()

        search.on_change = render
        if class_dd is not None:
            fill_students()

            def on_class(e):
                fill_students()
                render()
            class_dd.on_change = on_class
            student_dd.on_change = render
        render(push=False)
        header = ft.Row([
            ft.Container(content=ft.Icon(icons[kind], size=24, color="#FFFFFF"), bgcolor=C("#3157D5"),
                         padding=12, border_radius=14),
            ft.Column([ft.Text(titles[kind], size=19, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                       ft.Text("Click an item to open its class", size=12, color=C("#748198"))],
                      spacing=2, expand=True),
            count_chip,
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        content = ft.Container(content=ft.Column(([ft.Row([class_dd, student_dd], spacing=10)] if class_dd is not None else [])
                                                 + [search, ft.Divider(height=1, color=C("#E7ECF4")), list_col],
                                                 spacing=12, tight=True), width=560)
        dlg = ft.AlertDialog(
            modal=True, title=header, content=content,
            actions=[compatible_button("Close", on_click=lambda e: close_dialog(dlg), icon=ft.Icons.CLOSE,
                                       style=ft.ButtonStyle(bgcolor=C("#3157D5"), color="#FFFFFF",
                                                            shape=ft.RoundedRectangleBorder(radius=10),
                                                            padding=pad_sym(18, 12)))],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=20), bgcolor=C("#FFFFFF"))
        open_control(page, dlg)
        page.update()

    def student_stat_dialog(kind):
        """Pop-up list behind a student dashboard number (classes, activities, submitted, graded)."""
        me = state["user"]
        enrolled = {e["class_id"] for e in read_rows("enrollments") if e["student_id"] == me["id"]}
        classes = [c for c in read_rows("classes") if c["id"] in enrolled and not is_archived(c)]
        class_ids = {c["id"] for c in classes}
        cmap = {c["id"]: c for c in classes}
        all_acts = {a["id"]: a for a in read_rows("activities")}
        counts = _student_counts()
        icons = {"classes": ft.Icons.SCHOOL_OUTLINED, "activities": ft.Icons.ASSIGNMENT_OUTLINED,
                 "submitted": ft.Icons.UPLOAD_FILE_OUTLINED, "graded": ft.Icons.QUERY_STATS_OUTLINED}
        titles = {"classes": "Joined classes", "activities": "Activities assigned",
                  "submitted": "Submitted work", "graded": "Graded work"}
        nouns = {"classes": "class", "activities": "activity", "submitted": "submission", "graded": "graded item"}
        accent = C("#3157D5", True)
        blue_bg = C("#EEF2FF")
        entries = []   # (title, subtitle, badge, badge_color, badge_bg, class_to_open)

        def class_of(class_id):
            return cmap.get(class_id) or by_id("classes", class_id)

        if kind == "classes":
            for c in sorted(classes, key=lambda c: ((c.get("school_year") or ""), c["name"].casefold(),
                                                    c["subject"].casefold())):
                entries.append((c["name"], f"{c['teacher_name']} • {plural('student', counts.get(c['id'], 0))}",
                                c["code"], accent, blue_bg, c))
        elif kind == "activities":
            acts = [a for a in all_acts.values() if a["class_id"] in class_ids and not is_record_item(a)]
            for a in sorted(acts, key=id_key, reverse=True):
                c = cmap[a["class_id"]]
                entries.append((f"{activity_label(a)}: {a['title']}",
                                f"{c['name']} — {c['subject']} • {a.get('term') or 'Midterm'} • "
                                f"Deadline: {a['deadline'] or 'None'}",
                                cat_of(a), accent, blue_bg, c))
        else:
            subs = [x for x in read_rows("submissions") if x["student_id"] == me["id"]]
            if kind == "graded":
                subs = [x for x in subs if x["score"] != ""]
            for x in sorted(subs, key=id_key, reverse=True):
                c = class_of(x["class_id"])
                if not c:
                    continue
                a = all_acts.get(x["activity_id"])
                what = f"{activity_label(a)}: {a['title']}" if a else "Activity"
                how = f"Submitted {x['submitted_at']}" if x["submitted_at"] else "Recorded by your teacher"
                if x["score"] == "":
                    badge, bcol, bbg = "Awaiting grade", C("#B54708"), C("#FEE4E2")
                elif is_excused(x["score"]):
                    badge, bcol, bbg = "EXC", C("#0D9488"), C("#E8F8F4")
                else:
                    total = f" / {fmt(a['max_points'])}" if a else ""
                    badge, bcol, bbg = f"{fmt(x['score'])}{total}", C("#0D9488"), C("#E8F8F4")
                entries.append((what, f"{c['name']} — {c['subject']} • {how}", badge, bcol, bbg, c))

        search = text_field("Search", width=540, hint="Type to filter the list")
        list_col = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, tight=True, height=360)
        count_chip = ft.Container(bgcolor=blue_bg, padding=pad_sym(9, 4), border_radius=10,
                                  content=ft.Text("", size=11, weight=ft.FontWeight.BOLD, color=accent))
        dlg = None

        def go(c):
            close_dialog(dlg)
            open_class(c)

        def build_item(i, e):
            title, sub, badge, bcol, bbg, c = e
            row = [ft.Text(str(i), size=11, color=C("#9AA5B5"), width=26),
                   ft.Container(content=ft.Icon(icons[kind], size=17, color=accent), bgcolor=blue_bg,
                                padding=9, border_radius=10),
                   ft.Column([ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                              ft.Text(sub, size=11, color=C("#748198"))], spacing=2, expand=True)]
            if badge:
                row.append(ft.Container(content=ft.Text(badge, size=11, weight=ft.FontWeight.BOLD, color=bcol),
                                        bgcolor=bbg, padding=pad_sym(10, 4), border_radius=10))
            return ft.Container(content=ft.Row(row, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=pad_sym(12, 9), bgcolor=C("#F7F9FD"), border_radius=12,
                                border=border_all(1, C("#E7ECF4")), ink=True,
                                tooltip="Click to open this class",
                                on_click=lambda ev, cl=c: go(cl))

        def render(e=None, push=True):
            q = (search.value or "").strip().casefold()
            shown = [x for x in entries if not q or q in f"{x[0]} {x[1]} {x[2]} {x[5]['subject']}".casefold()]
            n = len(shown)
            count_chip.content.value = plural(nouns[kind], n)
            if shown:
                controls = []

                def band(text, count_text, icon, sub=False):
                    return ft.Container(
                        content=ft.Row([
                            ft.Icon(icon, size=15 if sub else 16, color=accent if sub else "#FFFFFF"),
                            ft.Text(text, size=12, weight=ft.FontWeight.BOLD,
                                    color=accent if sub else "#FFFFFF", expand=True),
                            ft.Text(count_text, size=11, color=C("#748198") if sub else "#DCE6FF"),
                        ], spacing=8),
                        padding=pad_sym(12, 7 if sub else 8),
                        bgcolor=C("#E8EEFF") if sub else C("#3157D5"), border_radius=10,
                        margin=margin_only(top=4) if sub else None)

                if kind == "classes":
                    years = {}
                    for x in shown:
                        c = x[5]
                        years.setdefault(c.get("school_year") or "—", {}).setdefault(c["subject"], []).append(x)
                    for yr in sorted(years, reverse=True):
                        subjects = years[yr]
                        total = sum(len(v) for v in subjects.values())
                        controls.append(band(f"S.Y. {yr}", plural("class", total), ft.Icons.CALENDAR_MONTH_OUTLINED))
                        for subj in sorted(subjects, key=str.casefold):
                            items = subjects[subj]
                            controls.append(band(subj, plural("section", len(items)), ft.Icons.MENU_BOOK_OUTLINED,
                                                 sub=True))
                            controls += [build_item(i, x) for i, x in enumerate(items, start=1)]
                else:
                    groups = {}
                    for x in shown:
                        c = x[5]
                        groups.setdefault(f"{c['name']} — {c['subject']}", []).append(x)
                    for key in sorted(groups, key=str.casefold):
                        items = groups[key]
                        controls.append(band(key, plural(nouns[kind], len(items)), ft.Icons.SCHOOL_OUTLINED))
                        controls += [build_item(i, x) for i, x in enumerate(items, start=1)]
                list_col.controls = controls
            else:
                list_col.controls = [ft.Text("Nothing to show yet." if not entries else "No match for your search.",
                                             size=12, color=C("#748198"))]
            if push:
                page.update()

        search.on_change = render
        render(push=False)
        header = ft.Row([
            ft.Container(content=ft.Icon(icons[kind], size=24, color="#FFFFFF"), bgcolor=C("#3157D5"),
                         padding=12, border_radius=14),
            ft.Column([ft.Text(titles[kind], size=19, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                       ft.Text("Click an item to open its class", size=12, color=C("#748198"))],
                      spacing=2, expand=True),
            count_chip,
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        content = ft.Container(content=ft.Column([search, ft.Divider(height=1, color=C("#E7ECF4")), list_col],
                                                 spacing=12, tight=True), width=560)
        dlg = ft.AlertDialog(
            modal=True, title=header, content=content,
            actions=[compatible_button("Close", on_click=lambda e: close_dialog(dlg), icon=ft.Icons.CLOSE,
                                       style=ft.ButtonStyle(bgcolor=C("#3157D5"), color="#FFFFFF",
                                                            shape=ft.RoundedRectangleBorder(radius=10),
                                                            padding=pad_sym(18, 12)))],
            actions_alignment=ft.MainAxisAlignment.END,
            shape=ft.RoundedRectangleBorder(radius=20), bgcolor=C("#FFFFFF"))
        open_control(page, dlg)
        page.update()

    def dashboard():
        user = state["user"]
        if not user:
            login_view()
            return
        role = user["role"]
        first_name = (user["full_name"].split() or ["there"])[0]
        if role == "teacher":
            classes = [c for c in read_rows("classes") if c["teacher_id"] == user["id"] and not is_archived(c)]
            class_ids = {c["id"] for c in classes}
            enrollments = read_rows("enrollments")
            activities = [a for a in read_rows("activities") if a["class_id"] in class_ids and not is_record_item(a)]
            submissions = [s for s in read_rows("submissions") if s["class_id"] in class_ids]
            body = ft.Column([
                section_title(f"Welcome, {first_name} 👋", "Here is what's happening in your classroom."),
                ft.ResponsiveRow([
                    stat_card("Classes created", len(classes), ft.Icons.SCHOOL_OUTLINED,
                              on_click=lambda e: teacher_stat_dialog("classes")),
                    stat_card("Students enrolled", sum(1 for e in enrollments if e["class_id"] in class_ids),
                              ft.Icons.GROUP_OUTLINED, C("#0D9488"),
                              on_click=lambda e: teacher_stat_dialog("students")),
                    stat_card("Activities", len(activities), ft.Icons.ASSIGNMENT_OUTLINED, C("#7C3AED"),
                              on_click=lambda e: teacher_stat_dialog("activities")),
                    stat_card("Submissions", len(submissions), ft.Icons.UPLOAD_FILE_OUTLINED, C("#D97706"),
                              on_click=lambda e: teacher_stat_dialog("submissions")),
                ], spacing=14, run_spacing=14),
                card(ft.Column([
                    ft.Text("Quick actions", size=17, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                    ft.Text("Manage your classes, post learning materials, and review student work.",
                            size=12, color=C("#748198")),
                    ft.Row([
                        button("Create a class", lambda e: create_class_dialog(), ft.Icons.ADD, True),
                        button("Open my classes", lambda e: teacher_classes(), ft.Icons.SCHOOL_OUTLINED),
                        button("Record sheet", lambda e: record_sheet_view(), ft.Icons.EDIT_NOTE),
                        button("Grade settings", lambda e: grade_settings_view(), ft.Icons.TUNE),
                        button("Grade sheet", lambda e: choose_grade_class(), ft.Icons.ASSESSMENT_OUTLINED),
                        button("Reports", lambda e: reports_view(), ft.Icons.SUMMARIZE_OUTLINED),
                    ], wrap=True, spacing=10),
                ], spacing=12), padding=22),
                section_title("Your classes", "Open a class to manage its content."),
                class_cards(classes, teacher=True),
            ], spacing=18, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        elif role == "admin":
            users = read_rows("users")
            body = ft.Column([
                section_title(f"Welcome, {first_name} 👋",
                              "Manage the school years, class sections and subjects teachers can choose from."),
                ft.ResponsiveRow([
                    stat_card("Teachers", sum(1 for u in users if u["role"] == "teacher"),
                              ft.Icons.PERSON_OUTLINE, C("#7C3AED"), ADMIN_COLS,
                              lambda e: admin_stat_dialog("teachers")),
                    stat_card("Students", sum(1 for u in users if u["role"] == "student"),
                              ft.Icons.GROUP_OUTLINED, C("#0D9488"), ADMIN_COLS,
                              lambda e: admin_stat_dialog("students")),
                    stat_card("Classes", len(read_rows("classes")), ft.Icons.SCHOOL_OUTLINED,
                              cols=ADMIN_COLS, on_click=lambda e: admin_stat_dialog("classes")),
                    stat_card("School years",
                              sum(1 for y in read_rows("school_years") if y.get("active") != "0"),
                              ft.Icons.CALENDAR_MONTH_OUTLINED, C("#0D9488"), ADMIN_COLS,
                              lambda e: admin_stat_dialog("years")),
                    stat_card("Active sections",
                              sum(1 for s in read_rows("sections") if s.get("active") != "0"),
                              ft.Icons.GROUPS_OUTLINED, C("#D97706"), ADMIN_COLS,
                              lambda e: admin_stat_dialog("sections")),
                    stat_card("Subjects", len(read_rows("subjects")), ft.Icons.MENU_BOOK_OUTLINED, C("#DB2777"),
                              ADMIN_COLS, lambda e: admin_stat_dialog("subjects")),
                ], spacing=14, run_spacing=14),
                card(ft.Column([
                    ft.Text("Admin tools", size=17, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                    ft.Text("Teachers can only create classes from the active school years, sections and subjects you add here.",
                            size=12, color=C("#748198")),
                    ft.Column([
                        ft.Row([
                            fill_button("Manage school years", lambda e: admin_manage_view("school_years"),
                                        ft.Icons.CALENDAR_MONTH_OUTLINED, True),
                            fill_button("Manage courses", lambda e: courses_view(), ft.Icons.WORKSPACES_OUTLINED, True),
                            fill_button("Manage class sections", lambda e: admin_manage_view("sections"),
                                        ft.Icons.GROUPS_OUTLINED, True),
                            fill_button("Manage class subjects", lambda e: admin_manage_view("subjects"),
                                        ft.Icons.MENU_BOOK_OUTLINED, True),
                        ], spacing=10),
                        ft.Row([
                            fill_button("Manage users", lambda e: admin_users_view(), ft.Icons.ALTERNATE_EMAIL),
                            fill_button("Reports", lambda e: admin_reports_view(), ft.Icons.SUMMARIZE_OUTLINED),
                            fill_button("School settings", lambda e: school_settings_view(), ft.Icons.SETTINGS_OUTLINED),
                            fill_button("Back up data", lambda e: backup_data(), ft.Icons.SAVE_OUTLINED),
                        ], spacing=10),
                        ft.Row([
                            fill_button("Restore backup", lambda e: restore_data(), ft.Icons.RESTORE),
                            fill_button("Activity log", lambda e: activity_log_view(), ft.Icons.HISTORY),
                            fill_button("Edit my profile", lambda e: profile_dialog(), ft.Icons.PERSON_OUTLINE),
                            fill_button("Change my password", lambda e: change_password_dialog(), ft.Icons.LOCK_OUTLINE),
                        ], spacing=10),
                    ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                ], spacing=12), padding=22),
            ], spacing=18, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        else:
            enrollments = [e for e in read_rows("enrollments") if e["student_id"] == user["id"]]
            class_ids = {e["class_id"] for e in enrollments}
            classes = [c for c in read_rows("classes") if c["id"] in class_ids and not is_archived(c)]
            class_ids = {c["id"] for c in classes}
            activities = [a for a in read_rows("activities") if a["class_id"] in class_ids and not is_record_item(a)]
            subs = [s for s in read_rows("submissions") if s["student_id"] == user["id"]]
            graded = [s for s in subs if s["score"] != ""]
            body = ft.Column([
                section_title(f"Welcome, {first_name} 👋",
                              "Keep track of your classes, activities, and progress."),
                ft.ResponsiveRow([
                    stat_card("Joined classes", len(classes), ft.Icons.SCHOOL_OUTLINED,
                              on_click=lambda e: student_stat_dialog("classes")),
                    stat_card("Activities assigned", len(activities), ft.Icons.ASSIGNMENT_OUTLINED, C("#7C3AED"),
                              on_click=lambda e: student_stat_dialog("activities")),
                    stat_card("Submitted work", len(subs), ft.Icons.UPLOAD_FILE_OUTLINED, C("#0D9488"),
                              on_click=lambda e: student_stat_dialog("submitted")),
                    stat_card("Graded work", len(graded), ft.Icons.QUERY_STATS_OUTLINED, C("#D97706"),
                              on_click=lambda e: student_stat_dialog("graded")),
                ], spacing=14, run_spacing=14),
                card(ft.Column([
                    ft.Text("Join a class", size=17, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                    ft.Text("Enter the six-character class code or paste the invite link from your teacher.",
                            size=12, color=C("#748198")),
                    join_class_controls(),
                ], spacing=12), padding=22),
                section_title("Your classes", "Select a class to view announcements and submit activities."),
                class_cards(classes, teacher=False, after=dashboard),
            ], spacing=18, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        shell("Dashboard", "Your learning workspace", body, "dashboard")

    def leave_class(c, after):
        def do():
            for e in read_rows("enrollments"):
                if e["class_id"] == c["id"] and e["student_id"] == state["user"]["id"]:
                    remove_row("enrollments", e["id"])
            log_event("class", "Left class", f"{c['name']} - {c['subject']}", c["id"])
            if state["class"] and state["class"]["id"] == c["id"]:
                state["class"] = None
            after()
            toast(f"You left {c['name']}.")
        ask_confirm("Leave class", f"Leave \"{c['name']} — {c['subject']}\"? "
                                   "You can rejoin later with the class code.", do)

    def class_cards(classes, teacher, after=None):
        if not classes:
            return empty_card(ft.Icons.SCHOOL_OUTLINED, "No classes yet",
                              "Create a class or join one using a class code.")
        after = after or (teacher_classes if teacher else student_classes)
        all_enrollments = read_rows("enrollments")
        unread = {} if teacher else unread_announcements(state["user"]["id"])
        cards = []
        for c in classes:
            count = sum(1 for e in all_enrollments if e["class_id"] == c["id"])
            buttons = [button("Open class", lambda e, item=c: open_class(item),
                              ft.Icons.ARROW_FORWARD_ROUNDED, True)]
            if not teacher:
                buttons.append(button("Leave", lambda e, item=c: leave_class(item, after), ft.Icons.EXIT_TO_APP))
            cards.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Container(content=ft.Icon(ft.Icons.MENU_BOOK_ROUNDED, color=C("#3157D5", True)),
                                     bgcolor=C("#EEF2FF"), padding=10, border_radius=12),
                        ft.Row(([ft.Container(content=ft.Text("Archived", size=11, weight=ft.FontWeight.BOLD,
                                                              color=C("#B54708")),
                                              bgcolor=C("#FEE4E2"), padding=pad_sym(8, 4), border_radius=8)]
                                if is_archived(c) else []) +
                               ([ft.Container(content=ft.Text(f"{len(unread[c['id']])} new", size=11,
                                                              weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                                              bgcolor=C("#E5484D"), padding=pad_sym(8, 4), border_radius=8)]
                                if c["id"] in unread else []) +
                               [ft.Container(content=ft.Text(c["code"], size=11, weight=ft.FontWeight.BOLD,
                                                             color=C("#3157D5", True)),
                                             bgcolor=C("#EEF2FF"), padding=8, border_radius=8)], spacing=6),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(c["name"], size=17, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                    ft.Text(f"{c['subject']}  •  S.Y. {c.get('school_year') or '—'}", size=12, color=C("#748198")),
                    ft.Row([
                        ft.Icon(ft.Icons.GROUP_OUTLINED, size=15, color=C("#748198")),
                        ft.Text(f"{count} students" if teacher else c["teacher_name"], size=11, color=C("#748198")),
                    ], spacing=5),
                    ft.Row(buttons, wrap=True, spacing=6, run_spacing=6),
                ], spacing=10),
                col={"xs": 12, "sm": 6, "lg": 4, "xxl": 3}, padding=18, bgcolor=C("#FFFFFF"), border_radius=16,
                border=border_all(1, C("#E7ECF4")),
            ))
        return ft.ResponsiveRow(cards, spacing=14, run_spacing=14)

    def join_class_controls():
        code = text_field("Class code or invite link", width=300, hint="e.g. A1B2C3")

        def join(_):
            value = extract_code(code.value)
            c = next((x for x in read_rows("classes") if x["code"] == value), None)
            if not c or is_archived(c):
                toast("No class was found for that code.", True)
                return
            if any(e["class_id"] == c["id"] and e["student_id"] == state["user"]["id"]
                   for e in read_rows("enrollments")):
                toast("You are already enrolled in this class.")
                return

            def do():
                add_row("enrollments", {"id": next_id("enrollments"), "class_id": c["id"],
                                        "student_id": state["user"]["id"],
                                        "student_name": state["user"]["full_name"], "joined_at": timestamp()})
                log_event("class", "Joined class", f"{c['name']} - {c['subject']}", c["id"])
                student_classes()
                toast(f"You joined {c['name']}.")
            ask_confirm("Join class", f"Join \"{c['name']} — {c['subject']}\" with {c['teacher_name']}?", do)

        code.on_submit = join
        return ft.Row([code, button("Join class", join, ft.Icons.ADD_LINK, True)], wrap=True, spacing=10)

    def show_class_code(c, title="Class code"):
        show_dialog(title, ft.Column([
            ft.Text("Share this code or the invite link with your students."),
            ft.Container(content=ft.Text(c["code"], size=28, weight=ft.FontWeight.BOLD, color=C("#3157D5", True)),
                         bgcolor=C("#EEF2FF"), padding=18, border_radius=12, alignment=center_alignment()),
            ft.Text(invite_link(c["code"]), selectable=True, size=12, color=C("#526078")),
            ft.Row([
                button("Copy code", lambda e: copy_text(c["code"], "Class code copied."), ft.Icons.CONTENT_COPY),
                button("Copy invite link", lambda e: copy_text(invite_link(c["code"]), "Invite link copied."),
                       ft.Icons.LINK),
                button("Copy invite message", lambda e: copy_text(invite_text(c), "Invite message copied."),
                       ft.Icons.MESSAGE_OUTLINED),
            ], wrap=True, spacing=8),
        ], tight=True, spacing=12))

    def create_class_dialog():
        years = sorted([y for y in read_rows("school_years") if y.get("active") != "0"],
                       key=lambda r: r["name"], reverse=True)
        sections = sorted([s for s in read_rows("sections") if s.get("active") != "0"],
                          key=lambda r: r["name"].casefold())
        subjects = sorted([x for x in read_rows("subjects") if x.get("active") != "0"],
                          key=lambda r: r["name"].casefold())
        if not years or not sections or not subjects:
            toast("The admin must add active school years, class sections and subjects first.", True)
            return
        year_dd = ft.Dropdown(label="School year", width=360, border_radius=12, filled=True,
                              bgcolor=C("#FFFFFF"), options=[ft.dropdown.Option(y["name"]) for y in years])
        section = ft.Dropdown(label="Class section", width=360, border_radius=12, filled=True,
                              bgcolor=C("#FFFFFF"),
                              options=[ft.dropdown.Option(r["id"], r["name"]) for r in sections])
        subject = ft.Dropdown(label="Subject (choose a section first)", width=360, border_radius=12, filled=True,
                              bgcolor=C("#FFFFFF"), options=[], disabled=True)
        dlg = None

        def fill_subjects(e=None):
            sec = next((x for x in sections if x["id"] == section.value), None)
            course = section_course(sec["name"]) if sec else ""
            if not sec:
                fit = []
            elif course in get_courses():
                fit = [r for r in subjects if subject_fits_course(r, course)]
            else:
                fit = subjects   # section not named after a known course: show everything
            subject.options = [ft.dropdown.Option(r["name"]) for r in fit]
            subject.value = None
            subject.disabled = not sec
            subject.label = (f"Subject ({course} and general subjects)" if sec and course in get_courses()
                             else "Subject" if sec else "Subject (choose a section first)")
            page.update()
            if sec and not fit:
                toast(f"No subjects for {course} yet. Ask the admin to add some.", True)

        section.on_change = fill_subjects

        def save(_):
            sec = next((s for s in sections if s["id"] == section.value), None)
            s = subject.value
            if not year_dd.value or not sec or not s:
                toast("Choose a school year, a class section and a subject.", True)
                return
            n, sy = sec["name"], year_dd.value
            if any(c["teacher_id"] == state["user"]["id"] and c["name"] == n and c["subject"] == s
                   and (c.get("school_year") or "") == sy for c in read_rows("classes")):
                toast("You already have a class with that section, school year and subject.", True)
                return

            def do():
                code = unique_code({c["code"] for c in read_rows("classes")})
                row = {"id": next_id("classes"), "code": code, "name": n, "subject": s, "school_year": sy,
                       "teacher_id": state["user"]["id"], "teacher_name": state["user"]["full_name"],
                       "created_at": timestamp()}
                add_row("classes", row)
                log_event("class", "Class created", f"{n} - {s} (S.Y. {sy})", row["id"])
                state["sy_filter"] = sy or "none"
                close_dialog(dlg)
                dashboard()
                show_class_code(row, "Class created")
            ask_confirm("Create class", f"Create {n} ({sy}) — {s}?", do)

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Create a class"),
            content=ft.Column([year_dd, section, subject], tight=True, spacing=12, width=380),
            actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                     compatible_button("Create class", on_click=save)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        open_control(page, dlg)
        page.update()

    def school_year_filter(classes, teacher, after=None):
        """Dropdown of school years + the class cards for the chosen year."""
        found = {c.get("school_year") or "none" for c in classes}
        years = sorted((y for y in found if y != "none"), reverse=True) + (["none"] if "none" in found else [])
        chosen = state.get("sy_filter")
        if chosen != "all" and chosen not in years:
            chosen = years[0] if years else "all"   # default: the latest school year
        state["sy_filter"] = chosen
        holder = ft.Container()
        count = ft.Text("", size=12, color="#748198")

        def label(y):
            return "No school year" if y == "none" else f"S.Y. {y}"

        def show(push=True):
            picked = [c for c in classes if chosen == "all" or (c.get("school_year") or "none") == chosen]
            count.value = (f"{len(picked)} class(es) in {label(chosen)}" if chosen != "all"
                           else f"{len(picked)} class(es) in all school years")
            holder.content = class_cards(picked, teacher=teacher, after=after)
            if push:
                page.update()

        def changed(e):
            nonlocal chosen
            chosen = year_dd.value
            state["sy_filter"] = chosen
            show()

        year_dd = ft.Dropdown(label="School year", width=240, value=chosen,
                              options=[ft.dropdown.Option("all", "All school years")] +
                                      [ft.dropdown.Option(y, label(y)) for y in years])
        year_dd.on_change = changed
        show(push=False)
        if not classes:
            return holder
        return ft.Column([ft.Row([year_dd, count], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                          holder], spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def default_class(classes):
        """The class to preselect: the one the teacher is in, else the first class of the newest school year."""
        cur = state.get("class")
        if cur and any(x["id"] == cur["id"] for x in classes):
            return cur
        return sorted(classes, key=lambda c: c.get("school_year") or "", reverse=True)[0]

    def year_class_dropdowns(classes, current, year_kw=None, class_kw=None, subject_first=False):
        """A School year dropdown plus a Class dropdown that only lists that year's classes.
        Returns (year_dd, class_dd, fill): call fill() after the year changes."""
        def yr(c):
            return c.get("school_year") or "none"
        years = sorted({yr(c) for c in classes if yr(c) != "none"}, reverse=True)
        if any(yr(c) == "none" for c in classes):
            years.append("none")
        year_dd = ft.Dropdown(label="School year", value=yr(current),
                              options=[ft.dropdown.Option(y, "No school year" if y == "none" else y) for y in years],
                              **(year_kw or {}))
        class_dd = ft.Dropdown(label="Class", **(class_kw or {}))

        def fill(keep=None):
            inyear = sorted((c for c in classes if yr(c) == year_dd.value),
                            key=(lambda c: (c["subject"].casefold(), c["name"].casefold())) if subject_first
                            else (lambda c: (c["name"].casefold(), c["subject"].casefold())))
            class_dd.options = [ft.dropdown.Option(c["id"], f"{c['subject']} — {c['name']}" if subject_first
                                                   else f"{c['name']} — {c['subject']}") for c in inyear]
            ids = {c["id"] for c in inyear}
            class_dd.value = keep if keep in ids else (inyear[0]["id"] if inyear else None)

        fill(current["id"])
        return year_dd, class_dd, fill

    def my_classes():
        """The teacher's active classes (plus the class they are currently inside, even if archived)."""
        mine = [c for c in read_rows("classes") if c["teacher_id"] == state["user"]["id"]]
        cur = state.get("class")
        return [c for c in mine if not is_archived(c) or (cur and cur["id"] == c["id"])]

    def teacher_classes():
        every = [c for c in read_rows("classes") if c["teacher_id"] == state["user"]["id"]]
        archived_count = sum(1 for c in every if is_archived(c))
        show_archived = bool(state.get("show_archived"))
        classes = every if show_archived else [c for c in every if not is_archived(c)]

        def toggle(e):
            state["show_archived"] = bool(archived_switch.value)
            teacher_classes()

        archived_switch = ft.Switch(label=f"Show archived classes ({archived_count})", value=show_archived,
                                    on_change=toggle)
        body = ft.Column([
            ft.Row([
                section_title("My classes", "Create, open, and manage your classrooms."),
                button("Create class", lambda e: create_class_dialog(), ft.Icons.ADD, True),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            *([archived_switch] if archived_count else []),
            school_year_filter(classes, teacher=True),
        ], spacing=18, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        shell("My classes", "Teacher workspace", body, "classes")

    def student_classes():
        enrolled_ids = {e["class_id"] for e in read_rows("enrollments") if e["student_id"] == state["user"]["id"]}
        classes = [c for c in read_rows("classes") if c["id"] in enrolled_ids and not is_archived(c)]
        body = ft.Column([
            section_title("My classes", "Your enrolled classrooms."),
            card(ft.Column([ft.Text("Join another class", weight=ft.FontWeight.BOLD),
                            join_class_controls()], spacing=10), padding=18),
            school_year_filter(classes, teacher=False, after=student_classes),
        ], spacing=18, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        shell("My classes", "Student workspace", body, "classes")

    def open_class(class_row):
        state["class"] = class_row
        if state["user"]["role"] == "teacher":
            teacher_class_view()
        else:
            student_class_view()

    def class_top(c, teacher=False):
        controls = [
            ft.Row([
                ft.Container(content=ft.Icon(ft.Icons.MENU_BOOK_ROUNDED, color=C("#3157D5", True), size=25),
                             bgcolor=C("#EEF2FF"), padding=12, border_radius=14),
                ft.Column([
                    ft.Text(c["name"], size=21, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                    ft.Text(f"{c['subject']}  •  S.Y. {c.get('school_year') or '—'}", color=C("#748198"), size=12),
                ], spacing=3, expand=True),
                ft.Container(content=ft.Text(f"CODE  {c['code']}", color=C("#3157D5", True),
                                              weight=ft.FontWeight.BOLD, size=12),
                             bgcolor=C("#EEF2FF"), padding=12, border_radius=10),
            ]),
            ft.Text(f"Teacher: {c['teacher_name']}", size=12, color=C("#748198")),
        ]
        if teacher:
            controls.append(ft.Row([
                button("Copy code", lambda e: copy_text(c["code"], "Class code copied."), ft.Icons.CONTENT_COPY),
                button("Copy invite link", lambda e: copy_text(invite_link(c["code"]), "Invite link copied."),
                       ft.Icons.LINK),
                button("Copy invite message", lambda e: copy_text(invite_text(c), "Invite message copied."),
                       ft.Icons.MESSAGE_OUTLINED),
            ], wrap=True, spacing=8, run_spacing=8))
            controls.append(ft.Text(f"Invite link: {invite_link(c['code'])}", size=11, color=C("#748198"),
                                    selectable=True))
        return card(ft.Column(controls, spacing=12), padding=18)

    def teacher_class_view():
        c = state["class"]
        buttons = ft.Row([
            button("Post announcement", lambda e: announcement_dialog(), ft.Icons.CAMPAIGN_OUTLINED, True),
            button("Create activity", lambda e: activity_dialog(), ft.Icons.ASSIGNMENT_OUTLINED),
            button("Submissions & grading", lambda e: manage_submissions_view()),
            button("Record sheet", lambda e: record_sheet_view(), ft.Icons.EDIT_NOTE),
            button("Grade settings", lambda e: grade_settings_view(), ft.Icons.TUNE),
            button("Grade sheet", lambda e: grade_sheet_view()),
            button("Reports", lambda e: reports_view(), ft.Icons.SUMMARIZE_OUTLINED),
            button("Students", lambda e: enrolled_students_view()),
            (button("Restore class", lambda e: restore_class(c), ft.Icons.UNARCHIVE_OUTLINED, True)
             if is_archived(c) else
             button("Archive class", lambda e: archive_class(c), ft.Icons.ARCHIVE_OUTLINED)),
        ], wrap=True, spacing=8, run_spacing=8)
        body = ft.Column([
            ft.Row([button("Back to classes", lambda e: teacher_classes(), ft.Icons.ARROW_BACK),
                    ft.Container(expand=True),
                    button("Dashboard", lambda e: dashboard(), ft.Icons.DASHBOARD_OUTLINED)], spacing=8),
            class_top(c, teacher=True),
            *([ft.Container(content=ft.Row([ft.Icon(ft.Icons.ARCHIVE_OUTLINED, color=C("#B54708")),
                                           ft.Text("This class is archived. It is hidden from students and from your "
                                                   "class lists. Use \"Restore class\" to make it active again.",
                                                   size=12, color=C("#B54708"), expand=True)], spacing=10),
                            padding=12, border_radius=12, bgcolor=C("#FEE4E2"))] if is_archived(c) else []),
            buttons,
            class_feed(teacher=True),
        ], spacing=14, scroll=ft.ScrollMode.AUTO)
        shell(c["name"], "Manage classroom content and student work", body, "classes")

    def student_class_view():
        c = state["class"]
        state["fresh_ann"] = set(unread_announcements(state["user"]["id"]).get(c["id"], []))
        mark_announcements_seen(state["user"]["id"], c["id"])
        body = ft.Column(
            controls=[
                ft.Row([
                    button("Back to classes", lambda e: student_classes(), ft.Icons.ARROW_BACK),
                    ft.Container(expand=True),
                    button("My submissions", lambda e: student_work_view()),
                    button("My scores", lambda e: student_score_view()),
                    button("Leave class", lambda e: leave_class(c, student_classes), ft.Icons.EXIT_TO_APP),
                ], spacing=8),
                class_top(c),
                class_feed(teacher=False),
            ],
            spacing=14, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        shell(c["name"], "Announcements, learning materials, and activities", body, "classes")

    def class_feed(teacher):
        c = state["class"]
        announcements = [a for a in read_rows("announcements") if a["class_id"] == c["id"]]
        activities = [a for a in read_rows("activities") if a["class_id"] == c["id"] and not is_record_item(a)]
        items = []
        for a in sorted(announcements, key=id_key, reverse=True):
            fresh = (not teacher) and a["id"] in state.get("fresh_ann", set())
            items.append(("Announcement", ("NEW - " if fresh else "") + a["title"], a["description"],
                          a["posted_at"], a,
                          ft.Icons.CAMPAIGN_OUTLINED, False))
        for a in sorted(activities, key=id_key, reverse=True):
            detail = (f"{cat_of(a)} • {a.get('term') or 'Midterm'} • Max points: {fmt(a['max_points'])} • "
                      f"Deadline: {a['deadline'] or 'None'}")
            items.append((cat_of(a), f"{activity_label(a)}: {a['title']}", detail, a["created_at"], a,
                          ft.Icons.ASSIGNMENT_OUTLINED, True))
        items.sort(key=lambda x: x[3], reverse=True)
        if not items:
            return empty_card(ft.Icons.INBOX_OUTLINED, "Nothing posted yet",
                              "Announcements and activities will appear here.")
        controls = [ft.Text("Class feed", size=18, weight=ft.FontWeight.BOLD, color=C("#18243A"))]
        for kind, title, desc, date, row, icon, is_act in items:
            actions = [ft.TextButton("Open", on_click=lambda e, r=row, k=kind: item_dialog(r, k, teacher))]
            if row.get("link"):
                actions.append(ft.TextButton("Open link", icon=ft.Icons.LINK,
                                             on_click=lambda e, u=row["link"]: open_link(u)))
            if teacher and not is_act:
                actions += [
                    ft.TextButton("Edit", on_click=lambda e, r=row: announcement_dialog(r)),
                    ft.TextButton("Delete", on_click=lambda e, r=row: delete_announcement(r)),
                ]
            if teacher and is_act:
                actions += [
                    ft.TextButton("Edit", on_click=lambda e, r=row: activity_dialog(r)),
                    ft.TextButton("Delete", on_click=lambda e, r=row: delete_activity(r)),
                ]
            desc = desc or ""
            controls.append(card(ft.Column([
                ft.Row([
                    ft.Container(content=ft.Icon(icon, color=C("#3157D5", True), size=20),
                                 bgcolor=C("#EEF2FF"), padding=10, border_radius=12),
                    ft.Column([
                        ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                        ft.Text(f"{kind}  •  {date}", size=10, color=C("#748198")),
                    ], spacing=3, expand=True),
                ], spacing=12),
                ft.Text(desc[:220] + ("…" if len(desc) > 220 else ""), size=12, color=C("#526078")),
                *([ft.Row([ft.Icon(ft.Icons.LINK, size=15, color=C("#3157D5", True)),
                           ft.Text(link_site(row["link"]), size=11, color=C("#3157D5", True))], spacing=5)]
                  if row.get("link") else []),
                ft.Row(actions, wrap=True, spacing=6),
            ], spacing=10), padding=16))
        return ft.Column(controls, spacing=10)

    def item_dialog(row, kind, teacher):
        is_activity = "instructions" in row
        dlg = None
        heading = f"{activity_label(row)}: {row['title']}" if is_activity else row["title"]
        body_controls = [
            ft.Text(heading, size=19, weight=ft.FontWeight.BOLD, color=C("#18243A")),
            ft.Text((row["instructions"] if is_activity else row["description"]) or "",
                    selectable=True, size=13),
        ]
        actions = [ft.TextButton("Close", on_click=lambda e: close_dialog(dlg))]
        if is_activity:
            body_controls += [
                ft.Text(f"Type: {cat_of(row)}   •   Term: {row.get('term') or 'Midterm'}"),
                ft.Text(f"Maximum points: {fmt(row['max_points'])}"),
                ft.Text(f"Deadline: {row['deadline'] or 'No deadline'}"),
            ]
        if row.get("link"):
            body_controls.append(ft.Text(row["link"], size=12, color=C("#3157D5", True), selectable=True))
            body_controls.append(ft.Row([
                button("Open link", lambda e, u=row["link"]: open_link(u), ft.Icons.OPEN_IN_NEW, True),
                button("Copy link", lambda e, u=row["link"]: copy_text(u, "Link copied."), ft.Icons.CONTENT_COPY),
            ], wrap=True, spacing=8))
        path = row.get("file_path", "")
        if path:
            body_controls.append(ft.Text(f"Attachment: {Path(path).name}", size=12, color=C("#748198")))
            body_controls.append(button("Open attachment", lambda e, p=path: show_open_file(p), ft.Icons.OPEN_IN_NEW))
            body_controls.append(button("Copy file path", lambda e, p=path: copy_text(resolve_path(p), "File path copied to clipboard."),
                                        ft.Icons.CONTENT_COPY))
        if is_activity and not teacher:
            sub = next((s for s in read_rows("submissions") if s["activity_id"] == row["id"]
                        and s["student_id"] == state["user"]["id"]), None)
            closed = deadline_passed(row)
            has_file = bool(sub and sub["file_path"])
            body_controls.append(ft.Divider())
            body_controls.append(ft.Text("Your submission", weight=ft.FontWeight.BOLD))
            if has_file:
                body_controls += [
                    ft.Text(f"File: {Path(sub['file_path']).name}", size=12),
                    ft.Text(f"Submitted: {sub['submitted_at'] or '—'}", size=12, color=C("#748198")),
                    button("Open my submitted file", lambda e, p=sub["file_path"]: show_open_file(p),
                           ft.Icons.OPEN_IN_NEW),
                ]
            else:
                body_controls.append(ft.Text("You have not submitted a file yet.", size=12, color=C("#748198")))
            if sub and sub["score"] != "":
                body_controls.append(ft.Text(f"Score: {fmt(sub['score'])} / {fmt(row['max_points'])}",
                                             weight=ft.FontWeight.BOLD, color=C("#0D9488")))
            if closed:
                body_controls.append(ft.Text("The deadline has passed. Submissions are closed.",
                                             color=C("#B42318"), weight=ft.FontWeight.BOLD))
            else:
                def go_submit(e):
                    close_dialog(dlg)
                    submit_activity(row)
                actions.insert(0, compatible_button("Resubmit" if has_file else "Submit activity",
                                                    on_click=go_submit))
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Activity" if is_activity else kind),
            content=ft.Container(content=ft.Column(body_controls, tight=True, spacing=10,
                                                   scroll=ft.ScrollMode.AUTO), width=600),
            actions=actions, actions_alignment=ft.MainAxisAlignment.END,
        )
        open_control(page, dlg)
        page.update()

    def open_link(url):
        try:
            url = normalize_link(url)
            if not url:
                raise ValueError("There is no link to open.")
            if not webbrowser.open(url):
                page.launch_url(url)
        except Exception as exc:
            toast(f"Could not open the link: {exc}", True)

    def show_open_file(path):
        ok, message = open_path(path)
        toast(message, not ok)

    def pick_file(callback):
        selected_path = native_file_dialog(
            "open", title="Choose a file",
            filetypes=[
                ["All files", "*.*"],
                ["Documents", "*.pdf *.doc *.docx *.ppt *.pptx *.xls *.xlsx *.txt"],
                ["Images", "*.png *.jpg *.jpeg *.gif *.bmp"],
            ],
        )
        if selected_path:
            callback(selected_path)

    def announcement_dialog(existing=None):
        title = text_field("Announcement title", width=560, value=existing["title"] if existing else "")
        desc = text_field("Description", width=560, multiline=True, value=existing["description"] if existing else "")
        link_field = text_field("Link (optional) — e.g. a YouTube video", width=560,
                                value=(existing.get("link") or "") if existing else "",
                                hint="https://www.youtube.com/watch?v=...")
        file_label = ft.Text(Path(existing["file_path"]).name if existing and existing.get("file_path")
                             else "No attachment selected", size=11, color=C("#748198"))
        chosen = {"path": existing.get("file_path", "") if existing else "", "new": False}
        dlg = None

        def browse(_):
            def got(path):
                chosen["path"] = path
                chosen["new"] = True
                file_label.value = Path(path).name
                page.update()
            pick_file(got)

        def save(_):
            t, d = (title.value or "").strip(), (desc.value or "").strip()
            if not t or not d:
                toast("Title and description are required.", True)
                return
            try:
                link = normalize_link(link_field.value)
            except ValueError as exc:
                toast(str(exc), True)
                return

            def do():
                selected = chosen["path"]
                try:
                    if selected and chosen["new"]:
                        prefix = f"ann{existing['id'] if existing else next_id('announcements')}"
                        selected = copy_attachment(selected, FILES_DIR, prefix)
                    data = {"title": t, "description": d, "file_path": selected, "link": link}
                    if existing:
                        update_row("announcements", existing["id"], data)
                    else:
                        data.update({"id": next_id("announcements"), "class_id": state["class"]["id"],
                                     "posted_at": timestamp()})
                        add_row("announcements", data)
                    log_event("class", "Announcement saved" if existing else "Announcement posted", t,
                              state["class"]["id"])
                    close_dialog(dlg)
                    teacher_class_view()
                    toast("Announcement saved.")
                except Exception as exc:
                    toast(f"Could not save announcement: {exc}", True)
            ask_confirm("Save announcement", "Save this announcement?" if existing else "Post this announcement to the class?", do)

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Edit announcement" if existing else "Post announcement"),
            content=ft.Container(content=ft.Column([
                title, desc, link_field,
                ft.Row([button("Choose attachment", browse, ft.Icons.ATTACH_FILE), file_label], wrap=True),
            ], tight=True, spacing=12, scroll=ft.ScrollMode.AUTO), width=600),
            actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                     compatible_button("Save announcement", on_click=save)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        open_control(page, dlg)
        page.update()

    def delete_announcement(row):
        def do_delete():
            remove_row("announcements", row["id"])
            log_event("class", "Announcement deleted", row["title"], row["class_id"])
            teacher_class_view()
            toast("Announcement deleted.")
        ask_confirm("Delete announcement", "This announcement will be removed from the class feed.", do_delete)

    def delete_activity(row):
        def do_delete():
            remove_row("activities", row["id"])
            write_rows("submissions", [s for s in read_rows("submissions") if s["activity_id"] != row["id"]])
            log_event("class", "Activity deleted", f"{activity_label(row)}: {row['title']}", row["class_id"])
            teacher_class_view()
            toast("Activity deleted.")
        ask_confirm("Delete activity",
                    f"Delete \"{activity_label(row)}: {row['title']}\"? All student submissions and scores "
                    "for it will be removed too.", do_delete)

    def activity_dialog(existing=None):
        c = state["class"]
        title = text_field("Topic / title", width=560, value=existing["title"] if existing else "")
        category = ft.Dropdown(label="Assessment type", value=cat_of(existing) if existing else "Activity",
                               width=275, options=[ft.dropdown.Option(x) for x in CATEGORIES],
                               border_radius=12, filled=True, bgcolor=C("#FFFFFF"))
        term = ft.Dropdown(label="Term", value=(existing.get("term") if existing else None) or state["term"],
                           width=275, options=[ft.dropdown.Option(x) for x in TERMS],
                           border_radius=12, filled=True, bgcolor=C("#FFFFFF"))
        points = text_field("Maximum points", width=560, value=fmt(existing["max_points"]) if existing else "100")
        label_preview = ft.Text("", size=13, weight=ft.FontWeight.BOLD, color=C("#3157D5", True))

        def update_label(_=None):
            if existing and category.value == cat_of(existing):
                label_preview.value = f"Label: {activity_label(existing)}"
            else:
                label_preview.value = f"Label (automatic): {category.value} {next_activity_number(c['id'], category.value)}"
            page.update()

        category.on_change = update_label
        label_preview.value = (f"Label: {activity_label(existing)}" if existing
                               else f"Label (automatic): Activity {next_activity_number(c['id'], 'Activity')}")

        picked = {"date": None, "time": None}
        if existing and existing.get("deadline"):
            try:
                dt = datetime.strptime(existing["deadline"], "%Y-%m-%d %H:%M")
                picked["date"], picked["time"] = dt.date(), dt.time()
            except ValueError:
                pass
        deadline_label = ft.Text("No deadline set", size=13, color=C("#526078"))

        def current_deadline():
            if not picked["date"]:
                return ""
            t = picked["time"] or time(23, 59)
            return f"{picked['date']:%Y-%m-%d} {t:%H:%M}"

        def refresh_deadline(push=True):
            dl_text = current_deadline()
            deadline_label.value = f"Deadline: {dl_text}" if dl_text else "No deadline set"
            if push:
                page.update()

        refresh_deadline(push=False)

        def on_date(e):
            v = e.control.value
            if v:
                picked["date"] = v.date() if isinstance(v, datetime) else v
                refresh_deadline()

        def on_time(e):
            v = e.control.value
            if v:
                picked["time"] = v
                if not picked["date"]:
                    picked["date"] = datetime.now().date()
                refresh_deadline()

        def pick_date(_):
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            open_control(page, ft.DatePicker(first_date=today, last_date=datetime(today.year + 5, 12, 31),
                                             on_change=on_date))

        def pick_time(_):
            open_control(page, ft.TimePicker(value=picked["time"] or time(23, 59), on_change=on_time))

        def clear_deadline(_):
            picked["date"] = None
            picked["time"] = None
            refresh_deadline()

        deadline = ft.Column([
            ft.Text("Deadline (optional)", size=12, color=C("#526078")),
            ft.Row([
                button("Pick date", pick_date, ft.Icons.CALENDAR_MONTH),
                button("Pick time", pick_time, ft.Icons.ACCESS_TIME),
                ft.TextButton("Clear", on_click=clear_deadline),
            ], wrap=True, spacing=8),
            deadline_label,
        ], spacing=6)
        instructions = text_field("Instructions", width=560, multiline=True,
                                  value=existing["instructions"] if existing else "")
        file_label = ft.Text(Path(existing["file_path"]).name if existing and existing.get("file_path")
                             else "No attachment selected", size=11, color=C("#748198"))
        chosen = {"path": existing.get("file_path", "") if existing else "", "new": False}
        dlg = None

        def browse(_):
            def got(path):
                chosen["path"] = path
                chosen["new"] = True
                file_label.value = Path(path).name
                page.update()
            pick_file(got)

        def save(_):
            t, inst = (title.value or "").strip(), (instructions.value or "").strip()
            dl = current_deadline()
            try:
                maximum = float(points.value)
                if not t or not inst or maximum <= 0:
                    raise ValueError
                if dl:
                    datetime.strptime(dl, "%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                toast("Enter a title, instructions, positive maximum points, and a valid optional deadline.", True)
                return

            def do():
                try:
                    path = existing.get("file_path", "") if existing else ""
                    if chosen["new"] and chosen["path"]:
                        prefix = f"activity{existing['id'] if existing else next_id('activities')}"
                        path = copy_attachment(chosen["path"], FILES_DIR, prefix)
                    cat = category.value or "Activity"
                    if existing and cat == cat_of(existing):
                        number, label = existing.get("number") or "", activity_label(existing)
                    else:
                        number = str(next_activity_number(c["id"], cat))
                        label = f"{cat} {number}"
                    data = {"title": t, "category": cat, "number": number, "label": label,
                            "term": term.value or "Midterm", "instructions": inst, "max_points": maximum,
                            "deadline": dl, "file_path": path}
                    if existing:
                        update_row("activities", existing["id"], data)
                    else:
                        data.update({"id": next_id("activities"), "class_id": c["id"], "created_at": timestamp()})
                        add_row("activities", data)
                    log_event("class", "Activity saved" if existing else "Activity created",
                              f"{label}: {t} ({term.value or 'Midterm'})", c["id"])
                    state["term"] = term.value or "Midterm"
                    close_dialog(dlg)
                    teacher_class_view()
                    toast(f"{label} saved." if existing else f"{label} created.")
                except Exception as exc:
                    toast(f"Could not save activity: {exc}", True)
            ask_confirm("Save activity", "Save changes to this activity?" if existing
                        else "Create this activity and post it to the class?", do)

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Edit activity" if existing else "Create activity"),
            content=ft.Container(content=ft.Column([
                ft.Row([category, term], spacing=10), label_preview, title, points, deadline, instructions,
                ft.Row([button("Choose attachment", browse, ft.Icons.ATTACH_FILE), file_label], wrap=True),
            ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO), width=600),
            actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                     compatible_button("Save activity" if existing else "Create activity", on_click=save)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        open_control(page, dlg)
        page.update()

    def submit_activity(activity):
        if deadline_passed(activity):
            toast("The deadline has passed. Submissions are closed.", True)
            return

        def chosen(path):
            def do():
                if deadline_passed(activity):
                    toast("The deadline has passed. Submissions are closed.", True)
                    return
                try:
                    copied = copy_attachment(path, SUBMISSIONS_DIR,
                                             f"student{state['user']['id']}_activity{activity['id']}")
                    existing = next((s for s in read_rows("submissions") if s["activity_id"] == activity["id"]
                                     and s["student_id"] == state["user"]["id"]), None)
                    if existing:
                        update_row("submissions", existing["id"], {
                            "file_path": copied, "submitted_at": timestamp(), "score": "", "graded_at": "",
                        })
                    else:
                        add_row("submissions", {
                            "id": next_id("submissions"), "activity_id": activity["id"],
                            "class_id": activity["class_id"], "student_id": state["user"]["id"],
                            "student_name": state["user"]["full_name"], "file_path": copied,
                            "submitted_at": timestamp(), "score": "", "graded_at": "",
                        })
                    log_event("class", "Work submitted",
                              f"{activity_label(activity)}: {activity['title']} ({Path(path).name})",
                              activity["class_id"])
                    student_work_view()
                    toast("Your activity was submitted.")
                except Exception as exc:
                    toast(f"Submission failed: {exc}", True)
            ask_confirm("Submit work", f"Submit \"{Path(path).name}\" for {activity_label(activity)}? "
                                       "Any file you submitted before will be replaced.", do)
        pick_file(chosen)

    def student_work_view():
        c = state["class"]
        activities = sorted([a for a in read_rows("activities")
                             if a["class_id"] == c["id"] and not is_record_item(a)],
                            key=lambda a: (CATEGORIES.index(cat_of(a)), id_key(a)))
        subs = read_rows("submissions")
        rows = []
        for a in activities:
            s = next((x for x in subs if x["activity_id"] == a["id"] and x["student_id"] == state["user"]["id"]), None)
            if not s or not s["file_path"]:
                status = "Closed — missing" if deadline_passed(a) else "Missing"
                submitted, score, path = "—", "—", ""
            else:
                status = "Awaiting evaluation" if s["score"] == "" else "Graded"
                submitted = s["submitted_at"] or "—"
                path = Path(s["file_path"]).name
                score = "—" if s["score"] == "" else f"{fmt(s['score'])} / {fmt(a['max_points'])}"
            rows.append((activity_label(a), a["title"], submitted, status, score, path))
        body = ft.Column([
            ft.Row([button("Back to class", lambda e: student_class_view(), ft.Icons.ARROW_BACK),
                    section_title("My submissions", "Open an activity from the class feed to submit or resubmit.")],
                   spacing=14),
            card(table_view(["Activity", "Title", "Submitted at", "Status", "Score", "File"], rows),
                 padding=14, expand=True),
        ], spacing=14)
        shell("My submissions", c["name"], body, "classes")

    def student_score_view():
        ids = {e["class_id"] for e in read_rows("enrollments") if e["student_id"] == state["user"]["id"]}
        classes = [c for c in read_rows("classes") if c["id"] in ids and not is_archived(c)]
        if not classes:
            toast("Join a class first.")
            return
        current = default_class(classes)

        def yr(c):
            return c.get("school_year") or "none"
        years = sorted({yr(c) for c in classes if yr(c) != "none"}, reverse=True)
        if any(yr(c) == "none" for c in classes):
            years.append("none")
        year_dd = ft.Dropdown(label="School year", width=170, value=yr(current),
                              options=[ft.dropdown.Option(y, "No school year" if y == "none" else y) for y in years])
        section_dd = ft.Dropdown(label="Section", width=170)
        dropdown = ft.Dropdown(label="Subject", width=300)

        def fill_sections(keep=None):
            names = sorted({c["name"] for c in classes if yr(c) == year_dd.value}, key=str.casefold)
            section_dd.options = [ft.dropdown.Option(n) for n in names]
            section_dd.value = keep if keep in names else (names[0] if names else None)

        def fill_subjects(keep=None):
            insec = sorted((c for c in classes if yr(c) == year_dd.value and c["name"] == section_dd.value),
                           key=lambda c: c["subject"].casefold())
            dropdown.options = [ft.dropdown.Option(c["id"], c["subject"]) for c in insec]
            ids = {c["id"] for c in insec}
            dropdown.value = keep if keep in ids else (insec[0]["id"] if insec else None)

        fill_sections(current["name"])
        fill_subjects(current["id"])
        summary = ft.Text("", size=13, color=C("#6B7890"))
        holder = ft.Container(expand=True)

        def refresh(e=None, push=True):
            c = by_id("classes", dropdown.value) or current
            state["class"] = c
            acts = sorted([a for a in read_rows("activities") if a["class_id"] == c["id"]],
                          key=lambda a: ((a.get("term") or "Midterm") != "Midterm",
                                         CATEGORIES.index(cat_of(a)), id_key(a)))
            subs = subs_index()
            rows, graded = [], 0
            for a in acts:
                s = subs.get((a["id"], state["user"]["id"]))
                if not s or (s["score"] == "" and not s["file_path"]):
                    stat, score = ("Not yet recorded" if is_record_item(a) else "Missing submission"), "—"
                elif s["score"] == "":
                    stat, score = "Awaiting evaluation", "—"
                elif is_excused(s["score"]):
                    stat, score = "Excused", "EXC"
                else:
                    stat = "Graded" + (f" ({mark_label(s.get('mark'))})" if s.get("mark") else "")
                    score = fmt(s["score"])
                    graded += 1
                rows.append((activity_label(a), cat_of(a), a.get("term") or "Midterm", score,
                             fmt(a["max_points"]), stat))
            summary.value = f"{graded} of {len(acts)} activities graded."
            holder.content = card(table_view(["Activity", "Type", "Term", "Score", "Max points", "Status"], rows),
                                  padding=14, expand=True)
            if push:
                page.update()

        dropdown.on_change = refresh
        section_dd.on_change = lambda e: (fill_subjects(), refresh(e))
        year_dd.on_change = lambda e: (fill_sections(), fill_subjects(), refresh(e))
        refresh(push=False)
        body = ft.Column([
            section_title("My scores", "Pick a school year, section and subject to check your scores."),
            ft.Row([year_dd, section_dd, dropdown, summary], spacing=16, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            holder,
        ], spacing=14)
        shell("My scores", "Your recorded scores", body, "scores")

    def enrolled_students_view():
        c = state["class"]
        users = {u["id"]: u for u in read_rows("users")}
        holder = ft.Container(expand=True)
        title_holder = ft.Container()

        def remove(e_row):
            def do():
                log_event("class", "Student removed from class",
                          f"{e_row['student_name']} from {c['name']} (their scores were deleted)", c["id"],
                          e_row["student_id"])
                remove_student_from_class(c["id"], e_row["student_id"])
                refresh()
                toast("Student removed from the class.")
            ask_confirm("Remove student", f"Remove {e_row['student_name']} from {c['name']}? Their scores in this "
                                          "class will be deleted. They can rejoin with the class code.", do)

        def refresh(push=True):
            enrollments = class_enrollments(c["id"])
            rows = []
            for e in enrollments:
                u = users.get(e["student_id"]) or {"full_name": e["student_name"]}
                rows.append(ft.Container(
                    content=ft.Row([
                        ft.Container(ft.Text(format_sheet_name(u), size=12, weight=ft.FontWeight.BOLD), width=240),
                        ft.Container(ft.Text((users.get(e["student_id"]) or {}).get("username", ""), size=12,
                                             selectable=True), width=220),
                        ft.Container(ft.Text(e["joined_at"], size=12), width=160),
                        ft.IconButton(icon=ft.Icons.PERSON_REMOVE_OUTLINED, icon_size=18, icon_color=C("#B42318"),
                                      tooltip="Remove from class", on_click=lambda ev, x=e: remove(x)),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=pad_sym(10, 4), border=border_all(1, C("#EEF2F8")), border_radius=10))
            title_holder.content = section_title("Enrolled students", f"{len(rows)} students in {c['name']}.")
            if rows:
                holder.content = card(ft.Column([ft.Row([ft.Column(rows, spacing=6)], scroll=ft.ScrollMode.AUTO)],
                                                scroll=ft.ScrollMode.AUTO, expand=True), padding=14, expand=True)
            else:
                holder.content = empty_card(ft.Icons.GROUP_OUTLINED, "No enrolled students yet",
                                            "Share the class code so students can join.")
            if push:
                page.update()

        refresh(push=False)
        body = ft.Column([
            ft.Row([button("Back to class", lambda e: teacher_class_view(), ft.Icons.ARROW_BACK),
                    title_holder], spacing=14),
            holder,
        ], spacing=14)
        shell("Enrolled students", c["name"], body, "classes")

    def archive_class(c):
        def do():
            update_row("classes", c["id"], {"archived": "1"})
            log_event("class", "Class archived", f"{c['name']} - {c['subject']}", c["id"])
            state["class"] = None
            teacher_classes()
            toast(f"{c['name']} was archived. Nothing was deleted.")
        ask_confirm("Archive class", f"Archive \"{c['name']} — {c['subject']}\"? Nothing is deleted: the students, "
                                     "scores and records are all kept. The class is hidden from your lists and from "
                                     "students. You can bring it back anytime with \"Show archived classes\" on the "
                                     "My classes page.", do)

    def restore_class(c):
        update_row("classes", c["id"], {"archived": ""})
        log_event("class", "Class restored", f"{c['name']} - {c['subject']}", c["id"])
        state["class"] = by_id("classes", c["id"])
        teacher_class_view()
        toast(f"{c['name']} is active again.")

    def manage_submissions_view():
        c = state["class"]
        all_acts = sorted([a for a in read_rows("activities")
                           if a["class_id"] == c["id"] and not is_record_item(a)],
                          key=lambda a: (CATEGORIES.index(cat_of(a)), id_key(a)))
        if not all_acts:
            toast("Create an activity first.")
            return
        cat_dd = ft.Dropdown(label="Category", width=220, value="All categories",
                             options=[ft.dropdown.Option("All categories")] + [ft.dropdown.Option(x) for x in CATEGORIES])
        act_dd = ft.Dropdown(label="Choose activity", width=480)
        holder = ft.Container(expand=True)

        def filtered():
            return [a for a in all_acts if cat_dd.value == "All categories" or cat_of(a) == cat_dd.value]

        def fill_activities():
            acts = filtered()
            act_dd.options = [ft.dropdown.Option(a["id"], f"{activity_label(a)} — {a['title']} ({a.get('term') or 'Midterm'})")
                              for a in acts]
            act_dd.value = acts[0]["id"] if acts else None

        def open_sub_file(sub_id):
            sub = by_id("submissions", sub_id) if sub_id else None
            if not sub or not sub["file_path"]:
                toast("There is no submitted file for this student.", True)
                return
            ok, msg = open_path(sub["file_path"])
            toast(msg, not ok)

        def grade_submission(sub_id, activity):
            sub = by_id("submissions", sub_id) if sub_id else None
            if not sub:
                toast("You can only grade a submitted activity.", True)
                return
            score_field = text_field(f"Score (0 to {fmt(activity['max_points'])}, or EXC)", width=280,
                                     value=score_to_text(sub["score"], False, ""))
            mark_dd = ft.Dropdown(label="Submission timing", width=280, value=sub.get("mark") or "none",
                                  options=[ft.dropdown.Option("none", "On time"), ft.dropdown.Option("L", "Late"),
                                           ft.dropdown.Option("M", "Make-up")])
            dlg = None

            def save_grade(_):
                try:
                    value, typed_mark = parse_entry(score_field.value, False, float(activity["max_points"]))
                    if value == "":
                        raise ValueError("Enter a score.")
                except ValueError as exc:
                    toast(str(exc), True)
                    return
                mark = typed_mark or ("" if mark_dd.value in (None, "none") else mark_dd.value)

                def do():
                    old_text = score_to_text(sub["score"], False, sub.get("mark", ""))
                    update_row("submissions", sub_id, {"score": value, "mark": mark, "graded_at": timestamp()})
                    log_event("score", "Score changed",
                              f"{sub['student_name']} - {activity_label(activity)} "
                              f"({activity.get('term') or 'Midterm'}): {old_text or 'blank'} -> "
                              f"{score_to_text(value, False, mark)}", activity["class_id"], sub["student_id"])
                    close_dialog(dlg)
                    refresh()
                    toast("Score saved.")
                ask_confirm("Save score", f"Save a score of {score_to_text(value, False, mark)} for "
                                          f"{sub['student_name']}?", do)

            dlg = ft.AlertDialog(
                modal=True, title=ft.Text(f"Grade: {activity_label(activity)}"),
                content=ft.Column([score_field, mark_dd], tight=True, spacing=12, width=300),
                actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                         compatible_button("Save score", on_click=save_grade)],
            )
            open_control(page, dlg)
            page.update()

        def refresh(e=None, push=True):
            a = next((x for x in all_acts if x["id"] == act_dd.value), None)
            if not a:
                holder.content = card(ft.Text("No activities in this category yet."), padding=18)
                if push:
                    page.update()
                return
            subs = subs_index()
            rows = []
            for en in class_enrollments(c["id"]):
                sub = subs.get((a["id"], en["student_id"]))
                if sub and sub["file_path"]:
                    stat = "Graded" if sub["score"] != "" else "Awaiting evaluation"
                    rows.append((en["student_name"], stat, sub["submitted_at"] or "—",
                                 fmt(sub["score"]) if sub["score"] != "" else "—",
                                 Path(sub["file_path"]).name, sub["id"]))
                elif sub and sub["score"] != "":
                    rows.append((en["student_name"], "Graded (encoded)", "—", fmt(sub["score"]), "", ""))
                else:
                    rows.append((en["student_name"], "Missing", "—", "—", "", ""))

            def make_row(r, act=a):
                sid = r[5]
                if sid:
                    right = ft.Row([
                        ft.TextButton("Open file", on_click=lambda e, s=sid: open_sub_file(s)),
                        compatible_button("Grade", on_click=lambda e, s=sid: grade_submission(s, act)),
                    ], spacing=4)
                else:
                    right = ft.Text("No submission", color=C("#9AA5B5"), size=11)
                return ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(r[0], weight=ft.FontWeight.BOLD, size=13),
                            ft.Text(f"{r[1]} • Submitted: {r[2]} • Score: {r[3]} / {fmt(act['max_points'])}",
                                    size=11, color=C("#748198")),
                            ft.Text(r[4], size=10, color=C("#9AA5B5")),
                        ], spacing=4, expand=True),
                        right,
                    ]),
                    padding=12, border=border_all(1, C("#E7ECF4")), border_radius=12, bgcolor=C("#FFFFFF"),
                )

            holder.content = card(ft.Column([
                ft.Text(f"{activity_label(a)} — student submissions", size=16, weight=ft.FontWeight.BOLD),
                ft.Column([make_row(r) for r in rows], spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
                if rows else ft.Text("No students enrolled yet."),
            ], spacing=10, expand=True), padding=18, expand=True)
            if push:
                page.update()

        def on_category(e):
            fill_activities()
            refresh()

        cat_dd.on_change = on_category
        act_dd.on_change = refresh
        fill_activities()
        refresh(push=False)
        body = ft.Column([
            ft.Row([button("Back to class", lambda e: teacher_class_view(), ft.Icons.ARROW_BACK),
                    section_title("Submissions & grading", "Pick a category, then an activity.")], spacing=14),
            ft.Row([cat_dd, act_dd], spacing=12, wrap=True),
            holder,
        ], spacing=14)
        shell("Submissions & grading", c["name"], body, "classes")

    def choose_grade_class():
        classes = my_classes()
        if not classes:
            toast("Create a class first.")
            return
        year_dd, selected, fill_classes = year_class_dropdowns(classes, default_class(classes),
                                                               {"width": 420}, {"width": 420})
        selected.label = "Select class"
        year_dd.on_change = lambda e: (fill_classes(), page.update())
        dlg = None

        def go(_):
            chosen = next((x for x in classes if x["id"] == selected.value), None)
            if not chosen:
                toast("Please select a valid class.", True)
                return
            state["class"] = chosen
            close_dialog(dlg)
            grade_sheet_view()

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Open digital grade sheet"),
            content=ft.Container(width=480, content=ft.Column([
                ft.Text("Choose the class whose scores you want to manage."), year_dd, selected,
            ], tight=True, spacing=12)),
            actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                     compatible_button("Open grade sheet", on_click=go, icon=ft.Icons.ASSESSMENT_OUTLINED)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        open_control(page, dlg)
        page.update()

    def sheet_grid_control(grid):
        """Grouped grade sheet (category bands, max-points row, TOT / TR / WS result columns)."""
        W_NAME, W_ITEM, W_RES, W_FIN, RH = 210, 78, 56, 100, 32
        try:
            left = ft.Alignment(-1, 0)
        except Exception:
            left = center_alignment()

        def cell(text, w, h=RH, bg=C("#FFFFFF"), color=C("#18243A"), bold=False, size=11, align_left=False):
            return ft.Container(
                content=ft.Text(str(text), size=size, color=color, max_lines=2,
                                text_align=ft.TextAlign.LEFT if align_left else ft.TextAlign.CENTER,
                                weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL),
                width=w, height=h, bgcolor=bg, border=border_all(1, C("#E3E9F3")),
                alignment=left if align_left else center_alignment(), padding=pad_sym(4, 2),
            )

        groups = grid["groups"]
        bands = []
        for g in groups:
            width = len(g["acts"]) * W_ITEM + 3 * W_RES
            bands.append(cell(f"{g['cat'].upper()} ({fmt(round(g['weight'], 2))}%)", width,
                              bg=C("#17243A"), color="#FFFFFF", bold=True, size=12))
        fin_head = ft.Row([cell("FINAL GRADE", W_FIN, h=3 * RH, bg=C("#17243A"), color="#FFFFFF", bold=True, size=11),
                           cell("GWA", W_RES + 10, h=3 * RH, bg=C("#17243A"), color="#FFFFFF", bold=True, size=11)],
                          spacing=0)
        item_row, max_row = [], []
        for g in groups:
            for a in g["acts"]:
                item_row.append(cell(activity_label(a), W_ITEM, bg=C("#E8EEFF"), bold=True, size=10))
                max_row.append(cell(fmt(a["max_points"]), W_ITEM, bg=C("#F4F8FF"), color=C("#3157D5", True), bold=True))
            item_row.append(cell("RESULT", 3 * W_RES, bg=C("#3157D5"), color="#FFFFFF", bold=True, size=10))
            for t in ("TOT", "TR", "WS"):
                max_row.append(cell(t, W_RES, bg=C("#E8EEFF"), bold=True, size=10))
        header = ft.Row([
            cell("STUDENT NAME", W_NAME, h=3 * RH, bg=C("#17243A"), color="#FFFFFF", bold=True, size=12),
            ft.Column([ft.Row(bands, spacing=0), ft.Row(item_row, spacing=0), ft.Row(max_row, spacing=0)],
                      spacing=0),
            fin_head,
        ], spacing=0, vertical_alignment=ft.CrossAxisAlignment.START)
        body = [header]
        for i, s in enumerate(grid["students"]):
            bg = C("#FFFFFF") if i % 2 == 0 else C("#F7F9FD")
            cells = [cell(s["name"], W_NAME, bg=bg, bold=True, size=11, align_left=True)]
            for gc in s["cells"]:
                for v in gc["scores"]:
                    cells.append(cell(v, W_ITEM, bg=bg))
                cells.append(cell(gc["tot"], W_RES, bg=bg, bold=True))
                cells.append(cell(gc["tr"], W_RES, bg=bg, color=C("#748198"), size=10))
                cells.append(cell(gc["ws"], W_RES, bg=bg, color=C("#0D9488"), bold=True))
            cells.append(cell(s["final"], W_FIN, bg=C("#EEF2FF"), bold=True, color=C("#3157D5", True)))
            cells.append(cell(s["gwa"], W_RES + 10, bg=C("#EEF2FF"), bold=True, color=C("#3157D5", True)))
            body.append(ft.Row(cells, spacing=0))
        return ft.Column([ft.Row([ft.Column(body, spacing=0)], scroll=ft.ScrollMode.AUTO)],
                         scroll=ft.ScrollMode.AUTO, expand=True)

    def do_export_pdf(c, context, title, cols, rows, filename, grid_table=None):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            toast("Install PDF support with: py -m pip install reportlab", True)
            return
        if not rows:
            toast("There is nothing to export yet.", True)
            return
        destination = native_file_dialog(
            "save", title=f"Export {title}", initialfile=filename,
            defaultextension=".pdf", filetypes=[["PDF files", "*.pdf"]],
        )
        if not destination:
            return
        try:
            export_report_pdf(destination, c, context, title, cols, rows, grid_table)
            toast(f"PDF exported: {destination}")
        except Exception as exc:
            toast(f"PDF export failed: {exc}", True)

    def grade_settings_view():
        """Grade settings dashboard: weights, semester, midterm share and allowed absences per class."""
        classes = my_classes()
        if not classes:
            toast("Create a class first.")
            return
        current = default_class(classes)
        state["class"] = current
        year_dd, class_dd, fill_classes = year_class_dropdowns(classes, current, {"expand": 1}, {"expand": 2})
        term_dd = ft.Dropdown(label="Term", expand=1, value=state["term"],
                              options=[ft.dropdown.Option(t) for t in TERMS])
        sem_dd = ft.Dropdown(label="Semester", expand=1, options=[ft.dropdown.Option(s) for s in SEMESTERS])
        share_tf = text_field("Midterm share of overall grade (%)")
        share_tf.expand = 1
        absence_tf = text_field("Allowed absences")
        absence_tf.expand = 1
        checks = {cat: ft.Checkbox(label=cat, value=False) for cat in CATEGORIES}
        pcts = {cat: ft.TextField(label="Weight (%)", keyboard_type=ft.KeyboardType.NUMBER,
                                  border_radius=10, disabled=True) for cat in CATEGORIES}
        status = ft.Text("", size=11, color=C("#748198"))

        def load_class_values():
            s = get_settings(class_dd.value)
            sem_dd.value = s["semester"]
            share_tf.value = fmt(s["midterm_share"])
            absence_tf.value = str(get_absence_limit(class_dd.value))

        def load_weights():
            w = get_settings(class_dd.value)[term_dd.value]
            for cat in CATEGORIES:
                checks[cat].value = cat in w
                pcts[cat].value = fmt(w[cat]) if cat in w else ""
                pcts[cat].disabled = cat not in w

        def ui_weights():
            """Return (weights, missing). `missing` lists ticked categories whose weight box is blank.
            Raises ValueError when a box holds something that is not a valid number."""
            w, missing = {}, []
            for cat in CATEGORIES:
                if not checks[cat].value:
                    continue
                raw = (pcts[cat].value or "").strip()
                if not raw:
                    missing.append(cat)
                    continue
                v = float(raw)
                if v != v or v in (float("inf"), float("-inf")):
                    raise ValueError("not a finite number")
                w[cat] = v
            return w, missing

        def refresh(e=None, push=True):
            for cat in CATEGORIES:
                pcts[cat].disabled = not checks[cat].value
            try:
                w, missing = ui_weights()
                total = sum(w.values())
                if not w and not missing:
                    status.value = "No categories selected — all categories are weighted equally until you set them."
                    status.color = C("#B54708")
                elif missing:
                    status.value = f"Enter a weight for: {', '.join(missing)}."
                    status.color = C("#B42318")
                elif abs(total - 100) < .001 and all(x >= 0 for x in w.values()):
                    status.value = f"Weights total {total:g}%. Ready to save."
                    status.color = C("#0D9488")
                else:
                    status.value = f"Weights total {total:g}%. They must be non-negative and total 100%."
                    status.color = C("#B54708")
            except ValueError:
                status.value = "Enter a number for every selected category's weight."
                status.color = C("#B42318")
            if push:
                page.update()

        def on_class(e):
            state["class"] = by_id("classes", class_dd.value)
            load_class_values()
            load_weights()
            refresh()

        def on_term(e):
            state["term"] = term_dd.value
            load_weights()
            refresh()

        class_dd.on_change = on_class
        year_dd.on_change = lambda e: (fill_classes(), on_class(e))
        term_dd.on_change = on_term
        for cat in CATEGORIES:
            checks[cat].on_change = refresh
            pcts[cat].on_change = refresh

        def save(_):
            c = by_id("classes", class_dd.value)
            try:
                w, missing = ui_weights()
            except ValueError:
                toast("Enter a number for every selected category's weight.", True)
                return
            if not w and not missing:
                toast("Select at least one category.", True)
                return
            if missing:
                toast(f"Enter a weight for every selected category. Missing: {', '.join(missing)}.", True)
                return
            if any(x < 0 for x in w.values()) or abs(sum(w.values()) - 100) > .001:
                toast("Category weights must be non-negative and total 100%.", True)
                return
            try:
                share = float(share_tf.value)
                if share < 0 or share > 100:
                    raise ValueError
            except (ValueError, TypeError):
                toast("The Midterm share must be a number from 0 to 100.", True)
                return
            try:
                absences = int((absence_tf.value or "").strip())
                if absences < 0:
                    raise ValueError
            except (ValueError, TypeError):
                toast("Allowed absences must be a whole number (0 or more).", True)
                return

            def do():
                save_settings(c["id"], sem_dd.value, term_dd.value, w, share)
                set_absence_limit(c["id"], absences)
                log_event("class", "Grade settings saved",
                          f"{c['name']} - {c['subject']} ({term_dd.value}, {sem_dd.value}): "
                          f"allowed absences {absences}, midterm share {fmt(share)}%", c["id"])
                refresh()
                toast(f"{term_dd.value} grade settings saved.")
            ask_confirm("Save grade settings",
                        f"Save these settings for {c['name']} — {c['subject']} ({term_dd.value}, {sem_dd.value})?", do)

        def open_sheet(_):
            state["class"] = by_id("classes", class_dd.value)
            grade_sheet_view()

        load_class_values()
        load_weights()

        def weight_tile(cat):
            return ft.Container(
                content=ft.Column([checks[cat], pcts[cat]], spacing=6,
                                  horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                expand=1, padding=12, border=border_all(1, C("#E7ECF4")), border_radius=12)

        per_row = 4
        tiles = [weight_tile(cat) for cat in CATEGORIES]
        tile_rows = []
        for i in range(0, len(tiles), per_row):
            chunk = tiles[i:i + per_row]
            chunk += [ft.Container(expand=1) for _ in range(per_row - len(chunk))]
            tile_rows.append(ft.Row(chunk, spacing=12))
        body = ft.Column([
            ft.Row([section_title("Grade settings", "Set how each class is graded. The grade sheet and reports use these settings."),
                    ft.Container(expand=True),
                    button("Open grade sheet", open_sheet, ft.Icons.ASSESSMENT_OUTLINED),
                    button("Save settings", save, ft.Icons.SAVE_OUTLINED, True)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            card(ft.Column([
                ft.Text("Class and term", size=15, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                ft.Row([year_dd, class_dd, term_dd, sem_dd], spacing=12),
                ft.Row([share_tf, absence_tf, ft.Container(expand=1)], spacing=12),
                ft.Text("Midterm share is used for the overall grade. Allowed absences is used by the "
                        "Attendance Summary report.", size=11, color=C("#748198")),
            ], spacing=10), padding=16),
            card(ft.Column([
                ft.Text("Category weights", size=15, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                ft.Text("Tick the categories you grade on and set the % of each for the chosen term. "
                        "The total must be 100%.", size=11, color=C("#748198")),
                ft.Column(tile_rows, spacing=12),
                status,
            ], spacing=10), padding=16),
        ], spacing=14, scroll=ft.ScrollMode.AUTO)
        refresh(push=False)
        shell("Grade settings", current["name"], body, "grade_settings")

    def grade_sheet_view():
        c = state["class"]
        term_dd = ft.Dropdown(label="Term", width=170, value=state["term"],
                              options=[ft.dropdown.Option(t) for t in TERMS])
        weights_note = ft.Text("", size=12, color=C("#526078"), expand=True)
        holder = ft.Container(height=470)

        def saved_weights():
            return get_settings(c["id"])[term_dd.value]

        def refresh(e=None, push=True):
            state["term"] = term_dd.value
            w = saved_weights()
            if w:
                weights_note.value = "Weights: " + ", ".join(f"{k} {fmt(round(v, 2))}%" for k, v in w.items()
                                                             if k in CATEGORIES)
            else:
                weights_note.value = "No weights saved yet — all categories are weighted equally. " \
                                     "Set them in Grade settings."
            grid = build_sheet_grid(c, term_dd.value, w)
            if grid["students"]:
                holder.content = ft.Container(content=sheet_grid_control(grid), height=470)
            else:
                holder.content = ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.GRID_ON_OUTLINED, size=30, color=C("#9AA5B5")),
                        ft.Text("No enrolled students yet", weight=ft.FontWeight.BOLD, color=C("#344054")),
                        ft.Text("Once students join this class, their scores will appear here.",
                                size=12, color=C("#748198")),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        alignment=ft.MainAxisAlignment.CENTER, spacing=8),
                    alignment=center_alignment(), padding=24,
                )
            if push:
                page.update()

        term_dd.on_change = refresh

        def edit_scores_dialog(_=None):
            acts = term_activities(c["id"], term_dd.value)
            enrollments = class_enrollments(c["id"])
            if not acts or not enrollments:
                toast(f"Add a {term_dd.value} activity and enroll students before editing scores.")
                return
            student = ft.Dropdown(label="Student", width=460,
                                  options=[ft.dropdown.Option(e["student_id"], e["student_name"]) for e in enrollments])
            activity = ft.Dropdown(label="Activity", width=460,
                                   options=[ft.dropdown.Option(a["id"], f"{activity_label(a)} — {a['title']}") for a in acts])
            score = text_field("Score (blank = not recorded, EXC = excused, 18L = late, 18M = make-up)", width=460)
            dlg = None

            def load_score(_):
                if student.value and activity.value:
                    sub = subs_index().get((activity.value, student.value))
                    score.value = score_to_text(sub["score"], False, sub.get("mark", "")) if sub else ""
                    page.update()

            student.on_change = load_score
            activity.on_change = load_score

            def save(_):
                if not student.value or not activity.value:
                    toast("Select a student and activity.", True)
                    return
                a = by_id("activities", activity.value)
                try:
                    answer, mark = parse_entry(score.value, False, float(a["max_points"]))
                except ValueError as exc:
                    toast(str(exc), True)
                    return

                def do():
                    existing = subs_index().get((activity.value, student.value))
                    enrollment = next(e for e in enrollments if e["student_id"] == student.value)
                    old_text = score_to_text(existing["score"], False, existing.get("mark", "")) if existing else ""
                    log_event("score", "Score changed",
                              f"{enrollment['student_name']} - {activity_label(a)} ({a.get('term') or 'Midterm'}, "
                              f"{c['name']}): {old_text or 'blank'} -> {score_to_text(answer, False, mark) or 'blank'}",
                              c["id"], student.value)
                    if existing:
                        update_row("submissions", existing["id"],
                                   {"score": answer, "mark": mark, "graded_at": timestamp() if answer else ""})
                    elif answer:
                        add_row("submissions", {"id": next_id("submissions"), "activity_id": a["id"],
                                                "class_id": c["id"], "student_id": student.value,
                                                "student_name": enrollment["student_name"], "file_path": "",
                                                "submitted_at": "", "score": answer, "graded_at": timestamp(),
                                                "mark": mark})
                    close_dialog(dlg)
                    refresh()
                    toast("Score saved.")
                ask_confirm("Save score", "Save this score to the grade sheet?", do)

            dlg = ft.AlertDialog(
                modal=True, title=ft.Text("Encode or edit a score"),
                content=ft.Column([student, activity, score], tight=True, spacing=12, width=480),
                actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                         compatible_button("Save score", on_click=save)],
            )
            open_control(page, dlg)
            page.update()

        def export_click(_):
            grid_table = grid_to_table(build_sheet_grid(c, term_dd.value, saved_weights()))
            context = class_context(c, term_dd.value)
            ask_confirm("Export PDF", "Export the grade sheet as a PDF?",
                        lambda: do_export_pdf(c, context, "Grade Sheet", [], grid_table["body"],
                                              f"GradeSheet_{c['name']}_{term_dd.value}.pdf".replace(" ", "_"),
                                              grid_table))

        def export_csv(_):
            grid_table = grid_to_table(build_sheet_grid(c, term_dd.value, saved_weights()))
            if not grid_table["body"]:
                toast("There is nothing to export yet.", True)
                return
            filename = f"GradeSheet_{c['name']}_{term_dd.value}.csv".replace(" ", "_")
            destination = native_file_dialog("save", title="Export grade sheet (CSV)", initialfile=filename,
                                             defaultextension=".csv", filetypes=[["CSV files", "*.csv"]])
            if not destination:
                return
            try:
                h0, h1, h2 = grid_table["header"]
                header, band = [], ""
                for i in range(grid_table["ncols"]):
                    band = h0[i] or band
                    parts = [band, h1[i], h2[i]] if 0 < i < grid_table["ncols"] - 2 else [h0[i]]
                    header.append(" | ".join(x for x in parts if x))
                with open(destination, "w", newline="", encoding="utf-8-sig") as fh:
                    writer = csv.writer(fh)
                    writer.writerow([get_setting("school_name")])
                    writer.writerow([get_setting("school_location")])
                    if get_setting("report_line3"):
                        writer.writerow([get_setting("report_line3")])
                    writer.writerow([class_context(c, term_dd.value)])
                    writer.writerow([])
                    writer.writerow(header)
                    writer.writerows(grid_table["body"])
                toast(f"CSV exported: {destination}")
            except Exception as exc:
                toast(f"CSV export failed: {exc}", True)

        def open_settings(_):
            grade_settings_view()

        body = ft.Column([
            ft.Row([
                button("Back to class", lambda e: teacher_class_view(), ft.Icons.ARROW_BACK),
                ft.Container(expand=True),
                button("Encode/edit score", edit_scores_dialog, ft.Icons.EDIT_NOTE),
                button("Export CSV", export_csv, ft.Icons.SAVE_OUTLINED),
                button("Export PDF", export_click, ft.Icons.PICTURE_AS_PDF, True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            section_title("Digital grade sheet", f"{c['name']} • {c['subject']} • S.Y. {c.get('school_year') or '—'}"),
            card(ft.Row([term_dd, weights_note, button("Grade settings", open_settings, ft.Icons.TUNE)],
                        spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=14),
            ft.Text("TOT = points earned, TR = TOT / total possible x 100, WS = TR x category weight. "
                    "Blank scores count as 0. Weighted grade = sum of the WS columns. A trailing L = late, "
                    "M = make-up (the score still counts).", size=11, color=C("#748198")),
            card(holder, padding=12),
        ], spacing=14, scroll=ft.ScrollMode.AUTO)
        refresh(push=False)
        shell("Digital grade sheet", c["name"], body, "grades")

    def record_sheet_view():
        """Spreadsheet-style recording of scores per category, with live results."""
        classes = my_classes()
        if not classes:
            toast("Create a class first.")
            return
        current = default_class(classes)
        year_dd, class_dd, fill_classes = year_class_dropdowns(classes, current, {"width": 170}, {"width": 300})
        term_dd = ft.Dropdown(label="Term", width=150, value=state["term"],
                              options=[ft.dropdown.Option(t) for t in TERMS])
        cat_dd = ft.Dropdown(label="Category", width=200, value=state.get("rec_cat") or CATEGORIES[0],
                             options=[ft.dropdown.Option(x) for x in CATEGORIES])
        info = ft.Text("", size=11, color=C("#748198"))
        holder = ft.Container(height=470)
        fields, max_fields, draft, saved_all = {}, {}, {}, {}
        view = {"acts": []}
        W_NAME, W_ITEM, W_RES, RH, HH = 210, 98, 64, 40, 126
        try:
            left = ft.Alignment(-1, 0)
        except Exception:
            left = center_alignment()

        def cell(text, w, h=RH, bg=C("#FFFFFF"), color=C("#18243A"), bold=False, size=11, align_left=False):
            return ft.Container(
                content=ft.Text(str(text), size=size, color=color, max_lines=2,
                                text_align=ft.TextAlign.LEFT if align_left else ft.TextAlign.CENTER,
                                weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL),
                width=w, height=h, bgcolor=bg, border=border_all(1, C("#E3E9F3")),
                alignment=left if align_left else center_alignment(), padding=pad_sym(4, 2),
            )

        def small_field(value, width):
            return ft.TextField(value=value, width=width, height=34, text_size=12,
                                text_align=ft.TextAlign.CENTER, border_radius=8,
                                border_color=C("#DCE3EF"), focused_border_color=C("#3157D5"),
                                content_padding=pad_sym(4, 2), on_change=lambda e: None)

        def snapshot():
            for k, f in fields.items():
                draft[k] = f.value or ""
            for k, f in max_fields.items():
                draft[("max", k)] = f.value or ""

        def has_unsaved():
            snapshot()
            return any(v != saved_all.get(k, v) for k, v in draft.items())

        def refresh(e=None, push=True):
            snapshot()
            c = by_id("classes", class_dd.value)
            state["class"] = c
            state["term"] = term_dd.value
            state["rec_cat"] = cat_dd.value
            cat = cat_dd.value
            all_acts = term_activities(c["id"], term_dd.value)
            acts = [a for a in all_acts if cat_of(a) == cat]
            view["acts"] = acts
            enrollments = class_enrollments(c["id"])
            users = {u["id"]: u for u in read_rows("users")}
            subs = subs_index()
            weights = get_settings(c["id"])[term_dd.value]
            fields.clear()
            max_fields.clear()
            if not enrollments:
                holder.content = empty_card(ft.Icons.GROUP_OUTLINED, "No enrolled students yet",
                                            "Once students join this class you can record their scores here.")
                info.value = ""
            elif not acts:
                what = "date" if cat == "Attendance" else "column"
                holder.content = empty_card(ft.Icons.INBOX_OUTLINED, f"No {cat} items yet",
                                            f"Click \"Add item\" to create the first {what} "
                                            f"(for example {cat} 1).")
                info.value = ""
            else:
                head = [cell("STUDENT NAME", W_NAME, h=HH, bg=C("#17243A"), color="#FFFFFF", bold=True, size=12)]
                for a in acts:
                    date_item = is_date_item(a)
                    top = [ft.Text(activity_label(a), size=10, weight=ft.FontWeight.BOLD, color=C("#18243A"),
                                   text_align=ft.TextAlign.CENTER, max_lines=1)]
                    if date_item:
                        top += [ft.Text(a["title"], size=10, color=C("#3157D5", True), weight=ft.FontWeight.BOLD),
                                ft.Text("P / L / A / E", size=9, color=C("#748198"))]
                    else:
                        mf = small_field(draft.get(("max", a["id"]), fmt(a["max_points"])), W_ITEM - 20)
                        saved_all[("max", a["id"])] = fmt(a["max_points"])
                        max_fields[a["id"]] = mf
                        top += [ft.Text("Max points", size=9, color=C("#748198")), mf]
                    top.append(ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_size=16, icon_color=C("#B42318"),
                                             tooltip="Delete this item",
                                             on_click=lambda e, item=a: delete_item(item)))
                    head.append(ft.Container(
                        content=ft.Column(top, spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                          alignment=ft.MainAxisAlignment.CENTER),
                        width=W_ITEM, height=HH, bgcolor=C("#E8EEFF"), border=border_all(1, C("#E3E9F3")),
                        alignment=center_alignment()))
                for t in ("TOT", "TR %", "WS"):
                    head.append(cell(t, W_RES, h=HH, bg=C("#3157D5"), color="#FFFFFF", bold=True, size=11))
                head.append(cell("TERM FINAL", W_RES + 16, h=HH, bg=C("#17243A"), color="#FFFFFF", bold=True, size=11))
                head.append(cell("GWA", W_RES, h=HH, bg=C("#17243A"), color="#FFFFFF", bold=True, size=11))
                rows = [ft.Row(head, spacing=0)]
                weight_note = ""
                for i, en in enumerate(enrollments):
                    bg = C("#FFFFFF") if i % 2 == 0 else C("#F7F9FD")
                    sid = en["student_id"]
                    u = users.get(sid) or {"full_name": en["student_name"]}
                    _scores, detail, final = term_detail(all_acts, subs, sid, weights)
                    d = detail[cat]
                    weight_note = f"{cat} weight this term: {fmt(round(d['weight'], 2))}%"
                    line = [cell(format_sheet_name(u), W_NAME, bg=bg, bold=True, align_left=True)]
                    for a in acts:
                        s = subs.get((a["id"], sid))
                        raw = s["score"] if s else ""
                        saved = score_to_text(raw, is_date_item(a), (s or {}).get("mark", ""))
                        saved_all[(a["id"], sid)] = saved
                        tf = small_field(draft.get((a["id"], sid), saved), W_ITEM - 20)
                        fields[(a["id"], sid)] = tf
                        line.append(ft.Container(content=tf, width=W_ITEM, height=RH, bgcolor=bg,
                                                 border=border_all(1, C("#E3E9F3")), alignment=center_alignment()))
                    line.append(cell(fmt(round(d["earned"], 2)), W_RES, bg=bg, bold=True))
                    line.append(cell(fmt(round(d["tr"], 1)) if d["tr"] is not None else "0", W_RES, bg=bg,
                                     color=C("#748198"), size=10))
                    line.append(cell(f"{d['ws']:.2f}", W_RES, bg=bg, color=C("#0D9488"), bold=True))
                    line.append(cell(f"{final:.2f}" if final is not None else "—", W_RES + 16,
                                     bg=C("#EEF2FF"), bold=True, color=C("#3157D5", True)))
                    line.append(cell(gwa_of(final) or "—", W_RES, bg=C("#EEF2FF"), bold=True, color=C("#3157D5", True)))
                    rows.append(ft.Row(line, spacing=0))
                if cat == "Attendance":
                    hint = (f"Type P = present, L = late (counts {fmt(LATE_CREDIT * 100)}%), A = absent, "
                            "E = excused (not counted). ")
                else:
                    hint = ("Type EXC for an excused score (not counted). Add L (late) or M (make-up) after a "
                            "score, e.g. 18L. Blank counts as 0. ")
                info.value = (f"{weight_note}. {hint}TOT = points earned, TR = TOT / total possible x 100, "
                              "WS = TR x category weight. Results update after you press Save scores.")
                holder.content = ft.Column([ft.Row([ft.Column(rows, spacing=0)], scroll=ft.ScrollMode.AUTO)],
                                           scroll=ft.ScrollMode.AUTO, expand=True)
            if push:
                page.update()

        def add_item(_=None):
            c = by_id("classes", class_dd.value)
            cat = cat_dd.value
            is_att = cat == "Attendance"
            if is_att:
                today = datetime.now().date()
                first = text_field("Date", width=270, value=today.strftime("%Y-%m-%d"))
                first.read_only = True
                second = None

                def on_pick(e):
                    v = e.control.value
                    if v:
                        day = v.date() if isinstance(v, datetime) else v
                        first.value = day.strftime("%Y-%m-%d")
                        page.update()

                def open_calendar(_=None):
                    try:
                        current = datetime.strptime(first.value, "%Y-%m-%d")
                    except (ValueError, TypeError):
                        current = datetime.now()
                    open_control(page, ft.DatePicker(
                        value=current, first_date=datetime(2020, 1, 1),
                        last_date=datetime(today.year + 1, 12, 31), on_change=on_pick))

                date_row = ft.Row([first, ft.IconButton(icon=ft.Icons.CALENDAR_MONTH, icon_size=26,
                                                        tooltip="Pick a date from the calendar",
                                                        on_click=open_calendar)],
                                  spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            else:
                first = text_field("Maximum points", width=320, value="100")
                second = text_field("Title (optional)", width=320, hint=f"{cat} {next_activity_number(c['id'], cat)}")
                date_row = None
            dlg = None

            def save(_):
                n = next_activity_number(c["id"], cat)
                label = f"{cat} {n}"
                if is_att:
                    try:
                        day = datetime.strptime((first.value or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
                    except ValueError:
                        toast("Pick a date from the calendar.", True)
                        return
                    if any(a["title"] == day for a in term_activities(c["id"], term_dd.value)
                           if cat_of(a) == "Attendance"):
                        toast(f"Attendance for {day} already exists.", True)
                        return
                    title, m = day, 1.0
                else:
                    try:
                        m = float(first.value)
                        if m <= 0:
                            raise ValueError
                    except (ValueError, TypeError):
                        toast("Enter a positive number for the maximum points.", True)
                        return
                    title = (second.value or "").strip() or label
                add_row("activities", {
                    "id": next_id("activities"), "class_id": c["id"],
                    "title": title, "category": cat, "number": str(n),
                    "label": label, "term": term_dd.value,
                    "instructions": "Recorded in the record sheet.", "max_points": m,
                    "deadline": "", "file_path": "", "created_at": timestamp(), "source": "record",
                })
                log_event("class", "Record item added", f"{label} ({term_dd.value}, {c['name']}): {title}", c["id"])
                close_dialog(dlg)
                refresh()
                toast(f"{label} added.")

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text(f"Add {'attendance date' if is_att else cat.lower() + ' item'} ({term_dd.value})"),
                content=ft.Column([date_row if is_att else first] + ([second] if second else []),
                                  tight=True, spacing=12, width=340),
                actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                         compatible_button("Add item", on_click=save)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            open_control(page, dlg)
            page.update()

        def delete_item(item):
            def do():
                for k in [k for k in draft if k == ("max", item["id"]) or k[0] == item["id"]]:
                    draft.pop(k, None)
                    saved_all.pop(k, None)
                for k in [k for k in fields if k[0] == item["id"]]:
                    fields.pop(k, None)
                max_fields.pop(item["id"], None)
                log_event("class", "Record item deleted",
                          f"{activity_label(item)} ({item.get('term') or 'Midterm'}) with all its scores",
                          item["class_id"])
                remove_row("activities", item["id"])
                write_rows("submissions", [s for s in read_rows("submissions") if s["activity_id"] != item["id"]])
                refresh()
                toast("Item deleted.")
            ask_confirm("Delete item", f"Delete \"{activity_label(item)}\"? All recorded scores for it "
                                       "will be removed.", do)

        def save_all(_):
            acts = view["acts"]
            if not acts:
                toast("Add an item first.", True)
                return
            new_max = {}
            for a in acts:
                if is_date_item(a):
                    new_max[a["id"]] = float(a["max_points"])
                    continue
                try:
                    m = float(max_fields[a["id"]].value)
                    if m <= 0:
                        raise ValueError
                except (ValueError, TypeError, KeyError):
                    toast(f"Maximum points for {activity_label(a)} must be a positive number.", True)
                    return
                new_max[a["id"]] = m
            by_act = {a["id"]: a for a in acts}
            updates = []
            for (aid, sid), f in fields.items():
                a = by_act[aid]
                try:
                    ans, mark = parse_entry(f.value, is_date_item(a), new_max[aid])
                except ValueError as exc:
                    toast(f"{activity_label(a)}: {exc}", True)
                    return
                updates.append((aid, sid, ans, mark))

            def do():
                c = by_id("classes", class_dd.value)
                by_act = {a["id"]: a for a in acts}
                for a in acts:
                    if fmt(a["max_points"]) != fmt(new_max[a["id"]]):
                        log_event("score", "Maximum points changed",
                                  f"{activity_label(a)} ({term_dd.value}, {c['name']}): "
                                  f"{fmt(a['max_points'])} -> {fmt(new_max[a['id']])}", c["id"])
                        update_row("activities", a["id"], {"max_points": new_max[a["id"]]})
                rows = read_rows("submissions")
                index = {(s["activity_id"], s["student_id"]): s for s in rows}
                names = {e["student_id"]: e["student_name"] for e in class_enrollments(c["id"])}
                nid = int(next_id("submissions"))
                umap = {u["id"]: u for u in read_rows("users")}
                changes = []
                for aid, sid, ans, mark in updates:
                    a = by_act[aid]
                    date_item = is_date_item(a)
                    s = index.get((aid, sid))
                    old_text = score_to_text(s["score"], date_item, s.get("mark", "")) if s else ""
                    if s:
                        old = fmt(s["score"]) if s["score"] != "" else ""
                        if old == ans and (s.get("mark") or "") == mark:
                            continue
                        s["score"], s["mark"] = ans, mark
                        s["graded_at"] = timestamp() if ans else ""
                    elif ans:
                        rows.append({"id": str(nid), "activity_id": aid, "class_id": c["id"], "student_id": sid,
                                     "student_name": names.get(sid, ""), "file_path": "", "submitted_at": "",
                                     "score": ans, "graded_at": timestamp(), "mark": mark})
                        nid += 1
                    else:
                        continue
                    who = format_sheet_name(umap.get(sid) or {"full_name": names.get(sid, "")})
                    changes.append(("score", "Score changed",
                                    f"{who} - {activity_label(a)} ({term_dd.value}, {c['name']}): "
                                    f"{old_text or 'blank'} -> {score_to_text(ans, date_item, mark) or 'blank'}",
                                    c["id"], sid))
                write_rows("submissions", rows)
                log_events(changes)
                ids = {a["id"] for a in acts}
                for k in [k for k in draft if (k[0] == "max" and k[1] in ids) or k[0] in ids]:
                    draft.pop(k, None)
                    saved_all.pop(k, None)
                fields.clear()
                max_fields.clear()
                refresh()
                toast("Scores saved.")
            ask_confirm("Save scores", f"Save all {cat_dd.value} scores for {term_dd.value}?", do)

        for dd in (class_dd, term_dd, cat_dd):
            dd.on_change = refresh
        year_dd.on_change = lambda e: (fill_classes(), refresh(e))
        add_btn = button("Add item", add_item, ft.Icons.ADD)
        refresh(push=False)
        body = ft.Column([
            ft.Row([ft.Column([section_title("Record sheet", "Record attendance, recitation, quiz, activity, "
                                                             "laboratory, performance and exam scores.")],
                              expand=True),
                    add_btn,
                    button("Save scores", save_all, ft.Icons.SAVE_OUTLINED, True)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([year_dd, class_dd, term_dd, cat_dd], spacing=12, wrap=True),
            info,
            card(holder, padding=12),
        ], spacing=14, scroll=ft.ScrollMode.AUTO)
        shell("Record sheet", current["name"], body, "records")
        state["unsaved"] = has_unsaved

    def reports_view():
        classes = my_classes()
        if not classes:
            toast("Create a class first.")
            return
        current = default_class(classes)
        year_dd, class_dd, fill_classes = year_class_dropdowns(classes, current, {"width": 170}, {"width": 300})
        type_dd = ft.Dropdown(label="Report", width=230, value="Grade Status",
                              options=[ft.dropdown.Option("Grade Status"), ft.dropdown.Option("Incomplete Report"),
                                       ft.dropdown.Option("Attendance Summary")])
        term_dd = ft.Dropdown(label="Term", width=150, value="Midterm",
                              options=[ft.dropdown.Option(t) for t in (*TERMS, "Overall")])
        note = ft.Text("", size=11, color=C("#748198"))
        holder = ft.Container(expand=True)
        data = {"cols": [], "rows": []}

        def refresh(e=None, push=True):
            c = by_id("classes", class_dd.value)
            state["class"] = c
            term_dd.disabled = type_dd.value == "Incomplete Report"
            if type_dd.value == "Attendance Summary":
                allowed = get_absence_limit(c["id"])
                data["cols"], data["rows"] = build_attendance_rows(c, term_dd.value, allowed)
                over = sum(1 for r in data["rows"] if r[-1] == "OVER LIMIT")
                note.value = (f"Counts the attendance dates recorded in the Record sheet. Late counts as "
                              f"{fmt(LATE_CREDIT * 100)}% of a day present; excused days are not counted. "
                              f"Status: OK, At limit (absences = {allowed}) or OVER LIMIT (more than {allowed} "
                              f"absences; set the limit in Grade settings). {over} student(s) over the limit.")
            elif type_dd.value == "Grade Status":
                data["cols"], data["rows"] = build_status_rows(c, term_dd.value)
                note.value = ("GWA scale: 1.00 (97-100%), 1.25 (94-96%), 1.50 (91-93%), 1.75 (88-90%), 2.00 (85-87%), "
                              "2.25 (82-84%), 2.50 (79-81%), 2.75 (76-78%), 3.00 (75%), 5.00 (below 75%). "
                              "Pass = 75% or higher with complete work; Conditional = 75% or higher but some scores are "
                              "not recorded yet; Incomplete = below 75% with unrecorded scores (or nothing graded "
                              "yet); Failed = below 75% with all scores recorded. Excused (EXC) scores are skipped.")
            else:
                data["cols"], data["rows"] = build_incomplete_rows(c)
                note.value = "Lists students who have no recorded score for one or more Midterm or Finals assessments."
            if data["rows"]:
                holder.content = card(table_view(data["cols"], data["rows"]), padding=14, expand=True)
            else:
                holder.content = empty_card(ft.Icons.TASK_ALT, "Nothing to show",
                                            "No students or no incomplete work for this report.")
            if push:
                page.update()

        for dd in (type_dd, term_dd):
            dd.on_change = refresh
        class_dd.on_change = refresh
        year_dd.on_change = lambda e: (fill_classes(), refresh(e))

        def export_click(_):
            c = by_id("classes", class_dd.value)
            title = type_dd.value
            if title in ("Grade Status", "Attendance Summary"):
                context = class_context(c, term_dd.value)
            else:
                context = class_context(c)
            cols, rows = list(data["cols"]), list(data["rows"])
            ask_confirm("Export PDF", f"Export the {title} report as a PDF?",
                        lambda: do_export_pdf(c, context, title, cols, rows,
                                              f"{title.replace(' ', '')}_{c['name']}.pdf".replace(" ", "_")))

        refresh(push=False)
        body = ft.Column([
            ft.Row([section_title("Reports", "Grade status, incomplete work and attendance per class."),
                    ft.Container(expand=True),
                    button("Export PDF", export_click, ft.Icons.PICTURE_AS_PDF, True)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([year_dd, class_dd, type_dd, term_dd], spacing=12, wrap=True),
            note,
            holder,
        ], spacing=14)
        shell("Reports", "Student grade status and incomplete work", body, "reports")

    def profile_dialog():
        user = state["user"]
        last0, first0, mi0 = name_parts(user)
        first = text_field("First name", width=360, value=first0)
        mi = text_field("Middle initial (optional)", width=360, value=mi0)
        mi.max_length = 1
        last = text_field("Last name", width=360, value=last0)
        sfx_field = text_field("Suffix (optional, e.g. Jr., Sr., III)", width=360, value=user_suffix(user))
        sfx_field.max_length = 6
        dlg = None

        def save(_):
            f = (first.value or "").strip()
            m = (mi.value or "").strip().rstrip(".").upper()[:1]
            l = (last.value or "").strip()
            if not f or not l:
                toast("First name and last name are required.", True)
                return
            sfx = clean_suffix(sfx_field.value)
            full = format_full_name(f, m, l, sfx)

            def do():
                update_row("users", user["id"], {"first_name": f, "middle_initial": m, "last_name": l, "suffix": sfx,
                                                 "full_name": full})
                enr = read_rows("enrollments")
                for e in enr:
                    if e["student_id"] == user["id"]:
                        e["student_name"] = full
                write_rows("enrollments", enr)
                sub = read_rows("submissions")
                for x in sub:
                    if x["student_id"] == user["id"]:
                        x["student_name"] = full
                write_rows("submissions", sub)
                cls = read_rows("classes")
                for c in cls:
                    if c["teacher_id"] == user["id"]:
                        c["teacher_name"] = full
                write_rows("classes", cls)
                log_event("account", "Profile name changed", f"{user['full_name']} -> {full}")
                user.update({"first_name": f, "middle_initial": m, "last_name": l, "suffix": sfx,
                             "full_name": full})
                close_dialog(dlg)
                dashboard()
                toast("Profile updated.")
            ask_confirm("Update profile", f"Save your name as \"{full}\"?", do)

        def pw(_):
            close_dialog(dlg)
            change_password_dialog()

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("My profile"),
            content=ft.Column([ft.Text(f"Account: {user['username']}", size=12, color=C("#748198")),
                               first, mi, last, sfx_field,
                               ft.TextButton("Change my password", on_click=pw)],
                              tight=True, spacing=12, width=380),
            actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                     compatible_button("Save profile", on_click=save)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        open_control(page, dlg)
        page.update()

    def backup_data():
        destination = native_file_dialog(
            "save", title="Back up StudyTrack data",
            initialfile=f"StudyTrack_backup_{datetime.now().strftime('%Y-%m-%d')}.zip",
            defaultextension=".zip", filetypes=[["ZIP files", "*.zip"]])
        if not destination:
            return
        try:
            make_backup_zip(destination)
            log_event("backup", "Backup created", destination)
            toast(f"Backup saved: {destination}")
        except Exception as exc:
            toast(f"Backup failed: {exc}", True)

    def activity_log_view():
        user = state["user"]
        is_student = user["role"] == "student"
        if is_student:
            kinds = [("all", "Everything"), ("score", "Scores"), ("class", "Classes"),
                     ("account", "My account"), ("security", "Logins")]
        else:
            kinds = [("all", "Everything"), ("score", "Scores"), ("class", "Classes"), ("account", "Accounts"),
                     ("security", "Logins & security"), ("backup", "Backups")]
        kind_dd = ft.Dropdown(label="Show", width=200, value="all",
                              options=[ft.dropdown.Option(k, v) for k, v in kinds])
        search = text_field("Search", width=260, hint="class, activity, action...")
        role_dd = ft.Dropdown(label="Who", width=180, value="all",
                              options=[ft.dropdown.Option("all", "Everyone"),
                                       ft.dropdown.Option("teacher", "Teachers"),
                                       ft.dropdown.Option("student", "Students"),
                                       ft.dropdown.Option("admin", "Admin")])
        count = ft.Text("", size=12, color=C("#748198"))
        holder = ft.Container(expand=True)
        PAGE_SIZE = 50
        pg = {"n": 0}     # 0 = the newest page; higher numbers are older entries

        flt = {"date": None, "from": None, "to": None}   # a specific day and / or a time-of-day range
        filter_note = ft.Text("", size=12, color=C("#526078"), weight=ft.FontWeight.W_600)

        def filter_active():
            return bool(flt["date"] or flt["from"] or flt["to"])

        def filter_text():
            parts = []
            if flt["date"]:
                parts.append(f"{flt['date']:%A, %b %d, %Y}")
            if flt["from"] or flt["to"]:
                a = f"{flt['from']:%I:%M %p}" if flt["from"] else "start of day"
                b = f"{flt['to']:%I:%M %p}" if flt["to"] else "end of day"
                parts.append(f"{a} to {b}")
            return ("Showing: " + "  |  ".join(parts)) if parts else "Showing all dates and times"

        def matches_filter(r):
            if not filter_active():
                return True
            t = _parse_time(r["time"])
            if t is None:
                return False
            if flt["date"] and t.date() != flt["date"]:
                return False
            minute = t.hour * 60 + t.minute
            lo = flt["from"].hour * 60 + flt["from"].minute if flt["from"] else None
            hi = flt["to"].hour * 60 + flt["to"].minute if flt["to"] else None
            if lo is not None and hi is not None:
                return (lo <= minute <= hi) if lo <= hi else (minute >= lo or minute <= hi)  # past midnight
            if lo is not None:
                return minute >= lo
            if hi is not None:
                return minute <= hi
            return True

        def visible_rows():
            rows = read_rows("activity_log")
            if is_student:
                mine = {e["class_id"] for e in read_rows("enrollments") if e["student_id"] == user["id"]}
                posted = ("Announcement posted", "Announcement saved", "Activity created", "Activity saved")
                rows = [r for r in rows
                        if r["user_id"] == user["id"] or r["student_id"] == user["id"]
                        or (r["class_id"] in mine and r["action"] in posted)]
            elif user["role"] == "teacher":
                mine = {c["id"] for c in read_rows("classes") if c["teacher_id"] == user["id"]}
                rows = [r for r in rows if r["class_id"] in mine or r["user_id"] == user["id"]]
            elif role_dd.value != "all":
                rows = [r for r in rows if r["role"] == role_dd.value]
            return rows

        def go_page(delta):
            pg["n"] += delta
            refresh(keep_page=True)

        def with_pager(table_card, total, pages):
            """The table card plus Older / Newer buttons underneath (only when there is more than one page)."""
            if pages <= 1:
                return table_card
            older = button("Older entries", lambda e: go_page(1), ft.Icons.ARROW_BACK)
            newer = button("Newer entries", lambda e: go_page(-1), ft.Icons.ARROW_FORWARD)
            older.disabled = pg["n"] >= pages - 1
            newer.disabled = pg["n"] <= 0
            pager = ft.Row([older,
                            ft.Text(f"Page {pg['n'] + 1} of {pages}", size=12, color=C("#526078"),
                                    weight=ft.FontWeight.W_600),
                            newer],
                           alignment=ft.MainAxisAlignment.CENTER, spacing=14,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER)
            return ft.Column([table_card, pager], spacing=10, expand=True)

        def refresh(e=None, push=True, keep_page=False):
            if not keep_page:
                pg["n"] = 0     # a new filter or search starts again from the newest entries
            rows = visible_rows()
            if kind_dd.value != "all":
                rows = [r for r in rows if r["kind"] == kind_dd.value]
            q = (search.value or "").strip().casefold()
            if q:
                rows = [r for r in rows if q in f"{r['user_name']} {r['action']} {r['details']}".casefold()]
            rows = [r for r in rows if matches_filter(r)]
            rows.sort(key=lambda r: int(r["id"]) if (r.get("id") or "").isdigit() else 0, reverse=True)
            total = len(rows)
            pages = max(1, -(-total // PAGE_SIZE))
            pg["n"] = max(0, min(pg["n"], pages - 1))
            start = pg["n"] * PAGE_SIZE
            rows = rows[start:start + PAGE_SIZE]
            filter_note.value = filter_text()
            count.value = (f"Showing {start + 1}-{start + len(rows)} of {total} entries (newest first)"
                           if rows else f"Showing 0 of {total} entries")
            if rows and is_student:
                class_names = {c["id"]: c["name"] for c in read_rows("classes")}
                holder.content = with_pager(card(table_view(
                    ["Date & Time", "Activity", "Description", "Class", "Performed By"],
                    [(r["time"], r["action"], r["details"], class_names.get(r["class_id"], "—"),
                      "You" if r["user_id"] == user["id"]
                      else (f"{r['user_name'] or '—'} ({r['role'].title()})" if r["role"] else (r["user_name"] or "—")))
                     for r in rows], fill=True), padding=14, expand=True), total, pages)
            elif rows:
                holder.content = with_pager(card(table_view(["Date & Time", "User", "Role", "Activity", "Description"],
                                                 [(r["time"], r["user_name"] or "—", (r["role"] or "—").title(),
                                                   r["action"], r["details"])
                                                  for r in rows], fill=True), padding=14, expand=True), total, pages)
            elif filter_active():
                holder.content = empty_card(ft.Icons.EVENT_BUSY, "Nothing on that date or time",
                                            "Try another day or time range, or clear the date and time filter.")
            else:
                holder.content = empty_card(ft.Icons.HISTORY, "No activity yet",
                                            "Your activity will be listed here." if is_student
                                            else "Changes will be listed here.")
            if push:
                page.update()

        def on_date(e):
            v = e.control.value
            if v:
                flt["date"] = v.date() if isinstance(v, datetime) else v
                refresh()

        def on_from(e):
            if e.control.value:
                flt["from"] = e.control.value
                refresh()

        def on_to(e):
            if e.control.value:
                flt["to"] = e.control.value
                refresh()

        def pick_date(_):
            now = datetime.now()
            open_control(page, ft.DatePicker(
                first_date=datetime(2020, 1, 1), last_date=now.replace(hour=23, minute=59),
                value=datetime.combine(flt["date"], time(0, 0)) if flt["date"] else None,
                on_change=on_date))

        def pick_from(_):
            open_control(page, ft.TimePicker(value=flt["from"] or time(0, 0), on_change=on_from))

        def pick_to(_):
            open_control(page, ft.TimePicker(value=flt["to"] or time(23, 59), on_change=on_to))

        def set_day(days_back):
            flt["date"] = (datetime.now() - timedelta(days=days_back)).date()
            refresh()

        def clear_filter(_=None):
            flt.update({"date": None, "from": None, "to": None})
            refresh()

        kind_dd.on_change = refresh
        search.on_change = refresh
        role_dd.on_change = refresh
        refresh(push=False)
        date_time_row = card(ft.Column([
            ft.Text("Check a specific day or time", size=13, weight=ft.FontWeight.BOLD, color=C("#18243A")),
            ft.Row([
                button("Pick a date", pick_date, ft.Icons.CALENDAR_MONTH_OUTLINED),
                button("Today", lambda e: set_day(0)),
                button("Yesterday", lambda e: set_day(1)),
                button("From time", pick_from, ft.Icons.ACCESS_TIME),
                button("To time", pick_to, ft.Icons.ACCESS_TIME),
                ft.TextButton("Clear date & time", on_click=clear_filter),
            ], spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            filter_note,
        ], spacing=10), padding=16)
        if is_student:
            subtitle = ("Your logins, class activity and submissions, plus score updates and new posts from your "
                        "teachers. Use the date and time options to check a specific day or time.")
        elif user["role"] == "admin":
            subtitle = "Everything done by teachers, students and admin, and when."
        else:
            subtitle = "Who changed what, and when. Score changes show the old and new value."
        body = ft.Column([
            section_title("Activity log", subtitle),
            ft.Row([kind_dd] + ([role_dd] if user["role"] == "admin" else []) + [search, count],
                   spacing=14, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            date_time_row,
            holder,
        ], spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        shell("Activity log",
              "Admin workspace" if user["role"] == "admin" else "Your activity" if is_student else "Your classes",
              body, "log")

    def restore_data():
        path = native_file_dialog("open", title="Choose a StudyTrack backup (ZIP)",
                                  filetypes=[["ZIP files", "*.zip"]])
        if not path:
            return
        try:
            validate_backup(path)
        except ValueError as exc:
            toast(str(exc), True)
            return

        def do():
            try:
                safety = restore_backup_zip(path)
            except Exception as exc:
                toast(f"Restore failed: {exc}", True)
                return
            log_event("backup", "Backup restored", f"From {os.path.basename(path)}. Previous data kept in {safety}")
            _SESSION["user"] = None
            state["user"] = None
            state["class"] = None
            login_view()
            toast(f"Backup restored. Please log in again. Your previous data was kept in: {safety}")
        ask_confirm("Restore backup",
                    f"Replace ALL current data (users, classes, scores) with the backup "
                    f"\"{os.path.basename(path)}\"? A copy of the current data is kept in the "
                    "studytrack_backups folder so nothing is lost. You will be logged out.", do)

    def change_password_dialog():
        current = text_field("Current password", password=True, width=360)
        new = text_field("New password (at least 6 characters)", password=True, width=360)
        confirm = text_field("Confirm new password", password=True, width=360)
        dlg = None

        def save(_):
            user = state["user"]
            if not verify_password(current.value or "", user["password_hash"]):
                toast("Current password is incorrect.", True)
                return
            if len(new.value or "") < 6:
                toast("Use at least 6 characters.", True)
                return
            if new.value != confirm.value:
                toast("The new passwords do not match.", True)
                return

            def do():
                hashed = hash_password(new.value)
                update_row("users", user["id"], {"password_hash": hashed})
                user["password_hash"] = hashed
                log_event("account", "Password changed", user["username"])
                close_dialog(dlg)
                toast("Password changed.")
            ask_confirm("Change password", "Change your password?", do)

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Change password"),
            content=ft.Column([current, new, confirm], tight=True, spacing=12, width=380),
            actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                     compatible_button("Save password", on_click=save)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        open_control(page, dlg)
        page.update()

    def admin_users_view():
        role_dd = ft.Dropdown(label="Show", width=240, value="all",
                              options=[ft.dropdown.Option("all", "Teachers & students"),
                                       ft.dropdown.Option("pending", "Teachers waiting for approval"),
                                       ft.dropdown.Option("teacher", "Teachers only"),
                                       ft.dropdown.Option("student", "Students only"),
                                       ft.dropdown.Option("inactive", "Inactive accounts")])
        count = ft.Text("", size=12, color=C("#748198"))
        holder = ft.Container(expand=True)

        def approve(u):
            update_row("users", u["id"], {"approved": "1"})
            log_event("account", "Teacher approved", u["full_name"])
            refresh()
            toast(f"{u['full_name']} can now log in as a teacher.")

        def unlock(u):
            update_row("users", u["id"], {"failed_attempts": "", "locked_until": ""})
            log_event("security", "Login unlocked by admin", u["username"])
            refresh()
            toast(f"{u['full_name']} can try to log in again.")

        def toggle_active(u):
            active = u.get("active") != "0"

            def do():
                update_row("users", u["id"], {"active": "0" if active else "1"})
                u["active"] = "0" if active else "1"
                log_event("account", "Account set inactive" if active else "Account set active",
                          f"{u['full_name']} ({u['username']}, {u['role']})")
                refresh()
                toast(f"{u['full_name']} is now {'inactive' if active else 'active'}.")
            if active:
                ask_confirm("Set inactive", f"Set {u['full_name']} to inactive? They will not be able to log in, "
                                            "but their classes, enrollments and scores are kept. You can set the "
                                            "account active again anytime.", do)
            else:
                ask_confirm("Set active", f"Set {u['full_name']} to active? They will be able to log in again.", do)

        def edit_name(u):
            last0, first0, mi0 = name_parts(u)
            first = text_field("First name", width=360, value=first0)
            mi = text_field("Middle initial (optional)", width=360, value=mi0)
            mi.max_length = 1
            last = text_field("Last name", width=360, value=last0)
            sfx_field = text_field("Suffix (optional, e.g. Jr., Sr., III)", width=360, value=user_suffix(u))
            sfx_field.max_length = 6
            dlg = None

            def save(_):
                f = (first.value or "").strip()
                m = (mi.value or "").strip().rstrip(".").upper()[:1]
                l = (last.value or "").strip()
                if not f or not l:
                    toast("First name and last name are required.", True)
                    return
                sfx = clean_suffix(sfx_field.value)
                full = format_full_name(f, m, l, sfx)
                update_row("users", u["id"], {"first_name": f, "middle_initial": m, "last_name": l, "suffix": sfx,
                                              "full_name": full})
                enr = read_rows("enrollments")
                for e in enr:
                    if e["student_id"] == u["id"]:
                        e["student_name"] = full
                write_rows("enrollments", enr)
                sub = read_rows("submissions")
                for x in sub:
                    if x["student_id"] == u["id"]:
                        x["student_name"] = full
                write_rows("submissions", sub)
                cls = read_rows("classes")
                for c in cls:
                    if c["teacher_id"] == u["id"]:
                        c["teacher_name"] = full
                write_rows("classes", cls)
                log_event("account", "Name edited by admin", f"{u['full_name']} -> {full}")
                close_dialog(dlg)
                refresh()
                toast("Name updated.")

            dlg = ft.AlertDialog(
                modal=True, title=ft.Text("Edit name"),
                content=ft.Column([first, mi, last, sfx_field], tight=True, spacing=12, width=380),
                actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                         compatible_button("Save", on_click=save)],
                actions_alignment=ft.MainAxisAlignment.END)
            open_control(page, dlg)
            page.update()

        def refresh(e=None, push=True):
            users = [u for u in read_rows("users") if u["role"] != "admin"]
            if role_dd.value == "pending":
                users = [u for u in users if u["role"] == "teacher" and u.get("approved") == "0"]
            elif role_dd.value == "inactive":
                users = [u for u in users if u.get("active") == "0"]
            elif role_dd.value != "all":
                users = [u for u in users if u["role"] == role_dd.value]
            users.sort(key=lambda u: (u["role"], name_parts(u)[0].casefold(), name_parts(u)[1].casefold()))
            count.value = f"{len(users)} account(s)"
            rows = []
            for u in users:
                pending = u["role"] == "teacher" and u.get("approved") == "0"
                inactive = u.get("active") == "0"
                actions = []
                locked = lock_minutes_left(u.get("locked_until"))
                if pending:
                    actions.append(compatible_button("Approve", on_click=lambda e, x=u: approve(x)))
                if locked:
                    actions.append(ft.IconButton(icon=ft.Icons.LOCK_OPEN, icon_size=18, tooltip="Unlock login",
                                                 on_click=lambda e, x=u: unlock(x)))
                actions += [
                    ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=18, tooltip="Edit name",
                                  on_click=lambda e, x=u: edit_name(x)),
                    ft.TextButton("Set active" if inactive else "Set inactive",
                                  on_click=lambda e, x=u: toggle_active(x)),
                ]
                if pending:
                    state_text, state_color = "Waiting for approval", C("#B54708")
                elif inactive:
                    state_text, state_color = "Inactive", C("#B42318")
                elif locked:
                    state_text, state_color = f"Locked (about {locked} min)", C("#B42318")
                else:
                    state_text, state_color = (u.get("last_login") or "Never logged in"), C("#344054")
                rows.append(ft.Container(
                    content=ft.Row([
                        ft.Container(ft.Text(format_sheet_name(u), size=12, weight=ft.FontWeight.BOLD), expand=3),
                        ft.Container(ft.Text(u["username"], size=12, selectable=True), expand=3),
                        ft.Container(ft.Text(u["role"].title(), size=12), expand=1),
                        ft.Container(ft.Text(state_text, size=12, color=state_color), expand=2),
                        ft.Container(ft.Row(actions, spacing=2, alignment=ft.MainAxisAlignment.END), width=230),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=pad_sym(10, 4), border=border_all(1, C("#EEF2F8")), border_radius=10))
            if not rows:
                holder.content = empty_card(ft.Icons.PEOPLE_OUTLINE, "No accounts to show", "Nothing matches this filter.")
            else:
                def head(text, **kw):
                    return ft.Container(ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=C("#344054")), **kw)
                # same column widths and padding as the account rows, so the titles line up
                header = ft.Container(
                    content=ft.Row([
                        head("Full Name", expand=3),
                        head("Email", expand=3),
                        head("Role", expand=1),
                        head("Status / Last Login", expand=2),
                        ft.Container(ft.Row([ft.Text("Actions", size=12, weight=ft.FontWeight.BOLD,
                                                     color=C("#344054"))],
                                            alignment=ft.MainAxisAlignment.END), width=230),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=pad_sym(10, 4), border=border_only(bottom=ft.BorderSide(1, C("#E7ECF4"))))
                holder.content = card(ft.Column([
                    header,
                    ft.Column(rows, spacing=6, scroll=ft.ScrollMode.AUTO, expand=True,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                ], spacing=8, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                    padding=14, expand=True)
            if push:
                page.update()

        role_dd.on_change = refresh
        refresh(push=False)
        body = ft.Column([
            section_title("Manage users", "Approve teachers, fix names, or set accounts active / inactive."),
            ft.Row([role_dd, count], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            holder,
        ], spacing=14)
        shell("Manage users", "Admin workspace", body, "users")

    def admin_reports_view():
        """Admin report dashboard: pick a school year first, then the report type.
        Numbers in the tables can be clicked to see the list behind them."""
        years = sorted(read_rows("school_years"), key=lambda r: r["name"], reverse=True)
        sections = sorted([x for x in read_rows("sections") if x.get("active") != "0"],
                          key=lambda r: r["name"].casefold())
        year_dd = ft.Dropdown(label="School year", width=220, value=None,
                              options=[ft.dropdown.Option("all", "All school years")] +
                                      [ft.dropdown.Option(y["name"]) for y in years])
        type_dd = ft.Dropdown(label="Report", width=400, value="school_year", disabled=True,
                              options=[ft.dropdown.Option("school_year", "School year report (sections per year)"),
                                       ft.dropdown.Option("section", "Section report (subjects per section)"),
                                       ft.dropdown.Option("subject", "Subject report (students per subject)"),
                                       ft.dropdown.Option("active", "Active classes report (subjects & students)")])
        section_dd = ft.Dropdown(label="Section", width=220, value="all", visible=False,
                                 options=[ft.dropdown.Option("all", "All sections")] +
                                         [ft.dropdown.Option(s["name"]) for s in sections])
        note = ft.Text("", size=11, color=C("#748198"))
        holder = ft.Container(expand=True)
        data = {"cols": [], "rows": []}
        titles = {"school_year": "School Year Report", "section": "Section Report",
                  "subject": "Subject Report", "active": "Active Classes Report"}
        clickable = ("Sections", "Subjects", "Classes", "Students enrolled")
        export_btn = button("Export PDF", lambda e: export_click(e), ft.Icons.PICTURE_AS_PDF, True)

        def row_classes(kind, row):
            """The class rows behind one line of a report."""
            year = year_dd.value
            if kind == "school_year":
                return [c for c in read_rows("classes") if (c.get("school_year") or "") == row[0]]
            if kind == "section":
                return _report_classes(year, row[0])
            if kind == "subject":
                return [c for c in _report_classes(year, row[0]) if c["subject"] == row[1]]
            return [c for c in _report_classes(year, section_dd.value, active_only=True)
                    if (c.get("school_year") or "—") == row[0] and c["name"] == row[1]
                    and c["subject"] == row[2] and c["teacher_name"] == row[3]]

        def show_detail(kind, row, col):
            cs = sorted(row_classes(kind, row), key=lambda c: (c["name"].casefold(), c["subject"].casefold()))
            users = {u["id"]: u for u in read_rows("users")}
            enr = {c["id"]: class_enrollments(c["id"]) for c in cs}
            icons = {"Sections": ft.Icons.GROUPS_OUTLINED, "Subjects": ft.Icons.MENU_BOOK_OUTLINED,
                     "Classes": ft.Icons.SCHOOL_OUTLINED, "Students enrolled": ft.Icons.GROUP_OUTLINED}
            noun = {"Sections": "section", "Subjects": "subject", "Classes": "class",
                    "Students enrolled": "student"}[col]
            accent = C("#3157D5", True)

            def chip(text, color=None, bg=None):
                return ft.Container(content=ft.Text(text, size=11, weight=ft.FontWeight.BOLD,
                                                    color=color or accent),
                                    bgcolor=bg or C("#EEF2FF"), padding=pad_sym(9, 4), border_radius=10)

            def item(icon, title, sub=None, trailing=None):
                texts = [ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=C("#18243A"))]
                if sub:
                    texts.append(ft.Text(sub, size=11, color=C("#748198")))
                return ft.Container(
                    content=ft.Row([
                        ft.Container(content=ft.Icon(icon, size=18, color=accent), bgcolor=C("#EEF2FF"),
                                     padding=9, border_radius=10),
                        ft.Column(texts, spacing=2, expand=True),
                    ] + ([trailing] if trailing else []), spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=pad_sym(12, 10), bgcolor=C("#F7F9FD"), border_radius=12,
                    border=border_all(1, C("#E7ECF4")))

            items = []
            if col == "Sections":
                for n in sorted({c["name"] for c in cs}, key=str.casefold):
                    mine = [c for c in cs if c["name"] == n]
                    items.append(item(icons[col], n, f"{len(mine)} class(es) • "
                                                     f"{sum(len(enr[c['id']]) for c in mine)} student(s)"))
            elif col == "Subjects":
                for n in sorted({c["subject"] for c in cs}, key=str.casefold):
                    mine = [c for c in cs if c["subject"] == n]
                    items.append(item(icons[col], n, f"{len(mine)} class(es) • "
                                                     f"{sum(len(enr[c['id']]) for c in mine)} student(s)"))
            elif col == "Classes":
                for c in cs:
                    items.append(item(icons[col], f"{c['name']} — {c['subject']}",
                                      f"S.Y. {c.get('school_year') or '—'} • {c['teacher_name']}",
                                      chip(f"{len(enr[c['id']])} students") if not is_archived(c)
                                      else chip("Archived", C("#B54708"), C("#FEE4E2"))))
            else:
                for c in cs:
                    items.append(ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.SCHOOL_OUTLINED, size=16, color="#FFFFFF"),
                            ft.Text(f"{c['name']} — {c['subject']}", size=12, weight=ft.FontWeight.BOLD,
                                    color="#FFFFFF", expand=True),
                            ft.Text(f"{len(enr[c['id']])} student(s)", size=11, color="#DCE6FF"),
                        ], spacing=8),
                        padding=pad_sym(12, 8), bgcolor=C("#3157D5"), border_radius=10))
                    if not enr[c["id"]]:
                        items.append(ft.Text("No students enrolled yet.", size=12, color=C("#748198")))
                    for i, e in enumerate(enr[c["id"]], start=1):
                        name = student_label(e, users)
                        items.append(ft.Container(
                            content=ft.Row([
                                ft.Text(str(i), size=11, color=C("#9AA5B5"), width=22),
                                ft.CircleAvatar(content=ft.Text(name[:1].upper(), size=12, color="#FFFFFF"),
                                                bgcolor=C("#4768D8"), radius=14),
                                ft.Text(name, size=13, color=C("#18243A")),
                            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            padding=pad_sym(10, 6), bgcolor=C("#F7F9FD"), border_radius=10,
                            border=border_all(1, C("#E7ECF4"))))
            if not items:
                items = [ft.Text("Nothing to show.", size=12, color=C("#748198"))]
            total = (sum(len(v) for v in enr.values()) if col == "Students enrolled"
                     else len({c["name"] for c in cs}) if col == "Sections"
                     else len({c["subject"] for c in cs}) if col == "Subjects" else len(cs))
            if kind in ("school_year", "section"):
                what = ("School year " if kind == "school_year" else "Section ") + row[0]
            elif kind == "subject":
                what = f"{row[0]} • {row[1]}"
            else:
                what = f"{row[1]} • {row[2]}"
            header = ft.Row([
                ft.Container(content=ft.Icon(icons[col], size=24, color="#FFFFFF"), bgcolor=C("#3157D5"),
                             padding=12, border_radius=14),
                ft.Column([ft.Text(col, size=19, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                           ft.Text(what, size=12, color=C("#748198"))], spacing=2, expand=True),
                chip(f"{total} {noun}{'' if total == 1 else 's'}"),
            ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            body = ft.Container(
                content=ft.Column([ft.Divider(height=1, color=C("#E7ECF4")),
                                   ft.Column(items, spacing=8, scroll=ft.ScrollMode.AUTO, tight=True,
                                             height=min(380, 58 * len(items) + 8))], spacing=12, tight=True),
                width=520)
            dlg = ft.AlertDialog(
                modal=True, title=header, content=body,
                actions=[compatible_button("Close", on_click=lambda e: close_dialog(dlg),
                                           icon=ft.Icons.CLOSE,
                                           style=ft.ButtonStyle(bgcolor=C("#3157D5"), color="#FFFFFF",
                                                                shape=ft.RoundedRectangleBorder(radius=10),
                                                                padding=pad_sym(18, 12)))],
                actions_alignment=ft.MainAxisAlignment.END,
                shape=ft.RoundedRectangleBorder(radius=20), bgcolor=C("#FFFFFF"))
            open_control(page, dlg)
            page.update()

        def report_table(kind, cols, rows):
            def build(i, col, row, v):
                if col in clickable:
                    return ft.Container(
                        content=ft.Text(str(v), size=12, weight=ft.FontWeight.BOLD, color=C("#3157D5", True)),
                        tooltip="Click to see the list", ink=True, border_radius=6, padding=pad_sym(0, 4),
                        on_click=lambda e, r=row, cn=col: show_detail(kind, r, cn))
                return None
            return table_view(cols, rows, cell_builder=build)

        def refresh(e=None, push=True):
            if not year_dd.value:
                type_dd.disabled = True
                section_dd.visible = False
                export_btn.disabled = True
                data["cols"], data["rows"] = [], []
                note.value = "Choose a school year first, then pick the report you want to see."
                holder.content = empty_card(ft.Icons.CALENDAR_MONTH_OUTLINED, "Choose a school year first",
                                            "Pick a school year (or All school years) above to unlock the reports.")
                if push:
                    page.update()
                return
            type_dd.disabled = False
            export_btn.disabled = False
            kind = type_dd.value
            section_dd.visible = kind in ("subject", "active")
            if kind == "school_year":
                cols, rows = build_year_report(year_dd.value)
                note.value = ("Sections = the different class sections that have at least one class in that "
                              "school year. Archived classes are included. Click a number to see the list.")
            elif kind == "section":
                cols, rows = build_section_report(year_dd.value)
                note.value = ("Subjects = the different subjects offered to that section through classes. "
                              "Click a number to see the list.")
            elif kind == "subject":
                cols, rows = build_subject_report(year_dd.value, section_dd.value)
                note.value = ("Students enrolled in each subject. Pick a section to see just its subjects. "
                              f"Total students shown: {sum(r[-1] for r in rows)}. Click a number to see the list.")
            else:
                cols, rows = build_active_class_report(year_dd.value, section_dd.value)
                note.value = ("Only active (not archived) classes, with the students enrolled in each subject. "
                              f"Total students: {sum(r[-1] for r in rows)}. Click a number to see the list.")
            data["cols"], data["rows"] = list(cols), list(rows)
            if rows and kind == "active":
                def stat(icon, value, label, accent):
                    return ft.Container(
                        content=ft.Row([
                            ft.Container(content=ft.Icon(icon, color=C(accent, True), size=18),
                                         bgcolor=C("#EEF2FF"), padding=8, border_radius=10),
                            ft.Row([ft.Text(str(value), size=20, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                                    ft.Text(label, size=12, color=C("#748198"))],
                                   spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        expand=True, padding=pad_sym(8, 0))

                summary = ft.Container(
                    content=ft.Row([
                        stat(ft.Icons.WORKSPACES_OUTLINED, len({r[1] for r in rows}), "Sections", "#3157D5"),
                        ft.VerticalDivider(width=1, color=C("#E7ECF4")),
                        stat(ft.Icons.MENU_BOOK_OUTLINED, len({r[2] for r in rows}), "Subjects", "#7C3AED"),
                        ft.VerticalDivider(width=1, color=C("#E7ECF4")),
                        stat(ft.Icons.TASK_ALT, len(rows), "Active classes", "#0D9488"),
                        ft.VerticalDivider(width=1, color=C("#E7ECF4")),
                        stat(ft.Icons.PEOPLE_OUTLINE, sum(r[-1] for r in rows), "Students enrolled", "#DB2777"),
                    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, height=44),
                    padding=pad_sym(16, 10), bgcolor=C("#FFFFFF"), border_radius=14,
                    border=border_all(1, C("#E7ECF4")))
                holder.content = ft.Column([summary,
                                            card(report_table(kind, cols, rows), padding=14, expand=True)],
                                           spacing=14, expand=True)
            elif rows:
                holder.content = card(report_table(kind, cols, rows), padding=14, expand=True)
            else:
                holder.content = empty_card(ft.Icons.TASK_ALT, "Nothing to show",
                                            "No data matches this report and filter yet.")
            if push:
                page.update()

        def export_click(_):
            kind = type_dd.value
            parts = ["School Year: " + ("All" if year_dd.value == "all" else year_dd.value)]
            if kind in ("subject", "active"):
                parts.append("Section: " + ("All" if section_dd.value == "all" else section_dd.value))
            context = "   |   ".join(parts)
            title = titles[kind]
            cols, rows = list(data["cols"]), list(data["rows"])
            ask_confirm("Export PDF", f"Export the {title} as a PDF?",
                        lambda: do_export_pdf(None, context, title, cols, rows,
                                              f"{title.replace(' ', '')}.pdf"))

        for dd in (type_dd, year_dd, section_dd):
            dd.on_change = refresh
        refresh(push=False)
        body = ft.Column([
            ft.Row([section_title("Reports", "Choose a school year, then the report. Click any number for details."),
                    ft.Container(expand=True),
                    export_btn],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([year_dd, type_dd, section_dd], spacing=12, wrap=True),
            note,
            holder,
        ], spacing=14)
        shell("Reports", "Admin workspace", body, "admin_reports")

    def school_settings_view():
        """Admin page: school heading used on exported reports, logo and passing grade (courses are on the Courses page)."""
        name_tf = text_field("School / university name", width=620, value=get_setting("school_name"))
        loc_tf = text_field("Location (campus, city, province)", width=620, value=get_setting("school_location"))
        line3_tf = text_field("Extra heading line (optional, e.g. a college or department)", width=620,
                              value=get_setting("report_line3"))
        passing_tf = text_field("Passing grade (%)", width=300, value=get_setting("passing_grade"))
        logo = {"path": get_setting("logo_path"), "new": False}
        logo_label = ft.Text("", size=11, color=C("#748198"))
        preview = ft.Container()

        def refresh_preview(push=True):
            logo_label.value = Path(logo["path"]).name if logo["path"] else "No logo selected"
            lines = [ft.Text((name_tf.value or "").strip() or "School name", size=14, weight=ft.FontWeight.BOLD,
                             color="#111111", text_align=ft.TextAlign.CENTER),
                     ft.Text((loc_tf.value or "").strip(), size=11, color="#333333", text_align=ft.TextAlign.CENTER)]
            if (line3_tf.value or "").strip():
                lines.append(ft.Text(line3_tf.value.strip(), size=11, color="#333333",
                                     text_align=ft.TextAlign.CENTER))
            shown = resolve_path(logo["path"]) if logo["path"] and not logo["new"] else logo["path"]
            if shown and os.path.isfile(shown):
                lines.insert(0, ft.Image(src=shown, height=56, fit=ft.ImageFit.CONTAIN)
                             if hasattr(ft, "ImageFit") else ft.Image(src=shown, height=56))
            preview.content = ft.Column(lines, spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            if push:
                page.update()

        for tf in (name_tf, loc_tf, line3_tf):
            tf.on_change = lambda e: refresh_preview()

        def browse(_):
            def got(path):
                if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg"):
                    toast("Please choose a PNG or JPG image for the logo.", True)
                    return
                logo["path"], logo["new"] = path, True
                refresh_preview()
            selected = native_file_dialog("open", title="Choose a logo (PNG or JPG)",
                                          filetypes=[["Images", "*.png *.jpg *.jpeg"]])
            if selected:
                got(selected)

        def remove_logo(_):
            logo["path"], logo["new"] = "", False
            refresh_preview()

        def save(_):
            n = (name_tf.value or "").strip()
            if not n:
                toast("The school name is required.", True)
                return
            try:
                passing = float((passing_tf.value or "").strip())
                if passing <= 0 or passing > 100:
                    raise ValueError
            except ValueError:
                toast("The passing grade must be a number from 1 to 100.", True)
                return

            def do():
                try:
                    path = logo["path"]
                    if logo["new"] and path:
                        path = copy_attachment(path, FILES_DIR, "logo")
                    set_setting("school_name", n)
                    set_setting("school_location", (loc_tf.value or "").strip())
                    set_setting("report_line3", (line3_tf.value or "").strip())
                    set_setting("passing_grade", fmt(passing))
                    set_setting("logo_path", path)
                    log_event("account", "School settings changed", f"{n} | passing grade: {fmt(passing)}")
                    school_settings_view()
                    toast("School settings saved. New exports will use them.")
                except Exception as exc:
                    toast(f"Could not save settings: {exc}", True)
            ask_confirm("Save school settings", "Save these school settings? They apply to all new report exports.", do)

        refresh_preview(push=False)
        body = ft.Column([
            ft.Row([section_title("School settings",
                                  "The heading printed on exported PDF / CSV reports, plus the passing grade."),
                    ft.Container(expand=True),
                    button("Save settings", save, ft.Icons.SAVE_OUTLINED, True)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            card(ft.Column([
                ft.Text("Report heading", size=15, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                name_tf, loc_tf, line3_tf,
                ft.Row([button("Choose logo", browse, ft.Icons.IMAGE_OUTLINED),
                        ft.TextButton("Remove logo", on_click=remove_logo), logo_label],
                       wrap=True, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Text("Preview of the top of a report:", size=11, color=C("#748198")),
                ft.Container(content=preview, bgcolor="#FFFFFF", padding=16, border_radius=12,
                             border=border_all(1, C("#E7ECF4")), alignment=center_alignment()),
            ], spacing=12), padding=20),
            card(ft.Column([
                ft.Text("Academic settings", size=15, weight=ft.FontWeight.BOLD, color=C("#18243A")),
                ft.Row([passing_tf,
                        ft.Text("The passing mark used for grades and reports. Courses are managed on the "
                                "Courses page.", size=11, color=C("#748198"), expand=True)],
                       spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=12), padding=20),
        ], spacing=14, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        shell("School settings", "Admin workspace", body, "school_settings")

    def courses_view():
        """Admin page: add courses and set them active / inactive."""
        new_course = text_field("New course code", width=300, hint="e.g. BSN")
        list_holder = ft.Column(spacing=8)

        def usage(code):
            sections = sum(1 for s in read_rows("sections") if section_course(s["name"]) == code)
            subjects = sum(1 for s in read_rows("subjects") if code in subject_courses(s))
            classes = sum(1 for c in read_rows("classes") if section_course(c.get("name")) == code)
            return sections, subjects, classes

        def render(push=True):
            items = []
            inactive = get_inactive_courses()
            for code in get_courses():
                sections, subjects, classes = usage(code)
                active = code not in inactive
                items.append(ft.Container(
                    content=ft.Row([
                        ft.Column([ft.Text(code, weight=ft.FontWeight.BOLD, size=13),
                                   ft.Text(f"{sections} section(s) • {subjects} subject(s) • {classes} class(es)",
                                           size=11, color=C("#748198"))], spacing=3, expand=True),
                        ft.Container(
                            content=ft.Text("Active" if active else "Inactive", size=11, weight=ft.FontWeight.BOLD,
                                            color=C("#0D9488") if active else C("#B42318")),
                            bgcolor=C("#E8F8F4") if active else C("#FEE4E2"), padding=pad_sym(10, 5),
                            border_radius=10),
                        ft.TextButton("Set inactive" if active else "Set active",
                                      on_click=lambda e, c=code: toggle(c)),
                    ]),
                    padding=12, border=border_all(1, C("#E7ECF4")), border_radius=12, bgcolor=C("#FFFFFF")))
            list_holder.controls = items
            if push:
                page.update()

        def add(_=None):
            code = (new_course.value or "").strip().upper()
            if not code:
                toast("Enter a course code.", True)
                return
            if not re.fullmatch(r"[A-Z0-9]+", code):
                toast("Course codes are one word with letters and numbers only, for example BSIT.", True)
                return
            courses = list(get_courses())
            if code in courses:
                toast("That course already exists.", True)
                return

            def do():
                set_setting("courses", ",".join(courses + [code]))
                log_event("account", "Course added", code)
                new_course.value = ""
                render()
                toast("Course added.")
            ask_confirm("Add course", f"Add course \"{code}\"?", do)

        def toggle(code):
            inactive = list(get_inactive_courses())
            active = code not in inactive
            if active and len(get_active_courses()) <= 1:
                toast("The school needs at least one active course.", True)
                return
            sections, subjects, classes = usage(code)
            note = (f" It is used by {sections} section(s), {subjects} subject(s) and {classes} class(es); "
                    "those are kept." if sections or subjects or classes else "")

            def do():
                new_list = inactive + [code] if active else [c for c in inactive if c != code]
                set_setting("inactive_courses", ",".join(new_list))
                log_event("account", "Course set inactive" if active else "Course set active", code)
                render()
                toast(f"{code} is now {'inactive' if active else 'active'}.")
            if active:
                ask_confirm("Set inactive", f"Set course \"{code}\" to inactive? It will no longer be offered "
                                            f"when adding subjects or filtering.{note}", do)
            else:
                do()

        new_course.on_submit = add
        render(push=False)
        body = ft.Column([
            section_title("Courses", "The courses / programs the school offers. Section names must start with "
                                     "the course code, e.g. \"BSIT 1A\"."),
            card(ft.Row([new_course, button("Add course", add, ft.Icons.ADD, True)], wrap=True, spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=18),
            card(list_holder, padding=18),
        ], spacing=14, scroll=ft.ScrollMode.AUTO)
        shell("Courses", "Admin workspace", body, "courses")

    def admin_manage_view(table):
        """School years, sections and subjects (add / edit / active-inactive)."""
        is_year = table == "school_years"
        has_active = table in ("school_years", "sections", "subjects")
        singular = {"school_years": "school year", "sections": "section", "subjects": "subject"}[table]
        title = {"school_years": "School years", "sections": "Class sections", "subjects": "Class subjects"}[table]
        example = {"school_years": "e.g. 2026-2027", "sections": "e.g. BSIT 2A", "subjects": "e.g. Programming 1"}[table]
        class_field = {"school_years": "school_year", "sections": "name", "subjects": "subject"}[table]
        is_subject = table == "subjects"
        new_name = text_field("School year" if is_year else f"New {singular} name", width=300, hint=example)

        def course_picker(initial, on_change=None):
            """Drop-down to choose one course (or All courses). Returns (control, get_selected)."""
            start_value = initial[0] if len(initial) == 1 else None
            dd = ft.Dropdown(label="Course", width=200, value=start_value, border_radius=12, filled=True,
                             bgcolor=C("#FFFFFF"),
                             options=[ft.dropdown.Option(c) for c in get_active_courses()] +
                                     [ft.dropdown.Option(ALL_COURSES, "All courses")])
            if on_change:
                dd.on_change = lambda e: on_change()
            return dd, (lambda: [dd.value] if dd.value else [])

        add_picker, add_selected = None, (lambda: [])
        if is_subject:
            new_name.disabled = True
            new_name.hint_text = "Choose a course first"

            def on_courses():
                ok = bool(add_selected())
                new_name.disabled = not ok
                new_name.hint_text = example if ok else "Choose a course first"
                page.update()
            add_picker, add_selected = course_picker([], on_courses)
        list_holder = ft.Column(spacing=8)

        def used_in(row):
            return sum(1 for c in read_rows("classes") if (c.get(class_field) or "") == row["name"])

        def duplicate(name, ignore_id=None):
            return any(r["name"].casefold() == name.casefold() and r["id"] != ignore_id
                       for r in read_rows(table))

        def valid_year(y):
            m = re.fullmatch(r"(\d{4})-(\d{4})", y)
            return bool(m) and int(m.group(2)) == int(m.group(1)) + 1

        def valid_section(n):
            """Only the format 'BSIT 1A' (course letters, one space, year number, section letter)."""
            return re.fullmatch(r"[A-Z]+ \d+[A-Z]+", n) is not None

        SECTION_FORMAT_MSG = "Use the section format like BSIT 1A (course, a space, year and section letter). No dashes."

        def render(push=True):
            if is_subject:
                rows = sorted(read_rows(table), key=lambda r: (course_label(r).casefold(), r["name"].casefold()))
            else:
                rows = sorted(read_rows(table), key=lambda r: r["name"].casefold(), reverse=is_year)
            if not rows:
                list_holder.controls = [ft.Text(f"No {singular}s yet. Add the first one above.",
                                                size=12, color=C("#748198"))]
            else:
                items = []
                for r in rows:
                    active = r.get("active") != "0"
                    info = [ft.Text(r["name"], weight=ft.FontWeight.BOLD, size=13),
                            ft.Text((f"{course_label(r)} • " if is_subject else "")
                                    + f"Used in {used_in(r)} class(es)", size=11, color=C("#748198"))]
                    actions = [ft.TextButton("Rename" if is_subject else "Edit", on_click=lambda e, row=r: rename(row))]
                    if has_active:
                        actions.append(ft.TextButton("Set inactive" if active else "Set active",
                                                     on_click=lambda e, row=r: toggle(row)))
                    else:
                        actions.append(ft.TextButton("Delete", on_click=lambda e, row=r: delete(row)))
                    badge = []
                    if has_active:
                        badge = [ft.Container(
                            content=ft.Text("Active" if active else "Inactive", size=11, weight=ft.FontWeight.BOLD,
                                            color=C("#0D9488") if active else C("#B42318")),
                            bgcolor=C("#E8F8F4") if active else C("#FEE4E2"), padding=pad_sym(10, 5), border_radius=10)]
                    items.append(ft.Container(
                        content=ft.Row([ft.Column(info, spacing=3, expand=True)] + badge + actions),
                        padding=12, border=border_all(1, C("#E7ECF4")), border_radius=12, bgcolor=C("#FFFFFF")))
                list_holder.controls = items
            if push:
                page.update()

        def add(_=None):
            chosen_courses = add_selected()
            if is_subject and not chosen_courses:
                toast("Choose a course (or All courses) first.", True)
                return
            n = (new_name.value or "").strip()
            if not n:
                toast(f"Enter a {singular} name.", True)
                return
            if is_year and not valid_year(n):
                toast("Enter the school year like 2026-2027 (two consecutive years).", True)
                return
            if table == "sections":
                n = " ".join(n.upper().split())
                if not valid_section(n):
                    toast(SECTION_FORMAT_MSG, True)
                    return
            if duplicate(n):
                toast(f"That {singular} already exists.", True)
                return

            def do():
                row = {"id": next_id(table), "name": n, "created_at": timestamp()}
                if has_active:
                    row["active"] = "1"
                if is_subject:
                    row["course"] = ",".join(chosen_courses)
                add_row(table, row)
                log_event("class", f"{singular.title()} added", n)
                new_name.value = ""
                render()
                toast(f"{singular.title()} added.")
            ask_confirm(f"Add {singular}",
                        f"Add {singular} \"{n}\"" + (f" for {'All courses' if ALL_COURSES in chosen_courses else ', '.join(chosen_courses)}?"
                                                      if is_subject else "?"), do)

        def toggle(row):
            active = row.get("active") != "0"

            def do():
                update_row(table, row["id"], {"active": "0" if active else "1"})
                log_event("class", f"{singular.title()} set {'inactive' if active else 'active'}", row["name"])
                render()
                toast(f"{singular.title()} set to {'inactive' if active else 'active'}.")
            ask_confirm("Set inactive" if active else "Set active",
                        (f"Set \"{row['name']}\" to inactive? Teachers will no longer be able to create classes "
                         f"with this {singular}. Existing classes are not affected.") if active else
                        f"Set \"{row['name']}\" to active? Teachers can use it again.", do)

        def rename(row):
            field = text_field(f"{singular.title()} name", width=360, value=row["name"])
            edit_picker, edit_selected = course_picker(subject_courses(row)) if is_subject else (None, (lambda: []))
            dlg = None

            def save(_):
                keep_old = is_subject and not edit_selected() and bool(subject_courses(row))
                if is_subject and not edit_selected() and not keep_old:
                    toast("Choose a course (or All courses).", True)
                    return
                n = (field.value or "").strip()
                if not n:
                    toast(f"Enter a {singular} name.", True)
                    return
                if is_year and not valid_year(n):
                    toast("Enter the school year like 2026-2027 (two consecutive years).", True)
                    return
                if table == "sections":
                    n = " ".join(n.upper().split())
                    if not valid_section(n):
                        toast(SECTION_FORMAT_MSG, True)
                        return
                if duplicate(n, ignore_id=row["id"]):
                    toast(f"That {singular} already exists.", True)
                    return

                def do():
                    old = row["name"]
                    update_row(table, row["id"], {"name": n})
                    if is_subject:
                        update_row(table, row["id"], {"course": ",".join(edit_selected() or subject_courses(row))})
                    for c in read_rows("classes"):
                        if (c.get(class_field) or "") == old:
                            update_row("classes", c["id"], {class_field: n})
                    log_event("class", f"{singular.title()} edited", f"{old} -> {n}")
                    close_dialog(dlg)
                    render()
                    toast(f"{singular.title()} updated.")
                ask_confirm(f"Save {singular}", f"Save changes to \"{row['name']}\"?", do)

            dlg = ft.AlertDialog(
                modal=True, title=ft.Text(f"Edit {singular}"),
                content=ft.Column(([edit_picker] if is_subject else []) + [field], tight=True, spacing=12, width=420),
                actions=[ft.TextButton("Cancel", on_click=lambda e: close_dialog(dlg)),
                         compatible_button("Save", on_click=save)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            open_control(page, dlg)
            page.update()

        def delete(row):
            if used_in(row):
                toast(f"This {singular} is used by existing classes and can't be deleted.", True)
                return

            def do_delete():
                remove_row(table, row["id"])
                log_event("class", f"{singular.title()} deleted", row["name"])
                render()
                toast(f"{singular.title()} deleted.")
            ask_confirm(f"Delete {singular}", f"Delete \"{row['name']}\"?", do_delete)

        new_name.on_submit = add
        render(push=False)
        subtitle = {"school_years": "Add the school years teachers can pick when creating a class. "
                                    "Inactive school years are hidden from teachers.",
                    "sections": "Add the class sections. Inactive sections are hidden from teachers.",
                    "subjects": "Choose the course first, then type the subject. Pick All courses for minor subjects every course takes. Teachers only see the active subjects for their section's course."}[table]
        body = ft.Column([
            section_title(title, subtitle),
            card(ft.Row(([add_picker] if is_subject else []) +
                    [new_name, button(f"Add {singular}", add, ft.Icons.ADD, True)], wrap=True, spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
                 padding=18),
            card(list_holder, padding=18),
        ], spacing=14, scroll=ft.ScrollMode.AUTO)
        shell(title, "Admin workspace", body, table)


    welcome_view()


if __name__ == "__main__":
    ft.app(target=main)
