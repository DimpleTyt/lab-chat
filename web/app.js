/* lab-chat — клиентская логика. Без сборки, без внешних зависимостей. */
(function () {
  'use strict';

  var API = {
    state: '/api/state',
    login: '/api/login',
    logout: '/api/logout',
    intake: '/api/intake',
    confirm: '/api/intake/confirm',
    cancel: '/api/intake/cancel',
    chat: '/api/chat',
    next: '/api/next'
  };

  /* ─── Состояние ───────────────────────────────────────────── */

  var state = {
    user: null,
    phase: null,
    step: null,
    progress: { idx: 0, total: 0, can_advance: false },
    variant: null,
    sources: null,
    unknown: [],
    lastIntakeText: '',
    editingFromChat: false,
    cardFields: [],
    streaming: false,
    intakeBusy: false,
    atBottom: true,
    booted: false,
    model: ''
  };

  var els = {
    boot: document.getElementById('boot'),

    loginView: document.getElementById('view-login'),
    loginForm: document.getElementById('login-form'),
    loginUser: document.getElementById('login-username'),
    loginPass: document.getElementById('login-password'),
    loginError: document.getElementById('login-error'),
    loginSubmit: document.getElementById('login-submit'),

    intakeView: document.getElementById('view-intake'),
    intakeUser: document.getElementById('intake-user'),
    intakeLogout: document.getElementById('intake-logout'),
    intakeForm: document.getElementById('intake-form'),
    intakeText: document.getElementById('intake-text'),
    intakeError: document.getElementById('intake-error'),
    intakeSubmit: document.getElementById('intake-submit'),
    intakeCancel: document.getElementById('intake-cancel'),
    intakeSkip: document.getElementById('intake-skip'),
    intakeCard: document.getElementById('intake-card'),
    intakeCardError: document.getElementById('intake-card-error'),

    chatView: document.getElementById('view-chat'),
    chatUser: document.getElementById('chat-user'),
    chatLogout: document.getElementById('chat-logout'),
    chatEdit: document.getElementById('chat-edit'),
    chatStepLabel: document.getElementById('chat-step-label'),
    chatProgress: document.getElementById('chat-progress'),
    chatFeedWrap: document.getElementById('chat-feed-wrap'),
    chatFeed: document.getElementById('chat-feed'),
    chatInput: document.getElementById('chat-input'),
    chatNext: document.getElementById('chat-next'),
    chatStatus: document.getElementById('chat-status')
  };

  /* ─── Markdown ────────────────────────────────────────────── */

  var markedReady = !!(window.marked && typeof window.marked.parse === 'function');

  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  var escapeAttr = escapeHtml;

  function fallbackMarkdown(text) {
    var lines = String(text === null || text === undefined ? '' : text)
      .replace(/\r\n?/g, '\n')
      .split('\n');
    var out = [];
    var para = [];
    var list = null;
    var i = 0;

    function flushPara() {
      if (!para.length) return;
      out.push('<p>' + para.map(inlineFormat).join('<br>') + '</p>');
      para = [];
    }

    function flushList() {
      if (!list) return;
      out.push('<' + list.tag + '>' + list.items.map(function (item) {
        return '<li>' + inlineFormat(item) + '</li>';
      }).join('') + '</' + list.tag + '>');
      list = null;
    }

    function flush() {
      flushPara();
      flushList();
    }

    while (i < lines.length) {
      var line = lines[i];
      var fence = /^```\s*([A-Za-z0-9_+.#-]*)\s*$/.exec(line);

      if (fence) {
        flush();
        i += 1;
        var code = [];
        while (i < lines.length && !/^```/.test(lines[i])) {
          code.push(lines[i]);
          i += 1;
        }
        if (i < lines.length) i += 1;
        out.push('<pre><code class="language-' + escapeAttr(fence[1] || 'text') + '">' +
          escapeHtml(code.join('\n')) + '</code></pre>');
        continue;
      }

      if (!line.trim()) {
        flush();
        i += 1;
        continue;
      }

      var heading = /^(#{1,4})\s+(.*)$/.exec(line);
      if (heading) {
        flush();
        var level = heading[1].length;
        out.push('<h' + level + '>' + inlineFormat(heading[2]) + '</h' + level + '>');
        i += 1;
        continue;
      }

      var bullet = /^\s*[-*]\s+(.*)$/.exec(line);
      var numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
      if (bullet || numbered) {
        flushPara();
        var tag = bullet ? 'ul' : 'ol';
        if (!list || list.tag !== tag) {
          flushList();
          list = { tag: tag, items: [] };
        }
        list.items.push((bullet || numbered)[1]);
        i += 1;
        continue;
      }

      flushList();
      para.push(line.trim());
      i += 1;
    }

    flush();
    return out.join('\n');
  }

  function inlineFormat(text) {
    var s = escapeHtml(text);
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    return s;
  }

  function sanitizeHtml(html) {
    var tpl = document.createElement('template');
    tpl.innerHTML = html || '';
    var forbidden = tpl.content.querySelectorAll(
      'script,style,iframe,frame,frameset,object,embed,form,input,button,link,meta,base,img,picture,video,audio,source,track,svg,math'
    );
    for (var i = 0; i < forbidden.length; i += 1) {
      forbidden[i].parentNode.removeChild(forbidden[i]);
    }
    var all = tpl.content.querySelectorAll('*');
    for (var j = 0; j < all.length; j += 1) {
      var node = all[j];
      var attrs = Array.prototype.slice.call(node.attributes || []);
      for (var k = 0; k < attrs.length; k += 1) {
        var name = attrs[k].name.toLowerCase();
        var value = attrs[k].value;
        if (name.indexOf('on') === 0) {
          node.removeAttribute(attrs[k].name);
        } else if ((name === 'href' || name === 'src' || name === 'xlink:href') &&
                   /^\s*(javascript|data|vbscript):/i.test(value)) {
          node.removeAttribute(attrs[k].name);
        }
      }
    }
    return tpl.innerHTML;
  }

  function renderMarkdown(text) {
    var source = text === null || text === undefined ? '' : String(text);
    var html = '';
    if (markedReady) {
      try {
        html = window.marked.parse(source, { gfm: true, breaks: true });
      } catch (e) {
        html = fallbackMarkdown(source);
      }
    } else {
      html = fallbackMarkdown(source);
    }
    return sanitizeHtml(html);
  }

  /* ─── HTTP ────────────────────────────────────────────────── */

  function errorMessage(data, status) {
    if (data && data.error) {
      if (typeof data.error === 'string') return data.error;
      if (data.error.message) return data.error.message;
    }
    if (status === 401) return 'Нужно войти заново';
    if (status === 403) return 'Доступ запрещён';
    if (status === 404) return 'Сервер не нашёл запрос';
    if (status === 422) return 'Сервер не принял данные';
    if (status === 0) return 'Сервер не ответил';
    return 'Ошибка сервера (' + status + ')';
  }

  async function api(url, options) {
    options = options || {};
    var init = {
      method: options.method || 'GET',
      credentials: 'same-origin',
      headers: {}
    };
    if (options.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(options.body);
    }

    var timer = null;
    if (options.timeout) {
      var controller = new AbortController();
      init.signal = controller.signal;
      timer = setTimeout(function () {
        controller.abort();
      }, options.timeout);
    }

    var res;
    try {
      res = await fetch(url, init);
    } catch (err) {
      if (err && err.name === 'AbortError') {
        var aborted = new Error('Сервер не ответил');
        aborted.status = 0;
        throw aborted;
      }
      var netErr = new Error('Нет связи с сервером');
      netErr.status = 0;
      netErr.cause = err;
      throw netErr;
    } finally {
      if (timer) clearTimeout(timer);
    }

    var data = null;
    if (res.status !== 204) {
      var raw = await res.text();
      if (raw) {
        try {
          data = JSON.parse(raw);
        } catch (e) {
          data = { raw: raw };
        }
      }
    }

    if (!res.ok) {
      var error = new Error(errorMessage(data, res.status));
      error.status = res.status;
      error.code = data && data.error && data.error.code;
      error.data = data;
      throw error;
    }
    return data;
  }

  /* ─── DOM-хелперы ─────────────────────────────────────────── */

  function show(node) {
    if (node) node.hidden = false;
  }

  function hide(node) {
    if (node) node.hidden = true;
  }

  function setError(node, message) {
    if (!node) return;
    if (!message) {
      node.textContent = '';
      node.hidden = true;
      return;
    }
    node.textContent = message;
    node.hidden = false;
  }

  function showCardError(message) {
    setError(els.intakeCardError, message);
    if (message && els.intakeCardError) {
      try {
        els.intakeCardError.scrollIntoView({ block: 'nearest' });
      } catch (e) { /* старые браузеры */ }
    }
  }

  /* ─── Простой по бездействию: час ─────────────────────────── */
  var IDLE_MS = 60 * 60 * 1000;
  var idleTimer = 0;

  function armIdle() {
    if (idleTimer) clearTimeout(idleTimer);
    if (!state.user) return;
    idleTimer = setTimeout(function () {
      idleTimer = 0;
      if (!state.user) return;
      try { api(API.logout, { method: 'POST', timeout: 5000 }); } catch (e) { /* ignore */ }
      state.user = null;
      showView('login');
      setError(els.loginError, 'Час без действий — войди снова');
    }, IDLE_MS);
  }

  ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'].forEach(function (name) {
    document.addEventListener(name, armIdle, { passive: true });
  });

  /* ─── Синхронизация с сервером между вкладками/клиентами ──── */
  var lastSyncAt = 0;

  async function syncProgress() {
    if (!state.user || state.streaming) return;
    if (document.visibilityState !== 'visible') return;
    var now = Date.now();
    if (now - lastSyncAt < 5000) return;
    lastSyncAt = now;

    try {
      var data = await api(API.state, { timeout: 10000 });
      if (data && data.progress) applyProgress(data.progress);
      var serverNum = data && data.step ? data.step.num : 0;
      var localNum = state.step ? state.step.num : 0;
      if (!serverNum || serverNum === localNum) return;

      state.phase = data.phase || state.phase;
      state.variant = data.variant || state.variant;
      appendSystem('Прогресс изменился в другом окне — шаг ' + serverNum + '.');
      setStep(data.step, { scroll: true });
    } catch (err) {
      if (err.status === 401) {
        forceLogin('Сессия истекла, войди снова');
      }
    }
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') syncProgress();
  });
  window.addEventListener('focus', syncProgress);

  function showView(name) {
    state.booted = true;
    state.view = name;
    hide(els.boot);
    hide(els.loginView);
    hide(els.intakeView);
    hide(els.chatView);

    if (name === 'login') {
      show(els.loginView);
      document.title = 'lab-chat';
      setTimeout(function () {
        if (els.loginUser && !els.loginUser.value) els.loginUser.focus();
      }, 40);
    } else if (name === 'intake') {
      show(els.intakeView);
      document.title = 'lab-chat — задание';
    } else {
      show(els.chatView);
      document.title = 'lab-chat — чат';
      setTimeout(function () {
        autosize();
        scrollToBottom(true);
        if (!state.streaming) els.chatInput.focus();
      }, 40);
    }
  }

  function displayName(user) {
    if (!user) return '';
    if (typeof user === 'string') return user;
    return user.display_name || user.displayName || user.username || user.name || '';
  }

  function applyUser() {
    var name = displayName(state.user);
    els.intakeUser.textContent = name;
    els.chatUser.textContent = name;
  }

  /* ─── Вход ────────────────────────────────────────────────── */

  async function onLogin(event) {
    event.preventDefault();

    var username = els.loginUser.value.trim();
    var password = els.loginPass.value;
    if (!username || !password) {
      setError(els.loginError, 'Введи логин и пароль');
      return;
    }

    setError(els.loginError, '');
    els.loginSubmit.disabled = true;
    els.loginSubmit.textContent = 'Вход…';

    try {
      var data = await api(API.login, {
        method: 'POST',
        body: { username: username, password: password },
        timeout: 15000
      });
      state.user = (data && data.user) || username;
      applyUser();
      armIdle();
      state.lastIntakeText = '';
      state.cardFields = [];
      els.intakeText.value = '';
      els.loginPass.value = '';
      await loadState();
    } catch (err) {
      setError(els.loginError, err.status === 401 ? 'Неверный логин или пароль' : err.message);
    } finally {
      els.loginSubmit.disabled = false;
      els.loginSubmit.textContent = 'Войти';
    }
  }

  async function logout() {
    try {
      await api(API.logout, { method: 'POST', timeout: 8000 });
    } catch (e) {
      /* даже если сервер не ответил, локально выходим */
    }
    resetClient();
    showView('login');
  }

  function resetClient() {
    state.user = null;
    state.phase = null;
    state.step = null;
    state.variant = null;
    state.sources = null;
    state.unknown = [];
    state.progress = { idx: 0, total: 0, can_advance: false };
    state.streaming = false;
    state.intakeBusy = false;
    state.lastIntakeText = '';
    state.editingFromChat = false;
    state.cardFields = [];
    state.model = '';

    clearFeed();
    els.chatInput.value = '';
    els.chatInput.disabled = false;
    els.chatInput.style.height = '';
    els.intakeText.value = '';
    els.intakeCard.hidden = true;
    els.intakeCard.innerHTML = '';
    els.intakeForm.hidden = false;
    els.chatProgress.style.width = '0%';
    els.chatStatus.textContent = '';
    els.chatStepLabel.textContent = 'Шаг 0/0';
    els.chatStepLabel.removeAttribute('title');
    els.loginForm.reset();
    setError(els.loginError, '');
    setError(els.intakeError, '');
    setError(els.intakeCardError, '');
    syncNextButton();
  }

  /* ─── Состояние с сервера ─────────────────────────────────── */

  function forceLogin(message) {
    resetClient();
    showView('login');
    if (message) setError(els.loginError, message);
  }

  async function loadState() {
    try {
      var data = await api(API.state, { timeout: 12000 });
      applyState(data);
    } catch (err) {
      if (err.status === 401) {
        forceLogin('');
        return;
      }
      forceLogin(err.message);
    }
  }

  function applyState(data) {
    if (!data || typeof data !== 'object') {
      showView('login');
      return;
    }

    state.user = data.user || state.user;
    applyUser();
    armIdle();
    state.phase = data.phase || 'intake';
    state.variant = data.variant || null;
    state.sources = data.sources || null;
    state.unknown = data.unknown || [];
    if (data.intake_text) state.lastIntakeText = data.intake_text;

    applyProgress(data.progress);

    if (data.step) {
      state.step = data.step;
      updateHeader(data.step);
    } else {
      state.step = null;
      resetHeader();
    }

    if (state.phase === 'chat') {
      clearFeed();
      if (data.step) {
        appendStep(data.step, { scroll: false });
      } else {
        appendSystem('Шаг пока не начат.');
      }
      showView('chat');
    } else if (state.phase === 'confirm') {
      renderIntakeCard(data.variant, data.sources, data.unknown, []);
      showView('intake');
    } else {
      showIntakeForm();
      showView('intake');
    }
  }

  /* ─── Задание ─────────────────────────────────────────────── */

  function showIntakeForm() {
    els.intakeForm.hidden = false;
    els.intakeCard.hidden = true;
    els.intakeCard.innerHTML = '';
    state.cardFields = [];
    setError(els.intakeCardError, '');
    els.intakeCancel.hidden = !state.editingFromChat;
    if (!els.intakeText.value && state.lastIntakeText) {
      els.intakeText.value = state.lastIntakeText;
    }
    setTimeout(function () {
      els.intakeText.focus();
      var len = els.intakeText.value.length;
      try {
        els.intakeText.setSelectionRange(len, len);
      } catch (e) { /* поле ещё не в фокусе */ }
    }, 40);
  }

  function startAssignmentEdit() {
    state.editingFromChat = true;
    showIntakeForm();
    showView('intake');
  }

  async function cancelAssignmentEdit() {
    if (!state.editingFromChat) return;
    try {
      var data = await api(API.cancel, { method: 'POST', body: {}, timeout: 10000 });
      state.editingFromChat = false;
      els.intakeCancel.hidden = true;
      els.intakeText.value = '';
      state.phase = (data && data.phase) || 'chat';
      if (data && data.step) {
        state.step = data.step;
        updateHeader(data.step);
      }
      if (data && data.progress) applyProgress(data.progress);
      showView(state.phase === 'chat' ? 'chat' : 'intake');
      if (state.phase !== 'chat') showIntakeForm();
    } catch (err) {
      setError(els.intakeCardError, err.message);
    }
  }

  function skipIntake() {
    els.intakeText.value = 'без задания';
    submitIntake();
  }

  function setIntakeBusy(busy) {
    state.intakeBusy = busy;
    els.intakeSubmit.disabled = busy;
    els.intakeSubmit.textContent = busy ? 'Разбираю…' : 'Разобрать';
    els.intakeText.disabled = busy;

    var buttons = els.intakeCard.querySelectorAll('.card-actions .btn');
    for (var i = 0; i < buttons.length; i += 1) buttons[i].disabled = busy;

    var inputs = els.intakeCard.querySelectorAll('.card-input');
    for (var j = 0; j < inputs.length; j += 1) inputs[j].disabled = busy;
  }

  async function submitIntake() {
    if (state.intakeBusy) return;
    var text = els.intakeText.value.trim();
    if (!text) {
      setError(els.intakeError, 'Вставь текст задания');
      return;
    }

    state.lastIntakeText = text;
    setError(els.intakeError, '');
    setError(els.intakeCardError, '');
    setIntakeBusy(true);

    try {
      var data = await api(API.intake, {
        method: 'POST',
        body: { text: text },
        timeout: 90000
      });
      state.phase = 'confirm';
      state.variant = (data && data.variant) || state.variant;
      state.sources = (data && data.sources) || null;
      state.unknown = (data && data.unknown) || [];
      renderIntakeCard(
        state.variant,
        state.sources,
        state.unknown,
        (data && data.warnings) || []
      );
    } catch (err) {
      if (err.status === 401) {
        forceLogin('Сессия истекла, войди снова');
      } else {
        setError(els.intakeError, err.message);
      }
    } finally {
      setIntakeBusy(false);
    }
  }

  async function confirmIntake() {
    if (state.intakeBusy) return;

    setError(els.intakeCardError, '');
    var variant = readCardVariant();
    if (variant === null) return;

    state.variant = variant;
    setIntakeBusy(true);

    try {
      var data = await api(API.confirm, {
        method: 'POST',
        body: { variant: variant },
        timeout: 30000
      });
      state.cardFields = [];
      state.editingFromChat = false;
      state.phase = 'chat';
      clearFeed();
      if (data && data.progress) applyProgress(data.progress);
      if (data && data.step) {
        state.step = data.step;
        updateHeader(data.step);
        appendStep(data.step, { scroll: false });
      } else {
        appendSystem('Шаг пока не начат.');
      }
      showView('chat');
      scrollToBottom(true);
    } catch (err) {
      if (err.status === 401) {
        forceLogin('Сессия истекла, войди снова');
      } else {
        showCardError(err.message);
      }
    } finally {
      setIntakeBusy(false);
    }
  }

  /* ─── Карточка задания ────────────────────────────────────── */

  function toList(value) {
    if (value === null || value === undefined) return [];
    if (Array.isArray(value)) {
      return value.map(sourceText).filter(function (item) { return item !== ''; });
    }
    if (typeof value === 'object') {
      var out = [];
      Object.keys(value).forEach(function (key) {
        out.push(key + ': ' + valueText(value[key]));
      });
      return out;
    }
    return [String(value)];
  }

  function valueText(value) {
    if (value === null || value === undefined) return '';
    if (Array.isArray(value)) {
      return value.map(function (item) { return valueText(item); }).join(', ');
    }
    if (typeof value === 'object') {
      return Object.keys(value).map(function (key) {
        return key + ': ' + valueText(value[key]);
      }).join(', ');
    }
    return String(value);
  }

  function sourceText(item) {
    if (item === null || item === undefined) return '';
    if (typeof item === 'string') return item;
    if (Array.isArray(item)) {
      return item.map(sourceText).filter(function (part) { return part !== ''; }).join(', ');
    }
    if (typeof item === 'object') {
      var label = item.label || item.name || item.title || item.key || item.param || item.field;
      var value = item.value !== undefined ? item.value
        : (item.text !== undefined ? item.text
          : (item.result !== undefined ? item.result : undefined));
      if (label && value !== undefined) return String(label) + ': ' + valueText(value);
      if (value !== undefined) return valueText(value);
      return valueText(item);
    }
    return String(item);
  }

  var NUMBER_FIELDS = {
    'storage.raid_level': true,
    'storage.disks': true,
    'docker.port': true
  };

  function normalizeSourceEntries(sources) {
    var entries = [];

    function addEntry(raw) {
      if (raw === null || raw === undefined) return;

      if (typeof raw !== 'object' || Array.isArray(raw)) {
        entries.push({
          key: '',
          label: '',
          value: raw,
          source: 'exam',
          editable: false
        });
        return;
      }

      var key = raw.key ? String(raw.key) : '';
      var value = raw.value !== undefined ? raw.value : raw.text;

      entries.push({
        key: key,
        label: String(raw.label || raw.name || key || ''),
        value: value,
        source: String(raw.source || raw.origin || 'exam').toLowerCase(),
        editable: key !== ''
      });
    }

    if (Array.isArray(sources)) {
      sources.forEach(addEntry);
      return entries;
    }

    if (sources && typeof sources === 'object') {
      Object.keys(sources).forEach(function (key) {
        var value = sources[key];

        if (value && typeof value === 'object' && !Array.isArray(value) &&
            (value.value !== undefined || value.source !== undefined || value.label !== undefined)) {
          entries.push({
            key: key,
            label: String(value.label || key),
            value: value.value !== undefined ? value.value : value.text,
            source: String(value.source || value.origin || 'exam').toLowerCase(),
            editable: true
          });
        } else {
          entries.push({
            key: key,
            label: key,
            value: value,
            source: 'exam',
            editable: true
          });
        }
      });
    }

    return entries;
  }

  function groupSourceEntries(entries) {
    var groups = { exam: [], method: [] };

    entries.forEach(function (entry) {
      if (entry.source === 'method') groups.method.push(entry);
      else groups.exam.push(entry);
    });

    return groups;
  }

  function editValueText(value) {
    if (value === null || value === undefined) return '';
    if (Array.isArray(value)) {
      return value.map(function (item) { return valueText(item); }).join(', ');
    }
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function entryIsNumber(entry) {
    return NUMBER_FIELDS[entry.key] === true || typeof entry.value === 'number';
  }

  function entryIsList(entry) {
    return entry.key === 'modules' || Array.isArray(entry.value);
  }

  function makeEditGroup(title, entries) {
    var group = document.createElement('div');
    group.className = 'card-group';

    var head = document.createElement('p');
    head.className = 'eyebrow card-group-title';
    head.textContent = title;
    group.appendChild(head);

    entries.forEach(function (entry) {
      if (!entry.editable) {
        var staticRow = document.createElement('div');
        staticRow.className = 'card-item';
        staticRow.textContent = sourceText(entry);
        group.appendChild(staticRow);
        return;
      }

      var row = document.createElement('label');
      row.className = 'card-row';

      var label = document.createElement('span');
      label.className = 'card-row-label';
      label.textContent = entry.label || entry.key;

      var input = document.createElement('input');
      input.className = 'input card-input';
      input.type = entryIsNumber(entry) ? 'number' : 'text';
      if (input.type === 'number') {
        input.step = '1';
        input.min = '0';
      }
      input.value = editValueText(entry.value);
      input.spellcheck = false;
      input.setAttribute('aria-label', label.textContent);
      input.setAttribute('data-key', entry.key);

      row.appendChild(label);
      row.appendChild(input);
      group.appendChild(row);

      state.cardFields.push({
        key: entry.key,
        label: label.textContent,
        original: entry.value,
        numeric: entryIsNumber(entry),
        list: entryIsList(entry),
        input: input
      });
    });

    return group;
  }

  function setDeep(target, path, value) {
    var parts = String(path).split('.');
    var node = target;

    for (var i = 0; i < parts.length; i += 1) {
      var part = parts[i];
      if (part === '__proto__' || part === 'constructor' || part === 'prototype') return;
      if (i === parts.length - 1) {
        node[part] = value;
        return;
      }
      if (!node[part] || typeof node[part] !== 'object' || Array.isArray(node[part])) {
        node[part] = {};
      }
      node = node[part];
    }
  }

  function readCardVariant() {
    if (!state.cardFields.length) {
      return state.variant && typeof state.variant === 'object' ? state.variant : {};
    }

    var variant = {};
    var error = '';

    state.cardFields.forEach(function (field) {
      if (error) return;

      var raw = String(field.input.value || '').trim();
      if (!raw) return;

      if (field.list) {
        var parts = raw.split(/[\s,]+/).filter(function (part) { return part !== ''; });
        var numericItems = field.key === 'modules' ||
          (Array.isArray(field.original) && field.original.length > 0 &&
            field.original.every(function (item) { return typeof item === 'number'; }));

        var items = [];
        for (var i = 0; i < parts.length; i += 1) {
          if (numericItems) {
            var numberItem = Number(parts[i].replace(',', '.'));
            if (!isFinite(numberItem)) {
              error = '«' + field.label + '»: нужны числа через запятую';
              return;
            }
            items.push(numberItem);
          } else {
            items.push(parts[i]);
          }
        }

        if (items.length) setDeep(variant, field.key, items);
        return;
      }

      if (field.numeric) {
        var number = Number(raw.replace(',', '.'));
        if (!isFinite(number)) {
          error = '«' + field.label + '»: нужно число';
          return;
        }
        setDeep(variant, field.key, number);
        return;
      }

      setDeep(variant, field.key, raw);
    });

    if (error) {
      showCardError(error);
      return null;
    }

    return variant;
  }

  function pluralDisks(count) {
    var n = Math.abs(Number(count)) % 100;
    var n1 = n % 10;
    if (n > 10 && n < 20) return 'дисков';
    if (n1 === 1) return 'диск';
    if (n1 >= 2 && n1 <= 4) return 'диска';
    return 'дисков';
  }

  function variantSummary(variant) {
    var out = [];
    if (!variant || typeof variant !== 'object') return out;

    if (variant.domain) out.push('домен ' + variant.domain);

    var st = variant.storage || {};
    if (st.raid_level !== undefined && st.raid_level !== null && st.raid_level !== '') {
      var line = 'RAID ' + st.raid_level;
      if (st.disks) line += ', ' + st.disks + ' ' + pluralDisks(st.disks);
      if (st.mount) line += ', ' + st.mount;
      out.push(line);
    }

    var hosts = variant.hosts || {};
    ['hq-srv', 'hq-cli', 'hq-rtr', 'br-srv', 'isp'].forEach(function (key) {
      if (hosts[key]) out.push(key.toUpperCase() + ' ' + hosts[key]);
    });

    return out;
  }

  function makeGroup(title, items, muted) {
    var group = document.createElement('div');
    group.className = 'card-group';

    var head = document.createElement('p');
    head.className = 'eyebrow card-group-title';
    head.textContent = title;
    group.appendChild(head);

    items.forEach(function (text) {
      var row = document.createElement('div');
      row.className = 'card-item' + (muted ? ' card-item-muted' : '');
      row.textContent = text;
      group.appendChild(row);
    });

    return group;
  }

  function makeCardButton(label, className, handler) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = className;
    btn.textContent = label;
    btn.addEventListener('click', handler);
    return btn;
  }

  function renderIntakeCard(variant, sources, unknown, warnings) {
    if (variant) state.variant = variant;

    var card = els.intakeCard;
    card.innerHTML = '';
    els.intakeForm.hidden = true;
    card.hidden = false;
    setError(els.intakeCardError, '');
    state.cardFields = [];

    var entries = normalizeSourceEntries(sources);
    var groups = groupSourceEntries(entries);

    if (groups.exam.length) {
      card.appendChild(makeEditGroup('ИЗ ЗАДАНИЯ', groups.exam));
    }
    if (groups.method.length) {
      card.appendChild(makeEditGroup('ИЗ МЕТОДИЧКИ', groups.method));
    }

    if (!groups.exam.length && !groups.method.length) {
      var summary = variantSummary(variant);
      card.appendChild(makeGroup(
        'ТЕКУЩИЕ ЗНАЧЕНИЯ',
        summary.length ? summary : ['Задание разобрано, значения по умолчанию'],
        false
      ));
    }

    var unknownList = toList(unknown);
    if (unknownList.length) {
      var unknownGroup = document.createElement('div');
      unknownGroup.className = 'card-group';
      var unknownHead = document.createElement('p');
      unknownHead.className = 'eyebrow card-group-title';
      unknownHead.textContent = 'НЕ РАСПОЗНАНО';
      unknownGroup.appendChild(unknownHead);
      unknownList.forEach(function (text) {
        var row = document.createElement('div');
        row.className = 'card-unknown';
        row.textContent = text;
        unknownGroup.appendChild(row);
      });
      card.appendChild(unknownGroup);
    }

    var warnList = toList(warnings);
    if (warnList.length) {
      var warnBox = document.createElement('div');
      warnBox.className = 'card-warnings';
      warnList.forEach(function (text) {
        var row = document.createElement('div');
        row.className = 'card-warning';
        row.textContent = text;
        warnBox.appendChild(row);
      });
      card.appendChild(warnBox);
    }

    var actions = document.createElement('div');
    actions.className = 'card-actions';
    actions.appendChild(makeCardButton('Всё верно', 'btn btn-primary', confirmIntake));
    actions.appendChild(makeCardButton('Ввести текст заново', 'btn', showIntakeForm));
    card.appendChild(actions);
  }

  /* ─── Лента и шапка ───────────────────────────────────────── */

  function clearFeed() {
    els.chatFeed.innerHTML = '';
  }

  function updateHeader(step) {
    var total = step.total || state.progress.total || 0;
    var num = step.num || state.progress.idx || 0;
    var label = 'Шаг ' + num + '/' + total;
    if (step.module !== undefined && step.module !== null) {
      label += ' · Модуль ' + step.module;
    }
    els.chatStepLabel.textContent = label;
  }

  function resetHeader() {
    els.chatStepLabel.textContent = 'Шаг 0/' + (state.progress.total || 0);
  }

  function applyProgress(progress) {
    if (!progress || typeof progress !== 'object') return;

    var next = {
      idx: typeof progress.idx === 'number' ? progress.idx : state.progress.idx,
      total: typeof progress.total === 'number' ? progress.total : state.progress.total,
      can_advance: typeof progress.can_advance === 'boolean'
        ? progress.can_advance
        : state.progress.can_advance
    };
    state.progress = next;

    var total = next.total > 0 ? next.total : 0;
    var idx = Math.max(0, next.idx || 0);
    if (total > 0 && idx > total) idx = total;
    var percent = total > 0 ? (idx / total) * 100 : 0;
    els.chatProgress.style.width = percent.toFixed(2) + '%';

    if (!state.step && total > 0) resetHeader();
    syncNextButton();
  }

  function syncNextButton() {
    els.chatNext.disabled = state.streaming || !state.progress.can_advance;
  }

  function nearBottom() {
    var wrap = els.chatFeedWrap;
    return wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight <= 80;
  }

  function scrollToBottom(force) {
    if (!force && !nearBottom()) return;
    state.atBottom = true;
    requestAnimationFrame(function () {
      els.chatFeedWrap.scrollTop = els.chatFeedWrap.scrollHeight;
    });
  }

  function appendSystem(text) {
    var node = document.createElement('div');
    node.className = 'msg msg-system';
    var body = document.createElement('div');
    body.className = 'msg-text';
    body.textContent = text;
    node.appendChild(body);
    els.chatFeed.appendChild(node);
    scrollToBottom(state.atBottom);
  }

  function appendError(text) {
    var node = document.createElement('div');
    node.className = 'msg msg-error';
    var body = document.createElement('div');
    body.className = 'msg-text';
    body.textContent = text;
    node.appendChild(body);
    els.chatFeed.appendChild(node);
    scrollToBottom(true);
  }

  function appendUser(text) {
    var node = document.createElement('div');
    node.className = 'msg msg-user';

    var label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = 'ВЫ';

    var body = document.createElement('div');
    body.className = 'msg-text';
    body.textContent = text;

    node.appendChild(label);
    node.appendChild(body);
    els.chatFeed.appendChild(node);
    scrollToBottom(true);
    return node;
  }

  function appendAssistant(text) {
    var node = document.createElement('div');
    node.className = 'msg msg-assistant msg-streaming';

    var md = document.createElement('div');
    md.className = 'md';
    node.appendChild(md);

    node._markdown = text || '';
    node._mdEl = md;

    els.chatFeed.appendChild(node);
    scrollToBottom(true);
    return node;
  }

  function appendStep(step, options) {
    options = options || {};
    if (!step || !step.markdown) return null;

    var last = els.chatFeed.lastElementChild;
    if (!options.force && last && last.classList.contains('msg-step') &&
        last.getAttribute('data-step') === String(step.num) &&
        last._markdown === step.markdown) {
      return null;
    }

    var node = document.createElement('div');
    node.className = 'msg msg-assistant msg-step';
    node.setAttribute('data-step', String(step.num));

    var md = document.createElement('div');
    md.className = 'md';
    node.appendChild(md);

    node._markdown = step.markdown;
    node._mdEl = md;

    md.innerHTML = renderMarkdown(step.markdown);
    decorateCode(md, true);

    els.chatFeed.appendChild(node);
    scrollToBottom(options.scroll === false ? state.atBottom : true);
    return node;
  }

  function setStep(step, options) {
    if (!step) return;
    state.step = step;
    updateHeader(step);
    appendStep(step, options);
  }

  /* ─── Рендер markdown в сообщении ─────────────────────────── */

  var pendingRender = new Set();
  var renderHandle = 0;

  function queueRender(node) {
    pendingRender.add(node);
    if (renderHandle) return;
    renderHandle = requestAnimationFrame(function () {
      renderHandle = 0;
      pendingRender.forEach(function (item) {
        renderInto(item, false);
      });
      pendingRender.clear();
    });
  }

  function renderInto(node, highlight) {
    var md = node._mdEl || node.querySelector('.md');
    if (!md) return;
    node._mdEl = md;
    md.innerHTML = renderMarkdown(node._markdown || '');
    decorateCode(md, highlight);
  }

  function finishStreaming(node) {
    pendingRender.delete(node);
    node.classList.remove('msg-streaming');
    renderInto(node, true);
    if (!String(node._markdown || '').trim()) node.remove();
    scrollToBottom(state.atBottom);
  }

  function decorateCode(container, highlight) {
    var blocks = container.querySelectorAll('pre');
    for (var i = 0; i < blocks.length; i += 1) {
      var pre = blocks[i];
      var code = pre.querySelector('code');
      if (!code) continue;

      if (highlight && window.hljs) {
        try {
          window.hljs.highlightElement(code);
        } catch (e) {
          /* подсветка не критична */
        }
      }

      var wrap = pre.parentElement;
      if (!wrap || !wrap.classList.contains('codeblock')) {
        wrap = document.createElement('div');
        wrap.className = 'codeblock';
        pre.parentNode.insertBefore(wrap, pre);
        wrap.appendChild(pre);
      }

      if (!wrap.querySelector(':scope > .code-copy')) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'code-copy';
        btn.textContent = 'Копировать';
        btn.setAttribute('aria-label', 'Копировать команду');
        btn.addEventListener('click', function () {
          copyCode(code, btn);
        });
        wrap.appendChild(btn);
      }
    }
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', '');
        area.style.position = 'fixed';
        area.style.top = '0';
        area.style.left = '0';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        var ok = document.execCommand('copy');
        document.body.removeChild(area);
        if (ok) resolve();
        else reject(new Error('copy failed'));
      } catch (err) {
        reject(err);
      }
    });
  }

  function copyCode(code, btn) {
    var text = String(code.textContent || '').replace(/\s+$/, '');
    copyText(text).then(function () {
      flashCopy(btn, 'Скопировано');
    }, function () {
      flashCopy(btn, 'Не вышло');
    });
  }

  function flashCopy(btn, text) {
    btn.textContent = text;
    if (btn._timer) clearTimeout(btn._timer);
    btn._timer = setTimeout(function () {
      btn.textContent = 'Копировать';
    }, 1200);
  }

  /* ─── Отправка в чат (SSE) ────────────────────────────────── */

  function newId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    var bytes = new Uint8Array(16);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (var i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    var hex = Array.prototype.map.call(bytes, function (b) {
      return b.toString(16).padStart(2, '0');
    }).join('');
    return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) +
      '-' + hex.slice(16, 20) + '-' + hex.slice(20);
  }

  function setStreaming(on) {
    state.streaming = on;
    els.chatInput.disabled = on;
    els.chatInput.placeholder = on ? 'Ждём ответ…' : 'Сообщение…';
    if (on) {
      els.chatStatus.textContent = 'стрим…';
    } else {
      els.chatStatus.textContent = '';
      els.chatInput.focus();
      autosize();
    }
    syncNextButton();
  }

  async function sendMessage() {
    if (state.streaming) return;

    var text = els.chatInput.value.trim();
    if (!text) return;
    if (!state.user) {
      showView('login');
      return;
    }

    var clientId = newId();
    els.chatInput.value = '';
    autosize();
    appendUser(text);

    var bubble = appendAssistant('');
    setStreaming(true);

    try {
      await streamChat(text, clientId, bubble);
    } catch (err) {
      if (err.status === 401) {
        forceLogin('Сессия истекла, войди снова');
      } else if (err.status === 409) {
        appendError('уже отправлено');
      } else {
        appendError(err.message);
      }
    } finally {
      finishStreaming(bubble);
      setStreaming(false);
    }
  }

  async function streamChat(text, clientId, bubble) {
    var res;
    try {
      res = await fetch(API.chat, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream'
        },
        body: JSON.stringify({ text: text, client_msg_id: clientId })
      });
    } catch (err) {
      var netErr = new Error('Нет связи с сервером');
      netErr.status = 0;
      netErr.cause = err;
      throw netErr;
    }

    if (!res.ok) {
      var payload = null;
      try {
        payload = await res.json();
      } catch (e) {
        payload = null;
      }
      var error = new Error(res.status === 409 ? 'уже отправлено' : errorMessage(payload, res.status));
      error.status = res.status;
      error.code = payload && payload.error && payload.error.code;
      throw error;
    }

    if (!res.body || typeof res.body.getReader !== 'function') {
      throw new Error('Браузер не умеет читать поток');
    }

    var reader = res.body.getReader();
    var decoder = new TextDecoder('utf-8');
    var buffer = '';
    var eventName = 'message';
    var dataLines = [];

    function dispatch() {
      if (!dataLines.length) {
        eventName = 'message';
        return;
      }
      var raw = dataLines.join('\n');
      var name = eventName || 'message';
      eventName = 'message';
      dataLines = [];

      var payload = null;
      try {
        payload = JSON.parse(raw);
      } catch (e) {
        payload = { text: raw };
      }
      handleStreamEvent(name, payload, bubble);
    }

    function readLine(line) {
      if (line.charAt(0) === ':') return;
      var colon = line.indexOf(':');
      var field = colon === -1 ? line : line.slice(0, colon);
      var value = colon === -1 ? '' : line.slice(colon + 1);
      if (value.charAt(0) === ' ') value = value.slice(1);
      if (field === 'event') {
        eventName = value;
      } else if (field === 'data') {
        dataLines.push(value);
      }
    }

    try {
      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });

        var newline = buffer.indexOf('\n');
        while (newline !== -1) {
          var line = buffer.slice(0, newline);
          buffer = buffer.slice(newline + 1);
          if (line.charAt(line.length - 1) === '\r') line = line.slice(0, -1);
          if (line === '') dispatch();
          else readLine(line);
          newline = buffer.indexOf('\n');
        }
      }

      buffer += decoder.decode();
      if (buffer.trim()) {
        readLine(buffer.replace(/\r$/, ''));
      }
      dispatch();
    } finally {
      try {
        reader.releaseLock();
      } catch (e) {
        /* ignore */
      }
    }
  }

  function handleStreamEvent(name, data, bubble) {
    if (!data || typeof data !== 'object') data = {};

    switch (name) {
      case 'meta':
        state.model = data.model || '';
        if (state.model) {
          els.chatStatus.textContent = 'модель: ' + state.model;
          els.chatStepLabel.setAttribute('title', 'Модель: ' + state.model);
        }
        if (typeof data.step_num === 'number' && !state.step) {
          els.chatStepLabel.textContent = 'Шаг ' + data.step_num + '/' + (state.progress.total || 0);
        }
        break;

      case 'delta':
        if (typeof data.text === 'string' && data.text) {
          bubble._markdown = (bubble._markdown || '') + data.text;
          queueRender(bubble);
          scrollToBottom(state.atBottom);
        }
        break;

      case 'step': {
        var incoming = data.step || (data.markdown ? data : null);
        if (incoming) setStep(incoming, { scroll: true });
        if (data.progress) applyProgress(data.progress);
        break;
      }

      case 'done': {
        var progress = {};
        if (data.progress && typeof data.progress === 'object') {
          Object.keys(data.progress).forEach(function (key) {
            progress[key] = data.progress[key];
          });
        }
        if (typeof data.can_advance === 'boolean') progress.can_advance = data.can_advance;
        applyProgress(progress);

        /* Сервер просит новое задание или вернул разобранную карточку. */
        if (data.phase === 'intake') {
          state.phase = 'intake';
          showIntakeForm();
          showView('intake');
        } else if (data.phase === 'confirm') {
          state.phase = 'confirm';
          state.variant = data.variant || state.variant;
          state.sources = data.sources || null;
          state.unknown = data.unknown || [];
          renderIntakeCard(state.variant, state.sources, state.unknown, data.warnings || []);
          showView('intake');
        }
        break;
      }

      case 'error':
        appendError(
          (data.message && String(data.message)) ||
          (data.error && data.error.message) ||
          'Ошибка модели'
        );
        break;

      default:
        if (typeof data.text === 'string' && data.text) {
          bubble._markdown = (bubble._markdown || '') + data.text;
          queueRender(bubble);
        }
        break;
    }
  }

  /* ─── «Дальше» ────────────────────────────────────────────── */

  async function nextStep() {
    if (state.streaming || !state.progress.can_advance) return;

    var clientId = newId();
    setStreaming(true);

    try {
      var data = await api(API.next, {
        method: 'POST',
        body: { client_msg_id: clientId },
        timeout: 30000
      });
      if (data && data.step) setStep(data.step, { scroll: true });
      if (data && data.progress) applyProgress(data.progress);
    } catch (err) {
      if (err.status === 401) {
        forceLogin('Сессия истекла, войди снова');
      } else if (err.status === 409) {
        appendError('шаг ещё не подтверждён');
      } else {
        appendError(err.message);
      }
    } finally {
      setStreaming(false);
    }
  }

  /* ─── Ввод ────────────────────────────────────────────────── */

  function autosize() {
    var input = els.chatInput;
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 180) + 'px';
  }

  /* ─── Инициализация ───────────────────────────────────────── */

  function bind() {
    els.loginForm.addEventListener('submit', onLogin);
    els.intakeSubmit.addEventListener('click', submitIntake);
    els.intakeSkip.addEventListener('click', skipIntake);
    els.intakeCancel.addEventListener('click', cancelAssignmentEdit);
    els.chatEdit.addEventListener('click', startAssignmentEdit);
    els.chatNext.addEventListener('click', nextStep);
    els.intakeLogout.addEventListener('click', logout);
    els.chatLogout.addEventListener('click', logout);

    els.intakeText.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        submitIntake();
      }
    });

    els.intakeCard.addEventListener('input', function () {
      setError(els.intakeCardError, '');
    });

    els.chatInput.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendMessage();
      }
    });

    els.chatInput.addEventListener('input', autosize);

    els.chatFeedWrap.addEventListener('scroll', function () {
      state.atBottom = nearBottom();
    });

    window.addEventListener('resize', function () {
      if (state.atBottom) scrollToBottom(true);
    });

    window.addEventListener('focus', function () {
      if (state.view === 'chat') autosize();
    });
  }

  function init() {
    bind();
    autosize();

    /* Страховка: если /api/state молчит дольше 15 с, показываем вход. */
    setTimeout(function () {
      if (!state.booted) showView('login');
    }, 15000);

    loadState();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
