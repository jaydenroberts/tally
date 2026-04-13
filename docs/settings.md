# Settings

The Settings page is where you manage your profile, users, AI personas, and general app preferences. It is divided into four tabs: **Profile**, **Users**, **Personas**, and **General**.

Only owners can access the Users and Personas tabs. Viewer accounts can only access Profile.

---

## Profile Tab

### Changing Your Password

1. Go to **Settings → Profile**
2. Enter your current password
3. Enter your new password and confirm it
4. Click **Save**

Your session remains active after a password change. Other active sessions (if any) will be invalidated.

---

## Users Tab

The Users tab is owner-only. It shows all user accounts in your Tally instance and lets you manage them.

### Viewing Users

The user list shows each account's username, display name, role, and assigned persona.

### Adding a User

1. Click **Add User**
2. Enter a username and password
3. Select a role: **Owner** or **Viewer**
4. Optionally assign a persona (determines AI Coach behaviour for this user)
5. Click **Save**

**Owner** accounts have full access to create, edit, and delete all data. **Viewer** accounts can view data but cannot make changes.

### Editing a User

Click the edit icon next to a user to update their display name, role, or assigned persona. You cannot change a user's username after creation.

To clear a user's persona assignment, open the edit form and set the persona field to blank.

### Deleting a User

Click the delete icon next to a user and confirm. You cannot delete your own account. Deleting a user does not delete any data they created.

### Assigning Personas

To give a user a specific AI Coach persona:
1. Open the user edit form
2. Select a persona from the **Persona** dropdown
3. Click **Save**

The persona takes effect immediately. If the user is currently in an AI Coach session, they may need to refresh for the new persona to load.

---

## Personas Tab

The Personas tab is owner-only. It lists all personas available in your Tally instance, including the two built-in system personas (Analyst and Family).

### Built-in Personas

The **Analyst** and **Family** personas are created by Tally on first run. They cannot be deleted, but their display names can be edited.

### Creating a Custom Persona

1. Click **Add Persona**
2. Fill in:
   - **Name** — the persona's display name
   - **Description** — a plain-language summary of what this persona is for
   - **System prompt** — the instruction text sent to the AI before each conversation. This defines the AI's behaviour, tone, and focus.
   - **Data access level** — `full`, `summary`, or `readonly`
   - **Can modify data** — whether the AI can write back to your Tally data
   - **Tone notes** (optional) — additional guidance for the AI's tone
3. Click **Save**

### Editing a Persona

Click the edit icon on a persona to update any of its fields. Changes take effect for all users assigned to that persona immediately.

### Deleting a Persona

Click the delete icon on a custom persona and confirm. When a persona is deleted, it is unassigned from any users who had it — those users will have no persona assigned until you assign them a new one. System personas cannot be deleted.

---

## General Tab

The General tab controls app-wide preferences that apply to all users.

### Currency

Set the currency symbol displayed throughout Tally (e.g. `$`, `£`, `€`). This is a display preference only — Tally does not perform currency conversion.

After saving, the currency symbol updates across all pages immediately without a page reload.

### Role Display Names

The owner and viewer role labels displayed in the UI can be renamed. For example, you might rename "Viewer" to "Partner" for a household setup.

**Note:** This changes only the display name. The underlying role slugs (`owner` and `viewer`) are fixed and used by Tally's security system — renaming the display name does not change what each role can do.

---

## Account Recovery

If you lose access to your owner account, use the `RECOVERY_TOKEN` environment variable to temporarily activate a password reset endpoint — no email or SMTP required.

### Recovery Steps

1. Stop the Tally container
2. Add `RECOVERY_TOKEN=your-recovery-secret` to the container's environment variables and restart
3. Tally logs a warning on startup: `WARNING: RECOVERY_TOKEN is set — password recovery endpoint is active. Remove after use.`
4. Send a POST request to the recovery endpoint:

```bash
curl -X POST http://your-server-ip:8092/api/auth/recover \
  -H "Content-Type: application/json" \
  -d '{"token": "your-recovery-secret", "new_password": "your-new-password"}'
```

5. Log in with the owner account using your new password
6. Stop the container, remove `RECOVERY_TOKEN` from the environment, and restart

**Warning:** Remove `RECOVERY_TOKEN` after use. While it is set, anyone who can reach the endpoint and knows the token can reset the owner password.

The recovery endpoint resets the password of the owner account with the lowest ID (the first owner created). If you have multiple owner accounts, it resets the original one.

**Tip:** For resilience, consider maintaining two owner accounts — a primary personal account and a backup service account. If you lose access to one, you can use the other without needing the recovery flow.

---

## Related

- [AI Coach](ai-coach.md) — how personas affect the AI coaching interface
- [Getting Started](getting-started.md) — first-run setup and owner account creation
- [Configuration](configuration.md) — environment variables for first-run account creation and recovery
