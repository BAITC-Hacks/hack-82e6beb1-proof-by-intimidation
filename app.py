from __future__ import annotations

from datetime import date

import streamlit as st

from agent.core import run_task_agent
from rating import CARD_FIELDS, calculate_rating
from storage import load_state, next_id, reset_state, save_state

st.set_page_config(page_title="AI Sana Challenge Hub", page_icon="🎓", layout="wide")


def state() -> dict:
    if "hub_state" not in st.session_state:
        st.session_state.hub_state = load_state()
    return st.session_state.hub_state


def persist() -> None:
    save_state(state())


def team_name(team_id: str) -> str:
    return next((team["name"] for team in state()["teams"] if team["id"] == team_id), team_id)


def render_rating(rating: dict) -> None:
    st.metric("Рейтинг готовности", f"{rating['score']} / 100", rating["level"])
    st.progress(rating["score"])
    with st.expander("Расшифровка рейтинга"):
        for item in rating["breakdown"]:
            st.write(f"{item['field']}: **{item['earned']} / {item['max']}**")
        if rating["improvements"]:
            st.caption(" ".join(rating["improvements"]))


st.title("🎓 AI Sana Challenge Hub")
st.caption("Из сырой бизнес-задачи — в понятную возможность для студенческой команды.")

with st.sidebar:
    st.subheader("Демо-данные")
    if st.button("Сбросить к исходным данным"):
        st.session_state.hub_state = reset_state()
        st.session_state.pop("agent_result", None)
        st.session_state.pop("editable_card", None)
        st.rerun()
    st.caption("Все имена и данные в демо синтетические.")

create_tab, catalog_tab, decisions_tab = st.tabs(["1. Создать задачу", "2. Каталог и отклик", "3. Решение бизнеса"])

with create_tab:
    st.subheader("Черновик бизнес-задачи")
    sample = "Хотим помочь первокурсникам быстрее находить полезные практические задания."
    draft = st.text_area("Опишите потребность, проблему или задачу", value=st.session_state.get("draft", sample), height=120)
    if st.button("AI: найти недостающие сведения и вопросы", type="primary"):
        if len(draft.strip()) < 10:
            st.error("Опишите задачу хотя бы в 10 символах.")
        elif len(draft) > 5000:
            st.error("Черновик слишком длинный: максимум 5000 символов.")
        else:
            st.session_state.draft = draft
            with st.spinner("AI анализирует черновик..."):
                st.session_state.agent_result = run_task_agent(draft)
            st.session_state.pop("editable_card", None)

    result = st.session_state.get("agent_result")
    if result:
        if result["mode"] == "offline":
            st.warning(result["message"])
        else:
            st.success("AI-анализ выполнен.")
        st.write("**Уточняющие вопросы:**")
        for number, question in enumerate(result["questions"], start=1):
            st.write(f"{number}. {question}")
        with st.expander("Журнал шагов агента"):
            for step in result["steps"]:
                st.write(f"**{step['tool']}**")
                st.json(step["result"])

        st.subheader("Ответьте и соберите редактируемую карточку")
        with st.form("answers_form"):
            answers = {}
            for field, label in CARD_FIELDS.items():
                if field in {"title", "contact", "interaction_format"}:
                    answers[field] = st.text_input(label, value=result["card"].get(field, ""))
                else:
                    answers[field] = st.text_area(label, value=result["card"].get(field, ""), height=75)
            make_card = st.form_submit_button("Сформировать карточку и пересчитать")
        if make_card:
            with st.spinner("AI собирает карточку только из указанных фактов..."):
                final_result = run_task_agent(st.session_state.draft, answers)
            st.session_state.agent_result = final_result
            st.session_state.editable_card = final_result["card"]
            st.rerun()

    card = st.session_state.get("editable_card")
    if card:
        st.subheader("Проверьте карточку перед публикацией")
        with st.form("publish_form"):
            edited = {field: st.text_area(label, value=card.get(field, ""), height=70) for field, label in CARD_FIELDS.items()}
            topic = st.selectbox("Тема", ["Образование", "EdTech", "Аналитика", "Коммуникации"])
            confirmed = st.checkbox("Подтверждаю, что заполненные сведения верны и могут быть опубликованы.")
            publish = st.form_submit_button("Подтвердить и опубликовать", type="primary")
        preview = dict(edited)
        preview["confirmed_fields"] = [field for field, value in edited.items() if value.strip()] if confirmed else []
        render_rating(calculate_rating(preview))
        if publish:
            if not confirmed:
                st.error("Для публикации нужно ручное подтверждение карточки.")
            elif not edited["title"].strip() or not edited["context"].strip() or not edited["need"].strip():
                st.error("Заполните как минимум название, контекст и потребность.")
            else:
                task_rating = calculate_rating(preview)
                task = dict(preview, id=next_id(state()["tasks"], "t"), topic=topic, published=True, current_score=task_rating["score"])
                state()["tasks"].append(task)
                persist()
                st.success(f"Задача опубликована. Рейтинг: {task_rating['score']} / 100.")

with catalog_tab:
    st.subheader("Общий каталог задач")
    all_tasks = [task for task in state()["tasks"] if task.get("published")]
    topics = sorted({task.get("topic", "Другое") for task in all_tasks})
    levels = ["Все", "Черновик", "Рабочая", "Готовая", "Приоритетная"]
    col1, col2 = st.columns(2)
    selected_topic = col1.selectbox("Тема", ["Все"] + topics)
    selected_level = col2.selectbox("Уровень готовности", levels)
    filtered = []
    for task in all_tasks:
        rating = calculate_rating(task)
        if selected_topic != "Все" and task.get("topic") != selected_topic:
            continue
        if selected_level != "Все" and rating["level"] != selected_level:
            continue
        filtered.append((task, rating))
    for task, rating in sorted(filtered, key=lambda item: item[1]["score"], reverse=True):
        with st.container(border=True):
            st.subheader(task["title"])
            st.caption(f"{task.get('topic', 'Другое')} · {rating['level']} · {rating['score']} / 100")
            st.write(task["need"])
            if rating["missing"]:
                st.info("Требует уточнения: " + ", ".join(rating["missing"]))
            with st.expander("Подробнее и отправить предложение"):
                st.write("**Ожидаемый результат:**", task["expected_result"] or "Не указан")
                st.write("**Ограничения:**", task["constraints"] or "Не указаны")
                with st.form(f"proposal_{task['id']}"):
                    team = st.selectbox("Команда", state()["teams"], format_func=lambda item: item["name"], key=f"team_{task['id']}")
                    idea = st.text_area("Идея решения", key=f"idea_{task['id']}")
                    plan = st.text_area("План", key=f"plan_{task['id']}")
                    deadline = st.text_input("Срок", value="10 дней", key=f"deadline_{task['id']}")
                    link = st.text_input("Ссылка на прототип", value="https://example.com", key=f"link_{task['id']}")
                    send = st.form_submit_button("Отправить предложение")
                if send:
                    if not all([idea.strip(), plan.strip(), deadline.strip(), link.strip()]):
                        st.error("Заполните идею, план, срок и ссылку.")
                    else:
                        state()["proposals"].append({"id": next_id(state()["proposals"], "p"), "task_id": task["id"], "team_id": team["id"], "idea": idea.strip(), "plan": plan.strip(), "deadline": deadline.strip(), "link": link.strip(), "status": "submitted"})
                        persist()
                        st.success("Предложение отправлено. Бизнес увидит его в разделе решений.")

with decisions_tab:
    st.subheader("Ручной выбор бизнеса")
    business_tasks = state()["tasks"]
    selected = st.selectbox("Задача", business_tasks, format_func=lambda item: item["title"])
    proposals = [proposal for proposal in state()["proposals"] if proposal["task_id"] == selected["id"]]
    if not proposals:
        st.info("Для этой задачи пока нет предложений.")
    for proposal in proposals:
        with st.container(border=True):
            st.write(f"**{team_name(proposal['team_id'])}** · статус: `{proposal['status']}`")
            st.write(proposal["idea"])
            st.caption(f"План: {proposal['plan']} · Срок: {proposal['deadline']} · {proposal['link']}")
            col_a, col_b = st.columns(2)
            if col_a.button("Выбрать команду", key=f"accept_{proposal['id']}"):
                proposal["status"] = "accepted"
                persist()
                st.success("Команда выбрана вручную.")
            if col_b.button("Отклонить", key=f"reject_{proposal['id']}"):
                proposal["status"] = "rejected"
                persist()
                st.info("Предложение отклонено вручную.")
    accepted = [proposal for proposal in proposals if proposal["status"] == "accepted"]
    if accepted:
        chosen = st.selectbox("Подтвердить прогресс выбранной команды", accepted, format_func=lambda item: team_name(item["team_id"]))
        if st.button("Подтвердить этап и начислить 10 баллов"):
            state()["progress"].append({"proposal_id": chosen["id"], "team_id": chosen["team_id"], "points": 10, "date": str(date.today())})
            persist()
            st.success(f"Прогресс подтверждён. {team_name(chosen['team_id'])} получает 10 баллов.")
