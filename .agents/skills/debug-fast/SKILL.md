---
name: debug-fast
description: Fix errors quickly under time pressure. Use when something crashes, an API call fails, output is malformed, or the app will not start.
---

# Debug fast

1. Read the full error and find the first line that points to our code.
2. Reproduce with the smallest possible command.
3. Fix the root cause with the smallest change. Do not refactor while debugging.
4. Check common causes first: missing env var, wrong model name, package missing from requirements.txt, JSON parse failure from the model, Streamlit re-runs resetting state (use `st.session_state`).
5. If a fix will take more than ~15 minutes, propose a simpler working alternative (fewer steps, simpler data, a smaller scope) — never a fake result standing in for a real feature.
6. After fixing, re-run the main demo path to confirm nothing else broke.
