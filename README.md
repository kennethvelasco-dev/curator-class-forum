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
- `/servers/request/` — verified students submit a CoR-backed class server
  request for Admin review
- `/servers/request/<request-id>/cor/` — active staff can inspect a request's
  private CoR; the storage key is never exposed as a public URL
- `/servers/admin/server-requests/` — active staff review pending server
  requests; decisions are submitted to
  `/servers/admin/server-requests/<request-id>/decision/`
- `/servers/`, `/channels/`, `/discussions/`, `/announcements/`, and
  `/moderation/` — mounted app namespaces; other endpoints are not implemented yet
- `/admin/` — Django administration

The server-request route is available to verified users. Other server
workflows, channel, discussion, announcement, and moderation routes are not
implemented yet.

## Database schema

Sprint 1 database entities and cardinality are documented in [docs/database-schema.md](docs/database-schema.md). The document distinguishes implemented account models from future sprint models that are intentionally not yet created.

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
| `PRIVATE_COR_STORAGE_ROOT` | `../private_cor_storage` in development | Private CoR storage path; relative paths resolve against the project root. Production requires an explicit value. |
| `EMAIL_BACKEND` | Django console backend | Local backend prints verification messages to the console |
| `EMAIL_HOST` | Empty | SMTP host when using Django's SMTP backend |
| `EMAIL_PORT` | `587` | SMTP port |
| `EMAIL_HOST_USER` | Empty | SMTP username |
| `EMAIL_HOST_PASSWORD` | Empty | SMTP password; keep private and out of Git |
| `EMAIL_USE_TLS` | `True` | Whether SMTP uses TLS |
| `EMAIL_TIMEOUT` | `10` | Finite SMTP connection timeout in seconds |
| `DEFAULT_FROM_EMAIL` | `Curator <noreply@localhost>` | Sender address for verification messages |
| `DATABASE_ENGINE` | `sqlite` | Database backend; PostgreSQL must be explicitly selected with `postgresql` |
| `POSTGRES_DB` | `curator_forum` | PostgreSQL application database name |
| `POSTGRES_USER` | `curator_dev` | PostgreSQL user |
| `POSTGRES_PASSWORD` | Empty | PostgreSQL password; keep private and out of Git |
| `POSTGRES_HOST` | `127.0.0.1` | PostgreSQL server host |
| `POSTGRES_PORT` | `5432` | PostgreSQL server port |
| `POSTGRES_TEST_DB` | `curator_forum_test` | Separate PostgreSQL test database; must differ from `POSTGRES_DB` |
| `POSTGRES_SSLMODE` | `verify-full` for remote hosts; unset for loopback | Explicit PostgreSQL TLS mode; production remote hosts require `verify-full` |
| `POSTGRES_SSLROOTCERT` | Unset | Optional path to the CA certificate used by psycopg |

SQLite remains the default local database and the basic setup above requires no
PostgreSQL server. To use PostgreSQL, explicitly set
`DATABASE_ENGINE=postgresql` and configure `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT`. Configure
`POSTGRES_TEST_DB` to a different database name; settings reject a collision
before Django starts its test runner. Each test run may create and destroy its
test database, so separate PostgreSQL test runs must not use the same test
database concurrently. When CI jobs share a PostgreSQL service, assign a unique
`POSTGRES_TEST_DB` to every workflow run/job.

Remote PostgreSQL connections default to `sslmode=verify-full`. For a private
or self-managed server, provide the trusted CA certificate path with
`POSTGRES_SSLROOTCERT`; psycopg uses it for certificate validation. Loopback
hosts (`localhost`, `127.0.0.1`, and `::1`) do not require certificate
verification by default. When `DJANGO_DEBUG=False`, remote PostgreSQL requires
full hostname and certificate verification; weaker modes are rejected.

The console email backend is for local development only and prints
verification messages, including token-bearing links, to console output.
When `DJANGO_DEBUG=False`, set `EMAIL_BACKEND` to a non-console backend such as
`django.core.mail.backends.smtp.EmailBackend` and configure its delivery
settings. Startup rejects the console backend in production mode.

CoR documents use a private filesystem storage root that cannot generate
public URLs. In production (`DJANGO_DEBUG=False`), explicitly configure
`PRIVATE_COR_STORAGE_ROOT`; it must point to a persistent directory outside
the repository and every web-server document root, served directory, and
public alias. Do not configure Nginx, Apache, a CDN, or another web server to
serve or alias this directory. Relative paths resolve against the project
root. The default development path is a sibling directory outside the
repository. Built-in path checks cannot discover every external web-server
alias or deployment-specific mapping; production deployment must explicitly
verify that the configured storage root is not publicly served.

The storage backend requests directory mode `0700` and file mode `0600` when
Django creates new directories and files. On Linux/POSIX deployments, the
private root should have permissions equivalent to `0700` and stored files
permissions equivalent to `0600`. These creation modes do not secure a root
directory that already exists; check and secure existing directories during
deployment. The application does not recursively change permissions.

On Windows, apply restrictive Windows ACLs so only the application identity
and explicitly authorized system administrators can access the storage
directory. POSIX permission bits do not enforce Windows ACLs. The application
does not provide complete cross-platform permission or ACL enforcement.

Upload validation accepts `.pdf` files up to 6 MiB and uses pypdf to parse the
PDF structure. Filenames stored by the backend use random UUIDs rather than
the uploaded filename. Structural parsing is not malware detection or a
guarantee that a document is safe to open.

The reusable `apps.servers.storage.delete_cor()` service returns
`ALREADY_ABSENT` only when absence is confirmed. An inaccessible path,
filesystem error, or ambiguous state raises `CorDeletionError`; the exception
is chained for diagnostics while log messages omit the filename and underlying
exception text. The `apps.servers.services.cor_cleanup.attempt_cor_cleanup()`
service applies this behavior to approved/rejected `ServerRequest` and
`JoinRequest` rows. It re-reads current state, clears only the exact key that
was verified absent, and leaves failed cleanup retryable with attempt metadata.
The cleanup attempt is durably reserved as `processing` before storage; fresh
claims block other workers. Claims older than 30 minutes are considered
abandoned and may be recovered on the next cleanup run. The timeout assumes
storage work finishes within that interval; a worker that runs longer may
overlap recovery, though stale completion writes are fenced by the attempt
number and deletion is idempotent. The counter records reservations, not
guaranteed physical deletion calls: a process crash after reservation but
before storage can leave a reservation without a storage call.
Model saves reject replacing or clearing a decided request's CoR key. Direct
`QuerySet.update()`, bulk operations, raw SQL, and shell mutation bypass this
guard and are unsupported for decided-key changes.
Decision handlers should mark cleanup pending with the final decision in their
existing database transaction and invoke the service with `transaction.on_commit`;
no decision handlers are implemented yet.

Retry pending cleanup manually with:

```powershell
python manage.py cleanup_pending_cor_files
python manage.py cleanup_pending_cor_files --limit 100
python manage.py cleanup_pending_cor_files --dry-run
```

`--limit` applies globally across both request models and the command selects
them fairly in deterministic round-robin order. Dry-run prints aggregate
eligible counts and explicitly does not check individual file existence. A
nonzero command result means a processed storage, retrieval, or persistence
failure requires attention; output does not claim pending state unless that
state was successfully confirmed.
Recurring retries are not automatic; run the command operationally or schedule
it externally and monitor its exit status. Legacy approved/rejected rows are
backfilled by the cleanup lifecycle migration: rows with a file key become
pending and rows without one become complete without accessing storage.

Registration links expire after 24 hours and can be used once. Opening a link
does not create an account; the email owner sets the password and records
consent on the linked form. Expired requests can be restarted without leaving
an email address permanently reserved. User passwords are stored using
Django's password hashing. Login sessions last 14 days.
The application redacts verification tokens from its configured Django
console and admin-email logs. Django development-server access logs and
external infrastructure logs may still record the original request URL;
configure those logs separately if token-bearing paths must be excluded. The
initial verification response uses a no-referrer policy, and subsequent forms
use tokenless URLs.

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
