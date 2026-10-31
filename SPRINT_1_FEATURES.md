Curator — Sprint 1 Feature Checklist
Sprint 1
 Foundation + Accounts & Access

Sprint goal: Deliver a working account system with registration, institutional email verification, login, logout, and protected pages.

FSD baseline: Curator FSD v1.0, particularly FR-001, FR-002, and FR-003.
1. Project foundation
- [ ] Confirm Django project starts successfully.
- [ ] Confirm project follows Django Model–Template–View architecture.
- [ ] Verify requirements.txt contains all required dependencies.
- [ ] Configure environment variables.
- [ ] Ensure .env is excluded from Git.
- [ ] Create or update .env.example with required variable names.
- [ ] Verify database configuration.
- [ ] Verify static files and templates configuration.
- [ ] Confirm migrations are tracked in Git.
- [ ] Update README with installation and setup instructions.
- [ ] Confirm another developer can clone and run the project.
Acceptance criteria:
- A fresh clone can install dependencies, configure the environment, migrate the database, and run the application.
- python manage.py check completes without errors.
2. Custom user model
FSD attributes include email, password hash, full name, student number, active status, and creation date.
- [ ] Inspect the existing apps/accounts implementation.
- [ ] Confirm the custom User model is configured using AUTH_USER_MODEL.
- [ ] Use institutional email as the login identifier.
- [ ] Enforce unique email addresses.
- [ ] Normalize email addresses.
- [ ] Store the user's full name.
- [ ] Store student number if required by the registration design.
- [ ] Use Django's built-in password hashing.
- [ ] Support account active/inactive status.
- [ ] Add account creation timestamp.
- [ ] Add email-verification status.
- [ ] Add appropriate model validation and constraints.
- [ ] Generate and review required migrations.
Important: Do not replace the existing migration history unnecessarily. Inspect existing migrations before modifying the User model.
3. Registration
FSD: FR-001 and FR-003.
- [ ] Create registration page.
- [ ] Create registration form.
- [ ] Collect required user information.
- [ ] Validate institutional email addresses.
- [ ] Make the allowed email domain configurable.
- [ ] Use iskolarngbayan.pup.edu.ph as the initial PUP pilot domain.
- [ ] Reject invalid email addresses.
- [ ] Reject duplicate email addresses.
- [ ] Validate all fields on the server.
- [ ] Validate password confirmation.
- [ ] Enforce password requirements:
  - [ ] At least 8 characters.
  - [ ] At least one uppercase letter.
  - [ ] At least one lowercase letter.
  - [ ] At least one digit.
  - [ ] Special characters permitted.
- [ ] Display the rules and privacy notice.
- [ ] Explain CoR processing.
- [ ] Explain anonymous-post authorship visibility.
- [ ] Require explicit consent before registration.
- [ ] Record consent and its timestamp.
- [ ] Prevent registration without consent.
- [ ] Display a successful registration message.
- [ ] Instruct the user to verify their email.
Acceptance criteria:
- Valid institutional email and valid registration information create an unverified account.
- Invalid institutional email is rejected.
- Duplicate email is rejected.
- Weak passwords are rejected.
- Missing consent prevents registration.
4. Email verification
FSD: FR-001.
- [ ] Generate secure verification tokens.
- [ ] Implement token expiration.
- [ ] Associate verification tokens with the correct account.
- [ ] Configure email delivery through environment variables.
- [ ] Implement verification email template.
- [ ] Include verification link.
- [ ] Implement verification endpoint.
- [ ] Mark account as verified only after successful token validation.
- [ ] Handle expired tokens.
- [ ] Handle invalid tokens.
- [ ] Handle previously used tokens.
- [ ] Display verification success and failure pages.
- [ ] Prevent unverified users from accessing authenticated pages.
- [ ] Configure local development email backend.
- [ ] Test email generation and verification.
Acceptance criteria:
- New accounts are unverified by default.
- Valid verification links activate verification.
- Invalid or expired links cannot verify accounts.
- Users cannot bypass verification by directly entering protected URLs.
5. Login and logout
FSD: FR-002.
- [ ] Create login page.
- [ ] Authenticate using email and password.
- [ ] Use Django's authentication framework.
- [ ] Prevent unverified accounts from logging in.
- [ ] Display appropriate login errors.
- [ ] Establish authenticated sessions.
- [ ] Redirect authenticated users to the dashboard.
- [ ] Implement logout.
- [ ] Invalidate sessions after logout.
- [ ] Protect authenticated pages.
- [ ] Redirect unauthenticated visitors to login.
- [ ] Configure reasonable session expiry.
- [ ] Use POST for logout.
Acceptance criteria:
- Verified users can log in.
- Incorrect credentials are rejected.
- Unverified users cannot log in.
- Logged-out users cannot access protected pages.
- Sessions behave correctly after restarting the server.
6. Basic authenticated dashboard
- [ ] Create a basic authenticated landing page.
- [ ] Display the signed-in user's name.
- [ ] Display the signed-in user's email.
- [ ] Add a visible logout button.
- [ ] Add navigation between login and registration.
- [ ] Display appropriate messages for unauthenticated visitors.
- [ ] Make the page responsive.
Do not implement the full server/channel dashboard yet.
7. Roles and authorization foundation
- [ ] Separate authentication from authorization.
- [ ] Establish a reusable permission-checking approach.
- [ ] Use Django's staff/superuser functionality appropriately.
- [ ] Keep future Student, Officer, President, and Admin permissions in mind.
- [ ] Document how future server-specific membership roles will work.
- [ ] Ensure the design supports a user belonging to multiple servers.
Important architectural rule: Do not create one global President or Officer role on the User model. Those roles belong to a user's membership in a particular server.

Full officer assignment and channel permissions are outside Sprint 1.
8. Interface and usability
- [ ] Registration page is usable on desktop and mobile.
- [ ] Login page is usable on desktop and mobile.
- [ ] Verification result pages are clear.
- [ ] Forms have readable labels.
- [ ] Validation messages are understandable.
- [ ] Privacy and consent information is visible.
- [ ] Forms are keyboard accessible.
- [ ] Maintain readable color contrast.
- [ ] Follow Curator's dark, minimalist design direction.
9. Security and privacy
- [ ] Use Django password hashing.
- [ ] Keep CSRF protection enabled.
- [ ] Use Django ORM or parameterized queries.
- [ ] Escape user-provided content in templates.
- [ ] Validate input server-side.
- [ ] Store secrets in environment variables.
- [ ] Never commit .env.
- [ ] Do not log passwords or verification tokens.
- [ ] Configure secure cookies and HTTPS for production.
- [ ] Minimize collection of personal information.
- [ ] Record consent appropriately.
10. Automated tests
- [ ] Test custom User creation.
- [ ] Test email uniqueness.
- [ ] Test email normalization.
- [ ] Test institutional email validation.
- [ ] Test password requirements.
- [ ] Test registration consent requirement.
- [ ] Test unverified account creation.
- [ ] Test verification email generation.
- [ ] Test valid verification token.
- [ ] Test invalid verification token.
- [ ] Test expired verification token.
- [ ] Test reused verification token.
- [ ] Test unverified login rejection.
- [ ] Test verified login success.
- [ ] Test incorrect password rejection.
- [ ] Test logout.
- [ ] Test protected-page access.
- [ ] Run the complete test suite.
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
- [ ] Matches the FSD.
- [ ] Server-side validation works.
- [ ] Automated tests are implemented.
- [ ] python manage.py check passes.
- [ ] python manage.py makemigrations --check --dry-run passes.
- [ ] python manage.py test passes.
- [ ] Migrations are reviewed and committed when necessary.
- [ ] No secrets or temporary exports are committed.
- [ ] Manual testing is complete.
- [ ] Code follows the existing project architecture.
- [ ] Pull request includes implementation details and test results.
- [ ] Another developer reviews the changes.
- [ ] Changes are merged into dev, not directly into main.
14. Sprint review demonstration
At the end of Sprint 1, demonstrate:
1. Open Curator while logged out.
2. Navigate to registration.
3. Attempt registration with an invalid email.
4. Register using a valid institutional email.
5. Show the consent requirement.
6. Show that the account is initially unverified.
7. Open the verification email.
8. Verify the account.
9. Log in.
10. Open the protected dashboard.
11. Display the user's account information.
12. Log out.
13. Attempt to revisit the protected dashboard.
14. Show that access is denied or redirected.
15. Run the Django system check and tests.

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



16. Git commands for the current branch
git status
git switch feature/accounts-authentication
git fetch origin
git merge origin/dev


After implementation and testing:
git add .
git commit -m "feat(accounts): implement registration and email verification"
git push -u origin feature/accounts-authentication


Open a pull request with:
- Base: dev
- Compare: feature/accounts-authentication