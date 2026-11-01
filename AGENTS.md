# Curator — AI Development Instructions (Grok / Agentic Coding)

These instructions apply to Grok Build, IDE coding agents, and other AI assistants working in this repository.

## 1. Project identity and source of truth

- Project: **Curator — Class Forum**
- Repository: `kennethvelasco-dev/curator-class-forum`
- Local Windows workspace (current known path): `C:\Users\Kenneth\OneDrive\Desktop\curator-class-forum`
- Framework: Django 5.2, Python.
- Architecture: Django Model–Template–View (MTV), the Django equivalent of MVC.
- Frontend: Django Templates, HTML, CSS, JavaScript.
- Local database: SQLite.
- Production database target: PostgreSQL/Supabase (do not assume production configuration is already complete).
- Environment configuration: `python-dotenv`.
- Local timezone: `Asia/Manila`.
- Current app layout includes `apps/accounts/`, `core/`, `config/`, `templates/`, `static/`, and feature app scaffolds.

**Requirements authority (highest to lowest):**
1. Approved `docs/FSD.pdf` (Curator FSD v1.0).
2. The active sprint specification/checklist in the repository.
3. Existing architecture, migrations, and accepted implementation decisions.
4. GitHub issue descriptions and acceptance criteria, provided they do not contradict the FSD.
5. AI suggestions.

Do not silently reinterpret, add, remove, or weaken an approved requirement. If two sources conflict, identify the exact conflict and stop before implementing the disputed behavior.

## 2. Project purpose and product rules

Curator is a university class forum and academic scheduling platform. It is intended to organize class servers, subject channels, discussions, announcements, and a read-only calendar. Students join class servers through Certificate of Registration (CoR) verification. The FSD defines Student, Officer, President, and platform Admin roles.

Important domain rules:
- A user may belong to multiple class servers.
- President and Officer are **server-membership roles**, not global roles on the User model.
- Platform Admin is separate from server-level roles.
- Access to channels and server resources must be checked on the server, never merely hidden in the UI.
- CoR documents contain sensitive student information. They must be private, available only to the authorized verifier/Admin as specified, and deleted immediately after the verification decision.
- CoR upload requirements: PDF only, maximum 6 MB. The upload screen must instruct students to mask their personal contact number before uploading.
- Student number is collected in the CoR join-request flow, not during initial account registration.
- Preserve the FSD's approval/rejection, mandatory reason, access, notification, audit, and privacy rules.

## 3. Current technical baseline

Use the existing stack and patterns. Do not add a frontend framework, REST framework, task queue, storage provider, or dependency unless a specific approved requirement needs it and the team approves the design.

Known repository facts:
- `requirements.txt` currently declares Django `>=5.2,<5.3` and `python-dotenv>=1.0,<2.0`.
- Local setup uses `.venv`, `.env`, `python manage.py migrate`, and `python manage.py runserver`.
- `python manage.py test` runs the Django test suite.
- Existing custom email-based User model and registration-verification migrations are already in place. Inspect actual code and migration history before touching them.
- Existing app namespaces include accounts, servers, channels, discussions, announcements, and moderation; do not assume every feature route is implemented.
- `.env`, credentials, local database files, uploaded CoR PDFs, and other private artifacts must never be committed.

Never assume a README statement proves that a feature exists. Inspect the current branch and source code.

## 4. Sprint and delivery boundaries

The planned schedule from the team roadmap is:
- Sprint 1: Nov 2–15, 2026 — Foundation + Accounts & Access.
- Sprint 2: Nov 16–29, 2026 — Servers, CoR, and Membership.
- Sprint 3: Nov 30–Dec 13, 2026 — Channels, roles, class setup, and threaded discussion.
- Sprint 4: Dec 14–27, 2026 — Announcements, calendar, and notifications.
- Sprint 5: Dec 28, 2026–Jan 10, 2027 — Moderation, administration, and release.
- Final buffer: Jan 11–15, 2027.

Sprint 1 is integrated on `dev` at merge commit `e8c1aa0e7cc6b528431cf62d1a40e3f221124110`; the team reported Django checks/migration checks passing and 51 tests passing. A fresh-clone/manual verification remains outstanding. Do not report Sprint 1 as fully signed off until that verification is complete.

### Sprint 2 scope

Sprint 2 implements the server lifecycle and CoR-based membership workflows, mapped to FSD FR-004 through FR-010 and FR-013.

GitHub Sprint 2 issues currently identified:
- **#19** — Create `Server`, `ServerRequest`, and `Membership` models. Assigned to Jamere (`jmrlvnth-bit`). This is a critical dependency; coordinate model fields, constraints, migrations, and interfaces with Jamere. Do not independently duplicate or replace this work.
- **#20** — Student server-creation request form with CoR upload (PDF, <= 6 MB). Assigned to Kenneth.
- **#21** — Student server join request with CoR and subject confirmation. Assigned to Kenneth.
- **#22** — President join-request review interface with mandatory rejection reason. Assigned to Kenneth.
- **#23** — Immediate CoR file deletion after approval or rejection. Assigned to Kenneth; critical privacy/security work.
- **#24** — Multi-server enrollment and section-specific subject access. Assigned to Kenneth; Should-Have. Do not let it delay Must-Have requirements.
- **#25** — President title transfer. Assigned to Kenneth; Should-Have. Do not let it delay Must-Have requirements.
- **#26** — Automated test suite for server creation, join requests, and CoR deletion. Assigned to Kenneth; coordinate tests against both developers' model/service interfaces.
- **#56** — Admin review workflow for server requests with mandatory reason logging. Assigned to Kenneth.

Issue descriptions and acceptance criteria are the task-level contract. Always fetch/read the current issue before implementation; issue details may have changed.

### Sprint 2 developer ownership

Developer 1 — Kenneth (`kennethvelasco-dev`):
- Foundation/configuration and account/authentication.
- CoR workflows and membership access-control.
- Security/privacy and Admin/audit/security logic.
- Sprint 2 assigned work: #20–#26 and #56, subject to priority and the live GitHub issue state.
- Coordinate with Jamere on shared models/migrations and test integration.

Developer 2 — Jamere (`jmrlvnth-bit`):
- Sprint 2 assigned work: #19, core `Server`, `ServerRequest`, and `Membership` models/migrations.
- Collaborate on integration, tests, reviews, and bug fixes.

Both developers share integration testing, code review, defect fixing, and documentation. Never reassign ownership or make unilateral changes to shared work.

### Later-sprint work

Do not implement Sprint 3–5 features during Sprint 2 unless Kenneth explicitly asks for a bounded research/design task. Announcements and calendar belong to Sprint 4 (FR-032–FR-038). Prior planning or Claude groundwork for later issues is not authorization to implement or merge those features now. Preserve existing notes and avoid modifying unrelated scaffolds.

## 5. Mandatory workflow before editing

For every task:

1. **Confirm task:** Identify the GitHub issue number, assignee, sprint, priority, dependencies, FSD requirements, and acceptance criteria.
2. **Inspect state:** Run `git status`, identify current branch, inspect relevant files, tests, migrations, and recent commits. Read `README.md`, this file, `.github/copilot-instructions.md`, `docs/FSD.pdf` (or its relevant extracted section), and the active sprint checklist.
3. **Check shared work:** Inspect Jamere's branch/PR/model proposal before changing models, relationships, migration dependencies, or shared services.
4. **Plan first:** Provide a concise plan listing files likely to change, data-model impact, authorization/security implications, tests, and risks. For database/security changes, wait for approval before implementation.
5. **Limit scope:** Implement one issue or one coherent subtask at a time. Do not opportunistically refactor unrelated code.
6. **Implement:** Follow existing conventions, use small changes, and preserve working behavior.
7. **Test:** Add/update tests and run the relevant checks. Do not fabricate results.
8. **Review diff:** Inspect `git diff` and `git status`; check for secrets, accidental files, unrelated changes, and migration surprises.
9. **Report:** State changed files, issue/FR mapping, behavior implemented, tests and exact results, migration impact, unresolved items, and next action.
10. **Pause:** Do not begin the next major issue until Kenneth confirms or gives a clearly scoped next task.

If repository state, issue scope, or requirements are unclear, ask one focused question rather than guessing.

## 6. Coding standards

- Use Django 5.2 and the repository's current Python style.
- Prefer Django ORM and model/form validation; use parameterized queries if raw SQL is unavoidable.
- Keep views focused on HTTP request/response orchestration.
- Put reusable business rules in appropriate model methods, forms, or focused service modules following existing patterns.
- Keep business logic out of templates and JavaScript.
- Use Django's built-in authentication, password hashing, sessions, CSRF protection, and messages framework where appropriate.
- Validate all untrusted input on the server. Client-side validation is supplemental only.
- Use `transaction.atomic()` for multi-step decisions that must remain consistent.
- Use clear names, focused functions, and minimal dependencies.
- Follow the current app structure; do not invent a second architecture.
- Avoid generic abstractions, premature optimization, unnecessary comments, and broad rewrites.
- Add docstrings/comments only where they clarify non-obvious domain behavior or security decisions.
- Preserve accessibility, keyboard operation, responsive layouts, and the established Curator dark/minimal design.

## 7. Security and privacy rules (strict)

- Never expose `.env`, API keys, passwords, tokens, private keys, database dumps, or user secrets.
- Never commit `.env`, local SQLite databases, virtual environments, uploaded CoR files, or test artifacts.
- Never log passwords, verification tokens, raw CoR contents, or unnecessary personal information.
- Do not store CoR files under public static/media URLs.
- Do not trust an unguessable URL as access control. Enforce authorization in the view/service before returning a file.
- Restrict CoR access to the specific authorized verifier and platform Admin as the FSD requires.
- Validate PDF format and 6 MB maximum on the server. Do not rely only on filename or browser MIME type; inspect content safely.
- Instruct students to mask their contact number before upload.
- Delete the physical CoR file and clear its stored reference immediately after an approval/rejection decision. Handle deletion failures explicitly; do not falsely report successful deletion.
- Ensure approval/rejection state, membership creation, and reason logging remain consistent. Use transactions and explicit cleanup/error handling appropriate to the storage backend.
- Do not weaken Django security middleware, CSRF, session, password, or authorization settings to make a test pass.
- Do not create a global President/Officer flag on `User`.
- Prevent insecure direct-object-reference access between servers.
- Do not reveal private student information in error messages or logs.

If a task requires a trade-off between transaction atomicity and file deletion (filesystem/object storage is not part of a database transaction), explain the failure modes and propose a recoverable, tested strategy before coding. Never claim the file deletion is transactionally atomic with a database transaction unless the storage system actually guarantees it.

## 8. Models and migrations

- Inspect `apps/accounts/models.py` and all existing migrations before changing user-related or shared relationships.
- Coordinate Sprint 2 `Server`, `ServerRequest`, and `Membership` model interfaces with Jamere.
- Keep membership roles scoped to a server membership.
- Add database constraints for invariants (for example, unique user-server membership) where appropriate.
- Do not delete, rename, squash, or regenerate existing migrations casually.
- Do not edit a migration already shared/applied by teammates unless explicitly agreed.
- Generate migrations only after model changes are approved; inspect the generated file.
- Run migration checks and test migration application.
- Explain any data migration, destructive change, or rollback risk before applying it.

## 9. Git and collaboration rules

Branch strategy:
- `main`: stable release only.
- `dev`: integration branch.
- `test`: QA/release-candidate branch when the team workflow calls for it.
- `feature/*`: individual feature branches.
- `bugfix/*`: defect fixes.

Rules:
- Start feature branches from the latest `origin/dev`.
- PR base is **`dev`**, not `main`.
- Never commit directly to `main`, `dev`, or `test`.
- Never push directly to shared integration branches.
- Never merge your own PR unless Kenneth explicitly authorizes it and required review/checks are complete.
- Do not force-push, reset shared branches, delete branches, or rewrite history without explicit approval.
- Do not stage or commit all files blindly. Inspect `git status` and stage only related paths.
- Do not amend or rewrite another developer's commits.
- Do not merge Jamere's model branch or modify shared migrations without coordination.
- Do not create duplicate PRs for an issue that already has an active PR.

Recommended PowerShell workflow:

```powershell
git status
git fetch origin
git switch dev
git pull --ff-only origin dev
git switch -c feature/issue-20-server-request
```

After implementation and tests:

```powershell
git status
git diff --check
git diff
git add <specific-related-files>
git commit -m "feat(servers): add server creation request"
git push -u origin feature/issue-20-server-request
```

Open a PR:
- Base: `dev`
- Compare: the feature branch
- Include issue reference (for example `Closes #20` only if the PR truly completes it).
- Include summary, implementation details, tests run, migration notes, security considerations, and screenshots for UI changes.

Never state that a PR is merged unless GitHub confirms it.

## 10. Required checks and test discipline

Run the narrowest relevant tests first, then the full suite when appropriate:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.servers
python manage.py test
```

Also verify:
- `git diff --check`
- Unauthorized users cannot access protected views/files.
- Cross-server access isolation works.
- Invalid and oversized uploads are rejected.
- Valid CoR PDFs are stored privately.
- Approval and rejection require correct actors and reasons.
- CoR files are actually removed after a decision.
- Membership and server creation outcomes match the FSD.
- Existing Sprint 1 authentication tests continue to pass.

Report actual command output or a concise faithful summary. If a command was not run, say so. Do not delete or weaken tests to achieve a green result.

## 11. AI collaboration protocol: Grok and Claude

Grok is a second engineering assistant, not an independent project owner.

- Treat Claude's output as a proposal until verified against the repository, FSD, and GitHub issue.
- Do not overwrite Claude's files or discard uncommitted work. Inspect `git status`, diffs, and branch ownership first.
- When reviewing Claude's implementation, review the actual code/diff, not only its explanation.
- Give independent findings with file paths, line references, severity, and reproducible reasoning.
- Separate confirmed defects from questions and suggestions.
- Do not create competing implementations of the same issue.
- Do not ask two agents to edit the same files concurrently.
- One agent owns implementation; the other reviews or performs a clearly separate task.
- If Claude has done advance research for Sprint 4 announcements/calendar, Grok may review the research when asked, but must not implement or merge Sprint 4 features during Sprint 2.
- Kenneth is the decision-maker for scope, priorities, and merge authorization.

## 12. Required response format after each task

Always report:

1. **Issue / scope:** issue number, sprint, and FR references.
2. **Findings before editing:** existing implementation and dependencies.
3. **Files changed:** exact paths and why.
4. **Implementation:** behavior delivered and important decisions.
5. **Tests:** exact commands and pass/fail results.
6. **Migrations:** none / generated / applied, with details.
7. **Security and privacy:** relevant authorization, upload, deletion, and data-handling checks.
8. **Git state:** branch, commit, PR URL/status; do not claim a push or merge unless confirmed.
9. **Remaining work:** unmet acceptance criteria and blockers.
10. **Next step:** one recommended next action.

A task is not Done because a screen exists. It is Done only when acceptance criteria are implemented, tested, reviewed, and integrated through the agreed workflow.
