import base64
from pathlib import Path
from textwrap import wrap
from uuid import uuid4

from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageFont

from voicerhub_bot.visual_templates import get_visual_template


BASE_VISUAL_RULES = """
Create a premium 3:2 editorial image for a Ukrainian B2B technology company.
Show the actual business concept clearly. Do not render letters, captions,
watermarks, logos or unreadable UI text. Keep the composition professional,
credible and suitable for a Telegram channel.
""".strip()


class ImageGenerator:
    def __init__(
        self,
        api_key: str,
        image_model: str,
        output_dir: Path,
        logo_path: Path | None = None,
    ) -> None:
        self.client = AsyncOpenAI(api_key=api_key)
        self.image_model = image_model
        self.output_dir = output_dir
        self.logo_path = logo_path

    async def generate(
        self,
        title: str,
        prompt: str,
        *,
        model: str | None = None,
        reference_paths: list[Path] | None = None,
        template_id: str = "editorial-dark",
        logo_path: Path | None = None,
        company_logo_path: Path | None = None,
        template: dict | None = None,
        size: str = "1536x1024",
        output_size: tuple[int, int] | None = None,
        platform: str = "Telegram",
    ) -> tuple[Path, object]:
        selected_model = model or self.image_model
        template = template or get_visual_template(template_id)
        full_prompt = (
            f"{BASE_VISUAL_RULES}\nTarget platform: {platform}. "
            "Compose the subject for the target aspect ratio.\n\n"
            f"Visual direction:\n{template['prompt']}"
            f"\n\nSubject:\n{prompt}"
        )
        if reference_paths:
            full_prompt += (
                "\n\nUse the supplied images as exact brand and product references. "
                "Preserve logos, distinctive shapes, colors, and identity faithfully. "
                "Integrate them naturally into a new premium editorial composition."
            )
            response = await self.client.images.edit(
                model=selected_model,
                image=reference_paths,
                prompt=full_prompt,
                size=size,
                quality="medium",
                output_format="png",
            )
        else:
            response = await self.client.images.generate(
                model=selected_model,
                prompt=full_prompt,
                size=size,
                quality="medium",
                output_format="png",
            )
        encoded_image = response.data[0].b64_json
        if not encoded_image:
            raise ValueError("The image API did not return base64 image data.")
        image_bytes = base64.b64decode(encoded_image)
        output_path = self.output_dir / f"{uuid4().hex}.png"
        output_path.write_bytes(image_bytes)
        if output_size:
            self._fit_output(output_path, output_size)
        self._apply_branding(
            output_path,
            title,
            template_id=template_id,
            logo_path=logo_path,
            company_logo_path=company_logo_path,
            template=template,
        )
        return output_path, response

    @staticmethod
    def _fit_output(image_path: Path, output_size: tuple[int, int]) -> None:
        image = Image.open(image_path).convert("RGB")
        target_width, target_height = output_size
        source_ratio = image.width / image.height
        target_ratio = target_width / target_height
        if source_ratio > target_ratio:
            crop_width = int(image.height * target_ratio)
            left = (image.width - crop_width) // 2
            image = image.crop((left, 0, left + crop_width, image.height))
        else:
            crop_height = int(image.width / target_ratio)
            top = (image.height - crop_height) // 2
            image = image.crop((0, top, image.width, top + crop_height))
        image.resize(output_size, Image.Resampling.LANCZOS).save(
            image_path,
            format="PNG",
            optimize=True,
        )

    def _apply_branding(
        self,
        image_path: Path,
        title: str,
        *,
        template_id: str = "editorial-dark",
        logo_path: Path | None = None,
        company_logo_path: Path | None = None,
        template: dict | None = None,
    ) -> None:
        template = template or get_visual_template(template_id)
        image = Image.open(image_path).convert("RGBA")
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        width, height = image.size
        accent = _hex_color(template["accent"])
        layout = template["layout"]

        if layout == "left_panel":
            draw.rectangle((0, 0, int(width * 0.52), height), fill=(4, 11, 29, 180))
            text_x, text_y, max_chars = 70, 100, 25
        elif layout == "bottom_left":
            draw.rectangle((0, int(height * 0.57), width, height), fill=(4, 11, 29, 175))
            text_x, text_y, max_chars = 70, int(height * 0.65), 31
        elif layout == "top_band":
            draw.rectangle((0, 0, width, int(height * 0.34)), fill=(4, 11, 29, 175))
            text_x, text_y, max_chars = 72, 72, 34
        else:
            draw.rectangle((0, 0, width, int(height * 0.42)), fill=(4, 11, 29, 155))
            text_x, text_y, max_chars = 82, 90, 29
        draw.rectangle((0, 0, 14, height), fill=(*accent, 255))

        title_font = _load_font(58)
        lines = wrap(title.upper(), width=max_chars)[:3]
        y = text_y
        for line in lines:
            draw.text((text_x, y), line, font=title_font, fill=(255, 255, 255, 255))
            y += 72

        selected_logo = logo_path if logo_path and logo_path.is_file() else None
        if selected_logo:
            logo = Image.open(selected_logo).convert("RGBA")
            logo.thumbnail((360, 110))
            overlay.alpha_composite(
                logo,
                (width - logo.width - 55, height - logo.height - 42),
            )

        selected_company_logo = (
            company_logo_path
            if company_logo_path and company_logo_path.is_file()
            else None
        )
        if selected_company_logo and selected_company_logo.is_file():
            company_logo = Image.open(selected_company_logo).convert("RGBA")
            company_logo.thumbnail((290, 85))
            overlay.alpha_composite(
                company_logo,
                (width - company_logo.width - 55, 42),
            )

        Image.alpha_composite(image, overlay).convert("RGB").save(
            image_path,
            format="PNG",
            optimize=True,
        )


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _hex_color(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
