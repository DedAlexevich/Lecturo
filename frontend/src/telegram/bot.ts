export const telegramBotUsername = import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined;

export const telegramBotUrl = telegramBotUsername ? `https://t.me/${telegramBotUsername}?start=notify` : null;
