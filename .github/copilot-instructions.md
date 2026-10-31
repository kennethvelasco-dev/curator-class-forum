# Curator — GitHub Copilot Instructions

The authoritative requirements document is `docs/FSD.pdf`.

## 1. Project Overview

Curator is a university class forum and academic schedule platform developed using Django.

The platform provides:
- Verified class servers.
- Subject-based discussion channels.
- Threaded discussions and replies.
- Anonymous and named posting.
- Class announcements.
- Shared academic calendars.
- Role-based moderation and administration.
- CoR-based student verification.

The approved Functional Specifications Document (FSD) v1.0 is the primary source of truth for all functional requirements.

Do not invent features or change approved requirements without explicit authorization.

## 2. Development Environment

- Framework: Django 5.2
- Language: Python
- Database: SQLite for local development; PostgreSQL/Supabase for production.
- Environment configuration: python-dotenv.
- Frontend: Django Templates, HTML, CSS, and JavaScript.
- Architecture: Django Model–Template–View (MTV), corresponding to the MVC structure required by the project.

Follow the existing repository structure. Do not introduce unnecessary frameworks, dependencies, or architectural patterns.

## 3. Project Development Rules

1. Inspect existing files before modifying them.
2. Reuse existing functionality where possible.
3. Do not duplicate existing models, views, forms, or services.
4. Keep business logic out of templates.
5. Keep views focused on handling requests and responses.
6. Use Django ORM for database operations.
7. Use Django's built-in authentication and password hashing.
8. Validate user input on the server.
9. Use CSRF protection on forms.
10. Keep sensitive configuration in environment variables.
11. Follow consistent naming conventions.
12. Keep the application runnable throughout development.
13. Avoid unnecessary refactoring outside the current task.
14. Prefer simple, maintainable solutions over overengineering.

## 4. FSD Compliance

## Functional Requirements and FSD Authority

The approved **Curator FSD v1.0** is the authoritative source for project requirements.

### Requirements hierarchy

When making implementation decisions, follow this priority:

1. Approved Curator FSD v1.0.
2. Current sprint checklist (`SPRINT_1_FEATURES.md`).
3. Existing project architecture and established implementation decisions.
4. Developer suggestions, provided they do not conflict with the FSD.

Do not invent, remove, or silently modify functional requirements.

If a requirement is unclear, contradictory, or missing, explain the issue and request clarification before implementing a potentially conflicting solution.

### FSD compliance

- Check relevant functional requirement IDs before implementing a feature.
- Preserve the intended behavior described in the FSD.
- Do not implement deferred or out-of-scope features unless explicitly approved.
- Keep implementation traceable to the relevant FR and user story IDs.
- Report which requirements are satisfied, partially implemented, or not implemented.

### Authentication and registration requirements

Follow FR-001 through FR-003:

- Registration must use an institutional email address.
- The allowed institutional email domain must be configurable through environment settings.
- The initial pilot domain is `iskolarngbayan.pup.edu.ph`, unless the team approves a change.
- Email verification must use an emailed verification link.
- Passwords must be at least 8 characters and contain uppercase letters, lowercase letters, and digits.
- Passwords must be securely hashed using Django authentication.
- Registration must display the applicable rules and privacy notice.
- Obtain explicit consent for CoR processing and authorship visibility.
- Record the consent decision and sufficient information to identify the notice version and consent time.
- Do not allow unverified accounts to access protected application functionality.

Do not require a student number during initial account registration unless an approved requirement explicitly adds it. The FSD requires the student number during the CoR join-request process (UC-02).

Password reset is deferred in FSD v1.0. Do not add it to Sprint 1.

### Account model and authorization rules

- Use Django's configured custom User model.
- Email is the account login identifier.
- Normalize email addresses and enforce uniqueness.
- Preserve Django's password hashing and authentication behavior.
- Keep account authentication separate from application authorization.
- Do not implement President or Officer as permanent global user roles.
- A user may belong to multiple servers.
- Server-specific roles must belong to the user's membership in the corresponding server.
- Django staff/superuser privileges are for platform administration and must not be confused with server membership roles.
- Coordinate changes to shared models and migrations with the other developer.

### Privacy and security requirements

- Collect only information required by the FSD.
- Never expose CoR files to unauthorized users.
- CoR files must be handled through private storage and deleted after the verification decision.
- Never log passwords, verification tokens, or unnecessary personal information.
- Authorship visibility must follow the FSD's reason, audit-log, and author-notification requirements.
- Use server-side validation, CSRF protection, Django ORM protections, and appropriate access checks.
- Do not treat hidden UI elements as authorization controls.

### Implementation discipline

Before implementing a feature:

1. Identify the relevant FSD requirements.
2. Inspect existing code and related models.
3. Identify dependencies and possible effects on other applications.
4. Present a concise implementation plan when model, migration, authentication, authorization, or security changes are involved.
5. Implement only the approved scope.
6. Add or update tests.
7. Run the relevant checks and report actual results.

Do not claim a requirement is complete merely because its page or interface exists. Verify its underlying behavior.

## 5. Sprint Instructions

The active sprint requirements are documented in:

`SPRINT_1_FEATURES.md`

Read this file before implementing Sprint 1 tasks.

Do not assume every checklist item belongs to one developer.

Implement only the responsibilities assigned to the requesting developer.

Work incrementally:
1. Inspect the current implementation.
2. Identify incomplete requirements.
3. Propose a small implementation plan.
4. Identify affected files.
5. Implement one logical feature.
6. Add or update automated tests.
7. Run the relevant checks.
8. Report the results.
9. Wait for approval before proceeding to another major feature when requested.

Never claim a feature is complete without implementation and testing.

## 6. Developer Responsibilities

### Developer 1 — Kenneth Velasco

Primary responsibility:
- Project foundation.
- Custom User model.
- Registration.
- Institutional email verification.
- Password validation.
- Registration consent.
- Login and logout.
- Authentication and permission foundation.
- Basic account dashboard.
- Account-related automated tests.

### Developer 2 — Teammate

Primary responsibility:
- Review of database architecture.
- Review of account model compatibility.
- Discussion and channel architecture preparation.
- Integration testing.
- Fresh-clone setup verification.
- Review of Developer 1's account implementation.
- Assigned feature implementation in subsequent sprints.

Both developers collaborate on database design, integration, testing, and code review.

Do not independently modify shared models or migrations without coordinating with the other developer.

## 7. Git Workflow

Follow the repository's branching strategy:

- `main`: stable releases.
- `dev`: integration branch.
- `test`: quality assurance and release candidate.
- `feature/*`: individual feature development.
- `bugfix/*`: defect corrections.

Rules:
- Never develop directly on `main`.
- Create feature branches from the latest `dev`.
- Commit related changes in focused commits.
- Push feature branches to GitHub.
- Open pull requests targeting `dev`.
- Request teammate review before merging.
- Test integrated changes before promoting them.
- Never force-push shared branches without explicit authorization.

Suggested commit prefixes:
- `feat:` new functionality.
- `fix:` bug fixes.
- `refactor:` code restructuring.
- `test:` automated tests.
- `docs:` documentation.
- `chore:` maintenance.

## 8. Database and Migration Rules

- Inspect existing models and migrations before changing database structure.
- Never delete migration files to resolve migration errors.
- Never regenerate an existing shared initial migration without a clear reason.
- Generate migrations after intentional model changes.
- Review generated migration contents.
- Ensure migration dependencies are correct.
- Test migrations against the development database.
- Explain potentially destructive database operations before performing them.

## 9. Testing Requirements

After implementing a feature, run relevant tests.

At minimum, verify:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Add tests for:
- Successful operations.
- Invalid input.
- Unauthorized access.
- Permission restrictions.
- Expected error conditions.
- Relevant security behavior.

Do not remove existing tests simply to make the test suite pass.

If a test fails, investigate and explain the cause before changing unrelated code.

## 10. Security Requirements

- Never store plaintext passwords.
- Never expose secret keys or credentials.
- Never commit `.env`.
- Never expose private CoR files.
- Use appropriate authorization checks.
- Protect state-changing requests against CSRF.
- Prevent unauthorized access to server resources.
- Do not trust client-side validation alone.
- Avoid logging sensitive personal information.

## 11. Code Change Discipline

Before modifying files:
- Identify the purpose of each affected file.
- Explain why the change is necessary.
- Avoid overwriting working implementations.
- Avoid changing unrelated functionality.
- Preserve existing conventions.

After modifying files, report:

1. What was implemented.
2. Which files were created or modified.
3. Which FSD requirements were addressed.
4. Which tests were executed.
5. Test results.
6. Migration impact.
7. Remaining work.
8. Any risks or unresolved issues.

Do not fabricate test results.

## 12. Scope Control

Do not:
- Implement multiple major features in one uncontrolled operation.
- Build features that are outside the active sprint.
- Add unnecessary packages.
- Replace the existing architecture without approval.
- Rewrite unrelated files.
- Assume a requirement exists because similar applications commonly have it.

If a requirement is unclear or conflicts with the FSD, stop and explain the conflict before implementing it.

## 13. Primary Objective

Help the development team deliver Curator as a complete, secure, maintainable, and working application before the project deadline.

Prioritize:
1. FSD compliance.
2. Working functionality.
3. Security and privacy.
4. Maintainable code.
5. Automated testing.
6. Reliable Git integration.

The goal is a working integrated application, not merely completed individual screens or isolated features.