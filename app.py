import os
import sqlite3
import smtplib
from email.message import EmailMessage
from datetime import datetime, date, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "internai.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-this-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','mentor','intern')),
            department TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            intern_id INTEGER NOT NULL,
            mentor_id INTEGER,
            assigned_by INTEGER NOT NULL,
            deadline TEXT,
            review_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Assigned'
                CHECK(status IN ('Assigned','In Progress','Submitted','Approved','Needs Changes')),
            submission TEXT DEFAULT '',
            mentor_feedback TEXT DEFAULT '',
            reminder_sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(intern_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(mentor_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(assigned_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_review_reminder
            ON tasks(review_date, reminder_sent, status);
        """)

        # First-run demo admin. Change this password immediately after first login.
        row = db.execute("SELECT id FROM users WHERE email = ?", ("admin@internai.local",)).fetchone()
        if not row:
            db.execute(
                "INSERT INTO users (full_name,email,password_hash,role,department) VALUES (?,?,?,?,?)",
                ("System Admin", "admin@internai.local",
                 generate_password_hash("Admin@12345"), "admin", "Administration")
            )


def send_email(to_email, subject, body):
    """Returns (success, message). Gmail SMTP uses an App Password, not your Gmail login password."""
    username = os.environ.get("MAIL_USERNAME", "").strip()
    app_password = os.environ.get("MAIL_APP_PASSWORD", "").replace(" ", "").strip()
    sender = os.environ.get("MAIL_FROM", username).strip()

    if not username or not app_password or not sender:
        return False, "Email is not configured. Set MAIL_USERNAME, MAIL_APP_PASSWORD and MAIL_FROM."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, app_password)
            smtp.send_message(msg)
        return True, "Email sent."
    except Exception as exc:
        app.logger.exception("Email send failed")
        return False, f"Email failed: {exc}"


def reminder_job():
    """Runs regularly. The database flag prevents duplicate reminders after restarts."""
    today = date.today()
    reminder_day = today + timedelta(days=2)
    with get_db() as db:
        tasks = db.execute("""
            SELECT t.id, t.title, t.description, t.review_date, t.deadline, t.intern_id,
                   u.full_name, u.email
            FROM tasks t
            JOIN users u ON u.id = t.intern_id
            WHERE t.review_date = ?
              AND t.reminder_sent = 0
              AND t.status NOT IN ('Approved')
        """, (reminder_day.isoformat(),)).fetchall()

        for task in tasks:
            subject = f"InternAI reminder: review in 2 days — {task['title']}"
            body = f"""Hi {task['full_name']},

This is an automatic reminder that your task review is scheduled in 2 days.

Task: {task['title']}
Description: {task['description']}
Deadline: {task['deadline'] or 'Not specified'}
Review date: {task['review_date']}

Please prepare your work and submit it in InternAI before the review.

Regards,
InternAI Internship Management System
"""
            ok, message = send_email(task["email"], subject, body)
            if ok:
                db.execute("UPDATE tasks SET reminder_sent = 1 WHERE id = ?", (task["id"],))
            else:
                app.logger.warning("Reminder for task %s was not sent: %s", task["id"], message)


def start_scheduler():
    # Avoid duplicate schedulers when Flask's debug reloader starts twice.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        scheduler = BackgroundScheduler(daemon=True, timezone="Asia/Kolkata")
        scheduler.add_job(reminder_job, "interval", minutes=30, id="review_reminders",
                          replace_existing=True, max_instances=1)
        scheduler.start()
        app.extensions["internai_scheduler"] = scheduler


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.context_processor
def inject_now():
    return {"current_year": date.today().year}


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["full_name"] = user["full_name"]
            session["email"] = user["email"]
            session["role"] = user["role"]
            flash(f"Welcome, {user['full_name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    role = session["role"]
    uid = session["user_id"]
    with get_db() as db:
        if role in ("admin", "mentor"):
            users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
            tasks = db.execute("""
                SELECT t.*, i.full_name AS intern_name, i.email AS intern_email,
                       m.full_name AS mentor_name
                FROM tasks t
                JOIN users i ON i.id=t.intern_id
                LEFT JOIN users m ON m.id=t.mentor_id
                ORDER BY t.review_date ASC, t.id DESC
            """).fetchall()
            stats = {
                "interns": db.execute("SELECT COUNT(*) n FROM users WHERE role='intern'").fetchone()["n"],
                "tasks": db.execute("SELECT COUNT(*) n FROM tasks").fetchone()["n"],
                "pending": db.execute("SELECT COUNT(*) n FROM tasks WHERE status IN ('Assigned','In Progress','Submitted','Needs Changes')").fetchone()["n"],
                "completed": db.execute("SELECT COUNT(*) n FROM tasks WHERE status='Approved'").fetchone()["n"],
            }
        else:
            users = []
            tasks = db.execute("""
                SELECT t.*, m.full_name AS mentor_name
                FROM tasks t LEFT JOIN users m ON m.id=t.mentor_id
                WHERE t.intern_id=?
                ORDER BY t.review_date ASC, t.id DESC
            """, (uid,)).fetchall()
            stats = {
                "interns": 0,
                "tasks": len(tasks),
                "pending": sum(1 for t in tasks if t["status"] != "Approved"),
                "completed": sum(1 for t in tasks if t["status"] == "Approved"),
            }
    return render_template("dashboard.html", users=users, tasks=tasks, stats=stats, role=role)


@app.route("/users/new", methods=["GET", "POST"])
@roles_required("admin")
def create_user():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        department = request.form.get("department", "").strip()
        if not name or not email or len(password) < 8 or role not in ("admin", "mentor", "intern"):
            flash("Enter all required fields. Password must be at least 8 characters.", "danger")
            return redirect(url_for("create_user"))
        try:
            with get_db() as db:
                db.execute("""
                    INSERT INTO users (full_name,email,password_hash,role,department)
                    VALUES (?,?,?,?,?)
                """, (name, email, generate_password_hash(password), role, department))
            flash(f"User {name} created successfully.", "success")
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            flash("That email address is already registered.", "danger")
    return render_template("user_form.html")


@app.route("/tasks/new", methods=["GET", "POST"])
@roles_required("admin", "mentor")
def create_task():
    with get_db() as db:
        interns = db.execute("SELECT id, full_name, email FROM users WHERE role='intern' ORDER BY full_name").fetchall()
        mentors = db.execute("SELECT id, full_name FROM users WHERE role='mentor' ORDER BY full_name").fetchall()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        intern_id = request.form.get("intern_id", type=int)
        mentor_id = request.form.get("mentor_id", type=int) or (session["user_id"] if session["role"] == "mentor" else None)
        deadline = request.form.get("deadline", "").strip() or None
        review_date = request.form.get("review_date", "").strip()
        try:
            review_dt = date.fromisoformat(review_date)
            deadline_dt = date.fromisoformat(deadline) if deadline else None
        except ValueError:
            flash("Please enter valid dates.", "danger")
            return render_template("task_form.html", interns=interns, mentors=mentors)
        if not title or not description or not intern_id or review_dt < date.today():
            flash("Enter task details and a review date that is today or in the future.", "danger")
            return render_template("task_form.html", interns=interns, mentors=mentors)
        if deadline_dt and deadline_dt > review_dt:
            flash("Deadline cannot be after the review date.", "danger")
            return render_template("task_form.html", interns=interns, mentors=mentors)
        with get_db() as db:
            intern = db.execute("SELECT id FROM users WHERE id=? AND role='intern'", (intern_id,)).fetchone()
            if not intern:
                flash("Please select a valid intern.", "danger")
                return render_template("task_form.html", interns=interns, mentors=mentors)
            cur = db.execute("""
                INSERT INTO tasks (title,description,intern_id,mentor_id,assigned_by,deadline,review_date)
                VALUES (?,?,?,?,?,?,?)
            """, (title, description, intern_id, mentor_id, session["user_id"], deadline, review_date))
            task_id = cur.lastrowid
            intern_info = db.execute("SELECT full_name,email FROM users WHERE id=?", (intern_id,)).fetchone()
        subject = f"New internship task assigned: {title}"
        body = f"""Hi {intern_info['full_name']},

A new task has been assigned to you.

Task: {title}
Description: {description}
Deadline: {deadline or 'Not specified'}
Review date: {review_date}

Please log in to InternAI to track and submit your progress.

Regards,
InternAI Internship Management System
"""
        ok, message = send_email(intern_info["email"], subject, body)
        if ok:
            flash("Task assigned. Email notification sent.", "success")
        else:
            flash(f"Task saved, but email was not sent. {message}", "warning")
        return redirect(url_for("dashboard"))
    return render_template("task_form.html", interns=interns, mentors=mentors)


@app.route("/tasks/<int:task_id>/submit", methods=["POST"])
@roles_required("intern")
def submit_task(task_id):
    submission = request.form.get("submission", "").strip()
    status = request.form.get("status", "Submitted")
    if status not in ("In Progress", "Submitted"):
        status = "Submitted"
    with get_db() as db:
        task = db.execute("SELECT * FROM tasks WHERE id=? AND intern_id=?",
                          (task_id, session["user_id"])).fetchone()
        if not task:
            abort(404)
        if task["status"] == "Approved":
            flash("This task is already approved.", "info")
        else:
            db.execute("UPDATE tasks SET submission=?, status=? WHERE id=?",
                       (submission, status, task_id))
            flash("Task progress updated.", "success")
    return redirect(url_for("dashboard"))


@app.route("/tasks/<int:task_id>/review", methods=["POST"])
@roles_required("admin", "mentor")
def review_task(task_id):
    status = request.form.get("status", "")
    feedback = request.form.get("mentor_feedback", "").strip()
    if status not in ("Approved", "Needs Changes", "In Progress"):
        flash("Invalid review status.", "danger")
        return redirect(url_for("dashboard"))
    with get_db() as db:
        task = db.execute("""
            SELECT t.*, u.email, u.full_name FROM tasks t
            JOIN users u ON u.id=t.intern_id WHERE t.id=?
        """, (task_id,)).fetchone()
        if not task:
            abort(404)
        db.execute("UPDATE tasks SET status=?, mentor_feedback=? WHERE id=?",
                   (status, feedback, task_id))
    subject = f"Task review update: {task['title']}"
    body = f"""Hi {task['full_name']},

Your task has been reviewed.

Task: {task['title']}
Review status: {status}
Mentor feedback: {feedback or 'No additional feedback'}

Please log in to InternAI for details.

Regards,
InternAI Internship Management System
"""
    ok, _ = send_email(task["email"], subject, body)
    flash("Review saved." + (" Email sent to intern." if ok else " Email notification could not be sent; check SMTP settings."), "success")
    return redirect(url_for("dashboard"))


@app.route("/health")
def health():
    return {"status": "ok", "service": "InternAI"}


with app.app_context():
    init_db()

# Scheduler runs in the same process as Flask. For production, run a separate scheduler worker
# or configure a single web worker to avoid multiple schedulers.
start_scheduler()

if __name__ == "__main__":
    app.run(debug=False)
