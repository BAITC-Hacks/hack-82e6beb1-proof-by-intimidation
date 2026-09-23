# AGENTS.md — HackAlem AI team rules

## Context
- **Название кейса:** Единый кейс по геймификации практических заданий AI Sana — Рейтинг качества бизнес задач и открытый выбор команд.
- **Целевые пользователи:** представитель бизнеса, публикующий задачу, и студенческие команды, самостоятельно выбирающие задачи.
- **Главный сценарий:** представитель бизнеса вводит черновик задачи → AI анализирует полноту, задаёт уточняющие вопросы и формирует редактируемую карточку → после подтверждения рассчитывается рейтинг и задача публикуется в каталоге → команда отправляет предложение → бизнес вручную выбирает одну, несколько или ни одной команды → выбранная команда получает баллы за подтверждённый прогресс.

### MANDATORY conditions

Команде необходимо создать работающий MVP, который помогает представителю бизнеса превратить первоначальное описание своей потребности или задачи в полноценную карточку, оценивает качество её заполнения и размещает задачу в открытом каталоге. Студенты самостоятельно выбирают интересные задачи и подают предложения, а представитель бизнеса принимает решение, с кем продолжить работу.

Главный результат
Сквозной сценарий от черновика бизнес задачи до публикации, отклика и выбора команды

Ключевой принцип
Главная геймификация направлена на бизнес: чем полнее и полезнее описана задача, тем выше её рейтинг и позиция в каталоге. Система может рекомендовать задачи студентам, но не назначает команды.

Разработайте MVP платформы, в которой представитель бизнеса описывает свою потребность, проблему или задачу. Система помогает дополнить сведения, рассчитывает рейтинг готовности и публикует карточку в общем каталоге. Любая студенческая команда может просмотреть задачу и подать предложение. Бизнес самостоятельно сравнивает отклики и выбирает одну, несколько или ни одной команды.

1
Черновик
Представитель бизнеса вводит краткое описание потребности, проблемы или задачи.

2
Уточнение
Система определяет недостающие сведения и задаёт не менее трёх уместных вопросов.

3
Карточка
Из ответов формируется редактируемая карточка, которую представитель бизнеса подтверждает.

4
Рейтинг
Система начисляет баллы за полноту и показывает, какие сведения повысят рейтинг задачи.

5
Каталог
Подтверждённая задача публикуется в общем пуле на позиции, соответствующей её рейтингу.

6
Выбор студентов
Любая команда просматривает каталог или рекомендации и подаёт своё предложение.

7
Выбор бизнеса
Бизнес сравнивает предложения и сам выбирает одну, несколько или ни одной команды.

8
Результат
После подтверждённого этапа выбранная команда получает баллы за фактический прогресс.

Конструктор задачи
Свободный ввод; проверка полноты; минимум 3 уточняющих вопроса; редактируемая карточка; ручное подтверждение.

Карточка задачи
Название, контекст, потребность, пользователи, данные, ограничения, ожидаемый результат, критерии успеха, контакт и формат взаимодействия.

Рейтинг задачи
Оценка от 0 до 100; расшифровка начисленных баллов; список недостающих сведений; пересчёт после редактирования.

Общий каталог
Все опубликованные задачи доступны всем командам; сортировка по рейтингу; фильтры по теме и уровню готовности.

Отклики команд
Любая команда может отправить идею решения, план и ссылку на прототип. Число откликов не ограничивается.

Выбор бизнеса
Список предложений и ручные действия выбрать или отклонить. Автоматическое назначение команды запрещено.

Рейтинг отражает не известность компании, а готовность конкретной бизнес задачи к работе со студентами. Баллы начисляются только за заполненные и подтверждённые поля.

Низкий рейтинг не скрывает задачу и не запрещает отклик. Он показывает студентам, насколько реально начать работу без дополнительных уточнений. Рейтинг пересчитывается после каждого подтверждённого дополнения.

В MVP должна быть минимум одна содержательная AI функция. Рекомендуется использовать ИИ для анализа полноты описания и генерации уточняющих вопросов либо для преобразования ответов в карточку задачи. Если внешний API недоступен, допускается локальная заглушка, однако команда должна показать промпт, формат входа и выхода и обработку некорректного ответа.

ИИ не должен добавлять факты, которых не сообщал пользователь.

Сформированный текст редактируется и подтверждается человеком до публикации.

ИИ может рекомендовать студентам задачи по интересам и навыкам, но не ограничивает общий каталог.

ИИ не выбирает команду за бизнес и не назначает исполнителей автоматически.

Персональные и чувствительные признаки участников не используются.

Ссылка на репозиторий или архив с исходным кодом.

Работающий MVP, который можно запустить по инструкции.

README с архитектурой, формулой рейтинга задачи, правилами каталога и тестовыми сценариями.

Демонстрация до 5 минут на одном заранее подготовленном примере.

На защите участники вводят слабое описание бизнес задачи, дополняют его и показывают рост рейтинга. Затем задача публикуется в общем каталоге, студенческая команда самостоятельно отправляет предложение, а бизнес вручную принимает или отклоняет отклик. Все переходы должны работать в MVP, а не на слайдах.

### Дополнительно из кейса

- **Владелец задачи:** МНВО — AI Sana.
- **Продолжительность:** 5 часов, включая подготовку демонстрации.
- **Команда:** 3–5 участников.
- **Формат:** Веб приложение или интерактивный прототип с работающей логикой.
- **Рекомендуемая формула рейтинга:** контекст и потребность — 20 баллов; данные и материалы — 20; ожидаемый результат — 15; критерии успеха — 15; ограничения — 10; пользователи — 10; связь с бизнесом — 10.
- **Уровни готовности:** 0–39 — черновик; 40–69 — рабочая; 70–89 — готовая; 90–100 — приоритетная.
- **Данные:** организаторы могут выдать JSON или CSV. Если набор не выдан, команда создаёт минимум 5 черновиков задач, 5 карточек задач, 5 профилей команд и 5 предложений с указанными в кейсе обязательными полями.
- **Не требуется:** полноценная регистрация, восстановление пароля, сложная ролевая модель, чат, уведомления, календарь, файловое хранилище, собственная ML-модель, векторная база, мобильная адаптация, производственная инфраструктура и полный проектный трекер.
- **Оценка:** сквозной сценарий — 20; качество карточки — 15; геймификация бизнеса — 25; каталог и отклики — 15; AI функция — 10; техническое качество — 10; демонстрация — 5.
- **Технология:** минимум одна содержательная AI функция; конкретная AI-модель, провайдер, язык программирования и фреймворк кейсом не предписаны.

## How we are scored (Положение, п. 7.4) — technical stage, 100 points
| Criterion | Points | What it means for us |
|---|---|---|
| Case fit & functionality | 20 | Every mandatory requirement of the case works. Main scenario runs fully from input to result. Only working features count. |
| Technical implementation | 25 | Features are really implemented in code, components are connected, structure is clear. Key functions must NOT be replaced by pre-written answers or imitation. |
| README & documentation | 20 | README replaces the presentation. Content matters, not looks. |
| Reproducibility & deployment | 20 | A juror runs it in a clean environment from the README. A deployed link is a bonus, not a substitute. |
| Reliability & security | 15 | Main scenario never crashes on valid input; obviously invalid input is handled gracefully. |
- AI judges may do the preliminary evaluation (п. 8.3): everything must be explicit and easy to verify in the repo and README.
- Extra features do NOT compensate for a missed mandatory condition (п. 7.3).

## Hard rules (Положение)
- The platform repo (edu.astanahub.com) is the ONLY working repo. It locks at 18:00; that snapshot is the competition version for all stages, including Demo Day.
- Verifiable progress EVERY hour, or the team can be disqualified (п. 6.6): commit at least hourly with a meaningful message, and append a line to `PROGRESS.md`.
- Disclose all pre-made material, libraries, models, templates and datasets (п. 6.4) in the README.
- Never commit API keys. Use `.env` (gitignored) and `.env.example`.
- The team repo is a GitHub repo created by the platform. All final code must be pushed there.
- EVERY team member must make a personal, visible contribution (commits under their own GitHub account). Participation is not counted otherwise.
- We solve exactly ONE case from the track.
- README is written in Russian (organisers' template), see the readme-writer skill.

## Prime directive
Mandatory requirements first, working end to end, then documentation and reproducibility. Polish comes last.

## Stack (do not change without the team agreeing)
- Python 3.11+, single repo. Work inside a virtualenv (`.venv`), never the global interpreter.
- `requirements.txt` lists every dependency with a pinned version, generated from the virtualenv — a package that only exists globally on our laptop breaks the jury's clean run.
- We may use `uv` locally for speed (`uv venv`, `uv pip install -r requirements.txt`), but `requirements.txt` + plain `python -m venv` + `pip install` MUST remain the documented, working install path. Never make `uv` (or a `uv.lock` / `pyproject.toml`-only setup) the only way to run the project — jurors may not have it.
- OpenAI Python SDK. Model from env var `OPENAI_MODEL`, key from `OPENAI_API_KEY` (loaded via `python-dotenv`).
- Budget is $50 of API credits: cheap model while developing, strong model for the final version. Avoid loops with many API calls.
- UI: React + Vite (`frontend/`), Python FastAPI (`server/`) and SQLite, approved by the user for the rebuild on 23.09.2026. Keep the original Streamlit (`app.py`) runnable as a legacy version. Domain and AI logic stays in plain Python modules.
- Storage: in-memory or local JSON/SQLite. No external services that a juror would need to set up.

## Cross-platform rules (we develop on Windows; jurors likely run Linux/macOS)
- Open every file with `encoding="utf-8"`; Kazakh/Russian text must display correctly.
- Use `pathlib` and relative paths only. Never hardcode `C:\` paths or backslashes.
- No Windows-only commands or packages in the project.
- README gives install/run commands for BOTH Windows (PowerShell) and Linux/macOS.
- Prefer `python -m pip ...`, `python -m streamlit run app.py`, `python -m pytest` (work without venv activation).

## Project layout
```
app.py            # Streamlit UI only — calls agent/
frontend/         # React product UI, built by Vite
server/           # FastAPI routes, validation and SQLite persistence
agent/architect.py # New evidence-grounded AI briefing engine
agent/core.py     # agent loop (plan -> tool calls -> check -> answer)
agent/tools.py    # tool functions + their JSON schemas
agent/prompts.py  # all system prompts in one place
data/             # sample/seed data shipped with the repo
tests/            # a few pytest checks of the main scenario and bad input
.env.example      # OPENAI_API_KEY=, OPENAI_MODEL=
PROGRESS.md       # one line per hour: time, what was done
README.md
```

## How to work
- Small, focused changes. The product must start with `python -m uvicorn server.app:app` after building `frontend/`; preserve `python -m streamlit run app.py` for the legacy version.
- After each finished feature: the human RUNS it in the browser, then commits and pushes. Never let an hour pass with untracked files.
- Never add `.env` to git, to a zip, or to anything shared. Secrets live only in `.env` locally.
- Real AI calls are the default. Never hardcode results for the main scenario.
- If the API key is missing or the API fails, show a clear, labelled error or "offline mode" message. Never silently return canned answers as if they were real.
- Validate inputs (empty text, wrong file type, too long, wrong language) and show friendly messages instead of stack traces.
- Log each agent step (tool name, inputs, short result) so the UI can show the reasoning trail.
- Do not delete or rewrite working features unless asked.
- User-facing content supports Kazakh, Russian and English; answer in the user's language.

## Before saying a task is done
1. Run the app or `python -c "import agent.core"`, and `pytest -q` if tests exist.
2. Confirm no secrets are in the code.
3. Summarise in 3 lines what changed and how to test it.
