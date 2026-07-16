# Geekonomy HRMS

Internal Human Resource Management System for **Geekonomy**, customized from the open-source [Horilla](https://www.horilla.com/) HRMS.

**Live:** [people.geekonomy.in](https://people.geekonomy.in)

---

## About

Geekonomy HRMS helps the team manage day-to-day HR operations in one place — employees, attendance, leave, payroll, hiring, and more.

This project is based on **Horilla** (LGPL) by [Cybrosys Technologies](https://www.cybrosys.com/), customized and extended for Geekonomy’s workflows, branding, and integrations.

---

## Modules

| Module | Description |
|--------|-------------|
| **Employee** | Employee profiles, work info, org structure |
| **Attendance** | Punch / attendance requests, approvals, late notifications |
| **Leave** | Leave requests, balances, Comp Off, approvals |
| **Payroll** | Payslips, reimbursements, **expense tracking** |
| **Recruitment** | Jobs, candidates, interviews |
| **Onboarding** | New joiner setup and tasks |
| **Asset** | Company asset allocation |
| **Offboarding** | Exit process |
| **Reports** | HR / attendance / leave reporting |
| **Dashboard** | Overview with Slack online/offline presence |

---

## Geekonomy customizations

- Geekonomy branding (login, emails, logos)
- Expense tracking (list, filters, grand total, duplicate, Excel export)
- Comp Off leave rules and flows
- Attendance / leave email notifications
- Slack presence on the dashboard
- **Resend** for outbound email (`RESEND_API_KEY` + `DEFAULT_FROM_EMAIL`)
- Production Docker + Nginx setup (`docker-compose.prod.yaml`)

---

## Tech stack

- **Backend:** Python, Django 4.2
- **Database:** PostgreSQL
- **Email:** Resend API
- **Deploy:** Docker, Gunicorn, Nginx
- **Integrations:** Slack Bot API

---

## Local development

### Prerequisites

- Python 3.10+
- PostgreSQL
- Git

### Setup

```bash
git clone <your-repo-url>
cd horilla

python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### Environment

Copy and edit `.env` (see `.env.dist` if present):

```env
DEBUG=True
TIME_ZONE=Asia/Kolkata
SECRET_KEY=change-me
ALLOWED_HOSTS=*
CSRF_TRUSTED_ORIGINS=http://localhost:8000

DB_ENGINE=django.db.backends.postgresql
DB_NAME=horilla
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

# Email (Resend) — From address must be on a verified Resend domain
RESEND_API_KEY=re_xxxxxxxx
DEFAULT_FROM_EMAIL=Geekonomy HRMS <hr@thegeekonomy.com>
HR_EMAIL=hr@thegeekonomy.com

# Optional
SLACK_BOT_TOKEN=xoxb-xxxxxxxx
```

When `RESEND_API_KEY` is set, all app emails (leave, attendance, forgot password, etc.) are sent via **Resend**. SMTP / Mail Server host settings are ignored for sending; **From** always uses `DEFAULT_FROM_EMAIL`.

### Database & run

```bash
python manage.py migrate
python manage.py compilemessages
python manage.py runserver 0.0.0.0:8000
```

Open: [http://localhost:8000](http://localhost:8000)

---

## Production (Docker)

Production config: `docker-compose.prod.yaml`

Services:

- `horilla-db` — PostgreSQL
- `horilla-app` — Django / Gunicorn
- `horilla-nginx` — reverse proxy (port **8880**)

### Deploy / update

On the server:

```bash
cd /path/to/horilla
git pull
docker-compose -f docker-compose.prod.yaml up --build -d
```

Ensure production environment includes at least:

- `RESEND_API_KEY`
- `DEFAULT_FROM_EMAIL`
- `DB_*` / `DATABASE_URL`
- `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS`
- `SECRET_KEY`
- `SLACK_BOT_TOKEN` (if Slack presence is used)

`requirements.txt` must be **UTF-8** (not UTF-16), or the Docker `pip install` step will fail.

---

## Email notes

1. Verify domain **thegeekonomy.com** in the [Resend](https://resend.com) dashboard.
2. Use a From address on that domain (e.g. `hr@thegeekonomy.com`).
3. Inline logos in emails are embedded as CID attachments so they display even when the app host is private.

---

## Project structure (high level)

```text
horilla/           Django project settings & URLs
employee/          Employees
attendance/        Attendance
leave/             Leave
payroll/           Payroll & expenses
recruitment/       Hiring
onboarding/        Onboarding
asset/             Assets
base/              Core, auth, mail backend (incl. Resend)
static/            Static assets & Geekonomy logos
docker-compose.prod.yaml
Dockerfile
```

---

## Credits & license

- **Product customization:** Geekonomy
- **Upstream platform:** [Horilla](https://www.horilla.com/) — open-source HRMS by [Cybrosys Technologies](https://www.cybrosys.com/)
- **License:** LGPL (inherited from Horilla) — see project license terms for redistribution obligations

---

## Support (internal)

For Geekonomy team issues, contact the internal IT / HRMS maintainers.  
Upstream Horilla docs and community: [horilla.com](https://www.horilla.com/)


