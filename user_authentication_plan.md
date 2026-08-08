## Plan: GitHub OAuth Per-User Sign-In

Replace the current admin/password login with GitHub OAuth, but do it together with per-user authorization. The original OAuth-only plan would authenticate users but would not isolate job data, cache deletion permissions, or write permissions. The recommended rollout is: GitHub org membership for access, httpOnly 30-day session cookies for persistence, job ownership checks for each user, shared read-through analysis cache for same-product matches, protected admin cache entries, optional fresh LLM reruns, and shared Product Knowledge with admin-only writes.

**Steps**

1. Register and configure the GitHub OAuth app.
   - Set local callback URL to `http://localhost:8000/api/auth/github/callback`.
   - Request `read:org` so the backend can verify org membership.
   - Add env vars: `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_ORG`, `JWT_SECRET`, `FRONTEND_URL`, `COOKIE_SECURE`, and an admin allowlist such as `GITHUB_ADMIN_USERS` or `GITHUB_ADMIN_TEAM`.

2. Add backend OAuth/session dependencies.
   - Add `httpx` for GitHub API calls.
   - Add `PyJWT` for signed session cookies.
   - Keep cookie `Max-Age` at 30 days, `HttpOnly`, `SameSite=Lax`, and `Secure` only when served over HTTPS.

3. Replace password auth with GitHub OAuth in the backend.
   - In `backend/app/auth.py`, replace `SimpleAuth` with GitHub OAuth helpers for authorize URL generation, code exchange, GitHub user lookup, org membership check, JWT creation, and JWT verification.
   - Change `require_user` so it reads the `session` cookie, verifies the JWT, and returns a structured authenticated user object rather than only a username string.
   - Include at least GitHub login, GitHub id, org, and admin flag in the session claims or in a derived auth context.

4. Add OAuth routes.
   - In `backend/app/main.py`, remove `POST /api/login`.
   - Add `GET /api/auth/github` to create a CSRF state cookie and redirect to GitHub.
   - Add `GET /api/auth/github/callback` to validate state, exchange code, verify org membership, set the 30-day `session` cookie, and redirect to the frontend.
   - Add `POST /api/logout` to clear the `session` cookie.
   - Keep `GET /api/me`, but return GitHub username and role metadata needed by the frontend.

5. Add job ownership before exposing OAuth broadly. Depends on step 3.
   - In `backend/app/job_registry.py`, add an owner field to each job, using the authenticated GitHub login or stable GitHub id.
   - During upload/job creation in `backend/app/main.py`, store the authenticated user as the job owner.
   - For every route that accepts `job_id`, verify that the current user owns the job before returning status, units, manager views, cache views, stop actions, or reanalysis results.
   - Return `404` or `403` consistently for cross-user access. Prefer `404` if you do not want to reveal that another user's job exists.

6. Implement shared read-through analysis cache with ownership-protected deletion. Depends on step 3.
   - In `backend/app/analysis_cache.py`, keep cache lookup shared across org users for matching product/code/context/signature/knowledge-version entries so User B can reuse a previous User A or admin result without a fresh LLM call.
   - Add metadata to every cache entry: `created_by`, `created_by_role`, `created_at`, `product_code`, `knowledge_hash`, `prompt_version`, `is_admin_saved` or `protected`, and a sanitized match signature that does not expose another user's uploaded log text.
   - Cache lookup should prefer admin-protected entries first, then the newest valid shared non-protected entry for the same product/signature.
   - Add an explicit `force_refresh` or `bypass_cache` option to upload/reanalysis requests. When selected, skip cache lookup, run a fresh LLM call, and save the result as a new user-created cache entry or revision without overwriting admin-protected entries.
   - Restrict cache deletion: admins can delete any cache entry; normal users can delete only their own non-protected entries; normal users cannot delete cache entries saved or protected by admins.
   - Restrict `GET /api/cache/analysis` so normal users can see enough shared cache metadata to understand reuse, but not private source job IDs, uploaded paths, or another user's raw log context.

7. Keep Product Knowledge shared, but protect writes with admin authorization.
   - Product Knowledge and acronym data remain shared reads for all GitHub org users.
   - Write routes under `/api/knowledge/*` should require admin authorization.
   - Admin status should come from an explicit allowlist or GitHub team membership, not just org membership.
   - Read routes can remain available to all authenticated org users.

8. Update frontend auth for cookie sessions.
   - In `frontend/src/api.js`, add `credentials: 'include'` to requests and remove bearer token header injection.
   - In `frontend/src/auth.jsx`, remove localStorage token usage, call `/api/me` on load, redirect login to `/api/auth/github`, and call `/api/logout` on logout.
   - In `frontend/src/pages/Login.jsx`, replace the username/password form with a GitHub sign-in button and display unauthorized/error states from OAuth redirects.
   - In dashboard components, use returned role metadata to hide or disable admin-only Product Knowledge write controls for non-admin users.
   - Add a clear `Run fresh analysis` or `Ignore cache` control wherever users submit uploads or reanalysis, and pass `force_refresh`/`bypass_cache` to the backend when selected.

9. Update tests for auth, ownership, and roles.
   - Replace tests that depend on `/api/login` bearer tokens with cookie/session auth helpers or dependency overrides.
   - Add tests that User A cannot access User B's job status, units, manager output, or private job cache details.
   - Add tests that shared cache lookup reuses a previous same-product result without calling the LLM again.
   - Add tests that `force_refresh`/`bypass_cache` skips cache lookup, calls the LLM, and saves a new user-created cache entry or revision.
   - Add tests that normal users cannot delete admin-saved/protected cache entries, but can delete their own non-protected entries.
   - Add tests that non-admin org users can read Product Knowledge but cannot upload, update, rebuild, or delete it.
   - Add tests for expired/invalid session cookies, OAuth callback state mismatch, non-org GitHub users, and logout cookie clearing.

**Relevant Files**

- `backend/app/auth.py` - replace in-memory bearer-token auth with GitHub OAuth, session JWT verification, and user/role context.
- `backend/app/main.py` - add OAuth/logout routes, update `/api/me`, set job owners during upload, enforce ownership and admin checks across protected endpoints.
- `backend/app/job_registry.py` - add job owner metadata and ownership-aware access helpers.
- `backend/app/analysis_cache.py` - implement shared same-product cache reads, cache ownership metadata, admin-protected entries, force-refresh bypass behavior, and role-aware deletion.
- `backend/app/dependencies.py` and `backend/app/knowledge/*` - keep shared knowledge stores, but make write operations require admin authorization.
- `backend/app/config.py` - add GitHub OAuth, cookie, frontend redirect, JWT, and admin-role settings.
- `backend/app/models.py` - remove password login models and add auth/user response models if useful.
- `backend/requirements.txt` - add `httpx` and `PyJWT`.
- `frontend/src/api.js` - send cookies with API requests and remove bearer-token behavior.
- `frontend/src/auth.jsx` - replace localStorage auth state with `/api/me`-driven cookie-session auth.
- `frontend/src/pages/Login.jsx` - replace credential form with GitHub sign-in UI and OAuth error handling.
- `frontend/src/App.jsx`, upload/reanalysis components, and Product Knowledge page components - consume auth role metadata, gate admin-only controls, and expose the optional fresh-analysis cache bypass control.
- `backend/tests/*` - update auth fixtures and add cross-user/role tests.

**Verification**

1. Run backend tests after adding auth fixtures and ownership tests: `cd backend && pytest`.
2. Manually start the backend and frontend, then verify `GET /api/auth/github` redirects to GitHub.
3. Complete OAuth with a GitHub org member and confirm `/api/me` returns the expected login and role.
4. Refresh the browser and confirm the user remains signed in through the httpOnly cookie.
5. Sign out and confirm `POST /api/logout` clears the cookie and returns the app to the login screen.
6. Use two test users or dependency-overridden test clients to confirm User A cannot access User B's job ids, while same-product analysis can reuse a sanitized shared cache entry created by another user.
7. Confirm a normal org user cannot delete admin-saved/protected cache entries, but can run a fresh LLM analysis when choosing the cache bypass option.
8. Confirm a normal org user can read Product Knowledge but receives `403` from Product Knowledge write/rebuild/delete routes.
9. Confirm a configured admin user can perform Product Knowledge writes.
10. Confirm a GitHub account outside the org is rejected and redirected back with a clear login error.

**Decisions**

- GitHub OAuth replaces the current admin/password login entirely.
- The app should allow only members of the configured GitHub org.
- Persistent login uses a 30-day httpOnly cookie, not localStorage.
- Job data must be scoped per user before OAuth is launched for multiple users.
- Analysis cache is shared for same-product/signature reads to avoid repeated LLM calls, but deletion is role- and ownership-controlled.
- Admin-saved or admin-protected cache entries cannot be deleted by normal users.
- Any user can choose a fresh LLM call by using an explicit cache-bypass option.
- Product Knowledge and acronyms are shared across org users for reading.
- Product Knowledge writes are admin-only.
- Admin authorization should use a configured allowlist or GitHub team membership, separate from general org membership.

**Further Considerations**

1. Admin source: simplest is `GITHUB_ADMIN_USERS`; more maintainable is GitHub team membership such as `GITHUB_ADMIN_TEAM`.
2. Cache sharing: shared cache should expose only sanitized result metadata and final diagnosis content, never another user's raw uploaded log snippets, source job ids, local file paths, or private context.
3. Deployment: production must use HTTPS and `COOKIE_SECURE=true`, and the GitHub OAuth app callback URL must match the deployed backend URL exactly.
