from __future__ import annotations


WORKSPACE_PERMISSIONS = {
    "content.view",
    "content.create",
    "content.edit",
    "content.delete",
    "content.publish",
    "content.schedule",
    "ideas.create",
    "ideas.delete",
    "calendar.manage",
    "brand.view",
    "brand.edit",
    "rubrics.manage",
    "visual_styles.manage",
    "brand_materials.manage",
    "users.view",
    "users.invite",
    "users.remove",
    "roles.manage",
    "channels.manage",
    "expenses.view",
    "billing.manage",
    "workspace.settings",
}

PERMISSION_DETAILS = {
    "content.view": (
        "Перегляд контенту",
        "Дозволяє переглядати ідеї, чернетки, готові та опубліковані матеріали.",
    ),
    "content.create": (
        "Створення контенту",
        "Дозволяє створювати нові чернетки вручну або за допомогою AI.",
    ),
    "content.edit": (
        "Редагування контенту",
        "Дозволяє змінювати заголовки, тексти, візуали та статуси чернеток.",
    ),
    "content.delete": (
        "Видалення контенту",
        "Дозволяє видаляти чернетки та інші матеріали поточного workspace.",
    ),
    "content.publish": (
        "Публікація контенту",
        "Дозволяє публікувати готові матеріали у підключених каналах.",
    ),
    "content.schedule": (
        "Планування публікацій",
        "Дозволяє призначати дату публікації та знімати матеріали з розкладу.",
    ),
    "ideas.create": (
        "Створення ідей",
        "Дозволяє додавати і генерувати нові ідеї для контенту.",
    ),
    "ideas.delete": (
        "Видалення ідей",
        "Дозволяє видаляти окремі або вибрані ідеї.",
    ),
    "calendar.manage": (
        "Керування календарем",
        "Дозволяє додавати, переносити та скасовувати заплановані публікації.",
    ),
    "brand.view": (
        "Перегляд бренду",
        "Дозволяє переглядати профіль компанії, tone of voice та бренд-матеріали.",
    ),
    "brand.edit": (
        "Редагування бренду",
        "Дозволяє змінювати профіль компанії, tone of voice та оформлення workspace.",
    ),
    "rubrics.manage": (
        "Керування рубриками",
        "Дозволяє створювати, редагувати, активувати та видаляти рубрики.",
    ),
    "visual_styles.manage": (
        "Керування візуальними стилями",
        "Дозволяє налаштовувати стилі, які AI використовує для генерації зображень.",
    ),
    "brand_materials.manage": (
        "Керування матеріалами бренду",
        "Дозволяє завантажувати, редагувати та видаляти логотипи, брендбуки й референси.",
    ),
    "users.view": (
        "Перегляд користувачів",
        "Дозволяє бачити команду workspace та призначені ролі.",
    ),
    "users.invite": (
        "Запрошення користувачів",
        "Дозволяє запрошувати нових учасників до workspace.",
    ),
    "users.remove": (
        "Видалення користувачів",
        "Дозволяє деактивувати або видаляти учасників із workspace.",
    ),
    "roles.manage": (
        "Керування ролями",
        "Дозволяє змінювати ролі користувачів у межах доступного рівня.",
    ),
    "channels.manage": (
        "Керування каналами",
        "Дозволяє підключати, перевіряти та змінювати Telegram-канали.",
    ),
    "expenses.view": (
        "Перегляд витрат",
        "Дозволяє переглядати AI-витрати, використання моделей і ліміти.",
    ),
    "billing.manage": (
        "Керування тарифом",
        "Дозволяє керувати тарифом, бюджетами та платіжними налаштуваннями workspace.",
    ),
    "workspace.settings": (
        "Налаштування workspace",
        "Дозволяє змінювати назву, режим роботи, оформлення та загальні параметри.",
    ),
}

ROLE_PERMISSIONS = {
    "owner": set(WORKSPACE_PERMISSIONS),
    "admin": set(WORKSPACE_PERMISSIONS) - {"billing.manage"},
    "content_manager": {
        "content.view",
        "content.create",
        "content.edit",
        "content.delete",
        "ideas.create",
        "ideas.delete",
        "brand.view",
        "rubrics.manage",
        "visual_styles.manage",
        "brand_materials.manage",
        "calendar.manage",
        "expenses.view",
    },
    "editor": {
        "content.view",
        "content.edit",
        "brand.view",
        "expenses.view",
    },
    "publisher": {
        "content.view",
        "content.publish",
        "content.schedule",
        "calendar.manage",
        "brand.view",
    },
    "viewer": {
        "content.view",
        "brand.view",
        "expenses.view",
    },
}

ROLE_LABELS = {
    "owner": "Власник",
    "admin": "Адміністратор",
    "content_manager": "Контент-менеджер",
    "editor": "Редактор",
    "publisher": "Публікатор",
    "viewer": "Переглядач",
}

ROLE_DESCRIPTIONS = {
    "owner": "Повний контроль workspace, команди, бренду, каналів і тарифу.",
    "admin": "Керує контентом, брендом, каналами та командою без критичних дій власника.",
    "content_manager": "Створює ідеї, плани, чернетки та готує матеріали до перевірки.",
    "editor": "Редагує чернетки, погоджує матеріали та повертає їх на доопрацювання.",
    "publisher": "Планує та публікує готові матеріали в підключені канали.",
    "viewer": "Переглядає контент, календар, бренд і витрати без права змін.",
}

WORKSPACE_ROLES = set(ROLE_PERMISSIONS)


def permissions_for(role: str, *, platform_admin: bool = False) -> set[str]:
    if platform_admin:
        return set(WORKSPACE_PERMISSIONS) | {"platform.view", "platform.manage"}
    return set(ROLE_PERMISSIONS.get(role, set()))


def has_permission(
    role: str,
    permission: str,
    *,
    platform_admin: bool = False,
) -> bool:
    return permission in permissions_for(role, platform_admin=platform_admin)


def role_catalog() -> list[dict]:
    return [
        {
            "id": role,
            "label": ROLE_LABELS[role],
            "description": ROLE_DESCRIPTIONS[role],
            "permissions": sorted(ROLE_PERMISSIONS[role]),
            "permission_details": [
                {
                    "key": permission,
                    "label": PERMISSION_DETAILS[permission][0],
                    "description": PERMISSION_DETAILS[permission][1],
                }
                for permission in sorted(ROLE_PERMISSIONS[role])
            ],
        }
        for role in (
            "owner",
            "admin",
            "content_manager",
            "editor",
            "publisher",
            "viewer",
        )
    ]
