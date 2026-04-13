# AI Coach

The AI Coach is a financial coaching chat interface built into Tally. It connects to the Claude API and gives you a conversational way to ask questions about your finances, get coaching on spending habits, and (depending on configuration) make changes to your data.

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

**Note:** Even with modify access enabled, the AI operates within Tally's standard permission model. It cannot create owner accounts, delete accounts, or perform destructive operations.

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

## Privacy Note

The AI Coach sends your financial data (filtered by the persona's data access level) to the Claude API (Anthropic) as part of each conversation. This data leaves your server. If you are concerned about privacy, use a persona with a lower data access level or the readonly level.

The AI does not store your conversation history between sessions.

---

## Streaming Responses

AI responses stream in real time as the AI generates them. You will see text appear progressively rather than waiting for the full response to complete before it is displayed.

---

## Related

- [Settings](settings.md) — managing personas and assigning them to users
- [Accounts](accounts.md) — account data the AI can access
- [Transactions](transactions.md) — transaction data the AI can access
