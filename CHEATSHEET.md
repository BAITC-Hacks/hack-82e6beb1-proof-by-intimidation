# Cheat sheet — 23.09 (keep open all day)

## First 5 minutes at 13:00
1. Clone team repo, copy kit in (show hidden files!), `git add . && git commit -m "setup: team rules and skills" && git push`
2. Paste into AGENTS.md -> Context: case summary + EVERY mandatory condition, word for word.
3. If the case demands another stack/format/model — edit the Stack section BEFORE any code.

## Daily commands
```powershell
python -m venv .venv
.venv\Scripts\activate                 # prompt must show (.venv)
pip install -r requirements.txt
python -m streamlit run app.py
python -m pytest -q
pip freeze > requirements.txt          # after adding any package
git add . ; git commit -m "..." ; git push
git checkout .                         # undo uncommitted damage
```
If activation is ever blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`,
or call the venv directly: `.venv\Scripts\python.exe -m pytest -q`

## Prompts that work with Codex
- **Start**: "Read AGENTS.md and all skills in .agents/skills. Build <main scenario> for <user>. The agent must run a real multi-round tool-calling loop (max 6 rounds) with 3-4 tools that the model chooses itself — do not force a single tool call. Show every round in the UI. Handle empty/invalid input and a missing API key gracefully. Give me the exact Windows commands to run it."
- **Next feature**: "Add <one feature>. Change nothing else. Then tell me how to test it."
- **Drifting**: "Re-read AGENTS.md and .agents/skills, then continue."
- **Docs**: "Use the readme-writer skill and update README.md from the current repo only."
- **Polish (only after everything mandatory works)**: "Improve the visual presentation of app.py only, no logic changes: clear header, results in cards, readable step timeline, loading status."

## If something breaks
| Problem | Do this |
|---|---|
| Codex broke working code | `git checkout .` (that is why we commit each feature) |
| Bug > 15 minutes | Simplify or cut the feature. Never a fake result. |
| Behind at 15:30 | Drop everything that is not a mandatory condition |
| Venue internet down | Phone hotspot |
| API key not working | Re-check Billing -> Promotions; ask a mentor (raise hand) |
| Requirement unclear | Ask a mentor — do not guess |
| Codex Pro asks for payment | Do not pay. Use existing login / VS Code. API credits are separate. |

## Never
- Commit `.env` or any key. Share a zip containing `.env`.
- Fake or hardcode results of core features.
- Add features after 16:30.
- Leave the room 17:00-18:00.
- Let an hour pass without a commit + PROGRESS.md line.

## Before 17:50
- [ ] Every mandatory condition works
- [ ] Clean-install test passed (fresh clone + new venv + README commands)
- [ ] Bad input handled, no stack traces
- [ ] README complete (incl. disclosure + team contributions)
- [ ] All three members have commits under their own accounts
- [ ] Final push done, "Сдать решение" updated
