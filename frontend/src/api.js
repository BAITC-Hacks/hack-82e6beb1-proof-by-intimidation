export async function api(path, options = {}) {
  let language = 'ru';
  try { language = localStorage.getItem('sana-language') || 'ru'; } catch { /* Use the default language when storage is unavailable. */ }
  const messages = {
    ru: { network: 'Не удалось связаться с сервером. Проверьте подключение и доступность приложения.', timeout: 'Превышено время ожидания ответа сервера.', invalid: 'Сервер вернул некорректный ответ. Повторите позже.', cancelled: 'Запрос отменён.', check: 'Перед повторной отправкой проверьте, сохранился ли результат.' },
    en: { network: 'Could not reach the server. Check your connection and that the app is running.', timeout: 'The server response timed out.', invalid: 'The server returned an invalid response. Try again later.', cancelled: 'Request cancelled.', check: 'Before sending again, check whether your changes were saved.' },
    kk: { network: 'Сервермен байланысу мүмкін болмады. Қосылымды және қолданбаның жұмысын тексеріңіз.', timeout: 'Сервер жауабын күту уақыты аяқталды.', invalid: 'Сервер қате жауап қайтарды. Кейін қайталаңыз.', cancelled: 'Сұрау тоқтатылды.', check: 'Қайта жібермес бұрын нәтиженің сақталғанын тексеріңіз.' },
  }[language] || { network: 'Could not reach the server.', timeout: 'The server response timed out.', invalid: 'The server returned an invalid response.', cancelled: 'Request cancelled.', check: 'Check whether your changes were saved before sending again.' };
  const { timeoutMs = 180000, signal: externalSignal, ...requestOptions } = options;
  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort();
  if (externalSignal?.aborted) controller.abort();
  else externalSignal?.addEventListener('abort', abortFromCaller, { once: true });
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, Math.min(180000, Math.max(1, Number(timeoutMs) || 180000)));
  try {
    const response = await fetch(`/api${path}`, {
      credentials: 'include',
      ...requestOptions,
      headers: { 'Content-Type': 'application/json', 'Accept-Language': language, ...requestOptions.headers },
      body: requestOptions.body === undefined ? undefined : JSON.stringify(requestOptions.body),
      signal: controller.signal,
    });
    let data;
    try { data = await response.json(); }
    catch (error) { if (controller.signal.aborted || response.ok) throw error; data = {}; }
    if (!response.ok) {
      const detail = data?.detail ?? data?.message ?? `HTTP ${response.status}`;
      const message = Array.isArray(detail)
        ? detail.map(item => `${(item.loc || []).filter(x => x !== 'body').join('.')}: ${item.msg}`).join('\n')
        : typeof detail === 'object' ? detail.message || detail.error || JSON.stringify(detail) : detail;
      const error = new Error(message);
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.status) throw error;
    const key = timedOut ? 'timeout' : controller.signal.aborted ? 'cancelled' : error instanceof SyntaxError ? 'invalid' : 'network';
    const write = !['GET','HEAD'].includes((requestOptions.method || 'GET').toUpperCase());
    const message = `${messages[key]}${write ? ` ${messages.check}` : ''}`;
    const friendlyError = new Error(message);
    friendlyError.code = key;
    throw friendlyError;
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener('abort', abortFromCaller);
  }
}

export function safeLink(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}
