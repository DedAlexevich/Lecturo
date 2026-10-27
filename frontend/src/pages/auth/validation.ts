const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateEmail(email: string): string | undefined {
  if (email.trim() === "") return "Введите адрес почты";
  if (!emailPattern.test(email.trim())) return "Проверьте адрес почты";
  return undefined;
}

export function validateNewPassword(password: string): string | undefined {
  if (password.length < 8) return "Минимум 8 символов";
  if (password.length > 128) return "Не больше 128 символов";
  return undefined;
}

export function validatePasswordConfirm(password: string, confirm: string): string | undefined {
  if (password !== confirm) return "Пароли не совпадают";
  return undefined;
}
