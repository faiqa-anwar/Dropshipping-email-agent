# Dropshipping Multi-Email Handling Agent (LangGraph)

A working LangGraph scaffold that: classifies inbound emails, grounds
decisions in real source data (Shopify order + Excel refund policy),
auto-replies / auto-refunds when safe, and escalates to a human via
Slack using LangGraph's `interrupt()` — pausing and resuming exactly
where it left off.

## Run it

```bash
pip install -r requirements.txt
python run_demo.py
```

No API keys required — it runs on mock data by default. Set
`OPENAI_API_KEY` in your environment and it automatically switches
`app/integrations/llm.py` to a real model instead of the keyword-based
mock classifier.

## How it's structured

```
agent_app/
  graph/
    state.py     - EmailState TypedDict, shared across all nodes
    nodes.py     - identify_sender_type, classify_email, fetch_context, decide,
                   draft_reply, escalate_to_human, send_and_log,
                   classify_supplier_email, handle_supplier_email,
                   classify_carrier_email, handle_carrier_email
    graph.py     - wires nodes + conditional edges + checkpointer
  integrations/
    shopify_client.py    - mock order lookup (swap for real Shopify Admin API)
    inventory_store.py   - mock stock/cost/tracking store (supplier + carrier write here)
    policy_source.py     - reads app/mock_data/refund_policy.xlsx for
                            auditable, citable policy rules
    llm.py                - real LLM (OpenRouter or OpenAI) if a key is set,
                            else rule-based mock
    notify_clients.py     - mock Slack + email + audit log
  mock_data/
    refund_policy.xlsx    - the actual "source" the agent cites in its reasoning
run_demo.py     - simulates 10 emails across both inboxes (customer, supplier,
                  carrier, spam, duplicate-refund, angry/legal-threat),
                  including two escalate-and-resume cycles
```

## Two inboxes, three sender types

`support@` receives customer emails only. `orders@` receives a mix of
**customers, suppliers, and shipping carriers** - the graph triages sender
type first (`identify_sender_type`) before deciding which classification
taxonomy and downstream handling applies:

- **Customer** (either inbox) → existing order-status/refund/complaint flow
- **Supplier** → stock alerts auto-update mock inventory, price changes
  auto-log a cost update, order confirmations/invoices are logged only,
  anything ambiguous (e.g. shipping delays) escalates
- **Carrier** → tracking updates/delivery confirmations sync to the order
  record automatically, delivery exceptions (damaged/lost) always escalate
  since those usually need proactive customer outreach
- **Spam** → ignored immediately, no further processing

## The graph flow

```
START -> identify_sender_type
           |-- spam     ------------------------------------> decide (ignore) -> send_and_log
           |-- supplier -> classify_supplier_email -> handle_supplier_email --+
           |-- carrier  -> classify_carrier_email  -> handle_carrier_email  --+--> (escalate?) -> escalate_to_human -> send_and_log
           '-- customer -> classify_email -> fetch_context -> assess_urgency -> check_duplicate -> decide
                                                                                                       |-- auto_reply/auto_refund -> draft_reply -> send_and_log
                                                                                                       '-- escalate -----------------> escalate_to_human -> send_and_log
```

`decide()` checks `is_urgent` and `is_duplicate` **before** any normal
policy/auto-approval rule — an angry/legal-threat email or a suspected
double-refund always escalates, even if the refund would otherwise
qualify for auto-approval.

### Urgency override (`assess_urgency` node)
Detects anger, chargeback/legal threats, or excessive caps/exclamation
marks. Forces escalation regardless of category confidence or policy
match - see `run_demo.py` email `e10` for a live example (chargeback
threat overrides what would otherwise be a straightforward refund).

### Duplicate detection (`check_duplicate` node)
Before approving a refund/cancellation, checks whether the same
`order_id` already has a matching `auto_refund`/`auto_reply` decision in
the audit log (Supabase's `email_decisions` table, or the in-memory mock
log). See `run_demo.py` email `e9` - a follow-up about an already-refunded
order gets escalated instead of refunded twice.

`escalate_to_human` calls `interrupt()`, which pauses the graph and
persists its state via the checkpointer. Resuming later (e.g. after a
human clicks "approve" in Slack) is a single call:

```python
from langgraph.types import Command
graph.invoke(Command(resume=human_answer), config)  # same thread_id
```

## Deploying (Vercel)

`api/index.py` is a small Flask app exposing the agent as a JSON API - no
UI, just endpoints:

- `POST /api/process` — `{ "email_id", "inbox_source", "sender", "subject", "body" }`
  → runs the email through the graph, returns the decision, or `{"status": "escalated", ...}` if it paused
- `POST /api/resume` — `{ "email_id", "human_response" }`
  → resumes a paused (escalated) run
- `GET /api/health` — liveness check

### Why persistence needs a real database here
Vercel functions are stateless serverless invocations - nothing in memory
or a local SQLite file survives between requests. That breaks the
escalate → pause → resume flow (`interrupt()`/`Command(resume=...)` need
the paused state to still be there later). So `api/index.py` uses
`PostgresSaver` pointed at your **Supabase project's own Postgres
database** (Supabase is Postgres under the hood) instead of
`run_demo.py`'s `InMemorySaver` or `run_live.py`'s local SQLite file.

### Steps
1. Get your direct Postgres connection string: Supabase dashboard →
   Project Settings → Database → **Connection string** (URI format,
   looks like `postgresql://postgres:[password]@...supabase.co:5432/postgres`)
2. Install the Vercel CLI (`npm i -g vercel`) or just connect your GitHub
   repo at vercel.com/new
3. In your Vercel project's Settings → Environment Variables, add:
   `SUPABASE_DB_URL` (from step 1), plus `SUPABASE_URL`/`SUPABASE_KEY`
   (for order/policy/inventory lookups) and `OPENROUTER_API_KEY` if using
   a real LLM
4. Deploy: `vercel --prod` (or push to GitHub if using the dashboard
   integration) — Vercel auto-detects `vercel.json` and `api/index.py`
5. Test it:
   ```bash
   curl -X POST https://your-project.vercel.app/api/process \
     -H "Content-Type: application/json" \
     -d '{"email_id":"test1","inbox_source":"support@company.com","sender":"jane@example.com","subject":"Where is my order?","body":"Havent heard an update, whats the status?"}'
   ```
   If it escalates, resume it:
   ```bash
   curl -X POST https://your-project.vercel.app/api/resume \
     -H "Content-Type: application/json" \
     -d '{"email_id":"test1","human_response":"Approved - process the refund"}'
   ```

`api/requirements.txt` is a trimmed dependency list scoped to just what
the Vercel function needs (no Gmail/local-dev-only packages) to keep the
deployment size down.



Steps 1-3 are now built-in and auto-detected (see below) — set the env
vars and nothing else changes. Steps 4+ are still manual.

### Supabase (replaces the in-memory/Excel mock data)
1. Create a project at supabase.com
2. Open the SQL Editor and run `supabase_schema.sql` — creates `orders`,
   `inventory`, `refund_policy`, `email_decisions` tables and seeds sample data
3. Set `SUPABASE_URL` and `SUPABASE_KEY` (Project Settings → API → anon or
   service_role key) as environment variables
4. `shopify_client.py`, `policy_source.py`, `inventory_store.py`, and
   `notify_clients.log_decision` all auto-detect Supabase and switch over —
   no other code changes needed. Edit policy rows live in Supabase's table
   editor instead of the Excel file.

### Gmail (real inbox ingestion, replaces run_demo.py's sample list)
1. Follow the setup steps at the top of `agent_app/integrations/gmail_client.py`
   (Google Cloud project → enable Gmail API → OAuth credentials → download
   `credentials.json`)
2. Run `python -m agent_app.integrations.gmail_client` once to complete the OAuth
   login and generate `token.json`
3. If `orders@` and `support@` are aliases on one Google account, `run_live.py`
   works as-is. If they're separate accounts, run the OAuth flow once per
   account and uncomment the `TWO_ACCOUNTS` section in `run_live.py`
4. Run `python run_live.py` — polls both inboxes for unread mail, runs each
   through the graph, sends real replies via Gmail, and marks handled emails
   as read. Escalated emails are left unread until you call
   `resume_escalation(graph, email_id, human_response)` after a human responds
5. Uses a persistent SQLite checkpointer (`dropship_agent.db`) instead of
   `run_demo.py`'s in-memory one, so paused escalations survive between
   separate runs of the script (important if you run it via cron)

### OpenRouter/OpenAI (real LLM instead of the keyword mock)
Set `OPENROUTER_API_KEY` (and optionally `OPENROUTER_MODEL`, e.g.
`anthropic/claude-3.5-haiku`) or `OPENAI_API_KEY`.

### Still manual
4. **Slack**: replace `post_to_slack` with `slack_sdk.WebClient(...).chat_postMessage(...)`,
   and build a small endpoint/button that calls
   `resume_escalation(graph, email_id, human_response)` when a human responds.
5. **Real refund execution**: `handle` currently just prints "issuing
   refund" — call Shopify's actual refund API in `send_and_log`.

