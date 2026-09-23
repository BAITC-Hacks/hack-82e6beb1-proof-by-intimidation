"""Small API message catalog; developer diagnostics never reach the interface."""

from __future__ import annotations

from typing import Any

MESSAGES = {
    "The server restarted before analysis finished. Your draft is safe; retry the analysis.": ("Сервер перезапущен до завершения анализа. Черновик сохранён — запустите анализ ещё раз.", "Талдау аяқталмай сервер қайта іске қосылды. Бастапқы мәтін сақталды — талдауды қайта бастаңыз."),
    "This analysis request was already used for a different draft. Start a new analysis.": ("Этот запрос уже относится к другому черновику. Запустите новый анализ.", "Бұл сұрау басқа бастапқы мәтінге тиесілі. Жаңа талдауды бастаңыз."),
    "This analysis job is not available in this browser.": ("Этот анализ недоступен в данном браузере.", "Бұл талдау осы браузерде қолжетімсіз."),
    "This task could not be found.": ("Задача не найдена.", "Тапсырма табылмады."),
    "Only the task's creator can make this change from their original browser.": ("Это действие доступно только автору задачи в том браузере, где она была создана.", "Бұл әрекетті тек тапсырма авторы оны жасаған браузерде орындай алады."),
    "The analysis is not available in this workspace. Analyze the draft again.": ("Этот анализ недоступен в вашем рабочем пространстве. Проанализируйте черновик ещё раз.", "Бұл талдау жұмыс кеңістігіңізде қолжетімсіз. Бастапқы мәтінді қайта талдаңыз."),
    "Give your task a title of at least three characters before publishing.": ("Перед публикацией введите название задачи — не менее трёх символов.", "Жариялау алдында тапсырманың атауын енгізіңіз — кемінде үш таңба."),
    "Describe the current situation or the business need before publishing.": ("Перед публикацией опишите текущую ситуацию или потребность бизнеса.", "Жариялау алдында ағымдағы жағдайды немесе бизнес қажеттілігін сипаттаңыз."),
    "This request must come from the Challenge Hub website.": ("Откройте Challenge Hub и повторите действие на сайте.", "Challenge Hub сайтын ашып, әрекетті сол жерде қайталаңыз."),
    "Please check the highlighted information and try again.": ("Проверьте введённые данные и попробуйте ещё раз.", "Енгізілген ақпаратты тексеріп, қайта көріңіз."),
    "Storage is temporarily busy. Your change was not saved; please try again.": ("Хранилище временно занято. Изменения не сохранены — попробуйте ещё раз.", "Деректер қоймасы уақытша бос емес. Өзгерістер сақталмады — қайта көріңіз."),
    "This change conflicts with an existing record. Refresh and try again.": ("Запись уже изменилась. Обновите страницу и повторите действие.", "Жазба өзгертілген. Бетті жаңартып, әрекетті қайталаңыз."),
    "This task changed in another tab. Refresh before saving your edits.": ("Задача изменена в другой вкладке. Обновите страницу перед сохранением.", "Тапсырма басқа қойындыда өзгертілген. Сақтау алдында бетті жаңартыңыз."),
    "This task changed while you were editing. Refresh and try again.": ("Задача изменилась во время редактирования. Обновите страницу и повторите действие.", "Өңдеу кезінде тапсырма өзгертілген. Бетті жаңартып, қайта көріңіз."),
    "Choose an existing sample team or enter your own team's name.": ("Выберите демонстрационную команду или введите название своей.", "Үлгі команданы таңдаңыз немесе өз командаңыздың атауын енгізіңіз."),
    "Enter your team's name before submitting a proposal.": ("Перед отправкой предложения введите название команды.", "Ұсыныс жібермес бұрын команданың атауын енгізіңіз."),
    "This proposal could not be found.": ("Предложение команды не найдено.", "Команданың ұсынысы табылмады."),
    "A team with confirmed progress remains accepted; its recorded work cannot be revoked here.": ("У команды уже есть подтверждённый результат. Отменить выбор после начисления баллов нельзя.", "Команданың расталған нәтижесі бар. Ұпай берілгеннен кейін таңдауды жою мүмкін емес."),
    "Choose this team before confirming its completed milestone.": ("Сначала выберите команду, затем подтвердите выполненный этап.", "Алдымен команданы таңдаңыз, содан кейін орындалған кезеңді растаңыз."),
    "Progress has already been confirmed for this proposal. Points are awarded once.": ("Этап уже подтверждён. Баллы за этот результат начисляются один раз.", "Кезең расталып қойған. Бұл нәтиже үшін ұпай бір рет беріледі."),
    "Unknown API endpoint.": ("Запрошенный адрес не найден.", "Сұралған мекенжай табылмады."),
    "Page not found.": ("Страница не найдена.", "Бет табылмады."),
    "Frontend is not built. Run npm install and npm run build in frontend/, or use the Vite development server.": ("Интерфейс ещё не собран. Выполните npm install и npm run build в frontend/ или запустите сервер разработки Vite.", "Интерфейс әлі құрастырылмаған. frontend/ ішінде npm install және npm run build орындаңыз немесе Vite серверін іске қосыңыз."),
    "Unknown card field. Only the ten task-card fields are supported.": ("В карточке есть неизвестное поле. Используйте поля формы задачи.", "Карточкада белгісіз өріс бар. Тапсырма нысанындағы өрістерді пайдаланыңыз."),
    "The card is too long. Limit each field to 4,000 characters and the card to 24,000.": ("Карточка слишком длинная: до 4 000 символов в поле и до 24 000 в сумме.", "Карточка тым ұзын: бір өрісте 4 000, барлығы 24 000 таңбаға дейін."),
    "Use a title of at most 180 characters.": ("Сократите название до 180 символов.", "Атауды 180 таңбаға дейін қысқартыңыз."),
    "Use at most 4,000 characters in each answer.": ("Допускается не более 4 000 символов в каждом ответе.", "Әр жауапта 4 000 таңбадан артық болмауы керек."),
    "The answers must total at most 24,000 characters.": ("Суммарная длина ответов не должна превышать 24 000 символов.", "Жауаптардың жалпы ұзындығы 24 000 таңбадан аспауы керек."),
    "Provide a full http:// or https:// prototype link without credentials.": ("Укажите полную ссылку на прототип с http:// или https://, без логина и пароля.", "Прототипке http:// немесе https:// арқылы толық сілтеме беріңіз, логин мен құпиясөзді қоспаңыз."),
    "Analysis is already running in this browser. Wait for it to finish.": ("Анализ уже выполняется в этом браузере. Дождитесь результата.", "Бұл браузерде талдау орындалып жатыр. Нәтижесін күтіңіз."),
    "Too many analysis requests. Wait a minute before trying again.": ("Слишком много запросов на анализ. Подождите минуту и повторите попытку.", "Талдау сұраулары тым көп. Бір минут күтіп, қайта көріңіз."),
    "All analysis slots are busy. Please try again shortly.": ("Сейчас выполняется много анализов. Повторите попытку чуть позже.", "Қазір көптеген талдау орындалып жатыр. Сәл кейінірек қайта көріңіз."),
    "AI is not connected. Configure the server or choose the labelled offline check.": ("AI пока не подключён. Настройте подключение на сервере или выберите офлайн-проверку.", "AI әлі қосылмаған. Сервердегі қосылымды баптаңыз немесе офлайн тексеруді таңдаңыз."),
    "The AI answer failed fact validation. Your text is preserved; retry or choose the labelled offline check.": ("Ответ AI не прошёл проверку фактов. Ваш текст сохранён: повторите анализ или выберите офлайн-проверку.", "AI жауабы деректерді тексеруден өтпеді. Мәтініңіз сақталды: талдауды қайталаңыз немесе офлайн тексеруді таңдаңыз."),
    "AI is unavailable. Your text is preserved; retry later or choose the labelled offline check.": ("AI сейчас недоступен. Ваш текст сохранён: повторите позже или выберите офлайн-проверку.", "AI қазір қолжетімсіз. Мәтініңіз сақталды: кейін қайталаңыз немесе офлайн тексеруді таңдаңыз."),
    "Describe the task in words in English, Kazakh or Russian.": ("Опишите задачу словами на русском, казахском или английском языке.", "Тапсырманы қазақша, орысша немесе ағылшынша сөзбен сипаттаңыз."),
    "This information is required.": ("Заполните это поле.", "Бұл өрісті толтырыңыз."),
    "This field is not supported.": ("Такое поле не поддерживается.", "Бұл өріске қолдау көрсетілмейді."),
    "Confirm the card before publishing.": ("Подтвердите карточку перед публикацией.", "Жариялау алдында карточканы растаңыз."),
    "Choose one of the available options.": ("Выберите одно из доступных значений.", "Қолжетімді нұсқалардың бірін таңдаңыз."),
    "Enter text in this field.": ("Введите текст в это поле.", "Бұл өріске мәтін енгізіңіз."),
    "Check this field's value.": ("Проверьте значение этого поля.", "Бұл өрістің мәнін тексеріңіз."),
}


def language_from_header(value: str) -> str:
    candidates = []
    for index, item in enumerate(value.split(",")):
        parts = item.strip().lower().split(";")
        language = parts[0].split("-")[0]
        if language not in {"ru", "kk", "en"}:
            continue
        try:
            quality = float(next((part[2:] for part in parts[1:] if part.startswith("q=")), "1"))
        except ValueError:
            quality = 0
        if quality > 0:
            candidates.append((quality, -index, language))
    return max(candidates)[2] if candidates else "ru"


def translate(message: str, language: str = "ru") -> str:
    if language == "en" or message not in MESSAGES:
        return message
    return MESSAGES[message][1 if language == "kk" else 0]


def analysis_failure(message: str, language: str, code: str | None = None) -> str:
    if code == "not_configured" or any(fragment in message for fragment in ("not connected", "не подключён", "қосылмаған")):
        key = "AI is not connected. Configure the server or choose the labelled offline check."
    elif code == "validation_failed" or any(fragment in message for fragment in ("fact validation", "проверку фактов", "деректерді тексеруден")):
        key = "The AI answer failed fact validation. Your text is preserved; retry or choose the labelled offline check."
    else:
        key = "AI is unavailable. Your text is preserved; retry later or choose the labelled offline check."
    return translate(key, language)


def validation_message(item: dict[str, Any], language: str) -> str:
    kind, context = item["type"], item.get("ctx", {})
    if kind == "value_error":
        return translate(item["msg"].removeprefix("Value error, "), language)
    if kind in {"string_too_short", "string_too_long"}:
        minimum = kind == "string_too_short"
        limit = context.get("min_length" if minimum else "max_length", "")
        templates = {
            "ru": "Введите не менее {n} символов." if minimum else "Сократите текст до {n} символов.",
            "kk": "Кемінде {n} таңба енгізіңіз." if minimum else "Мәтінді {n} таңбаға дейін қысқартыңыз.",
            "en": "Enter at least {n} characters." if minimum else "Use at most {n} characters.",
        }
        return templates[language].format(n=limit)
    if kind == "literal_error":
        return translate("Confirm the card before publishing." if "confirmed" in item["loc"] else "Choose one of the available options.", language)
    return translate({
        "missing": "This information is required.", "extra_forbidden": "This field is not supported.",
        "string_type": "Enter text in this field.",
    }.get(kind, "Check this field's value."), language)
