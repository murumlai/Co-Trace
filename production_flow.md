Production flow should be:

1. User opens Co-Trace in browser.
2. Frontend sees no valid session from /api/me.
3. User clicks “Sign in with GitHub.”
4. Backend redirects to GitHub.
5. GitHub authenticates user.
6. GitHub redirects back to IIS-hosted backend callback.
7. Backend validates OAuth state, exchanges code, fetches GitHub identity.
8. Backend issues secure HttpOnly app session cookie.
9. User is redirected back to frontend and remains signed in.