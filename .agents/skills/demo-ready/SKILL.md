---
name: demo-ready
description: Prepare the repo for technical judging and reviewers: clean-environment run, reliability, tests, disclosure, final checks. Use in the final 60-90 minutes or when asked to "make it submission-ready", "prepare for judging", or "finish up".
---

# Submission-ready checklist (technical stage is scored only from the repo)

Stop adding features. Only do these, in order:

1. **Mandatory conditions**: re-read the task's mandatory admission conditions; confirm each one works and is shown in the README.
2. **Dependency check**: install from `requirements.txt` in a BRAND NEW virtualenv and run the app there. Anything that only worked because it was already on the laptop shows up here.
3. **Clean-environment test**: fresh clone into a new folder, new virtualenv, `pip install -r requirements.txt`, copy `.env.example` to `.env`, run exactly the README commands. Fix anything that fails. (Reproducibility = 20 points.)
4. **Reliability**: run the main scenario 3 times with valid input, then try empty, huge and nonsense input. No crashes, no stack traces. (15 points.)
5. **Tests**: a few `pytest` tests for the main scenario logic and input validation; `pytest -q` passes.
6. **No imitation**: make sure no key function returns pre-written answers. Any offline fallback is clearly labelled.
7. **Show the agent working**: UI displays each step (tool used + short result).
8. **README**: run the `readme-writer` skill and check every section is filled.
9. **Deployment (bonus only)**: if time allows, a public link with the key set as an environment variable. Never at the expense of steps 1-7.
10. **Final**: update `PROGRESS.md`, commit and push well before 18:00.
