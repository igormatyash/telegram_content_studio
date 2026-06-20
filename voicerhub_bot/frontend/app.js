const basePath = document.body.dataset.basePath || "";
const apiUrl = path => `${basePath}/${path.replace(/^\/+/, "")}`;
const state = {
  me: null,
  company: null,
  data: null,
  users: [],
  view: "home",
  ideaFilter: "all",
  draftFilter: "all",
  brandTab: "profile",
  settingsTab: "workspace",
  calendarDate: new Date(),
  onboardingStep: 1,
  usage: null,
  referral: null,
  platformUsage: null,
  platformPeriod: "month",
  platformSection: "overview",
  platformClientId: null,
  platformCompanyId: null,
  platformData: {},
  serviceUpdates: {items: [], latest_id: 0},
  lists: {},
  selected: {},
  recentJobIds: new Set(),
  recentDraftIds: new Set(),
  completedJobs: [],
  plans: null,
  roles: null,
  instagramIntegration: null,
  currentPublishJobs: [],
  guideStep: 0,
  locale: localStorage.getItem("content-studio:locale") || "uk",
  appearanceDirty: false,
};
let generationPollTimer = null;
let generationSignature = "";
const viewRoutes = {
  home: "dashboard",
  ideas: "ideas",
  plan: "content-plan",
  drafts: "drafts",
  calendar: "calendar",
  brand: "brand",
  analytics: "expenses",
  settings: "settings",
  platform: "platform",
};
const routeViews = Object.fromEntries(
  Object.entries(viewRoutes).map(([view, route]) => [route, view]),
);
const titles = {
  home: ["Головна", "Огляд вашого контенту та найближчих дій."],
  ideas: ["Ідеї", "Генеруйте та зберігайте теми для майбутніх публікацій."],
  plan: ["Контент-план", "Плануйте контент на тиждень або місяць."],
  drafts: ["Чернетки", "Перевіряйте, редагуйте та готуйте матеріали до публікації."],
  calendar: ["Календар", "Плануйте публікації та керуйте графіком виходу контенту."],
  brand: ["Бренд", "Налаштуйте стиль комунікації, рубрики та візуальні правила."],
  analytics: ["Витрати", "Контролюйте AI-витрати, генерації та використання моделей."],
  settings: ["Налаштування", "Керуйте workspace, користувачами, каналами та режимом роботи."],
  platform: ["Платформа", "Клієнти, компанії, активність і витрати сервісу."],
};
const translations = {
  uk: {
    localeCode: "UA",
    localeFlag: "🇺🇦",
    guide: "Гайд",
    updates: "Оновлення",
    search: "Пошук",
    create: "＋ Створити",
    exportCsv: "CSV",
    exportExcel: "Excel",
    chooseExport: "Оберіть формат експорту",
    noExportData: "Немає даних для експорту",
    brandFilled: "Наповнений на",
    fillBrand: "Доповнити профіль →",
  },
  en: {
    localeCode: "EN",
    localeFlag: "🇬🇧",
    guide: "Guide",
    updates: "Updates",
    search: "Search",
    create: "＋ Create",
    exportCsv: "CSV",
    exportExcel: "Excel",
    chooseExport: "Choose export format",
    noExportData: "No data to export",
    brandFilled: "Filled",
    fillBrand: "Complete profile →",
  },
};
const uiTextEn = {
  "Завантаження…": "Loading...",
  "Workspace": "Workspace",
  "Головна": "Home",
  "Ідеї": "Ideas",
  "Контент-план": "Content plan",
  "Дошка": "Board",
  "Чернетки": "Drafts",
  "Календар": "Calendar",
  "Налаштування": "Settings",
  "Бренд": "Brand",
  "Витрати": "Expenses",
  "Аналітика": "Analytics",
  "Платформа": "Platform",
  "Огляд": "Overview",
  "Клієнти": "Clients",
  "Компанії": "Companies",
  "Користувачі": "Users",
  "Реферали": "Referrals",
  "Активність": "Activity",
  "Вийти": "Log out",
  "Відкрити меню": "Open menu",
  "Змінити мову": "Change language",
  "Оновлення": "Updates",
  "Пошук": "Search",
  "Сповіщення": "Notifications",
  "Створити": "Create",
  "＋ Створити": "+ Create",
  "Що зробити зараз": "What to do now",
  "Швидкі дії": "Quick actions",
  "Наступні публікації": "Upcoming posts",
  "Заплановано": "Scheduled",
  "Нові теми": "New topics",
  "У роботі": "In progress",
  "Потребують уваги": "Need attention",
  "Очікують публікації": "Waiting to publish",
  "У календарі": "In calendar",
  "За весь час": "All time",
  "Згенерувати ідеї": "Generate ideas",
  "AI запропонує теми на основі бренду": "AI will suggest topics based on the brand",
  "Створити контент-план": "Create content plan",
  "На тиждень або місяць": "For a week or month",
  "Створити чернетку": "Create draft",
  "З ідеї або з нуля": "From an idea or from scratch",
  "Запланувати пост": "Schedule post",
  "Чернетка з візуалом → календар": "Draft with visual → calendar",
  "Публікацій ще немає": "No publications yet",
  "Підготуйте чернетку та додайте її до календаря.": "Prepare a draft and add it to the calendar.",
  "Бренд-профіль": "Brand profile",
  "Заповнений бренд-профіль робить AI-результати точнішими.": "A complete brand profile makes AI results more accurate.",
  "Створити вручну": "Create manually",
  "✦ Згенерувати ідеї": "✦ Generate ideas",
  "Параметри плану": "Plan settings",
  "Швидко створіть тижневий або місячний план без довгого скролу.": "Quickly create a weekly or monthly plan without long scrolling.",
  "✦ Згенерувати план": "✦ Generate plan",
  "Період": "Period",
  "Тиждень": "Week",
  "Місяць": "Month",
  "Дата початку": "Start date",
  "Кількість постів": "Number of posts",
  "Рубрика": "Rubric",
  "Результат": "Result",
  "Створити ідеї": "Create ideas",
  "Поставити чернетки в чергу": "Queue drafts",
  "Мета": "Goal",
  "Редакційний календар": "Editorial calendar",
  "Експорт": "Export",
  "Без розкладу": "Unscheduled",
  "Матеріали без дати": "Materials without date",
  "Виберіть матеріал, щоб одразу призначити дату.": "Choose a material to assign a date immediately.",
  "Сьогодні": "Today",
  "Профіль компанії": "Company profile",
  "Tone of voice": "Tone of voice",
  "Рубрики": "Rubrics",
  "Візуальні стилі": "Visual styles",
  "Матеріали бренду": "Brand materials",
  "Оформлення": "Appearance",
  "Витрати по днях": "Daily expenses",
  "Останні 30 днів": "Last 30 days",
  "Експортувати звіт": "Export report",
  "Наведіть на стовпчик": "Hover a bar",
  "Деталі витрат": "Expense details",
  "Сума, дата та частка періоду зʼявляться тут.": "Amount, date and share of the period will appear here.",
  "По моделях": "By models",
  "Топ рубрик": "Top rubrics",
  "Режим роботи": "Workflow mode",
  "Ролі": "Roles",
  "Тарифи": "Plans",
  "Реферальна програма": "Referral program",
  "Канали": "Channels",
  "Безпека": "Security",
  "Super Admin Dashboard": "Super Admin Dashboard",
  "Огляд платформи": "Platform overview",
  "Клієнти, workspace, активність і AI-витрати в одному місці.": "Clients, workspaces, activity and AI expenses in one place.",
  "Оновити дані": "Refresh data",
  "Ваші робочі простори": "Your workspaces",
  "Вибрати workspace": "Choose workspace",
  "Кожен workspace має окремі бренд, контент, команду, канал і календар.": "Each workspace has a separate brand, content, team, channel and calendar.",
  "Закрити": "Close",
  "Налаштування workspace": "Workspace setup",
  "Пропустити": "Skip",
  "← Назад": "← Back",
  "Далі →": "Next →",
  "Скасувати": "Cancel",
  "Зберегти": "Save",
  "Ваші ідеї генеруються": "Your ideas are being generated",
  "Аналізуємо бренд, рубрики та формуємо нові теми.": "Analyzing the brand and rubrics, then creating new topics.",
  "Не закривайте сторінку. Зазвичай це займає до хвилини.": "Do not close the page. It usually takes up to a minute.",
  "Редактор публікації": "Publication editor",
  "Як працювати із сервісом": "How to use the service",
  "Більше не показувати": "Do not show again",
  "CONTENT STUDIO · Налаштування workspace · Voicer Wave": "CONTENT STUDIO · Workspace settings · Voicer Wave",
  "Ідея": "Idea",
  "Чернетка": "Draft",
  "На перевірці": "In review",
  "Потрібні правки": "Needs changes",
  "Готово": "Ready",
  "Опубліковано": "Published",
  "Генерується": "Generating",
  "Візуал": "Visual",
  "Помилка": "Error",
  "Скасовано": "Cancelled",
  "На перевірку": "Send to review",
  "Позначити готовим": "Mark ready",
  "Повернути на правки": "Request changes",
  "Погодити": "Approve",
  "Повернути в чернетки": "Return to drafts",
  "Platform Admin": "Platform Admin",
  "Власник": "Owner",
  "Адміністратор": "Administrator",
  "Контент-менеджер": "Content manager",
  "Редактор": "Editor",
  "Публікатор": "Publisher",
  "Переглядач": "Viewer",
  "Учасник": "Member",
  "Ще не заплановано": "Not scheduled yet",
  "Сайт": "Website",
  "Основний колір": "Primary color",
  "Опис компанії": "Company description",
  "Ключові продукти або послуги": "Key products or services",
  "Зберегти профіль": "Save profile",
  "Стиль комунікації": "Communication style",
  "Зберегти": "Save",
  "Що можна": "What to do",
  "Чого не можна": "What to avoid",
  "Рубрики контенту": "Content rubrics",
  "Як AI використовує рубрики": "How AI uses rubrics",
  "Створити рубрику": "Create rubric",
  "Ціль": "Goal",
  "Тон": "Tone",
  "Статус": "Status",
  "Активна": "Active",
  "Неактивна": "Inactive",
  "Редагувати": "Edit",
  "Стилі workspace": "Workspace styles",
  "Вбудовані стилі": "Built-in styles",
  "Системний": "System",
  "Власних стилів ще немає": "No custom styles yet",
  "Створити стиль": "Create style",
  "Матеріалів ще немає": "No materials yet",
  "Додати посилання": "Add link",
  "Завантажити матеріал": "Upload material",
  "Видалити": "Delete",
  "Брендований workspace": "Branded workspace",
  "Назва workspace": "Workspace name",
  "Короткий опис": "Short description",
  "Кольори інтерфейсу": "Interface colors",
  "Основний": "Primary",
  "Додатковий": "Secondary",
  "Аватар workspace": "Workspace avatar",
  "Логотип компанії": "Company logo",
  "Завантажити й обрізати": "Upload and crop",
  "Завантажити логотип": "Upload logo",
  "Зберегти оформлення": "Save appearance",
  "Так workspace виглядатиме в інтерфейсі": "This is how the workspace will look in the interface",
  "Тариф": "Plan",
  "Публікації": "Publications",
  "AI-бюджет": "Generation limits",
  "Повторити onboarding": "Restart onboarding",
  "Небезпечна зона": "Danger zone",
  "Видалення workspace": "Delete workspace",
  "Видалити workspace": "Delete workspace",
  "Загальні": "General",
  "Режим роботи workspace": "Workspace workflow mode",
  "Оберіть, як ваша команда працює з контентом.": "Choose how your team works with content.",
  "Редакційний pipeline": "Editorial pipeline",
  "Контент-дошка Kanban": "Content Kanban board",
  "Зберегти режим": "Save mode",
  "Користувачі workspace": "Workspace users",
  "Запросити користувача": "Invite user",
  "Змінити роль": "Change role",
  "Деактивувати": "Deactivate",
  "Видалити з workspace": "Remove from workspace",
  "Активний": "Active",
  "Вимкнений": "Disabled",
  "Права доступу": "Access permissions",
  "Ролі workspace": "Workspace roles",
  "Оберіть план для workspace": "Choose a workspace plan",
  "Оплатити в Telegram": "Pay in Telegram",
  "Поточний тариф": "Current plan",
  "Оплата через Telegram Stars": "Payment via Telegram Stars",
  "Запрошуйте нових користувачів": "Invite new users",
  "Скопіювати посилання": "Copy link",
  "Оновити код": "Rotate code",
  "Вимкнути посилання": "Disable link",
  "Переходи": "Clicks",
  "Реєстрації": "Signups",
  "Активні клієнти": "Active clients",
  "Підключення каналу": "Channel connection",
  "Підключено": "Connected",
  "Не підключено": "Not connected",
  "Перевірити підключення": "Test connection",
  "Перевірити та зберегти": "Test and save",
  "Підключити Instagram": "Connect Instagram",
  "Відключити Instagram": "Disconnect Instagram",
  "Скоро з’являться": "Coming soon",
  "Більше соцмереж": "More social networks",
  "Змінити пароль": "Change password",
  "Новий пароль": "New password",
  "Клієнт": "Client",
  "Реєстрація": "Registration",
  "Останній вхід": "Last login",
  "Джерело": "Source",
  "Компанія": "Company",
  "Люди": "People",
  "Контент": "Content",
  "AI-витрати": "AI expenses",
  "Деталі": "Details",
  "Код": "Code",
  "Власник": "Owner",
  "Події платформи": "Platform events",
  "Подія": "Event",
  "Дата": "Date",
  "Останні входи": "Recent logins",
  "Успішно": "Success",
  "Операції": "Operations",
  "Тексти": "Texts",
  "Зображення": "Images",
  "Загальні витрати": "Total expenses",
  "Оберіть формат експорту": "Choose export format",
  "Легкий текстовий формат для таблиць і CRM.": "Lightweight text format for spreadsheets and CRM.",
  "Відкривається напряму в Microsoft Excel.": "Opens directly in Microsoft Excel.",
  "Немає даних для експорту": "No data to export",
  "Пошук": "Search",
  "Ідеї, чернетки та розділи": "Ideas, drafts and sections",
  "Нічого не знайдено.": "Nothing found.",
  "Що бажаєте створити?": "What would you like to create?",
  "Почніть із потрібного результату": "Start with the desired result",
  "Ідеї з AI": "AI ideas",
  "Чернетку вручну": "Manual draft",
  "Додати свій текст або почати з нуля": "Add your own text or start from scratch",
  "Розкласти публікації на тиждень чи місяць": "Plan posts for a week or month",
  "Оновлення сервісу": "Service updates",
  "Що нового в Content Studio": "What is new in Content Studio",
  "Додати повідомлення": "Add message",
  "Оновлень ще немає": "No updates yet",
  "Редагувати оновлення": "Edit update",
  "Нове повідомлення в ленту": "New feed message",
  "Опублікувати": "Publish",
  "Архівувати": "Archive",
  "Непрочитаних:": "Unread:",
  "Усі сповіщення прочитані": "All notifications are read",
  "Прочитати все": "Mark all as read",
  "Прочитано": "Read",
  "Повторити швидку генерацію": "Retry quick generation",
  "Все гаразд": "Everything is fine",
  "Немає помилок генерації, попереджень про тариф або бюджет.": "No generation errors, plan warnings or budget alerts.",
};
Object.assign(uiTextEn, {
  "Перегенерувати текст": "Regenerate text",
  "Запланувати": "Schedule",
  "Спочатку потрібен візуал": "A visual is required first",
  "Спочатку погодьте матеріал": "Approve the material first",
  "Дата і час": "Date and time",
  "Заголовок для поста": "Post title",
  "Заголовок на візуалі": "Visual title",
  "Без emoji та зайвих символів.": "Without emoji or unnecessary characters.",
  "Текст публікації": "Publication text",
  "Посилання": "Link",
  "Повернути в готові": "Return to ready",
  "Канали публікації": "Publishing channels",
  "Опублікувати": "Publish",
  "Підключіть Instagram": "Connect Instagram",
  "Одиночне зображення + caption.": "Single image + caption.",
  "Reels": "Reels",
  "Carousel": "Carousel",
  "Потрібен відео-модуль.": "Video module required.",
  "Потрібно кілька медіа в чернетці.": "Multiple media files are required in the draft.",
  "Ласкаво просимо до Content Studio": "Welcome to Content Studio",
  "Назва компанії": "Company name",
  "Технічний URL система створює автоматично.": "The system creates the technical URL automatically.",
  "Бренд та стиль комунікації": "Brand and communication style",
  "Ці дані використовуються як постійний контекст для AI. Пишіть факти й правила, а не рекламні гасла.": "This data is used as persistent AI context. Write facts and rules, not advertising slogans.",
  "Ключові послуги": "Key services",
  "Заборонені фрази": "Forbidden phrases",
  "Підключіть Telegram-канал": "Connect a Telegram channel",
  "Додайте бота адміністратором каналу. Ми перевіримо token, канал і права до збереження.": "Add the bot as a channel administrator. We will check the token, channel and permissions before saving.",
  "Введіть обидва значення для перевірки.": "Enter both values to test the connection.",
  "Перевірити зараз": "Test now",
  "Додайте рубрики контенту": "Add content rubrics",
  "Рубрика — це постійний напрям контенту. Для кожної вкажіть назву та поясніть, про що писати.": "A rubric is a recurring content direction. Give each one a name and explain what to write about.",
  "Назва": "Name",
  "Що публікуємо": "What to publish",
  "Додати рубрику": "Add rubric",
  "Створіть перший контент-план": "Create the first content plan",
  "AI використає бренд-профіль і рубрики. План створиться як ідеї, які можна переглянути до генерації чернеток.": "AI will use the brand profile and rubrics. The plan will be created as ideas that can be reviewed before draft generation.",
  "Завершити": "Finish",
  "Створіть робочий простір": "Create a workspace",
  "Заповніть бренд-профіль": "Complete the brand profile",
  "Створіть рубрики": "Create rubrics",
  "Згенеруйте та відберіть ідеї": "Generate and select ideas",
  "Підготуйте чернетки": "Prepare drafts",
  "Заплануйте або опублікуйте": "Schedule or publish",
  "Керуйте командою та результатом": "Manage team and results",
  "Крок": "Step",
  "Заголовок": "Title",
  "Тип": "Type",
  "Нова функція": "New feature",
  "Виправлення": "Fix",
  "Технічні роботи": "Maintenance",
  "Оголошення": "Announcement",
  "Важливість": "Importance",
  "Інформація": "Information",
  "Позитивне оновлення": "Positive update",
  "Важливо": "Important",
  "Опубліковано": "Published",
  "Архів": "Archive",
  "Закріпити зверху": "Pin to top",
  "Показувати з": "Show from",
  "Показувати до": "Show until",
  "Текст повідомлення": "Message text",
  "Зберегти": "Save",
  "Створити компанію та власника": "Create company and owner",
  "Що відбудеться": "What will happen",
  "Назва першого workspace": "First workspace name",
  "Ім’я власника": "Owner name",
  "Email власника": "Owner email",
  "Логін власника": "Owner login",
  "Тимчасовий пароль": "Temporary password",
  "Ліміт користувачів": "User limit",
  "Публікацій на місяць": "Publications per month",
  "Створити компанію": "Create company",
  "Змінити URL вручну": "Change URL manually",
  "Необов’язково. Якщо поле порожнє, URL буде створено автоматично.": "Optional. If empty, the URL will be created automatically.",
  "Відкрито": "Opened",
  "Перейти": "Open",
  "Поточна компанія": "Current company",
  "Новий workspace матиме окремі контент, бренд, Telegram-канал, календар і ролі.": "The new workspace will have separate content, brand, Telegram channel, calendar and roles.",
  "URL буде створено автоматично з назви.": "URL will be generated automatically from the name.",
  "Видалити назавжди": "Delete permanently",
  "Видаляємо…": "Deleting...",
  "Усі дані буде видалено без можливості відновлення": "All data will be permanently deleted",
  "Для підтвердження введіть точну назву:": "To confirm, enter the exact name:",
  "Рубрику збережено": "Rubric saved",
  "Активувати": "Activate",
  "Вибрати всі": "Select all",
  "Обрати всіх": "Select all",
  "Обрати всі": "Select all",
});
Object.assign(uiTextEn, {
  "AI generator": "AI generator",
  "AI-витрати · місяць": "Generations · month",
  "AI запропонує теми на основі бренду": "AI will suggest topics based on the brand",
  "AI використає бренд-профіль і рубрики. План створиться як ідеї, які можна переглянути до генерації чернеток.": "AI will use the brand profile and rubrics. The plan will be created as ideas you can review before generating drafts.",
  "AI дивиться на листи і дзвінки без шуму": "AI reviews messages and calls without noise",
  "AI-бюджет, $": "Internal AI cost budget, $",
  "Відключаємо…": "Disconnecting...",
  "Готуємо Meta Login…": "Preparing Meta Login...",
  "Business": "Business",
  "Channel username": "Channel username",
  "Content Studio Academy": "Content Studio Academy",
  "Content Studio AI": "Content Studio AI",
  "Email": "Email",
  "Email власника": "Owner email",
  "Facebook Page": "Facebook Page",
  "Feed image": "Feed image",
  "Instagram Feed": "Instagram Feed",
  "Instagram Feed заплановано": "Instagram Feed scheduled",
  "Instagram не опублікував пост": "Instagram did not publish the post",
  "Instagram відключено": "Instagram disconnected",
  "Instagram ще не активовано на платформі": "Instagram is not enabled on the platform yet",
  "Instagram-публікацію створено": "Instagram publication created",
  "Пост опубліковано в Instagram": "Post published to Instagram",
  "Meta повернула помилку без деталей.": "Meta returned an error without details.",
  "Owner": "Owner",
  "PNG, JPG, WebP, PDF, DOCX або PPTX до 20 MB.": "PNG, JPG, WebP, PDF, DOCX or PPTX up to 20 MB.",
  "Platform Admin є окремою платформною роллю. Ролі нижче діють лише всередині поточного workspace. Наведіть курсор або сфокусуйте право, щоб побачити пояснення.": "Platform Admin is a separate platform role. The roles below apply only inside the current workspace. Hover or focus a permission to see its explanation.",
  "Reels скоро": "Reels soon",
  "Carousel скоро": "Carousel soon",
  "Reset link": "Reset link",
  "Slug рубрики:": "Rubric slug:",
  "Telegram підключено": "Telegram connected",
  "Telegram працює без змін.": "Telegram keeps working without changes.",
  "Telegram працює як раніше. Instagram — окрема публікація, яка не змінює статус Telegram-поста.": "Telegram works as before. Instagram is a separate publication and does not change the Telegram post status.",
  "Token зберігається зашифрованим і не показується повторно.": "The token is stored encrypted and is not shown again.",
  "Trial завершується через": "Trial ends in",
  "URL": "URL",
  "URL буде створено автоматично з назви.": "The URL will be generated automatically from the name.",
  "Ваш бренд · Telegram": "Your brand · Telegram",
  "Ваші робочі простори": "Your workspaces",
  "Вас запросили до Content Studio": "You were invited to Content Studio",
  "Вбудовані стилі": "Built-in styles",
  "Введіть дані для автоматичної перевірки.": "Enter data for automatic validation.",
  "Введіть точну назву workspace для підтвердження.": "Enter the exact workspace name to confirm.",
  "Виберіть матеріал, щоб одразу призначити дату.": "Choose a material to assign a date right away.",
  "Виберіть параметри та створіть перший план.": "Choose parameters and create the first plan.",
  "Видалити матеріал?": "Delete this material?",
  "Видалити помилкове завдання?": "Delete the failed job?",
  "Видалити цю ідею?": "Delete this idea?",
  "Видалити назавжди": "Delete permanently",
  "Видалення workspace": "Workspace deletion",
  "Видаляємо…": "Deleting...",
  "Використовується у візуальних шаблонах.": "Used in visual templates.",
  "Використовуйте таблицю, пошук, фільтри й bulk-дії для великих списків.": "Use the table, search, filters and bulk actions for large lists.",
  "Вимкнути поточне реферальне посилання?": "Disable the current referral link?",
  "Відключити Instagram для цього workspace? Telegram залишиться підключеним.": "Disconnect Instagram for this workspace? Telegram will remain connected.",
  "Відкрийте розділ «Витрати» для деталізації.": "Open Expenses for details.",
  "Відкрийте чернетку, перевірте зображення та підключення Instagram.": "Open the draft and check the image and Instagram connection.",
  "Відкрити посилання": "Open link",
  "Відкрито": "Opened",
  "Власних стилів ще немає": "No custom styles yet",
  "Гайд більше не буде відкриватися автоматично. Він доступний у хедері.": "The guide will no longer open automatically. It remains available in the header.",
  "Гайд завершено. Він завжди доступний у хедері.": "Guide completed. It is always available in the header.",
  "Генерацію перезапущено": "Generation restarted",
  "Генерацію повторено": "Generation retried",
  "Генерацію розпочато. Прогрес з’явиться у чернетках.": "Generation started. Progress will appear in Drafts.",
  "Генерація зупинилася без детального опису.": "Generation stopped without a detailed description.",
  "Генерація зупинилася. Деталі є у сповіщеннях.": "Generation stopped. Details are available in notifications.",
  "Глобальні шаблони доступні для використання, але не редагуються. Прев’ю завантажуються одразу, щоб швидше оцінити стиль.": "Global templates are available for use but cannot be edited. Previews load immediately so you can evaluate the style faster.",
  "Готові": "Ready",
  "Готовий": "Ready",
  "Готово до підключення": "Ready to connect",
  "Готово до публікації у Feed": "Ready to publish to Feed",
  "Дата від": "Date from",
  "Дата до": "Date to",
  "Дата публікації": "Publication date",
  "Датою публікації": "Publication date",
  "Датою створення": "Creation date",
  "Деактивувати записів?": "Deactivate records?",
  "Джерело реєстрації": "Registration source",
  "Додайте META_APP_ID, META_APP_SECRET, PUBLIC_APP_URL/META_REDIRECT_URI та увімкніть INSTAGRAM_ENABLED. Telegram працює без змін.": "Add META_APP_ID, META_APP_SECRET, PUBLIC_APP_URL/META_REDIRECT_URI and enable INSTAGRAM_ENABLED. Telegram keeps working unchanged.",
  "Додайте бота адміністратором каналу. Ми перевіримо token, канал і права до збереження.": "Add the bot as a channel administrator. We will validate the token, channel and permissions before saving.",
  "Додайте конкретні назви, цільову аудиторію та користь. Це стане контекстом для генерації.": "Add specific names, target audience and value. This becomes generation context.",
  "Додайте ключові послуги": "Add key services",
  "Додайте рубрики контенту": "Add content rubrics",
  "Додати повідомлення": "Add message",
  "Додати свій текст або почати з нуля": "Add your own text or start from scratch",
  "Доступно власнику": "Available to owner",
  "Дочекайтесь індикатора готовності, не оновлюючи сторінку.": "Wait for the readiness indicator without refreshing the page.",
  "Завантажте логотип, фото, референс або додайте важливе посилання.": "Upload a logo, photo, reference or add an important link.",
  "Завдання": "Job",
  "Залишилося": "Remaining",
  "Заплановані": "Scheduled",
  "Заплануйте або опублікуйте": "Schedule or publish",
  "Заповнений бренд-профіль робить AI-результати точнішими.": "A complete brand profile makes AI results more accurate.",
  "Запрошуйте команду та призначайте зрозумілі ролі.": "Invite your team and assign clear roles.",
  "Запустіть контент-систему компанії за кілька хвилин.": "Launch a company content system in minutes.",
  "Зберігаємо…": "Saving...",
  "Зміни збережено": "Changes saved",
  "Змінити URL компанії вручну": "Change company URL manually",
  "Змінити URL вручну": "Change URL manually",
  "Змінити пароль або створіть одноразове посилання через адміністратора workspace.": "Change the password or create a one-time link through a workspace administrator.",
  "Ідею видалено": "Idea deleted",
  "Ідею додано": "Idea added",
  "Ідеї готові та збережені": "Ideas are ready and saved",
  "Ідеї з AI": "AI ideas",
  "Ідеї, чернетки та розділи": "Ideas, drafts and sections",
  "Ідеї не публікуються напряму: спочатку з них створюється чернетка.": "Ideas are not published directly: first create a draft from them.",
  "Ім’я власника": "Owner name",
  "Канал має бути публічним або доступним боту.": "The channel must be public or accessible to the bot.",
  "Керуйте contentом системно, з командою і без хаосу.": "Manage content systematically, with a team and without chaos.",
  "Керуйте командою та результатом": "Manage the team and results",
  "Керуйте workspace, користувачами, каналами та режимом роботи.": "Manage workspace, users, channels and workflow mode.",
  "Клієнти, компанії, активність і витрати сервісу.": "Clients, companies, activity and service expenses.",
  "Клієнти, workspace, активність і AI-витрати в одному місці.": "Clients, workspaces, activity and AI expenses in one place.",
  "Коли з’являться нові функції або важливі повідомлення, вони будуть тут.": "New features and important messages will appear here.",
  "Компанія об’єднує користувачів, ролі та всі ваші workspace.": "A company brings together users, roles and all your workspaces.",
  "Контент-дошка Kanban": "Content Kanban board",
  "Контент-процес від ідеї до публікації": "Content process from idea to publication",
  "Коротко напишіть, що змінилось, кого це стосується і що користувачу потрібно зробити.": "Briefly describe what changed, who it affects and what the user should do.",
  "Латиниця, цифри та дефіс.": "Latin letters, digits and hyphen.",
  "Ліміт користувачів": "User limit",
  "Логін власника": "Owner login",
  "Матеріал готовий.": "Material is ready.",
  "Матеріал завантажено": "Material uploaded",
  "Матеріал збережено": "Material saved",
  "Матеріали допомагають AI краще розуміти стиль компанії: логотипи, кольори, презентації, брендбук і референси.": "Materials help AI better understand the company style: logos, colors, presentations, brand book and references.",
  "Матеріали оновлено": "Materials updated",
  "Ми готуємо публікації в інші канали без dead controls: картки нижче лише показують roadmap.": "We are preparing publishing to other channels without dead controls: the cards below only show the roadmap.",
  "Можна повторити генерацію або змінити рубрику/дані чернетки.": "You can retry generation or change the rubric/draft data.",
  "На перевірці": "In review",
  "Наведіть курсор або сфокусуйте право, щоб побачити пояснення.": "Hover or focus a permission to see its explanation.",
  "Назва або опис": "Name or description",
  "Назва продукту — коротко яку задачу він вирішує": "Product name — briefly what task it solves",
  "Назвою": "Name",
  "Найпопулярніший": "Most popular",
  "Налаштуйте стиль комунікації, рубрики та візуальні правила.": "Configure communication style, rubrics and visual rules.",
  "Налаштуйте workspace за п’ять коротких кроків. Прогрес зберігається після кожного кроку.": "Set up the workspace in five short steps. Progress is saved after each step.",
  "Наприклад: Оновили календар і планування постів": "For example: Updated calendar and post scheduling",
  "Наприклад: пояснити користь продукту, зібрати заявки, прогріти аудиторію": "For example: explain product value, collect leads, warm up the audience",
  "Натисніть у чернетках на позначку «Щойно створено», щоб швидко знайти матеріал.": "In Drafts, click the “Just created” marker to quickly find the material.",
  "Не вдалося згенерувати матеріал": "Could not generate material",
  "Не закривайте сторінку. Зазвичай це займає до хвилини.": "Do not close the page. This usually takes up to a minute.",
  "Не підключено": "Not connected",
  "Немає з’єднання з мережею. Зміни стануть доступними після відновлення зв’язку.": "No network connection. Changes will be available after connection is restored.",
  "Немає помилок генерації, попереджень про тариф або бюджет.": "No generation errors, plan warnings or budget alerts.",
  "Необов’язково. Латиниця, цифри та дефіс.": "Optional. Latin letters, digits and hyphen.",
  "Необов’язково. Якщо поле порожнє, URL буде створено автоматично.": "Optional. If empty, the URL will be created automatically.",
  "Нові спочатку": "Newest first",
  "Нові теми на основі бренду й рубрик": "New topics based on brand and rubrics",
  "Новий workspace матиме окремі контент, бренд, Telegram-канал, календар і ролі.": "The new workspace will have separate content, brand, Telegram channel, calendar and roles.",
  "Нову версію поставлено в чергу": "New version queued",
  "Оберіть дату і час": "Choose date and time",
  "Оберіть дату і час для Instagram": "Choose date and time for Instagram",
  "Оберіть план для workspace": "Choose a plan for the workspace",
  "Оберіть, як ваша команда працює з контентом.": "Choose how your team works with content.",
  "Окремий простір для контенту, команди та публікацій.": "Separate space for content, team and publications.",
  "Окремі бренд, команда, канал і календар": "Separate brand, team, channel and calendar",
  "Оплатити в Telegram": "Pay in Telegram",
  "Опублікувати пост зараз?": "Publish the post now?",
  "Опублікувати цей пост в Instagram Feed? Telegram-публікація не зміниться.": "Publish this post to Instagram Feed? Telegram publication will not change.",
  "Опубліковані": "Published",
  "Оплата через Telegram Stars": "Payment via Telegram Stars",
  "Опис": "Description",
  "Орієнтовна дата": "Approximate date",
  "Основний workspace": "Primary workspace",
  "Передайте власнику логін і тимчасовий пароль.": "Give the owner their login and temporary password.",
  "Перейти": "Open",
  "Перевірте тариф у налаштуваннях workspace.": "Check the plan in workspace settings.",
  "Перспективна тема для майбутньої публікації.": "Promising topic for a future post.",
  "Плануємо…": "Scheduling...",
  "Плануємо Instagram…": "Scheduling Instagram...",
  "Платформа": "Platform",
  "Планова дата": "Planned date",
  "Повторюємо…": "Retrying...",
  "Поділіться персональним посиланням. Тут відображається лише ваша статистика в поточному workspace.": "Share your personal link. Only your statistics for the current workspace are shown here.",
  "Позначку": "Marker",
  "Потрібен Instagram Business або Creator": "Instagram Business or Creator account required",
  "Потрібен Meta App": "Meta App required",
  "Поточний": "Current",
  "Поточний тариф": "Current plan",
  "Публікацій на місяць": "Publications per month",
  "Публікацію додано до календаря": "Publication added to calendar",
  "Публікацію заплановано": "Publication scheduled",
  "Публікацію повернуто в готові": "Publication returned to ready",
  "Публікуємо…": "Publishing...",
  "Публікуємо в Instagram…": "Publishing to Instagram...",
  "Після оплати ліміти оновляться автоматично після підтвердження платежу.": "After payment, limits update automatically once payment is confirmed.",
  "Після реєстрації ми створимо перший workspace. Додаткові workspace можна буде додати в кабінеті компанії.": "After registration we will create the first workspace. Additional workspaces can be added in the company account.",
  "Підготуйте чернетку та додайте її до календаря.": "Prepare a draft and add it to the calendar.",
  "Підключення відбувається через Facebook Login і прив’язану Facebook Page.": "Connection uses Facebook Login and a linked Facebook Page.",
  "Підключіть Telegram-канал": "Connect a Telegram channel",
  "Підключіть Instagram": "Connect Instagram",
  "Підключено:": "Connected:",
  "Підключений канал": "Connected channel",
  "Публікуйте готові візуальні пости у Instagram Feed. Reels і Carousel вже закладені в інтерфейс, але будуть увімкнені після окремого медіа-модуля.": "Publish finished visual posts to Instagram Feed. Reels and Carousel are already prepared in the UI, but will be enabled after a separate media module.",
  "Редакційний pipeline": "Editorial pipeline",
  "Режим збережено": "Mode saved",
  "Реферальне джерело буде збережено після реєстрації.": "The referral source will be saved after registration.",
  "Реферальне посилання вимкнено": "Referral link disabled",
  "Реферальне посилання скопійовано": "Referral link copied",
  "Рубрика — це постійний напрям контенту. Для кожної вкажіть назву та поясніть, про що писати.": "A rubric is a recurring content direction. Give each one a name and explain what to write about.",
  "Рубрики допомагають Content Studio створювати контент системно. Кожна рубрика задає тему, ціль, тон і правила для AI.": "Rubrics help Content Studio create content systematically. Each rubric defines a topic, goal, tone and AI rules.",
  "Рубрики оновлено": "Rubrics updated",
  "Рубрику збережено": "Rubric saved",
  "Скасовуємо…": "Cancelling...",
  "Скоро з’являться": "Coming soon",
  "Спробуйте повторити генерацію або перевірте налаштування AI.": "Try generation again or check AI settings.",
  "Старі спочатку": "Oldest first",
  "Статус змінено:": "Status changed:",
  "Створено": "Created",
  "Створено новий реферальний код": "New referral code created",
  "Створити компанію": "Create company",
  "Створити компанію та workspace": "Create company and workspace",
  "Створити workspace": "Create workspace",
  "Створіть компанію": "Create a company",
  "Створіть перші теми на основі бренду та рубрик.": "Create the first topics based on brand and rubrics.",
  "Створіть рубрики, щоб AI міг планувати експертні пости, кейси, поради, новини та продажні матеріали.": "Create rubrics so AI can plan expert posts, cases, tips, news and sales content.",
  "Створіть стиль для генерації візуалів у впізнаваній манері бренду.": "Create a style for generating visuals in a recognizable brand manner.",
  "Створюємо…": "Creating...",
  "Запускаємо…": "Starting...",
  "Створюємо текст і структуру поста": "Creating text and post structure",
  "Сума, дата та частка періоду зʼявляться тут.": "Amount, date and share of period will appear here.",
  "Сьогодні": "Today",
  "Тариф і ліміти": "Plan and limits",
  "Текст": "Text",
  "Текст уже готовий, створюємо зображення": "Text is ready, creating image",
  "Термін тарифу завершився. AI-генерація та публікація тимчасово недоступні.": "The plan has expired. AI generation and publishing are temporarily unavailable.",
  "Технічний URL система створює автоматично.": "The system creates the technical URL automatically.",
  "Тимчасовий пароль": "Temporary password",
  "Тут з’являються нові функції, виправлення, планові роботи та важливі оголошення.": "New features, fixes, maintenance and important announcements appear here.",
  "У вас ще немає ідей": "You do not have ideas yet",
  "У вас ще немає рубрик": "You do not have rubrics yet",
  "Увійдіть у workspace": "Sign in to workspace",
  "Увійти": "Sign in",
  "Усі дані буде видалено без можливості відновлення": "All data will be permanently deleted",
  "Усі рубрики": "All rubrics",
  "Усі статуси": "All statuses",
  "Файл": "File",
  "Хто ви, для кого працюєте, яку проблему вирішуєте і чим відрізняєтесь.": "Who you are, who you work for, what problem you solve and how you differ.",
  "Це назавжди видалить контент, файли, налаштування й доступи поточного workspace.": "This will permanently delete content, files, settings and access for the current workspace.",
  "Це побачать користувачі сервісу в ленті оновлень. Без секретів, внутрішніх технічних деталей і токенів.": "Service users will see this in the updates feed. Do not include secrets, internal technical details or tokens.",
  "Чернетка з візуалом → календар": "Draft with visual → calendar",
  "Чернетку створено": "Draft created",
  "Чернетку створено. Вона підсвічена у списку чернеток.": "Draft created. It is highlighted in the drafts list.",
  "Чернеток ще немає": "No drafts yet",
  "Ще не маєте акаунта?": "Do not have an account yet?",
  "Щойно створено": "Just created",
  "Що нового в Content Studio": "What is new in Content Studio",
  "Що публікуємо": "What to publish",
  "7 днів": "7 days",
  "30 днів": "30 days",
  "Активна": "Active",
  "Активні компанії": "Active companies",
  "Агрегований звіт без перемикання між workspace.": "Aggregated report without switching workspaces.",
  "Будь-який workspace": "Any workspace",
  "Весь період": "All time",
  "Весь час": "All time",
  "Витрати всіх компаній": "All company expenses",
  "Витрати по компаніях, моделях і користувачах.": "Expenses by companies, models and users.",
  "Входів": "Logins",
  "Входів ще немає.": "No logins yet.",
  "До списку клієнтів": "Back to clients",
  "До списку компаній": "Back to companies",
  "Є workspace": "Has workspace",
  "Журнал важливих дій і входів без відкритих IP-адрес.": "Important action and login log without exposed IP addresses.",
  "Загальний список акаунтів сервісу.": "Full list of service accounts.",
  "Зареєстровані клієнтські компанії з’являться тут.": "Registered client companies will appear here.",
  "Запросив:": "Invited by:",
  "Клієнтів ще немає": "No clients yet",
  "Ключові метрики реєстрацій, клієнтів і використання.": "Key registration, client and usage metrics.",
  "Компаній не створено.": "No companies created.",
  "Компаній ще немає": "No companies yet",
  "Користувачів ще немає": "No users yet",
  "Люди": "People",
  "Місяць": "Month",
  "Невідомий користувач": "Unknown user",
  "Немає доступу": "No access",
  "Ні": "No",
  "Нові акаунти з’являться тут.": "New accounts will appear here.",
  "Нові за 7 днів": "New in 7 days",
  "Нові реєстрації з’являться в цьому розділі.": "New registrations will appear in this section.",
  "Нові сьогодні": "New today",
  "Остання активність": "Last activity",
  "Основна роль": "Primary role",
  "Перший workspace з’явиться після реєстрації або створення власником.": "The first workspace will appear after registration or owner creation.",
  "ПІБ / акаунт": "Full name / account",
  "Поки немає реферальних посилань": "No referral links yet",
  "Поки немає реферальних реєстрацій": "No referral signups yet",
  "Подій ще немає.": "No events yet.",
  "Посилання з’являться після відкриття реферального блоку користувачами.": "Links will appear after users open the referral block.",
  "Посилання, переходи та реферальні реєстрації.": "Links, clicks and referral signups.",
  "Помилка": "Error",
  "Профіль": "Profile",
  "Реєстрації по днях": "Registrations by day",
  "Реферальні посилання": "Referral links",
  "Реферальні реєстрації": "Referral signups",
  "Ролі у workspace": "Workspace roles",
  "Система": "System",
  "Так": "Yes",
  "Топ компаній за usage": "Top companies by usage",
  "Усі джерела": "All sources",
  "Усі зареєстровані клієнти та джерела їх залучення.": "All registered clients and acquisition sources.",
  "Учасники компанії з’являться тут.": "Company members will appear here.",
  "Час": "Time",
  "Чернетка #": "Draft #",
  "Workspace за місяць": "Workspaces this month",
  "Юридичні клієнти, їхні користувачі, ролі, workspace та активність.": "Legal clients, their users, roles, workspaces and activity.",
});
Object.assign(uiTextEn, {
  "← До списку клієнтів": "← Back to clients",
  "← До списку компаній": "← Back to companies",
  "＋ Додати повідомлення": "+ Add message",
  "＋ Додати рубрику": "+ Add rubric",
  "＋ Запланувати пост": "+ Schedule post",
  "＋ Запросити користувача": "+ Invite user",
  "＋ Створити рубрику": "+ Create rubric",
  "＋ Створити стиль": "+ Create style",
  "＋ Створити чернетку": "+ Create draft",
  "AI-теми, тексти та зображення": "AI topics, texts and images",
  "Активний матеріал": "Active material",
  "Активна рубрика": "Active rubric",
  "Активний стиль": "Active style",
  "Активні рубрики доступні в генерації ідей і контент-плану.": "Active rubrics are available for idea and content-plan generation.",
  "Аватар встановлено": "Avatar set",
  "Без зображення": "No image",
  "Брендбук": "Brand book",
  "Бренд-профіль — це пам’ять сервісу про вашу компанію. Чим конкретніше описані продукт, аудиторія, tone of voice, кольори й матеріали, тим стабільнішими будуть тексти та візуали.": "The brand profile is the service memory about your company. The more specific the product, audience, tone of voice, colors and materials are, the more stable texts and visuals become.",
  "В описі компанії пишіть факти: хто ви, для кого працюєте, яку проблему вирішуєте.": "In the company description, write facts: who you are, who you work for and what problem you solve.",
  "В оформленні завантажте аватар, логотип і виберіть основні кольори workspace.": "In Appearance, upload the avatar and logo and choose the main workspace colors.",
  "Відгуки клієнтів": "Client reviews",
  "Введіть @username каналу та повний bot token.": "Enter the channel @username and full bot token.",
  "Вибір workspace": "Workspace selection",
  "Відключено Instagram": "Instagram disconnected",
  "Відкритий": "Open",
  "Відкрито реферальне посилання": "Referral link opened",
  "Відкрити чернетку": "Open draft",
  "Відповідає на типові запитання клієнтів.": "Answers typical client questions.",
  "Візуальний стиль збережено": "Visual style saved",
  "Гайд": "Guide",
  "Гайд більше не буде відкриватися автоматично. Він доступний у хедері.": "The guide will no longer open automatically. It is available in the header.",
  "Гайд завершено. Він завжди доступний у хедері.": "Guide completed. It is always available in the header.",
  "Генеруємо…": "Generating...",
  "Генеруйте та зберігайте теми для майбутніх публікацій.": "Generate and save topics for future posts.",
  "Глобальні шаблони доступні для використання, але не редагуються. Прев’ю завантажуються одразу, щоб швидше оцінити стиль.": "Global templates are available for use but cannot be edited. Previews load immediately so you can evaluate the style faster.",
  "Дає короткі рекомендації для щоденної роботи.": "Gives short recommendations for daily work.",
  "Дати практичну користь": "Give practical value",
  "Деталі помилки": "Error details",
  "Для великого контент-виробництва та кількох команд.": "For large content production and multiple teams.",
  "Для кожної рубрики додайте назву, ціль, тон і приклад теми.": "For each rubric, add a name, goal, tone and example topic.",
  "Для кожної рубрики заповніть назву та опис від 10 символів": "For each rubric, fill in a name and description of at least 10 characters",
  "Для маркетингової команди, яка публікує регулярно.": "For a marketing team that publishes regularly.",
  "Для невеликої команди та стабільного контент-ритму.": "For a small team and steady content rhythm.",
  "До 300 публікацій на місяць": "Up to 300 publications per month",
  "До цього гайда можна повернутися з кнопки «Гайд» у верхньому хедері.": "You can return to this guide from the “Guide” button in the top header.",
  "Доброзичливий експертний": "Friendly expert",
  "Довести цінність на практиці": "Prove value in practice",
  "Додайте хоча б одну рубрику": "Add at least one rubric",
  "Додано матеріал бренду": "Brand material added",
  "Доповнити профіль →": "Complete profile →",
  "Дублювати": "Duplicate",
  "Експертний і зрозумілий": "Expert and clear",
  "Експертний пост": "Expert post",
  "Живий і впевнений": "Lively and confident",
  "Завантажуємо…": "Loading...",
  "Закріплено": "Pinned",
  "Закулісся бізнесу": "Behind the scenes",
  "Заплановано чернетку": "Draft scheduled",
  "Запустили новий напрям": "Launched a new direction",
  "Збільшений ліміт генерації зображень": "Increased image generation limit",
  "Згенерувати": "Generate",
  "Зняти заперечення": "Handle objections",
  "Зробити бренд людяним": "Make the brand human",
  "Ідеї — це бібліотека тем, з яких потім створюються чернетки. Генеруйте кілька варіантів, фільтруйте за рубриками, вибирайте найсильніші та перетворюйте їх на пости.": "Ideas are a library of topics that later become drafts. Generate several options, filter by rubrics, choose the strongest ones and turn them into posts.",
  "Календар →": "Calendar →",
  "Календар показує, коли вийде кожен матеріал. Готові чернетки можна призначити на локальну дату й час, перенести, повернути в готові або опублікувати.": "The calendar shows when each material will go out. Ready drafts can be assigned to a local date and time, moved, returned to ready or published.",
  "Кейс": "Case study",
  "Кількість": "Quantity",
  "Кількість входів": "Login count",
  "Кліше, перебільшення, небажані обіцянки": "Cliches, exaggerations, unwanted promises",
  "Ключові продукти/послуги": "Key products/services",
  "Кнопки «Запланувати» та «Опублікувати» зверху керують Telegram.": "The “Schedule” and “Publish” buttons above control Telegram.",
  "Кожен другий клієнт залишає відгук, але не кожна команда використовує цей сигнал.": "Every second client leaves feedback, but not every team uses this signal.",
  "Команда": "Team",
  "Компанія може мати кілька окремих workspace.": "A company can have several separate workspaces.",
  "Компанія, перший workspace і власник": "Company, first workspace and owner",
  "Кому підійде новий пакет": "Who the new package is for",
  "Конкретний і фактологічний": "Specific and factual",
  "Контент, бренд і публікації в одному просторі.": "Content, brand and publications in one workspace.",
  "Контент-план створено": "Content plan created",
  "Контролюйте AI-витрати, генерації та використання моделей.": "Track AI expenses, generations and model usage.",
  "Контент-календар і відкладена публікація": "Content calendar and scheduled publishing",
  "Користувач зареєструвався": "User registered",
  "Користувач увійшов у систему": "User signed in",
  "Користувачів оновлено": "Users updated",
  "Краще мати 5–8 зрозумілих рубрик, ніж один загальний список тем.": "It is better to have 5–8 clear rubrics than one general list of topics.",
  "Кут подачі": "Angle",
  "Логотип": "Logo",
  "Логотип збережено": "Logo saved",
  "Логотип ще не завантажено": "Logo has not been uploaded yet",
  "Масову дію виконано": "Bulk action completed",
  "Масштаб фото": "Photo scale",
  "Матеріал": "Material",
  "Матеріали без дати зібрані ліворуч, а заплановані пости видно в календарній сітці.": "Undated materials are collected on the left, and scheduled posts are shown in the calendar grid.",
  "Можна запланувати": "Can be scheduled",
  "На сторінці": "Per page",
  "Наповнений на": "Filled",
  "Напрям": "Direction",
  "Настрій / vibe": "Mood / vibe",
  "Навчає аудиторію корисному підходу або інструменту.": "Teaches the audience a useful approach or tool.",
  "Не вдалося виконати дію": "Could not complete the action",
  "Не вдалося зареєструватися": "Could not register",
  "Не вдалося підготувати аватар": "Could not prepare the avatar",
  "Не вдалося увійти": "Could not sign in",
  "Не можна видалити єдиний workspace компанії. Спочатку створіть інший workspace.": "You cannot delete the only workspace in a company. Create another workspace first.",
  "Не змішуйте матеріали різних компаній: так AI отримує чистіший контекст.": "Do not mix materials from different companies: AI gets cleaner context this way.",
  "Неактивний": "Inactive",
  "Немає візуалу": "No visual",
  "Немає даних.": "No data.",
  "Немає матеріалів для планування": "No materials to schedule",
  "Нова роль: admin, content_manager, editor, publisher, viewer": "New role: admin, content_manager, editor, publisher, viewer",
  "Нова чернетка": "New draft",
  "Новини компанії": "Company news",
  "Обрано workspace": "Workspace selected",
  "Обрати": "Choose",
  "Обрати всі ідеї на сторінці": "Select all ideas on the page",
  "Обрати всі пункти плану": "Select all plan items",
  "Обрати всі чернетки на сторінці": "Select all drafts on the page",
  "Огляд вашого контенту та найближчих дій.": "Overview of your content and next actions.",
  "Оновлення збережено": "Update saved",
  "Оновлення опубліковано": "Update published",
  "Оновлено візуальний стиль": "Visual style updated",
  "Оновлено матеріал бренду": "Brand material updated",
  "Оновлено оформлення workspace": "Workspace appearance updated",
  "Оновлено повідомлення в оновленнях": "Service update message updated",
  "Оновлено рубрику": "Rubric updated",
  "Оновлено workspace": "Workspace updated",
  "Опубліковано чернетку": "Draft published",
  "Освітній пост": "Educational post",
  "Оформлення збережено": "Appearance saved",
  "Пагінація": "Pagination",
  "Перед плануванням переконайтесь, що у чернетки є готовий візуал.": "Before scheduling, make sure the draft has a ready visual.",
  "Переконливий без тиску": "Persuasive without pressure",
  "Перевіряємо бота, канал і права адміністратора…": "Checking the bot, channel and administrator permissions...",
  "Перевіряйте, редагуйте та готуйте матеріали до публікації.": "Review, edit and prepare materials for publication.",
  "Перший план": "First plan",
  "Писати зрозуміло, конкретно та впевнено; підкріплювати тези прикладами.": "Write clearly, specifically and confidently; support claims with examples.",
  "Пишемо коротко, конкретно, без канцеляризмів.": "Write briefly, specifically and without bureaucratic wording.",
  "Підвищити довіру": "Increase trust",
  "Підвищити корисність бренду": "Increase brand usefulness",
  "Підключено Instagram": "Instagram connected",
  "Підключено Telegram": "Telegram connected",
  "Підтримувати контакт з аудиторією": "Keep in touch with the audience",
  "Після запуску генерації дочекайтесь індикатора готовності, не оновлюючи сторінку.": "After starting generation, wait for the readiness indicator without refreshing the page.",
  "Після налаштування контенту додайте людей, призначте ролі й контролюйте витрати. Так сервіс стає не просто генератором, а робочим SaaS-процесом для команди.": "After setting up content, add people, assign roles and track expenses. This turns the service from a generator into a working SaaS process for the team.",
  "Плануйте контент на тиждень або місяць.": "Plan content for a week or month.",
  "Плануйте публікації та керуйте графіком виходу контенту.": "Plan publications and manage the content schedule.",
  "Показує досвід клієнта та результат.": "Shows client experience and results.",
  "Показує задачу, рішення та вимірюваний результат.": "Shows the task, solution and measurable result.",
  "Показує процеси, людей та культуру.": "Shows processes, people and culture.",
  "Попередній перегляд": "Preview",
  "Поради клієнтам": "Client tips",
  "Посилання додано": "Link added",
  "Посилання скопійовано": "Link copied",
  "Посилити соціальний доказ": "Strengthen social proof",
  "Пост опубліковано": "Post published",
  "Пост опубліковано в Instagram": "Post published to Instagram",
  "Пояснити цінність функції": "Explain feature value",
  "Пояснює пропозицію через проблему та користь.": "Explains the offer through the problem and value.",
  "Пояснює професійну тему та демонструє експертизу.": "Explains a professional topic and demonstrates expertise.",
  "Практичний": "Practical",
  "Предметний": "Specific",
  "Презентація": "Presentation",
  "Призначити рубрику": "Assign rubric",
  "Приклад теми": "Example topic",
  "Приклади промптів": "Prompt examples",
  "Пріоритетна підтримка": "Priority support",
  "Продажний пост": "Sales post",
  "Продуктовий пост": "Product post",
  "Промпт для AI": "AI prompt",
  "Профіль збережено": "Profile saved",
  "Прямий і простий": "Direct and simple",
  "Публікувати може лише користувач із відповідними permissions.": "Only a user with the required permissions can publish.",
  "Рахунок відкрито в Telegram": "Invoice opened in Telegram",
  "Редагувати візуальний стиль": "Edit visual style",
  "Редагувати матеріал": "Edit material",
  "Редагувати рубрику": "Edit rubric",
  "Референс зображення": "Image reference",
  "Реферальну реєстрацію завершено": "Referral signup completed",
  "Розділ": "Section",
  "Розкриває функцію продукту через сценарій.": "Reveals a product feature through a scenario.",
  "Розповідає про зміни, події та команду.": "Tells about changes, events and the team.",
  "Розширені фільтри": "Advanced filters",
  "Рубрики допомагають планувати контент системно: експертні пости, кейси, FAQ, новини, продажні матеріали, поради. AI використовує рубрики, щоб не повторювати один і той самий формат.": "Rubrics help plan content systematically: expert posts, cases, FAQ, news, sales materials and tips. AI uses rubrics to avoid repeating the same format.",
  "Скільки триває запуск": "How long launch takes",
  "Сортування": "Sorting",
  "Статус оновлено": "Status updated",
  "Створено візуальний стиль": "Visual style created",
  "Створено запрошення у workspace": "Workspace invitation created",
  "Створено ідею": "Idea created",
  "Створено повідомлення в оновленнях": "Service update message created",
  "Створено рубрику": "Rubric created",
  "Створено чернетку": "Draft created",
  "Створено workspace": "Workspace created",
  "Створити візуальний стиль": "Create visual style",
  "Створити запит на продукт": "Create a product request",
  "Створити ідею": "Create idea",
  "Створюємо рахунок…": "Creating invoice...",
  "Створюйте контент системно, з командою, без хаосу.": "Create content systematically, with a team, without chaos.",
  "Серії постів і контент-плани на місяць": "Post series and monthly content plans",
  "Тема": "Topic",
  "Тон комунікації": "Communication tone",
  "У модалці планування перегляньте повний текст і картинку, щоб не помилитися з постом.": "In the scheduling modal, review the full text and image to avoid choosing the wrong post.",
  "У витратах видно AI-usage по днях, моделях і рубриках.": "Expenses show AI usage by day, model and rubric.",
  "У редакторі окремо перевіряйте заголовок для поста й заголовок на візуалі.": "In the editor, check the post title and visual title separately.",
  "У tone of voice додайте правила мови, довжини, звертання та приклади фраз.": "In tone of voice, add language rules, length rules, forms of address and phrase examples.",
  "Усе зі Start": "Everything in Start",
  "Усе з Growth": "Everything in Growth",
  "Установити фото": "Set photo",
  "Установити фото workspace": "Set workspace photo",
  "Фото": "Photo",
  "Ціль рубрики": "Rubric goal",
  "5 помилок під час впровадження": "5 mistakes during implementation",
  "Чернетка — це майбутній пост із заголовком, текстом, візуалом, статусом і соціальними варіантами. Її можна редагувати, погоджувати, повертати на правки й готувати до публікації.": "A draft is a future post with a title, text, visual, status and social variants. It can be edited, approved, returned for changes and prepared for publication.",
  "Щирий": "Sincere",
  "Що змінилося після впровадження": "What changed after implementation",
  "Що клієнт має знати перед стартом проєкту": "What a client should know before starting a project",
  "Як автоматизація економить час": "How automation saves time",
  "Як команда готує реліз": "How the team prepares a release",
  "Як ми скоротили час обробки звернень": "How we reduced request processing time",
  "Як підготувати команду до змін": "How to prepare a team for changes",
  "Якщо текст уже готовий, а картинка ще генерується, дочекайтесь статусу в таблиці.": "If the text is ready but the image is still generating, wait for the status in the table.",
  "Якщо у вас кілька брендів або клієнтів, створюйте для них різні workspace.": "If you have several brands or clients, create separate workspaces for them.",
  "Email підтверджено": "Email verified",
  "Instagram ще не налаштовано": "Instagram is not configured yet",
  "Owner workspace керує командою, ролями, брендом і небезпечними діями.": "The workspace owner manages the team, roles, brand and dangerous actions.",
  "Reset-посилання скопійовано": "Reset link copied",
  "Tone of voice збережено": "Tone of voice saved",
  "Viewer може тільки переглядати, Editor редагує, Publisher планує й публікує, Owner керує всім workspace.": "Viewer can only view, Editor edits, Publisher schedules and publishes, Owner manages the whole workspace.",
  "Workspace — це окремий простір для одного бренду, напряму або клієнта. У нього свої рубрики, чернетки, календар, Telegram-канал, команда, ролі, витрати й оформлення.": "A workspace is a separate space for one brand, direction or client. It has its own rubrics, drafts, calendar, Telegram channel, team, roles, expenses and appearance.",
  "🎨 Бренд": "🎨 Brand",
  "▦ Рубрики": "▦ Rubrics",
  "💡 Ідеї": "💡 Ideas",
  "✍ Чернетки": "✍ Drafts",
  "🗓 План": "🗓 Plan",
  "👥 Команда": "👥 Team",
});
const localizedTitles = {
  en: {
    home: ["Home", "Overview of your content and next actions."],
    ideas: ["Ideas", "Generate and save topics for future posts."],
    plan: ["Content plan", "Plan content for a week or month."],
    drafts: ["Drafts", "Review, edit and prepare posts for publishing."],
    calendar: ["Calendar", "Schedule publications and manage content timing."],
    brand: ["Brand", "Configure communication style, rubrics and visual rules."],
    analytics: ["Expenses", "Track AI spend, generations and model usage."],
    settings: ["Settings", "Manage workspace, users, channels and workflow mode."],
    platform: ["Platform", "Clients, companies, activity and service expenses."],
  },
};
const t = key => (translations[state.locale] || translations.uk)[key] || translations.uk[key] || key;
function translateText(value) {
  if (state.locale !== "en") return value;
  const text = String(value ?? "");
  const trimmed = text.trim();
  if (!trimmed) return text;
  let translated = uiTextEn[trimmed];
  if (!translated) {
    translated = trimmed
      .replace(/^Крок\s+(\d+)\s+з\s+(\d+)$/g, "Step $1 of $2")
      .replace(/^Обрано:\s*(\d+)$/g, "Selected: $1")
      .replace(/^Показано\s+(\d+)[–-](\d+)\s+з\s+(\d+)$/g, "Showing $1–$2 of $3")
      .replace(/^Поточний:\s*(.+)$/g, "Current: $1")
      .replace(/·\s*до\s*/g, "· until ")
      .replace(/^Власники:\s*(\d+)\s*·\s*Адміни:\s*(\d+)\s*·\s*Учасники:\s*(\d+)$/g, "Owners: $1 · Admins: $2 · Members: $3")
      .replace(/(\d+)\s*workspace\s*·\s*(\d+)\s*корист\.\s*·\s*(\d+)\s*публікацій/g, "$1 workspaces · $2 users · $3 publications")
      .replace(/(\d+)\s*корист\./g, "$1 users")
      .replace(/(\d+)\s*прав/g, "$1 permissions")
      .replace(/(\d+)\s*дн\./g, "$1 days")
      .replace(/(\d+)\s*публікацій\s*\/\s*місяць/g, "$1 publications / month")
      .replace(/(\d+)\s*публікацій/g, "$1 publications")
      .replace(/(\d+)\s*каналів/g, "$1 channels")
      .replace(/(\d+)\s*користувачів/g, "$1 users")
      .replace(/публікацій\s*\/\s*місяць/g, "publications / month")
      .replace(/AI-бюджет\s*\/\s*місяць/g, "generation limits / month")
      .replace(/чернетки\s*\/\s*план\s*\/\s*публікації/g, "drafts / schedule / publications")
      .replace(/Без workspace/g, "No workspace")
      .replace(/користувачів/g, "users")
      .replace(/користувач/g, "user")
      .replace(/каналів/g, "channels")
      .replace(/канал/g, "channel")
      .replace(/публікацій/g, "publications")
      .replace(/публікації/g, "publications")
      .replace(/чернетки/g, "drafts")
      .replace(/чернетка/g, "draft")
      .replace(/план/g, "plan")
      .replace(/Власник/g, "Owner")
      .replace(/Адміністратор/g, "Administrator")
      .replace(/Контент-менеджер/g, "Content manager")
      .replace(/Редактор/g, "Editor")
      .replace(/Публікатор/g, "Publisher")
      .replace(/Переглядач/g, "Viewer")
      .replace(/Учасник/g, "Member")
      .replace(/Власники/g, "Owners")
      .replace(/Адміни/g, "Admins")
      .replace(/Учасники/g, "Members")
      .replace(/створено/g, "created")
      .replace(/Скоро/g, "Soon");
  }
  if (translated === trimmed) return text;
  return text.replace(trimmed, translated);
}
const nativeConfirm = window.confirm.bind(window);
const nativePrompt = window.prompt.bind(window);
window.confirm = message => nativeConfirm(translateText(message));
window.prompt = (message, defaultValue = "") => nativePrompt(translateText(message), defaultValue);
function localizeDom(root = document.body) {
  if (state.locale !== "en" || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      if (["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE"].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
      if (parent.closest(".telegram-preview-text,.schedule-preview-card,.editor-preview-card,.service-update-card p")) return NodeFilter.FILTER_REJECT;
      const contentMain = parent.closest(".content-main,.asset-body");
      if (contentMain && (parent.matches("strong,small,p,h1,h2,h3,h4") || parent.closest("strong,small,p,h1,h2,h3,h4"))) return NodeFilter.FILTER_REJECT;
      return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach(node => {
    node.nodeValue = translateText(node.nodeValue);
  });
  root.querySelectorAll("[placeholder],[title],[aria-label],[data-tooltip]").forEach(node => {
    for (const attr of ["placeholder", "title", "aria-label", "data-tooltip"]) {
      if (node.hasAttribute(attr)) node.setAttribute(attr, translateText(node.getAttribute(attr)));
    }
  });
}
const statusLabels = {
  idea: "Ідея", suggested: "Ідея", draft: "Чернетка", review: "На перевірці",
  needs_changes: "Потрібні правки", ready: "Готово", scheduled: "Заплановано",
  published: "Опубліковано", queued_text: "Генерується", queued_image: "Візуал",
  text_batch: "Генерується", image_batch: "Візуал", failed: "Помилка",
  error: "Помилка", cancelled: "Скасовано",
};
const auditActionLabels = {
  user_logged_in: "Користувач увійшов у систему",
  user_registered: "Користувач зареєструвався",
  email_verified: "Email підтверджено",
  organization_created: "Створено workspace",
  organization_updated: "Оновлено workspace",
  workspace_selected: "Обрано workspace",
  "workspace.invitation_created": "Створено запрошення у workspace",
  telegram_connected: "Підключено Telegram",
  instagram_connected: "Підключено Instagram",
  instagram_disconnected: "Відключено Instagram",
  rubric_created: "Створено рубрику",
  "rubric.updated": "Оновлено рубрику",
  idea_created: "Створено ідею",
  draft_created: "Створено чернетку",
  draft_scheduled: "Заплановано чернетку",
  draft_published: "Опубліковано чернетку",
  referral_link_opened: "Відкрито реферальне посилання",
  referral_signup_completed: "Реферальну реєстрацію завершено",
  service_update_created: "Створено повідомлення в оновленнях",
  service_update_updated: "Оновлено повідомлення в оновленнях",
  visual_style_created: "Створено візуальний стиль",
  visual_style_updated: "Оновлено візуальний стиль",
  brand_material_created: "Додано матеріал бренду",
  brand_material_updated: "Оновлено матеріал бренду",
  workspace_appearance_updated: "Оновлено оформлення workspace",
};
const auditActionLabelsEn = {
  user_logged_in: "User logged in",
  user_registered: "User registered",
  email_verified: "Email verified",
  organization_created: "Workspace created",
  organization_updated: "Workspace updated",
  workspace_selected: "Workspace selected",
  "workspace.invitation_created": "Workspace invitation created",
  telegram_connected: "Telegram connected",
  instagram_connected: "Instagram connected",
  instagram_disconnected: "Instagram disconnected",
  rubric_created: "Rubric created",
  "rubric.updated": "Rubric updated",
  idea_created: "Idea created",
  draft_created: "Draft created",
  draft_scheduled: "Draft scheduled",
  draft_published: "Draft published",
  referral_link_opened: "Referral link opened",
  referral_signup_completed: "Referral signup completed",
  service_update_created: "Service update created",
  service_update_updated: "Service update updated",
  visual_style_created: "Visual style created",
  visual_style_updated: "Visual style updated",
  brand_material_created: "Brand material added",
  brand_material_updated: "Brand material updated",
  workspace_appearance_updated: "Workspace appearance updated",
};
function auditActionLabel(action) {
  const raw = String(action || "");
  if (state.locale === "en") {
    return auditActionLabelsEn[raw] || raw
      .replace(/[._-]+/g, " ")
      .replace(/\b\w/g, char => char.toUpperCase())
      .trim() || "System event";
  }
  return auditActionLabels[raw] || raw.replace(/[._-]+/g, " ");
}
const statusOrder = ["idea", "draft", "review", "needs_changes", "ready", "scheduled", "published"];
const statusActions = {
  draft: [["review","На перевірку"],["ready","Позначити готовим"]],
  review: [["needs_changes","Повернути на правки"],["ready","Погодити"]],
  needs_changes: [["draft","Повернути в чернетки"]],
  ready: [["draft","Повернути в чернетки"]],
};
const statusLabelsEn = {
  idea: "Idea", suggested: "Idea", draft: "Draft", review: "In review",
  needs_changes: "Needs changes", ready: "Ready", scheduled: "Scheduled",
  published: "Published", queued_text: "Generating", queued_image: "Visual",
  text_batch: "Generating", image_batch: "Visual", failed: "Error",
  error: "Error", cancelled: "Cancelled",
};
function statusLabel(status) {
  return state.locale === "en"
    ? (statusLabelsEn[status] || translateText(statusLabels[status] || status))
    : (statusLabels[status] || status);
}
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const money = value => `$${Number(value || 0).toFixed(2)}`;
const quotaLabel = (used, limit) => Number(limit || 0) <= 0 ? `${Number(used || 0).toLocaleString(state.locale === "en" ? "en-US" : "uk-UA")} / ∞` : `${Number(used || 0).toLocaleString(state.locale === "en" ? "en-US" : "uk-UA")} / ${Number(limit || 0).toLocaleString(state.locale === "en" ? "en-US" : "uk-UA")}`;
const quotaPercent = (used, limit) => Number(limit || 0) <= 0 ? 0 : Math.min(100, Math.round(Number(used || 0) / Number(limit || 1) * 100));
function workspaceAvatarUrl(workspace, kind = "avatar") {
  const id = Number(kind === "logo" ? (workspace?.brand_logo_asset_id || workspace?.settings?.brand_logo_asset_id) : (workspace?.workspace_avatar_asset_id || workspace?.settings?.workspace_avatar_asset_id)) || 0;
  if (!id) return "";
  const version = encodeURIComponent(`${id}:${workspace?.updated_at || workspace?.settings?.updated_at || Date.now()}`);
  if (workspace?.id) return apiUrl(`api/workspaces/${workspace.id}/appearance/avatar?v=${version}`);
  return apiUrl(`api/references/${id}/image?v=${version}`);
}
function workspaceAvatarMarkup(workspace, className = "") {
  const src = workspaceAvatarUrl(workspace);
  return src ? `<img class="${esc(className)}" src="${src}" alt="">` : esc(initials(workspace?.name || state.company?.name || "CS"));
}
const roleLabelsUk = {
  platform_admin:"Platform Admin",owner:"Власник",admin:"Адміністратор",
  content_manager:"Контент-менеджер",editor:"Редактор",
  publisher:"Публікатор",viewer:"Переглядач",member:"Учасник",
};
const roleLabelsEn = {
  platform_admin:"Platform Admin",owner:"Owner",admin:"Administrator",
  content_manager:"Content manager",editor:"Editor",
  publisher:"Publisher",viewer:"Viewer",member:"Member",
};
const roleLabel = role => (state.locale === "en" ? roleLabelsEn : roleLabelsUk)[role] || role || (state.locale === "en" ? "Member" : "Учасник");
function decodeHtmlMarkup(value) {
  let result = String(value || "");
  const textarea = document.createElement("textarea");
  for (let index = 0; index < 3; index += 1) {
    textarea.innerHTML = result;
    const decoded = textarea.value;
    if (decoded === result) break;
    result = decoded;
  }
  return result;
}
function parseDateValue(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return new Date(`${text}T12:00:00`);
  return new Date(text.replace(" ", "T"));
}
const formatDate = (value, fallback = "Ще не заплановано") => {
  if (!value) return fallback;
  const date = parseDateValue(value);
  return Number.isNaN(date.getTime())
    ? translateText(fallback)
    : date.toLocaleDateString(state.locale === "en" ? "en-US" : "uk-UA", {day:"2-digit",month:"short"});
};
const localDateKey = value => {
  const date = parseDateValue(value);
  if (!date) return "";
  if (Number.isNaN(date.getTime())) return "";
  const pad = number => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
};
const localDateTimeValue = value => {
  if (!value) return "";
  const date = parseDateValue(value);
  if (!date) return "";
  if (Number.isNaN(date.getTime())) return "";
  const pad = number => String(number).padStart(2, "0");
  return `${localDateKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};
const activeGenerationStatuses = new Set(["queued_text","text_batch","queued_image","image_batch"]);
const blockedPreviewTags = new Set(["SCRIPT","STYLE","IFRAME","OBJECT","EMBED","FORM","INPUT","BUTTON","SVG"]);
const plain = value => {
  const documentValue = new DOMParser().parseFromString(decodeHtmlMarkup(value), "text/html");
  documentValue.body.querySelectorAll([...blockedPreviewTags].join(",")).forEach(node=>node.remove());
  return (documentValue.body.textContent || "").replace(/\s+/g, " ").trim();
};
const allowedPreviewTags = new Set(["B","STRONG","I","EM","U","S","BR","CODE","PRE","A","BLOCKQUOTE"]);
function safeHtml(value) {
  const source = new DOMParser().parseFromString(decodeHtmlMarkup(value), "text/html");
  const clean = document.implementation.createHTMLDocument("");
  const copy = node => {
    if (node.nodeType === Node.TEXT_NODE) return clean.createTextNode(node.textContent || "");
    if (node.nodeType !== Node.ELEMENT_NODE) return clean.createTextNode("");
    if (blockedPreviewTags.has(node.tagName)) return clean.createTextNode("");
    if (!allowedPreviewTags.has(node.tagName)) {
      const fragment = clean.createDocumentFragment();
      [...node.childNodes].forEach(child => fragment.append(copy(child)));
      return fragment;
    }
    const element = clean.createElement(node.tagName.toLowerCase());
    if (node.tagName === "A") {
      const href = node.getAttribute("href") || "";
      if (/^(https?:|mailto:)/i.test(href)) {
        element.setAttribute("href", href);
        element.setAttribute("target", "_blank");
        element.setAttribute("rel", "noopener noreferrer");
      }
    }
    [...node.childNodes].forEach(child => element.append(copy(child)));
    return element;
  };
  const output = clean.createElement("div");
  [...source.body.childNodes].forEach(node => output.append(copy(node)));
  return output.innerHTML;
}
const can = permission => Boolean(state.me?.is_super_admin || state.me?.permissions?.includes(permission));
function brandCompletion() {
  const settings = state.company?.settings || {};
  const rubrics = state.data?.rubrics || [];
  const templates = state.data?.templates || [];
  const references = state.data?.references || [];
  const hasValue = key => String(settings[key] || "").trim().length > 0;
  const customVisuals = templates.filter(item => item.custom).length;
  const activeRubrics = rubrics.filter(item => item.active !== 0).length;
  const materialCount = references.length;
  const sections = [
    {
      key: "profile",
      label: "Профіль компанії",
      labelEn: "Company profile",
      weight: 30,
      score:
        (hasValue("company_description") ? 12 : 0) +
        (hasValue("key_services") ? 8 : 0) +
        (hasValue("website_url") ? 5 : 0) +
        (hasValue("brand_primary_color") ? 5 : 0),
      hints: ["Опис компанії", "Ключові продукти/послуги", "Сайт", "Основний колір"],
      hintsEn: ["Company description", "Key products/services", "Website", "Primary color"],
    },
    {
      key: "tone",
      label: "Tone of voice",
      labelEn: "Tone of voice",
      weight: 20,
      score: (hasValue("tone_of_voice") ? 16 : 0) + (hasValue("forbidden_phrases") ? 4 : 0),
      hints: ["Правила мови", "Заборонені слова або кліше"],
      hintsEn: ["Language rules", "Forbidden words or cliches"],
    },
    {
      key: "rubrics",
      label: "Рубрики",
      labelEn: "Rubrics",
      weight: 20,
      score: activeRubrics >= 3 ? 20 : activeRubrics >= 1 ? 12 : 0,
      hints: ["1 активна рубрика = +12%", "3+ активні рубрики = +20%"],
      hintsEn: ["1 active rubric = +12%", "3+ active rubrics = +20%"],
    },
    {
      key: "visuals",
      label: "Візуальні стилі",
      labelEn: "Visual styles",
      weight: 15,
      score: customVisuals >= 1 ? 15 : 0,
      hints: ["Створіть власний стиль для генерації зображень"],
      hintsEn: ["Create a custom style for image generation"],
    },
    {
      key: "assets",
      label: "Матеріали бренду",
      labelEn: "Brand materials",
      weight: 10,
      score: materialCount >= 2 ? 10 : materialCount >= 1 ? 6 : 0,
      hints: ["Логотип, брендбук, фото, презентація або посилання"],
      hintsEn: ["Logo, brand book, photo, presentation or link"],
    },
    {
      key: "appearance",
      label: "Оформлення",
      labelEn: "Appearance",
      weight: 5,
      score:
        (Number(settings.workspace_avatar_asset_id) ? 2 : 0) +
        (Number(settings.brand_logo_asset_id) ? 2 : 0) +
        (hasValue("brand_primary_color") && hasValue("brand_secondary_color") ? 1 : 0),
      hints: ["Аватар workspace", "Логотип компанії", "Основний і додатковий колір"],
      hintsEn: ["Workspace avatar", "Company logo", "Primary and secondary color"],
    },
  ].map(section => ({...section, score: Math.min(section.weight, section.score)}));
  const total = Math.min(100, sections.reduce((sum, section) => sum + section.score, 0));
  return {total, sections};
}
function renderBrandCompletionDetails({compact = false} = {}) {
  const completion = brandCompletion();
  return `<div class="brand-completion ${compact ? "compact" : ""}">
    <div class="row between"><div><div class="eyebrow">Бренд-профіль</div><h3>${t("brandFilled")} ${completion.total}%</h3></div><strong>${completion.total}/100</strong></div>
    <div class="brand-completion-bar"><span style="width:${completion.total}%"></span></div>
    <div class="brand-score-grid">${completion.sections.map(section => `<button type="button" data-brand-score-tab="${esc(section.key)}" class="${state.brandTab === section.key ? "active" : ""}"><span>${esc(state.locale === "en" ? section.labelEn : section.label)}</span><strong>${section.score}/${section.weight}%</strong><small>${esc((state.locale === "en" ? section.hintsEn : section.hints).join(" · "))}</small></button>`).join("")}</div>
  </div>`;
}
function updateBrandTabLabels() {
  const completion = brandCompletion();
  for (const section of completion.sections) {
    const button = document.querySelector(`[data-brand-tab="${section.key}"]`);
    if (!button) continue;
    button.innerHTML = `${esc(state.locale === "en" ? section.labelEn : section.label)} <span class="tab-score">${section.weight}%</span>`;
    button.title = `${section.score}/${section.weight}%`;
  }
}
function colorControl({id, label, value, help = ""}) {
  const safeValue = /^#[0-9A-Fa-f]{6}$/.test(value || "") ? value : "#6366f1";
  return `<label>${esc(label)}<div class="color-control color-control-pill">
    <span class="color-dot" id="${esc(id)}Dot" style="--color:${esc(safeValue)}"></span>
    <input id="${esc(id)}" type="color" value="${esc(safeValue)}">
    <input id="${esc(id)}Hex" value="${esc(safeValue)}" maxlength="7" aria-label="${esc(label)} hex">
  </div>${help ? `<small class="field-help">${esc(help)}</small>` : ""}</label>`;
}
function bindColorControl(id, onChange = () => {}) {
  const picker = document.querySelector(`#${id}`);
  const hex = document.querySelector(`#${id}Hex`);
  const dot = document.querySelector(`#${id}Dot`);
  if (!picker || !hex) return;
  const sync = value => {
    const normalized = /^#[0-9A-Fa-f]{6}$/.test(value || "") ? value.toLowerCase() : picker.value.toLowerCase();
    picker.value = normalized;
    hex.value = normalized.toUpperCase();
    if (dot) dot.style.setProperty("--color", normalized);
    onChange(normalized);
  };
  picker.oninput = () => sync(picker.value);
  hex.oninput = () => sync(hex.value);
  sync(picker.value);
}
function sortHeader(key, label, listKey, rerender) {
  const query = new URLSearchParams(location.search);
  const current = query.get("sort") || "";
  const ascendingDefaults = new Set(["display_name", "name"]);
  const direction = query.get("direction") || (ascendingDefaults.has(key) ? "asc" : "desc");
  const active = current === key || (!current && (key === "created_at" || key === "name" || key === "display_name"));
  const nextDirection = active && direction !== "asc" ? "asc" : "desc";
  queueMicrotask(() => {
    document.querySelectorAll(`[data-sort-list="${listKey}"][data-sort-key="${key}"]`).forEach(button => {
      button.onclick = () => updateListQuery(
        {page:"1",sort:key === "created_at" ? null : key,direction:nextDirection === "desc" ? null : nextDirection},
        rerender,
        listKey,
      );
    });
  });
  return `<button type="button" class="sort-header ${active ? "active" : ""}" data-sort-list="${esc(listKey)}" data-sort-key="${esc(key)}">${esc(label)}<span>${active ? (direction === "asc" ? "↑" : "↓") : "↕"}</span></button>`;
}
const pageParams = extra => {
  const current = new URLSearchParams(location.search);
  const query = new URLSearchParams({
    page: current.get("page") || "1",
    per_page: current.get("per_page") || "25",
  });
  if (current.get("search")) query.set("search", current.get("search"));
  for (const [key, value] of Object.entries(extra || {})) {
    if (value && value !== "all") query.set(key, value);
  }
  return query;
};
function pagedData(key, endpoint, extra, rerender) {
  const query = pageParams(extra);
  const signature = `${endpoint}?${query}`;
  const current = state.lists[key];
  if (current?.signature === signature) return current.error ? {items:[], page:1, per_page:Number(query.get("per_page")||25), total:0, total_pages:0, error:current.error} : current.data;
  if (current?.loading === signature) return null;
  state.lists[key] = {loading: signature};
  api(signature).then(data => {
    state.lists[key] = {signature, data};
    rerender();
  }).catch(error => {
    state.lists[key] = {signature, error};
    toast(error.message, true);
    rerender();
  });
  return null;
}
function updateListQuery(values, rerender, key) {
  const query = new URLSearchParams(location.search);
  for (const [name, value] of Object.entries(values)) {
    if (value === null || value === "" || value === "1" && name === "page") query.delete(name);
    else query.set(name, value);
  }
  history.pushState({view:state.view}, "", `${location.pathname}${query.size ? `?${query}` : ""}`);
  delete state.lists[key];
  rerender();
}
function pagination(data, key, rerender) {
  if (!data || !data.total_pages) return "";
  const start = data.total ? (data.page - 1) * data.per_page + 1 : 0;
  const end = Math.min(data.total, data.page * data.per_page);
  const pages = [];
  for (let page = Math.max(1, data.page - 2); page <= Math.min(data.total_pages, data.page + 2); page += 1) pages.push(page);
  queueMicrotask(() => {
    document.querySelectorAll(`[data-pagination="${key}"] [data-page]`).forEach(button => button.onclick = () => updateListQuery({page:button.dataset.page}, rerender, key));
    document.querySelector(`[data-pagination="${key}"] select`)?.addEventListener("change", event => updateListQuery({page:"1",per_page:event.target.value}, rerender, key));
  });
  const label = state.locale === "en" ? `Showing ${start}–${end} of ${data.total}` : `Показано ${start}–${end} з ${data.total}`;
  return `<nav class="pagination" data-pagination="${key}" aria-label="${state.locale === "en" ? "Pagination" : "Пагінація"}"><span>${label}</span><div><button data-page="${Math.max(1,data.page-1)}" ${data.page<=1?"disabled":""}>${state.locale === "en" ? "Back" : "Назад"}</button>${pages.map(page=>`<button data-page="${page}" class="${page===data.page?"active":""}">${page}</button>`).join("")}<button data-page="${Math.min(data.total_pages,data.page+1)}" ${data.page>=data.total_pages?"disabled":""}>${state.locale === "en" ? "Next" : "Вперед"}</button></div><label>${state.locale === "en" ? "Per page" : "На сторінці"}<select>${[10,25,50,100].map(size=>`<option value="${size}" ${size===data.per_page?"selected":""}>${size}</option>`).join("")}</select></label></nav>`;
}
function selected(key) {
  if (!state.selected[key]) state.selected[key] = new Set();
  return state.selected[key];
}
function selectionCheckbox(key, id) {
  return `<input class="row-check" type="checkbox" aria-label="Обрати" data-select-key="${key}" data-select-id="${esc(id)}" ${selected(key).has(String(id))?"checked":""}>`;
}
function bindSelection(key, target, renderBar) {
  target.querySelectorAll(`[data-select-key="${key}"]`).forEach(input => input.onchange = () => {
    if (input.checked) selected(key).add(String(input.dataset.selectId));
    else selected(key).delete(String(input.dataset.selectId));
    renderBar();
  });
  target.querySelectorAll(`[data-select-all="${key}"]`).forEach(input => input.onchange = () => {
    target.querySelectorAll(`[data-select-key="${key}"]`).forEach(row => {
      row.checked = input.checked;
      if (row.checked) selected(key).add(String(row.dataset.selectId));
      else selected(key).delete(String(row.dataset.selectId));
    });
    renderBar();
  });
}
function bulkBar(key, actions) {
  const count = selected(key).size;
  if (!count) return "";
  return `<div class="bulk-bar"><strong>Обрано: ${count}</strong>${actions.map(([action,label,kind=""])=>`<button class="${kind}" data-bulk-action="${action}">${label}</button>`).join("")}<button data-clear-selection>Скасувати вибір</button></div>`;
}
const icon = name => ({
  ideas: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 22h4"/><path d="M8.2 15.4A7 7 0 1 1 15.8 15.4C14.7 16.2 14 17 14 18h-4c0-1-.7-1.8-1.8-2.6Z"/></svg>',
  plan: '<svg viewBox="0 0 24 24"><path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/></svg>',
  drafts: '<svg viewBox="0 0 24 24"><path d="M4 5h6v14H4zM14 5h6v8h-6zM14 17h6v2h-6z"/></svg>',
  calendar: '<svg viewBox="0 0 24 24"><path d="M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2ZM3 9h18M8 2v4M16 2v4"/></svg>',
}[name] || "");
const socialLogo = platform => {
  const logos = {
    telegram: '<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="14" fill="#26A5E4"/><path fill="#fff" d="M20.9 8.2 6.8 13.6c-1 .4-1 1.4-.2 1.7l3.6 1.1 1.4 4.4c.2.7.7.8 1.2.3l2-2 3.7 2.7c.7.4 1.2.2 1.4-.7l2.5-11.7c.3-1-.4-1.5-1.5-1.2Z"/><path fill="#C8DAEA" d="m10.8 16.1 8.3-5.2c.4-.2.7-.1.4.2l-6.7 6.1-.3 3.1-1.7-4.2Z"/></svg>',
    instagram: '<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><defs><radialGradient id="igA" cx="30%" cy="105%" r="120%"><stop offset="0" stop-color="#FEDA75"/><stop offset=".26" stop-color="#FA7E1E"/><stop offset=".52" stop-color="#D62976"/><stop offset=".78" stop-color="#962FBF"/><stop offset="1" stop-color="#4F5BD5"/></radialGradient></defs><rect width="28" height="28" rx="8" fill="url(#igA)"/><rect x="7" y="7" width="14" height="14" rx="4.4" fill="none" stroke="#fff" stroke-width="2"/><circle cx="14" cy="14" r="3.6" fill="none" stroke="#fff" stroke-width="2"/><circle cx="18.8" cy="9.2" r="1.2" fill="#fff"/></svg>',
    facebook: '<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><rect width="28" height="28" rx="7" fill="#1877F2"/><path fill="#fff" d="M16.5 9.2H19V5.6c-.4-.1-1.8-.2-3.4-.2-3.3 0-5.6 2.1-5.6 5.9V14H6.5v4h3.5v9h4.3v-9h3.4l.5-4h-3.9v-2.3c0-1.2.3-2.5 2.2-2.5Z"/></svg>',
    whatsapp: '<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="14" fill="#25D366"/><path fill="#fff" d="M8.1 21.2 9 17.9a7.3 7.3 0 1 1 2.9 2.8l-3.8.5Zm4-3.1.3.2a5.7 5.7 0 1 0-1.8-1.7l.2.3-.5 1.9 1.8-.7Z"/><path fill="#fff" d="M11.2 9.8c.2-.4.4-.5.8-.5h.6c.2 0 .5.1.6.5l.8 1.8c.1.3.1.5-.1.7l-.5.7c-.2.2-.2.4 0 .7.4.8 1.3 1.8 2.4 2.3.3.2.5.2.7-.1l.7-.8c.2-.2.5-.3.8-.2l1.8.9c.4.2.5.4.5.7 0 1-.8 2-1.8 2.1-1.5.1-3.4-.6-5.1-2.3-1.6-1.6-2.6-3.6-2.5-5.1 0-.6.3-1.1.7-1.4Z"/></svg>',
    linkedin: '<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><rect width="28" height="28" rx="6" fill="#0A66C2"/><path fill="#fff" d="M7.1 11.2h4V22h-4V11.2Zm2-5.2a2.1 2.1 0 1 1 0 4.2 2.1 2.1 0 0 1 0-4.2Zm4.3 5.2h3.8v1.5h.1c.5-.9 1.8-1.9 3.7-1.9 4 0 4.7 2.6 4.7 6V22h-4v-4.6c0-1.1 0-2.5-1.5-2.5s-1.8 1.2-1.8 2.5V22h-4V11.2Z"/></svg>',
    tiktok: '<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><rect width="28" height="28" rx="7" fill="#050505"/><path fill="#25F4EE" d="M13 9.2v8.2a3.9 3.9 0 1 1-3.4-3.9v3.1a1 1 0 1 0 .7.9V5.7h3.1c.3 1.7 1.4 2.9 3.1 3.5v3.1A7.2 7.2 0 0 1 13 9.2Z"/><path fill="#FE2C55" d="M15 5.7c.4 1.7 1.5 2.8 3.3 3.3v3.2a7 7 0 0 1-3.3-1.3v6.3a4.3 4.3 0 0 1-6.5 3.8 4.2 4.2 0 0 0 5.1-4.1V8.3c.6.7 1.4 1.2 2.4 1.5-.5-.7-.9-1.4-1-2.4V5.7Z"/><path fill="#fff" d="M14 8.1v8.8a4.2 4.2 0 1 1-3.4-4.1v2.8a1.4 1.4 0 1 0 1 1.3V5.7H14c.3 1.7 1.4 3.2 3.3 3.8v2.8A7.1 7.1 0 0 1 14 11v-2.9Z"/></svg>',
  };
  return `<span class="social-logo ${esc(platform)}">${logos[platform] || logos.telegram}</span>`;
};

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  headers["X-Requested-With"] = "VoicerHubAdmin";
  const response = await fetch(apiUrl(path), {...options, headers});
  if (response.status === 401) {
    location.href = `${basePath}/`;
    throw new Error("Потрібно увійти");
  }
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "object" && detail
      ? detail.detail || detail.message || "Помилка запиту"
      : detail || data || "Помилка запиту";
    const error = new Error(message);
    if (typeof detail === "object" && detail) {
      error.reason = detail.reason;
      error.billingSection = detail.billing_section;
    }
    throw error;
  }
  return data;
}

function toast(message, error = false) {
  const node = document.querySelector("#toast");
  node.textContent = translateText(message);
  node.classList.toggle("error", error);
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.hidden = true, 3600);
}
async function loading(button, task, label = "Зачекайте…") {
  const old = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span>${translateText(label)}`;
  try { return await task(); }
  catch (error) { toast(error.message, true); throw error; }
  finally { button.disabled = false; button.innerHTML = old; }
}
async function withAiProgress(task, {
  title = "Ваші ідеї генеруються",
  text = "Аналізуємо бренд, рубрики та формуємо нові теми.",
} = {}) {
  const overlay = document.querySelector("#aiProgressOverlay");
  document.querySelector("#aiProgressTitle").textContent = title;
  document.querySelector("#aiProgressText").textContent = text;
  overlay.hidden = false;
  try { return await task(); }
  finally { overlay.hidden = true; }
}
function initials(name) {
  return String(name || "CS").split(/\s+/).slice(0,2).map(x => x[0]).join("").toUpperCase();
}
function pill(status) {
  const normalized = status === "suggested" ? "idea" : status;
  return `<span class="pill ${esc(normalized)}">${esc(statusLabel(status))}</span>`;
}
function empty(title, text, action = "") {
  return `<div class="empty-state"><div style="font-size:28px;color:#818cf8">✦</div><h3>${esc(translateText(title))}</h3><p class="muted">${esc(translateText(text))}</p>${action}</div>`;
}
function notificationStorageKey() {
  return `content-studio:read-notifications:${state.me?.id || "guest"}:${state.me?.organization_id || "none"}`;
}
function readNotificationKeys() {
  try {
    return new Set(JSON.parse(localStorage.getItem(notificationStorageKey()) || "[]"));
  } catch {
    return new Set();
  }
}
function saveReadNotificationKeys(keys) {
  localStorage.setItem(notificationStorageKey(), JSON.stringify([...keys]));
}
function notificationItems({includeRead = false} = {}) {
  const failed = (state.data?.jobs || []).filter(job => job.status === "failed");
  const items = failed.map(job => ({
    key: `failed-job:${job.id}`,
    type: "error",
    jobId: job.id,
    title: "Не вдалося згенерувати матеріал",
    text: job.error || job.error_message || "Генерація зупинилася без детального опису.",
    action: `${job.topic ? `Тема: ${plain(job.topic).slice(0, 140)}. ` : ""}Можна повторити генерацію або змінити рубрику/дані чернетки.`,
  }));
  items.push(...(state.completedJobs || []).map(job => ({
    key: `ready-job:${job.id}`,
    type: "success",
    jobId: null,
    title: "Чернетку створено",
    text: job.title || job.topic || `Завдання #${job.id}`,
    action: job.draft_id ? "Натисніть у чернетках на позначку «Щойно створено», щоб швидко знайти матеріал." : "Матеріал готовий.",
  })));
  items.push(...(state.data?.social_publish_jobs || []).filter(job => ["failed","published"].includes(job.status)).slice(0,12).map(job => ({
    key: `social-job:${job.id}:${job.status}`,
    type: job.status === "failed" ? "error" : "success",
    jobId: null,
    title: job.status === "failed" ? "Instagram не опублікував пост" : "Instagram-публікацію створено",
    text: job.status === "failed" ? (job.error || "Meta повернула помилку без деталей.") : (job.permalink || `Чернетка #${job.draft_id}`),
    action: job.status === "failed" ? "Відкрийте чернетку, перевірте зображення та підключення Instagram." : "Публікація доступна у підключеному Instagram акаунті.",
  })));
  const expiry = state.company?.quota_state?.days_left ?? null;
  if (state.company?.plan_code === "trial" && expiry !== null && expiry <= 7) {
    items.push({
      key: `trial:${state.company.trial_ends_at || state.company.plan_expires_at}`,
      type: expiry <= 0 ? "error" : "warning",
      title: expiry <= 0 ? "Trial завершився" : "Trial скоро завершиться",
      text: expiry <= 0 ? "Оберіть тариф для продовження роботи." : `Залишилося ${expiry} дн.`,
      action: "Перевірте тариф у налаштуваннях workspace.",
    });
  }
  for (const [kind, title] of [["text","Ліміт текстових генерацій майже використано"],["image","Ліміт зображень майже використано"]]) {
    const quota = state.company?.quota_state?.[kind] || {};
    const used = Number(quota.used || 0);
    const limit = Number(quota.limit || 0);
    if (!limit || used / limit < .7) continue;
    items.push({
      key: `${kind}-quota:${new Date().toISOString().slice(0, 7)}:${limit}`,
      type: used >= limit ? "error" : "warning",
      title,
      text: `${quotaLabel(used, limit)} (${Math.round(used / limit * 100)}%).`,
      action: "Відкрийте розділ «Тарифи», якщо потрібно більше генерацій.",
    });
  }
  const readKeys = readNotificationKeys();
  return items
    .map(item => ({...item, read: readKeys.has(item.key)}))
    .filter(item => includeRead || !item.read);
}
function updateNotificationBadge() {
  const notificationCount = notificationItems().length;
  const notificationBadge = document.querySelector("#notificationCount");
  notificationBadge.textContent = notificationCount;
  notificationBadge.hidden = notificationCount === 0;
  document.querySelector("#notificationsButton").classList.toggle("has-events", notificationCount > 0);
}
function serviceUpdatesStorageKey() {
  return `content-studio:service-updates:last-seen:${state.me?.id || "guest"}`;
}
function serviceUpdateLabel(value) {
  const labelsUk = {
    release: "Нова функція",
    fix: "Виправлення",
    maintenance: "Технічні роботи",
    announcement: "Оголошення",
  };
  const labelsEn = {
    release: "New feature",
    fix: "Fix",
    maintenance: "Maintenance",
    announcement: "Announcement",
  };
  return (state.locale === "en" ? labelsEn : labelsUk)[value] || value || (state.locale === "en" ? "Update" : "Оновлення");
}
function serviceUpdateDate(value) {
  return value
    ? new Date(String(value).replace(" ", "T") + "Z").toLocaleDateString(state.locale === "en" ? "en-US" : "uk-UA", {day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"})
    : "";
}
function updateServiceUpdatesBadge() {
  const badge = document.querySelector("#serviceUpdatesCount");
  const items = state.serviceUpdates?.items || [];
  const lastSeen = Number(localStorage.getItem(serviceUpdatesStorageKey()) || 0);
  const unread = items.filter(item => Number(item.id) > lastSeen).length;
  badge.textContent = unread;
  badge.hidden = unread === 0;
  document.querySelector("#serviceUpdatesButton").classList.toggle("has-events", unread > 0);
}
function appPathname() {
  const normalizedBase = basePath.replace(/\/+$/, "");
  return normalizedBase && location.pathname.startsWith(normalizedBase)
    ? location.pathname.slice(normalizedBase.length) || "/"
    : location.pathname;
}
function routeFromLocation() {
  const parts = appPathname().split("/").filter(Boolean);
  if (parts[0] === "platform") {
    const requestedSection = parts[1] === "organizations" ? "companies" : parts[1];
    const sections = new Set(["clients","companies","users","referrals","activity","expenses"]);
    state.platformSection = sections.has(requestedSection) ? requestedSection : "overview";
    state.platformClientId = state.platformSection === "clients" && Number(parts[2])
      ? Number(parts[2])
      : null;
    state.platformCompanyId = state.platformSection === "companies" && Number(parts[2])
      ? Number(parts[2])
      : null;
    return {view:"platform",draftId:null};
  }
  const workspaceIndex = parts.indexOf("workspace");
  if (
    workspaceIndex >= 0
    && parts[workspaceIndex + 2] === "drafts"
    && Number(parts[workspaceIndex + 3])
  ) {
    return {
      view: history.state?.fromView || "drafts",
      draftId: Number(parts[workspaceIndex + 3]),
    };
  }
  return {view: routeViews[parts[0]] || "home", draftId: null};
}
function queryForView(view) {
  const query = new URLSearchParams();
  const current = new URLSearchParams(location.search);
  const pathParts = appPathname().split("/").filter(Boolean);
  const sameList = view === "platform"
    ? pathParts[0] === "platform" && (pathParts[1] || "overview") === state.platformSection
    : pathParts[0] === viewRoutes[view];
  if (sameList) {
    for (const key of ["page","per_page","search"]) {
      const value = current.get(key);
      if (value) query.set(key, value);
    }
  }
  if (view === "ideas" && state.ideaFilter !== "all") query.set("rubric", state.ideaFilter);
  if (view === "drafts" && state.draftFilter !== "all") query.set("status", state.draftFilter);
  if (view === "calendar") {
    query.set("view", "month");
    query.set(
      "date",
      `${state.calendarDate.getFullYear()}-${String(state.calendarDate.getMonth() + 1).padStart(2, "0")}`,
    );
  }
  if (view === "brand" && state.brandTab !== "profile") query.set("tab", state.brandTab);
  if (view === "settings" && state.settingsTab !== "workspace") query.set("tab", state.settingsTab);
  if (view === "platform" && state.platformSection === "clients" && !state.platformClientId) {
    for (const key of ["source","period","active","workspace"]) {
      const value = current.get(key);
      if (value) query.set(key, value);
    }
  }
  return query.toString();
}
function urlForView(view) {
  const query = queryForView(view);
  let route = viewRoutes[view];
  if (view === "platform") {
    route = state.platformSection === "overview"
      ? "platform"
      : `platform/${state.platformSection}${
        state.platformClientId
          ? `/${state.platformClientId}`
          : state.platformCompanyId
          ? `/${state.platformCompanyId}`
          : ""
      }`;
  }
  return `${basePath}/${route}${query ? `?${query}` : ""}`;
}
function readRouteState() {
  const query = new URLSearchParams(location.search);
  state.ideaFilter = query.get("rubric") || "all";
  state.draftFilter = query.get("status") || "all";
  if (/^\d{4}-\d{2}$/.test(query.get("date") || "")) {
    const [year, month] = query.get("date").split("-").map(Number);
    state.calendarDate = new Date(year, month - 1, 1);
  }
  state.brandTab = query.get("tab") || "profile";
  state.settingsTab = query.get("tab") || "workspace";
  return routeFromLocation();
}
function updateViewUrl(view, {replace = false} = {}) {
  history[replace ? "replaceState" : "pushState"]({view}, "", urlForView(view));
}
function setView(view, {push = true, replace = false} = {}) {
  if (!viewRoutes[view]) view = "home";
  if (view === "platform" && !state.me?.is_super_admin) view = "home";
  state.view = view;
  if (push) updateViewUrl(view, {replace});
  document.querySelectorAll(".view").forEach(node => node.classList.toggle("active", node.id === `${view}View`));
  document.querySelectorAll(".nav-item[data-view]").forEach(node => node.classList.toggle("active", node.dataset.view === view));
  const titleSet = localizedTitles[state.locale] || titles;
  const [title, subtitle] = titleSet[view] || titles[view];
  document.querySelector("#pageTitle").textContent = view === "drafts" && state.company?.settings?.workspace_mode === "kanban" ? (state.locale === "en" ? "Board" : "Дошка") : title;
  document.querySelector("#pageSubtitle").textContent = subtitle;
  applyLocaleChrome();
  document.body.classList.remove("menu-open");
  renderCurrent();
}
function applyLocaleChrome() {
  document.documentElement.lang = state.locale === "en" ? "en" : "uk";
  document.querySelector("#languageFlag").textContent = t("localeFlag");
  document.querySelector("#languageCode").textContent = t("localeCode");
  document.querySelector("#openGuide").lastChild.textContent = t("guide");
  document.querySelector("#serviceUpdatesButton").childNodes[1].textContent = t("updates");
  const searchSmall = document.querySelector("#searchButton small")?.outerHTML || "";
  document.querySelector("#searchButton").innerHTML = `<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg>${t("search")} ${searchSmall}`;
  document.querySelector("#createButton").textContent = t("create");
  localizeDom(document.querySelector(".sidebar"));
}
async function applyLocationRoute({openDraft = true} = {}) {
  const route = readRouteState();
  setView(route.view, {push: false});
  document.querySelectorAll("[data-brand-tab]").forEach(node => node.classList.toggle("active", node.dataset.brandTab === state.brandTab));
  document.querySelectorAll("[data-settings]").forEach(node => node.classList.toggle("active", node.dataset.settings === state.settingsTab));
  if (route.draftId && openDraft && state.data) {
    await openEditor(route.draftId, false);
  } else if (!route.draftId) {
    document.querySelector("#editorOverlay").hidden = true;
    state.currentDraft = null;
  }
  if (route.view === "platform" && state.me?.is_super_admin) {
    await loadPlatformSection();
  }
}
function renderCurrent() {
  if (!state.data || !state.company) return;
  ({home: renderHome, ideas: renderIdeas, plan: renderPlan, drafts: renderDrafts, calendar: renderCalendar, brand: renderBrand, analytics: renderAnalytics, settings: renderSettings, platform: renderPlatform}[state.view])();
  localizeDom(document.querySelector(`#${state.view}View`) || document.body);
}

function applyIdentity() {
  const role = state.me.role || "platform_admin";
  document.querySelector("#userName").textContent = state.me.display_name || state.me.username;
  document.querySelector("#userRole").textContent = roleLabel(role);
  const avatar = document.querySelector("#userAvatar");
  if (state.me.avatar_url) avatar.src = state.me.avatar_url;
  else avatar.removeAttribute("src");
  avatar.alt = state.me.display_name || state.me.username;
  document.querySelector("#workspaceName").textContent = state.company.name;
  const workspaceLogo = document.querySelector("#workspaceLogo");
  workspaceLogo.innerHTML = workspaceAvatarMarkup({
    ...state.company,
    workspace_avatar_asset_id: state.company.settings?.workspace_avatar_asset_id,
  });
  document.querySelector("#workspacePlan").textContent = `${roleLabel(role)} · ${state.company.plan_code || "custom"} plan`;
  document.querySelector("#ideasCount").textContent = (state.data.ideas || []).length;
  document.querySelector("#draftsCount").textContent = (state.data.drafts || []).filter(x => x.status !== "published").length;
  const kanban = state.company.settings?.workspace_mode === "kanban";
  document.querySelectorAll(".pipeline-only").forEach(node => node.hidden = kanban);
  document.querySelector("#draftsNavLabel").textContent = kanban ? "Дошка" : "Чернетки";
  document.querySelector("#analyticsNavLabel").textContent = kanban ? "Аналітика" : "Витрати";
  const readOnly = role === "viewer";
  const canAdmin = ["platform_admin", "owner", "admin"].includes(role);
  document.body.classList.toggle("read-only", readOnly);
  document.body.classList.toggle("non-admin", !canAdmin);
  document.querySelector("#platformNav").hidden = !state.me.is_super_admin;
  document.querySelectorAll("[data-platform-section]").forEach(node => {
    node.classList.toggle(
      "active",
      state.view === "platform" && node.dataset.platformSection === state.platformSection,
    );
  });
  [
    "#createButton","#generateIdeas","#manualIdea","#manualDraft",
    "#calendarSchedule","#planForm button[type=submit]",
  ].forEach(selector => {
    const node = document.querySelector(selector);
    if (node) node.hidden = readOnly;
  });
  updateNotificationBadge();
  updateServiceUpdatesBadge();
  renderSystemBanner();
}

function renderSystemBanner() {
  const banner = document.querySelector("#systemBanner");
  const expiry = state.company?.plan_expires_at
    ? Math.ceil((new Date(state.company.plan_expires_at) - new Date()) / 86400000)
    : null;
  if (!navigator.onLine) {
    banner.textContent = "Немає з’єднання з мережею. Зміни стануть доступними після відновлення зв’язку.";
    banner.className = "system-banner error";
    banner.hidden = false;
  } else if (expiry !== null && expiry <= 0) {
    banner.textContent = "Термін тарифу завершився. AI-генерація та публікація тимчасово недоступні.";
    banner.className = "system-banner error";
    banner.hidden = false;
  } else if (state.company?.plan_code === "trial" && expiry !== null && expiry <= 3) {
    banner.textContent = `Trial завершується через ${expiry} дн. Оберіть тариф, щоб зберегти доступ до генерації.`;
    banner.className = "system-banner";
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

function renderHome() {
  const drafts = state.data.drafts || [];
  const ideas = state.data.ideas || [];
  const counts = {
    idea: ideas.filter(x => ["idea","suggested"].includes(x.status)).length,
    draft: drafts.filter(x => x.status === "draft").length,
    review: drafts.filter(x => x.status === "review").length,
    ready: drafts.filter(x => x.status === "ready").length,
    scheduled: drafts.filter(x => x.status === "scheduled").length,
    published: drafts.filter(x => x.status === "published").length,
  };
  document.querySelector("#homeMetrics").innerHTML = [
    ["idea","Ідеї",counts.idea,"Нові теми"],
    ["draft","Чернетки",counts.draft,"У роботі"],
    ["review","На перевірці",counts.review,"Потребують уваги"],
    ["ready","Готово",counts.ready,"Очікують публікації"],
    ["scheduled","Заплановано",counts.scheduled,"У календарі"],
    ["published","Опубліковано",counts.published,"За весь час"],
  ].map(([status,label,value,note]) => `<article class="card metric">${pill(status)}<strong>${value}</strong><small>${note}</small></article>`).join("");
  document.querySelector("#quickActions").innerHTML = `
    <div class="quick-action featured" data-action="ideas"><span class="action-icon">${icon("ideas")}</span><div><strong>Згенерувати ідеї</strong><small style="display:block;color:#c7d2fe">AI запропонує теми на основі бренду</small></div></div>
    <div class="quick-action" data-action="plan"><span class="action-icon">${icon("plan")}</span><div><strong>Створити контент-план</strong><small class="muted">На тиждень або місяць</small></div></div>
    <div class="quick-action" data-action="drafts"><span class="action-icon">${icon("drafts")}</span><div><strong>Створити чернетку</strong><small class="muted">З ідеї або з нуля</small></div></div>
    <div class="quick-action" data-action="calendar"><span class="action-icon">${icon("calendar")}</span><div><strong>Запланувати пост</strong><small class="muted">Чернетка з візуалом → календар</small></div></div>`;
  document.querySelectorAll(".quick-action").forEach(node => node.onclick = () => setView(node.dataset.action));
  const upcoming = drafts.filter(x => x.scheduled_at).sort((a,b) => new Date(a.scheduled_at)-new Date(b.scheduled_at)).slice(0,6);
  document.querySelector("#upcomingList").innerHTML = upcoming.length ? upcoming.map(item => `<button class="quick-action" data-draft="${item.id}"><strong style="min-width:54px">${formatDate(item.scheduled_at)}</strong><span style="text-align:left">${esc(plain(item.title))}</span>${pill(item.status)}</button>`).join("") : empty("Публікацій ще немає","Підготуйте чернетку та додайте її до календаря.");
  document.querySelectorAll("[data-draft]").forEach(node => node.onclick = () => openEditor(Number(node.dataset.draft)));
  const quota = state.company.quota_state || {};
  const textQuota = quota.text || {used:state.company.text_generation_count,limit:state.company.monthly_text_generations};
  const imageQuota = quota.image || {used:state.company.image_generation_count,limit:state.company.monthly_image_generations};
  const publicationQuota = quota.publications || {used:state.company.publication_count,limit:state.company.monthly_publications};
  const trialText = quota.subscription_status === "expired"
    ? "Trial завершився · оновіть тариф"
    : state.company.plan_code === "trial" && quota.days_left !== null
      ? `Trial active · ${quota.days_left} дн.`
      : "Ліміти поточного тарифу";
  document.querySelector("#usageCard").innerHTML = `<div class="eyebrow" style="color:#c4b5fd">Генерації · місяць</div><strong>${esc(trialText)}</strong><div class="quota-mini-list"><span>Тексти <b>${quotaLabel(textQuota.used,textQuota.limit)}</b></span><i><em style="width:${quotaPercent(textQuota.used,textQuota.limit)}%"></em></i><span>Зображення <b>${quotaLabel(imageQuota.used,imageQuota.limit)}</b></span><i><em style="width:${quotaPercent(imageQuota.used,imageQuota.limit)}%"></em></i><span>Публікації <b>${quotaLabel(publicationQuota.used,publicationQuota.limit)}</b></span><i><em style="width:${quotaPercent(publicationQuota.used,publicationQuota.limit)}%"></em></i></div>`;
  const completion = brandCompletion();
  const missing = completion.sections.filter(section => section.score < section.weight).slice(0, 3);
  document.querySelector("#brandProgress").innerHTML = `<div class="eyebrow">Бренд-профіль</div><h2>${t("brandFilled")} ${completion.total}%</h2><div class="brand-completion-bar"><span style="width:${completion.total}%"></span></div><p class="muted">Заповнений бренд-профіль робить AI-результати точнішими.</p>${missing.length ? `<div class="mini-score-list">${missing.map(section=>`<span>${esc(section.label)} <strong>${section.score}/${section.weight}%</strong></span>`).join("")}</div>` : ""}<button data-open-view="brand">${t("fillBrand")}</button>`;
  bindViewLinks();
}

function renderFilters(target, values, active, callback) {
  target.innerHTML = values.map(([value,label]) => `<button class="${value===active?"active":""}" data-filter="${value}">${label}</button>`).join("");
  target.querySelectorAll("button").forEach(button => button.onclick = () => callback(button.dataset.filter));
}
function renderIdeas() {
  const query = new URLSearchParams(location.search);
  state.ideaFilter = query.get("rubric") || "all";
  const filters = document.querySelector("#ideaFilters");
  filters.className = "list-filter-shell";
  filters.innerHTML = `<label class="list-search">Пошук<input id="ideaSearch" value="${esc(query.get("search")||"")}" placeholder="Назва або опис"></label>
    <label>Рубрика<select id="ideaRubric"><option value="all">Усі рубрики</option>${(state.data.rubrics||[]).map(x=>`<option value="${esc(x.slug)}" ${state.ideaFilter===x.slug?"selected":""}>${esc(x.name)}</option>`).join("")}</select></label>
    <details class="advanced-filters"><summary>Розширені фільтри</summary><div class="advanced-filter-grid">
      <label>Дата від<input id="ideaDateFrom" type="date" value="${esc(query.get("date_from")||"")}"></label>
      <label>Дата до<input id="ideaDateTo" type="date" value="${esc(query.get("date_to")||"")}"></label>
      <label>Сортування<select id="ideaSort"><option value="created_at">Датою створення</option><option value="planned_for" ${query.get("sort")==="planned_for"?"selected":""}>Плановою датою</option><option value="title" ${query.get("sort")==="title"?"selected":""}>Назвою</option></select></label>
      <label>Напрям<select id="ideaDirection"><option value="desc">Нові спочатку</option><option value="asc" ${query.get("direction")==="asc"?"selected":""}>Старі спочатку</option></select></label>
    </div></details>`;
  const applyIdeaFilters = () => updateListQuery({
    page:"1",
    search:document.querySelector("#ideaSearch").value.trim()||null,
    rubric:document.querySelector("#ideaRubric").value==="all"?null:document.querySelector("#ideaRubric").value,
    date_from:document.querySelector("#ideaDateFrom").value||null,
    date_to:document.querySelector("#ideaDateTo").value||null,
    sort:document.querySelector("#ideaSort").value==="created_at"?null:document.querySelector("#ideaSort").value,
    direction:document.querySelector("#ideaDirection").value==="desc"?null:document.querySelector("#ideaDirection").value,
  },renderIdeas,"ideas");
  filters.querySelectorAll("select,input[type=date]").forEach(node=>node.onchange=applyIdeaFilters);
  let ideaSearchTimer;
  document.querySelector("#ideaSearch").oninput=()=>{clearTimeout(ideaSearchTimer);ideaSearchTimer=setTimeout(applyIdeaFilters,350);};
  const data = pagedData("ideas","api/ideas",{
    rubric:state.ideaFilter,
    date_from:query.get("date_from")||"",
    date_to:query.get("date_to")||"",
    sort:query.get("sort")||"",
    direction:query.get("direction")||"",
  },renderIdeas);
  const target = document.querySelector("#ideasGrid");
  if (!data) {
    target.innerHTML = '<span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span>';
    return;
  }
  const liveIdeas = new Map((state.data.ideas || []).map(item => [Number(item.id), item]));
  const items = (data.items || []).map(item => ({...item,...(liveIdeas.get(Number(item.id)) || {})}));
  target.innerHTML = `${bulkBar("ideas",[["create_drafts","Створити чернетки"],["assign_rubric","Призначити рубрику"],["delete","Видалити","danger"]])}${items.length ? `<div class="table-wrap"><table class="users-table content-table"><thead><tr><th><input type="checkbox" data-select-all="ideas" aria-label="Обрати всі ідеї на сторінці"></th><th>${sortHeader("title","Ідея","ideas",renderIdeas)}</th><th>Рубрика</th><th>${sortHeader("planned_for","Планова дата","ideas",renderIdeas)}</th><th>${sortHeader("status","Статус","ideas",renderIdeas)}</th><th>Дії</th></tr></thead><tbody>${items.map(item => {
    const generating = activeGenerationStatuses.has(item.status);
    return `<tr class="${state.recentDraftIds.has(Number(item.draft_id)) ? "recent-row" : ""}"><td>${selectionCheckbox("ideas",item.id)}</td><td class="content-main"><strong>${esc(item.title_plain||plain(item.title))}</strong><small>${esc(plain(item.angle||"Перспективна тема для майбутньої публікації.").slice(0,150))}</small>${generating?`<div class="generation-progress"><span style="width:${Number(item.progress||12)}%"></span></div>`:""}</td><td><span class="pill idea">${esc((state.data.rubrics||[]).find(x=>x.slug===item.product)?.name||item.product)}</span></td><td>${item.planned_for?formatDate(item.planned_for):translateText("Ще не заплановано")}</td><td>${generating?`<span class="progress-label"><span class="spinner"></span>${esc(translateText(item.progress_label||statusLabel(item.status)))} · ${Number(item.progress||12)}%</span>`:pill(item.status)}</td><td><div class="table-actions">${can("content.create")?`<button class="dark-button" data-generate-idea="${item.id}" ${generating||item.draft_id?"disabled":""}>${generating?translateText("Генерується…"):item.draft_id?translateText("Створено"):translateText("Чернетка")}</button>`:""}${item.draft_id?`<button data-open-draft="${item.draft_id}">${translateText("Відкрити")}</button>`:""}${can("ideas.delete")?`<button class="ghost danger" data-delete-idea="${item.id}" ${generating?"disabled":""}>${translateText("Видалити")}</button>`:""}</div></td></tr>`;
  }).join("")}</tbody></table></div>` : empty("У вас ще немає ідей","Згенеруйте перші теми на основі бренду та рубрик.",can("ideas.create")?'<button class="primary" id="emptyGenerateIdeas">✦ Згенерувати ідеї</button>':"")}${pagination(data,"ideas",renderIdeas)}`;
  bindSelection("ideas",target,renderIdeas);
  target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("ideas").clear();renderIdeas();});
  target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runIdeaBulk(button.dataset.bulkAction));
  document.querySelectorAll("[data-generate-idea]").forEach(button => button.onclick = () => generateIdea(button));
  document.querySelectorAll("[data-open-draft]").forEach(button => button.onclick = () => openEditor(Number(button.dataset.openDraft)));
  document.querySelectorAll("[data-delete-idea]").forEach(button => button.onclick = async () => {
    if (!confirm("Видалити цю ідею?")) return;
    await api(`api/ideas/${button.dataset.deleteIdea}`, {method:"DELETE"});
    toast("Ідею видалено");
    await refresh();
  });
  document.querySelector("#emptyGenerateIdeas")?.addEventListener("click", () => document.querySelector("#generateIdeas").click());
}
async function runIdeaBulk(action) {
  const ids=[...selected("ideas")].map(Number);
  if (!ids.length) return;
  let value="";
  if (action==="delete"&&!confirm(`Видалити ${ids.length} елементів?\nЦю дію не можна буде скасувати.`)) return;
  if (action==="assign_rubric") {
    value=prompt(`Slug рубрики:\n${(state.data.rubrics||[]).map(x=>x.slug).join(", ")}`)||"";
    if (!value) return;
  }
  const result = await api("api/ideas/bulk",{method:"POST",body:JSON.stringify({ids,action,value})});
  if (action === "create_drafts") {
    (result.job_ids || []).forEach(id => state.recentJobIds.add(Number(id)));
    selected("ideas").clear();
    delete state.lists.ideas;
    delete state.lists.drafts;
    toast(`Запущено генерацію чернеток: ${result.changed || ids.length}`);
    await refresh(true);
    setView("drafts");
    return;
  }
  selected("ideas").clear();delete state.lists.ideas;toast("Масову дію виконано");await refresh(true);renderIdeas();
}
async function generateIdea(button) {
  await loading(button, async () => {
    const result = await api(`api/ideas/${button.dataset.generateIdea}/generate`, {method:"POST",body:JSON.stringify(generationPayload())});
    if (result.job_id) state.recentJobIds.add(Number(result.job_id));
    toast("Генерацію розпочато. Прогрес з’явиться у чернетках.");
    await refresh(true);
    delete state.lists.drafts;
    setView("drafts");
  }, "Створюємо…");
}
function generationPayload() {
  return {text_model:"gpt-5.4-mini",image_model:"gpt-image-2",reference_ids:[],template_id:"editorial-dark",logo_reference_id:null,company_logo_reference_id:null,link_url:"",tone:"expert",generation_mode:"fast"};
}

function renderPlan() {
  const select = document.querySelector("#planProduct");
  select.innerHTML = `<option value="all">Усі рубрики</option>${(state.data.rubrics||[]).filter(x=>x.active!==0).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}`;
  if (!document.querySelector("#planStart").value) document.querySelector("#planStart").value = localDateKey(new Date());
  const data = pagedData("plan","api/content-plan/items",{},renderPlan);
  const target=document.querySelector("#planList");
  if(!data){target.innerHTML='<span class="skeleton"></span><span class="skeleton"></span>';return;}
  const planned=data.items||[];
  const rubricName=item=>esc((state.data.rubrics||[]).find(x=>x.slug===item.product)?.name||item.rubric_name||item.product||"—");
  target.innerHTML=`${bulkBar("plan",[["delete","Видалити","danger"]])}${planned.length?`<div class="table-wrap plan-table-wrap"><table class="users-table content-table plan-table"><thead><tr><th><input type="checkbox" data-select-all="plan" aria-label="Обрати всі пункти плану"></th><th>Дата</th><th>Тема</th><th>Рубрика</th><th>Статус</th><th>Дії</th></tr></thead><tbody>${planned.map(item=>`<tr><td>${selectionCheckbox("plan",item.id)}</td><td><strong>${formatDate(item.planned_for)}</strong></td><td class="content-main"><strong>${esc(item.title_plain||plain(item.title))}</strong>${item.error_message?`<small class="plan-error">${esc(item.error_message)}</small>`:""}</td><td>${rubricName(item)}</td><td>${pill(item.status)}</td><td>${["failed","error","cancelled"].includes(item.status)&&item.job_id?`<div class="row plan-actions"><button data-retry-job="${item.job_id}">Повторити</button><button data-job-details="${item.job_id}">Деталі</button><button class="danger" data-delete-job="${item.job_id}">Видалити</button></div>`:'<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table></div>`:empty("Контент-план порожній","Виберіть параметри та створіть перший план.")}${pagination(data,"plan",renderPlan)}`;
  bindSelection("plan",target,renderPlan);
  target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("plan").clear();renderPlan();});
  target.querySelector("[data-bulk-action='delete']")?.addEventListener("click",async()=>{
    const ids=[...selected("plan")].map(Number);if(!ids.length||!confirm(`Видалити ${ids.length} елементів?\nЦю дію не можна буде скасувати.`))return;
    await api("api/ideas/bulk",{method:"POST",body:JSON.stringify({ids,action:"delete",value:""})});selected("plan").clear();delete state.lists.plan;await refresh(true);renderPlan();
  });
  target.querySelectorAll("[data-retry-job]").forEach(button=>button.onclick=async()=>{await loading(button,()=>api(`api/jobs/${button.dataset.retryJob}/retry-fast`,{method:"POST"}),"Повторюємо…");delete state.lists.plan;toast("Генерацію повторено");renderPlan();});
  target.querySelectorAll("[data-job-details]").forEach(button=>button.onclick=()=>{const item=planned.find(row=>String(row.job_id)===button.dataset.jobDetails);showForm("Деталі помилки",`<div class="wide callout warning"><strong>${esc(item?.error_message||"Помилка генерації")}</strong><p>${esc(item?.error||"Спробуйте повторити генерацію або перевірте налаштування AI.")}</p></div>`,null);});
  target.querySelectorAll("[data-delete-job]").forEach(button=>button.onclick=async()=>{if(!confirm("Видалити помилкове завдання?"))return;await api(`api/jobs/${button.dataset.deleteJob}`,{method:"DELETE"});delete state.lists.plan;toast("Запис видалено");renderPlan();});
}

function generationCard(job, draft = null) {
  const progress = Number(job.progress || 12);
  const title = draft?.title_plain || draft?.title || job.topic || "Нова чернетка";
  return `<article class="card generation-card">
    <div class="generation-visual"><div class="ai-orbit"><span class="ai-logo">AI</span><i></i><i></i><i></i></div></div>
    <div class="generation-body">
      ${pill(job.status)}
      <h3>${esc(plain(title))}</h3>
      <p class="muted">${esc(translateText(job.progress_label || statusLabel(job.status) || "Генеруємо матеріал"))}</p>
      <div class="generation-progress"><span style="width:${progress}%"></span></div>
      <div class="generation-status"><span>${job.status === "queued_image" || job.status === "image_batch" ? "Текст уже готовий, створюємо зображення" : "Створюємо текст і структуру поста"}</span><strong>${progress}%</strong></div>
    </div>
  </article>`;
}

function renderDrafts() {
  const kanban = state.company.settings?.workspace_mode === "kanban";
  const query = new URLSearchParams(location.search);
  state.draftFilter = query.get("status") || "all";
  const filters = document.querySelector("#draftFilters");
  filters.className = "list-filter-shell";
  filters.innerHTML = `<label class="list-search">Пошук<input id="draftSearch" value="${esc(query.get("search")||"")}" placeholder="Заголовок або текст"></label>
    <label>Статус<select id="draftStatus">${[["all","Усі статуси"],["draft","Чернетки"],["review","На перевірці"],["needs_changes","Потрібні правки"],["ready","Готові"],["scheduled","Заплановані"],["published","Опубліковані"]].map(([value,label])=>`<option value="${value}" ${state.draftFilter===value?"selected":""}>${label}</option>`).join("")}</select></label>
    <details class="advanced-filters"><summary>Розширені фільтри</summary><div class="advanced-filter-grid">
      <label>Рубрика<select id="draftRubric"><option value="">Усі рубрики</option>${(state.data.rubrics||[]).map(x=>`<option value="${esc(x.slug)}" ${query.get("rubric")===x.slug?"selected":""}>${esc(x.name)}</option>`).join("")}</select></label>
      <label>Дата від<input id="draftDateFrom" type="date" value="${esc(query.get("date_from")||"")}"></label>
      <label>Дата до<input id="draftDateTo" type="date" value="${esc(query.get("date_to")||"")}"></label>
      <label>Сортування<select id="draftSort"><option value="created_at">Датою створення</option><option value="scheduled_at" ${query.get("sort")==="scheduled_at"?"selected":""}>Датою публікації</option><option value="title" ${query.get("sort")==="title"?"selected":""}>Назвою</option></select></label>
      <label>Напрям<select id="draftDirection"><option value="desc">Нові спочатку</option><option value="asc" ${query.get("direction")==="asc"?"selected":""}>Старі спочатку</option></select></label>
    </div></details>`;
  const applyDraftFilters=()=>updateListQuery({
    page:"1",search:document.querySelector("#draftSearch").value.trim()||null,
    status:document.querySelector("#draftStatus").value==="all"?null:document.querySelector("#draftStatus").value,
    rubric:document.querySelector("#draftRubric").value||null,
    date_from:document.querySelector("#draftDateFrom").value||null,date_to:document.querySelector("#draftDateTo").value||null,
    sort:document.querySelector("#draftSort").value==="created_at"?null:document.querySelector("#draftSort").value,
    direction:document.querySelector("#draftDirection").value==="desc"?null:document.querySelector("#draftDirection").value,
  },renderDrafts,"drafts");
  filters.querySelectorAll("select,input[type=date]").forEach(node=>node.onchange=applyDraftFilters);
  let draftSearchTimer;document.querySelector("#draftSearch").oninput=()=>{clearTimeout(draftSearchTimer);draftSearchTimer=setTimeout(applyDraftFilters,350);};
  const data=pagedData("drafts","api/drafts",{
    status:state.draftFilter,rubric:query.get("rubric")||"",date_from:query.get("date_from")||"",
    date_to:query.get("date_to")||"",sort:query.get("sort")||"",direction:query.get("direction")||"",
  },renderDrafts);
  const target = document.querySelector("#draftsContent");
  if(!data){target.innerHTML='<div class="draft-grid"><span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span></div>';return;}
  const drafts=data.items||[];
  const activeJobs=(state.data.jobs||[]).filter(job=>activeGenerationStatuses.has(job.status));
  const activeDraftIds=new Set(activeJobs.filter(job=>job.draft_id).map(job=>Number(job.draft_id)));
  const visibleDrafts=drafts.filter(draft=>!activeDraftIds.has(Number(draft.id)));
  const draftById=new Map([...(state.data.drafts||[]),...drafts].map(draft=>[Number(draft.id),draft]));
  const generationCards=activeJobs.map(job=>generationCard(job,draftById.get(Number(job.draft_id)))).join("");
  const generationStrip=generationCards?`<div class="generation-strip">${generationCards}</div>`:"";
  const bar=bulkBar("drafts",[["status","Змінити статус"],["assign_rubric","Призначити рубрику"],["delete","Видалити","danger"]]);
  if (kanban) {
    target.innerHTML = `${bar}${generationStrip}<div class="kanban-board">${statusOrder.map(status => {const rows = status==="idea" ? [] : visibleDrafts.filter(x=>x.status===status);return `<section class="kanban-column"><div class="kanban-head"><span>${statusLabel(status)}</span><span>${rows.length}</span></div>${rows.map(item=>`<article class="kanban-card selectable-card">${selectionCheckbox("drafts",item.id)}<button class="kanban-open" data-open-draft="${item.id}">${pill(item.status)}<h4>${esc(item.title_plain||plain(item.title))}</h4><small class="muted">${formatDate(item.scheduled_at||item.created_at)}</small></button><div class="kanban-actions">${can("content.edit")?(statusActions[item.status]||[]).map(([next,label])=>`<button data-transition-draft="${item.id}" data-transition-status="${next}">${translateText(label)}</button>`).join(""):""}</div></article>`).join("")}</section>`;}).join("")}</div>${pagination(data,"drafts",renderDrafts)}`;
  } else {
    target.innerHTML = `${bar}${generationStrip}${visibleDrafts.length ? `<div class="table-wrap"><table class="users-table content-table"><thead><tr><th><input type="checkbox" data-select-all="drafts" aria-label="Обрати всі чернетки на сторінці"></th><th>${sortHeader("title","Чернетка","drafts",renderDrafts)}</th><th>Рубрика</th><th>${sortHeader("status","Статус","drafts",renderDrafts)}</th><th>Візуал</th><th>${sortHeader("scheduled_at","Дата","drafts",renderDrafts)}</th><th>Дії</th></tr></thead><tbody>${visibleDrafts.map(item => `<tr class="${state.recentDraftIds.has(Number(item.id)) ? "recent-row" : ""}"><td>${selectionCheckbox("drafts",item.id)}</td><td class="content-main"><strong>${esc(item.title_plain||plain(item.title))}</strong>${state.recentDraftIds.has(Number(item.id))?'<span class="fresh-chip">Щойно створено</span>':""}<small>${esc((item.caption_plain||plain(item.caption_html)).slice(0,155))}</small></td><td>${esc((state.data.rubrics||[]).find(x=>x.slug===item.product)?.name||item.product)}</td><td>${pill(item.status)}</td><td>${item.image_path?'<span class="success-text">Готовий</span>':'<span class="muted">Без зображення</span>'}</td><td>${item.scheduled_at?formatDate(item.scheduled_at):"Ще не заплановано"}</td><td><button data-open-draft="${item.id}">Відкрити</button></td></tr>`).join("")}</tbody></table></div>` : generationCards?"":empty("Чернеток ще немає","Створіть чернетку з ідеї або додайте матеріал вручну.")}${pagination(data,"drafts",renderDrafts)}`;
  }
  bindSelection("drafts",target,renderDrafts);
  target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("drafts").clear();renderDrafts();});
  target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runDraftBulk(button.dataset.bulkAction));
  document.querySelectorAll("[data-open-draft]").forEach(node => node.onclick = () => openEditor(Number(node.dataset.openDraft)));
  document.querySelectorAll("[data-transition-draft]").forEach(node => node.onclick = async () => {
    await api(`api/drafts/${node.dataset.transitionDraft}/status`, {method:"POST",body:JSON.stringify({status:node.dataset.transitionStatus})});
    toast(`${translateText("Статус змінено:")} ${statusLabel(node.dataset.transitionStatus)}`);
    await refresh();
  });
}
async function runDraftBulk(action) {
  const ids=[...selected("drafts")].map(Number);if(!ids.length)return;
  let value="";
  if(action==="delete"&&!confirm(`Видалити ${ids.length} елементів?\nЦю дію не можна буде скасувати.`))return;
  if(action==="assign_rubric"){value=prompt(`Slug рубрики:\n${(state.data.rubrics||[]).map(x=>x.slug).join(", ")}`)||"";if(!value)return;}
  if(action==="status"){value=prompt("Новий статус: draft, review, needs_changes, ready")||"";if(!value)return;}
  await api("api/drafts/bulk",{method:"POST",body:JSON.stringify({ids,action,value})});selected("drafts").clear();delete state.lists.drafts;toast("Масову дію виконано");await refresh(true);renderDrafts();
}

function renderCalendar() {
  const year = state.calendarDate.getFullYear(), month = state.calendarDate.getMonth();
  document.querySelector("#calendarTitle").textContent = state.calendarDate.toLocaleDateString(state.locale === "en" ? "en-US" : "uk-UA",{month:"long",year:"numeric"});
  const drafts = state.data.drafts || [];
  const schedulable = drafts.filter(x => x.status !== "published" && !x.scheduled_at);
  document.querySelector("#calendarReady").innerHTML = schedulable.length
    ? schedulable.map(x=>`<button class="quick-action" data-schedule-draft="${x.id}">${pill(x.status)}<span style="min-width:0;text-align:left"><strong>${esc(plain(x.title))}</strong><small class="muted">${x.image_path ? "Можна запланувати" : "Спочатку потрібен візуал"}</small></span></button>`).join("")
    : `<p class="muted">Усі матеріали вже заплановані або опубліковані.</p>`;
  const first = new Date(year,month,1), offset = (first.getDay()+6)%7;
  const start = new Date(year,month,1-offset);
  const cells = [];
  for (let i=0;i<42;i++) {
    const day = new Date(start); day.setDate(start.getDate()+i);
    const key = localDateKey(day);
    const events = drafts.filter(x => x.scheduled_at && localDateKey(x.scheduled_at)===key);
    const socialEvents = (state.data.social_publish_jobs||[]).filter(x => x.scheduled_at && localDateKey(x.scheduled_at)===key);
    cells.push(`<div class="calendar-day ${day.getMonth()!==month?"outside":""} ${key===localDateKey(new Date())?"today":""}"><strong>${day.getDate()}</strong>${events.map(x=>`<button class="calendar-event" data-open-draft="${x.id}">${new Date(x.scheduled_at).toLocaleTimeString(state.locale === "en" ? "en-US" : "uk-UA",{hour:"2-digit",minute:"2-digit"})} · ${esc(plain(x.title))}</button>`).join("")}${socialEvents.map(job=>{const draft=drafts.find(item=>Number(item.id)===Number(job.draft_id));return `<button class="calendar-event instagram" data-open-draft="${job.draft_id}">${new Date(job.scheduled_at).toLocaleTimeString(state.locale === "en" ? "en-US" : "uk-UA",{hour:"2-digit",minute:"2-digit"})} · Instagram · ${esc(plain(draft?.title||`Чернетка #${job.draft_id}`))}</button>`}).join("")}</div>`);
  }
  document.querySelector("#calendarGrid").innerHTML = ["Пн","Вт","Ср","Чт","Пт","Сб","Нд"].map(x=>`<div class="calendar-weekday">${x}</div>`).join("")+cells.join("");
  document.querySelectorAll("[data-open-draft]").forEach(node => node.onclick = () => openEditor(Number(node.dataset.openDraft)));
  document.querySelectorAll("[data-schedule-draft]").forEach(node => node.onclick = () => openScheduleForm(Number(node.dataset.scheduleDraft)));
}
function openScheduleForm(selectedId = null) {
  const drafts = (state.data.drafts || []).filter(x => x.status !== "published" && !x.scheduled_at);
  const eligible = drafts.filter(x => x.image_path);
  if (!eligible.length) {
    showForm(
      "Немає матеріалів для планування",
      `<div class="wide callout warning"><strong>Чому список порожній?</strong><p>У календар можна додати будь-яку неопубліковану чернетку, але для публікації потрібен готовий візуал. Відкрийте чернетку та згенеруйте або додайте зображення.</p></div>${drafts.map(x=>`<div class="wide schedule-row">${pill(x.status)}<span>${esc(plain(x.title))}</span><small>Немає візуалу</small></div>`).join("")}`,
      null,
    );
    return;
  }
  showForm(
    "Запланувати публікацію",
    `<div class="wide callout"><strong>Чернетка буде затверджена</strong><p>Після вибору дати матеріал отримає статус «Заплановано». Перед публікацією його ще можна відкрити, відредагувати або повернути в готові.</p></div>
    <label class="wide">Матеріал<select name="draft_id" id="scheduleDraftSelect">${eligible.map(x=>`<option value="${x.id}" ${x.id===selectedId?"selected":""}>${esc(plain(x.title))} — ${esc(statusLabel(x.status))}</option>`).join("")}</select></label>
    <div class="wide schedule-preview" id="scheduleDraftPreview"></div>
    <label class="wide">Дата і час<input name="scheduled_at" type="datetime-local" min="${localDateTimeValue(new Date(Date.now()+60000))}" required></label>`,
    async form => {
      await api(`api/drafts/${form.get("draft_id")}/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(form.get("scheduled_at")).toISOString()})});
      toast("Публікацію додано до календаря");
      await refresh();
      renderCalendar();
    },
    {submitLabel:"Запланувати"},
  );
  const preview = document.querySelector("#scheduleDraftPreview");
  const select = document.querySelector("#scheduleDraftSelect");
  const renderPreview = () => {
    const draft = eligible.find(item => String(item.id) === String(select.value)) || eligible[0];
    if (!draft) return;
    preview.innerHTML = `<article class="schedule-preview-card">
      <img src="${apiUrl(`api/drafts/${draft.id}/image`)}" alt="" onerror="this.closest('.schedule-preview-card').classList.add('no-image');this.remove()">
      <div>
        <div class="row">${pill(draft.status)}<span class="muted">${esc((state.data.rubrics||[]).find(r=>r.slug===draft.product)?.name||draft.product)}</span></div>
        <h3>${esc(plain(draft.title))}</h3>
        <p>${esc(plain(draft.caption_html||draft.topic||"").slice(0,360))}</p>
        <button type="button" class="ghost" data-preview-open-draft="${draft.id}">Відкрити чернетку</button>
      </div>
    </article>`;
    preview.querySelector("[data-preview-open-draft]").onclick = () => {
      document.querySelector("#formOverlay").hidden = true;
      openEditor(draft.id);
    };
  };
  select.addEventListener("change", renderPreview);
  renderPreview();
}

function renderBrand() {
  const settings = state.company.settings || {};
  const target = document.querySelector("#brandContent");
  updateBrandTabLabels();
  if (state.brandTab === "profile") target.innerHTML = `<div class="brand-layout"><article class="card brand-summary"><div class="row"><span class="workspace-logo">${initials(state.company.name)}</span><div><h2 style="margin:0">${esc(state.company.name)}</h2><span class="muted">${esc(settings.key_services||"Додайте ключові послуги")}</span></div></div>${renderBrandCompletionDetails({compact:true})}<div class="form-grid" style="margin-top:22px"><label>Сайт<input id="brandWebsite" type="url" placeholder="https://company.ua" value="${esc(settings.website_url||"")}"><small class="field-help">Сайт допомагає AI точніше зрозуміти продукт і термінологію.</small></label>${colorControl({id:"brandColor",label:"Основний колір",value:settings.brand_primary_color||"#6366f1",help:"Використовується у візуальних шаблонах."})}<label class="wide">Опис компанії<textarea id="brandDescription" placeholder="Хто ви, для кого працюєте, яку проблему вирішуєте і чим відрізняєтесь. 3–6 конкретних речень.">${esc(settings.company_description||"")}</textarea><small class="field-help">Приклад: «VoicerHub допомагає бізнесу автоматизувати голосові комунікації. Наші клієнти — контакт-центри та сервісні команди…»</small></label><label class="wide">Ключові продукти або послуги<textarea id="brandServices" placeholder="Назва продукту — коротко яку задачу він вирішує">${esc(settings.key_services||"")}</textarea><small class="field-help">Додайте конкретні назви, цільову аудиторію та користь. Це стане контекстом для генерації.</small></label></div><button class="primary" id="saveBrandProfile" style="margin-top:14px">Зберегти профіль</button></article><aside class="card panel"><h2>Рубрики</h2>${(state.data.rubrics||[]).map(x=>`<div class="usage-row"><span>${esc(x.name)}</span><strong>${(state.data.ideas||[]).filter(i=>i.product===x.slug).length}</strong></div>`).join("")||'<p class="muted">Ще немає рубрик.</p>'}</aside></div>`;
  else if (state.brandTab === "tone") target.innerHTML = `<article class="card panel"><div class="row between"><div><div class="eyebrow">Стиль комунікації</div><h2>Tone of voice</h2><p class="muted">Опишіть, як бренд звучить у текстах. Не використовуйте абстрактні слова без прикладів.</p></div><button class="primary" id="saveTone">Зберегти</button></div><textarea id="toneValue" placeholder="Пишемо українською, короткими реченнями. Звертаємося на «ви». Тон експертний, але доброзичливий. Пояснюємо терміни простими словами.">${esc(settings.tone_of_voice||"")}</textarea><small class="field-help">Добре: правила, довжина речень, форма звертання, рівень експертності та 1–2 приклади. Погано: лише «професійно та сучасно».</small><div class="tone-boxes" style="margin-top:14px"><div class="tone-good"><strong>✓ Що можна</strong><p>Писати зрозуміло, конкретно та впевнено; підкріплювати тези прикладами.</p></div><div class="tone-bad"><strong>× Чого не можна</strong><p>${esc(settings.forbidden_phrases||"Вкажіть кліше, перебільшення, небажані слова та обіцянки.")}</p></div></div></article>`;
  else if (state.brandTab === "rubrics") {
    const query = new URLSearchParams(location.search);
    const data=pagedData("rubrics","api/rubrics",{sort:query.get("sort")||"",direction:query.get("direction")||""},renderBrand);
    if(!data){target.innerHTML='<span class="skeleton"></span>';return;}
    const rows=data.items||[];
    target.innerHTML=`<article class="card panel"><div class="row between"><div><h2>Рубрики контенту</h2><p class="muted">Рубрики допомагають Content Studio створювати контент системно. Кожна рубрика задає тему, ціль, тон і правила для AI.</p></div>${can("rubrics.manage")?'<button class="primary" id="addRubric">＋ Створити рубрику</button>':""}</div><div class="callout"><strong>Як AI використовує рубрики</strong><p>Під час генерації ідей і контент-плану AI чергує різні формати та не повторює один тип контенту.</p></div>${bulkBar("rubrics",[["activate","Активувати"],["deactivate","Деактивувати"],["delete","Видалити","danger"]])}${rows.length?`<div class="table-wrap"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="rubrics" aria-label="Обрати всі"></th><th>${sortHeader("name","Рубрика","rubrics",renderBrand)}</th><th>Ціль</th><th>Тон</th><th>Статус</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td>${selectionCheckbox("rubrics",x.id)}</td><td><strong>${esc(x.name)}</strong><small>${esc(x.description)}</small></td><td>${esc(x.goal||"—")}</td><td>${esc(x.tone||"—")}</td><td>${x.active?"Активна":"Неактивна"}</td><td>${can("rubrics.manage")?`<button data-edit-rubric="${x.id}">Редагувати</button>`:""}</td></tr>`).join("")}</tbody></table></div>`:empty("У вас ще немає рубрик","Створіть рубрики, щоб AI міг планувати експертні пости, кейси, поради, новини та продажні матеріали.",can("rubrics.manage")?'<button class="primary" id="emptyAddRubric">Створити рубрику</button>':"")}${pagination(data,"rubrics",renderBrand)}</article>`;
    bindSelection("rubrics",target,renderBrand);target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("rubrics").clear();renderBrand();});
    target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runRubricBulk(button.dataset.bulkAction));
    target.querySelectorAll("[data-edit-rubric]").forEach(button=>button.onclick=()=>openRubricForm(rows.find(x=>x.id===Number(button.dataset.editRubric))));
  } else if (state.brandTab === "visuals") {
    const data=pagedData("visuals","api/brand/visual-styles",{},renderBrand);
    if(!data){target.innerHTML='<span class="skeleton"></span>';return;}
    const builtIns=(state.data.templates||[]).filter(x=>!x.custom);
    const rows=data.items||[];
    const builtInCards=builtIns.map(x=>`<article class="card asset-card"><img src="${apiUrl(`api/templates/${encodeURIComponent(x.id)}/preview`)}" alt="" loading="eager" decoding="async" fetchpriority="high"><div class="asset-body"><strong>${esc(x.name)}</strong><small>${esc(x.description)}</small><span class="pill ready">Системний</span></div></article>`).join("");
    const customCards=rows.map(x=>`<article class="card asset-card selectable-card">${selectionCheckbox("visuals",x.id)}<img src="${apiUrl(`api/templates/${encodeURIComponent(x.id)}/preview`)}" alt="" loading="eager" decoding="async" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'asset-placeholder',textContent:'Попередній перегляд'}))"><div class="asset-body"><strong>${esc(x.name)}</strong><small>${esc(x.description)}</small><div class="row"><button data-edit-style="${esc(x.id)}">Редагувати</button><button data-duplicate-style="${esc(x.id)}">Дублювати</button></div></div></article>`).join("");
    const emptyStyles=can("visual_styles.manage")?`<button class="visual-empty-card" id="addVisualStyleEmpty" type="button"><span class="visual-empty-icon">AI</span><span class="visual-empty-copy"><strong>Власних стилів ще немає</strong><small>Створіть стиль, щоб AI генерував візуали у впізнаваній манері вашого бренду: кольори, настрій, правила композиції та приклади промптів.</small></span><span class="visual-empty-action">Створити стиль</span></button>`:empty("Власних стилів ще немає","Створіть стиль для генерації візуалів у впізнаваній манері бренду.");
    target.innerHTML=`<div class="row between brand-section-head"><div><h2>Візуальні стилі</h2><p class="muted">Збережіть правила кольорів, настрою та композиції, які AI використовуватиме для зображень.</p></div>${can("visual_styles.manage")&&rows.length?'<button class="primary" id="addVisualStyle">＋ Створити стиль</button>':""}</div>${rows.length?"":emptyStyles}<h3>Стилі workspace</h3>${rows.length?bulkBar("visuals",[["activate","Активувати"],["deactivate","Деактивувати"],["delete","Видалити","danger"]]):""}<div class="asset-grid">${customCards||""}</div><div class="callout visual-system-callout"><strong>Вбудовані стилі</strong><p>Глобальні шаблони доступні для використання, але не редагуються. Прев’ю завантажуються одразу, щоб швидше оцінити стиль.</p></div><div class="asset-grid">${builtInCards}</div>${pagination(data,"visuals",renderBrand)}`;
    bindSelection("visuals",target,renderBrand);target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("visuals").clear();renderBrand();});
    target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runBrandBulk("visuals",button.dataset.bulkAction));
    target.querySelectorAll("[data-edit-style]").forEach(button=>button.onclick=()=>openVisualStyleForm(rows.find(x=>x.id===button.dataset.editStyle)));
    target.querySelectorAll("[data-duplicate-style]").forEach(button=>button.onclick=async()=>{await api(`api/templates/${button.dataset.duplicateStyle}/duplicate`,{method:"POST"});delete state.lists.visuals;toast("Стиль дубльовано");renderBrand();});
  } else if (state.brandTab === "assets") {
    const data=pagedData("assets","api/brand/materials",{},renderBrand);
    if(!data){target.innerHTML='<span class="skeleton"></span>';return;}
    if(data.error){target.innerHTML=`<div class="empty-state"><h3>Не вдалося завантажити матеріали бренду</h3><p class="muted">${esc(data.error.message||"Спробуйте ще раз.")}</p><button class="primary" id="retryBrandMaterials">Спробувати ще раз</button></div>`;target.querySelector("#retryBrandMaterials").onclick=()=>{delete state.lists.assets;renderBrand();};return;}
    const rows=data.items||[];
    target.innerHTML=`<div class="row between brand-section-head"><div><h2>Матеріали бренду</h2><p class="muted">Матеріали допомагають AI краще розуміти стиль компанії: логотипи, кольори, презентації, брендбук і референси.</p></div>${can("brand_materials.manage")?'<div class="row"><button id="addMaterialLink">Додати посилання</button><button class="primary" id="uploadMaterial">Завантажити матеріал</button></div>':""}</div>${bulkBar("assets",[["activate","Активувати"],["deactivate","Деактивувати"],["delete","Видалити","danger"]])}<div class="asset-grid">${rows.map(x=>`<article class="card asset-card selectable-card">${selectionCheckbox("assets",x.id)}${x.path&&x.media_type?.startsWith("image/")?`<img src="${apiUrl(`api/references/${x.id}/image`)}" alt="">`:`<div class="asset-placeholder">${x.source_url?"Посилання":esc((x.filename||"Файл").split(".").pop().toUpperCase())}</div>`}<div class="asset-body"><strong>${esc(x.name||x.filename||"Матеріал")}</strong><small>${esc(x.material_type)} · ${x.active?"Активний":"Неактивний"}</small>${x.source_url?`<a href="${esc(x.source_url)}" target="_blank" rel="noopener">Відкрити посилання</a>`:""}${can("brand_materials.manage")?`<div class="row"><button data-edit-material="${x.id}">Редагувати</button><button class="danger" data-delete-material="${x.id}">Видалити</button></div>`:""}</div></article>`).join("")||empty("Матеріалів ще немає","Завантажте логотип, фото, референс або додайте важливе посилання.")}</div>${pagination(data,"assets",renderBrand)}`;
    bindSelection("assets",target,renderBrand);
    target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("assets").clear();renderBrand();});
    target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runBrandBulk("assets",button.dataset.bulkAction));
    target.querySelectorAll("[data-edit-material]").forEach(button=>button.onclick=()=>openMaterialForm(rows.find(x=>x.id===Number(button.dataset.editMaterial))));
    target.querySelectorAll("[data-delete-material]").forEach(button=>button.onclick=async()=>{if(!confirm("Видалити матеріал?"))return;await api(`api/references/${button.dataset.deleteMaterial}`,{method:"DELETE"});delete state.lists.assets;renderBrand();});
  } else {
    const avatarId=Number(settings.workspace_avatar_asset_id)||null;
    const logoId=Number(settings.brand_logo_asset_id)||null;
    const avatarPreview=avatarId?`<img src="${apiUrl(`api/references/${avatarId}/image`)}" alt="">`:`<span>${initials(state.company.name)}</span>`;
    const logoPreview=logoId?`<img src="${apiUrl(`api/references/${logoId}/image`)}" alt="">`:'<span class="muted">Логотип ще не завантажено</span>';
    target.innerHTML=`<div class="appearance-layout"><article class="card panel"><div class="eyebrow">Брендований workspace</div><h2>Оформлення</h2><div class="form-grid"><label>Назва workspace<input id="appearanceName" value="${esc(state.company.name)}"></label><label>Короткий опис<input id="appearanceDescription" value="${esc(settings.workspace_short_description||"")}"></label>
      <div class="wide color-section"><strong>Кольори інтерфейсу</strong><div class="color-controls">
        ${colorControl({id:"appearancePrimary",label:"Основний",value:settings.brand_primary_color||"#6366f1"})}
        ${colorControl({id:"appearanceSecondary",label:"Додатковий",value:settings.brand_secondary_color||"#a855f7"})}
      </div><div class="color-presets">${[["#4f46e5","#a855f7"],["#0f766e","#22c55e"],["#0369a1","#38bdf8"],["#be123c","#fb7185"],["#111827","#6366f1"]].map(([a,b])=>`<button type="button" data-color-preset="${a},${b}" title="${a} / ${b}"><i style="--a:${a};--b:${b}"></i></button>`).join("")}</div></div>
      <div class="wide appearance-assets">
        <label class="upload-tile"><span class="asset-preview avatar-preview" id="appearanceAvatarPreview">${avatarPreview}</span><strong>Аватар workspace</strong><small>PNG, JPG або WebP до 5 MB. Після завантаження ви обріжете фото в круглу область.</small>${can("workspace.settings")?'<input id="appearanceAvatarFile" type="file" accept="image/png,image/jpeg,image/webp"><span class="button">Завантажити й обрізати</span>':""}</label>
        <label class="upload-tile"><span class="asset-preview logo-preview" id="appearanceLogoPreview">${logoPreview}</span><strong>Логотип компанії</strong><small>PNG/WebP з прозорим фоном рекомендовано. Оптимально 1200×400 px, пропорції від 1:2 до 8:1, до 5 MB.</small>${can("workspace.settings")?'<input id="appearanceLogoFile" type="file" accept="image/png,image/jpeg,image/webp"><span class="button">Завантажити логотип</span>':""}</label>
      </div><input id="appearanceAvatar" type="hidden" value="${avatarId||""}"><input id="appearanceLogo" type="hidden" value="${logoId||""}"></div>${can("workspace.settings")?'<button class="primary" id="saveAppearance">Зберегти оформлення</button>':""}</article><aside class="card workspace-preview" id="appearancePreview" style="--preview-primary:${esc(settings.brand_primary_color||"#6366f1")};--preview-secondary:${esc(settings.brand_secondary_color||"#a855f7")}"><div class="eyebrow">Так workspace виглядатиме в інтерфейсі</div><span class="workspace-logo" id="workspacePreviewAvatar">${avatarPreview}</span><div class="workspace-preview-logo" id="workspacePreviewLogo">${logoPreview}</div><h3>${esc(state.company.name)}</h3><p>${esc(settings.workspace_short_description||"Контент, бренд і публікації в одному просторі.")}</p><div class="preview-nav"><span>Головна</span><span>Ідеї</span><span>Чернетки</span></div></aside></div>`;
  }
  bindBrandActions();
}

function renderAnalytics() {
  const totals = state.data.totals || {};
  const jobs = state.data.jobs || [];
  const drafts = state.data.drafts || [];
  document.querySelector("#analyticsMetrics").innerHTML = [
    ["AI-витрати цього місяця",money(totals.total_cost)],
    ["Генерації",jobs.length],
    ["Зображення",jobs.filter(x=>x.image_model).length],
    ["Опубліковано",drafts.filter(x=>x.status==="published").length],
  ].map(([label,value],i)=>`<article class="${i===0?"usage-card":"card metric"}"><span>${label}</span><strong>${value}</strong></article>`).join("");
  const daily = [...(state.data.daily||[])].reverse();
  const max = Math.max(...daily.map(x=>Number(x.cost)),.01);
  const totalDaily = daily.reduce((sum,row)=>sum+Number(row.cost||0),0) || .01;
  document.querySelector("#usageChart").innerHTML = daily.length ? daily.map(x=>{
    const cost=Number(x.cost||0);
    const share=Math.round(cost/totalDaily*100);
    return `<button class="chart-bar" type="button" style="height:${Math.max(3,cost/max*100)}%" data-day="${esc(formatDate(x.day))}" data-cost="${esc(money(cost))}" data-share="${share}" aria-label="${esc(formatDate(x.day))}: ${esc(money(cost))}"></button>`;
  }).join("") : `<p class="muted">Дані з’являться після першої AI-генерації.</p>`;
  const focus=document.querySelector("#usageChartFocus");
  if(focus&&daily.length){
    const setFocus=bar=>{
      focus.classList.add("active");
      focus.innerHTML=`<span>${esc(bar.dataset.day)}</span><strong>${esc(bar.dataset.cost)}</strong><small>${esc(bar.dataset.share)}% витрат обраного періоду</small>`;
    };
    document.querySelectorAll("#usageChart .chart-bar").forEach((bar,index)=>{
      bar.addEventListener("mouseenter",()=>setFocus(bar));
      bar.addEventListener("focus",()=>setFocus(bar));
      if(index===daily.length-1)setFocus(bar);
    });
  }
  const models = state.usage?.models || [];
  document.querySelector("#modelUsage").innerHTML = models.map(row=>`<div class="usage-row"><span>${esc(row.model)}<small class="muted" style="display:block">${row.operations} операцій</small></span><strong>${money(row.cost)}</strong></div>`).join("")||'<p class="muted">Немає даних.</p>';
  const rubrics = state.usage?.rubrics || [];
  document.querySelector("#rubricUsage").innerHTML = rubrics.map(row=>`<div class="usage-row"><span>${esc((state.data.rubrics||[]).find(x=>x.slug===row.rubric_slug)?.name||row.rubric_slug)}</span><strong>${money(row.cost)}</strong></div>`).join("")||'<p class="muted">Немає даних.</p>';
  renderPlatformAnalytics();
}

function renderPlatformAnalytics() {
  const target = document.querySelector("#platformAnalytics");
  if (!state.me?.is_super_admin) {
    target.hidden = true;
    return;
  }
  target.hidden = false;
  const report = state.platformUsage;
  target.innerHTML = `<article class="card panel platform-panel">
    <div class="row between platform-head">
      <div><div class="eyebrow">Platform admin</div><h2>Витрати всіх компаній</h2><p class="muted">Агрегований звіт без перемикання між workspace.</p></div>
      <div class="filters">${[["today","Сьогодні"],["7d","7 днів"],["month","Місяць"],["all","Весь час"]].map(([value,label])=>`<button class="${state.platformPeriod===value?"active":""}" data-platform-period="${value}">${label}</button>`).join("")}</div>
    </div>
    ${report ? `<div class="analytics-metrics platform-metrics">
      <div class="card metric"><span>Загальні витрати</span><strong>${money(report.totals.cost)}</strong></div>
      <div class="card metric"><span>Операції</span><strong>${report.totals.operations}</strong></div>
      <div class="card metric"><span>Тексти</span><strong>${report.totals.text_generations}</strong></div>
      <div class="card metric"><span>Зображення</span><strong>${report.totals.image_generations}</strong></div>
    </div>
    <div class="table-wrap"><table class="users-table"><thead><tr><th>Компанія</th><th>Операції</th><th>Тексти</th><th>Зображення</th><th>Витрати</th></tr></thead><tbody>${report.companies.map(row=>`<tr><td><strong>${esc(row.organization_name)}</strong></td><td>${row.operations}</td><td>${row.text_generations}</td><td>${row.image_generations}</td><td><strong>${money(row.cost)}</strong></td></tr>`).join("")}</tbody></table></div>` : '<div class="skeleton" style="min-height:160px"></div>'}
  </article>`;
  target.querySelectorAll("[data-platform-period]").forEach(button => button.onclick = async () => {
    state.platformPeriod = button.dataset.platformPeriod;
    state.platformUsage = null;
    renderPlatformAnalytics();
    state.platformUsage = await api(`api/platform/usage?period=${state.platformPeriod}`);
    renderPlatformAnalytics();
  });
}

const platformMeta = {
  overview: ["Огляд платформи","Ключові метрики реєстрацій, клієнтів і використання."],
  clients: ["Клієнти","Усі зареєстровані клієнти та джерела їх залучення."],
  companies: ["Компанії","Юридичні клієнти, їхні користувачі, ролі, workspace та активність."],
  users: ["Користувачі","Загальний список акаунтів сервісу."],
  referrals: ["Реферали","Посилання, переходи та реферальні реєстрації."],
  activity: ["Активність","Журнал важливих дій і входів без відкритих IP-адрес."],
  expenses: ["Витрати","AI-витрати по компаніях, моделях і користувачах."],
};
const platformDate = value => value
  ? new Date(value).toLocaleString(state.locale === "en" ? "en-US" : "uk-UA",{dateStyle:"short",timeStyle:"short"})
  : "—";
function platformEmpty(title, text) {
  return `<div class="empty-state"><h3>${esc(translateText(title))}</h3><p class="muted">${esc(translateText(text))}</p></div>`;
}
async function openPlatformSection(section, {push = true, clientId = null, companyId = null} = {}) {
  state.platformSection = section;
  state.platformClientId = clientId;
  state.platformCompanyId = companyId;
  state.platformData[section] = null;
  setView("platform",{push});
  await loadPlatformSection();
}
async function loadPlatformSection(force = false) {
  if (!state.me?.is_super_admin) return;
  const section = state.platformSection;
  const cacheKey = state.platformClientId
    ? `client-${state.platformClientId}`
    : state.platformCompanyId
    ? `company-${state.platformCompanyId}`
    : section;
  if (!force && state.platformData[cacheKey]) {
    renderPlatform();
    return;
  }
  document.querySelector("#platformContent").innerHTML = '<div class="platform-loading"><span class="skeleton"></span><span class="skeleton"></span><span class="skeleton"></span></div>';
  try {
    let data;
    if (section === "overview") data = await api("api/platform/overview");
    else if (section === "clients" && state.platformClientId) data = await api(`api/platform/clients/${state.platformClientId}`);
    else if (section === "clients") data = await api(`api/platform/clients?${new URLSearchParams(location.search)}`);
    else if (section === "companies" && state.platformCompanyId) data = await api(`api/platform/companies/${state.platformCompanyId}`);
    else if (section === "companies") data = await api(`api/platform/companies?${pageParams()}`);
    else if (section === "users") data = await api(`api/platform/users?${pageParams()}`);
    else if (section === "referrals") data = await api(`api/platform/referrals?${pageParams()}`);
    else if (section === "activity") data = await api(`api/platform/activity?${pageParams()}`);
    else data = await api(`api/platform/usage?period=${state.platformPeriod}&${pageParams()}`);
    state.platformData[cacheKey] = data;
    renderPlatform();
  } catch (error) {
    document.querySelector("#platformContent").innerHTML = platformEmpty("Не вдалося завантажити дані",error.message);
  }
}
function renderPlatform() {
  const target = document.querySelector("#platformContent");
  if (!target || !state.me?.is_super_admin) return;
  const [heading, description] = platformMeta[state.platformSection];
  document.querySelector("#platformHeading").textContent = translateText(heading);
  document.querySelector("#platformDescription").textContent = translateText(description);
  document.querySelectorAll("[data-platform-section]").forEach(node => node.classList.toggle("active",node.dataset.platformSection===state.platformSection));
  const key = state.platformClientId
    ? `client-${state.platformClientId}`
    : state.platformCompanyId
    ? `company-${state.platformCompanyId}`
    : state.platformSection;
  const data = state.platformData[key];
  if (!data) return;
  if (state.platformSection === "overview") {
    const m = data.metrics;
    target.innerHTML = `<div class="platform-metric-grid">${[
      ["Нові сьогодні",m.registrations_today],["Нові за 7 днів",m.registrations_7d],
      ["Користувачі",m.users_total],["Компанії",m.companies_total],
      ["Workspace",m.workspaces_total],["Активні компанії",m.active_companies],
      ["Workspace за місяць",m.new_workspaces_month],
      ["AI-витрати за місяць",money(m.ai_cost_month)],["Публікації",m.publications_total],
      ["Реферальні реєстрації",m.referral_signups],
    ].map(([label,value])=>`<article class="card metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></article>`).join("")}</div>
    <div class="platform-grid"><article class="card panel"><h2>Реєстрації по днях</h2>${data.registrations_by_day.length?`<div class="platform-bars">${data.registrations_by_day.map(row=>`<div title="${row.day}: ${row.count}"><span style="height:${Math.max(8,row.count*18)}px"></span><small>${row.day.slice(5)}</small></div>`).join("")}</div>`:platformEmpty("Клієнтів ще немає","Нові реєстрації з’являться в цьому розділі.")}</article>
    <article class="card panel"><h2>Топ компаній за usage</h2>${data.top_companies.map(row=>`<div class="usage-row"><span><strong>${esc(row.name)}</strong><small class="muted" style="display:block">${row.workspace_count} workspace · ${row.user_count} корист. · ${row.published_count} публікацій</small></span><strong>${money(row.ai_cost)}</strong></div>`).join("")||'<p class="muted">Ще немає usage.</p>'}</article></div>`;
  } else if (state.platformSection === "clients" && state.platformClientId) {
    const client=data.client;
    target.innerHTML = `<button id="backToClients">← До списку клієнтів</button><div class="client-profile card panel"><div class="row between"><div><div class="eyebrow">Клієнт #${client.id}</div><h2>${esc(client.display_name||client.username)}</h2><p class="muted">${esc(client.email||client.username)}</p></div><span class="pill ${client.active?"ready":"failed"}">${client.active?"Активний":"Вимкнений"}</span></div>
    <div class="platform-detail-grid">${[
      ["Дата реєстрації",platformDate(client.created_at)],["Останній вхід",platformDate(client.last_login_at)],
      ["Кількість входів",client.login_count],["Остання активність",platformDate(client.last_seen_at)],
      ["Джерело",client.registration_source],["Referral code",client.referral_code||"—"],
      ["UTM source",client.utm_source||"—"],["AI usage",`${client.usage_operations} · ${money(client.ai_cost)}`],
      ["Ідеї",data.content_totals.ideas],["Чернетки",data.content_totals.drafts],
      ["Публікації",data.content_totals.published],
    ].map(([label,value])=>`<div><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`).join("")}</div></div>
    <div class="platform-grid"><article class="card panel"><h2>Компанії</h2>${data.companies.map(row=>`<div class="usage-row"><span><strong>${esc(row.name)}</strong><small class="muted" style="display:block">${esc(row.role)} · ${row.workspace_count||0} workspace · ${row.user_count||0} корист.</small></span><button data-company="${row.id}">Деталі</button></div>`).join("")||'<p class="muted">Компаній не створено.</p>'}<h3>Ролі у workspace</h3>${data.workspaces.map(row=>`<div class="usage-row"><span><strong>${esc(row.name)}</strong><small class="muted" style="display:block">${esc(row.role)} · ${row.draft_count||0} чернеток</small></span></div>`).join("")||'<p class="muted">Workspace не створено.</p>'}</article>
    <article class="card panel"><h2>Timeline активності</h2>${data.activity.slice(0,20).map(row=>`<div class="timeline-row"><span></span><div><strong>${esc(auditActionLabel(row.action))}</strong><small>${platformDate(row.created_at)} · ${esc(row.organization_name||"Без workspace")}</small><p>${esc(row.details||"")}</p></div></div>`).join("")||'<p class="muted">Подій ще немає.</p>'}</article></div>`;
    document.querySelector("#backToClients").onclick=()=>openPlatformSection("clients");
    document.querySelectorAll("[data-company]").forEach(button=>button.onclick=()=>openPlatformSection("companies",{companyId:Number(button.dataset.company)}));
  } else if (state.platformSection === "clients") {
    const query=new URLSearchParams(location.search);
    target.innerHTML = `<form class="platform-filters" id="clientFilters"><input name="search" placeholder="Email, ім’я або компанія" value="${esc(query.get("search")||"")}"><select name="source"><option value="">Усі джерела</option><option value="referral" ${query.get("source")==="referral"?"selected":""}>Referral</option><option value="direct" ${query.get("source")==="direct"?"selected":""}>Direct</option></select><select name="period"><option value="">Весь період</option><option value="7d" ${query.get("period")==="7d"?"selected":""}>7 днів</option><option value="30d" ${query.get("period")==="30d"?"selected":""}>30 днів</option></select><select name="workspace"><option value="">Будь-який workspace</option><option value="yes" ${query.get("workspace")==="yes"?"selected":""}>Є workspace</option><option value="no" ${query.get("workspace")==="no"?"selected":""}>Без workspace</option></select><button class="primary">Застосувати</button></form>
    ${bulkBar("platform-clients",[["export","Експорт"],["deactivate","Деактивувати","danger"]])}${data.clients.length?`<div class="table-wrap card"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="platform-clients"></th><th>${sortHeader("display_name","Клієнт","platform-clients",()=>loadPlatformSection(true))}</th><th>${sortHeader("created_at","Реєстрація","platform-clients",()=>loadPlatformSection(true))}</th><th>${sortHeader("last_login_at","Останній вхід","platform-clients",()=>loadPlatformSection(true))}</th><th>${sortHeader("company_count","Компанії","platform-clients",()=>loadPlatformSection(true))}</th><th>${sortHeader("workspace_count","Workspace","platform-clients",()=>loadPlatformSection(true))}</th><th>Джерело</th><th>${sortHeader("ai_cost","Витрати","platform-clients",()=>loadPlatformSection(true))}</th><th></th></tr></thead><tbody>${data.clients.map(row=>`<tr><td>${selectionCheckbox("platform-clients",row.id)}</td><td><strong>${esc(row.display_name||row.username)}</strong><small>${esc(row.email||row.username)}</small></td><td>${platformDate(row.created_at)}</td><td>${platformDate(row.last_login_at)}</td><td>${row.company_count}<small>${esc(row.primary_company_name)}</small></td><td>${row.workspace_count}</td><td>${esc(row.registration_source)}<small>${esc(row.referral_code||"")}</small></td><td>${money(row.ai_cost)}</td><td><button data-client="${row.id}">Профіль</button></td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Клієнтів ще немає","Нові реєстрації з’являться в цьому розділі.")}${pagination(data,"platform-clients",()=>loadPlatformSection(true))}`;
    document.querySelector("#clientFilters").onsubmit=async event=>{event.preventDefault();const params=new URLSearchParams(new FormData(event.currentTarget));for(const [key,value] of [...params])if(!value)params.delete(key);history.pushState({view:"platform"},"",`${basePath}/platform/clients${params.size?`?${params}`:""}`);state.platformData.clients=null;await loadPlatformSection(true);};
    document.querySelectorAll("[data-client]").forEach(button=>button.onclick=()=>openPlatformSection("clients",{clientId:Number(button.dataset.client)}));
  } else if (state.platformSection === "companies" && state.platformCompanyId) {
    const company=data.company;
    const roleLabels={owner:roleLabel("owner"),admin:roleLabel("admin"),member:roleLabel("member"),content_manager:roleLabel("content_manager"),editor:roleLabel("editor"),publisher:roleLabel("publisher"),viewer:roleLabel("viewer")};
    target.innerHTML=`<button id="backToCompanies">← До списку компаній</button>
    <article class="card panel client-profile"><div class="row between"><div><div class="eyebrow">Компанія #${company.id}</div><h2>${esc(company.name)}</h2><p class="muted">${esc(company.slug)} · створено ${platformDate(company.created_at)}</p></div><span class="pill ${company.active?"ready":"failed"}">${company.active?"Активна":"Вимкнена"}</span></div>
    <div class="platform-detail-grid">${[["Власник",company.owner_name||"—"],["Email власника",company.owner_email||"—"],["Workspace",company.workspace_count],["Користувачі",company.user_count],["Чернетки",company.draft_count],["Заплановано",company.scheduled_count],["Опубліковано",company.published_count],["AI-витрати",money(company.ai_cost)],["Остання активність",platformDate(company.last_activity_at)]].map(([label,value])=>`<div><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`).join("")}</div></article>
    <article class="card panel"><h2>Workspace компанії</h2>${data.workspaces.length?`<div class="table-wrap"><table class="users-table"><thead><tr><th>Workspace</th><th>Команда</th><th>Тариф</th><th>Контент</th><th>AI-витрати</th><th>Остання активність</th></tr></thead><tbody>${data.workspaces.map(row=>`<tr><td><strong>${esc(row.name)}</strong><small>${esc(row.slug)}</small></td><td>${row.user_count}/${row.max_users}</td><td>${esc(row.plan_code||"custom")}</td><td>${row.draft_count} / ${row.scheduled_count} / ${row.published_count}<small>чернетки / план / публікації</small></td><td>${money(row.ai_cost)}</td><td>${platformDate(row.last_activity_at)}</td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Workspace ще немає","Перший workspace з’явиться після реєстрації або створення власником.")}</article>
    <article class="card panel"><h2>Користувачі та ролі</h2>${data.users.length?`<div class="table-wrap"><table class="users-table"><thead><tr><th>ПІБ / акаунт</th><th>Company role</th><th>Ролі у workspace</th><th>Останній вхід</th><th>Входів</th><th>Статус</th></tr></thead><tbody>${data.users.map(row=>`<tr><td><strong>${esc(row.display_name||row.username)}</strong><small>${esc(row.email||row.username)}</small></td><td>${esc(roleLabels[row.company_role]||row.company_role)}</td><td>${row.workspace_roles.length?row.workspace_roles.map(item=>`<span class="role-assignment"><strong>${esc(item.workspace_name)}</strong>: ${esc(roleLabels[item.role]||item.role)}</span>`).join(""):"Немає доступу"}</td><td>${platformDate(row.last_login_at)}</td><td>${row.login_count||0}</td><td>${row.active?"Активний":"Вимкнений"}</td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Користувачів ще немає","Учасники компанії з’являться тут.")}</article>
    <article class="card panel"><h2>Остання активність компанії</h2>${data.activity.slice(0,30).map(row=>`<div class="timeline-row"><span></span><div><strong>${esc(auditActionLabel(row.action))}</strong><small>${platformDate(row.created_at)} · ${esc(row.display_name||row.username||"Система")} · ${esc(row.organization_name||"Без workspace")}</small><p>${esc(plain(row.details||""))}</p></div></div>`).join("")||'<p class="muted">Подій ще немає.</p>'}</article>`;
    document.querySelector("#backToCompanies").onclick=()=>openPlatformSection("companies");
  } else if (state.platformSection === "companies") {
    target.innerHTML = `${bulkBar("platform-companies",[["export","Експорт"],["deactivate","Деактивувати","danger"]])}${data.companies.length?`<div class="table-wrap card"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="platform-companies"></th><th>${sortHeader("name","Компанія","platform-companies",()=>loadPlatformSection(true))}</th><th>Власник</th><th>${sortHeader("created_at","Створено","platform-companies",()=>loadPlatformSection(true))}</th><th>${sortHeader("workspace_count","Workspace","platform-companies",()=>loadPlatformSection(true))}</th><th>${sortHeader("user_count","Люди","platform-companies",()=>loadPlatformSection(true))}</th><th>Ролі</th><th>Контент</th><th>${sortHeader("ai_cost","AI-витрати","platform-companies",()=>loadPlatformSection(true))}</th><th></th></tr></thead><tbody>${data.companies.map(row=>`<tr><td>${selectionCheckbox("platform-companies",row.id)}</td><td><strong>${esc(row.name)}</strong><small>${esc(row.slug)}</small></td><td>${esc(row.owner_name||"—")}<small>${esc(row.owner_email||"")}</small></td><td>${platformDate(row.created_at)}</td><td>${row.workspace_count}/${row.max_workspaces}</td><td>${row.user_count}</td><td><small>Власники: ${row.role_counts.owner||0} · Адміни: ${row.role_counts.admin||0} · Учасники: ${row.role_counts.member||0}</small></td><td>${row.draft_count} / ${row.scheduled_count} / ${row.published_count}<small>чернетки / план / публікації</small></td><td>${money(row.ai_cost)}</td><td><button data-company-detail="${row.id}">Деталі</button></td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Компаній ще немає","Зареєстровані клієнтські компанії з’являться тут.")}${pagination(data,"platform-companies",()=>loadPlatformSection(true))}`;
    document.querySelectorAll("[data-company-detail]").forEach(button=>button.onclick=()=>openPlatformSection("companies",{companyId:Number(button.dataset.companyDetail)}));
  } else if (state.platformSection === "users") {
    target.innerHTML = `${bulkBar("platform-users",[["export","Експорт"],["deactivate","Деактивувати","danger"]])}${data.users.length?`<div class="table-wrap card"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="platform-users"></th><th>${sortHeader("display_name","Користувач","platform-users",()=>loadPlatformSection(true))}</th><th>${sortHeader("created_at","Реєстрація","platform-users",()=>loadPlatformSection(true))}</th><th>${sortHeader("last_login_at","Останній вхід","platform-users",()=>loadPlatformSection(true))}</th><th>Email verified</th><th>${sortHeader("company_count","Компанії","platform-users",()=>loadPlatformSection(true))}</th><th>${sortHeader("workspace_count","Workspace","platform-users",()=>loadPlatformSection(true))}</th><th>Основна роль</th><th>Джерело</th><th>Статус</th></tr></thead><tbody>${data.users.map(row=>`<tr><td>${selectionCheckbox("platform-users",row.id)}</td><td><strong>${esc(row.display_name||row.username)}</strong><small>${esc(row.email||row.username)}</small></td><td>${platformDate(row.created_at)}</td><td>${platformDate(row.last_login_at)}</td><td>${row.email_verified?"Так":"Ні"}</td><td>${row.company_count}<small>${esc(row.primary_company_name||"")}</small></td><td>${row.workspace_count}</td><td>${esc(row.company_role||row.role||"—")}</td><td>${esc(row.registration_source)}</td><td>${row.active?"Активний":"Вимкнений"}</td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Користувачів ще немає","Нові акаунти з’являться тут.")}${pagination(data,"platform-users",()=>loadPlatformSection(true))}`;
  } else if (state.platformSection === "referrals") {
    target.innerHTML = `${bulkBar("platform-referrals",[["export","Експорт"],["deactivate","Вимкнути","danger"]])}<div class="platform-grid"><article class="card panel"><h2>Реферальні посилання</h2>${data.codes.length?`<div class="table-wrap"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="platform-referrals"></th><th>${sortHeader("code","Код","platform-referrals",()=>loadPlatformSection(true))}</th><th>${sortHeader("owner_username","Власник","platform-referrals",()=>loadPlatformSection(true))}</th><th>Компанія</th><th>${sortHeader("clicks","Переходи","platform-referrals",()=>loadPlatformSection(true))}</th><th>${sortHeader("signups","Реєстрації","platform-referrals",()=>loadPlatformSection(true))}</th><th>${sortHeader("status","Статус","platform-referrals",()=>loadPlatformSection(true))}</th></tr></thead><tbody>${data.codes.map(row=>`<tr><td>${selectionCheckbox("platform-referrals",row.id)}</td><td class="masked">${esc(row.code)}</td><td>${esc(row.owner_display_name||row.owner_username)}</td><td>${esc(row.owner_organization_name||"—")}</td><td>${row.clicks}</td><td>${row.signups}</td><td>${esc(row.status)}</td></tr>`).join("")}</tbody></table></div>`:platformEmpty("Поки немає реферальних посилань","Посилання з’являться після відкриття реферального блоку користувачами.")}</article>
    <article class="card panel"><h2>Реферальні реєстрації</h2>${data.signups.map(row=>`<div class="usage-row"><span><strong>${esc(row.new_email||row.new_username)}</strong><small class="muted" style="display:block">Запросив: ${esc(row.referrer_username)} · ${esc(row.utm_source||"direct")}</small></span><small>${platformDate(row.created_at)}</small></div>`).join("")||platformEmpty("Поки немає реферальних реєстрацій","Коли користувачі зареєструються за посиланням, вони з’являться тут.")}</article></div>${pagination(data,"platform-referrals",()=>loadPlatformSection(true))}`;
  } else if (state.platformSection === "activity") {
    target.innerHTML = `${bulkBar("platform-activity",[["export","Експорт"]])}<div class="platform-grid"><article class="card panel"><div class="row between"><h2>Події платформи</h2><div class="mini-sort">${sortHeader("created_at","Дата","platform-activity",()=>loadPlatformSection(true))}${sortHeader("action","Подія","platform-activity",()=>loadPlatformSection(true))}</div></div>${data.events.map(row=>`<div class="timeline-row selectable-row">${selectionCheckbox("platform-activity",row.id)}<div><strong>${esc(auditActionLabel(row.action))}</strong><small>${platformDate(row.created_at)} · ${esc(row.display_name||row.username||"Система")} · ${esc(row.organization_name||"Без workspace")}</small><p>${esc(plain(row.details||""))}</p></div></div>`).join("")||'<p class="muted">Подій ще немає.</p>'}</article><article class="card panel"><h2>Останні входи</h2>${data.logins.map(row=>`<div class="usage-row"><span><strong>${esc(row.display_name||row.username||"Невідомий користувач")}</strong><small class="muted" style="display:block">${esc(row.organization_name||"Без workspace")} · ${platformDate(row.created_at)}</small></span><span class="${row.success?"success-text":"danger-text"}">${row.success?"Успішно":"Помилка"}</span></div>`).join("")||'<p class="muted">Входів ще немає.</p>'}</article></div>${pagination(data,"platform-activity",()=>loadPlatformSection(true))}`;
  } else {
    const report=data;
    target.innerHTML = `<div class="filters platform-periods">${[["today","Сьогодні"],["7d","7 днів"],["month","Місяць"],["all","Весь час"]].map(([value,label])=>`<button class="${state.platformPeriod===value?"active":""}" data-platform-expense-period="${value}">${label}</button>`).join("")}</div><div class="platform-metric-grid">${[["Загальні витрати",money(report.totals.cost)],["Операції",report.totals.operations],["Тексти",report.totals.text_generations],["Зображення",report.totals.image_generations]].map(([label,value])=>`<article class="card metric"><span>${label}</span><strong>${value}</strong></article>`).join("")}</div><div class="table-wrap card"><table class="users-table"><thead><tr><th>${sortHeader("company_name","Компанія","platform-expenses",()=>loadPlatformSection(true))}</th><th>${sortHeader("workspace_count","Workspace","platform-expenses",()=>loadPlatformSection(true))}</th><th>${sortHeader("operations","Операції","platform-expenses",()=>loadPlatformSection(true))}</th><th>${sortHeader("text_generations","Тексти","platform-expenses",()=>loadPlatformSection(true))}</th><th>${sortHeader("image_generations","Зображення","platform-expenses",()=>loadPlatformSection(true))}</th><th>${sortHeader("cost","Витрати","platform-expenses",()=>loadPlatformSection(true))}</th></tr></thead><tbody>${report.companies.map(row=>`<tr><td><strong>${esc(row.company_name||row.organization_name)}</strong></td><td>${row.workspace_count||0}</td><td>${row.operations}</td><td>${row.text_generations}</td><td>${row.image_generations}</td><td>${money(row.cost)}</td></tr>`).join("")}</tbody></table></div>${pagination(report,"platform-expenses",()=>loadPlatformSection(true))}`;
    document.querySelectorAll("[data-platform-expense-period]").forEach(button=>button.onclick=async()=>{state.platformPeriod=button.dataset.platformExpensePeriod;state.platformData.expenses=null;await loadPlatformSection(true);});
  }
  for(const key of ["platform-clients","platform-companies","platform-users","platform-referrals","platform-activity"]){
    bindSelection(key,target,renderPlatform);
  }
  target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runPlatformBulk(button.dataset.bulkAction));
  target.querySelectorAll("[data-clear-selection]").forEach(button=>button.onclick=()=>{for(const key of Object.keys(state.selected).filter(x=>x.startsWith("platform-")))selected(key).clear();renderPlatform();});
  localizeDom(target);
}
async function runPlatformBulk(action){
  const key=`platform-${state.platformSection}`;
  const ids=[...selected(key)].map(Number);
  if(action==="export"){chooseExport((state.platformData[state.platformSection]?.items||[]),state.platformSection);return;}
  if(!ids.length)return;
  if(action==="deactivate"&&!confirm(`Деактивувати ${ids.length} записів?`))return;
  await api(`api/platform/bulk/${state.platformSection}`,{method:"POST",body:JSON.stringify({ids,action,value:""})});selected(key).clear();state.platformData[state.platformSection]=null;toast("Статус оновлено");await loadPlatformSection(true);
}
function flattenExportValue(value) {
  if (Array.isArray(value)) return value.map(flattenExportValue).join("; ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}
function downloadExport(rows, name, format = "csv", fields = null) {
  if (!rows.length) return toast(t("noExportData"), true);
  const keys = fields || Object.keys(rows[0]);
  const normalizedName = String(name || "export").replace(/\.(csv|xls|xlsx)$/i, "");
  let blob;
  let filename;
  if (format === "excel") {
    const html = `<!doctype html><html><head><meta charset="utf-8"></head><body><table><thead><tr>${keys.map(key=>`<th>${esc(key)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${keys.map(key=>`<td>${esc(flattenExportValue(row[key]))}</td>`).join("")}</tr>`).join("")}</tbody></table></body></html>`;
    blob = new Blob(["\ufeff", html], {type:"application/vnd.ms-excel;charset=utf-8"});
    filename = `${normalizedName}.xls`;
  } else {
    const cell = value => `"${flattenExportValue(value).replaceAll('"','""')}"`;
    const csv = [keys.join(","), ...rows.map(row => keys.map(key => cell(row[key])).join(","))].join("\n");
    blob = new Blob(["\ufeff", csv], {type:"text/csv;charset=utf-8"});
    filename = `${normalizedName}.csv`;
  }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}
function chooseExport(rows, name, fields = null) {
  if (!rows.length) return toast(t("noExportData"), true);
  showForm(
    t("chooseExport"),
    `<div class="wide export-choice-grid">
      <button type="button" data-export-format="csv"><span class="file-icon csv">CSV</span><strong>${t("exportCsv")}</strong><small>Легкий текстовий формат для таблиць і CRM.</small></button>
      <button type="button" data-export-format="excel"><span class="file-icon excel">XLS</span><strong>${t("exportExcel")}</strong><small>Відкривається напряму в Microsoft Excel.</small></button>
    </div>`,
    null,
  );
  document.querySelectorAll("[data-export-format]").forEach(button => button.onclick = () => {
    document.querySelector("#formOverlay").hidden = true;
    downloadExport(rows, name, button.dataset.exportFormat, fields);
  });
}

function renderSettings() {
  const target = document.querySelector("#settingsContent");
  const settings = state.company.settings || {};
  if (state.settingsTab === "workspace") {
    const currentCompanyId=Number(state.company.company?.id||state.company.company_id||0);
    const companyWorkspaces=(state.me.workspaces||[]).filter(item=>Number(item.company_id)===currentCompanyId).length||Number(state.company.company?.workspace_count||1);
    const isSystemWorkspace=Number(state.company.id)===1;
    const canDeleteWorkspace=(state.me.is_super_admin||state.me.role==="owner")&&!isSystemWorkspace&&companyWorkspaces>1;
    const deleteHint=isSystemWorkspace
      ?"Цей workspace зберігає системні дані платформи, тому його не можна видалити напряму. Перейдіть в інший workspace цієї компанії та видаліть його там."
      : companyWorkspaces>1
        ?"Це назавжди видалить контент, файли, налаштування й доступи поточного workspace."
        :"Не можна видалити єдиний workspace компанії. Спочатку створіть інший workspace.";
    const quota=state.company.quota_state||{};
    target.innerHTML = `<article class="card settings-card"><div class="row"><span class="workspace-logo">${workspaceAvatarMarkup({...state.company,workspace_avatar_asset_id:state.company.settings?.workspace_avatar_asset_id})}</span><div><h2 style="margin:0">${esc(state.company.name)}</h2><span class="muted">${esc(state.company.slug)}</span></div></div><div class="analytics-metrics" style="margin-top:20px"><div class="card metric"><span>Тариф</span><strong>${esc(state.company.plan_code||"custom")}</strong></div><div class="card metric"><span>Користувачі</span><strong>${state.company.user_count}/${state.company.max_users}</strong></div><div class="card metric"><span>Тексти</span><strong>${quotaLabel(quota.text?.used ?? state.company.text_generation_count, quota.text?.limit ?? state.company.monthly_text_generations)}</strong></div><div class="card metric"><span>Зображення</span><strong>${quotaLabel(quota.image?.used ?? state.company.image_generation_count, quota.image?.limit ?? state.company.monthly_image_generations)}</strong></div><div class="card metric"><span>Публікації</span><strong>${quotaLabel(state.company.publication_count,state.company.monthly_publications)}</strong></div></div><button id="restartOnboarding">Повторити onboarding</button></article>
      <article class="card settings-card danger-settings"><div><div class="eyebrow">Небезпечна зона</div><h2>Видалення workspace</h2><p class="muted">${deleteHint}</p></div><button class="danger" id="deleteCurrentWorkspace" ${canDeleteWorkspace?"":"disabled"}>Видалити workspace</button></article>`;
  }
  else if (state.settingsTab === "mode") target.innerHTML = `<article class="card settings-card"><div class="eyebrow">Загальні</div><h2>Режим роботи workspace</h2><p class="muted">Оберіть, як ваша команда працює з контентом.</p><div class="mode-grid"><label class="card panel"><input type="radio" name="workspaceMode" value="pipeline" ${settings.workspace_mode==="pipeline"?"checked":""}> <strong>Редакційний pipeline</strong><p class="muted">Послідовний процес: ідеї → план → чернетки → календар.</p></label><label class="card panel"><input type="radio" name="workspaceMode" value="kanban" ${settings.workspace_mode==="kanban"?"checked":""}> <strong>Контент-дошка Kanban</strong><p class="muted">Усі матеріали за статусами на одній дошці.</p></label></div><button class="primary" id="saveWorkspaceMode">Зберегти режим</button></article>`;
  else if (state.settingsTab === "users") {
    const query = new URLSearchParams(location.search);
    const data=pagedData("users","api/users",{sort:query.get("sort")||"",direction:query.get("direction")||""},renderSettings);
    if(!data){target.innerHTML='<span class="skeleton"></span>';return;}
    const rows=data.items||[];
    target.innerHTML=`<article class="card settings-card"><div class="row between"><div><h2 style="margin:0">Користувачі workspace</h2><p class="muted">Запрошуйте команду та призначайте зрозумілі ролі.</p></div>${can("users.invite")?'<button class="primary" id="inviteUser">＋ Запросити користувача</button>':""}</div>${bulkBar("users",[["role","Змінити роль"],["deactivate","Деактивувати"],["remove","Видалити з workspace","danger"]])}<div class="table-wrap"><table class="users-table"><thead><tr><th><input type="checkbox" data-select-all="users" aria-label="Обрати всіх"></th><th>${sortHeader("display_name","Користувач","users",renderSettings)}</th><th>${sortHeader("role","Роль","users",renderSettings)}</th><th>${sortHeader("status","Статус","users",renderSettings)}</th><th></th></tr></thead><tbody>${rows.map(x=>`<tr><td>${selectionCheckbox("users",x.id)}</td><td><strong>${esc(x.display_name||x.username)}</strong><small>${esc(x.email||x.username)}</small></td><td>${esc(x.role||"editor")}</td><td>${x.active?"Активний":"Вимкнений"}</td><td>${can("users.invite")?`<button data-reset-user="${x.id}">Reset link</button>`:""}</td></tr>`).join("")}</tbody></table></div>${pagination(data,"users",renderSettings)}</article>`;
    bindSelection("users",target,renderSettings);target.querySelector("[data-clear-selection]")?.addEventListener("click",()=>{selected("users").clear();renderSettings();});
    target.querySelectorAll("[data-bulk-action]").forEach(button=>button.onclick=()=>runUserBulk(button.dataset.bulkAction));
  }
  else if (state.settingsTab === "roles") {
    if(!state.roles){target.innerHTML='<span class="skeleton"></span>';api("api/roles").then(data=>{state.roles=data;renderSettings();}).catch(error=>toast(error.message,true));return;}
    target.innerHTML=`<article class="card settings-card"><div class="eyebrow">Права доступу</div><h2>Ролі workspace</h2><p class="muted">Platform Admin є окремою платформною роллю. Ролі нижче діють лише всередині поточного workspace. Наведіть курсор або сфокусуйте право, щоб побачити пояснення.</p><div class="roles-list">${state.roles.items.map(role=>`<details class="role-card"><summary><span><strong>${esc(role.label)}</strong><small>${esc(role.description)}</small></span><span>${role.user_count} корист. · ${role.permissions.length} прав</span></summary><div class="permission-grid">${(role.permission_details||role.permissions.map(key=>({key,label:key,description:key}))).map(permission=>`<span class="permission-chip" tabindex="0" data-tooltip="${esc(permission.description)}" aria-label="${esc(`${permission.label}. ${permission.description}`)}"><strong>${esc(permission.label)}</strong><small>${esc(permission.key)}</small></span>`).join("")}</div></details>`).join("")}</div></article>`;
  }
  else if (state.settingsTab === "billing") {
    if(!state.plans){target.innerHTML='<span class="skeleton"></span>';api("api/plans").then(data=>{state.plans=data;renderSettings();}).catch(error=>toast(error.message,true));return;}
    const expires = state.plans.expires_at ? formatDate(state.plans.expires_at, "") : "";
    target.innerHTML=`<article class="card settings-card pricing-panel"><div class="row between"><div><div class="eyebrow">Тарифи</div><h2>Оберіть план для workspace</h2><p class="muted">Публікації, користувачі, канали та генерації контролюються на рівні поточного workspace.</p></div><span class="pill ready">Поточний: ${esc(state.plans.current_plan||state.company.plan_code||"custom")}${expires?` · до ${esc(expires)}`:""}</span></div><div class="pricing-grid">${state.plans.plans.map(plan=>{const current=(state.plans.current_plan||state.company.plan_code)===plan.code;return `<article class="price-card ${plan.popular?"popular":""} ${current?"current":""}">${plan.popular?'<span class="popular-label">Найпопулярніший</span>':""}<h3>${esc(plan.name)}</h3><p class="tagline">${esc(plan.tagline)}</p><div class="price"><strong>${Number(plan.stars).toLocaleString(state.locale === "en" ? "en-US" : "uk-UA")} ★</strong><span>/ 30 днів</span></div><div class="plan-limits"><div class="plan-limit"><strong>${plan.publications}</strong><span>публікацій</span></div><div class="plan-limit"><strong>${plan.text_generations}</strong><span>текстів</span></div><div class="plan-limit"><strong>${plan.image_generations}</strong><span>зображень</span></div><div class="plan-limit"><strong>${plan.users}</strong><span>користувачів</span></div><div class="plan-limit"><strong>${plan.channels}</strong><span>каналів</span></div></div><ul class="plan-features">${(plan.features||[]).map(item=>`<li>${esc(item)}</li>`).join("")}</ul>${current?'<button disabled class="current-plan">Поточний тариф</button>':`<button class="${plan.popular?"success":"primary"}" data-buy-plan="${esc(plan.code)}" ${can("billing.manage")?"":"disabled"}>${can("billing.manage")?"Оплатити в Telegram":"Доступно власнику"}</button>`}</article>`}).join("")}</div><div class="billing-note"><strong>Оплата через Telegram Stars</strong><span>Після оплати ліміти оновляться автоматично після підтвердження платежу.</span></div></article>`;
  }
  else if (state.settingsTab === "referral") {
    const referral = state.referral || {};
    const disabled = referral.status === "disabled";
    target.innerHTML = `<article class="card settings-card"><div class="eyebrow">Реферальна програма</div><h2>Запрошуйте нових користувачів</h2><p class="muted">Поділіться персональним посиланням. Тут відображається лише ваша статистика в поточному workspace.</p><div class="referral-link"><input id="referralUrl" readonly value="${esc(referral.url||"")}"><button id="copyReferral" ${disabled?"disabled":""}>Скопіювати посилання</button></div>${disabled?'<div class="callout warning"><strong>Посилання вимкнено</strong><p>Оновіть код, щоб знову приймати реферальні переходи.</p></div>':""}<div class="analytics-metrics" style="margin-top:18px"><div class="card metric"><span>Переходи</span><strong>${Number(referral.clicks||0)}</strong></div><div class="card metric"><span>Реєстрації</span><strong>${Number(referral.signups||0)}</strong></div><div class="card metric"><span>Активні клієнти</span><strong>${Number(referral.active_clients||0)}</strong></div><div class="card metric"><span>Статус</span><strong style="font-size:18px">${disabled?"Вимкнено":"Активне"}</strong></div></div><div class="row"><button id="rotateReferral">Оновити код</button><button class="danger" id="disableReferral" ${disabled?"disabled":""}>Вимкнути посилання</button></div></article>`;
  }
  else if (state.settingsTab === "integrations") {
    if(!state.instagramIntegration){target.innerHTML='<span class="skeleton"></span>';api("api/integrations/instagram/status").then(data=>{state.instagramIntegration=data;renderSettings();}).catch(error=>toast(error.message,true));return;}
    const ig = state.instagramIntegration;
    const connected = ig.connected && ig.connection;
    target.innerHTML = `<div class="integrations-stack"><article class="card settings-card integration-card"><div class="integration-head"><div class="integration-title">${socialLogo("telegram")}<div><div class="eyebrow">Telegram</div><h2>Підключення каналу</h2><p class="muted">1. Створіть бота через @BotFather. 2. Додайте його адміністратором каналу. 3. Вкажіть @username каналу та token.</p></div></div><span class="integration-status ${state.company.telegram?.connected?"success":""}">${state.company.telegram?.connected?"Підключено":"Не підключено"}</span></div><div class="form-grid"><label>Channel username<input id="telegramChannel" placeholder="@company_channel" value="${esc(state.company.telegram?.channel_id||"")}"><small class="field-help">Канал має бути публічним або доступним боту.</small></label><label>Bot token<input id="telegramToken" type="password" placeholder="123456789:AA..."><small class="field-help">Token зберігається зашифрованим і не показується повторно.</small></label></div><div class="connection-status ${state.company.telegram?.connected?"success":""}" id="telegramStatus">${state.company.telegram?.connected?`Підключено: @${esc(state.company.telegram.bot_username||"bot")}`:"Введіть дані для автоматичної перевірки."}</div><div class="row" style="margin-top:14px"><button id="testTelegram">Перевірити підключення</button><button class="primary" id="saveTelegram">Перевірити та зберегти</button></div></article>
    <article class="card settings-card integration-card instagram-card"><div class="integration-head"><div class="integration-title">${socialLogo("instagram")}<div><div class="eyebrow">Instagram</div><h2>Instagram Feed</h2><p class="muted">Публікуйте готові візуальні пости у Instagram Feed. Reels і Carousel вже закладені в інтерфейс, але будуть увімкнені після окремого медіа-модуля.</p></div></div><span class="integration-status ${connected?"success":ig.setup_required?"warning":""}">${connected?"Підключено":ig.setup_required?"Потрібен Meta App":"Готово до підключення"}</span></div>${connected?`<div class="connected-account"><strong>@${esc(ig.connection.username||ig.connection.external_account_id)}</strong><span>${esc(ig.connection.page_name||"Facebook Page")} · ${esc(ig.connection.account_type||"Business")}</span>${ig.connection.last_error?`<small class="danger-text">${esc(ig.connection.last_error)}</small>`:""}</div>`:ig.setup_required?`<div class="callout warning"><strong>Instagram ще не активовано на платформі</strong><p>Додайте META_APP_ID, META_APP_SECRET, PUBLIC_APP_URL/META_REDIRECT_URI та увімкніть INSTAGRAM_ENABLED. Telegram працює без змін.</p><small class="muted">Бракує: ${esc((ig.missing||[]).join(", ")||"Meta credentials")}</small></div>`:`<div class="callout"><strong>Потрібен Instagram Business або Creator</strong><p>Підключення відбувається через Facebook Login і прив’язану Facebook Page.</p></div>`}<div class="capability-grid"><span class="capability active">Feed image</span><span class="capability soon">Reels скоро</span><span class="capability soon">Carousel скоро</span></div><div class="row" style="margin-top:14px">${connected?`<button class="danger" id="disconnectInstagram">Відключити Instagram</button>`:`<button class="primary" id="connectInstagram" ${ig.setup_required?"disabled":""}>Підключити Instagram</button>`}</div></article>
    <article class="card settings-card integration-card"><div class="eyebrow">Скоро з’являться</div><h2>Більше соцмереж</h2><p class="muted">Ми готуємо публікації в інші канали без dead controls: картки нижче лише показують roadmap.</p><div class="soon-grid">${(ig.soon||[]).map(item=>`<div class="soon-card">${socialLogo(item.platform)}<strong>${esc(item.label)}</strong><span>Скоро</span></div>`).join("")}</div></article></div>`;
  }
  else target.innerHTML = `<article class="card settings-card"><h2>Безпека</h2><p class="muted">Змініть пароль або створіть одноразове посилання через адміністратора workspace.</p><div class="form-grid"><label>Новий пароль<input id="ownPassword" type="password" minlength="10"></label></div><button class="primary" id="changePassword" style="margin-top:14px">Змінити пароль</button></article>`;
  bindSettingsActions();
}

async function openEditor(id, push = true) {
  try {
    const draft = await api(`api/drafts/${id}`);
    state.currentDraft = draft;
    state.currentPublishJobs = await api(`api/drafts/${id}/publish-jobs`).catch(()=>[]);
    const instagram = state.instagramIntegration || await api("api/integrations/instagram/status").catch(()=>null);
    state.instagramIntegration = instagram;
    const latestInstagramJob = (state.currentPublishJobs||[]).find(job=>job.platform==="instagram");
    const instagramConnected = instagram?.connected;
    const instagramStatus = latestInstagramJob
      ? `${statusLabel(latestInstagramJob.status)}${latestInstagramJob.permalink ? " · permalink ready" : ""}`
      : instagramConnected ? translateText("Готово до публікації у Feed") : translateText("Не підключено");
    const publishChannels = `<section class="publish-channels"><div><h3>Канали публікації</h3><p class="muted">Telegram працює як раніше. Instagram — окрема публікація, яка не змінює статус Telegram-поста.</p></div><div class="channel-grid"><article class="channel-card active">${socialLogo("telegram")}<span>Telegram</span><strong>${esc(state.company.telegram?.channel_id||"Підключений канал")}</strong><small>Кнопки «Запланувати» та «Опублікувати» зверху керують Telegram.</small></article><article class="channel-card ${instagramConnected?"active":""}">${socialLogo("instagram")}<span>Instagram Feed</span><strong>${esc(instagramStatus)}</strong><small>${latestInstagramJob?.error?esc(latestInstagramJob.error):"Одиночне зображення + caption."}</small>${instagramConnected?`<div class="row"><button type="button" id="publishInstagram" ${draft.image_path?"":"disabled title=\"Спочатку потрібен візуал\""}>Опублікувати</button><button type="button" id="scheduleInstagram" ${draft.image_path?"":"disabled title=\"Спочатку потрібен візуал\""}>Запланувати</button></div>`:`<button type="button" disabled>Підключіть Instagram</button>`}</article><article class="channel-card soon">${socialLogo("instagram")}<span>Reels</span><strong>Скоро</strong><small>Потрібен відео-модуль.</small></article><article class="channel-card soon">${socialLogo("instagram")}<span>Carousel</span><strong>Скоро</strong><small>Потрібно кілька медіа в чернетці.</small></article></div></section>`;
    if (push) {
      history.pushState(
        {draftId:id,fromView:state.view,pushed:true},
        "",
        `${basePath}/workspace/${state.me.organization_slug}/drafts/${id}`,
      );
    }
    const target = document.querySelector("#editorContent");
    target.innerHTML = `<header class="editor-header"><div class="row editor-title-row"><button id="closeEditor">←</button><div>${pill(draft.status)} <strong style="margin-left:8px">${esc(plain(draft.title))}</strong></div></div><div class="row editor-actions"><button id="regenText">Перегенерувати текст</button><button id="saveDraft">Зберегти</button><button id="scheduleDraft" ${draft.image_path?"":"disabled title=\"Спочатку потрібен візуал\""}>Запланувати</button><button class="primary" id="publishDraft" ${["ready","scheduled"].includes(draft.status)?"":"disabled title=\"Спочатку погодьте матеріал\""}>Опублікувати</button></div></header><div class="editor-grid"><form class="editor-form" id="editorForm"><div class="status-actions">${(statusActions[draft.status]||[]).map(([next,label])=>`<button type="button" data-editor-status="${next}">${label}</button>`).join("")}</div><div class="form-grid"><label>Рубрика<input value="${esc(draft.product)}" disabled></label><label>Дата і час<input id="scheduleAt" type="datetime-local" value="${localDateTimeValue(draft.scheduled_at)}"></label></div><label>Заголовок для поста<input id="editorTitle" value="${esc(decodeHtmlMarkup(draft.title))}"></label><label>Заголовок на візуалі<input id="editorVisualTitle" value="${esc(decodeHtmlMarkup(draft.visual_title||draft.title))}"><small class="muted">Без emoji та зайвих символів.</small></label><label>Текст публікації<textarea id="editorCaption" style="min-height:330px">${esc(decodeHtmlMarkup(draft.caption_html))}</textarea></label><label>Посилання<input id="editorLink" value="${esc(draft.link_url||"")}"></label>${publishChannels}<div class="row editor-secondary-actions"><button type="button" id="cancelSchedule" ${draft.status==="scheduled"?"":"hidden"}>Повернути в готові</button></div></form><aside class="editor-preview"><div class="editor-preview-card"><div class="row"><span class="workspace-logo" style="width:30px;height:30px">${initials(state.company.name)}</span><div><strong>${esc(state.company.name)}</strong><small style="display:block;color:#94a3b8">Telegram</small></div></div><img src="${apiUrl(`api/drafts/${id}/image`)}" alt="" onerror="this.style.display='none'"><h2 id="previewTitle">${esc(plain(draft.visual_title||draft.title))}</h2><div id="previewText" class="telegram-preview-text">${safeHtml(draft.caption_html)}</div></div></aside></div>`;
    document.querySelector("#editorOverlay").hidden = false;
    localizeDom(document.querySelector("#editorOverlay"));
    bindEditorActions();
  } catch (error) { toast(error.message,true); }
}
function closeEditor() {
  document.querySelector("#editorOverlay").hidden = true;
  if (routeFromLocation().draftId) {
    if (history.state?.pushed) history.back();
    else {
      state.view = history.state?.fromView || "drafts";
      updateViewUrl(state.view, {replace:true});
      setView(state.view, {push:false});
    }
  }
}

function showForm(title, fields, submit, options = {}) {
  document.querySelector("#formTitle").textContent = translateText(title);
  document.querySelector("#formBody").innerHTML = `<div class="form-grid">${fields}</div><div class="form-error" id="dynamicError"></div>`;
  document.querySelector("#formOverlay .modal").className = `modal ${options.modalClass || ""}`.trim();
  document.querySelector("#formOverlay").hidden = false;
  const form = document.querySelector("#dynamicForm");
  const submitButton = form.querySelector('button[type="submit"]');
  const cancelButton = form.querySelector("[data-close-overlay]");
  submitButton.hidden = !submit;
  submitButton.textContent = translateText(options.submitLabel || "Зберегти");
  submitButton.classList.toggle("danger", Boolean(options.danger));
  cancelButton.textContent = translateText(submit ? "Скасувати" : "Закрити");
  localizeDom(document.querySelector("#formOverlay"));
  form.onsubmit = async event => {
    event.preventDefault();
    if (!submit) return;
    cancelButton.disabled = true;
    try {
      await loading(
        submitButton,
        () => submit(new FormData(form)),
        translateText(options.loadingLabel || "Зберігаємо…"),
      );
      document.querySelector("#formOverlay").hidden=true;
    }
    catch (error) { document.querySelector("#dynamicError").textContent=error.message; }
    finally { cancelButton.disabled = false; }
  };
}
function renderWorkspaceChooser(force = false) {
  const workspaces = state.me.workspaces || [];
  if (!force && workspaces.length < 2 && !state.me.is_super_admin) return;
  document.querySelector("#workspaceGrid").innerHTML = workspaces.map(x=>{
    const current=x.id===state.me.organization_id;
    const avatar=workspaceAvatarMarkup(x);
    const companyWorkspaces=(state.me.companies||[]).find(company=>Number(company.id)===Number(x.company_id))?.workspace_count||1;
    const canDelete=(state.me.is_super_admin||x.role==="owner")&&Number(x.id)!==1&&companyWorkspaces>1;
    return `<article class="card workspace-card ${current?"active":""}">
      <div class="workspace-card-top"><span class="workspace-logo">${avatar}</span>${current?'<span class="pill ready">Активний</span>':""}</div>
      <div class="eyebrow">${esc(x.company_name||"Компанія")}</div><h3>${esc(x.name)}</h3>
      <p class="muted">${esc(x.workspace_short_description||"Окремий простір для контенту, команди та публікацій.")}</p>
      <div class="workspace-stat-grid"><span><strong>${x.user_count||0}</strong> корист.</span><span><strong>${x.channel_count||0}</strong> канал</span><span><strong>${esc(x.plan_code||"custom")}</strong> тариф</span></div>
      <div class="workspace-meta"><span>${esc(roleLabel(x.role|| (state.me.is_super_admin?"platform_admin":"member")))}</span><span>${esc(x.slug)}</span></div>
      <div class="workspace-card-actions"><button class="primary" data-workspace="${x.id}" ${current?"disabled":""}>${current?"Відкрито":"Перейти"}</button>${canDelete?`<button class="danger" data-delete-workspace="${x.id}">Видалити</button>`:""}</div>
    </article>`;
  }).join("")+`<button class="card workspace-card workspace-create" id="createWorkspace"><span class="workspace-create-icon">＋</span><strong>${state.me.is_super_admin?"Створити компанію":"Створити workspace"}</strong><small class="muted">${state.me.is_super_admin?"Компанія, перший workspace і власник":"Окремі бренд, команда, канал і календар"}</small></button>`;
  document.querySelector("#workspaceOverlay").hidden = false;
  localizeDom(document.querySelector("#workspaceOverlay"));
  document.querySelectorAll("[data-workspace]").forEach(button=>button.onclick=async()=>{await api("api/workspace/select",{method:"POST",body:JSON.stringify({organization_id:Number(button.dataset.workspace)})});location.href=`${basePath}/`;});
  document.querySelectorAll("[data-delete-workspace]").forEach(button=>button.onclick=()=>openWorkspaceDelete(Number(button.dataset.deleteWorkspace)));
  document.querySelector("#createWorkspace").onclick = () => {
    if (state.me.is_super_admin) {
      showForm(
        "Створити компанію та власника",
        `<div class="wide callout"><strong>Що відбудеться</strong><p>Буде створено порожній workspace і окремий owner-акаунт. Onboarding відкриється власнику під час першого входу, а не вам.</p></div>
        <label>Назва компанії<input name="name" required placeholder="Acme Ukraine"></label>
        <details class="wide advanced-field"><summary>Змінити URL вручну</summary><label>Slug<input name="slug" pattern="[A-Za-z0-9-]+" placeholder="acme-ukraine"><small class="field-help">Необов’язково. Якщо поле порожнє, URL буде створено автоматично.</small></label></details>
        <label>Назва першого workspace<input name="workspace_name" placeholder="Основний workspace"><small class="field-help">Компанія може мати кілька окремих workspace.</small></label>
        <label>Ім’я власника<input name="owner_display_name" required placeholder="Олена Коваль"></label>
        <label>Email власника<input name="owner_email" type="email" placeholder="owner@company.ua"></label>
        <label>Логін власника<input name="owner_username" required pattern="[A-Za-z0-9._-]+" placeholder="acme.owner"></label>
        <label>Тимчасовий пароль<input name="owner_password" type="password" minlength="10" required></label>
        <label>Ліміт користувачів<input name="max_users" type="number" min="1" max="50" value="3"></label>
        <label>Публікацій на місяць<input name="monthly_publications" type="number" min="1" value="30"></label>
        <label>Текстових генерацій<input name="monthly_text_generations" type="number" min="0" value="60"></label>
        <label>Генерацій зображень<input name="monthly_image_generations" type="number" min="0" value="30"></label>
        <label>Внутрішній AI-cost budget, $<input name="monthly_ai_budget" type="number" min="0" step="0.01" value="8"><small class="field-help">Лише для platform-аналітики витрат, не для клієнтського ліміту.</small></label>`,
        async form => {
          const created = await api("api/organizations", {method:"POST", body:JSON.stringify({
            name: form.get("name"), slug: form.get("slug"),
            workspace_name: form.get("workspace_name"),
            workspace_slug: "",
            owner_display_name: form.get("owner_display_name"),
            owner_email: form.get("owner_email") || null,
            owner_username: form.get("owner_username"),
            owner_password: form.get("owner_password"),
            max_users: Number(form.get("max_users")), max_channels: 1,
            monthly_publications: Number(form.get("monthly_publications")),
            monthly_text_generations: Number(form.get("monthly_text_generations")),
            monthly_image_generations: Number(form.get("monthly_image_generations")),
            monthly_ai_budget: Number(form.get("monthly_ai_budget")),
            max_workspaces: 10,
          })});
          state.me = await api("api/me");
          toast(`Компанію ${created.name} створено. Передайте власнику логін і тимчасовий пароль.`);
          renderWorkspaceChooser(true);
        },
        {submitLabel:"Створити компанію"},
      );
    } else {
      showForm("Створити workspace", `<div class="wide callout"><strong>${esc(state.company?.company?.name||"Поточна компанія")}</strong><p>Новий workspace матиме окремі контент, бренд, Telegram-канал, календар і ролі.</p></div><label class="wide">Назва workspace<input name="name" required><small class="field-help">URL буде створено автоматично з назви.</small></label><details class="wide advanced-field"><summary>Змінити URL вручну</summary><label>Slug<input name="slug" pattern="[A-Za-z0-9-]+"></label></details>`, async form => {await api("api/account/trial-workspace",{method:"POST",body:JSON.stringify({name:form.get("name"),slug:form.get("slug")||"",company_id:state.company?.company?.id||null})});location.href=`${basePath}/`;});
    }
  };
}

function openWorkspaceDelete(workspaceId=state.me.organization_id) {
  const workspace=(state.me.workspaces||[]).find(item=>Number(item.id)===Number(workspaceId))||state.company;
  if(!workspace)return;
  showForm(
    `Видалити «${workspace.name}»?`,
    `<div class="wide danger-zone"><div class="danger-symbol">!</div><div><strong>Усі дані буде видалено без можливості відновлення</strong><p>Зникнуть ідеї, чернетки, зображення, бренд-матеріали, календар, канал, ролі та історія цього workspace.</p></div></div>
     <label class="wide">Для підтвердження введіть точну назву: <strong>${esc(workspace.name)}</strong><input name="confirmation_name" autocomplete="off" required></label>`,
    async form=>{
      await api(`api/workspaces/${workspace.id}`,{method:"DELETE",body:JSON.stringify({confirmation_name:form.get("confirmation_name")})});
      toast(`Workspace «${workspace.name}» видалено`);
      location.href=`${basePath}/`;
    },
    {submitLabel:"Видалити назавжди",loadingLabel:"Видаляємо…",danger:true},
  );
}

function showOnboarding(step) {
  state.onboardingStep = Math.max(1,Math.min(5,step));
  const names = ["Компанія","Бренд","Канали","Рубрики","Перший план"];
  document.querySelector("#onboardingSteps").innerHTML = names.map((name,index)=>`<div class="onboarding-step ${index+1===state.onboardingStep?"active":""}">${index+1}. ${name}</div>`).join("");
  document.querySelector("#onboardingTitle").textContent = names[state.onboardingStep-1];
  document.querySelector("#onboardingBack").disabled = state.onboardingStep === 1;
  document.querySelector("#onboardingNext").textContent = state.onboardingStep === 5 ? "Завершити" : "Далі →";
  const settings = state.company.settings || {};
  const contents = {
    1:`<h2>Ласкаво просимо до Content Studio</h2><p class="muted">Налаштуйте workspace за п’ять коротких кроків. Прогрес зберігається після кожного кроку.</p><div class="progress">${[1,2,3,4,5].map(x=>`<span class="${x<=state.onboardingStep?"active":""}"></span>`).join("")}</div><div class="form-grid"><label class="wide">Назва компанії<input id="obName" value="${esc(state.company.name)}"><small class="field-help">Технічний URL система створює автоматично.</small></label></div>`,
    2:`<h2>Бренд та стиль комунікації</h2><p class="muted">Ці дані використовуються як постійний контекст для AI. Пишіть факти й правила, а не рекламні гасла.</p><div class="form-grid"><label class="wide">Опис компанії<textarea id="obDescription" placeholder="Хто ви, для кого працюєте, яку проблему вирішуєте і чим відрізняєтесь.">${esc(settings.company_description||"")}</textarea><small class="field-help">3–6 конкретних речень. Назвіть аудиторію, продукт і користь.</small></label><label class="wide">Tone of voice<textarea id="obTone" placeholder="Пишемо коротко, звертаємося на «ви», пояснюємо терміни простими словами…">${esc(settings.tone_of_voice||"")}</textarea><small class="field-help">Опишіть форму звертання, довжину, емоційність, рівень експертності та наведіть приклад.</small></label><label>Ключові послуги<textarea id="obServices" placeholder="Продукт — яку задачу вирішує">${esc(settings.key_services||"")}</textarea></label><label>Заборонені фрази<textarea id="obForbidden" placeholder="Кліше, перебільшення, небажані обіцянки">${esc(settings.forbidden_phrases||"")}</textarea></label></div>`,
    3:`<h2>Підключіть Telegram-канал</h2><p class="muted">Додайте бота адміністратором каналу. Ми перевіримо token, канал і права до збереження.</p><div class="form-grid"><label>Channel username<input id="obChannel" placeholder="@company_channel" value="${esc(state.company.telegram?.channel_id||"")}"></label><label>Bot token<input id="obToken" type="password" placeholder="123456789:AA..."></label></div><div class="connection-status" id="obTelegramStatus">Введіть обидва значення для перевірки.</div><button type="button" id="obTestTelegram" style="margin-top:12px">Перевірити зараз</button>`,
    4:`<h2>Додайте рубрики контенту</h2><p class="muted">Рубрика — це постійний напрям контенту. Для кожної вкажіть назву та поясніть, про що писати.</p><div class="rubric-builder" id="obRubricRows"></div><button type="button" id="obAddRubric">＋ Додати рубрику</button>`,
    5:`<h2>Створіть перший контент-план</h2><p class="muted">AI використає бренд-профіль і рубрики. План створиться як ідеї, які можна переглянути до генерації чернеток.</p><div class="form-grid"><label>Період<select id="obPeriod"><option value="week">Тиждень</option><option value="month">Місяць</option></select></label><label>Кількість постів<input id="obPosts" type="number" value="5" min="1" max="31"></label><label class="wide">Мета<textarea id="obFocus" placeholder="Наприклад: познайомити аудиторію з новим продуктом і зібрати заявки"></textarea></label></div>`,
  };
  document.querySelector("#onboardingBody").innerHTML = contents[state.onboardingStep];
  document.querySelector("#onboardingOverlay").hidden = false;
  localizeDom(document.querySelector("#onboardingOverlay"));
  if (state.onboardingStep === 3) bindTelegramValidation("obChannel", "obToken", "obTelegramStatus", "obTestTelegram");
  if (state.onboardingStep === 4) {
    const container = document.querySelector("#obRubricRows");
    const existing = (state.data.rubrics || []).map(row => ({name:row.name,description:row.description}));
    const addRow = (rubric = {}) => {
      const row = document.createElement("div");
      row.className = "rubric-row";
      row.innerHTML = `<label>Назва<input data-rubric-name value="${esc(rubric.name||"")}" placeholder="Експертні поради"></label><label>Що публікуємо<textarea data-rubric-description placeholder="Практичні інструкції, кейси та відповіді на часті питання.">${esc(rubric.description||"")}</textarea></label><button type="button" class="icon-button danger" data-remove-rubric aria-label="Видалити рубрику">×</button>`;
      row.querySelector("[data-remove-rubric]").onclick = () => row.remove();
      container.append(row);
    };
    (existing.length ? existing : [{name:"",description:""}]).forEach(addRow);
    document.querySelector("#obAddRubric").onclick = () => addRow();
  }
}
async function saveOnboarding() {
  const step = state.onboardingStep;
  if (step === 1) await api("api/onboarding/company",{method:"PUT",body:JSON.stringify({name:document.querySelector("#obName").value,slug:"",primary_language:"uk",brand_primary_color:"#6366f1",brand_logo_asset_id:null})});
  if (step === 2) await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:document.querySelector("#obDescription").value,tone_of_voice:document.querySelector("#obTone").value,key_services:document.querySelector("#obServices").value,forbidden_phrases:document.querySelector("#obForbidden").value,website_url:""})});
  if (step === 3 && document.querySelector("#obToken").value) await api("api/company/telegram",{method:"PUT",body:JSON.stringify({channel_id:document.querySelector("#obChannel").value,bot_token:document.querySelector("#obToken").value})});
  if (step === 4) {
    const rubrics = [...document.querySelectorAll(".rubric-row")].map(row => ({
      name: row.querySelector("[data-rubric-name]").value.trim(),
      description: row.querySelector("[data-rubric-description]").value.trim(),
    })).filter(row => row.name || row.description);
    if (!rubrics.length) throw new Error("Додайте хоча б одну рубрику");
    if (rubrics.some(row => row.name.length < 2 || row.description.length < 10)) throw new Error("Для кожної рубрики заповніть назву та опис від 10 символів");
    await api("api/onboarding/rubrics",{method:"POST",body:JSON.stringify({rubrics})});
  }
  if (step === 5) {
    await api("api/content-plan/generate",{method:"POST",body:JSON.stringify({product:"all",period:document.querySelector("#obPeriod").value,posts:Number(document.querySelector("#obPosts").value),start_date:localDateKey(new Date()),focus:document.querySelector("#obFocus").value,text_model:"gpt-5.4-mini",create_as:"ideas",rubric_slugs:[],channel_ids:[]})});
    await api("api/onboarding/complete",{method:"POST"});
    document.querySelector("#onboardingOverlay").hidden=true;
    await refresh();
    return;
  }
  await refresh();
  showOnboarding(step+1);
}

function bindViewLinks() { document.querySelectorAll("[data-open-view]").forEach(node=>node.onclick=()=>setView(node.dataset.openView)); }
const rubricTemplates = [
  ["Експертний пост","Пояснює професійну тему та демонструє експертизу.","Підвищити довіру","Експертний і зрозумілий","Що клієнт має знати перед стартом проєкту"],
  ["Кейс","Показує задачу, рішення та вимірюваний результат.","Довести цінність на практиці","Конкретний і фактологічний","Як ми скоротили час обробки звернень"],
  ["Освітній пост","Навчає аудиторію корисному підходу або інструменту.","Дати практичну користь","Доброзичливий експертний","5 помилок під час впровадження"],
  ["Новини компанії","Розповідає про зміни, події та команду.","Підтримувати контакт з аудиторією","Живий і впевнений","Запустили новий напрям"],
  ["Продажний пост","Пояснює пропозицію через проблему та користь.","Створити запит на продукт","Переконливий без тиску","Кому підійде новий пакет"],
  ["Поради клієнтам","Дає короткі рекомендації для щоденної роботи.","Підвищити корисність бренду","Практичний","Як підготувати команду до змін"],
  ["FAQ","Відповідає на типові запитання клієнтів.","Зняти заперечення","Прямий і простий","Скільки триває запуск"],
  ["Закулісся бізнесу","Показує процеси, людей та культуру.","Зробити бренд людяним","Відкритий","Як команда готує реліз"],
  ["Відгуки клієнтів","Показує досвід клієнта та результат.","Посилити соціальний доказ","Щирий","Що змінилося після впровадження"],
  ["Продуктовий пост","Розкриває функцію продукту через сценарій.","Пояснити цінність функції","Предметний","Як автоматизація економить час"],
];
function rubricFields(item={}) {
  return `<label>Назва рубрики<input name="name" required value="${esc(item.name||"")}"></label><label>Шаблон<select name="template"><option value="">З нуля</option>${rubricTemplates.map(([name])=>`<option value="${esc(name)}">${esc(name)}</option>`).join("")}</select></label><label class="wide">Опис<textarea name="description" minlength="20" required>${esc(item.description||"")}</textarea></label><label>Ціль рубрики<input name="goal" value="${esc(item.goal||"")}"></label><label>Тон комунікації<input name="tone" value="${esc(item.tone||"")}"></label><label class="wide">Приклад теми<input name="example_topic" value="${esc(item.example_topic||"")}"></label><label class="wide">Правила для AI<textarea name="instructions">${esc(item.instructions||"")}</textarea></label><label class="check-label wide"><input name="active" type="checkbox" ${item.active===0?"":"checked"}> Активна рубрика</label>`;
}
function openRubricForm(item=null) {
  showForm(item?"Редагувати рубрику":"Створити рубрику",rubricFields(item||{}),async form=>{
    const payload={name:form.get("name"),description:form.get("description"),goal:form.get("goal"),tone:form.get("tone"),example_topic:form.get("example_topic"),instructions:form.get("instructions"),default_link:item?.default_link||"",active:form.get("active")==="on"};
    await api(item?`api/rubrics/${item.id}`:"api/rubrics",{method:item?"PUT":"POST",body:JSON.stringify(payload)});
    delete state.lists.rubrics;toast("Рубрику збережено");await refresh(true);renderBrand();
  });
  const template=document.querySelector('[name="template"]');
  template.onchange=()=>{const preset=rubricTemplates.find(([name])=>name===template.value);if(!preset)return;const form=document.querySelector("#dynamicForm");form.elements.name.value=preset[0];form.elements.description.value=preset[1];form.elements.goal.value=preset[2];form.elements.tone.value=preset[3];form.elements.example_topic.value=preset[4];};
}
async function runRubricBulk(action) {
  const ids=[...selected("rubrics")].map(Number);if(!ids.length)return;
  if(action==="delete"&&!confirm(`Видалити ${ids.length} рубрик?\nЦю дію не можна буде скасувати.`))return;
  await api("api/rubrics/bulk",{method:"POST",body:JSON.stringify({ids,action,value:""})});selected("rubrics").clear();delete state.lists.rubrics;toast("Рубрики оновлено");await refresh(true);renderBrand();
}
async function runBrandBulk(kind,action){
  const ids=[...selected(kind)];
  if(!ids.length)return;
  if(action==="delete"&&!confirm(`Видалити ${ids.length} елементів?\nЦю дію не можна буде скасувати.`))return;
  const endpoint=kind==="visuals"?"api/templates/bulk":"api/brand/materials/bulk";
  await api(endpoint,{method:"POST",body:JSON.stringify({ids,action,value:""})});selected(kind).clear();delete state.lists[kind];toast("Матеріали оновлено");await refresh(true);renderBrand();
}
function visualStyleFields(item={}) {
  return `<div class="wide callout"><strong>Як заповнювати стиль</strong><p>Пишіть не «красиво і сучасно», а конкретні правила: фон, композиція, кольори, настрій, що можна й що заборонено. AI буде використовувати ці поля як інструкцію для генерації зображень.</p></div>
  <label>Назва стилю<input name="name" required placeholder="Наприклад: Premium B2B SaaS" value="${esc(item.name||"")}"><small class="field-help">Коротка назва, за якою команда швидко зрозуміє, коли використовувати цей стиль.</small></label>
  <label>Акцентний колір<input name="accent" type="color" value="${esc(item.accent||"#6366f1")}"><small class="field-help">Основний колір, який можна використовувати у градієнтах, акцентах і декоративних елементах.</small></label>
  <label class="wide">Опис стилю<textarea name="description" minlength="5" required placeholder="Світлі фони, чисті картки, абстрактні AI-елементи, акуратні градієнти, без людей і зайвого тексту.">${esc(item.description||"")}</textarea><small class="field-help">Опишіть загальну картинку: тип фону, рівень преміальності, деталізацію, чи потрібні люди, інтерфейси, 3D, фото або ілюстрація.</small></label>
  <label class="wide">Настрій / vibe<input name="mood" placeholder="Спокійний, преміальний, технологічний, експертний" value="${esc(item.mood||"")}"><small class="field-help">2–5 прикметників, які задають емоцію. Це допомагає уникати випадкового «шумного» дизайну.</small></label>
  <label class="wide">Що використовувати<textarea name="use_rules" placeholder="Світлий фон, картки, м’які тіні, синьо-фіолетовий градієнт, мінімалістичні AI-лінії, максимум 2–3 об’єкти у кадрі.">${esc(item.use_rules||"")}</textarea><small class="field-help">Перелічіть дозволені елементи: кольори, об’єкти, композицію, матеріали, шрифтовий настрій, бажані референси.</small></label>
  <label class="wide">Що не використовувати<textarea name="avoid_rules" placeholder="Без дрібного тексту, логотипів інших брендів, реалістичних людей, хаотичних колажів, кислотних кольорів, темного фону.">${esc(item.avoid_rules||"")}</textarea><small class="field-help">Це поле дуже важливе: воно прибирає небажані візуальні помилки й робить результати стабільнішими.</small></label>
  <label class="wide">Промпт для AI<textarea name="prompt" minlength="30" required placeholder="Створюй професійний B2B-візуал для Telegram-поста: чиста композиція, світлий фон, одна головна метафора, без зайвого тексту.">${esc(item.prompt||"Створюй чисті професійні візуали для бренду з чіткою композицією та без зайвого тексту.")}</textarea><small class="field-help">Напишіть основну інструкцію, яку AI має застосовувати до кожного візуалу цього стилю.</small></label>
  <label class="wide">Приклади промптів<textarea name="prompt_examples" placeholder="1. Абстрактна схема AI-аналізу дзвінків на світлому фоні...\n2. Чиста картка з метафорою автоматизації підтримки...">${esc(item.prompt_examples||"")}</textarea><small class="field-help">Додайте 2–4 приклади. Вони не обов’язкові, але сильно допомагають команді й AI тримати один напрям.</small></label>
  <label class="check-label wide"><input name="active" type="checkbox" ${item.active===0?"":"checked"}> Активний стиль</label>`;
}
function openVisualStyleForm(item=null) {
  showForm(item?"Редагувати візуальний стиль":"Створити візуальний стиль",visualStyleFields(item||{}),async form=>{
    const payload={name:form.get("name"),description:form.get("description"),prompt:form.get("prompt"),layout:item?.layout||"top_left",accent:form.get("accent"),mood:form.get("mood"),use_rules:form.get("use_rules"),avoid_rules:form.get("avoid_rules"),prompt_examples:form.get("prompt_examples"),active:form.get("active")==="on"};
    await api(item?`api/templates/${encodeURIComponent(item.id)}`:"api/templates",{method:item?"PUT":"POST",body:JSON.stringify(payload)});delete state.lists.visuals;toast("Візуальний стиль збережено");renderBrand();
  });
}
function openMaterialForm(item) {
  showForm("Редагувати матеріал",`<label>Назва<input name="name" value="${esc(item.name)}" required></label><label>Тип<select name="material_type">${["logo","brandbook","presentation","photo","reference_image","document","link","other"].map(type=>`<option value="${type}" ${item.material_type===type?"selected":""}>${type}</option>`).join("")}</select></label><label class="wide">URL<input name="source_url" value="${esc(item.source_url||"")}"></label><label class="wide">Опис<textarea name="description">${esc(item.description||"")}</textarea></label><label class="check-label wide"><input name="active" type="checkbox" ${item.active===0?"":"checked"}> Активний матеріал</label>`,async form=>{await api(`api/brand/materials/${item.id}`,{method:"PUT",body:JSON.stringify({name:form.get("name"),material_type:form.get("material_type"),source_url:form.get("source_url"),description:form.get("description"),active:form.get("active")==="on"})});delete state.lists.assets;toast("Матеріал збережено");renderBrand();});
}
function openAvatarCropper(file, uploadAppearanceAsset) {
  if(!file)return;
  const url=URL.createObjectURL(file);
  const crop={x:0,y:0,zoom:1,baseScale:1,stageW:0,stageH:0,diameter:0,dragging:false,lastX:0,lastY:0};
  const size=512;
  const image=new Image();
  image.src=url;
  showForm(
    "Установити фото workspace",
    `<div class="wide telegram-cropper">
      <div class="telegram-crop-stage" id="avatarCropFrame">
        <img id="avatarCropImage" src="${esc(url)}" alt="">
        <div class="telegram-crop-vignette" aria-hidden="true"></div>
        <div class="telegram-crop-ring" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      </div>
      <div class="telegram-crop-controls">
        <button type="button" id="avatarZoomOut" aria-label="Зменшити">−</button>
        <input id="avatarCropZoom" type="range" min="1" max="3" step="0.01" value="1" aria-label="Масштаб фото">
        <button type="button" id="avatarZoomIn" aria-label="Збільшити">+</button>
      </div>
      <small class="telegram-crop-help">Перетягніть фото та оберіть зону всередині кола. Після збереження аватар одразу застосовується у workspace.</small>
    </div>`,
    async()=>{
      if(!image.complete) await image.decode().catch(()=>{});
      measure();
      clamp();
      const canvas=document.createElement("canvas");
      canvas.width=size;canvas.height=size;
      const ctx=canvas.getContext("2d");
      ctx.clearRect(0,0,size,size);
      const scale=crop.baseScale*crop.zoom;
      const imageLeft=crop.stageW/2+crop.x-image.naturalWidth*scale/2;
      const imageTop=crop.stageH/2+crop.y-image.naturalHeight*scale/2;
      const cropLeft=crop.stageW/2-crop.diameter/2;
      const cropTop=crop.stageH/2-crop.diameter/2;
      const sourceX=(cropLeft-imageLeft)/scale;
      const sourceY=(cropTop-imageTop)/scale;
      const sourceSize=crop.diameter/scale;
      ctx.drawImage(image,sourceX,sourceY,sourceSize,sourceSize,0,0,size,size);
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/png",.95));
      if(!blob)throw new Error("Не вдалося підготувати аватар");
      await uploadAppearanceAsset("avatar",new File([blob],"workspace-avatar.png",{type:"image/png"}));
      URL.revokeObjectURL(url);
    },
    {submitLabel:"Установити фото",loadingLabel:"Завантажуємо…",modalClass:"avatar-crop-modal"},
  );
  const frame=document.querySelector("#avatarCropFrame");
  const img=document.querySelector("#avatarCropImage");
  const zoom=document.querySelector("#avatarCropZoom");
  const measure=()=>{
    if(!frame||!image.naturalWidth)return;
    const rect=frame.getBoundingClientRect();
    crop.stageW=rect.width;crop.stageH=rect.height;
    crop.diameter=Math.min(rect.width*.68,rect.height*.84,380);
    crop.baseScale=Math.min(rect.width/image.naturalWidth,rect.height/image.naturalHeight);
    const minZoom=Math.max(crop.diameter/(image.naturalWidth*crop.baseScale),crop.diameter/(image.naturalHeight*crop.baseScale),1);
    zoom.min=String(minZoom);
    if(crop.zoom<minZoom)crop.zoom=minZoom;
    zoom.value=String(crop.zoom);
    frame.style.setProperty("--crop-size",`${crop.diameter}px`);
  };
  const clamp=()=>{
    const scale=crop.baseScale*crop.zoom;
    const halfW=image.naturalWidth*scale/2;
    const halfH=image.naturalHeight*scale/2;
    const cropHalf=crop.diameter/2;
    const maxX=Math.max(0,halfW-cropHalf);
    const maxY=Math.max(0,halfH-cropHalf);
    crop.x=Math.max(-maxX,Math.min(maxX,crop.x));
    crop.y=Math.max(-maxY,Math.min(maxY,crop.y));
  };
  const update=()=>{measure();clamp();if(img){const w=image.naturalWidth*crop.baseScale;const h=image.naturalHeight*crop.baseScale;img.style.width=`${w}px`;img.style.height=`${h}px`;img.style.transform=`translate(calc(-50% + ${crop.x}px), calc(-50% + ${crop.y}px)) scale(${crop.zoom})`;}};
  image.onload=update;
  zoom?.addEventListener("input",()=>{crop.zoom=Number(zoom.value);update();});
  document.querySelector("#avatarZoomOut")?.addEventListener("click",()=>{crop.zoom=Math.max(Number(zoom.min),crop.zoom-.08);zoom.value=String(crop.zoom);update();});
  document.querySelector("#avatarZoomIn")?.addEventListener("click",()=>{crop.zoom=Math.min(Number(zoom.max),crop.zoom+.08);zoom.value=String(crop.zoom);update();});
  frame?.addEventListener("pointerdown",event=>{crop.dragging=true;crop.lastX=event.clientX;crop.lastY=event.clientY;frame.setPointerCapture(event.pointerId);});
  frame?.addEventListener("pointermove",event=>{if(!crop.dragging)return;crop.x+=event.clientX-crop.lastX;crop.y+=event.clientY-crop.lastY;crop.lastX=event.clientX;crop.lastY=event.clientY;update();});
  frame?.addEventListener("pointerup",()=>{crop.dragging=false;});
  window.addEventListener("resize",update,{once:true});
  update();
}
function bindBrandActions() {
  bindColorControl("brandColor");
  document.querySelectorAll("[data-brand-score-tab]").forEach(button => button.onclick = () => {
    state.brandTab = button.dataset.brandScoreTab;
    history.pushState({view:"brand"},"",`${basePath}/brand${state.brandTab === "profile" ? "" : `?tab=${state.brandTab}`}`);
    renderBrand();
  });
  document.querySelector("#saveBrandProfile")?.addEventListener("click",async()=>{
    await api("api/onboarding/company",{method:"PUT",body:JSON.stringify({name:state.company.name,slug:state.company.slug,primary_language:state.company.settings.primary_language||"uk",brand_primary_color:document.querySelector("#brandColor").value,brand_logo_asset_id:state.company.settings.brand_logo_asset_id||null})});
    await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:document.querySelector("#brandDescription").value,tone_of_voice:state.company.settings.tone_of_voice||"",key_services:document.querySelector("#brandServices").value,forbidden_phrases:state.company.settings.forbidden_phrases||"",website_url:document.querySelector("#brandWebsite").value})});
    toast("Профіль збережено");
    await refresh();
  });
  document.querySelector("#saveTone")?.addEventListener("click",async()=>{await api("api/onboarding/brand",{method:"PUT",body:JSON.stringify({company_description:state.company.settings.company_description||"",tone_of_voice:document.querySelector("#toneValue").value,key_services:state.company.settings.key_services||"",forbidden_phrases:state.company.settings.forbidden_phrases||"",website_url:state.company.settings.website_url||""})});toast("Tone of voice збережено");await refresh();});
  document.querySelector("#addRubric")?.addEventListener("click",()=>openRubricForm());
  document.querySelector("#emptyAddRubric")?.addEventListener("click",()=>openRubricForm());
  document.querySelector("#addVisualStyle")?.addEventListener("click",()=>openVisualStyleForm());
  document.querySelector("#addVisualStyleEmpty")?.addEventListener("click",()=>openVisualStyleForm());
  document.querySelector("#addMaterialLink")?.addEventListener("click",()=>showForm("Додати посилання",`<label>Назва<input name="name" required></label><label>Тип<select name="material_type"><option value="link">Посилання</option><option value="brandbook">Брендбук</option><option value="presentation">Презентація</option><option value="document">Документ</option><option value="other">Інше</option></select></label><label class="wide">URL<input name="source_url" type="url" required></label><label class="wide">Опис<textarea name="description"></textarea></label>`,async form=>{await api("api/brand/materials/link",{method:"POST",body:JSON.stringify({name:form.get("name"),material_type:form.get("material_type"),source_url:form.get("source_url"),description:form.get("description"),active:true})});delete state.lists.assets;toast("Посилання додано");renderBrand();}));
  document.querySelector("#uploadMaterial")?.addEventListener("click",()=>showForm("Завантажити матеріал",`<label>Назва<input name="name"></label><label>Тип<select name="material_type"><option value="logo">Логотип</option><option value="brandbook">Брендбук</option><option value="presentation">Презентація</option><option value="photo">Фото</option><option value="reference_image">Референс зображення</option><option value="document">Документ</option><option value="other">Інше</option></select></label><label class="wide">Файл<input name="file" type="file" accept="image/png,image/jpeg,image/webp,application/pdf,.docx,.pptx" required></label><label class="wide">Опис<textarea name="description"></textarea><small class="field-help">PNG, JPG, WebP, PDF, DOCX або PPTX до 20 MB.</small></label>`,async form=>{await api("api/references",{method:"POST",body:form});delete state.lists.assets;toast("Матеріал завантажено");await refresh(true);renderBrand();}));
  const updateAppearancePreview=()=>{const preview=document.querySelector("#appearancePreview");if(!preview)return;preview.style.setProperty("--preview-primary",document.querySelector("#appearancePrimary").value);preview.style.setProperty("--preview-secondary",document.querySelector("#appearanceSecondary").value);preview.querySelector("h3").textContent=document.querySelector("#appearanceName").value;preview.querySelector("p").textContent=document.querySelector("#appearanceDescription").value||"Контент, бренд і публікації в одному просторі.";};
  ["#appearanceName","#appearanceDescription","#appearancePrimary","#appearanceSecondary"].forEach(selector=>document.querySelector(selector)?.addEventListener("input",updateAppearancePreview));
  bindColorControl("appearancePrimary", updateAppearancePreview);
  bindColorControl("appearanceSecondary", updateAppearancePreview);
  document.querySelectorAll("[data-color-preset]").forEach(button=>button.onclick=()=>{const [primary,secondary]=button.dataset.colorPreset.split(",");document.querySelector("#appearancePrimary").value=primary;document.querySelector("#appearanceSecondary").value=secondary;bindColorControl("appearancePrimary", updateAppearancePreview);bindColorControl("appearanceSecondary", updateAppearancePreview);updateAppearancePreview();});
  const saveAppearanceSettings=async(showToast=true)=>{
    const result=await api("api/workspace/appearance",{method:"PUT",body:JSON.stringify({name:document.querySelector("#appearanceName").value,slug:"",short_description:document.querySelector("#appearanceDescription").value,primary_color:document.querySelector("#appearancePrimary").value,secondary_color:document.querySelector("#appearanceSecondary").value,avatar_asset_id:Number(document.querySelector("#appearanceAvatar").value)||null,logo_asset_id:Number(document.querySelector("#appearanceLogo").value)||null,favicon_asset_id:null})});
    state.company={...state.company,...result.company,settings:result.settings};
    const patchWorkspace = workspace => Number(workspace.id) === Number(state.company.id)
      ? {...workspace,...result.company,workspace_avatar_asset_id:result.settings.workspace_avatar_asset_id,brand_logo_asset_id:result.settings.brand_logo_asset_id,workspace_short_description:result.settings.workspace_short_description,updated_at:new Date().toISOString()}
      : workspace;
    if (state.me?.workspaces) state.me.workspaces = state.me.workspaces.map(patchWorkspace);
    if (state.company?.company?.workspaces) state.company.company.workspaces = state.company.company.workspaces.map(patchWorkspace);
    state.appearanceDirty = true;
    applyIdentity();
    if(showToast)toast("Оформлення збережено");
    return result;
  };
  const uploadAppearanceAsset=async(kind,file)=>{
    if(!file)return;
    const form=new FormData();form.append("kind",kind);form.append("file",file);
    const result=await api("api/workspace/appearance/assets",{method:"POST",body:form});
    const field=document.querySelector(kind==="avatar"?"#appearanceAvatar":"#appearanceLogo");
    field.value=result.id;
    const markup=`<img src="${apiUrl(`${result.url}?v=${result.id}`)}" alt="">`;
    document.querySelector(kind==="avatar"?"#appearanceAvatarPreview":"#appearanceLogoPreview").innerHTML=markup;
    document.querySelector(kind==="avatar"?"#workspacePreviewAvatar":"#workspacePreviewLogo").innerHTML=markup;
    await saveAppearanceSettings(false);
    toast(kind==="avatar"?"Аватар встановлено":"Логотип збережено");
  };
  document.querySelector("#appearanceAvatarFile")?.addEventListener("change",event=>openAvatarCropper(event.target.files[0],uploadAppearanceAsset));
  document.querySelector("#appearanceLogoFile")?.addEventListener("change",event=>uploadAppearanceAsset("logo",event.target.files[0]).catch(error=>toast(error.message,true)));
  document.querySelector("#saveAppearance")?.addEventListener("click",async()=>{await saveAppearanceSettings(true);renderBrand();});
}
function bindTelegramValidation(channelId, tokenId, statusId, buttonId) {
  const channel = document.querySelector(`#${channelId}`);
  const token = document.querySelector(`#${tokenId}`);
  const status = document.querySelector(`#${statusId}`);
  const button = document.querySelector(`#${buttonId}`);
  let timer;
  const validate = async () => {
    if (!channel.value.trim() || token.value.trim().length < 20) {
      status.className = "connection-status";
      status.textContent = "Введіть @username каналу та повний bot token.";
      return false;
    }
    status.className = "connection-status checking";
    status.textContent = "Перевіряємо бота, канал і права адміністратора…";
    try {
      const result = await api("api/company/telegram/validate", {method:"POST",body:JSON.stringify({channel_id:channel.value.trim(),bot_token:token.value.trim()})});
      status.className = "connection-status success";
      status.textContent = `Підключення працює: @${result.bot_username}, права ${result.membership_status}.`;
      return true;
    } catch (error) {
      status.className = "connection-status error";
      status.textContent = error.message;
      return false;
    }
  };
  const queue = () => {
    clearTimeout(timer);
    timer = setTimeout(validate, 700);
  };
  channel.addEventListener("input", queue);
  token.addEventListener("input", queue);
  channel.addEventListener("blur", validate);
  token.addEventListener("blur", validate);
  if (button) button.onclick = validate;
  return validate;
}
function bindSettingsActions() {
  document.querySelector("#saveWorkspaceMode")?.addEventListener("click",async()=>{const mode=document.querySelector('[name="workspaceMode"]:checked').value;await api("api/workspace/mode",{method:"PUT",body:JSON.stringify({workspace_mode:mode})});state.company.settings.workspace_mode=mode;applyIdentity();renderSettings();toast("Режим збережено");});
  document.querySelector("#restartOnboarding")?.addEventListener("click",async()=>{await api("api/onboarding/restart",{method:"POST"});showOnboarding(1);});
  document.querySelector("#deleteCurrentWorkspace")?.addEventListener("click",()=>openWorkspaceDelete());
  document.querySelector("#inviteUser")?.addEventListener("click",()=>showForm("Запросити користувача",`<label>Email<input name="email" type="email" required></label><label>Роль<select name="role"><option value="admin">Адміністратор</option><option value="content_manager">Контент-менеджер</option><option value="editor">Редактор</option><option value="publisher">Публікатор</option><option value="viewer">Переглядач</option></select></label>`,async form=>{const result=await api("api/invitations",{method:"POST",body:JSON.stringify({email:form.get("email"),role:form.get("role")})});await navigator.clipboard.writeText(result.url);toast("Посилання скопійовано");}));
  document.querySelectorAll("[data-reset-user]").forEach(button=>button.onclick=async()=>{const result=await api("api/password-reset/link",{method:"POST",body:JSON.stringify({user_id:Number(button.dataset.resetUser)})});await navigator.clipboard.writeText(result.url);toast("Reset-посилання скопійовано");});
  document.querySelector("#copyReferral")?.addEventListener("click",async()=>{await navigator.clipboard.writeText(state.referral.url);toast("Реферальне посилання скопійовано");});
  document.querySelector("#rotateReferral")?.addEventListener("click",async()=>{state.referral=await api("api/referrals/me/rotate",{method:"POST"});renderSettings();toast("Створено новий реферальний код");});
  document.querySelector("#disableReferral")?.addEventListener("click",async()=>{if(!confirm("Вимкнути поточне реферальне посилання?"))return;state.referral=await api("api/referrals/me/disable",{method:"POST"});renderSettings();toast("Реферальне посилання вимкнено");});
  document.querySelectorAll("[data-buy-plan]").forEach(button=>button.onclick=async()=>{
    const popup = window.open("about:blank", "_blank");
    try {
      const result = await loading(button,()=>api("api/billing/checkout",{method:"POST",body:JSON.stringify({plan_code:button.dataset.buyPlan})}),"Створюємо рахунок…");
      if (popup) popup.location = result.invoice_url;
      else location.href = result.invoice_url;
      toast("Рахунок відкрито в Telegram");
    } catch (error) {
      popup?.close();
      throw error;
    }
  });
  const telegramValidator = document.querySelector("#telegramChannel")
    ? bindTelegramValidation("telegramChannel", "telegramToken", "telegramStatus", "testTelegram")
    : null;
  document.querySelector("#saveTelegram")?.addEventListener("click",async()=>{
    if (!await telegramValidator()) return;
    await api("api/company/telegram",{method:"PUT",body:JSON.stringify({channel_id:document.querySelector("#telegramChannel").value,bot_token:document.querySelector("#telegramToken").value})});
    toast("Telegram підключено");
    await refresh();
  });
  document.querySelector("#connectInstagram")?.addEventListener("click",async event=>{
    const result = await loading(event.currentTarget,()=>api("api/integrations/instagram/connect-url",{method:"POST"}),"Готуємо Meta Login…");
    if (!result.url) return toast(result.message || "Instagram ще не налаштовано", true);
    location.href = result.url;
  });
  document.querySelector("#disconnectInstagram")?.addEventListener("click",async event=>{
    if(!confirm("Відключити Instagram для цього workspace? Telegram залишиться підключеним."))return;
    await loading(event.currentTarget,()=>api("api/integrations/instagram",{method:"DELETE"}),"Відключаємо…");
    state.instagramIntegration=null;
    toast("Instagram відключено");
    renderSettings();
  });
  document.querySelector("#changePassword")?.addEventListener("click",async()=>{await api("api/account/password",{method:"PUT",body:JSON.stringify({password:document.querySelector("#ownPassword").value})});location.href=`${basePath}/`;});
}
async function runUserBulk(action) {
  const ids=[...selected("users")].map(Number);if(!ids.length)return;
  let value="";
  if(action==="role"){value=prompt("Нова роль: admin, content_manager, editor, publisher, viewer")||"";if(!value)return;}
  if(action==="remove"&&!confirm(`Видалити ${ids.length} користувачів з workspace?`))return;
  await api("api/users/bulk",{method:"POST",body:JSON.stringify({ids,action,value})});selected("users").clear();delete state.lists.users;toast("Користувачів оновлено");renderSettings();
}
function bindEditorActions() {
  document.querySelector("#closeEditor").onclick=closeEditor;
  const updatePreview=()=>{document.querySelector("#previewTitle").textContent=plain(document.querySelector("#editorVisualTitle").value);document.querySelector("#previewText").innerHTML=safeHtml(document.querySelector("#editorCaption").value);};
  document.querySelector("#editorVisualTitle").oninput=updatePreview;document.querySelector("#editorCaption").oninput=updatePreview;
  document.querySelectorAll("[data-editor-status]").forEach(button => button.onclick = async () => {
    const draft = await api(`api/drafts/${state.currentDraft.id}/status`, {method:"POST",body:JSON.stringify({status:button.dataset.editorStatus})});
    toast(`${translateText("Статус змінено:")} ${statusLabel(draft.status)}`);
    await refresh(true);
    await openEditor(draft.id, false);
  });
  document.querySelector("#saveDraft").onclick=async event=>loading(event.currentTarget,async()=>{await api(`api/drafts/${state.currentDraft.id}`,{method:"PUT",body:JSON.stringify({title:document.querySelector("#editorTitle").value,visual_title:document.querySelector("#editorVisualTitle").value,caption_html:document.querySelector("#editorCaption").value,link_url:document.querySelector("#editorLink").value})});toast("Зміни збережено");await refresh(true);},"Зберігаємо…");
  document.querySelector("#regenText").onclick=async event=>loading(event.currentTarget,async()=>{await api(`api/drafts/${state.currentDraft.id}/regenerate-text`,{method:"POST",body:JSON.stringify(generationPayload())});toast("Нову версію поставлено в чергу");closeEditor();await refresh(true);delete state.lists.drafts;setView("drafts");},"Запускаємо…");
  document.querySelector("#scheduleDraft").onclick=async event=>{const value=document.querySelector("#scheduleAt").value;if(!value)return toast("Оберіть дату і час",true);await loading(event.currentTarget,async()=>{await api(`api/drafts/${state.currentDraft.id}/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(value).toISOString()})});toast("Публікацію заплановано");closeEditor();await refresh();},"Плануємо…");};
  document.querySelector("#cancelSchedule").onclick=async event=>loading(event.currentTarget,async()=>{await api(`api/drafts/${state.currentDraft.id}/cancel-schedule`,{method:"POST"});toast("Публікацію повернуто в готові");closeEditor();await refresh();},"Скасовуємо…");
  document.querySelector("#publishDraft").onclick=async event=>{if(!confirm("Опублікувати пост зараз?"))return;await loading(event.currentTarget,async()=>{await api(`api/drafts/${state.currentDraft.id}/publish`,{method:"POST"});toast("Пост опубліковано");closeEditor();await refresh();},"Публікуємо…");};
  document.querySelector("#publishInstagram")?.addEventListener("click",async event=>{
    if(!confirm("Опублікувати цей пост в Instagram Feed? Telegram-публікація не зміниться."))return;
    await loading(event.currentTarget,async()=>{
      const job = await api(`api/drafts/${state.currentDraft.id}/instagram/publish`,{method:"POST"});
      toast(job.permalink ? "Пост опубліковано в Instagram" : "Instagram-публікацію створено");
      await refresh(true);
      await openEditor(state.currentDraft.id,false);
    },"Публікуємо в Instagram…");
  });
  document.querySelector("#scheduleInstagram")?.addEventListener("click",async event=>{
    const value = document.querySelector("#scheduleAt").value;
    if(!value)return toast("Оберіть дату і час для Instagram",true);
    await loading(event.currentTarget,async()=>{
      await api(`api/drafts/${state.currentDraft.id}/instagram/schedule`,{method:"POST",body:JSON.stringify({scheduled_at:new Date(value).toISOString()})});
      toast("Instagram Feed заплановано");
      await refresh(true);
      await openEditor(state.currentDraft.id,false);
    },"Плануємо Instagram…");
  });
}

async function refresh(background = false) {
  try {
    const [me, company, data, usage, referral, serviceUpdates, instagram] = await Promise.all([api("api/me"),api("api/company"),api("api/dashboard"),api("api/usage"),api("api/referrals/me"),api(`api/service-updates?locale=${encodeURIComponent(state.locale)}`),api("api/integrations/instagram/status")]);
    state.me=me;state.company=company;state.data=data;state.usage=usage;state.referral=referral;state.serviceUpdates=serviceUpdates;state.instagramIntegration=instagram;
    if (me.is_super_admin) state.platformUsage = await api(`api/platform/usage?period=${state.platformPeriod}`);
    if (me.is_admin) state.users=await api("api/users");
    applyIdentity();
    updateGenerationPolling();
    if (!background) await applyLocationRoute();
    else renderCurrent();
    if (!background && onboardingRequired()) {
      if (!localStorage.getItem(guideStorageKey()) && !localStorage.getItem(guideDismissedKey())) openGuide();
      else showOnboarding(Math.max(1,Number(company.settings.onboarding_step||0)+1));
    }
  } catch (error) { if (!background) toast(error.message,true); }
}

function activeGenerationSignature(data = state.data) {
  return (data?.jobs || [])
    .filter(job => activeGenerationStatuses.has(job.status))
    .map(job => `${job.id}:${job.status}:${job.draft_id || 0}`)
    .sort()
    .join("|");
}
function trackGenerationCompletions(previousData, nextData) {
  const previous = new Map((previousData?.jobs || []).map(job => [Number(job.id), job]));
  for (const job of nextData?.jobs || []) {
    const before = previous.get(Number(job.id));
    if (!before || !activeGenerationStatuses.has(before.status)) continue;
    if (job.status === "ready" && job.draft_id) {
      state.recentJobIds.add(Number(job.id));
      state.recentDraftIds.add(Number(job.draft_id));
      state.completedJobs = [
        {id: job.id, draft_id: job.draft_id, title: job.topic || `Чернетка #${job.draft_id}`},
        ...state.completedJobs.filter(item => Number(item.id) !== Number(job.id)),
      ].slice(0, 12);
      toast("Чернетку створено. Вона підсвічена у списку чернеток.");
    }
    if (job.status === "failed") {
      toast(job.error || "Генерація зупинилася. Деталі є у сповіщеннях.", true);
    }
  }
}
function updateGenerationPolling() {
  clearTimeout(generationPollTimer);
  generationPollTimer = null;
  generationSignature = activeGenerationSignature();
  if (!generationSignature) return;
  generationPollTimer = setTimeout(async () => {
    try {
      const data = await api("api/dashboard");
      const nextSignature = activeGenerationSignature(data);
      const changed = nextSignature !== generationSignature;
      trackGenerationCompletions(state.data, data);
      state.data = data;
      generationSignature = nextSignature;
      if (changed) {
        delete state.lists.drafts;
        delete state.lists.ideas;
        delete state.lists.plan;
        applyIdentity();
        updateNotificationBadge();
        renderCurrent();
      }
    } catch (error) {
      console.warn("Generation polling failed", error);
    } finally {
      updateGenerationPolling();
    }
  }, 2500);
}

document.querySelectorAll(".nav-item[data-view]").forEach(node=>node.onclick=()=>{document.body.classList.remove("menu-open");setView(node.dataset.view);});
document.querySelectorAll("[data-platform-section]").forEach(node=>node.onclick=()=>{document.body.classList.remove("menu-open");openPlatformSection(node.dataset.platformSection);});
document.querySelector("#platformRefresh").onclick=()=>loadPlatformSection(true);
document.querySelector("#mobileMenu").onclick=()=>document.body.classList.add("menu-open");
document.addEventListener("click",event=>{if(document.body.classList.contains("menu-open")&&!event.target.closest(".sidebar")&&!event.target.closest("#mobileMenu"))document.body.classList.remove("menu-open");});
document.querySelector("#workspaceButton").onclick=async()=>{
  if (state.appearanceDirty) {
    const [me, company] = await Promise.all([api("api/me"), api("api/company")]);
    state.me = me;
    state.company = company;
    state.appearanceDirty = false;
    applyIdentity();
  }
  renderWorkspaceChooser(true);
};
document.querySelector("#logout").onclick=async()=>{await api("api/logout",{method:"POST"});location.href=`${basePath}/`;};
document.querySelector("#languageToggle").onclick=()=>{
  state.locale = state.locale === "uk" ? "en" : "uk";
  localStorage.setItem("content-studio:locale", state.locale);
  location.reload();
};
document.querySelectorAll("[data-close-overlay]").forEach(node=>node.onclick=()=>node.closest(".overlay").hidden=true);
document.querySelectorAll(".overlay").forEach(overlay=>overlay.addEventListener("click",event=>{
  if(event.target!==overlay||overlay.id==="aiProgressOverlay")return;
  if(overlay.id==="editorOverlay")closeEditor();
  else overlay.hidden=true;
}));
document.addEventListener("keydown", event => {
  const overlay = [...document.querySelectorAll(".overlay:not([hidden])")].pop();
  if (!overlay) return;
  if (event.key === "Escape" && overlay.id !== "onboardingOverlay") {
    overlay.hidden = true;
    if (overlay.id === "editorOverlay") closeEditor();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = [...overlay.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter(node => !node.hidden);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
window.addEventListener("online", renderSystemBanner);
window.addEventListener("offline", renderSystemBanner);
function syncVisualViewport() {
  const viewport = window.visualViewport;
  const height = Math.round(viewport?.height || window.innerHeight);
  const offsetTop = Math.round(viewport?.offsetTop || 0);
  const keyboardInset = Math.max(0, Math.round(window.innerHeight - height - offsetTop));
  document.documentElement.style.setProperty("--visual-viewport-height", `${height}px`);
  document.documentElement.style.setProperty("--visual-viewport-top", `${offsetTop}px`);
  document.documentElement.style.setProperty("--keyboard-inset", `${keyboardInset}px`);
  document.body.classList.toggle("keyboard-open", keyboardInset > 120);
  if (keyboardInset > 120 && document.activeElement?.matches("input,textarea,select")) {
    requestAnimationFrame(() => document.activeElement?.scrollIntoView({block:"nearest"}));
  }
}
window.visualViewport?.addEventListener("resize", syncVisualViewport);
window.visualViewport?.addEventListener("scroll", syncVisualViewport);
window.addEventListener("resize", syncVisualViewport);
syncVisualViewport();
document.querySelector("#generateIdeas").onclick=event=>showForm(
  "Згенерувати ідеї",
  `<label>Рубрика<select name="product"><option value="all">Усі рубрики</option>${(state.data?.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Кількість<input name="count" type="number" min="1" max="12" value="8"></label><label class="wide">Фокус<textarea name="focus"></textarea></label>`,
  async form=>{
    await withAiProgress(
      () => api("api/ideas/generate",{method:"POST",body:JSON.stringify({product:form.get("product"),count:Number(form.get("count")),focus:form.get("focus"),text_model:"gpt-5.4-mini",tone:"expert"})}),
    );
    delete state.lists.ideas;
    toast("Ідеї готові та збережені");
    await refresh(true);
    renderIdeas();
  },
  {submitLabel:"Згенерувати",loadingLabel:"Генеруємо…"},
);
document.querySelector("#manualIdea").onclick=()=>showForm("Створити ідею",`<label class="wide">Назва<input name="title" required></label><label>Рубрика<select name="product">${(state.data.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Орієнтовна дата<input name="planned_for" type="date"></label><label class="wide">Кут подачі<textarea name="angle"></textarea></label>`,async form=>{await api("api/ideas",{method:"POST",body:JSON.stringify({title:form.get("title"),product:form.get("product"),planned_for:form.get("planned_for")||null,angle:form.get("angle")})});toast("Ідею додано");await refresh();});
document.querySelector("#manualDraft").onclick=()=>showForm("Створити чернетку",`<label class="wide">Заголовок<input name="title" required></label><label>Рубрика<select name="product">${(state.data.rubrics||[]).map(x=>`<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("")}</select></label><label>Заголовок на візуалі<input name="visual_title"></label><label class="wide">Текст<textarea name="caption_html" minlength="20" required></textarea></label><label class="wide">Посилання<input name="link_url" type="url"></label>`,async form=>{const draft=await api("api/drafts",{method:"POST",body:JSON.stringify({title:form.get("title"),visual_title:form.get("visual_title"),product:form.get("product"),caption_html:form.get("caption_html"),link_url:form.get("link_url")})});toast("Чернетку створено");await refresh();openEditor(draft.id);});
document.querySelector("#calendarSchedule").onclick=()=>openScheduleForm();
document.querySelector("#planForm").onsubmit=async event=>{event.preventDefault();await loading(event.submitter,async()=>{await api("api/content-plan/generate",{method:"POST",body:JSON.stringify({product:document.querySelector("#planProduct").value,period:document.querySelector("#planPeriod").value,posts:Number(document.querySelector("#planPosts").value),start_date:document.querySelector("#planStart").value,focus:document.querySelector("#planFocus").value,text_model:"gpt-5.4-mini",create_as:document.querySelector("#planCreateAs").value,rubric_slugs:[],channel_ids:[]})});toast("Контент-план створено");await refresh();renderPlan();},"Створюємо…");};
document.querySelector("#calendarPrev").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);updateViewUrl("calendar");renderCalendar();};
document.querySelector("#calendarNext").onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);updateViewUrl("calendar");renderCalendar();};
document.querySelector("#calendarToday").onclick=()=>{state.calendarDate=new Date();updateViewUrl("calendar");renderCalendar();};
document.querySelector("#onboardingBack").onclick=()=>showOnboarding(state.onboardingStep-1);
document.querySelector("#onboardingNext").onclick=event=>loading(event.currentTarget,saveOnboarding,"Зберігаємо…");
document.querySelector("#skipOnboarding").onclick=async()=>{await api("api/onboarding/skip",{method:"POST"});document.querySelector("#onboardingOverlay").hidden=true;};
document.querySelectorAll("[data-brand-tab]").forEach(node=>node.onclick=()=>{state.brandTab=node.dataset.brandTab;if(state.brandTab==="assets"&&state.lists.assets?.error)delete state.lists.assets;const query=new URLSearchParams();if(state.brandTab!=="profile")query.set("tab",state.brandTab);history.pushState({view:"brand"},"",`${basePath}/brand${query.size?`?${query}`:""}`);document.querySelectorAll("[data-brand-tab]").forEach(x=>x.classList.toggle("active",x===node));renderBrand();});
document.querySelectorAll("[data-settings]").forEach(node=>node.onclick=()=>{state.settingsTab=node.dataset.settings;const query=new URLSearchParams();if(state.settingsTab!=="workspace")query.set("tab",state.settingsTab);history.pushState({view:"settings"},"",`${basePath}/settings${query.size?`?${query}`:""}`);document.querySelectorAll("[data-settings]").forEach(x=>x.classList.toggle("active",x===node));renderSettings();});
document.querySelector("#searchButton").onclick=()=>{
  showForm("Пошук",`<label class="wide">Ідеї, чернетки та розділи<input name="query" id="globalSearch" autofocus></label><div class="wide stack" id="searchResults"></div>`,async()=>{});
  const input=document.querySelector("#globalSearch"),results=document.querySelector("#searchResults");
  let searchTimer;
  input.oninput=()=>{
    clearTimeout(searchTimer);
    const query=input.value.trim();
    if(!query){results.innerHTML="";return}
    results.innerHTML='<span class="skeleton"></span>';
    searchTimer=setTimeout(async()=>{
      try {
        const params = new URLSearchParams({search:query,page:"1",per_page:"6"});
        const [ideas,drafts] = await Promise.all([
          api(`api/ideas?${params}`),
          api(`api/drafts?${params}`),
        ]);
        const sectionRows = Object.entries(titles)
          .filter(([view,meta]) => view !== "platform" || state.me?.is_super_admin)
          .filter(([,meta]) => `${meta[0]} ${meta[1]}`.toLowerCase().includes(query.toLowerCase()))
          .slice(0,4)
          .map(([view,meta])=>({type:"Розділ",view,title:meta[0],text:meta[1]}));
        const rows=[
          ...sectionRows,
          ...(ideas.items||[]).map(x=>({...x,type:"Ідея",view:"ideas",text:x.angle||""})),
          ...(drafts.items||[]).map(x=>({...x,type:"Чернетка",view:"drafts",text:x.caption_plain||plain(x.caption_html||""),draftId:x.id})),
        ].slice(0,14);
        results.innerHTML=rows.map(x=>`<button type="button" class="quick-action" data-search-view="${x.view}" data-search-draft="${x.draftId||""}"><span class="pill ${x.type==="Ідея"?"idea":x.type==="Чернетка"?"draft":"ready"}">${x.type}</span><span><strong>${esc(plain(x.title))}</strong><small class="muted">${esc(plain(x.text||"").slice(0,100))}</small></span></button>`).join("")||'<p class="muted">Нічого не знайдено.</p>';
        results.querySelectorAll("button").forEach(button=>button.onclick=()=>{document.querySelector("#formOverlay").hidden=true;if(button.dataset.searchDraft)openEditor(Number(button.dataset.searchDraft));else setView(button.dataset.searchView);});
      } catch (error) {
        results.innerHTML=`<p class="danger-text">${esc(error.message)}</p>`;
      }
    },260);
  };
};
document.querySelector("#createButton").onclick=()=>showForm(
  "Що бажаєте створити?",
  `<div class="wide create-intro"><span class="ai-spark">AI</span><div><strong>Почніть із потрібного результату</strong><p>Content Studio підкаже наступні кроки й збереже все у поточному workspace.</p></div></div>
   <div class="wide create-choice-grid">
    <button type="button" class="create-choice idea-choice" data-create-action="idea"><span class="create-choice-icon">✦</span><span><strong>Ідеї з AI</strong><small>Нові теми на основі бренду й рубрик</small></span><i>→</i></button>
    <button type="button" class="create-choice draft-choice" data-create-action="draft"><span class="create-choice-icon">＋</span><span><strong>Чернетку вручну</strong><small>Додати свій текст або почати з нуля</small></span><i>→</i></button>
    <button type="button" class="create-choice plan-choice" data-create-action="plan"><span class="create-choice-icon">▤</span><span><strong>Контент-план</strong><small>Розкласти публікації на тиждень чи місяць</small></span><i>→</i></button>
   </div>`,
  null,
);
document.querySelector("#formBody").addEventListener("click", event => {
  const button = event.target.closest("[data-create-action]");
  if (!button) return;
  document.querySelector("#formOverlay").hidden = true;
  if (button.dataset.createAction === "idea") { setView("ideas"); document.querySelector("#generateIdeas").click(); }
  if (button.dataset.createAction === "draft") { setView("drafts"); document.querySelector("#manualDraft").click(); }
  if (button.dataset.createAction === "plan") setView("plan");
});

const guideSteps = [
  {title:"Створіть робочий простір",visual:"workspace",text:"Workspace — це окремий простір для одного бренду, напряму або клієнта. У нього свої рубрики, чернетки, календар, Telegram-канал, команда, ролі, витрати й оформлення.",points:["Якщо у вас кілька брендів або клієнтів, створюйте для них різні workspace.","Не змішуйте матеріали різних компаній: так AI отримує чистіший контекст.","Owner workspace керує командою, ролями, брендом і небезпечними діями."]},
  {title:"Заповніть бренд-профіль",visual:"brand",text:"Бренд-профіль — це пам’ять сервісу про вашу компанію. Чим конкретніше описані продукт, аудиторія, tone of voice, кольори й матеріали, тим стабільнішими будуть тексти та візуали.",points:["В описі компанії пишіть факти: хто ви, для кого працюєте, яку проблему вирішуєте.","У tone of voice додайте правила мови, довжини, звертання та приклади фраз.","В оформленні завантажте аватар, логотип і виберіть основні кольори workspace."]},
  {title:"Створіть рубрики",visual:"rubrics",text:"Рубрики допомагають планувати контент системно: експертні пости, кейси, FAQ, новини, продажні матеріали, поради. AI використовує рубрики, щоб не повторювати один і той самий формат.",points:["Для кожної рубрики додайте назву, ціль, тон і приклад теми.","Активні рубрики доступні в генерації ідей і контент-плану.","Краще мати 5–8 зрозумілих рубрик, ніж один загальний список тем."]},
  {title:"Згенеруйте та відберіть ідеї",visual:"ideas",text:"Ідеї — це бібліотека тем, з яких потім створюються чернетки. Генеруйте кілька варіантів, фільтруйте за рубриками, вибирайте найсильніші та перетворюйте їх на пости.",points:["Після запуску генерації дочекайтесь індикатора готовності, не оновлюючи сторінку.","Використовуйте таблицю, пошук, фільтри й bulk-дії для великих списків.","Ідеї не публікуються напряму: спочатку з них створюється чернетка."]},
  {title:"Підготуйте чернетки",visual:"drafts",text:"Чернетка — це майбутній пост із заголовком, текстом, візуалом, статусом і соціальними варіантами. Її можна редагувати, погоджувати, повертати на правки й готувати до публікації.",points:["У редакторі окремо перевіряйте заголовок для поста й заголовок на візуалі.","Якщо текст уже готовий, а картинка ще генерується, дочекайтесь статусу в таблиці.","Перед плануванням переконайтесь, що у чернетки є готовий візуал."]},
  {title:"Заплануйте або опублікуйте",visual:"calendar",text:"Календар показує, коли вийде кожен матеріал. Готові чернетки можна призначити на локальну дату й час, перенести, повернути в готові або опублікувати.",points:["У модалці планування перегляньте повний текст і картинку, щоб не помилитися з постом.","Матеріали без дати зібрані ліворуч, а заплановані пости видно в календарній сітці.","Публікувати може лише користувач із відповідними permissions."]},
  {title:"Керуйте командою та результатом",visual:"team",text:"Після налаштування контенту додайте людей, призначте ролі й контролюйте витрати. Так сервіс стає не просто генератором, а робочим SaaS-процесом для команди.",points:["Viewer може тільки переглядати, Editor редагує, Publisher планує й публікує, Owner керує всім workspace.","У витратах видно AI-usage по днях, моделях і рубриках.","До цього гайда можна повернутися з кнопки «Гайд» у верхньому хедері."]},
];
const guideVisualLabels = {
  workspace: "🏠 Workspace",
  brand: "🎨 Бренд",
  rubrics: "▦ Рубрики",
  ideas: "💡 Ідеї",
  drafts: "✍ Чернетки",
  calendar: "🗓 План",
  team: "👥 Команда",
};
function guideStorageKey(){return `content-studio:guide:${state.me?.id||"guest"}:${state.me?.organization_id||"none"}`;}
function guideDismissedKey(){return `${guideStorageKey()}:dismissed`;}
function onboardingRequired(){
  const settings = state.company?.settings;
  return !!(settings && !["completed","skipped"].includes(settings.onboarding_status) && ["owner","admin"].includes(state.me?.role));
}
function renderGuide(){
  const step=guideSteps[state.guideStep];
  document.querySelector("#guideTitle").textContent=step.title;
  document.querySelector("#guideContent").innerHTML=`<div class="guide-stage"><div class="guide-copy"><div class="eyebrow">Крок ${state.guideStep+1} з ${guideSteps.length}</div><h3>${esc(step.title)}</h3><p>${esc(step.text)}</p><ul class="guide-points">${(step.points||[]).map(point=>`<li>${esc(point)}</li>`).join("")}</ul></div><div class="guide-illustration ${step.visual}"><span class="guide-orbit"></span><span class="guide-core">${esc(guideVisualLabels[step.visual]||step.title)}</span><i></i><i></i><i></i></div></div>`;
  document.querySelector("#guideDots").innerHTML=guideSteps.map((_,index)=>`<button class="${index===state.guideStep?"active":""}" data-guide-step="${index}" aria-label="Крок ${index+1}"></button>`).join("");
  document.querySelector("#guideBack").disabled=state.guideStep===0;
  document.querySelector("#guideNext").textContent=state.guideStep===guideSteps.length-1 && onboardingRequired() ? "Перейти до налаштування workspace" : state.guideStep===guideSteps.length-1 ? "Завершити" : "Далі →";
  document.querySelectorAll("[data-guide-step]").forEach(button=>button.onclick=()=>{state.guideStep=Number(button.dataset.guideStep);renderGuide();});
  localizeDom(document.querySelector("#guideOverlay"));
}
function openGuide(step=0){state.guideStep=Math.max(0,Math.min(guideSteps.length-1,step));renderGuide();document.querySelector("#guideOverlay").hidden=false;}
document.querySelector("#openGuide").onclick=()=>openGuide();
document.querySelector("#guideBack").onclick=()=>{if(state.guideStep>0){state.guideStep--;renderGuide();}};
document.querySelector("#guideDismiss").onclick=()=>{localStorage.setItem(guideDismissedKey(),"1");localStorage.setItem(guideStorageKey(),"done");document.querySelector("#guideOverlay").hidden=true;toast("Гайд більше не буде відкриватися автоматично. Він доступний у хедері.");if(onboardingRequired())showOnboarding(Math.max(1,Number(state.company.settings.onboarding_step||0)+1));};
document.querySelector("#guideNext").onclick=()=>{if(state.guideStep<guideSteps.length-1){state.guideStep++;renderGuide();return;}localStorage.setItem(guideStorageKey(),"done");document.querySelector("#guideOverlay").hidden=true;if(onboardingRequired())showOnboarding(Math.max(1,Number(state.company.settings.onboarding_step||0)+1));else toast("Гайд завершено. Він завжди доступний у хедері.");};

function updateTimeInput(value) {
  return value ? String(value).replace(" ", "T").slice(0, 16) : "";
}
function serviceUpdateFormFields(item = {}) {
  return `<div class="wide two-language-grid"><label>Заголовок українською<input name="title_uk" maxlength="160" value="${esc(item.title_uk||(!item.title_en?item.title||"":""))}" placeholder="Наприклад: Оновили календар і планування постів"></label>
    <label>English title<input name="title_en" maxlength="160" value="${esc(item.title_en||"")}" placeholder="Example: Calendar scheduling improved"></label>
    <label>Текст українською<textarea name="body_uk" maxlength="3000" placeholder="Коротко напишіть, що змінилось і кого це стосується.">${esc(item.body_uk||(!item.body_en?item.body||"":""))}</textarea></label>
    <label>English body<textarea name="body_en" maxlength="3000" placeholder="Briefly describe what changed and who it affects.">${esc(item.body_en||"")}</textarea></label></div>
    <input name="title" type="hidden" value="${esc(item.title_uk||item.title_en||item.title||"Оновлення сервісу")}"><input name="body" type="hidden" value="${esc(item.body_uk||item.body_en||item.body||"")}">
    <label>Тип<select name="category">${[["release","Нова функція"],["fix","Виправлення"],["maintenance","Технічні роботи"],["announcement","Оголошення"]].map(([value,label])=>`<option value="${value}" ${item.category===value?"selected":""}>${label}</option>`).join("")}</select></label>
    <label>Важливість<select name="importance">${[["info","Інформація"],["success","Позитивне оновлення"],["warning","Важливо"],["maintenance","Технічні роботи"]].map(([value,label])=>`<option value="${value}" ${item.importance===value?"selected":""}>${label}</option>`).join("")}</select></label>
    <label>Статус<select name="status">${[["published","Опубліковано"],["draft","Чернетка"],["archived","Архів"]].map(([value,label])=>`<option value="${value}" ${item.status===value?"selected":""}>${label}</option>`).join("")}</select></label>
    <label class="check-label"><input name="pinned" type="checkbox" ${item.pinned?"checked":""}> Закріпити зверху</label>
    <label>Показувати з<input name="visible_from" type="datetime-local" value="${esc(updateTimeInput(item.visible_from))}"></label>
    <label>Показувати до<input name="visible_until" type="datetime-local" value="${esc(updateTimeInput(item.visible_until))}"></label>
    <p class="wide field-help">Користувачі бачать тільки записи своєю мовою. Якщо заповнити лише українську, англійська лента не покаже це оновлення, і навпаки.</p>`;
}
async function reloadServiceUpdates({platform = false} = {}) {
  state.serviceUpdates = await api(platform && state.me?.is_super_admin ? "api/platform/service-updates" : `api/service-updates?locale=${encodeURIComponent(state.locale)}`);
  updateServiceUpdatesBadge();
  return state.serviceUpdates;
}
function openServiceUpdateEditor(item = null) {
  showForm(
    item ? "Редагувати оновлення" : "Нове повідомлення в ленту",
    serviceUpdateFormFields(item || {status:"published",category:"release",importance:"info"}),
    async form => {
      const payload = {
        title: form.get("title_uk") || form.get("title_en") || form.get("title"),
        body: form.get("body_uk") || form.get("body_en") || form.get("body"),
        title_uk: form.get("title_uk") || "",
        body_uk: form.get("body_uk") || "",
        title_en: form.get("title_en") || "",
        body_en: form.get("body_en") || "",
        category: form.get("category"),
        importance: form.get("importance"),
        status: form.get("status"),
        pinned: form.get("pinned") === "on",
        visible_from: form.get("visible_from") || "",
        visible_until: form.get("visible_until") || "",
      };
      await api(item ? `api/platform/service-updates/${item.id}` : "api/platform/service-updates", {
        method: item ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      await reloadServiceUpdates({platform:true});
      toast(item ? "Оновлення збережено" : "Оновлення опубліковано");
    },
    {submitLabel:item?"Зберегти":"Опублікувати"},
  );
}
async function openServiceUpdates() {
  const data = await reloadServiceUpdates({platform:state.me?.is_super_admin});
  const items = data.items || [];
  localStorage.setItem(serviceUpdatesStorageKey(), String(data.latest_id || 0));
  updateServiceUpdatesBadge();
  showForm(
    "Оновлення сервісу",
    `<div class="wide update-feed-head"><div><strong>Що нового в Content Studio</strong><p class="muted">Тут з’являються нові функції, виправлення, планові роботи та важливі оголошення.</p></div>${state.me?.is_super_admin?'<button type="button" class="primary" id="createServiceUpdate">＋ Додати повідомлення</button>':""}</div>
    <div class="wide service-update-list">${items.map(item=>`<article class="service-update-card ${esc(item.importance)} ${item.pinned?"pinned":""}"><div class="row between"><span class="pill ${item.category==="fix"?"ready":item.importance==="warning"?"needs_changes":"idea"}">${esc(serviceUpdateLabel(item.category))}</span><small>${esc(serviceUpdateDate(item.published_at||item.created_at))}</small></div><h3>${esc(item.title)}</h3>${item.body?`<p>${esc(item.body)}</p>`:""}<div class="service-update-meta">${item.pinned?"<span>Закріплено</span>":""}${item.status!=="published"?`<span>${esc(item.status)}</span>`:""}${item.created_by_display_name||item.created_by_username?`<span>${esc(item.created_by_display_name||item.created_by_username)}</span>`:""}</div>${state.me?.is_super_admin?`<div class="row"><button type="button" data-edit-service-update="${item.id}">Редагувати</button><button type="button" data-archive-service-update="${item.id}" ${item.status==="archived"?"disabled":""}>Архівувати</button></div>`:""}</article>`).join("") || '<div class="empty-state"><h3>Оновлень ще немає</h3><p class="muted">Коли з’являться нові функції або важливі повідомлення, вони будуть тут.</p></div>'}</div>`,
    null,
  );
  document.querySelector("#createServiceUpdate")?.addEventListener("click",()=>openServiceUpdateEditor());
  document.querySelectorAll("[data-edit-service-update]").forEach(button=>button.onclick=()=>openServiceUpdateEditor(items.find(item=>String(item.id)===String(button.dataset.editServiceUpdate))));
  document.querySelectorAll("[data-archive-service-update]").forEach(button=>button.onclick=async()=>{
    const item = items.find(row=>String(row.id)===String(button.dataset.archiveServiceUpdate));
    if(!item || !confirm(`Архівувати повідомлення «${item.title}»?`))return;
    await api(`api/platform/service-updates/${item.id}`,{method:"PUT",body:JSON.stringify({...item,status:"archived",visible_from:item.visible_from||"",visible_until:item.visible_until||""})});
    await openServiceUpdates();
  });
}
document.querySelector("#serviceUpdatesButton").onclick=()=>openServiceUpdates().catch(error=>toast(error.message,true));

function openNotifications() {
  const items = notificationItems({includeRead:true});
  const unreadCount = items.filter(item => !item.read).length;
  showForm(
    "Сповіщення",
    items.length ? `<div class="wide notification-toolbar"><span>${unreadCount ? `Непрочитаних: ${unreadCount}` : "Усі сповіщення прочитані"}</span><button type="button" id="readAllNotifications" ${unreadCount ? "" : "disabled"}>Прочитати все</button></div>${items.map(item=>`<article class="wide notification-item ${item.type} ${item.read?"read":""}"><div class="row between"><strong>${esc(item.title)}</strong>${item.read?'<span class="notification-read-label">Прочитано</span>':""}</div><p>${esc(item.text)}</p><small>${esc(item.action)}</small>${item.jobId?`<button type="button" data-retry-job="${item.jobId}">Повторити швидку генерацію</button>`:""}</article>`).join("")}` : `<div class="wide empty-state"><h3>Все гаразд</h3><p class="muted">Немає помилок генерації, попереджень про тариф або бюджет.</p></div>`,
    null,
  );
  document.querySelector("#readAllNotifications")?.addEventListener("click", () => {
    saveReadNotificationKeys(new Set(items.map(item => item.key)));
    updateNotificationBadge();
    openNotifications();
  });
  document.querySelectorAll("[data-retry-job]").forEach(button => button.onclick = async () => {
    await loading(button, async () => {
      const readKeys = readNotificationKeys();
      readKeys.delete(`failed-job:${button.dataset.retryJob}`);
      saveReadNotificationKeys(readKeys);
      await api(`api/jobs/${button.dataset.retryJob}/retry-fast`, {method:"POST"});
      toast("Генерацію перезапущено");
      document.querySelector("#formOverlay").hidden = true;
      await refresh();
    }, "Запускаємо…");
  });
}
document.querySelector("#notificationsButton").onclick=openNotifications;
document.querySelector("#exportPlan").onclick=()=>chooseExport((state.data.ideas||[]).filter(x=>x.plan_id),"content-plan",["planned_for","title","product","status"]);
document.querySelector("#exportDrafts").onclick=()=>chooseExport(state.data.drafts||[],"drafts",["id","title","product","status","scheduled_at"]);
document.querySelector("#exportUsage").onclick=()=>chooseExport(state.data.daily||[],"usage",["day","cost"]);
window.addEventListener("popstate",()=>applyLocationRoute());
const initialRoute = readRouteState();
state.view = initialRoute.view;
history.replaceState(
  initialRoute.draftId
    ? {draftId:initialRoute.draftId,fromView:"drafts"}
    : {view:initialRoute.view},
  "",
  initialRoute.draftId ? location.href : urlForView(initialRoute.view),
);
refresh().then(()=>{
  if(!onboardingRequired()&&!localStorage.getItem(guideStorageKey())&&!localStorage.getItem(guideDismissedKey())&&["completed","skipped"].includes(state.company?.settings?.onboarding_status)){
    setTimeout(()=>openGuide(),500);
  }
});
setInterval(()=>refresh(true),30000);
