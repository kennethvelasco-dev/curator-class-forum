Curator — Sprint 1 Feature Checklist
Sprint 1
 Foundation + Accounts & Access

Sprint goal: Deliver a working account system with registration, institutional email verification, login, logout, and protected pages.

FSD baseline: Curator FSD v1.0, particularly FR-001, FR-002, and FR-003.

Checklist status: Checked items are supported by the current source, settings, documentation, or tests. Production settings are conditionally enabled, but deployment/proxy behavior remains unverified. Items requiring missing implementation, fresh-clone testing, manual demonstration, or teammate/repository workflow remain unchecked.

1. Project foundation
- [x] Confirm Django project starts successfully.
- [x] Confirm project follows Django Model–Template–View architecture.
- [x] Verify requirements.txt contains all required dependencies.
- [x] Configure environment variables.
- [x] Ensure .env is excluded from Git.
- [x] Create or update .env.example with required variable names.
- [x] Verify database configuration.
- [x] Verify static files and templates configuration.
- [x] Confirm migrations are tracked in Git.
- [x] Update README with installation and setup instructions.
- [ ] Confirm another developer can clone and run the project.
Acceptance criteria:
- A fresh clone can install dependencies, configure the environment, migrate the database, and run the application.
- python manage.py check completes without errors.
2. Custom user model
FSD attributes include email, password hash, full name, student number, active status, and creation date. Student number must not be required or collected during initial account registration. Collect it in the CoR join-request flow (UC-02); any User-model student-number field must remain optional until that workflow is implemented.
- [x] Inspect the existing apps/accounts implementation.
- [x] Confirm the custom User model is configured using AUTH_USER_MODEL.
- [x] Use institutional email as the login identifier.
- [x] Enforce unique email addresses.
- [x] Normalize email addresses.
- [x] Store the user's full name.
- [x] Do not require or collect student number during initial account registration.
- [ ] Collect student number through the CoR join-request flow (UC-02), when implemented.
- [x] Use Django's built-in password hashing.
- [x] Support account active/inactive status.
- [x] Add account creation timestamp.
- [x] Add email-verification status.
- [x] Add appropriate model validation and constraints.
- [x] Generate and review required migrations.
Important: Do not replace the existing migration history unnecessarily. Inspect existing migrations before modifying the User model.
3. Registration
FSD: FR-001 and FR-003.
- [x] Create registration page.
- [x] Create registration form.
- [x] Collect required user information.
- [x] Collect only the institutional email before email ownership is proven; do not persist a password or create a User at this stage.
- [x] After a valid emailed link is submitted, collect full name, password, and explicit privacy consent to complete account creation.
- [x] Validate institutional email addresses.
- [x] Make the allowed email domain configurable.
- [x] Use iskolarngbayan.pup.edu.ph as the initial PUP pilot domain.
- [x] Reject invalid email addresses.
- [x] Reject duplicate email addresses.
- [x] Validate all fields on the server.
- [x] Validate password confirmation.
- [x] Enforce password requirements:
  - [x] At least 8 characters.
  - [x] At least one uppercase letter.
  - [x] At least one lowercase letter.
  - [x] At least one digit.
  - [x] Special characters permitted.
- [x] Display the rules and privacy notice.
- [x] Explain CoR processing.
- [x] Explain anonymous-post authorship visibility.
- [x] Require explicit consent when completing registration after email ownership is proven.
- [x] Record consent and its timestamp.
- [x] Prevent registration without consent.
- [x] Display a successful registration message.
- [x] Instruct the user to verify their email.
Acceptance criteria:
- A valid institutional email starts a time-limited verification request without creating a User or storing a password.
- A valid emailed link alone does not create an account; submitting the completion form with valid information and consent creates a verified account and establishes its password.
- Invalid institutional email is rejected.
- Existing verified email addresses cannot create duplicate accounts.
- A pending or expired verification request cannot establish a password; expired addresses can restart registration.
- Weak passwords are rejected.
- Missing consent prevents registration.
4. Email verification
FSD: FR-001.
- [x] Generate secure verification tokens.
- [x] Implement token expiration.
- [x] Associate verification tokens with the correct account.
- [x] Configure email delivery through environment variables.
- [ ] Implement verification email template (the current verification message is assembled inline in the view).
- [x] Include verification link.
- [x] Implement verification endpoint.
- [x] Mark account as verified only after successful token validation.
- [x] Handle expired tokens.
- [x] Handle invalid tokens.
- [x] Handle previously used tokens.
- [x] Display verification success and failure pages.
- [x] Prevent unverified users from accessing authenticated pages.
- [x] Configure local development email backend.
- [x] Test email generation and verification.
Acceptance criteria:
- No new account is created until a valid verification link is submitted with the account-completion form.
- Valid verification links complete registration and activate the verified account.
- Invalid or expired links cannot verify accounts.
- Users cannot bypass verification by directly entering protected URLs.
5. Login and logout
FSD: FR-002.
- [x] Create login page.
- [x] Authenticate using email and password.
- [x] Use Django's authentication framework.
- [x] Prevent unverified accounts from logging in.
- [x] Display appropriate login errors.
- [x] Establish authenticated sessions.
- [x] Redirect authenticated users to the dashboard.
- [x] Implement logout.
- [x] Invalidate sessions after logout.
- [x] Protect authenticated pages.
- [x] Redirect unauthenticated visitors to login.
- [x] Configure reasonable session expiry.
- [x] Use POST for logout.
Acceptance criteria:
- Verified users can log in.
- Incorrect credentials are rejected.
- Unverified users cannot log in.
- Logged-out users cannot access protected pages.
- Sessions behave correctly after restarting the server.
6. Basic authenticated dashboard
- [x] Create a basic authenticated landing page.
- [x] Display the signed-in user's name.
- [x] Display the signed-in user's email.
- [x] Add a visible logout button.
- [x] Add navigation between login and registration.
- [x] Display appropriate messages for unauthenticated visitors.
- [x] Make the page responsive.
Do not implement the full server/channel dashboard yet.
7. Roles and authorization foundation
- [x] Separate authentication from authorization.
- [x] Establish a reusable permission-checking approach.
- [x] Use Django's staff/superuser functionality appropriately.
- [x] Keep future Student, Officer, President, and Admin permissions in mind.
- [x] Document how future server-specific membership roles will work.
- [ ] Ensure the design supports a user belonging to multiple servers (server-membership implementation is not present yet).
Important architectural rule: Do not create one global President or Officer role on the User model. Those roles belong to a user's membership in a particular server.

Full officer assignment and channel permissions are outside Sprint 1.
8. Interface and usability
- [x] Registration page is usable on desktop and mobile.
- [x] Login page is usable on desktop and mobile.
- [x] Verification result pages are clear.
- [x] Forms have readable labels.
- [x] Validation messages are understandable.
- [x] Privacy and consent information is visible.
- [x] Forms are keyboard accessible.
- [x] Maintain readable color contrast.
- [x] Follow Curator's dark, minimalist design direction.
9. Security and privacy
- [x] Use Django password hashing.
- [x] Keep CSRF protection enabled.
- [x] Use Django ORM or parameterized queries.
- [x] Escape user-provided content in templates.
- [x] Validate input server-side.
- [x] Store secrets in environment variables.
- [x] Never commit .env.
- [ ] Do not log passwords or verification tokens (the local console email backend prints verification links containing tokens).
- [x] Configure secure cookies and HTTPS for production (settings enable these when `DJANGO_DEBUG=False`; production proxy/deployment behavior still requires deployment verification).
- [x] Minimize collection of personal information.
- [x] Record consent appropriately.
10. Automated tests
- [x] Test custom User creation.
- [x] Test email uniqueness.
- [x] Test email normalization.
- [x] Test institutional email validation.
- [x] Test password requirements.
- [x] Test registration consent requirement.
- [x] Test that email verification is pending without creating a User or storing a password.
- [x] Test verification email generation.
- [x] Test valid verification token.
- [x] Test invalid verification token.
- [x] Test expired verification token.
- [x] Test reused verification token.
- [x] Test unverified login rejection.
- [x] Test verified login success.
- [x] Test incorrect password rejection.
- [x] Test logout.
- [x] Test protected-page access.
- [x] Run the complete test suite.
11. Explicitly excluded from Sprint 1
These features belong to later increments:
Feature	FSD reference
Server creation and Admin approval	FR-004–005
Student server joining and CoR verification	FR-006–009
Multiple-server membership	FR-010
Channel access management	FR-011
Officer assignment	FR-012
President transfer	FR-013
Default and subject channels	FR-014–017
Threads and replies	FR-018–023
Anonymous posting and authorship	FR-024–029
Abuse-of-authority reporting	FR-030–031
Announcements and calendar	FR-032–037
Notifications	FR-038
Moderation	FR-039–040
Administration	FR-041–042

Password reset, two-factor authentication, and social login are also excluded.
12. Suggested implementation order
1. Inspect the existing User model and migration history.
2. Confirm project settings and environment configuration.
3. Finalize the custom User model.
4. Implement registration.
5. Implement password validation and consent.
6. Configure email delivery.
7. Implement email verification.
8. Implement login and logout.
9. Implement the protected landing page.
10. Implement automated tests.
11. Review security and privacy.
12. Update documentation.
13. Open a pull request into dev.
14. Have the teammate review and test the integration.
13. Definition of Done
A feature is not complete merely because its page exists.
- [ ] Matches the FSD (full FSD compliance has not been independently verified).
- [x] Server-side validation works.
- [x] Automated tests are implemented.
- [x] python manage.py check passes.
- [x] python manage.py makemigrations --check --dry-run passes.
- [x] python manage.py test passes.
- [x] Migrations are reviewed and committed when necessary.
- [x] No secrets or temporary exports are committed.
- [ ] Manual testing is complete.
- [x] Code follows the existing project architecture.
- [ ] Pull request includes implementation details and test results.
- [ ] Another developer reviews the changes.
- [ ] Changes are merged into dev, not directly into main.
14. Sprint review demonstration
At the end of Sprint 1, demonstrate:
1. Open Curator while logged out.
2. Navigate to registration.
3. Attempt registration with an invalid email.
4. Request registration using a valid institutional email.
5. Show that no account or password exists before email ownership is proven.
6. Open the verification email; show that GET does not complete registration.
7. Enter account information and consent, then submit to verify and create the account.
8. Log in.
9. Open the protected dashboard.
10. Display the user's account information.
11. Log out.
12. Attempt to revisit the protected dashboard.
13. Show that access is denied or redirected.
14. Run the Django system check and tests.

15. Instructions for GitHub Copilot
Add the following instruction to .github/copilot-instructions.md if that file exists:
For Sprint 1, read SPRINT_1_FEATURES.md before making changes.

Treat the FSD v1.0 and the sprint checklist as the requirements baseline.

Inspect the existing project structure, custom User model, settings,
URLs, templates, and migration history before modifying code.

Implement one small feature at a time. Keep changes within Sprint 1.

Do not implement server creation, CoR verification, discussions,
announcements, calendar, or deferred features unless explicitly requested.

Use Django's built-in authentication and password hashing.
Validate data on the server. Protect authenticated views.
Keep secrets in environment variables.

Add automated tests for every implemented behavior.

After each task, report:
- Files changed
- Features implemented
- Tests executed and results
- Migration impact
- Remaining checklist items

Do not claim a feature is complete unless it has been implemented
and tested.



16. Git workflow examples
Create a feature branch from the latest `dev` branch. Replace `<feature-branch>` with a descriptive branch name such as `feature/accounts-authentication`; the name shown is only an example.

```powershell
git status
git fetch origin
git switch dev
git pull --ff-only origin dev
git switch -c <feature-branch>
```

After implementation and testing:

```powershell
git add <related-files>
git commit -m "<type>(<area>): <summary>"
git push -u origin <feature-branch>
```

Open a pull request with:
- Base: dev
- Compare: `<feature-branch>`