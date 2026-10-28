import assert from "node:assert/strict";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, headless: true });
const base = process.env.TEST_BASE_URL ?? "http://127.0.0.1:5186";

async function setup(platform, status = 200, savedToken = false, waiting = false, rejectSaved = false) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  const requests = [];
  const payments = [];
  const errors = [];
  const billing = { status: "pending" };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("https://telegram.org/js/**", (route) => route.fulfill({ body: "", contentType: "text/javascript" }));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    let responseStatus = 200;
    if (path.endsWith("telegram-webapp")) {
      const request = route.request().postDataJSON();
      requests.push(request);
      responseStatus = request.accept_terms && request.accept_personal_data ? 200 : status;
      body = responseStatus === 200 ? { access_token: "test-token", token_type: "bearer" } : { detail: "Нужно принять документы" };
    } else if (path.endsWith("/billing/waiting")) {
      body = {
        lectures: waiting ? [{ id: "00000000-0000-4000-8000-000000000001", title: "Лекция в ожидании", duration_sec: 120 }] : [],
        available_sec: 60,
        resets_at: "2026-11-01T00:00:00Z",
      };
    } else if (path.endsWith("/billing/quota")) {
      body = { weekly_limit_sec: 3600, weekly_used_sec: 0, package_left_sec: 0, resets_at: "2026-11-01T00:00:00Z" };
    } else if (path.endsWith("/billing/products")) {
      body = [
        { code: "hours", title: "Час обработки", kind: "package", price_rub: 100, seconds: 3600 },
        { code: "more", title: "Пять часов", kind: "package", price_rub: 400, seconds: 18000 },
      ];
    } else if (path.endsWith("/billing/payments") && route.request().method() === "POST") {
      payments.push(route.request().postDataJSON());
      body = { id: "payment-1", kind: "package", product_code: "hours", amount_kopecks: 10000, status: "pending", confirmation_url: "https://yoomoney.ru/checkout/test", created_at: "2026-10-27T00:00:00Z", paid_at: null };
    } else if (path.endsWith("/billing/payments")) {
      body = [{ id: "payment-1", kind: "package", product_code: "hours", amount_kopecks: 10000, status: billing.status, confirmation_url: "https://yoomoney.ru/checkout/test", created_at: "2026-10-27T00:00:00Z", paid_at: null }];
    } else if (rejectSaved && route.request().headers().authorization === "Bearer saved-token") {
      responseStatus = 401;
      body = { detail: "Недействительный токен" };
    } else if (path === "/api/v1/me") {
      body = { id: "1", display_name: "Тест", email: null, plan: "free", identities: platform ? [{ provider: "telegram", created_at: "2026-10-27T00:00:00Z" }] : [], balance_seconds: 0 };
    }
    await route.fulfill({ status: responseStatus, json: body });
  });
  await page.addInitScript(({ platform, savedToken }) => {
    if (savedToken) localStorage.setItem("lecturo.token", "saved-token");
    localStorage.setItem("lecturo-theme", "light");
    localStorage.setItem("lecturo.cookies-ack", "accepted");
    window.mock = { events: {}, back: new Set(), ready: 0, expand: 0, visible: false, links: [] };
    const mock = window.mock;
    window.Telegram = { WebApp: {
      initData: platform ? "signed-test-data" : "", platform, colorScheme: "dark",
      themeParams: { bg_color: "#121212", text_color: "#eeeeee" },
      ready: () => mock.ready++, expand: () => mock.expand++,
      onEvent: (name, fn) => (mock.events[name] ??= new Set()).add(fn),
      offEvent: (name, fn) => mock.events[name].delete(fn),
      openLink: (url) => mock.links.push(url),
      BackButton: { show: () => mock.visible = true, hide: () => mock.visible = false,
        onClick: (fn) => mock.back.add(fn), offClick: (fn) => mock.back.delete(fn) },
    } };
  }, { platform, savedToken });
  return { context, page, requests, errors, payments, billing };
}

try {
  for (const platform of ["android", "ios"]) {
    const { context, page, requests, errors, payments, billing } = await setup(platform, 403);
    await page.goto(base + "/login");
    await page.getByRole("dialog").waitFor();
    assert.equal(requests.length, 1);
    assert.deepEqual(requests[0], { init_data: "signed-test-data", accept_terms: false, accept_personal_data: false });
    const next = page.getByRole("button", { name: "Продолжить", exact: true });
    assert.equal(await next.isEnabled(), false);
    for (const label of await page.getByRole("dialog").locator("label.checkbox").all()) await label.locator(".checkbox__box").click();
    await next.click();
    await page.waitForURL(base + "/");
    assert.equal(requests.length, 2);
    assert.equal(requests[1].accept_terms, true);
    assert.equal(requests[1].accept_personal_data, true);
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), "test-token");
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "dark");
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo-theme")), "light");
    assert.equal(await page.evaluate(() => window.mock.events.themeChanged.size), 1);
    assert.equal(await page.evaluate(() => window.mock.back.size), 1);
    assert.ok(await page.evaluate(() => window.mock.ready > 0 && window.mock.expand > 0));
    await page.evaluate(() => {
      window.Telegram.WebApp.colorScheme = "light";
      window.Telegram.WebApp.themeParams = { bg_color: "#fafafa" };
      window.mock.events.themeChanged.forEach((fn) => fn());
    });
    assert.equal(await page.evaluate(() => document.documentElement.style.getPropertyValue("--color-surface")), "#fafafa");
    await page.locator("nav:visible").getByRole("link", { name: "Кабинет", exact: true }).click();
    await page.waitForURL(base + "/account");
    await page.waitForFunction(() => window.mock.visible);
    await page.getByText("откроется в браузере. После оплаты вернитесь в Telegram").waitFor();
    await page.locator("label.checkbox").filter({ hasText: "Принимаю условия" }).locator(".checkbox__box").click();
    await page.getByRole("button", { name: "Оплатить 100" }).click();
    await page.getByText("Введите адрес почты").waitFor();
    assert.equal(payments.length, 0);
    await page.getByLabel("Email для чека").fill(" student@mail.ru ");
    await page.getByRole("button", { name: "Оплатить 100" }).click();
    await page.getByRole("button", { name: "Открыть оплату в браузере" }).click();
    await page.getByRole("button", { name: "Открыть оплату в браузере" }).click();
    assert.deepEqual(await page.evaluate(() => window.mock.links), ["https://yoomoney.ru/checkout/test", "https://yoomoney.ru/checkout/test"]);
    await page.evaluate(async () => {
      const { openExternalLink, bindTheme } = await import("/src/telegram/sdk.ts");
      openExternalLink("javascript:alert(1)");
      openExternalLink("http://[");
      openExternalLink("https://user:password@yoomoney.ru/checkout/test");
      const cleanup = bindTheme(window.Telegram.WebApp);
      cleanup();
    });
    assert.equal(await page.evaluate(() => window.mock.links.length), 2);
    assert.equal(await page.evaluate(() => window.mock.events.themeChanged.size), 1);
    assert.equal(payments.length, 1);
    assert.equal(payments[0].receipt_email, "student@mail.ru");
    await page.evaluate(() => window.mock.events.activated.forEach((fn) => fn()));
    billing.status = "succeeded";
    await page.getByRole("button", { name: "Оплатить 100" }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Открыть оплату в браузере" }).count(), 0);
    billing.status = "pending";
    await page.getByRole("radio", { name: "Пять часов" }).check();
    assert.equal(await page.getByRole("button", { name: "Открыть оплату в браузере" }).count(), 0);
    await page.screenshot({ path: `/tmp/telegram-${platform}-account.png`, fullPage: true });
    await page.evaluate(() => window.mock.back.forEach((fn) => fn()));
    await page.waitForURL(base + "/");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(overflow, false);
    await page.screenshot({ path: `/tmp/telegram-${platform}.png`, fullPage: true });
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup(undefined);
    await page.goto(base + "/login");
    await page.getByRole("heading", { name: "Вход", exact: true }).waitFor();
    assert.equal(requests.length, 0);
    assert.equal(await page.evaluate(() => window.mock.ready), 0);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light");
    await page.getByRole("textbox", { name: "Почта" }).fill("student@lecturo.ru");
    await page.setViewportSize({ width: 390, height: 400 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.evaluate(async () => {
      const { openExternalLink } = await import("/src/telegram/sdk.ts");
      openExternalLink("/reset-password");
    });
    await page.waitForURL(base + "/reset-password");
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup("android", 401);
    await page.goto(base + "/login");
    await page.getByRole("alert").filter({ hasText: "Вход через Telegram" }).waitFor();
    assert.equal(requests.length, 1);
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), null);
    assert.deepEqual(errors, []);
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/auth/telegram-webapp")),
      page.getByRole("button", { name: "Повторить вход" }).click(),
    ]);
    assert.equal(requests.length, 2);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup("ios");
    await page.goto(base + "/login");
    await page.waitForURL(base + "/");
    assert.equal(requests.length, 1);
    assert.equal(await page.getByRole("dialog").count(), 0);
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), "test-token");
    assert.equal(await page.locator("header").getByRole("button", { name: "Выйти", exact: true }).count(), 0);
    await page.locator("nav:visible").getByRole("link", { name: "Кабинет", exact: true }).click();
    await page.getByRole("button", { name: "Выйти", exact: true }).click();
    await page.waitForURL(base + "/login");
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), null);
    await page.getByRole("button", { name: "Войти через Telegram", exact: true }).waitFor();
    assert.equal(requests.length, 1);
    await page.getByRole("button", { name: "Войти через Telegram", exact: true }).click();
    await page.waitForFunction(() => localStorage.getItem("lecturo.token") === "test-token");
    assert.equal(requests.length, 2);
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup("ios", 200, true);
    await page.goto(base + "/account");
    await page.getByRole("button", { name: "Выйти", exact: true }).click();
    await page.waitForURL(base + "/login");
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), null);
    assert.equal(requests.length, 0);
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup(undefined, 200, true);
    await page.goto(base + "/account");
    await page.getByRole("link", { name: "Оплатить", exact: true }).waitFor();
    await page.evaluate(() => document.addEventListener("click", (event) => {
      window.nativePrevented = event.defaultPrevented;
      event.preventDefault();
    }, { once: true }));
    await page.getByRole("link", { name: "Оплатить", exact: true }).click({ modifiers: ["Control"] });
    assert.equal(await page.evaluate(() => window.nativePrevented), false);
    assert.equal(requests.length, 0);
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, errors } = await setup("android", 200, false, true);
    await page.goto(base + "/login");
    await page.waitForURL(base + "/");
    await page.getByText("Ждут лимита: 1 лекция.", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.mock.events.themeChanged.size), 1);
    await page.getByRole("button", { name: "Выбрать, что обработать" }).click();
    await page.getByRole("dialog", { name: "Не хватает лимита" }).waitFor();
    await page.keyboard.press("Escape");
    await page.getByRole("dialog", { name: "Не хватает лимита" }).waitFor({ state: "hidden" });
    assert.equal(await page.evaluate(() => window.mock.back.size), 1);
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup("android", 200, true, false, true);
    await page.goto(base + "/");
    await page.locator("nav:visible").getByRole("link", { name: "Кабинет", exact: true }).waitFor();
    assert.equal(requests.length, 1);
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), "test-token");
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup("ios", 401, true, false, true);
    await page.goto(base + "/");
    await page.getByRole("alert").filter({ hasText: "Вход через Telegram" }).waitFor();
    await page.waitForTimeout(500);
    assert.equal(requests.length, 1);
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), null);
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup("android", 403);
    await page.goto(base + "/login");
    const dialog = page.getByRole("dialog", { name: "Создание аккаунта" });
    await dialog.waitFor();
    await dialog.getByRole("button", { name: "Отмена", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    const login = page.getByRole("button", { name: "Войти через Telegram", exact: true });
    await login.waitFor();
    await login.click();
    await dialog.waitFor();
    assert.equal(requests.length, 2);
    for (const label of await dialog.locator("label.checkbox").all()) await label.locator(".checkbox__box").click();
    await dialog.getByRole("button", { name: "Продолжить", exact: true }).click();
    await page.waitForURL(base + "/");
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), "test-token");
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup("ios");
    const lectureId = "00000000-0000-4000-8000-000000000003";
    await page.route((url) => url.pathname.startsWith(`/api/v1/lectures/${lectureId}`), (route) => new URL(route.request().url()).pathname !== `/api/v1/lectures/${lectureId}`
      ? route.fulfill({ status: 404, json: { detail: "Не найдено" } })
      : route.fulfill({ json: {
      id: lectureId, title: "Лекция из уведомления", source_type: "upload", source_url: null, embed_url: null,
      duration_sec: 120, status: "ready", processed_locally: false, video_expires_at: null,
      created_at: "2026-10-27T00:00:00Z", video_url: null, audio_only: false, audio_url: null, steps: [],
      segments: [{ start: 0, end: 2, text: "Первая фраза." }], chapters: [], summary: { content_md: "Конспект" },
    } }));
    await page.goto(base + `/lectures/${lectureId}#tgWebAppData=query_id%3D1&tgWebAppVersion=8.0`);
    await page.getByRole("heading", { name: "Лекция из уведомления" }).waitFor();
    assert.equal(new URL(page.url()).pathname, `/lectures/${lectureId}`);
    assert.equal(new URL(page.url()).hash, "");
    assert.equal(requests.length, 1);
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.route("https://telegram.org/js/telegram-widget.js*", (route) => route.abort());
    const page = await context.newPage();
    const sdkRequests = [];
    await page.route("https://telegram.org/js/telegram-web-app.js*", (route) => {
      sdkRequests.push(route.request().url());
      return route.abort();
    });
    await page.goto(base + "/login");
    await page.getByRole("heading", { name: "Вход", exact: true }).waitFor();
    assert.deepEqual(sdkRequests, []);
    const miniAppPage = await context.newPage();
    await miniAppPage.route("https://telegram.org/js/telegram-web-app.js*", (route) => {
      sdkRequests.push(route.request().url());
      return route.abort();
    });
    await miniAppPage.goto(base + "/login#tgWebAppData=query_id%3D1&tgWebAppVersion=8.0");
    await miniAppPage.getByRole("heading", { name: "Вход", exact: true }).waitFor();
    assert.equal(sdkRequests.length, 1);
    await context.close();
  }
  for (const path of ["/login", "/register"]) {
    const miniApp = await setup("android", 401);
    await miniApp.page.goto(base + path);
    await miniApp.page.getByRole("alert").filter({ hasText: "Вход через Telegram" }).waitFor();
    assert.equal(await miniApp.page.getByRole("button", { name: "Войти через Telegram" }).count(), 0);
    assert.equal(await miniApp.page.getByRole("button", { name: "Повторить вход" }).count(), 1);
    assert.equal(await miniApp.page.getByRole("textbox", { name: "Почта" }).count(), 1);
    assert.deepEqual(miniApp.errors, []);
    await miniApp.context.close();
    const browserPage = await setup(undefined);
    await browserPage.page.goto(base + path);
    await browserPage.page.getByRole("button", { name: "Войти через Telegram" }).waitFor();
    assert.equal(browserPage.requests.length, 0);
    await browserPage.context.close();
  }
  for (const colorScheme of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme });
    const page = await context.newPage();
    const errors = [];
    const logins = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("https://telegram.org/js/telegram-widget.js*", (route) => route.fulfill({
      contentType: "text/javascript",
      body: `window.Telegram = window.Telegram || {};
        window.Telegram.Login = { auth: (options, callback) => {
          window.telegramLoginOptions = options;
          callback({ id: 7, first_name: "Анна", auth_date: 1700000000, hash: "abc" });
        } };`,
    }));
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/v1/auth/providers") return route.fulfill({ json: { vk: true, yandex: true } });
      if (path === "/api/v1/auth/telegram") {
        const request = route.request().postDataJSON();
        logins.push(request);
        return request.accept_terms && request.accept_personal_data
          ? route.fulfill({ json: { access_token: "web-token", token_type: "bearer" } })
          : route.fulfill({ status: 403, json: { detail: "Нужно принять документы" } });
      }
      if (path === "/api/v1/me") return route.fulfill({ json: { id: "1", display_name: "Анна", email: null, plan: "free", identities: [], balance_seconds: 0 } });
      return route.fulfill({ json: [] });
    });
    for (const width of [360, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(base + "/login");
      const names = ["Войти через Telegram", "Войти через VK", "Войти через Яндекс"];
      const buttons = names.map((name) => page.getByRole("button", { name }));
      for (const button of buttons) await button.waitFor();
      await page.waitForFunction(() => !document.querySelector(".provider-button[aria-busy]"));
      const boxes = await Promise.all(buttons.map((button) => button.boundingBox()));
      const logos = await Promise.all(buttons.map((button) => button.locator(".provider-logo").boundingBox()));
      for (const box of boxes) {
        assert.equal(Math.round(box.width), Math.round(boxes[0].width));
        assert.equal(Math.round(box.height), Math.round(boxes[0].height));
      }
      logos.forEach((logo, index) => {
        assert.equal(Math.round(logo.width), Math.round(logos[0].width));
        assert.equal(Math.round(boxes[index].x + boxes[index].width - logo.x - logo.width), Math.round(boxes[0].x + boxes[0].width - logos[0].x - logos[0].width));
      });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
      if (process.env.SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.SCREENSHOT_DIR}/login-${colorScheme}-${width}.png`, fullPage: true });
    }
    await page.getByRole("button", { name: "Войти через Telegram" }).focus();
    await page.keyboard.press("Enter");
    await page.getByRole("dialog", { name: "Создание аккаунта" }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.telegramLoginOptions), { bot_id: 1234567890, request_access: "write", lang: "ru" });
    for (const label of await page.getByRole("dialog").locator("label.checkbox").all()) await label.locator(".checkbox__box").click();
    await page.getByRole("button", { name: "Продолжить" }).click();
    await page.waitForURL((url) => url.pathname === "/");
    assert.equal(logins.length, 2);
    assert.deepEqual(logins[0], { id: 7, first_name: "Анна", auth_date: 1700000000, hash: "abc", accept_terms: false, accept_personal_data: false });
    assert.equal(logins[1].accept_terms, true);
    assert.deepEqual(errors, []);
    await context.close();
  }
  for (const platform of ["android", undefined]) {
    const { context, page, errors } = await setup(platform, 200, !platform);
    const lectureId = "00000000-0000-4000-8000-000000000002";
    const exportPath = `/api/v1/lectures/${lectureId}/export.pdf`;
    const linkRequests = [];
    const downloads = [];
    let linkStatus = 200;
    await page.route((url) => url.pathname.startsWith(`/api/v1/lectures/${lectureId}`), (route) => new URL(route.request().url()).pathname !== `/api/v1/lectures/${lectureId}`
      ? route.fulfill({ status: 404, json: { detail: "Не найдено" } })
      : route.fulfill({ json: {
      id: lectureId, title: "Лекция для экспорта", source_type: "upload", source_url: null, embed_url: null,
      duration_sec: 120, status: "ready", processed_locally: false, video_expires_at: null,
      created_at: "2026-10-27T00:00:00Z", video_url: null, audio_only: false, audio_url: null, steps: [],
      segments: [{ start: 0, end: 2, text: "Первая фраза." }], chapters: [], summary: { content_md: "Конспект" },
    } }));
    await page.route((url) => url.pathname.startsWith(`/api/v1/lectures/${lectureId}/exports/`), (route) => {
      linkRequests.push({ path: new URL(route.request().url()).pathname, method: route.request().method(), auth: route.request().headers().authorization });
      return linkStatus === 200
        ? route.fulfill({ json: { url: `${exportPath}?token=signed-export`, expires_at: new Date(Date.now() + 120_000).toISOString() } })
        : route.fulfill({ status: linkStatus, json: { detail: "Расшифровки ещё нет" } });
    });
    const fileStatuses = [];
    await page.route((url) => url.pathname === exportPath, (route) => {
      downloads.push(route.request().url());
      const fileStatus = fileStatuses.shift() ?? 200;
      return fileStatus === 200
        ? route.fulfill({ body: "%PDF-1.4", headers: { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="lecture.pdf"' } })
        : route.fulfill({ status: fileStatus, json: { detail: "Ссылка недействительна" } });
    });
    if (platform) {
      await page.goto(base + "/login");
      await page.waitForURL(base + "/");
    }
    await page.goto(base + `/lectures/${lectureId}`);
    const pdf = page.getByRole("button", { name: "PDF", exact: true });
    if (platform) {
      await pdf.click();
      const open = page.getByRole("button", { name: "Открыть PDF", exact: true });
      await open.waitFor();
      assert.equal(await page.evaluate(() => window.mock.links.length), 0);
      await open.click();
      await page.waitForFunction(() => window.mock.links.length === 1);
      await pdf.waitFor();
      assert.deepEqual(await page.evaluate(() => window.mock.links), [`${base}${exportPath}?token=signed-export`]);
      assert.deepEqual(downloads, []);
    } else {
      const [download] = await Promise.all([page.waitForEvent("download"), pdf.click()]);
      assert.equal(download.suggestedFilename(), "lecture.pdf");
      assert.deepEqual(downloads, [`${base}${exportPath}?token=signed-export`]);
      assert.equal(page.url(), base + `/lectures/${lectureId}`);
    }
    assert.equal(linkRequests[0].path, `/api/v1/lectures/${lectureId}/exports/pdf/link`);
    assert.equal(linkRequests[0].method, "POST");
    assert.match(linkRequests[0].auth, /^Bearer \S+-token$/);
    linkStatus = 409;
    await page.getByRole("button", { name: "SRT", exact: true }).click();
    await page.getByText("Файл ещё не готов, попробуйте позже.").waitFor();
    assert.equal(linkRequests.length, 2);
    assert.equal(downloads.length, platform ? 0 : 1);
    if (!platform) {
      linkStatus = 200;
      fileStatuses.push(500);
      await pdf.click();
      const failure = page.getByRole("alert").filter({ hasText: "Не удалось скачать PDF" });
      await failure.waitFor();
      assert.equal(page.url(), base + `/lectures/${lectureId}`);
      assert.equal(downloads.length, 2);
      assert.equal(linkRequests.length, 2);
      const [download] = await Promise.all([page.waitForEvent("download"), failure.getByRole("button", { name: "Попробовать снова" }).click()]);
      assert.equal(download.suggestedFilename(), "lecture.pdf");
      await failure.waitFor({ state: "detached" });
      assert.equal(linkRequests.length, 2);
      fileStatuses.push(401);
      const [refreshed] = await Promise.all([page.waitForEvent("download"), pdf.click()]);
      assert.equal(refreshed.suggestedFilename(), "lecture.pdf");
      assert.equal(linkRequests.length, 3);
      fileStatuses.push(401, 401);
      await pdf.click();
      await failure.waitFor();
      assert.equal(linkRequests.length, 4);
      assert.equal(page.url(), base + `/lectures/${lectureId}`);
      for (const width of [360, 1280]) {
        await page.setViewportSize({ width, height: 800 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      }
    }
    assert.deepEqual(errors, []);
    await context.close();
  }
  for (const platform of ["android", undefined]) {
    const { context, page, errors } = await setup(platform);
    if (platform) {
      await page.goto(base + "/login");
      await page.waitForURL(base + "/");
    }
    await page.goto(base + "/local");
    await page.getByRole("heading", { level: 1 }).waitFor();
    await page.evaluate(() => new Promise((resolve, reject) => {
      const request = indexedDB.open("lecturo-local");
      request.onsuccess = () => {
        const transaction = request.result.transaction("lectures", "readwrite");
        transaction.objectStore("lectures").put({ id: "fixture", title: "Проверочная лекция", createdAt: Date.now(), durationSec: 10, language: "ru", model: "tiny", segments: [{ start: 0, end: 10, text: "Тестовая запись" }], chapters: [], summaryMd: null });
        transaction.oncomplete = () => { request.result.close(); resolve(); };
        transaction.onerror = reject;
      };
      request.onerror = reject;
    }));
    await page.reload({ waitUntil: "domcontentloaded" });
    const markdown = page.getByRole("button", { name: "Скачать «Проверочная лекция» в формате MD" });
    if (platform) {
      await page.evaluate(() => {
        window.mock.copied = [];
        window.mock.shared = [];
        Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: (text) => { window.mock.copied.push(text); return Promise.resolve(); } } });
        navigator.canShare = (data) => Boolean(data.files);
        navigator.share = (data) => { window.mock.shared.push(data.files ? data.files.map((file) => file.name) : data.text); return Promise.resolve(); };
      });
      await markdown.click();
      const dialog = page.getByRole("dialog", { name: "Markdown" });
      await dialog.waitFor();
      assert.match(await dialog.getByRole("textbox").inputValue(), /^# Проверочная лекция/);
      await dialog.getByRole("button", { name: "Скопировать" }).click();
      await dialog.getByText("Текст скопирован.").waitFor();
      assert.match((await page.evaluate(() => window.mock.copied))[0], /Тестовая запись/);
      await dialog.getByRole("button", { name: "Поделиться" }).click();
      await page.waitForFunction(() => window.mock.shared.length === 1);
      assert.deepEqual(await page.evaluate(() => window.mock.shared), [["Проверочная лекция.md"]]);
      await page.evaluate(() => {
        Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.reject(new Error("denied")) } });
        document.execCommand = () => true;
      });
      await dialog.getByRole("button", { name: "Скопировать" }).click();
      await dialog.getByText("Текст скопирован.").waitFor();
      for (const width of [360, 1280]) {
        await page.setViewportSize({ width, height: 800 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        const box = await dialog.boundingBox();
        assert.ok(box.x >= 0 && box.x + box.width <= width);
      }
      await dialog.getByRole("button", { name: "Закрыть" }).click();
      await dialog.waitFor({ state: "hidden" });
    } else {
      const [download] = await Promise.all([page.waitForEvent("download"), markdown.click()]);
      assert.equal(download.suggestedFilename(), "Проверочная лекция.md");
      assert.equal(await page.getByRole("dialog").count(), 0);
    }
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log("Telegram browser checks passed: Android/iOS SDK mocks, consents, theme, history, browser fallback, mobile layout, auth errors, consent cancel, notification deep link, deferred SDK, export links, local export");
} finally {
  await browser.close();
}
