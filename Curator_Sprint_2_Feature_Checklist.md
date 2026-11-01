# Curator --- Sprint 2 Feature Checklist

## Sprint 2

**Servers, CoR Verification & Membership**

-   **Sprint dates:** November 16–29, 2026
-   **Final checkpoint:** November 29, 2026, 11:59 PM PHT
-   **Planned effort:** 24 story points
-   **Repository:** `kennethvelasco-dev/curator-class-forum`
-   **FSD baseline:** Curator FSD v1.0
-   **Sprint issues:** #19--#26 and #56

------------------------------------------------------------------------

## 1. Sprint Goal

Deliver the first working server and membership lifecycle for Curator.

By the end of this sprint:

1.  Students can request a new class server and submit a valid
    Certificate of Registration (CoR).
2.  Administrators can securely review server requests and approve or
    reject them with a recorded reason.
3.  Students can request to join an existing server and confirm the
    subjects/sections they are enrolled in.
4.  Class Presidents can review join requests and approve or reject
    them.
5.  Approved students receive access only to the appropriate server and
    approved subject channels.
6.  CoR files are stored privately and permanently deleted after a
    decision.
7.  Students can belong to multiple servers, and Presidents can transfer
    their role to another verified member.
8.  Automated tests protect the new workflows and the existing Sprint 1
    account functionality.

**Important:** Sprint 2 is not complete merely because the pages render.
The server-side validation, authorization, database changes, file
privacy, deletion behavior, and automated tests must work.

------------------------------------------------------------------------

## 2. Verified Issue Ownership

The following assignments were checked against the current GitHub
issues.

| Issue | Task | Assignee | Priority |
| --- | --- | --- | --- |
| [#19](https://github.com/kennethvelasco-dev/curator-class-forum/issues/19) | Create `Server`, `ServerRequest`, and `Membership` models | Jamere (`jmrlvnth-bit`) | Critical |
| [#20](https://github.com/kennethvelasco-dev/curator-class-forum/issues/20) | Student server creation request form with CoR upload | Kenneth (`kennethvelasco-dev`) | High |
| [#21](https://github.com/kennethvelasco-dev/curator-class-forum/issues/21) | Student server join request with CoR and subject confirmation | Kenneth (`kennethvelasco-dev`) | Critical |
| [#22](https://github.com/kennethvelasco-dev/curator-class-forum/issues/22) | President join-request review interface | Kenneth (`kennethvelasco-dev`) | High |
| [#23](https://github.com/kennethvelasco-dev/curator-class-forum/issues/23) | Immediate CoR deletion after approval or rejection | Kenneth (`kennethvelasco-dev`) | Critical |
| [#24](https://github.com/kennethvelasco-dev/curator-class-forum/issues/24) | Multi-server enrollment and section-specific access | Kenneth (`kennethvelasco-dev`) | Medium |
| [#25](https://github.com/kennethvelasco-dev/curator-class-forum/issues/25) | President title transfer | Kenneth (`kennethvelasco-dev`) | Medium |
| [#26](https://github.com/kennethvelasco-dev/curator-class-forum/issues/26) | Automated tests for Sprint 2 workflows | Kenneth (`kennethvelasco-dev`) | High |
| [#56](https://github.com/kennethvelasco-dev/curator-class-forum/issues/56) | Admin review workflow for server requests | Kenneth (`kennethvelasco-dev`) | High |

### Kenneth's responsibilities

-   [ ] #20 --- Server creation request form and secure CoR upload.
-   [ ] #21 --- Student join request, CoR upload, and subject
    confirmation.
-   [ ] #22 --- President review queue and approve/reject processing.
-   [ ] #23 --- CoR file deletion and orphan-file prevention.
-   [ ] #24 --- Multiple server memberships and section-specific access.
-   [ ] #25 --- Secure President role transfer.
-   [ ] #26 --- Automated unit and integration tests.
-   [ ] #56 --- Admin server-request review, decision reasons, server
    creation, and initial President assignment.

### Jamere's responsibility

-   [ ] #19 --- Implement the foundational `Server`, `ServerRequest`,
    and `Membership` models, constraints, and migrations.

### Shared responsibilities

-   [ ] Agree on model fields, relationships, status values, and service
    interfaces before dependent implementation proceeds.
-   [ ] Review each other's changes and resolve integration conflicts.
-   [ ] Test workflows across the complete application, not only in
    isolation.
-   [ ] Keep the FSD, issue descriptions, and implementation behavior
    aligned.
-   [ ] Verify that Sprint 1 authentication and access behavior remains
    functional.

**Ownership rule:** An issue's assigned owner is accountable for
completing its acceptance criteria and preparing its work for review.
Shared work does not silently transfer issue ownership.

------------------------------------------------------------------------

## 3. Feature Checklist and Acceptance Criteria

## A. Foundation dependency --- Issue #19

**Owner: Jamere**

This work is a dependency for the server and membership features below.
Kenneth must coordinate with Jamere before relying on model names,
fields, or relationships.

-   [ ] Create `Server` model with class/section name, slug,
    description, active status, and creation timestamp.
-   [ ] Create `ServerRequest` model with requester, status, decision
    reason, review timestamp, and CoR reference.
-   [ ] Create `Membership` model linking a user to a server.
-   [ ] Support the roles Student, Officer, and President.
-   [ ] Enforce the required uniqueness constraints and prevent
    duplicate active memberships.
-   [ ] Support valid membership role transitions.
-   [ ] Generate and verify migrations.
-   [ ] Add model-level automated tests.
-   [ ] Confirm the model/API contract with Kenneth before dependent
    features are finalized.

**Dependency handoff:** Do not invent replacement models or duplicate
relationships to work around an unfinished dependency. Agree on the
contract, use temporary isolated work only when practical, and integrate
against the actual merged implementation.

## B. Server creation request and CoR upload --- Issue #20

**Owner: Kenneth**

-   [ ] Implement the server creation request route at
    `/servers/request/`.
-   [ ] Implement the Django form, view, and template.
-   [ ] Require an authenticated user.
-   [ ] Accept PDF files only.
-   [ ] Reject files larger than 6 MB.
-   [ ] Display clear, user-friendly validation errors.
-   [ ] Warn students to mask/block out their personal contact number
    before uploading.
-   [ ] Store CoR files in private storage, not a publicly enumerable
    media URL.
-   [ ] Create a pending `ServerRequest` associated with the
    authenticated requester.
-   [ ] Show a submission confirmation and pending-review status.
-   [ ] Add automated tests for authentication, valid uploads, invalid
    file types, oversized files, and private access.

**Acceptance:** A student can submit a valid request and see that it is
pending. Invalid uploads are rejected, and unauthorized users cannot
retrieve the document.

## C. Admin server-request review --- Issue #56

**Owner: Kenneth**

-   [ ] Build an Admin-only dashboard/queue for pending server requests.
-   [ ] Restrict the review endpoint and CoR viewer to authorized
    platform administrators.
-   [ ] Allow an Admin to inspect the submitted CoR through a protected
    file handler.
-   [ ] Implement approval with server-side validation.
-   [ ] On approval, create the `Server`.
-   [ ] On approval, create the default channels: Announcements,
    Calendar, and Rules.
-   [ ] On approval, designate the requester as the server's President
    and create the required membership.
-   [ ] Implement rejection with a mandatory, non-empty reason.
-   [ ] Record the decision and review metadata.
-   [ ] Delete the uploaded CoR after either approval or rejection.
-   [ ] Add tests for access restrictions, approval, rejection,
    mandatory reason, server creation, default channels, President
    assignment, and file deletion.

**Acceptance:** Only an Admin can review a server request. Approval
creates the server and initial President membership. Rejection requires
a reason. The CoR is deleted after the decision.

## D. Student join request --- Issue #21

**Owner: Kenneth**

-   [ ] Implement the join route at `/servers/<slug>/join/`.
-   [ ] Require authentication.
-   [ ] Accept PDF CoR uploads only, maximum 6 MB.
-   [ ] Collect the student's student number as required by the issue.
-   [ ] Display the subjects/sections associated with the selected
    server.
-   [ ] Require the student to confirm at least one enrolled subject.
-   [ ] Warn the student to mask their personal contact number before
    uploading.
-   [ ] Create a pending join-request record linked to the student and
    server.
-   [ ] Ensure the uploaded CoR can be accessed only by the relevant
    server President and an Admin when escalation is authorized.
-   [ ] Provide a clear pending status to the student.
-   [ ] Add tests for validation, permissions, duplicate requests, and
    status visibility.

**Architecture note:** The issue uses the name `JoinRequest`, while #19
defines `ServerRequest` and `Membership`. Inspect the existing
application and coordinate the data model with Jamere. Do not create a
second, overlapping request model without an explicit design decision.

## E. President join-request review --- Issue #22

**Owner: Kenneth**

-   [ ] Build a pending join-request queue for each server.
-   [ ] Restrict the queue to that server's authenticated President.
-   [ ] Ensure a President cannot review requests for another server.
-   [ ] Provide a protected CoR inspection link.
-   [ ] Allow approval of the student's confirmed subjects.
-   [ ] Allow rejection only with a non-empty explanation.
-   [ ] Record the decision and its relevant metadata.
-   [ ] On approval, create/activate the student's membership.
-   [ ] Bind permissions to only the approved subjects for that server.
-   [ ] Ensure rejected or pending users do not receive member access.
-   [ ] Add automated tests for authorization, approval, rejection,
    required reason, and subject-level access.

## F. CoR deletion and privacy --- Issue #23

**Owner: Kenneth**

-   [ ] Implement a reusable CoR deletion service.
-   [ ] Delete the physical file after an Admin approves or rejects a
    server request.
-   [ ] Delete the physical file after a President approves or rejects a
    join request.
-   [ ] Clear the corresponding file reference from the request record.
-   [ ] Handle missing files safely and make cleanup idempotent.
-   [ ] Prevent unauthorized file access before a decision.
-   [ ] Ensure a failed deletion is not silently reported as successful.
-   [ ] Log enough operational information to investigate cleanup
    failures without logging sensitive document contents.
-   [ ] Add tests that assert the file no longer exists after each
    decision path.
-   [ ] Add regression tests for orphaned files and repeated decision
    attempts.

**Important implementation detail:** Database transactions do not
automatically make filesystem/storage operations transactional. Design
the decision and cleanup sequence so the application does not report a
completed privacy cleanup when deletion failed. Preserve a recoverable
failure state or retry path, and test it. Do not delete the only copy
before the decision has been safely recorded.

## G. Multi-server membership and section-specific access --- Issue #24

**Owner: Kenneth**

-   [ ] Allow one student to have memberships in multiple distinct
    servers.
-   [ ] Display all of the student's active servers on the
    dashboard/navigation.
-   [ ] Implement an active-server switcher.
-   [ ] Scope channel queries to the currently selected server.
-   [ ] Filter subject channels using the student's approved subjects
    for that server.
-   [ ] Prevent a membership in Server A from granting access to Server
    B.
-   [ ] Prevent unapproved subjects from appearing or being accessible.
-   [ ] Verify that switching servers does not leak data between
    servers.
-   [ ] Add tests for multiple memberships, switching, and
    server/subject isolation.

## H. President title transfer --- Issue #25

**Owner: Kenneth**

-   [ ] Implement a President settings page or transfer interface.
-   [ ] List only eligible active, approved members of the same server.
-   [ ] Require confirmation before transfer.
-   [ ] Require password re-authentication.
-   [ ] Reject transfer to non-members or unverified accounts.
-   [ ] Perform the role transition atomically.
-   [ ] Assign the target member the President role.
-   [ ] Demote the previous President to Officer or Student according to
    the agreed rule.
-   [ ] Ensure the previous President immediately loses President-only
    permissions.
-   [ ] Add tests for authorization, invalid targets, re-authentication,
    role changes, and permission revocation.

## I. Automated test suite --- Issue #26

**Owner: Kenneth, with Jamere supporting model-level tests**

-   [ ] Add tests under `apps/servers/tests.py` or the project's
    established test structure.
-   [ ] Test server creation requests.
-   [ ] Test Admin approval and rejection.
-   [ ] Test default channel creation and initial President membership.
-   [ ] Test student join requests.
-   [ ] Test President approval and rejection.
-   [ ] Test mandatory rejection reasons.
-   [ ] Test CoR privacy and access restrictions.
-   [ ] Test immediate CoR deletion after every decision path.
-   [ ] Test multi-server membership and subject isolation.
-   [ ] Test President title transfer and permission revocation.
-   [ ] Run the Sprint 1 authentication tests to check for regressions.
-   [ ] Run the complete Django test suite.
-   [ ] Fix failures caused by Sprint 2 changes before marking the issue
    complete.

**Required command:** `python manage.py test apps.servers`

The issue's acceptance criterion calls for all Sprint 2 workflows to
pass, including file-system assertions and role/permission tests.

------------------------------------------------------------------------

## 4. AI Coding Assistant --- Mandatory Rules

These rules apply whenever an AI assistant (Claude, ChatGPT, Copilot, or
another coding agent) inspects, writes, edits, tests, or refactors this
repository.

### A. Understand before changing code

-   [ ] Inspect the repository structure before proposing
    implementation.
-   [ ] Read the relevant models, views, forms, URLs, templates,
    services, settings, and tests before editing.
-   [ ] Read the applicable GitHub issue and its acceptance criteria.
-   [ ] Inspect the existing Sprint 1 implementation and preserve
    working behavior.
-   [ ] Check the current branch, working tree, and recent changes
    before making edits.
-   [ ] Identify dependencies and coordinate model/service contracts
    before implementing dependent features.
-   [ ] State the files likely to change and the implementation plan
    before a substantial change.
-   [ ] If a requirement is ambiguous or conflicts with existing code,
    explain the conflict and ask for a decision rather than silently
    inventing behavior.

### B. Preserve the existing architecture

-   [ ] Follow the project's existing Django architecture and
    conventions.
-   [ ] Use Django's MTV structure: models, templates, and views.
-   [ ] Keep business logic reusable and appropriately separated, using
    the existing service-layer conventions (including `services.py`
    where appropriate).
-   [ ] Keep views focused on HTTP handling, permissions, validation
    coordination, and responses.
-   [ ] Do not put the entire feature into one oversized view or model
    method.
-   [ ] Reuse existing authentication, authorization, forms, utilities,
    and UI patterns where appropriate.
-   [ ] Do not introduce a new framework, package, database, or
    architectural pattern without explaining why and obtaining approval.
-   [ ] Do not duplicate models or create parallel sources of truth.
-   [ ] Keep naming, URL patterns, templates, and app boundaries
    consistent with the repository.

### C. Code quality and security

-   [ ] Write readable, maintainable, production-minded code.
-   [ ] Validate all untrusted input on the server, even when the
    browser also validates it.
-   [ ] Enforce authorization on every protected view and file handler;
    hiding a link is not access control.
-   [ ] Scope every server-specific query to a server the current user
    is authorized to access.
-   [ ] Use Django forms/model validation and ORM operations
    appropriately.
-   [ ] Use CSRF protection for state-changing requests.
-   [ ] Avoid raw SQL unless the existing design requires it and the
    query is safely parameterized.
-   [ ] Never expose private CoR files through public media URLs or
    guessable paths.
-   [ ] Never log passwords, authentication tokens, CoR contents, or
    unnecessary personal information.
-   [ ] Enforce file type and size restrictions on the server; do not
    trust file extensions alone.
-   [ ] Avoid mass assignment and do not trust role, user ID, server ID,
    or approval status supplied by the client.
-   [ ] Use transactions for related database changes and handle storage
    operations explicitly.
-   [ ] Avoid broad exception handling that hides errors.
-   [ ] Do not weaken security controls to make a test pass.

### D. Changes must be scoped and traceable

-   [ ] Implement only the requested issue and necessary supporting
    changes.
-   [ ] Do not refactor unrelated modules during a feature task.
-   [ ] Do not delete existing functionality, tests, migrations, or user
    changes without explicit approval.
-   [ ] Do not overwrite uncommitted work.
-   [ ] Do not generate migrations blindly; inspect the model changes
    and migration output.
-   [ ] Explain any added dependency and why it is necessary.
-   [ ] Keep the implementation aligned with the FSD and issue
    acceptance criteria.
-   [ ] Update or add tests whenever behavior changes.

### E. AI must not take Git actions without permission

-   [ ] Do not switch branches, create branches, merge, rebase, reset,
    stash, or cherry-pick unless explicitly instructed.
-   [ ] Do not commit, push, force-push, close issues, or merge pull
    requests unless explicitly instructed.
-   [ ] Do not modify GitHub issue assignments or project status without
    permission.
-   [ ] Never use destructive commands to make the working tree clean.
-   [ ] Before any requested Git operation, inspect the current branch
    and working tree.
-   [ ] Report the exact files changed and commands executed.
-   [ ] If a command may overwrite or discard work, stop and request
    approval.

### F. Be evidence-based

-   [ ] Do not claim a feature is complete because code was generated.
-   [ ] Do not claim tests pass unless the tests were actually executed
    and passed.
-   [ ] Do not claim a file is private or deleted without verifying the
    access/deletion behavior.
-   [ ] Distinguish verified behavior, unverified assumptions, and
    remaining manual checks.
-   [ ] Report test failures and warnings honestly.
-   [ ] Do not mark GitHub issues Done until their acceptance criteria
    and Definition of Done are satisfied.

------------------------------------------------------------------------

## 5. Required Development Workflow

Follow this workflow for each assigned issue. Do not skip review or
testing to save time.

### Step 1 --- Select and inspect the issue

1.  Open the assigned GitHub issue.
2.  Read its objective, implementation scope, requirements, acceptance
    criteria, and Definition of Done.
3.  Inspect related code and tests.
4.  Check issue dependencies and confirm required model/service
    contracts with the responsible teammate.
5.  Convert the acceptance criteria into a small implementation
    checklist.

**Output:** A short plan, dependency list, and expected files to change.

### Step 2 --- Confirm the development baseline

Run:

``` powershell
git status
git branch --show-current
git log -5 --oneline
```

Confirm the intended base branch and that existing user changes are
safe. Sprint feature work should branch from the agreed current `dev`
baseline unless the team explicitly decides otherwise.

**Do not assume that the local branch is current.** Fetch and inspect
remote changes before starting when appropriate.

### Step 3 --- Create or use the issue branch

Use one focused branch per issue or tightly coupled implementation unit,
following the team's naming convention.

Example:

``` text
feature/20-server-creation-request
feature/21-server-join-request
feature/22-president-review
feature/23-cor-file-cleanup
```

-   Start from the agreed `dev` branch.
-   Keep unrelated issues out of the branch.
-   Do not work directly on `main`.
-   Do not merge another person's unfinished branch without
    coordination.

### Step 4 --- Implement in small, reviewable increments

1.  Implement the data/form/service/view/template changes required by
    the issue.
2.  Add server-side validation and authorization as part of the feature,
    not as a later patch.
3.  Add tests alongside the implementation.
4.  Keep changes small enough to inspect and explain.
5.  Run focused tests after meaningful changes.
6.  Re-check the diff for unrelated edits.

### Step 5 --- Run verification

Activate the virtual environment if it is not already active:

``` powershell
.venv\Scripts\Activate.ps1
```

Run the relevant checks:

``` powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.servers
python manage.py test
git diff --check
git status
```

If the test layout differs, inspect the repository and use the correct
test label. Do not silently skip a required check.

Also perform manual browser checks for the user-facing workflows,
especially:

-   Student request submission and validation.
-   Admin-only server review.
-   President-only join-request review.
-   Unauthorized direct URL/file access.
-   CoR deletion after approval and rejection.
-   Multi-server switching and subject access.
-   President transfer and loss of previous privileges.

### Step 6 --- Review the implementation

Before requesting review:

-   [ ] Compare the final diff against the issue scope.
-   [ ] Check for accidental settings, secrets, generated files, or
    unrelated changes.
-   [ ] Check migrations and database constraints.
-   [ ] Check authorization at the view and object level.
-   [ ] Check that errors are handled without hiding failures.
-   [ ] Check that tests cover both success and failure cases.
-   [ ] Confirm that Sprint 1 behavior still works.

### Step 7 --- Pull request and integration

Use the agreed branch flow:

``` text
feature/*  →  dev  →  test  →  main
```

1.  Push the feature branch only when authorized.
2.  Open a pull request targeting `dev`.
3.  Link the relevant issue (for example, `Closes #20` only when the
    issue is genuinely completed by that PR).
4.  Describe the implementation, tests run, screenshots where useful,
    and known limitations.
5.  Request teammate review.
6.  Resolve review comments and rerun relevant tests.
7.  Merge into `dev` only after approval and successful checks.
8.  Integrate the sprint candidate into `test` for broader QA.
9.  Merge to `main` only after the team has verified and approved the
    release candidate.

**Never merge unfinished feature work directly into `main`.** A
successful local test is not a substitute for peer review and
integration testing.

### Step 8 --- Update the issue and sprint board

-   [ ] Update the issue with implementation and test evidence.
-   [ ] Move the task through the team's workflow: Backlog → Ready → In
    Progress → In Review → Testing → Done.
-   [ ] Keep the assignee accurate.
-   [ ] Record blockers and dependencies.
-   [ ] Mark Done only after the merged implementation has passed the
    agreed verification.

------------------------------------------------------------------------

## 6. Definition of Done --- Sprint 2

A feature is Done only when all applicable conditions are met:

-   [ ] Every acceptance criterion in its GitHub issue is satisfied.
-   [ ] The feature follows the existing project architecture.
-   [ ] Server-side validation is implemented.
-   [ ] Authentication and authorization are verified.
-   [ ] Private CoR documents cannot be accessed by unauthorized users.
-   [ ] CoR deletion is verified after approval and rejection.
-   [ ] Database changes and migrations are valid.
-   [ ] Automated tests cover successful, invalid, and unauthorized
    scenarios.
-   [ ] Relevant tests pass.
-   [ ] Sprint 1 authentication tests still pass.
-   [ ] `python manage.py check` reports no issues.
-   [ ] `python manage.py makemigrations --check --dry-run` reports no
    uncommitted model changes.
-   [ ] `git diff --check` reports no whitespace errors.
-   [ ] Manual browser verification is complete for user-facing
    behavior.
-   [ ] Code has been reviewed and merged through the agreed branch
    workflow.
-   [ ] GitHub issue and sprint board are updated with accurate status.

### Sprint-level completion

-   [ ] #19 model foundation integrated.
-   [ ] #20 server creation request works end-to-end.
-   [ ] #56 Admin review works end-to-end.
-   [ ] #21 student join request works end-to-end.
-   [ ] #22 President review works end-to-end.
-   [ ] #23 CoR deletion is verified for all decision paths.
-   [ ] #24 multi-server and subject-level access isolation works.
-   [ ] #25 President transfer works securely.
-   [ ] #26 automated tests pass.
-   [ ] No unresolved critical security or data-integrity defects
    remain.
-   [ ] Sprint 1 functionality remains stable.
-   [ ] Sprint review/demo evidence is prepared.

------------------------------------------------------------------------

## 7. Out of Scope and Scope Control

Do not pull later-sprint functionality into Sprint 2 simply because it
is related to servers.

-   [ ] Do not implement discussion feeds, announcements, or calendar
    functionality beyond creating the default channel records required
    by #56.
-   [ ] Do not implement unrelated UI redesigns or broad refactors.
-   [ ] Do not add unapproved features or dependencies.
-   [ ] Do not weaken the CoR privacy requirements to simplify
    implementation.
-   [ ] Do not expand role permissions beyond the FSD and approved issue
    requirements.

If an acceptance criterion cannot be completed because of a dependency,
raise the blocker early and document its impact. Do not silently remove
the criterion.

------------------------------------------------------------------------

## 8. AI Task Execution Prompt

Use this prompt when asking an AI coding assistant to work on one Sprint
2 issue:

> You are working on the Curator Class Forum Django project. Complete
> only the GitHub issue assigned to you for Sprint 2.
>
> First inspect the repository, current branch, working tree, relevant
> FSD requirements, issue description, existing implementation, and
> tests. Do not assume that a model, route, service, or permission
> exists until you verify it.
>
> Before editing, provide a concise implementation plan, identify
> dependencies, list the expected files to change, and identify security
> considerations. Follow the existing Django MTV architecture and
> service-layer conventions. Coordinate model contracts with the
> teammate responsible for shared models. Do not create duplicate models
> or parallel sources of truth.
>
> Implement the issue's acceptance criteria completely, including
> server-side validation, object-level authorization, private file
> handling, database integrity, and automated tests where applicable.
> Preserve all existing Sprint 1 behavior and all unrelated user
> changes. Keep the patch scoped and maintainable.
>
> Do not switch branches, commit, push, merge, rebase, reset, stash,
> close issues, or change GitHub project metadata unless I explicitly
> authorize that action.
>
> Run the relevant tests and project checks. Report the exact commands
> and actual results. Do not claim success for anything you did not
> verify. Identify remaining manual checks, known limitations, and
> blockers.
>
> At the end, provide: 1. What was implemented. 2. Files created or
> modified. 3. Acceptance criteria satisfied and any still incomplete.
> 4. Tests/checks executed and their actual results. 5. Security and
> authorization checks performed. 6. Any migration, integration, or
> teammate dependency. 7. The next recommended step.
>
> Do not mark the issue complete unless its acceptance criteria and
> Definition of Done are genuinely satisfied.

------------------------------------------------------------------------

## 9. Sprint 2 Progress Tracker

Update these checkboxes only when there is evidence that the work is
complete.

### Kenneth

-   [ ] #20 --- Server creation request and CoR upload
-   [ ] #21 --- Student join request and subject confirmation
-   [ ] #22 --- President join-request review
-   [ ] #23 --- CoR deletion and privacy safeguards
-   [ ] #24 --- Multi-server membership and subject isolation
-   [ ] #25 --- President title transfer
-   [ ] #26 --- Automated tests
-   [ ] #56 --- Admin server-request review

### Jamere

-   [ ] #19 --- Server, ServerRequest, and Membership models

### Team integration

-   [ ] Shared model contract agreed.
-   [ ] Dependent feature branches integrated.
-   [ ] Peer reviews completed.
-   [ ] Sprint candidate deployed or available in the test environment.
-   [ ] End-to-end demonstration completed.
-   [ ] Sprint 1 regression checks passed.
-   [ ] Sprint 2 review and retrospective completed.

------------------------------------------------------------------------

**Sprint 2 completion standard:** Working, tested, access-controlled
functionality integrated into the project---not merely generated code,
completed templates, or closed GitHub issues.
