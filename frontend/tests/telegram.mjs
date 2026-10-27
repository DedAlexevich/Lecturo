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
    await page.getByRole("button", { name: "Выйти", exact: true }).click();
    await page.waitForURL(base + "/login");
    assert.equal(await page.evaluate(() => localStorage.getItem("lecturo.token")), null);
    await page.getByRole("button", { name: "Войти через Telegram", exact: true }).waitFor();
    assert.equal(requests.length, 1);
    await page.getByRole("button", { name: "Войти через Telegram", exact: true }).click();
    await page.waitForURL(base + "/");
    assert.equal(requests.length, 2);
    assert.deepEqual(errors, []);
    await context.close();
  }
  {
    const { context, page, requests, errors } = await setup("ios", 200, true);
    await page.goto(base + "/");
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
    await page.getByRole("button", { name: "Выйти", exact: true }).waitFor();
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
  for (const path of ["/login", "/register"]) {
    const miniApp = await setup("android", 401);
    await miniApp.page.goto(base + path);
    await miniApp.page.getByRole("alert").filter({ hasText: "Вход через Telegram" }).waitFor();
    assert.equal(await miniApp.page.locator(".auth-telegram").count(), 0);
    assert.equal(await miniApp.page.getByRole("button", { name: "Повторить вход" }).count(), 1);
    assert.equal(await miniApp.page.getByRole("textbox", { name: "Почта" }).count(), 1);
    assert.deepEqual(miniApp.errors, []);
    await miniApp.context.close();
    const browserPage = await setup(undefined);
    await browserPage.page.goto(base + path);
    await browserPage.page.locator(".auth-telegram").waitFor({ state: "attached" });
    assert.equal(browserPage.requests.length, 0);
    await browserPage.context.close();
  }
  console.log("Telegram browser checks passed: Android/iOS SDK mocks, consents, theme, history, browser fallback, mobile layout, auth errors");
} finally {
  await browser.close();
}
