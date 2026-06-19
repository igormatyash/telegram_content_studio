const authLocale = localStorage.getItem("content-studio:locale") || "uk";
const authTextEn = {
  "Вхід · Content Studio": "Sign in · Content Studio",
  "Реєстрація · Content Studio": "Registration · Content Studio",
  "AI publishing workspace": "AI publishing workspace",
  "14 днів trial": "14-day trial",
  "Безпечний доступ": "Secure access",
  "Увійдіть у workspace": "Sign in to workspace",
  "Керуйте контентом системно, з командою і без хаосу.": "Manage content systematically, with a team and without chaos.",
  "Email або логін": "Email or username",
  "Пароль": "Password",
  "Запам’ятати мене": "Remember me",
  "Забули пароль?": "Forgot password?",
  "Увійти": "Sign in",
  "або": "or",
  "Продовжити з Google": "Continue with Google",
  "Ще не маєте акаунта?": "Do not have an account yet?",
  "Створити компанію": "Create company",
  "Заплановано": "Scheduled",
  "Як системно працювати з відгуками клієнтів": "How to work with client feedback systematically",
  "Кожен другий клієнт залишає відгук, але не кожна команда використовує цей сигнал.": "Every second client leaves feedback, but not every team uses this signal.",
  "Створюйте контент системно, з командою, без хаосу.": "Create content systematically, with a team and without chaos.",
  "Створіть компанію": "Create a company",
  "Після реєстрації ми створимо перший workspace. Додаткові workspace можна буде додати в кабінеті компанії.": "After registration we will create the first workspace. Additional workspaces can be added in the company account.",
  "Вас запросили до Content Studio": "You were invited to Content Studio",
  "Реферальне джерело буде збережено після реєстрації.": "The referral source will be saved after registration.",
  "Ваше ім’я": "Your name",
  "Логін": "Username",
  "Назва компанії": "Company name",
  "Компанія об’єднує користувачів, ролі та всі ваші workspace.": "A company brings together users, roles and all your workspaces.",
  "Змінити URL компанії вручну": "Change company URL manually",
  "Slug компанії": "Company slug",
  "Необов’язково. Латиниця, цифри та дефіс.": "Optional. Latin letters, digits and hyphen.",
  "Створити компанію та workspace": "Create company and workspace",
  "Вже маєте акаунт?": "Already have an account?",
  "Ваш бренд · Telegram": "Your brand · Telegram",
  "Готово": "Ready",
  "Контент-процес від ідеї до публікації": "Content process from idea to publication",
  "Ідеї, чернетки, календар, бренд-профіль та AI-витрати в одному workspace.": "Ideas, drafts, calendar, brand profile and AI expenses in one workspace.",
  "Запустіть контент-систему компанії за кілька хвилин.": "Launch a company content system in minutes.",
  "Прийняти запрошення": "Accept invitation",
  "Створити новий пароль": "Create a new password",
  "Приєднайтесь до команди Content Studio.": "Join the Content Studio team.",
  "Посилання одноразове. Після зміни пароля активні сесії буде завершено.": "This is a one-time link. Active sessions will be ended after the password change.",
  "Новий пароль": "New password",
  "Продовжити": "Continue",
  "Завантаження…": "Loading...",
  "Входимо…": "Signing in...",
  "Створюємо…": "Creating...",
  "Не вдалося увійти": "Could not sign in",
  "Не вдалося зареєструватися": "Could not register",
  "Не вдалося виконати дію": "Could not complete the action",
  "Реферальне посилання недійсне або вже вимкнене. Ви можете зареєструватися напряму.": "The referral link is invalid or disabled. You can register directly.",
  "Попросіть адміністратора workspace створити одноразове посилання для відновлення.": "Ask a workspace administrator to create a one-time recovery link.",
};

function authT(value) {
  if (authLocale !== "en") return value;
  const text = String(value ?? "");
  const trimmed = text.trim();
  return text.replace(trimmed, authTextEn[trimmed] || trimmed);
}

function applyAuthLocale() {
  if (authLocale !== "en") return;
  document.documentElement.lang = "en";
  document.title = authT(document.title);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(node => {
    node.nodeValue = authT(node.nodeValue);
  });
  document.querySelectorAll("[placeholder],[title],[aria-label]").forEach(node => {
    for (const attr of ["placeholder", "title", "aria-label"]) {
      if (node.hasAttribute(attr)) node.setAttribute(attr, authT(node.getAttribute(attr)));
    }
  });
}

window.authT = authT;
applyAuthLocale();
