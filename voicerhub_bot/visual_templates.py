VISUAL_TEMPLATES = [
    {
        "id": "editorial-dark",
        "name": "Editorial Dark",
        "description": "Темний технологічний кадр із великим заголовком.",
        "prompt": "Cinematic dark editorial technology photography, deep navy environment, crisp cyan accents, realistic business context, controlled contrast, calm upper-left negative space.",
        "layout": "top_left",
        "accent": "#18ecd6",
    },
    {
        "id": "clean-light",
        "name": "Clean Light",
        "description": "Світла корпоративна композиція з чистим простором.",
        "prompt": "Bright premium corporate editorial photography, white and soft gray architecture, natural daylight, restrained cyan and blue details, minimal composition, generous negative space.",
        "layout": "bottom_left",
        "accent": "#087f8c",
    },
    {
        "id": "data-dashboard",
        "name": "Data Dashboard",
        "description": "Інтерфейси, метрики та бізнес-аналітика.",
        "prompt": "Sophisticated business intelligence scene with realistic dashboards, charts and structured data layers, sharp product visualization, dark neutral background, no readable UI text.",
        "layout": "top_left",
        "accent": "#ffb547",
    },
    {
        "id": "human-at-work",
        "name": "Human at Work",
        "description": "Людина в реальному робочому процесі.",
        "prompt": "Authentic documentary-style workplace scene with one professional actively using technology, natural posture and believable environment, premium commercial photography, no staged handshake.",
        "layout": "left_panel",
        "accent": "#18ecd6",
    },
    {
        "id": "isometric-system",
        "name": "Isometric System",
        "description": "Об’ємна схема процесу або екосистеми.",
        "prompt": "Premium isometric 3D system visualization, connected modules, precise geometry, subtle depth, professional product-design rendering, navy, cyan, white and one warm accent.",
        "layout": "top_left",
        "accent": "#6ee7d8",
    },
    {
        "id": "abstract-signal",
        "name": "Abstract Signal",
        "description": "Хвилі голосу, сигнали та потоки даних.",
        "prompt": "Elegant abstract signal visualization with voice waves and flowing data trails, refined glass and light materials, strong central rhythm, premium technology editorial art.",
        "layout": "bottom_left",
        "accent": "#38bdf8",
    },
    {
        "id": "product-hero",
        "name": "Product Hero",
        "description": "Акцент на продукті, логотипі або інтерфейсі.",
        "prompt": "High-end product hero composition, one clear central product or interface focal point, studio lighting, precise materials, minimal background, premium launch-key-visual quality.",
        "layout": "top_band",
        "accent": "#18ecd6",
    },
    {
        "id": "industry-scene",
        "name": "Industry Scene",
        "description": "Логістика, ритейл, контакт-центр або інша галузь.",
        "prompt": "Realistic industry environment with technology integrated into actual operations, cinematic but credible, clear operational details, premium B2B campaign photography.",
        "layout": "left_panel",
        "accent": "#f5a524",
    },
    {
        "id": "editorial-collage",
        "name": "Editorial Collage",
        "description": "Динамічний журнальний колаж із кількох сцен.",
        "prompt": "Contemporary editorial collage combining two or three coherent business moments, clean cut-paper geometry, sophisticated magazine art direction, strong hierarchy, no decorative clutter.",
        "layout": "top_band",
        "accent": "#18ecd6",
    },
    {
        "id": "blueprint",
        "name": "Technical Blueprint",
        "description": "Технічна схема з лініями та пояснювальною логікою.",
        "prompt": "Technical blueprint-inspired visualization with precise lines, system nodes and process structure, dark graphite background, cyan drafting marks, polished and highly legible composition.",
        "layout": "bottom_left",
        "accent": "#4cc9f0",
    },
    {
        "id": "warm-business",
        "name": "Warm Business",
        "description": "Теплий людяний стиль без типового темного AI-візуалу.",
        "prompt": "Warm modern business editorial photography, natural sunlight, balanced neutral colors with restrained teal details, approachable human atmosphere, credible and polished.",
        "layout": "top_left",
        "accent": "#f59e0b",
    },
    {
        "id": "minimal-object",
        "name": "Minimal Object",
        "description": "Один символ або об’єкт на чистому фоні.",
        "prompt": "Minimal conceptual still life with one strong symbolic object representing the business idea, refined studio background, subtle shadows, premium advertising art direction.",
        "layout": "bottom_left",
        "accent": "#18ecd6",
    },
]

DEFAULT_TEMPLATE_ID = "editorial-dark"


def get_visual_template(template_id: str) -> dict:
    return next(
        (item for item in VISUAL_TEMPLATES if item["id"] == template_id),
        VISUAL_TEMPLATES[0],
    )
