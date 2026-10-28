# ERPNext Assistant

A read-only AI assistant that lives inside your ERPNext desk. Bring your own Anthropic API key, open the Assistant page, and ask questions about your own data in plain language:

- "Which sales invoices are overdue this month, and for how much?"
- "What's our total purchase volume with each supplier this year?"
- "Show me the items below their reorder level."
- "What fields does the Delivery Note doctype have?"

The assistant looks the answers up live from your database, under your permissions, and shows its work.

## The security model, up front

Most "AI + ERP" tools fail on trust. This one is built around three hard guarantees:

1. **Read only, by construction.** The assistant has exactly five abilities: list doctypes, read a doctype's schema, list documents, fetch one document, and count/sum documents. There is no tool that creates, edits, submits, cancels, deletes, or runs SQL. Its write capability is not "restricted by instructions" — the code paths do not exist.
2. **Your permissions are the boundary.** Every lookup runs through Frappe's own permission-checked APIs as the logged-in user. The assistant can never show a user anything ERPNext itself would not show them. A sales user asking about payroll gets a permission message, not payroll.
3. **Your key, your data, server side only.** The Anthropic API key is stored encrypted on your site and used only from the server. It is never sent to a browser. The only data that leaves your server is the content of records the assistant reads to answer a question, sent to the Anthropic API under your own key.

On top of that, admins get a **blocked doctypes** list (things the assistant can never read regardless of permissions), and credential doctypes (User, API keys, OAuth records, email accounts, the email queue) are hard-blocked in code. Password-type fields are stripped from every result, field-level permissions (permlevels) are honored on reads, filters and aggregates, and a per-user hourly question cap keeps any one user from running up the site's Anthropic bill.

## Requirements

- Frappe Framework v15 or v16, with or without ERPNext
- An [Anthropic API key](https://console.anthropic.com) (pay as you go; instructions are built into the settings page)
- The `anthropic` Python package on your bench (installed automatically with the app)

## Installation

### Bench (self-hosted)

From your bench directory:

```bash
bench get-app https://github.com/animusdigitalco/erpnext-assistant
bench --site yoursite.example.com install-app erpnext_assistant
bench --site yoursite.example.com migrate
bench restart
```

Note that the app name is `erpnext_assistant` (underscore) even though the repository is `erpnext-assistant`.

If dependencies did not install automatically on an older bench:

```bash
bench pip install anthropic
bench restart
```

### Frappe Cloud

1. Open your bench group, go to **Apps**, and choose **Add App**.
2. Pick **From GitHub** and paste `https://github.com/animusdigitalco/erpnext-assistant`.
3. Deploy the bench, then install **ERPNext Assistant** on your site from the site's Apps tab.

### Verify

```bash
bench --site yoursite.example.com list-apps
```

You should see `erpnext_assistant` in the list.

## Setup

1. In the desk, search for **Assistant Settings**.
2. Follow the on-page instructions to create an Anthropic API key (console.anthropic.com → Billing → API Keys → Create Key) and paste it in.
3. Pick a model. `claude-opus-5` gives the best answers; `claude-haiku-4-5` is the budget option.
4. Choose who can use it under **Allowed Roles** (empty means System Managers only).
5. Add anything sensitive to **Blocked DocTypes** (one per line), e.g. `Salary Slip`.
6. Tick **Enabled** and save.
7. Search **Assistant** in the desk to open the chat page.

## Settings reference

| Setting | Default | What it controls |
| --- | --- | --- |
| Enabled | off | Master switch; nothing works while off |
| Anthropic API Key | — | Stored encrypted, used server side only |
| Model | claude-opus-5 | Which Claude model answers |
| Allowed Roles | empty | Who can open the chat (System Managers always can) |
| Blocked DocTypes | empty | Doctypes the assistant can never read, for anyone |
| Max Results Per Lookup | 20 | Rows one lookup may return (hard cap 100) |
| Max Lookups Per Question | 15 | Data lookups allowed per question |
| Max Questions Per User Per Hour | 30 | Spending brake per user (0 disables it) |
| Extra Instructions | — | Site-specific context added to every chat |
| Save Conversations | on | Store each user's chats (each user only sees their own) |

## Troubleshooting

- **Answers cut off with a gateway error on hard questions:** a question that needs many lookups on a large model can outlast the default web worker timeout. Raise it with `bench config http_timeout 300 && bench setup supervisor && bench restart` (on Frappe Cloud, set the HTTP timeout in the bench group settings).
- **"The anthropic Python package is not installed":** run `bench pip install anthropic && bench restart`.
- **A user who should have access gets a permission error:** check Allowed Roles in Assistant Settings, and remember an empty list means System Managers only.

## What it costs

Answers are billed to your Anthropic account per token. A typical question that reads a handful of records costs a few cents on Opus and a fraction of a cent on Haiku. Each answer in the chat shows the tokens it used. The per-question lookup cap keeps a runaway question from becoming a runaway bill.

## What it does not do

- It does not write anything. No creating, editing, submitting, cancelling, deleting, no exceptions.
- It does not answer general questions. Ask it about the weather and it will point you back to your data.
- It does not bypass permissions, and a role in Allowed Roles only grants access to the chat, never to extra data.
- It does not phone home anywhere except the Anthropic API, with your key.

## How it works

- **Assistant Settings** (Single doctype) holds the key, model, access and scope controls.
- The **Assistant** desk page posts your question to a whitelisted server endpoint.
- The server runs an agentic loop against the Anthropic Messages API with five read-only tools. Each tool call is permission-checked via `frappe.get_list` / `frappe.get_doc` as the asking user, filters and fields are validated against the doctype's real schema, and Password fields are stripped.
- Tool progress streams back to the chat over Frappe's realtime socket, and the final answer renders as markdown.
- Document content is treated as data: the system prompt instructs the model to ignore instruction-like text inside records, and since every tool is read-only and permission-scoped, a hostile string inside a document has nothing to exfiltrate and nothing to change.

## Uninstall

```bash
bench --site yoursite.example.com uninstall-app erpnext_assistant
```

This removes the settings (including the stored key) and saved conversations.

## License

MIT
