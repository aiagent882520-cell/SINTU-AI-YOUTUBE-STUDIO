# Owner, Admin and User feature access

## Account hierarchy

- **Owner** is the single bootstrap account configured by `SINTU_OWNER_USERNAME` (defaults to `SINTU_ADMIN_USERNAME`). The Owner is marked in the database and cannot be demoted, disabled, or edited through team-account management.
- **Admin** can use only the feature groups explicitly granted by the Owner. The Admin role does not imply global access.
- **Editor/User** can use only granted features and may create/update only within the existing Editor method restrictions.
- **Viewer/User** can read only the features explicitly granted by the Owner.

## Feature grants

New team accounts receive no feature grants. The Owner can grant or revoke any combination of:

- Dashboard
- Projects
- AI Assistant
- AI Production
- Video Editor
- Media Library
- Agent Management
- YouTube Studio
- Social & Publishing
- Integrations
- AI Provider Settings
- Earning System

Permission changes are written to the security audit log. Revocation is enforced by the API on the next request; hiding a panel in the browser is only a usability aid, not the security boundary.

## Security contract

- Unclassified API routes fail closed for non-Owner accounts.
- Owner-only routes include team management, permission management, security audit, backup management and Principal AI knowledge/council control.
- Existing account role restrictions remain in force: Viewer is read-only; Editor cannot use PUT/PATCH/DELETE; Admin can write only inside granted features.
- The application session is revalidated against the current database account state, so disabling an account invalidates its next request.
- The bootstrap Owner identity is separate from ordinary Admin accounts.

## Owner second factor

Mobile/email OTP enrollment and mandatory OTP verification are a separate unfinished security increment. Until that is delivered and enabled, this implementation still uses the existing password + signed session flow. Do not treat the Owner panel as fully production-secure until OTP is complete.
