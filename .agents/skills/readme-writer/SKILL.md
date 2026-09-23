---
name: readme-writer
description: Write or update README.md for the judges in Russian, following the organisers' template. Use when asked to write docs or the README, before hourly commits from 16:00, and in the final hour. README replaces the team presentation and is worth 20 points.
---

# README for judges (and AI judges)

If the case document contains its own README prompt, follow it first; this skill only adds to it.

Write in Russian. Use ONLY information that can be verified in the current repository. Never invent features, technologies or results. Content counts, not decoration.

## Sections (organisers' template, in this order, plus our additions marked +)
1. **Название проекта**
2. **Краткое описание**: what problem it solves and for whom.
3. **Что реализовано**: main working functions. Partial features marked as partial.
4. **Как работает решение**: the main user scenario from input to result.
   + **Соответствие требованиям кейса**: table: требование | как выполнено | где в коде | как проверить.
   + **Как работает AI-агент**: loop steps, tools and what each does, where prompts are, how output is validated.
5. **Технологии**: languages, frameworks, libraries (with versions), AI models, APIs, external services.
6. **Архитектура проекта**: components and how they interact + simple Mermaid or ASCII diagram, file names for each part.
7. **Установка и запуск**: system requirements, step-by-step copy-paste commands for Windows (PowerShell) AND Linux/macOS, using `python -m venv` + `pip install -r requirements.txt` as the primary path (uv only as an optional alternative), environment variables table (name, purpose, example, required?).
8. **Как проверить решение**: exact scenario the jury can repeat, sample input from `data/`, expected result.
   + **Обработка ошибок и безопасность**: invalid input, API failures, no secrets in repo.
   + **Тесты**: how to run, what they cover.
9. **Данные и интеграции**: data sources, APIs, external services.
10. **Ограничения**: honest list of what is not implemented.
11. **Ссылка на deployed-версию**, if it exists.
   + **Подготовлено до хакатона / сделано на хакатоне** (п. 6.4): this AGENTS.md + skills kit was prepared in advance; all project code written on 23.09. List third-party libraries and models.
   + **Команда**: names and who did what.

## Rules
- Every command must work when copy-pasted into a clean environment.
- Keep it scannable: short paragraphs, tables, code blocks.
