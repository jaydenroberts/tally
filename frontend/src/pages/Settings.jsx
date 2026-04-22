import { useEffect, useState, useCallback } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import Modal from '../components/Modal'
import Button from '../components/Button'
import FormField, { inputStyle, selectStyle } from '../components/FormField'

// ─── Local settings (localStorage) ───────────────────────────────────────────

const LS_KEY = 'tally_settings'

function loadLocalSettings() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {} } catch { return {} }
}

function saveLocalSettings(s) {
  localStorage.setItem(LS_KEY, JSON.stringify(s))
}

// ─── Badge helpers ────────────────────────────────────────────────────────────

const ACCESS_COLORS = {
  full:     '#50FA7B',  // green
  summary:  '#FFB86C',  // orange
  readonly: '#6272A4',  // muted
}

function AccessBadge({ level }) {
  const color = ACCESS_COLORS[level] || 'var(--muted)'
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99, color, background: color + '20', textTransform: 'capitalize' }}>
      {level}
    </span>
  )
}

function RoleBadge({ role }) {
  const color = role?.name === 'owner' ? '#8BE9FD' : '#6272A4'  // cyan : muted
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99, color, background: color + '20', whiteSpace: 'nowrap' }}>
      {role?.display_name ?? role?.name ?? '—'}
    </span>
  )
}

function ActiveBadge({ active }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99,
      color:       active ? '#50FA7B' : '#6272A4',    // green : muted
      background:  active ? '#50FA7B20' : '#44475A',  // green alpha : border
    }}>
      {active ? 'Active' : 'Inactive'}
    </span>
  )
}

// ─── Tab nav ──────────────────────────────────────────────────────────────────

function TabNav({ tabs, active, onChange }) {
  return (
    <div style={{
      display: 'flex', gap: 2, marginBottom: 28,
      borderBottom: '1px solid var(--border)',
      overflowX: 'auto',
    }}>
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            padding: '10px 18px',
            fontWeight: active === t.id ? 700 : 400,
            color:  active === t.id ? 'var(--green)' : 'var(--muted)',
            borderBottom: active === t.id ? '2px solid var(--green)' : '2px solid transparent',
            whiteSpace: 'nowrap', fontSize: 14,
            marginBottom: -1,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

// ─── Profile tab ──────────────────────────────────────────────────────────────

function ProfileTab({ user }) {
  const [pwForm, setPwForm]     = useState({ newPassword: '', confirm: '' })
  const [pwError, setPwError]   = useState('')
  const [pwSuccess, setPwSuccess] = useState(false)
  const [saving, setSaving]     = useState(false)

  function setPw(field) {
    return (e) => { setPwForm((f) => ({ ...f, [field]: e.target.value })); setPwSuccess(false) }
  }

  async function handlePasswordChange(e) {
    e.preventDefault()
    if (pwForm.newPassword.length < 8) { setPwError('Password must be at least 8 characters'); return }
    if (pwForm.newPassword !== pwForm.confirm) { setPwError('Passwords do not match'); return }
    setPwError(''); setSaving(true); setPwSuccess(false)
    try {
      await client.patch(`/users/${user.id}`, { password: pwForm.newPassword })
      setPwForm({ newPassword: '', confirm: '' })
      setPwSuccess(true)
    } catch (err) {
      setPwError(err.response?.data?.detail ?? 'Failed to update password')
    } finally { setSaving(false) }
  }

  const infoRows = [
    { label: 'Username',       value: user.username },
    user.email ? { label: 'Email', value: user.email } : null,
    { label: 'Role',           value: <RoleBadge role={user.role} /> },
    user.persona ? { label: 'AI Persona', value: <span style={{ color: 'var(--cyan)', fontSize: 14, fontWeight: 500 }}>{user.persona.name}</span> } : null,
    { label: 'Account status', value: <ActiveBadge active={user.is_active} /> },
  ].filter(Boolean)

  return (
    <div>
      <div style={styles.card}>
        <p style={styles.sectionTitle}>My Profile</p>
        {infoRows.map((row, i) => (
          <div
            key={row.label}
            style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '9px 0',
              borderBottom: i < infoRows.length - 1 ? '1px solid var(--border)' : 'none',
            }}
          >
            <span style={styles.infoLabel}>{row.label}</span>
            {typeof row.value === 'string'
              ? <span style={styles.infoValue}>{row.value}</span>
              : row.value}
          </div>
        ))}
      </div>

      <div style={{ ...styles.card, marginTop: 16 }}>
        <p style={styles.sectionTitle}>Change Password</p>
        <form onSubmit={handlePasswordChange}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, maxWidth: 480 }}>
            <FormField label="New password">
              <input
                style={inputStyle}
                type="password"
                value={pwForm.newPassword}
                onChange={setPw('newPassword')}
                required
                autoComplete="new-password"
                placeholder="Min. 8 characters"
              />
            </FormField>
            <FormField label="Confirm password">
              <input
                style={inputStyle}
                type="password"
                value={pwForm.confirm}
                onChange={setPw('confirm')}
                required
                autoComplete="new-password"
              />
            </FormField>
          </div>
          {pwError   && <p style={styles.errorMsg}>{pwError}</p>}
          {pwSuccess && <p style={styles.successMsg}>Password updated.</p>}
          <div style={{ marginTop: 12 }}>
            <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Update password'}</Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── User form ────────────────────────────────────────────────────────────────

function UserForm({ initial, roles, personas, onSave, onCancel, saving }) {
  const isEdit = !!initial
  const [form, setForm] = useState({
    username:   initial?.username       ?? '',
    email:      initial?.email          ?? '',
    password:   '',
    role_id:    String(initial?.role?.id ?? roles[0]?.id ?? ''),
    persona_id: String(initial?.persona?.id ?? ''),
    is_active:  initial?.is_active      ?? true,
  })
  const [error, setError] = useState('')

  function set(field) {
    return (e) => {
      const val = e.target.type === 'checkbox' ? e.target.checked : e.target.value
      setForm((f) => ({ ...f, [field]: val }))
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!isEdit && form.password.length < 8) { setError('Password must be at least 8 characters'); return }
    setError('')

    if (!isEdit) {
      const payload = {
        username: form.username,
        password: form.password,
        role_id:  parseInt(form.role_id),
      }
      if (form.email) payload.email = form.email
      onSave(payload)
    } else {
      const payload = {
        role_id:    parseInt(form.role_id),
        persona_id: form.persona_id ? parseInt(form.persona_id) : null,
        is_active:  form.is_active,
      }
      if (form.email !== (initial?.email ?? ''))  payload.email    = form.email || null
      if (form.password)                          payload.password = form.password
      onSave(payload)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {!isEdit && (
        <FormField label="Username *">
          <input style={inputStyle} value={form.username} onChange={set('username')} required autoFocus autoComplete="off" />
        </FormField>
      )}

      <FormField label="Email" hint="Optional">
        <input style={inputStyle} type="email" value={form.email} onChange={set('email')} autoComplete="email" />
      </FormField>

      <FormField
        label={isEdit ? 'New password' : 'Password *'}
        hint={isEdit ? 'Leave blank to keep existing' : 'Min. 8 characters'}
      >
        <input style={inputStyle} type="password" value={form.password} onChange={set('password')} required={!isEdit} autoComplete="new-password" />
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Role *">
          <select style={selectStyle} value={form.role_id} onChange={set('role_id')} required>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.display_name}</option>
            ))}
          </select>
        </FormField>

        <FormField label="AI Persona">
          <select style={selectStyle} value={form.persona_id} onChange={set('persona_id')}>
            <option value="">No persona</option>
            {personas.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </FormField>
      </div>

      {isEdit && (
        <FormField label="Status">
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: 'var(--white)', fontSize: 14 }}>
            <input type="checkbox" checked={form.is_active} onChange={set('is_active')} style={{ accentColor: 'var(--green)', width: 15, height: 15 }} />
            Active account
          </label>
        </FormField>
      )}

      {error && <p style={styles.errorMsg}>{error}</p>}
      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create user'}
        </Button>
      </div>
    </form>
  )
}

// ─── Users tab ────────────────────────────────────────────────────────────────

function UsersTab({ currentUser, roles, personas, onReload, onRefreshCurrentUser }) {
  const [users, setUsers]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [loadError, setLoadError] = useState('')
  const [showAdd, setShowAdd]   = useState(false)
  const [editing, setEditing]   = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [saving, setSaving]     = useState(false)
  const [actionError, setActionError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    client.get('/users')
      .then((r) => setUsers(r.data))
      .catch(() => setLoadError('Failed to load users'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  async function handleAdd(payload) {
    setSaving(true); setActionError('')
    try {
      await client.post('/users', payload)
      setShowAdd(false); load()
    } catch (err) {
      setActionError(err.response?.data?.detail ?? 'Failed to create user')
    } finally { setSaving(false) }
  }

  async function handleEdit(payload) {
    setSaving(true); setActionError('')
    try {
      await client.patch(`/users/${editing.id}`, payload)
      setEditing(null); load(); onReload()
      // Refresh the current user in AuthContext so persona changes are reflected
      // immediately in the sidebar and Chat page without requiring a logout.
      onRefreshCurrentUser()
    } catch (err) {
      setActionError(err.response?.data?.detail ?? 'Failed to update user')
    } finally { setSaving(false) }
  }

  async function handleDelete() {
    setSaving(true); setActionError('')
    try {
      await client.delete(`/users/${deleting.id}`)
      setDeleting(null); load()
    } catch (err) {
      setActionError(err.response?.data?.detail ?? 'Failed to delete user')
    } finally { setSaving(false) }
  }

  if (loading)   return <p style={{ color: 'var(--muted)' }}>Loading…</p>
  if (loadError) return <p style={{ color: 'var(--red)' }}>{loadError}</p>

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Button onClick={() => { setShowAdd(true); setActionError('') }}>+ Add user</Button>
      </div>

      <div style={styles.card}>
        {users.length === 0 && (
          <p style={{ color: 'var(--muted)', padding: '8px 0' }}>No users found.</p>
        )}
        {users.map((u, i) => (
          <div
            key={u.id}
            style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '12px 0',
              borderBottom: i < users.length - 1 ? '1px solid var(--border)' : 'none',
              flexWrap: 'wrap',
            }}
          >
            {/* Initials avatar */}
            <div style={styles.avatar}>
              {u.username[0].toUpperCase()}
            </div>

            {/* Name & email */}
            <div style={{ flex: 1, minWidth: 100 }}>
              <p style={{ fontWeight: 600, color: u.is_active ? 'var(--white)' : 'var(--muted)', fontSize: 14 }}>
                {u.username}
                {u.id === currentUser.id && (
                  <span style={{ fontSize: 11, color: 'var(--cyan)', marginLeft: 6 }}>(you)</span>
                )}
              </p>
              {u.email && (
                <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{u.email}</p>
              )}
            </div>

            {/* Badges */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <RoleBadge role={u.role} />
              {u.persona && (
                <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99, color: '#8BE9FD', background: '#8BE9FD20' }}>
                  {u.persona.name}
                </span>
              )}
              <ActiveBadge active={u.is_active} />
            </div>

            {/* Actions */}
            <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
              <button
                style={styles.iconBtn}
                onClick={() => { setEditing(u); setActionError('') }}
                title="Edit user"
              >✎</button>
              {u.id !== currentUser.id && (
                <button
                  style={{ ...styles.iconBtn, color: 'var(--red)' }}
                  onClick={() => { setDeleting(u); setActionError('') }}
                  title="Delete user"
                >✕</button>
              )}
            </div>
          </div>
        ))}
      </div>

      {showAdd && (
        <Modal title="Add user" onClose={() => setShowAdd(false)}>
          {actionError && <p style={styles.errorMsg}>{actionError}</p>}
          <UserForm
            roles={roles}
            personas={personas}
            onSave={handleAdd}
            onCancel={() => setShowAdd(false)}
            saving={saving}
          />
        </Modal>
      )}

      {editing && (
        <Modal title={`Edit — ${editing.username}`} onClose={() => setEditing(null)}>
          {actionError && <p style={styles.errorMsg}>{actionError}</p>}
          <UserForm
            initial={editing}
            roles={roles}
            personas={personas}
            onSave={handleEdit}
            onCancel={() => setEditing(null)}
            saving={saving}
          />
        </Modal>
      )}

      {deleting && (
        <Modal title="Delete user?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            Permanently delete <strong>{deleting.username}</strong>?
          </p>
          <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 16 }}>
            Consider deactivating the account instead to preserve history.
          </p>
          {actionError && <p style={styles.errorMsg}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? 'Deleting…' : 'Delete user'}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ─── Persona form ─────────────────────────────────────────────────────────────

function PersonaForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState({
    name:              initial?.name              ?? '',
    description:       initial?.description       ?? '',
    system_prompt:     initial?.system_prompt     ?? '',
    data_access_level: initial?.data_access_level ?? 'full',
    can_modify_data:   initial?.can_modify_data   ?? false,
    tone_notes:        initial?.tone_notes        ?? '',
  })
  const [error, setError] = useState('')

  function set(field) {
    return (e) => {
      const val = e.target.type === 'checkbox' ? e.target.checked : e.target.value
      setForm((f) => ({ ...f, [field]: val }))
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!form.name.trim()) { setError('Name is required'); return }
    setError('')
    onSave({
      name:              form.name.trim(),
      description:       form.description    || null,
      system_prompt:     form.system_prompt  || null,
      data_access_level: form.data_access_level,
      can_modify_data:   form.can_modify_data,
      tone_notes:        form.tone_notes     || null,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <FormField label="Name *">
        <input style={inputStyle} value={form.name} onChange={set('name')} required autoFocus />
      </FormField>

      <FormField label="Description" hint="Shown in user management UI">
        <input
          style={inputStyle}
          value={form.description}
          onChange={set('description')}
          placeholder="e.g. Read-only view for family members"
        />
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Data access level">
          <select style={selectStyle} value={form.data_access_level} onChange={set('data_access_level')}>
            <option value="full">Full — all data</option>
            <option value="summary">Summary — aggregated only</option>
            <option value="readonly">Read-only — no sensitive data</option>
          </select>
        </FormField>

        <FormField label="Permissions">
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: 'var(--white)', fontSize: 14, paddingTop: 10 }}>
            <input
              type="checkbox"
              checked={form.can_modify_data}
              onChange={set('can_modify_data')}
              style={{ accentColor: 'var(--green)', width: 15, height: 15 }}
            />
            Can modify data
          </label>
        </FormField>
      </div>

      <FormField label="System prompt" hint="Instructions sent to the AI assistant">
        <textarea
          style={{ ...inputStyle, resize: 'vertical', minHeight: 80 }}
          value={form.system_prompt}
          onChange={set('system_prompt')}
          placeholder="You are a helpful financial assistant…"
        />
      </FormField>

      <FormField label="Tone notes" hint="Additional guidance on communication style">
        <input
          style={inputStyle}
          value={form.tone_notes}
          onChange={set('tone_notes')}
          placeholder="e.g. Be concise and avoid jargon"
        />
      </FormField>

      {error && <p style={styles.errorMsg}>{error}</p>}
      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save changes' : 'Create persona'}
        </Button>
      </div>
    </form>
  )
}

// ─── Persona card ─────────────────────────────────────────────────────────────

function PersonaCard({ persona, onEdit, onDelete }) {
  const accessColor = ACCESS_COLORS[persona.data_access_level] || 'var(--muted)'

  return (
    <div style={{ ...styles.card, borderTop: `3px solid ${accessColor}` }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
            <p style={{ fontSize: 15, fontWeight: 600, color: 'var(--white)' }}>{persona.name}</p>
            {persona.is_system && (
              <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 7px', borderRadius: 99, color: 'var(--muted)', background: 'var(--border)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                system
              </span>
            )}
          </div>
          {persona.description && (
            <p style={{ fontSize: 13, color: 'var(--muted)' }}>{persona.description}</p>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
          <button style={styles.iconBtn} onClick={onEdit} title="Edit persona">✎</button>
          {!persona.is_system && (
            <button style={{ ...styles.iconBtn, color: 'var(--red)' }} onClick={onDelete} title="Delete persona">✕</button>
          )}
        </div>
      </div>

      {/* Capability badges */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <AccessBadge level={persona.data_access_level} />
        <span style={{
          fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 99,
          color:      persona.can_modify_data ? '#50FA7B' : '#6272A4',    // green : muted
          background: persona.can_modify_data ? '#50FA7B20' : '#44475A',  // green alpha : border
        }}>
          {persona.can_modify_data ? 'Can modify' : 'Read only'}
        </span>
      </div>

      {/* System prompt preview */}
      {persona.system_prompt && (
        <p style={{
          fontSize: 12, color: 'var(--muted)', lineHeight: 1.5,
          padding: '8px 10px', background: 'var(--bg)',
          borderRadius: 'var(--radius)', fontFamily: 'monospace',
          maxHeight: 72, overflow: 'hidden',
          display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
        }}>
          {persona.system_prompt}
        </p>
      )}

      {/* Tone notes */}
      {persona.tone_notes && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8, fontStyle: 'italic' }}>
          "{persona.tone_notes}"
        </p>
      )}
    </div>
  )
}

// ─── Personas tab ─────────────────────────────────────────────────────────────

function PersonasTab({ personas, onReload }) {
  const [showAdd, setShowAdd]   = useState(false)
  const [editing, setEditing]   = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [saving, setSaving]     = useState(false)
  const [actionError, setActionError] = useState('')

  async function handleAdd(payload) {
    setSaving(true); setActionError('')
    try {
      await client.post('/users/personas', payload)
      setShowAdd(false); onReload()
    } catch (err) {
      setActionError(err.response?.data?.detail ?? 'Failed to create persona')
    } finally { setSaving(false) }
  }

  async function handleEdit(payload) {
    setSaving(true); setActionError('')
    try {
      await client.patch(`/users/personas/${editing.id}`, payload)
      setEditing(null); onReload()
    } catch (err) {
      setActionError(err.response?.data?.detail ?? 'Failed to update persona')
    } finally { setSaving(false) }
  }

  async function handleDelete() {
    setSaving(true); setActionError('')
    try {
      await client.delete(`/users/personas/${deleting.id}`)
      setDeleting(null); onReload()
    } catch (err) {
      setActionError(err.response?.data?.detail ?? 'Failed to delete persona')
    } finally { setSaving(false) }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Button onClick={() => { setShowAdd(true); setActionError('') }}>+ Add persona</Button>
      </div>

      <div style={styles.personaGrid}>
        {personas.map((p) => (
          <PersonaCard
            key={p.id}
            persona={p}
            onEdit={() => { setEditing(p); setActionError('') }}
            onDelete={() => { setDeleting(p); setActionError('') }}
          />
        ))}
      </div>

      {showAdd && (
        <Modal title="New persona" onClose={() => setShowAdd(false)} width={560}>
          {actionError && <p style={styles.errorMsg}>{actionError}</p>}
          <PersonaForm onSave={handleAdd} onCancel={() => setShowAdd(false)} saving={saving} />
        </Modal>
      )}

      {editing && (
        <Modal title={`Edit — ${editing.name}`} onClose={() => setEditing(null)} width={560}>
          {actionError && <p style={styles.errorMsg}>{actionError}</p>}
          <PersonaForm
            initial={editing}
            onSave={handleEdit}
            onCancel={() => setEditing(null)}
            saving={saving}
          />
        </Modal>
      )}

      {deleting && (
        <Modal title="Delete persona?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            Delete <strong>{deleting.name}</strong>?
          </p>
          <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 16 }}>
            Any users assigned this persona will have it removed.
          </p>
          {actionError && <p style={styles.errorMsg}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? 'Deleting…' : 'Delete persona'}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ─── Categories tab ───────────────────────────────────────────────────────────

function CategoriesTab() {
  const [categories, setCategories]   = useState([])
  const [loading, setLoading]         = useState(true)
  const [loadError, setLoadError]     = useState('')
  const [newName, setNewName]         = useState('')
  const [adding, setAdding]           = useState(false)
  const [addError, setAddError]       = useState('')
  // Map of category id → current rename input value (only populated while editing)
  const [renaming, setRenaming]       = useState({})   // { [id]: string }
  const [renameSaving, setRenameSaving] = useState({}) // { [id]: bool }
  const [renameError, setRenameError] = useState({})   // { [id]: string }
  const [deleting, setDeleting]       = useState(null) // category object
  const [deleteError, setDeleteError] = useState('')
  const [deleteSaving, setDeleteSaving] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    client.get('/categories')
      .then((r) => setCategories(r.data))
      .catch(() => setLoadError('Failed to load categories'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  // ── Add ────────────────────────────────────────────────────────────────────

  async function handleAdd(e) {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setAdding(true); setAddError('')
    try {
      await client.post('/categories', { name })
      setNewName('')
      load()
    } catch (err) {
      setAddError(err.response?.data?.detail ?? 'Failed to add category')
    } finally { setAdding(false) }
  }

  // ── Rename ─────────────────────────────────────────────────────────────────

  function startRename(cat) {
    setRenaming((prev) => ({ ...prev, [cat.id]: cat.name }))
    setRenameError((prev) => ({ ...prev, [cat.id]: '' }))
  }

  function cancelRename(id) {
    setRenaming((prev) => {
      const next = { ...prev }; delete next[id]; return next
    })
  }

  async function commitRename(cat) {
    const name = (renaming[cat.id] ?? '').trim()
    if (!name || name === cat.name) { cancelRename(cat.id); return }
    setRenameSaving((prev) => ({ ...prev, [cat.id]: true }))
    setRenameError((prev) => ({ ...prev, [cat.id]: '' }))
    try {
      await client.patch(`/categories/${cat.id}`, { name })
      cancelRename(cat.id)
      load()
    } catch (err) {
      setRenameError((prev) => ({ ...prev, [cat.id]: err.response?.data?.detail ?? 'Failed to rename' }))
    } finally {
      setRenameSaving((prev) => ({ ...prev, [cat.id]: false }))
    }
  }

  // ── Delete ─────────────────────────────────────────────────────────────────

  async function handleDelete() {
    if (!deleting) return
    setDeleteSaving(true); setDeleteError('')
    try {
      await client.delete(`/categories/${deleting.id}`)
      setDeleting(null)
      load()
    } catch (err) {
      setDeleteError(err.response?.data?.detail ?? 'Failed to delete category')
    } finally { setDeleteSaving(false) }
  }

  if (loading)   return <p style={{ color: 'var(--muted)' }}>Loading…</p>
  if (loadError) return <p style={{ color: 'var(--red)' }}>{loadError}</p>

  const userCategories   = categories.filter((c) => !c.is_system)
  const systemCategories = categories.filter((c) =>  c.is_system)

  return (
    <div style={{ maxWidth: 640 }}>
      {/* Add new category */}
      <div style={styles.card}>
        <p style={styles.sectionTitle}>Add Category</p>
        <form onSubmit={handleAdd} style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
          <div style={{ flex: 1 }}>
            <FormField label="Category name">
              <input
                style={inputStyle}
                value={newName}
                onChange={(e) => { setNewName(e.target.value); setAddError('') }}
                placeholder="e.g. Pet Supplies"
                autoComplete="off"
              />
            </FormField>
          </div>
          <div style={{ paddingBottom: 2 }}>
            <Button type="submit" disabled={adding || !newName.trim()}>
              {adding ? 'Adding…' : 'Add'}
            </Button>
          </div>
        </form>
        {addError && <p style={{ ...styles.errorMsg, marginTop: 8 }}>{addError}</p>}
      </div>

      {/* Custom categories */}
      <div style={{ ...styles.card, marginTop: 16 }}>
        <p style={styles.sectionTitle}>Custom Categories</p>
        {userCategories.length === 0 && (
          <p style={{ color: 'var(--muted)', fontSize: 13 }}>
            No custom categories yet. Add one above.
          </p>
        )}
        {userCategories.map((cat, i) => {
          const isRenaming = cat.id in renaming
          return (
            <div
              key={cat.id}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 0',
                borderBottom: i < userCategories.length - 1 ? '1px solid var(--border)' : 'none',
              }}
            >
              {isRenaming ? (
                /* Inline rename input */
                <div style={{ flex: 1, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <input
                    style={{ ...inputStyle, flex: 1, minWidth: 140 }}
                    value={renaming[cat.id]}
                    onChange={(e) => setRenaming((prev) => ({ ...prev, [cat.id]: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') { e.preventDefault(); commitRename(cat) }
                      if (e.key === 'Escape') cancelRename(cat.id)
                    }}
                    autoFocus
                  />
                  <Button size="sm" onClick={() => commitRename(cat)} disabled={renameSaving[cat.id]}>
                    {renameSaving[cat.id] ? '…' : 'Save'}
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => cancelRename(cat.id)}>
                    Cancel
                  </Button>
                  {renameError[cat.id] && (
                    <span style={{ color: 'var(--red)', fontSize: 12 }}>{renameError[cat.id]}</span>
                  )}
                </div>
              ) : (
                /* Display row */
                <>
                  <span style={{ flex: 1, fontSize: 14, color: 'var(--white)' }}>{cat.name}</span>
                  <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                    <button
                      style={styles.iconBtn}
                      onClick={() => startRename(cat)}
                      title="Rename"
                    >✎</button>
                    <button
                      style={{ ...styles.iconBtn, color: 'var(--red)' }}
                      onClick={() => { setDeleting(cat); setDeleteError('') }}
                      title="Delete"
                    >✕</button>
                  </div>
                </>
              )}
            </div>
          )
        })}
      </div>

      {/* System categories — read-only reference */}
      <div style={{ ...styles.card, marginTop: 16 }}>
        <p style={styles.sectionTitle}>System Categories</p>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>
          Built-in categories shared across all users. These cannot be renamed or deleted.
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {systemCategories.map((cat) => (
            <span
              key={cat.id}
              style={{
                fontSize: 12, padding: '4px 10px', borderRadius: 99,
                background: 'var(--border)', color: 'var(--muted)',
              }}
            >
              {cat.name}
            </span>
          ))}
        </div>
      </div>

      {/* Delete confirmation modal */}
      {deleting && (
        <Modal title="Delete category?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            Delete <strong>{deleting.name}</strong>?
          </p>
          <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 16 }}>
            Any transactions, budgets, or recurring entries using this category will be uncategorised.
            Your transaction history is preserved — nothing is deleted.
          </p>
          {deleteError && <p style={styles.errorMsg}>{deleteError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={deleteSaving}>
              {deleteSaving ? 'Deleting…' : 'Delete category'}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ─── General tab ──────────────────────────────────────────────────────────────

const CURRENCIES = ['USD','EUR','GBP','CAD','AUD','NZD','CHF','JPY','CNY','INR','BRL','MXN','ZAR','SGD','HKD','NOK','SEK','DKK','PLN']

const TIMEZONES = [
  'UTC',
  'America/New_York','America/Chicago','America/Denver','America/Los_Angeles',
  'America/Vancouver','America/Toronto','America/Sao_Paulo',
  'Europe/London','Europe/Paris','Europe/Berlin','Europe/Madrid','Europe/Rome',
  'Europe/Amsterdam','Europe/Zurich','Europe/Stockholm','Europe/Warsaw',
  'Asia/Dubai','Asia/Karachi','Asia/Kolkata','Asia/Singapore','Asia/Tokyo',
  'Asia/Hong_Kong','Asia/Seoul',
  'Australia/Sydney','Australia/Melbourne',
  'Pacific/Auckland',
]

function GeneralTab({ roles }) {
  const [settings, setSettings] = useState(() => ({
    app_name: 'Tally',
    currency: 'USD',
    timezone: 'UTC',
    ...loadLocalSettings(),
  }))
  const [prefSaved, setPrefSaved] = useState(false)

  // Per-role editing state
  const [roleEdits,  setRoleEdits]  = useState(() => Object.fromEntries(roles.map((r) => [r.id, r.display_name])))
  const [roleSaving, setRoleSaving] = useState({})
  const [roleError,  setRoleError]  = useState({})
  const [roleSaved,  setRoleSaved]  = useState({})

  function set(field) {
    return (e) => { setSettings((s) => ({ ...s, [field]: e.target.value })); setPrefSaved(false) }
  }

  function handleSavePrefs(e) {
    e.preventDefault()
    saveLocalSettings(settings)
    // Notify the CurrencyProvider (and any other listeners) that settings changed
    window.dispatchEvent(new Event('tally:settings-changed'))
    setPrefSaved(true)
    setTimeout(() => setPrefSaved(false), 2500)
  }

  async function handleSaveRole(role) {
    const newName = roleEdits[role.id]?.trim()
    if (!newName) return
    setRoleSaving((s) => ({ ...s, [role.id]: true }))
    setRoleError( (s) => ({ ...s, [role.id]: '' }))
    setRoleSaved( (s) => ({ ...s, [role.id]: false }))
    try {
      await client.patch(`/users/roles/${role.id}`, { display_name: newName })
      setRoleSaved((s) => ({ ...s, [role.id]: true }))
      setTimeout(() => setRoleSaved((s) => ({ ...s, [role.id]: false })), 2500)
    } catch (err) {
      setRoleError((s) => ({ ...s, [role.id]: err.response?.data?.detail ?? 'Failed to save' }))
    } finally {
      setRoleSaving((s) => ({ ...s, [role.id]: false }))
    }
  }

  return (
    <div style={{ maxWidth: 640 }}>
      {/* App preferences */}
      <div style={styles.card}>
        <p style={styles.sectionTitle}>App Preferences</p>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
          Stored locally in your browser. Each device maintains its own preferences.
        </p>
        <form onSubmit={handleSavePrefs}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 }}>
            <FormField label="App name">
              <input style={inputStyle} value={settings.app_name} onChange={set('app_name')} />
            </FormField>
            <FormField label="Default currency">
              <select style={selectStyle} value={settings.currency} onChange={set('currency')}>
                {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </FormField>
          </div>
          <FormField label="Default timezone">
            <select style={selectStyle} value={settings.timezone} onChange={set('timezone')}>
              {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
          </FormField>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 }}>
            <Button type="submit">Save preferences</Button>
            {prefSaved && <span style={{ color: 'var(--green)', fontSize: 13 }}>Saved ✓</span>}
          </div>
        </form>
      </div>

      {/* Role display names */}
      <div style={{ ...styles.card, marginTop: 16 }}>
        <p style={styles.sectionTitle}>Role Display Names</p>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
          Rename how roles appear in the UI. The internal slugs ("owner", "viewer") are used
          for access control and never change.
        </p>
        {roles.map((r) => (
          <div key={r.id} style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 160 }}>
                <FormField label={`"${r.name}" role display name`}>
                  <input
                    style={inputStyle}
                    value={roleEdits[r.id] ?? r.display_name}
                    onChange={(e) => setRoleEdits((prev) => ({ ...prev, [r.id]: e.target.value }))}
                  />
                </FormField>
              </div>
              <div style={{ paddingBottom: 2 }}>
                <Button size="sm" onClick={() => handleSaveRole(r)} disabled={roleSaving[r.id]}>
                  {roleSaving[r.id] ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </div>
            {roleError[r.id] && (
              <p style={{ ...styles.errorMsg, marginTop: 4 }}>{roleError[r.id]}</p>
            )}
            {roleSaved[r.id] && (
              <p style={{ color: 'var(--green)', fontSize: 13, marginTop: 4 }}>Saved ✓</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Settings() {
  const { user, isOwner, refreshUser } = useAuth()

  const [tab, setTab]           = useState('profile')
  const [roles, setRoles]       = useState([])
  const [personas, setPersonas] = useState([])
  const [loading, setLoading]   = useState(true)

  const loadRolesAndPersonas = useCallback(() => {
    Promise.all([
      client.get('/users/roles'),
      client.get('/users/personas'),
    ]).then(([r, p]) => {
      setRoles(r.data)
      setPersonas(p.data)
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadRolesAndPersonas() }, [loadRolesAndPersonas])

  const tabs = [
    { id: 'profile', label: 'Profile' },
    ...(isOwner ? [
      { id: 'users',       label: 'Users' },
      { id: 'personas',    label: 'Personas' },
      { id: 'categories',  label: 'Categories' },
      { id: 'general',     label: 'General' },
    ] : []),
  ]

  if (loading) return <p style={{ color: 'var(--muted)' }}>Loading…</p>

  return (
    <div>
      <div style={styles.pageHeader}>
        <h1 style={styles.pageTitle}>Settings</h1>
      </div>

      <TabNav tabs={tabs} active={tab} onChange={setTab} />

      {tab === 'profile'  && (
        <ProfileTab user={user} />
      )}
      {tab === 'users'    && isOwner && (
        <UsersTab
          currentUser={user}
          roles={roles}
          personas={personas}
          onReload={loadRolesAndPersonas}
          onRefreshCurrentUser={refreshUser}
        />
      )}
      {tab === 'personas' && isOwner && (
        <PersonasTab
          personas={personas}
          onReload={loadRolesAndPersonas}
        />
      )}
      {tab === 'categories' && isOwner && (
        <CategoriesTab />
      )}
      {tab === 'general'  && isOwner && (
        <GeneralTab roles={roles} />
      )}
    </div>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = {
  pageHeader: {
    display: 'flex', alignItems: 'center',
    justifyContent: 'space-between', marginBottom: 20,
  },
  pageTitle: { fontSize: 24, fontWeight: 700, color: 'var(--white)' },

  card: {
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', padding: '18px 20px',
  },
  sectionTitle: { fontSize: 15, fontWeight: 600, color: 'var(--white)', marginBottom: 14 },

  infoLabel: { fontSize: 13, color: 'var(--muted)', width: 130, flexShrink: 0 },
  infoValue: { fontSize: 14, color: 'var(--white)' },

  avatar: {
    width: 36, height: 36, borderRadius: '50%',
    background: 'var(--border)', color: 'var(--white)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontWeight: 700, fontSize: 14, flexShrink: 0,
  },

  iconBtn: {
    background: 'none', border: 'none', color: 'var(--muted)',
    fontSize: 15, padding: '3px 5px', borderRadius: 'var(--radius)', cursor: 'pointer',
  },

  personaGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
    gap: 16,
  },

  errorMsg:   { color: 'var(--red)',   fontSize: 13, marginBottom: 12 },
  successMsg: { color: 'var(--green)', fontSize: 13, marginBottom: 12 },
}
