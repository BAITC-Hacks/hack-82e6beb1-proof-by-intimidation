from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from agent.core import run_task_agent
from rating import CARD_FIELDS, SCORING_RULES, calculate_rating
from storage import load_demo_card, load_drafts, load_state, next_id, reset_state, save_state

st.set_page_config(page_title="AI Sana Challenge Hub", page_icon="✦", layout="wide", initial_sidebar_state="expanded")
st.markdown(
    """
    <style>
    .stApp {background:#F7F8FC;color:#101936} section[data-testid="stSidebar"]{background:#101936}
    section[data-testid="stSidebar"] *{color:#F1F4FF!important} section[data-testid="stSidebar"] label{width:100%!important;white-space:normal!important;overflow:visible!important}.block-container{max-width:1370px;padding-top:1.4rem}
    h1,h2,h3{letter-spacing:-.03em;color:#101936}[data-testid="stMetric"]{background:#fff;border:1px solid #E7EAF3;border-radius:16px;padding:14px}[data-testid="stMetric"] [data-testid="stMetricLabel"] *,[data-testid="stMetric"] [data-testid="stMetricValue"] *{color:#101936!important;opacity:1!important}
    .hero{background:linear-gradient(115deg,#101936,#26377B 60%,#6558F5);color:white;padding:30px 34px;border-radius:24px;margin-bottom:22px;box-shadow:0 14px 36px rgba(30,43,100,.18)}
    .hero h1{color:#fff!important;margin:0 0 7px;font-size:2.2rem}.hero p{color:#D9DEFF;margin:0;font-size:1.05rem}.eyebrow{color:#BFC8FF;font-size:.75rem;font-weight:700;letter-spacing:.13em;text-transform:uppercase;margin-bottom:8px}
    .passport{background:#fff;border:1px solid #E7EAF3;border-radius:20px;padding:22px;box-shadow:0 4px 15px rgba(19,31,72,.04)}.passport-title{font-size:1.3rem;font-weight:750;color:#101936;margin:4px 0 8px}
    .chip{display:inline-block;padding:5px 9px;border-radius:99px;font-size:.78rem;font-weight:700;margin:0 5px 6px 0}.chip-violet{background:#EEEDFF;color:#5347D7}.chip-mint{background:#E5F8F2;color:#087A5D}.chip-gold{background:#FFF5DD;color:#9B6500}.chip-slate{background:#EEF1F7;color:#4C5874}
    .question{background:#F8F8FF;border-left:3px solid #6558F5;padding:12px 14px;border-radius:0 12px 12px 0;margin:8px 0;color:#2F3A5D}.score-ring{font-size:2.25rem;font-weight:800;color:#6558F5;line-height:1}.score-label{color:#667085;font-size:.82rem;margin-top:6px}.section-note{color:#667085;margin-top:-7px;margin-bottom:16px}
    .empty{background:#fff;border:1px dashed #CBD2E1;border-radius:16px;color:#667085;padding:26px;text-align:center}div[data-testid="stForm"]{background:#fff;border:1px solid #E7EAF3;border-radius:18px;padding:18px}.stButton>button,.stFormSubmitButton>button{border-radius:10px;font-weight:650}.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"]{background:#6558F5;border-color:#6558F5}
    .stApp label,.stApp label *,.stApp [data-testid="stWidgetLabel"] *{color:#26345A!important}.stApp input,.stApp textarea,.stApp [data-baseweb="select"]>div{background:#fff!important;color:#101936!important;border-color:#CBD2E1!important}.stApp input::placeholder,.stApp textarea::placeholder{color:#7A859B!important}
    section[data-testid="stSidebar"] label,section[data-testid="stSidebar"] label *{color:#F1F4FF!important}
    </style>
    """,
    unsafe_allow_html=True,
)


def state() -> dict:
    if "hub_state" not in st.session_state:
        st.session_state.hub_state = load_state()
    return st.session_state.hub_state


def persist() -> None:
    save_state(state())


def team_name(team_id: str) -> str:
    return next((team["name"] for team in state()["teams"] if team["id"] == team_id), team_id)


def team_by_id(team_id: str) -> dict:
    return next((team for team in state()["teams"] if team["id"] == team_id), {})


def task_rating(task: dict) -> dict:
    return calculate_rating(task)


def level_chip(level: str) -> str:
    kind = {"Черновик": "slate", "Рабочая": "gold", "Готовая": "mint", "Приоритетная": "violet"}.get(level, "slate")
    return f'<span class="chip chip-{kind}">{escape(level)}</span>'


def render_quality_review(review: dict, *, draft: bool = False) -> None:
    if not review:
        st.caption("AI-разбор качества недоступен. Действует локальная консервативная оценка.")
        return
    if draft:
        potential = sum(round(weight * int(review.get(key, {}).get("level", 0)) / 4) for key, (_, weight) in SCORING_RULES.items())
        st.metric("Потенциал текущего черновика", f"{potential}/100")
        st.caption("Предварительная диагностика, не официальный рейтинг. Баллы появляются только после подтверждения карточки.")
    priority = sorted(SCORING_RULES, key=lambda key: (int(review.get(key, {}).get("level", 0)), -SCORING_RULES[key][1]))[:3] if draft else list(SCORING_RULES)
    st.caption("Три самых важных пробела" if draft else "Все критерии")
    for key in priority:
        label, weight = SCORING_RULES[key]
        item = review.get(key, {})
        level = int(item.get("level", 0))
        with st.container(border=True):
            a, b = st.columns([3, 1])
            a.markdown(f"**{label}**")
            b.markdown(f"**{level}/4** · до {weight} баллов")
            if item.get("evidence"):
                st.caption(f"Из вашего текста: «{item['evidence']}»")
            st.write(item.get("reason") or "В черновике пока нет проверяемой информации по этому пункту.")
            if level < 4:
                st.info(item.get("next_step") or "Уточните это поле конкретными фактами.")
    if draft:
        with st.expander("Все 8 критериев оценки"):
            for key, (label, weight) in SCORING_RULES.items():
                item = review.get(key, {})
                st.write(f"**{label}: {item.get('level', 0)}/4** · {item.get('reason') or 'Не оценено'}")


def hero(title: str, subtitle: str, eyebrow: str) -> None:
    st.markdown(f'<div class="hero"><div class="eyebrow">{escape(eyebrow)}</div><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>', unsafe_allow_html=True)


def render_passport(task: dict, compact: bool = False) -> None:
    rating = task_rating(task)
    title, topic = escape(task.get("title") or "Без названия"), escape(task.get("topic") or "Другое")
    if compact:
        st.markdown(f'<div class="passport"><div>{level_chip(rating["level"])}<span class="chip chip-slate">{topic}</span></div><div class="passport-title">{title}</div><div class="score-ring">{rating["score"]}<span style="font-size:1rem;color:#98A2B3"> / 100</span></div><div class="score-label">{escape(task.get("need") or "Потребность пока не описана")}</div></div>', unsafe_allow_html=True)
        return
    left, right = st.columns([3, 1])
    with left:
        st.markdown(f'<div class="eyebrow" style="color:#6558F5">Паспорт задачи</div><div class="passport-title">{title}</div>{level_chip(rating["level"])}<span class="chip chip-slate">{topic}</span>', unsafe_allow_html=True)
        st.write(task.get("need") or "Потребность пока не описана")
    with right:
        st.markdown(f'<div class="score-ring">{rating["score"]}</div><div class="score-label">готовность из 100</div>', unsafe_allow_html=True)
    st.progress(rating["score"])
    a, b, c = st.columns(3)
    a.caption("Ожидаемый результат"); a.write(task.get("expected_result") or "Нужно уточнить")
    b.caption("Данные и доступ"); b.write(task.get("data") or "Не подтверждены")
    c.caption("Ментор и формат"); c.write(task.get("interaction_format") or "Не подтверждён")
    st.markdown("#### Почему такой рейтинг")
    st.caption("Баллы = вес критерия × уровень качества / 4. Незаверенные поля получают 0, даже если заполнены.")
    for item in rating["breakdown"]:
        with st.expander(f"{item['field']} · {item['earned']}/{item['max']} баллов · качество {item['level']}/4"):
            source_label = {"AI": "AI", "AI + rule": "AI с ограничением по формальному правилу", "local": "локальная проверка"}[item["source"]]
            st.caption(f"Основание: «{item['evidence'] or 'нет данных'}» · {source_label}")
            st.write(item["reason"])
            if item["earned"] < item["max"]: st.info(item["next_step"])


def render_agent_timeline(result: dict) -> None:
    with st.expander("Шаги AI-агента · что проверил ассистент"):
        st.caption("Модель формирует вопросы, а локальные инструменты проверяют поля и рассчитывают рейтинг.")
        for step in result.get("steps", []):
            st.write(f"**{step['tool']}**")
            st.json(step["result"], expanded=False)
        st.caption("Промпт и fallback доступны в agent/prompts.py и agent/core.py.")


def overview() -> None:
    tasks = [task for task in state()["tasks"] if task.get("published")]
    ratings = [task_rating(task)["score"] for task in tasks]
    accepted = sum(proposal.get("status") == "accepted" for proposal in state()["proposals"])
    hero("Challenge Hub", "Практические задачи, которые студентам действительно по силам довести до результата.", "AI Sana · сотрудничество вузов и бизнеса")
    a, b, c, d = st.columns(4)
    a.metric("Опубликованные задачи", len(tasks))
    b.metric("Средняя готовность", f"{round(sum(ratings) / len(ratings)) if ratings else 0}/100")
    c.metric("Команды в сообществе", len(state()["teams"]))
    d.metric("Команды выбраны", accepted)
    st.markdown("### В центре внимания")
    st.markdown('<p class="section-note">Качественное описание — это меньше уточнений для бизнеса и честнее старт для команды.</p>', unsafe_allow_html=True)
    featured = sorted(tasks, key=lambda task: task_rating(task)["score"], reverse=True)[:2]
    cols = st.columns(2)
    for column, task in zip(cols, featured):
        with column: render_passport(task, compact=True)
    st.markdown("### Как работает продукт")
    flow = st.columns(3)
    flow[0].markdown("**01 · Сформулировать**\n\nБизнес описывает реальную проблему, а AI выявляет неизвестные условия.")
    flow[1].markdown("**02 · Уточнить**\n\nПаспорт задачи делает результат, доступ к данным и поддержку ментора явными.")
    flow[2].markdown("**03 · Начать работу**\n\nКоманды предлагают подход; бизнес выбирает вручную и подтверждает прогресс.")


def challenge_studio() -> None:
    hero("Challenge Studio", "Соберите задачу, с которой студенческая команда сможет начать работу без догадок.", "Для представителей бизнеса")
    st.markdown("### 1 · Опишите реальную потребность")
    st.markdown('<p class="section-note">Не пишите идеальное ТЗ. Опишите ситуацию своими словами — AI-агент найдёт пробелы.</p>', unsafe_allow_html=True)
    demo_drafts = load_drafts()
    selected_demo = st.selectbox("Быстрый старт", [item["id"] for item in demo_drafts] + ["Свой черновик"], format_func=lambda value: "Свой черновик" if value == "Свой черновик" else next(item["text"][:64] for item in demo_drafts if item["id"] == value))
    sample = next((item["text"] for item in demo_drafts if item["id"] == selected_demo), st.session_state.get("draft", ""))
    draft = st.text_area("Черновик задачи", value=sample, key=f"draft_{selected_demo}", height=155, placeholder="Например: студентам сложно…")
    left, right = st.columns([1, 2])
    topics = ["Образование", "EdTech", "Аналитика", "Коммуникации"]
    sample_topic = next((item["topic"] for item in demo_drafts if item["id"] == selected_demo), "Образование")
    with left: topic = st.selectbox("Направление", topics, index=topics.index(sample_topic), key=f"topic_{selected_demo}")
    with right: st.caption("AI не добавит факты от себя. Неизвестные детали станут вопросами, а не выдуманными полями.")
    if st.button("Проверить черновик", type="primary", use_container_width=True):
        if len(draft.strip()) < 10: st.error("Добавьте хотя бы одно содержательное предложение (минимум 10 символов).")
        elif len(draft) > 5000: st.error("Черновик слишком длинный: максимум 5000 символов.")
        else:
            st.session_state.draft, st.session_state.draft_topic = draft.strip(), topic
            with st.spinner("AI-агент читает именно ваш черновик..."):
                st.session_state.agent_result = run_task_agent(st.session_state.draft)
            st.session_state.pop("candidate_card", None)
            st.session_state.pop("card_result", None)
    result = st.session_state.get("agent_result") if draft.strip() == st.session_state.get("draft", "") else None
    if not result: return
    if result["mode"] == "offline": st.warning(result["message"])
    st.markdown("### 2 · Разбор качества черновика")
    st.markdown(f'<div class="passport"><div class="eyebrow" style="color:#6558F5">Что получено из ввода</div><div class="passport-title">{escape(result.get("summary", ""))}</div></div>', unsafe_allow_html=True)
    if result.get("highlights"):
        st.caption("Подтверждённые сигналы из вашего текста")
        st.markdown("".join(f'<span class="chip chip-mint">{escape(item)}</span>' for item in result["highlights"]), unsafe_allow_html=True)
    if "fallback" in result.get("question_source", ""):
        st.info("Часть AI-вопросов не прошла проверку привязки к вашему тексту. Недостающее число вопросов дополнено локальными и не выдаётся за AI.")
    st.caption("Ответьте на эти конкретные вопросы — они сделают задачу исполнимой.")
    st.markdown("#### Диагностика качества черновика")
    st.caption(result.get("review_status", ""))
    render_quality_review(result.get("draft_review", {}), draft=True)
    st.markdown("#### Что уточнить")
    for number, question in enumerate(result["questions"], 1): st.markdown(f'<div class="question"><b>{number:02d}</b> · {escape(question)}</div>', unsafe_allow_html=True)
    render_agent_timeline(result)
    st.markdown("### 3 · Соберите паспорт задачи")
    demo_card_id = next((item.get("demo_card_id") for item in demo_drafts if item["id"] == selected_demo), None)
    use_demo = st.checkbox("Подставить синтетические ответы для демонстрации (их можно изменить)", value=False, key=f"demo_answers_{selected_demo}", disabled=not demo_card_id) and bool(demo_card_id)
    demo_fields = load_demo_card(demo_card_id) if use_demo else {}
    def initial(field: str) -> str:
        return demo_fields.get(field, result["card"].get(field, ""))
    with st.form(f"challenge_passport_form_{selected_demo}_{int(use_demo)}"):
        fields = {}
        first, second = st.columns(2)
        with first:
            fields["title"] = st.text_input("Название задачи", value=initial("title"), key=f"passport_title_{selected_demo}_{int(use_demo)}", placeholder="Короткое и понятное название")
            fields["context"] = st.text_area("Что происходит сейчас?", value=initial("context"), key=f"passport_context_{selected_demo}_{int(use_demo)}", height=92)
            fields["need"] = st.text_area("Что нужно изменить?", value=initial("need"), key=f"passport_need_{selected_demo}_{int(use_demo)}", height=92)
            fields["users"] = st.text_area("Для кого решение?", value=initial("users"), key=f"passport_users_{selected_demo}_{int(use_demo)}", height=78)
            fields["data"] = st.text_area("Какие данные или материалы доступны?", value=initial("data"), key=f"passport_data_{selected_demo}_{int(use_demo)}", height=78)
        with second:
            fields["expected_result"] = st.text_area("Какой результат команда должна передать?", value=initial("expected_result"), key=f"passport_result_{selected_demo}_{int(use_demo)}", height=78)
            fields["success_criteria"] = st.text_area("Как выглядит успех?", value=initial("success_criteria"), key=f"passport_success_{selected_demo}_{int(use_demo)}", height=78)
            fields["constraints"] = st.text_area("Сроки, доступы и ограничения", value=initial("constraints"), key=f"passport_constraints_{selected_demo}_{int(use_demo)}", height=78)
            fields["contact"] = st.text_input("Контакт ментора", value=initial("contact"), key=f"passport_contact_{selected_demo}_{int(use_demo)}")
            fields["interaction_format"] = st.text_input("Формат поддержки", value=initial("interaction_format"), key=f"passport_interaction_{selected_demo}_{int(use_demo)}", placeholder="Например: 30 минут раз в неделю")
        build = st.form_submit_button("Собрать passport из подтверждённых фактов", type="primary", use_container_width=True)
    if build:
        with st.spinner("Проверяем качество каждого поля и дословные основания оценки..."):
            final = run_task_agent(st.session_state.draft, fields)
        st.session_state.card_result = final
        st.session_state.candidate_card = dict(final["card"], topic=topic)
        st.rerun()
    candidate = st.session_state.get("candidate_card")
    if not candidate: return
    candidate["topic"] = topic
    st.markdown("### 4 · Подтвердите и опубликуйте")
    st.caption(st.session_state.get("card_result", {}).get("review_status", ""))
    st.info("Ниже — прогноз рейтинга, если вы подтвердите все заполненные поля. Официальные баллы начисляются только после вашего подтверждения.")
    potential = dict(candidate)
    potential["confirmed_fields"] = [field for field, value in candidate.items() if field in CARD_FIELDS and str(value).strip()]
    potential_rating = task_rating(potential)
    st.markdown('<div class="passport">', unsafe_allow_html=True); render_passport(potential); st.markdown('</div>', unsafe_allow_html=True)
    confirmed = st.checkbox("Я подтверждаю: поля passport верны, и challenge можно открыть студенческим командам.", key="human_confirmation")
    publish_a, publish_b = st.columns([1, 3])
    with publish_a: publish = st.button("Опубликовать", type="primary", use_container_width=True)
    with publish_b: st.caption(f"После ручного подтверждения рейтинг будет {potential_rating['score']} / 100. До подтверждения баллы не начисляются. Чтобы изменить карточку, отредактируйте поля выше и пересчитайте.")
    if publish:
        if not confirmed: st.error("Публикация требует явного ручного подтверждения.")
        elif not candidate.get("title", "").strip() or not candidate.get("context", "").strip() or not candidate.get("need", "").strip(): st.error("Для публикации добавьте название, контекст и потребность.")
        else:
            task = dict(candidate, id=next_id(state()["tasks"], "t"), published=True, confirmed_fields=potential["confirmed_fields"], current_score=potential_rating["score"])
            state()["tasks"].append(task); persist(); st.success("Challenge опубликован в Marketplace. Команды могут откликнуться.")


def marketplace() -> None:
    hero("Каталог задач", "Выберите задачу с ясным результатом, доступной поддержкой и реальной ценностью для портфолио.", "Для студенческих команд")
    tasks = [task for task in state()["tasks"] if task.get("published")]
    topics = sorted({task.get("topic", "Другое") for task in tasks})
    a, b = st.columns(2)
    selected_topic = a.selectbox("Направление", ["Все направления"] + topics)
    selected_level = b.selectbox("Готовность", ["Все уровни", "Черновик", "Рабочая", "Готовая", "Приоритетная"])
    shown = [task for task in tasks if (selected_topic == "Все направления" or task.get("topic") == selected_topic) and (selected_level == "Все уровни" or task_rating(task)["level"] == selected_level)]
    shown.sort(key=lambda task: task_rating(task)["score"], reverse=True)
    if not shown:
        st.markdown('<div class="empty">По этому фильтру challenges не найдены.</div>', unsafe_allow_html=True); return
    cards = st.columns(2)
    for index, task in enumerate(shown):
        with cards[index % 2]:
            render_passport(task, compact=True)
            if st.button("Открыть passport", key=f"open_{task['id']}", use_container_width=True): st.session_state.selected_task_id = task["id"]
    selected_id = st.session_state.get("selected_task_id", shown[0]["id"])
    selected = next((task for task in shown if task["id"] == selected_id), shown[0])
    st.markdown("### Описание задачи")
    st.markdown('<div class="passport">', unsafe_allow_html=True); render_passport(selected); st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("### Предложить решение")
    with st.form(f"proposal_form_{selected['id']}"):
        team = st.selectbox("От имени команды", state()["teams"], format_func=lambda item: item["name"])
        proposal_a, proposal_b = st.columns(2)
        with proposal_a:
            idea = st.text_area("Идея решения", placeholder="Какой подход вы предлагаете?")
            plan = st.text_area("План работы", placeholder="Исследование → prototype → тестирование")
        with proposal_b:
            deadline = st.text_input("Срок", value="10 дней")
            link = st.text_input("Ссылка на прототип / портфолио", placeholder="https://...")
            st.caption(f"Навыки команды: {team['skills']}")
        send = st.form_submit_button("Отправить предложение", type="primary", use_container_width=True)
    if send:
        if not all([idea.strip(), plan.strip(), deadline.strip(), link.strip()]) or not link.strip().startswith(("http://", "https://")):
            st.error("Заполните идею, план, срок и корректную ссылку, начинающуюся с https:// или http://.")
        else:
            state()["proposals"].append({"id": next_id(state()["proposals"], "p"), "task_id": selected["id"], "team_id": team["id"], "idea": idea.strip(), "plan": plan.strip(), "deadline": deadline.strip(), "link": link.strip(), "status": "submitted"})
            persist(); st.success("Proposal отправлен. Бизнес увидит его в Collaboration Desk.")


def collaboration_desk() -> None:
    hero("Отклики и выбор", "Сравнивайте предложения по сути, выбирайте вручную и фиксируйте реальный прогресс.", "Для представителей бизнеса")
    tasks = state()["tasks"]
    if not tasks:
        st.markdown('<div class="empty">Сначала опубликуйте хотя бы один challenge.</div>', unsafe_allow_html=True); return
    selected = st.selectbox("Выберите challenge", tasks, format_func=lambda item: item["title"])
    with st.expander("Уточнить опубликованную задачу и пересчитать рейтинг"):
        st.caption("Изменения подтверждает представитель бизнеса. Низкий рейтинг не скрывает задачу из каталога.")
        with st.form(f"edit_{selected['id']}"):
            edited = {}
            for key, label in CARD_FIELDS.items():
                edited[key] = st.text_area(label, value=selected.get(key, ""), height=72) if key not in {"title", "contact", "interaction_format"} else st.text_input(label, value=selected.get(key, ""))
            save_edit = st.form_submit_button("Подтвердить изменения и пересчитать", type="primary")
        if save_edit:
            if not all(edited[key].strip() for key in ("title", "context", "need")):
                st.error("Название, контекст и потребность обязательны.")
            else:
                with st.spinner("Пересчитываем качество задачи..."):
                    revised = run_task_agent(selected.get("draft") or selected.get("context", ""), edited)
                selected.update({key: edited[key].strip() for key in CARD_FIELDS})
                selected["quality_review"] = revised["card"].get("quality_review", {})
                selected["confirmed_fields"] = [key for key, value in edited.items() if value.strip()]
                selected["current_score"] = task_rating(selected)["score"]
                persist()
                st.success(f"Изменения подтверждены. Новый рейтинг: {selected['current_score']}/100.")
    proposals = [proposal for proposal in state()["proposals"] if proposal["task_id"] == selected["id"]]
    st.caption(f"Откликов: {len(proposals)} · решение всегда остаётся за бизнесом")
    if not proposals:
        st.markdown('<div class="empty">Пока нет предложений. Откройте Marketplace и отправьте одно от demo-команды.</div>', unsafe_allow_html=True); return
    for proposal in proposals:
        team = team_by_id(proposal["team_id"])
        with st.container(border=True):
            top_a, top_b = st.columns([3, 1])
            top_a.subheader(team_name(proposal["team_id"])); top_a.caption(f"{team.get('skills', '')} · {team.get('technologies', '')}")
            labels = {"submitted": "Новый", "shortlisted": "Шорт-лист", "accepted": "Выбрана", "rejected": "Отклонён"}
            top_b.markdown(level_chip(labels.get(proposal["status"], proposal["status"])), unsafe_allow_html=True)
            body_a, body_b = st.columns(2)
            body_a.write("**Подход**"); body_a.write(proposal["idea"])
            body_b.write("**План и срок**"); body_b.write(f"{proposal['plan']}\n\n{proposal['deadline']}")
            actions = st.columns(3)
            if actions[0].button("В шорт-лист", key=f"short_{proposal['id']}"):
                proposal["status"] = "shortlisted"; persist(); st.rerun()
            if actions[1].button("Выбрать команду", key=f"accept_{proposal['id']}", type="primary"):
                proposal["status"] = "accepted"; persist(); st.rerun()
            if actions[2].button("Отклонить", key=f"reject_{proposal['id']}"):
                proposal["status"] = "rejected"; persist(); st.rerun()
    accepted = [proposal for proposal in proposals if proposal["status"] == "accepted"]
    if accepted:
        st.markdown("### Подтверждение этапа работы")
        chosen = st.selectbox("Команда", accepted, format_func=lambda item: team_name(item["team_id"]))
        already_confirmed = any(item["proposal_id"] == chosen["id"] for item in state()["progress"])
        if already_confirmed: st.success("Первый milestone этой команды уже подтверждён.")
        elif st.button("Подтвердить первый milestone · +10 баллов"):
            state()["progress"].append({"proposal_id": chosen["id"], "team_id": chosen["team_id"], "points": 10, "date": str(date.today())})
            persist(); st.success(f"Milestone подтверждён. {team_name(chosen['team_id'])} получает 10 баллов.")


with st.sidebar:
    st.markdown("## ✦ AI Sana")
    st.caption("Challenge Hub")
    page = st.radio("Раздел", ["Overview", "Challenge Studio", "Marketplace", "Collaboration Desk"], format_func=lambda value: {"Overview": "Обзор", "Challenge Studio": "Создать задачу", "Marketplace": "Каталог", "Collaboration Desk": "Отклики и выбор"}[value], label_visibility="collapsed")
    st.divider(); st.markdown("**Демонстрация**")
    st.caption("Синтетические данные. Реальные ключи и персональные данные не сохраняются.")
    if st.button("Сбросить демоданные", use_container_width=True):
        st.session_state.hub_state = reset_state()
        for key in ["agent_result", "card_result", "candidate_card", "selected_task_id", "human_confirmation"]: st.session_state.pop(key, None)
        st.rerun()

if page == "Overview": overview()
elif page == "Challenge Studio": challenge_studio()
elif page == "Marketplace": marketplace()
else: collaboration_desk()
