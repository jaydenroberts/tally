# AI Coach

The AI Coach is a financial coaching chat interface built into Tally. It is entirely optional: if you don't configure a provider, the rest of Tally works exactly the same, and no AI-related network request is ever made. When you do configure one — Anthropic (Claude), OpenAI, or a local OpenAI-compatible endpoint such as Ollama — it gives you a conversational way to ask questions about your finances, get coaching on spending habits, and (depending on configuration) make changes to your data.

The AI Coach's behaviour is controlled by **personas** — configurable profiles that determine the AI's tone, what financial data it can see, and whether it can modify your data.

---

## Accessing the AI Coach

Click **AI Coach** in the sidebar navigation. The chat interface opens as a full page.

The AI Coach is available to all users, but the persona assigned to your account determines what it can do. Owners assign personas to users in **Settings → Users**.

---

## Personas

A persona defines how the AI behaves for a specific user. Each persona has:

- **Name** — shown in the UI when the persona is active
- **Description** — a plain-language summary of what this persona does
- **System prompt** — the instruction set given to the AI before your conversation starts (configured by the owner in Settings)
- **Data access level** — what financial data the AI can see
- **Can modify data** — whether the AI can make changes to your Tally data

---

## Data Access Levels

| Level | What the AI can see |
|-------|---------------------|
| Full | Complete transaction history, all account balances, all debts and savings goals |
| Summary | Totals and summaries only — no individual transaction details |
| Readonly | General coaching only — no financial data from your Tally instance |

The data access level is set per persona by the owner. Users cannot change their own data access level.

---

## Modifying Data

If a persona has **can modify data** enabled, the AI can make changes to your Tally data through the conversation — for example, logging a payment, recording a contribution, or updating a category.

If **can modify data** is disabled, the AI can only read and discuss your data. It cannot make any changes.

**Note:** Even with modify access enabled, the AI operates within Tally's standard permission model. It cannot create owner accounts, delete accounts, or perform destructive operations. A **Summary** or **Readonly** persona is never given data-changing tools, regardless of the modify setting — write access applies only to personas that can see the underlying data.

---

## Built-in Personas

Tally ships with two system personas:

| Persona | Access level | Can modify | Description |
|---------|-------------|------------|-------------|
| Analyst | Full | Yes | Full access to your financial data; can make changes on your behalf |
| Family | Full | No | Read-only; suitable for shared household use where you want coaching without write access |

System personas cannot be deleted. Their display names can be edited in **Settings → Personas**.

---

## Custom Personas

Owners can create additional personas in **Settings → Personas**. This lets you configure the AI's behaviour for specific users or use cases — for example, a persona for a partner with limited data access, or a persona focused on a specific financial goal.

See [Settings](settings.md) for instructions on creating and managing personas.

---

## What the AI Can and Cannot Do

**The AI can:**
- Answer questions about your spending, balances, and trends (subject to data access level)
- Provide general financial coaching and suggestions
- Explain your budget progress and savings trajectory
- Make data modifications if the persona allows it (log payments, record contributions, etc.)

**The AI cannot:**
- Access any external financial services or banks
- See data from outside your Tally instance
- Override Tally's security model or access controls
- Guarantee accuracy — always verify important financial decisions independently

---

## Privacy and Data Storage

Two separate questions apply here: where your conversation is **sent** while it's happening, and where it's **stored** afterwards. They have different answers.

### Where Your Data Is Sent

The AI Coach sends your financial data (filtered by the persona's data access level) to whichever provider you've configured with `AI_PROVIDER`:

| Provider | Where your data goes |
|----------|----------------------|
| Anthropic (Claude) | Sent to Anthropic's API as part of each conversation, under Anthropic's terms |
| OpenAI | Sent to OpenAI's API as part of each conversation, under OpenAI's terms |
| Ollama (or another local OpenAI-compatible endpoint) | Stays on your own network — nothing leaves your server |

If no API key is available — neither `AI_API_KEY` nor `ANTHROPIC_API_KEY` — no AI request is ever made and nothing leaves your machine. Note that this is governed by the key alone: `AI_PROVIDER` defaults to `anthropic`, so leaving it unset does **not** disable the feature. See below for what that looks like in the app.

If you're concerned about privacy but still want AI coaching, use a persona with a lower data access level (**Summary** or **Readonly**), or point `AI_PROVIDER` at a local Ollama instance so nothing leaves your server.

### Where Your Conversations Are Stored

This is a separate question from where your data is sent, and the answer doesn't depend on which provider you use. Every AI Coach conversation — including with Ollama — is saved in Tally's own SQLite database, on your own server. Conversations reload automatically when you return: use the session sidebar to resume a past conversation, start a new one, or delete one you no longer want.

There is no automatic expiry or cleanup — a conversation is kept until you delete it yourself. `CHAT_HISTORY_TURNS` doesn't change this: it only controls how many recent turns are replayed to the AI as context on each request, not what's kept in the database.

### If You Haven't Configured a Provider

**AI Coach** always appears in the sidebar, whether or not you've set `AI_PROVIDER` or an API key — Tally doesn't hide it based on configuration. If you open it and send a message with no provider configured, you'll get a generic error saying the assistant couldn't finish responding. That's expected: it means no provider is set up, not that something is broken. If you've deliberately left AI turned off, you can ignore it — the rest of Tally is unaffected.

---

## Streaming Responses

AI responses stream in real time as the AI generates them. You will see text appear progressively rather than waiting for the full response to complete before it is displayed.

---

## Related

- [Settings](settings.md) — managing personas and assigning them to users
- [Accounts](accounts.md) — account data the AI can access
- [Transactions](transactions.md) — transaction data the AI can access
