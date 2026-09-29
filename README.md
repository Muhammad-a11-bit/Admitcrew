# AdmitCrew — Full Project

Green-and-white student website, staff workspace, FastAPI backend, Supabase database connection, and importable n8n workflows for Nowshera Study Abroad Consultants.

## What is included

- `app/`: FastAPI API using the existing AdmitCrew Supabase project.
- `static/`: student program browser, inquiry form, staff dashboard, CSV upload, document review, and approval queue.
- `n8n-workflows/`: separate workflow JSON exports and setup notes.
- `supabase/`: additive SQL changes already applied to the existing project, plus a readable schema/migration file.
- `uploads/`: created at runtime for fake test documents; do not put real passports or transcripts in this project.

The existing AdmitCrew database already had 15 programs and 3 test leads. The backend uses those records and preserves them. It does not seed duplicate SQLite tables or change the existing program list.

## Start on Windows

1. Install Python 3.11 or newer.
2. Extract the ZIP and open the `admitcrew-backend` folder.
3. Copy `.env.example` to `.env` if it does not exist.
4. In the Supabase Dashboard for the existing **AdmitCrew** project, open **Settings → API Keys** and copy a server-only **Secret API key** into `SUPABASE_SECRET_KEY` in `.env`. Do not use a publishable key here. Do not share or commit `.env`.
5. Replace `ADMITCREW_STAFF_KEY` and `ADMITCREW_N8N_KEY` with different, long private secrets.
6. Double-click `run_windows.bat`.
7. Open `http://127.0.0.1:8000/` for the website and `http://127.0.0.1:8000/docs` for interactive API docs.

If PowerShell script execution is blocked, `run_windows.bat` uses Command Prompt activation. You can also run these in Command Prompt:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload
```

For macOS/Linux, use `./run_mac_linux.sh` after setting `.env`.

## Supabase connection and safety

This project uses the existing Supabase project `AdmitCrew` at `https://qwhxkyqpmmxvpdnodcuw.supabase.co`. The backend uses a Secret API key on the server, so it never appears in the student website. Row Level Security is enabled on the existing tables, and no permissive anonymous table policies are added; student, staff, and n8n requests go through the backend checks.

The following additive migrations were applied to that database, without deleting or replacing records:

- Add private student session tokens to leads; normalize existing phone formatting so repeat chats match one lead.
- Add chat workflow status and agent review metadata.
- Add outbound message type/channel and a chat link for delivery tracking.
- Add document storage/extracted IELTS fields and workflow indexes.

Check `supabase/migrations/` for the SQL. The dashboard’s API key section provides the Secret key needed locally. **Never put it in frontend JavaScript, n8n workflow JSON, or GitHub.**

## Frontend routes

- Student program browser: `http://127.0.0.1:8000/`
- Staff workspace: select **Staff workspace**, then enter `ADMITCREW_STAFF_KEY`.
- Student session token: saved in that browser’s local storage so the student can view their own staff-approved replies. Staff API responses omit student session tokens.
- The student inquiry is saved immediately; AI responses remain drafts until staff approval.

## API map

| Route | Use | Access |
|---|---|---|
| `GET /health` | Check API/Supabase configuration | Public |
| `GET /api/public/programs` | Browse active programs | Public through backend |
| `POST /api/public/leads` | Create/update lead, deduplicated by phone | Public; session token for existing lead updates |
| `POST /api/public/chat` | Save student inquiry for n8n | Public; requires the student session token |
| `GET /api/public/conversation` | Show student’s own messages | Student bearer token |
| `/api/staff/programs` | Add/edit/archive/import programs | Staff key |
| `/api/staff/leads` | Review lead details and chats | Staff key |
| `/api/staff/documents/{lead_id}` | Upload fake document / record manual check | Staff key |
| `/api/staff/messages` | Review and approve drafts | Staff key |
| `POST /api/staff/reminders/run` | Draft reminders for quiet students | Staff key |
| `/api/n8n/inbox` | Get new student questions and published program list | n8n key |
| `POST /api/n8n/replies` | Save an AI reply as a pending draft | n8n key |
| `/api/n8n/quiet-leads` and `/api/n8n/reminders/draft` | Find quiet leads and create reminder drafts | n8n key |
| `/api/n8n/documents/*` | Retrieve pending fake documents and submit extraction results | n8n key |
| `/api/n8n/approved-messages` and `/api/n8n/messages/{id}/mark-sent` | Deliver approved messages exactly once | n8n key |

## n8n setup

Import each file in `n8n-workflows/` separately. They belong in one n8n project/workspace named **AdmitCrew**, but stay as separate workflows. For each workflow:

1. Replace `https://YOUR_BACKEND_URL` with the reachable API URL. For local n8n on the same computer, use `http://host.docker.internal:8000` if n8n runs in Docker, or `http://127.0.0.1:8000` if it runs directly on the computer.
2. Set the backend key using an n8n credential or the workflow’s documented placeholder. Do not paste Supabase’s secret key into n8n; n8n only needs the backend key.
3. Set up a Google Gemini API key for the two AI workflows. On self-hosted n8n, set the environment variables shown in `n8n-workflows/n8n.env.example` and allow environment variable access in Code/expressions. On n8n Cloud, replace the `$env.*` expressions with n8n credentials or a credential-backed configuration supported by your plan.
4. Connect the backend and Gemini credentials in the HTTP Request nodes, then test each flow manually.
5. Publish the Schedule Trigger workflows after testing. n8n runs them on their configured interval only after you publish them.

If you use hosted n8n, the backend must have a reachable HTTPS address; a private `127.0.0.1` URL on your computer cannot be reached by hosted n8n. Keep the backend key private and use HTTPS for a hosted setup.

### Workflow roles

0. **00 Simple Webhook Q&A** — A small request-and-response example for testing the Q&A path. Import `n8n-workflows/00_webhook_question_answer.json`, then set the backend URL, `X-N8N-Key`, and Gemini API key on the two HTTP Request nodes. Start the workflow in test mode and POST JSON such as `{"question":"What is the fee for BSc Computer Science at the University of Manchester?"}` to the webhook's test URL. It reads the published programs from the backend and returns JSON containing `reply` and `needs_staff`. When activated, use the production webhook URL.

   This simple webhook responds directly to its caller. Use it for a demo or direct Q&A only; a student-facing production chat should use workflow 01 and the staff approval queue so replies are not delivered before staff approval.

1. **01 Student Question Agent** — polls the chat inbox, supplies the exact current program records to Gemini, refuses acceptance promises and unrelated requests, escalates unknown programs, and saves a draft. It does not send a student message.
2. **02 Quiet Student Reminder Drafts** — runs daily and writes reminder drafts for staff approval.
3. **03 Approved Website Inbox Delivery** — reads only staff-approved messages, releases them to the student inbox, and marks them sent once.
4. **04 Fake Document OCR Review** — extracts name, expiry, marks, and IELTS from pending test documents and records a review result. Staff can still review/override results.

WhatsApp and email sending are intentionally left as a later channel integration. The current approved delivery workflow sends to the student website inbox, which is enough to test the approval gate without contacting real students.

## Document handling

Use only fake test documents. The staff upload form can submit a file for OCR (`pending_ocr`) or include extracted fields for a manual rule check. The n8n OCR flow needs to reach the backend document download URL, so a hosted n8n instance requires an HTTPS reachable backend. Do not upload actual passports, transcripts, or IELTS reports.

## Test notes

The database contains 15 practice program records and three test leads. The four PDFs in `test_documents/` are synthetic test documents and visibly marked as samples; no real identity documents are included. Test:

- Create a new student twice using the same browser/session and phone; verify one lead remains.
- Ask about listed programs and compare the answer against the Supabase rows.
- Ask about a missing school, unrelated topic, and the acceptance trick; check staff review/decline behavior.
- Upload fake expired passport/transcript/IELTS files; check the recorded reason.
- Run the reminder workflow; it should create a pending approval row, not send it.
- Approve once in the staff site; the next n8n delivery run marks it sent and places it in the student's website inbox. A second mark-sent attempt is rejected.
