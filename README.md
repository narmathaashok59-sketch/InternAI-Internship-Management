# InternAI — Internship Management System

A beginner-friendly Flask + SQLite application with role-based login, task assignment, intern submissions, mentor review and email reminders **two calendar days before the review date**.

## Features

- Roles: Admin, Mentor, Intern
- Admin can create user accounts
- Admin and mentors can assign tasks to interns
- Assignment notification email
- Intern can save progress / submit work link or notes
- Admin / mentor can approve a task or request changes with feedback
- Review reminder job checks every 30 minutes
- `reminder_sent` is stored in SQLite to prevent repeat reminders after successful sends
- Search tasks in the dashboard

## Requirements

- Python 3.10 or newer
- Gmail account for outbound email (optional while developing)

## Setup on Windows

Open Command Prompt or VS Code terminal in this folder.

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

### Start the website

```bat
python app.py
```

Open `http://127.0.0.1:5000`.

First-run demo admin:
- Email: `admin@internai.local`
- Password: `Admin@12345`

**Important:** This is only a local demo account. Create a new admin account, then change/remove the demo credentials before using real student data. Never deploy with the default secret key.

## Configure Gmail SMTP

1. Turn on 2-Step Verification for the Gmail account that will send reminders.
2. Create a Google App Password in your Google Account security settings (if App Passwords is available).
3. In Windows Command Prompt, set the environment variables for the current terminal session:

```bat
set MAIL_USERNAME=yourgmail@gmail.com
set MAIL_APP_PASSWORD=your16characterapppassword
set MAIL_FROM=yourgmail@gmail.com
set SECRET_KEY=replace-this-with-a-long-random-secret
python app.py
```

Use the Google **App Password**, not your normal Gmail password. Keep it private; do not put it in source code or upload it to GitHub. These `set` values last only for the current terminal window. For a persistent setup, configure environment variables in your OS or hosting service.

Email is attempted when a task is assigned and when a mentor submits a review. If email is not configured, the task still saves and the website displays a warning.

## Reminder behavior

- Set a review date when assigning a task.
- The scheduler searches for tasks whose review date is exactly two days from today.
- It checks every 30 minutes.
- After an email sends successfully, it marks `reminder_sent = 1` so the same task reminder is not sent again.
- If email fails, the reminder remains eligible for retry on a later scheduler run, until the review date passes.
- The scheduler uses the computer/server's local date; set the server timezone correctly (India: Asia/Kolkata).

### Important deployment note

The included scheduler runs inside the Flask process. It is suitable for local development or a single-process internal demo. Keep the app/server running for scheduled reminders to run. For production, run the reminder scheduler as a **separate single worker/service** and deploy the web app with a production WSGI server. Do not start multiple copies of the scheduler across multiple web workers, because that can cause duplicate email attempts. Consider adding retry logs and an admin email log page before business-critical use.

## Project structure

```text
InternAI/
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── internai.db              # created automatically on first run
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── dashboard.html
│   ├── user_form.html
│   └── task_form.html
└── static/
    ├── style.css
    └── app.js
```

## Suggested test

1. Log in with demo admin.
2. Use **Add User** to create an intern and mentor with email addresses you can access.
3. Assign a task with a review date at least two days in the future.
4. Log out and log in as the intern; update progress and submit work.
5. Log in as the mentor/admin and review the submission.
6. For a safe reminder test, create a test task whose review date is two days from the current server date, set Gmail SMTP variables, and wait for the scheduler (up to 30 minutes). Do not test using real intern data first.

## Troubleshooting

- `py` not recognized: try `python --version`, then use `python` instead of `py`.
- Email fails: confirm Gmail App Password, sender address and internet connection.
- No reminder: confirm server is still running, review date is exactly two days away, task is not approved, and email settings are correct.
- Login issue: the SQLite database is `internai.db` in the project folder. Removing it resets all local data and recreates the demo admin; **only do this if you are happy to lose all saved demo records**.

## Before real office use

This starter is not yet a hardened production system. Add CSRF protection, password reset/change flow, audit logs, stronger account management, HTTPS, backups, privacy notices and a production deployment configuration before storing real employee/student data.
