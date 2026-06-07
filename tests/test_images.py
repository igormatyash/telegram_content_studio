from pathlib import Path

from PIL import Image

from voicerhub_bot.images import ImageGenerator


def test_branding_ignores_directory_as_logo_path(tmp_path: Path) -> None:
    image_path = tmp_path / "generated.png"
    Image.new("RGB", (1536, 1024), (10, 20, 40)).save(image_path)
    generator = ImageGenerator("test", "gpt-image-1.5", tmp_path, tmp_path)

    generator._apply_branding(image_path, "Тестовий заголовок")

    assert Image.open(image_path).size == (1536, 1024)


def test_gpt_image_2_edit_does_not_send_input_fidelity(tmp_path: Path) -> None:
    generator = ImageGenerator("test", "gpt-image-2", tmp_path)
    reference = tmp_path / "reference.png"
    Image.new("RGB", (10, 10), (0, 180, 160)).save(reference)
    captured = {}

    class FakeImages:
        async def edit(self, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop after request capture")

    generator.client.images = FakeImages()

    import asyncio

    try:
        asyncio.run(
            generator.generate(
                "Заголовок",
                "Premium logistics control room",
                reference_paths=[reference],
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "stop after request capture"

    assert captured["model"] == "gpt-image-2"
    assert "input_fidelity" not in captured


def test_selected_logo_is_composited_on_result(tmp_path: Path) -> None:
    image_path = tmp_path / "generated.png"
    logo_path = tmp_path / "logo.png"
    Image.new("RGB", (1536, 1024), (10, 20, 40)).save(image_path)
    Image.new("RGBA", (220, 70), (230, 20, 40, 255)).save(logo_path)
    generator = ImageGenerator("test", "gpt-image-2", tmp_path)

    generator._apply_branding(
        image_path,
        "Тестовий заголовок",
        template_id="clean-light",
        logo_path=logo_path,
    )

    result = Image.open(image_path).convert("RGB")
    assert result.getpixel((1300, 920))[0] > 180


def test_transparent_logo_keeps_transparent_area(tmp_path: Path) -> None:
    image_path = tmp_path / "generated.png"
    logo_path = tmp_path / "transparent-logo.png"
    Image.new("RGB", (1536, 1024), (10, 20, 40)).save(image_path)
    logo = Image.new("RGBA", (220, 70), (0, 0, 0, 0))
    for x in range(50, 170):
        for y in range(10, 60):
            logo.putpixel((x, y), (230, 20, 40, 255))
    logo.save(logo_path)

    generator = ImageGenerator("test", "gpt-image-2", tmp_path)
    generator._apply_branding(image_path, "Тест", logo_path=logo_path)

    result = Image.open(image_path).convert("RGB")
    assert result.getpixel((1270, 920)) == (10, 20, 40)
    assert result.getpixel((1350, 940))[0] > 180


def test_company_logo_is_not_added_unless_selected(tmp_path: Path) -> None:
    image_path = tmp_path / "generated.png"
    baseline_path = tmp_path / "baseline.png"
    configured_logo = tmp_path / "configured-logo.png"
    Image.new("RGB", (1536, 1024), (10, 20, 40)).save(image_path)
    Image.new("RGB", (1536, 1024), (10, 20, 40)).save(baseline_path)
    Image.new("RGBA", (220, 70), (230, 20, 40, 255)).save(configured_logo)
    generator = ImageGenerator(
        "test",
        "gpt-image-2",
        tmp_path,
        configured_logo,
    )

    generator._apply_branding(image_path, "Тест")
    ImageGenerator("test", "gpt-image-2", tmp_path)._apply_branding(
        baseline_path,
        "Тест",
    )

    result = Image.open(image_path).convert("RGB")
    baseline = Image.open(baseline_path).convert("RGB")
    assert result.getpixel((1300, 60)) == baseline.getpixel((1300, 60))
