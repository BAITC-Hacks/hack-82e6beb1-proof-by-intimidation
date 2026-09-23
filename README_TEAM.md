# How to use this kit

1. The platform creates your team GitHub repo. Clone it (GitHub login set up the night before); copy `AGENTS.md` and `.agents/` into it; commit immediately ("setup: add team rules", counts as hour-1 progress).
2. Copy `.env.example` to `.env`, add the API key you activate at 12:30.
3. Open Codex (or any AI tool; Codex is allowed but not mandatory, п. 6.9).
4. Paste the task summary and ALL mandatory admission conditions into AGENTS.md "Context".

## Two separate scoring stages
- Technical stage (decides who reaches the final): 100 pts from the repo only, NO pitch.
  Case fit 20 | Implementation 25 | README 20 | Reproducibility 20 | Reliability 15.
- Demo Day (finalists): Value 25 | Result quality 20 | Innovation 15 | Scalability 20 | Presentation 20.
  Technical points are not carried over. Demo Day judges the repo as it was at 18:00.

## Day plan
- 09:00-12:00  Registration window. Arrive TOGETHER around 09:30-10:00 (avoid the last-minute queue),
               enter one by one, badge scanned, take 3 seats side by side in your sector.
- 10:00-12:30  Set up: LAN cable, check IP (ipconfig), git/GitHub/Codex logged in, repo kit ready locally.
               Attend the Codex workshop if it runs in this window. Eat and use the toilet now.
               If you leave the zone, be back well before the start is announced.
- 12:30-13:00  Activate resources, put key in .env, run one test API call.
- 13:00-13:30  Read task + scoring methodology. List mandatory conditions. Choose the minimal architecture.
               Commit: setup + AGENTS.md + README skeleton with the requirements table.
- 13:30-15:00  Main scenario working end to end (input -> agent -> result).
- 15:00-16:30  Complete all mandatory requirements, input validation, step log, tests.
- 16:30        FEATURE FREEZE.
- 16:30-17:30  Clean-environment test, README (readme-writer skill), fix bugs.
- 17:30-17:50  Final checks, PROGRESS.md, final push, update "Сдать решение". Deploy only if everything else is done.
- 18:00        Repo locks automatically.

## Venue rules (Правила зачета участия)
- Enter one by one, badge scanned. Sit TOGETHER in your sector before the start: no moving after the start.
- Personal breaks: max 60 minutes TOTAL, tell the steward, badge scanned on exit and entry.
- LAST HOUR (17:00-18:00): nobody leaves. Toilet/water before 17:00.
- Leaving before the official end or missing the last hour = participation not counted.
- Every member must personally contribute: each person commits under their own GitHub account.
- Technical question: raise your hand, a mentor comes.

## Submission (don't forget!)
- Push final code to the team GitHub repo.
- Tracks page -> your case -> "Сдать решение" -> project name + description. Can be updated until the deadline.
  Do the first submission around 16:30 and update it at the end.

## Non-negotiables
- Hourly progress or disqualification risk: commit + PROGRESS.md line at 14:00, 15:00, 16:00, 17:00, 17:50.
- Every mandatory condition done before any extra feature.
- README is written continuously, not at 17:55.
- No fake/canned answers in core features.

## Budget
- $50 OpenAI credits: cheap model while developing, strong model for the final version.
