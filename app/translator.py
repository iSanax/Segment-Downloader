import gettext
import logging
from pathlib import Path


SUPPORTED_LANGUAGES = ("en", "pl")
DEFAULT_LANGUAGE = "en"
LANG_DIRECTORY = (
    Path(__file__).resolve().parent.parent
    / "lang"
    / "bin"
)
LOGGER = logging.getLogger(
    "SegmentDownloader.translator"
)

_current_language = DEFAULT_LANGUAGE
_translation = gettext.NullTranslations()


def set_language(language):
    global _current_language
    global _translation

    normalized_language = str(language).lower()

    if normalized_language not in SUPPORTED_LANGUAGES:
        normalized_language = DEFAULT_LANGUAGE

    translation_path = (
        LANG_DIRECTORY
        / f"{normalized_language}.mo"
    )

    try:
        with translation_path.open("rb") as file:
            _translation = gettext.GNUTranslations(
                file
            )

    except FileNotFoundError:
        _translation = gettext.NullTranslations()

        LOGGER.warning(
            "Translation file not found for language '%s': %s",
            normalized_language,
            translation_path
        )

    except (OSError, UnicodeError) as error:
        _translation = gettext.NullTranslations()

        LOGGER.error(
            "Failed to load language '%s' (%s).",
            normalized_language,
            type(error).__name__
        )

    _current_language = normalized_language

    LOGGER.info(
        "Language selected: %s.",
        _current_language
    )

    return _current_language


def get_language():
    return _current_language


def translate(message):
    return _translation.gettext(message)
