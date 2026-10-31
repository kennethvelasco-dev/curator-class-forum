# Curator — Class Forum

Curator is a Django starter project for a class forum and academic scheduling
platform. The project is organized into focused apps for accounts, servers,
channels, discussions, announcements, and moderation.

## Technology stack

- Python and Django
- Django Templates, HTML, CSS, and JavaScript
- SQLite for local development
- Environment-based configuration with `python-dotenv`
- Philippine local time (`Asia/Manila`)

## Requirements

- Python 3.10+
- pip

## Local setup

From the repository root, create and activate a virtual environment, then
install the project dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/> to view Curator. Local verification emails are
printed to the runserver console by the default email backend. Create a
platform administrator with `python manage.py createsuperuser`; the admin is
available at <http://127.0.0.1:8000/admin/>.

Run the test suite with `python manage.py test`.

## Routes

- `/` — Curator homepage (`core:home`)
- `/accounts/register/` — requests an institutional email verification link;
  no account password is stored before email ownership is proven
- `/accounts/verify-registration/<registration-id>/<token>/` — completes
  registration with a password and required privacy consent; account creation
  requires a POST, not merely opening the emailed link
- `/accounts/verify/<user-id>/<token>/` — legacy account verification endpoint
- `/accounts/login/` and `/accounts/logout/` — email sign-in and POST-only
  sign-out
- `/accounts/dashboard/` — protected account dashboard for verified users
- `/servers/`, `/channels/`, `/discussions/`, `/announcements/`, and
  `/moderation/` — mounted app namespaces; endpoints are not implemented yet
- `/admin/` — Django administration

Server, channel, discussion, announcement, and moderation routes are not
implemented yet.

## Configuration

Settings are loaded from environment variables, with values in a local `.env`
file taking precedence over defaults. Set `DJANGO_SECRET_KEY` to a unique,
private value and set `DJANGO_DEBUG=False` outside local development.

| Variable | Default | Description |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Local development-only key | Django secret key; required when debug is disabled |
| `DJANGO_DEBUG` | `True` | Enables Django debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed host names |
| `INSTITUTIONAL_EMAIL_DOMAIN` | `iskolarngbayan.pup.edu.ph` | Institutional email domain allowed for account registration |
| `EMAIL_BACKEND` | Django console backend | Local backend prints verification messages to the console |
| `EMAIL_HOST` | Empty | SMTP host when using Django's SMTP backend |
| `EMAIL_PORT` | `587` | SMTP port |
| `EMAIL_HOST_USER` | Empty | SMTP username |
| `EMAIL_HOST_PASSWORD` | Empty | SMTP password; keep private and out of Git |
| `EMAIL_USE_TLS` | `True` | Whether SMTP uses TLS |
| `EMAIL_TIMEOUT` | `10` | Finite SMTP connection timeout in seconds |
| `DEFAULT_FROM_EMAIL` | `Curator <noreply@localhost>` | Sender address for verification messages |

The console email backend is for local development only and prints
verification messages, including token-bearing links, to console output.
When `DJANGO_DEBUG=False`, set `EMAIL_BACKEND` to a non-console backend such as
`django.core.mail.backends.smtp.EmailBackend` and configure its delivery
settings. Startup rejects the console backend in production mode.

Registration links expire after 24 hours and can be used once. Opening a link
does not create an account; the email owner sets the password and records
consent on the linked form. Expired requests can be restarted without leaving
an email address permanently reserved. User passwords are stored using
Django's password hashing. Login sessions last 14 days.
When `DJANGO_DEBUG=False`, Django redirects HTTP to HTTPS and enables secure
session/CSRF cookies and HSTS; configure the deployment proxy and allowed hosts
to preserve the original HTTPS scheme correctly.

The account authorization foundation separates verified authentication from
future resource authorization. Django staff/superuser access is for platform
administration. Future President/Officer access must be checked against each
server membership, not stored as a global User role.

## Project layout

- `config/` — Django settings and entry points
- `apps/` — feature apps
- `core/` — shared views and project-level functionality
- `templates/` — shared and app templates
- `static/` — CSS, JavaScript, and images

## Development status

Sprint 1 account functionality includes institutional registration, consent
recording, email verification, email/password login, logout, a protected
dashboard, and Django admin support for the custom email-based User model.
Server creation, CoR uploads, discussions, scheduling, moderation, password
reset, two-factor authentication, and social login remain out of scope.
