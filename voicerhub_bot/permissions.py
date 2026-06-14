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
