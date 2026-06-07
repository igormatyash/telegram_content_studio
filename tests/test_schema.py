from voicerhub_bot.models import GeneratedPost


def test_generated_post_schema_is_strict_batch_compatible() -> None:
    schema = GeneratedPost.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "product",
        "title",
        "lead",
        "body",
        "bullets",
        "cta",
        "hashtags",
        "image_prompt",
        "title_options",
        "cta_options",
    }
