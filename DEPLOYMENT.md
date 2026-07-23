# Deployment — Streamlit Community Cloud

The app is deploy-ready. These steps are yours to perform (they need your GitHub + Streamlit
accounts and secret entry, which must not be automated).

## 1. Push the repo to GitHub
```bash
git init
git add -A
git commit -m "Week 3 — Personal Productivity Agent"
git branch -M main
git remote add origin https://github.com/Rana-Haseeb/productivity-agent-2026.git
git push -u origin main
```
`.env` and `WEEK3_PROJECT_MEMORY.md` are git-ignored, so **no secrets are pushed**. Verify with
`git status` that neither appears.

## 2. Create the app on Streamlit Community Cloud
1. Go to <https://share.streamlit.io> → **New app**.
2. Repository: `Rana-Haseeb/productivity-agent-2026` · Branch: `main` · **Main file: `app/main.py`**.
3. (Optional) Advanced settings → Python version 3.11+.

## 3. Add secrets (Streamlit dashboard → App → Settings → **Secrets**)
Paste this TOML (fill in real values — same as your local `.env`). The app bridges `st.secrets`
into environment variables automatically, so no code change is needed.
```toml
LLM_PROVIDER = "openrouter"
OPENROUTER_API_KEY = "sk-or-v1-…"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# For the graded eval run instead:
# LLM_PROVIDER = "openai"
# OPENAI_API_KEY = "sk-…"
DATABASE_URL = "postgresql://postgres.vtzhkcjrmakrfnulxuvz:mlp%40090%40mlp@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"
```
> Use the **session pooler** `DATABASE_URL` (IPv4). The direct `db.<ref>.supabase.co` host is
> IPv6-only and will not resolve on Streamlit Cloud.

## 4. Sample data
The deployed app connects to the **same Supabase database**, which already contains seeded sample
tasks and notes. To reset/reseed: `python scripts/init_db.py --reseed` (run locally).

## 5. Deploy & verify
Click **Deploy**. On first load, verify: the app renders, the Tasks tab shows sample data, a direct
question answers without a tool, and a "create a task" request shows the approval panel.

---

## Known deployment limitations
- **Build size / memory (the main risk).** `sentence-transformers` pulls `torch` (~2 GB), and the
  free tier has ~1 GB RAM. The app is built to **degrade gracefully**: if the embedding model can't
  load, semantic note search automatically falls back to keyword search and notes save without an
  embedding — the app stays up. If the build fails on `torch`, remove `sentence-transformers` from
  `requirements.txt` and redeploy (you'll get keyword search instead of semantic).
- **Free-model latency & rate limit.** OpenRouter free models are slow (15–40 s) and capped at
  ~50 requests/day. For a smooth onsite demo, set `LLM_PROVIDER=openai` + `OPENAI_API_KEY`.
- **Shared database.** Single Supabase project, single user scope (no per-user isolation yet).
- **Cold starts.** The first request after the app sleeps can be slow while the model loads.
