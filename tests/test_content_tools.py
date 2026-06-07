from voicerhub_bot.content_tools import (
    _PageTextParser,
    closest_duplicate,
    normalize_terminology,
    shorten_caption,
    similarity_score,
)


def test_similarity_detects_rephrased_topic() -> None:
    score = similarity_score(
        "Як TONY аналізує інтонацію в дзвінках",
        "Аналіз інтонації дзвінків за допомогою TONY",
    )

    assert score >= 0.62


def test_closest_duplicate_returns_existing_id() -> None:
    score, duplicate_id = closest_duplicate(
        "Контроль якості дзвінків",
        "Як автоматично перевіряти розмови за чек-листами",
        [
            {
                "id": 17,
                "title": "Автоматичний контроль дзвінків",
                "angle": "Перевірка розмов за налаштованими чек-листами",
            }
        ],
    )

    assert score >= 0.62
    assert duplicate_id == 17


def test_terminology_and_shortening() -> None:
    value = normalize_terminology("Tony працює у VoiceHub разом з PowerBi")
    assert value == "TONY працює у VoicerHub разом з Power BI"
    assert len(shorten_caption("слово " * 400)) <= 950


def test_page_parser_reads_meta_and_application_json() -> None:
    parser = _PageTextParser()
    parser.feed(
        """
        <meta name="description" content="Аналітика комунікацій для контролю якості">
        <script type="application/json">{"content":"TONY аналізує дзвінки та чати"}</script>
        """
    )

    result = " ".join(parser.parts)
    assert "Аналітика комунікацій" in result
    assert "TONY аналізує дзвінки" in result
