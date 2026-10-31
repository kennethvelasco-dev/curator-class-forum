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

Open <http://127.0.0.1:8000/> to view the starter page. Create an admin account
with `python manage.py createsuperuser`; the admin is available at
<http://127.0.0.1:8000/admin/>.

Run the test suite with `python manage.py test`.

## Routes

- `/` — Curator homepage (`core:home`)
- `/accounts/register/` — account registration with institutional email and
  required privacy consent
- `/servers/`, `/channels/`, `/discussions/`, `/announcements/`, and
  `/moderation/` — mounted app namespaces; endpoints are not implemented yet
- `/admin/` — Django administration

These prefixes are registered for future feature routes; requests to them return
404 until endpoints are added.

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

## Project layout

- `config/` — Django settings and entry points
- `apps/` — feature apps
- `core/` — shared views and project-level functionality
- `templates/` — shared and app templates
- `static/` — CSS, JavaScript, and images

## Development status

The project foundation is in place: the homepage renders through the shared
base template, feature app URL namespaces are mounted, and a custom user model
with its initial migration is defined. Authentication pages and the forum,
class scheduling, and moderation features remain future work.
