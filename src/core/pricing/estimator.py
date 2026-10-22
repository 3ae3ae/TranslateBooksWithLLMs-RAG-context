SYSTEM_PROMPT_TOKENS = 500
USER_TEMPLATE_TOKENS = 60

LANGUAGE_RATIOS = {
    ("english", "french"):  (1.15, 1.50),
    ("english", "spanish"): (1.15, 1.50),
    ("english", "italian"): (1.15, 1.50),
    ("english", "portuguese"): (1.15, 1.50),
    ("english", "german"):  (1.10, 1.40),
    ("english", "dutch"):   (1.05, 1.30),
    ("english", "russian"): (1.10, 1.45),
    ("english", "japanese"): (1.30, 1.80),
    ("english", "chinese"): (0.50, 0.80),
    ("english", "korean"):  (1.10, 1.50),
    ("english", "arabic"):  (1.10, 1.45),
    ("french", "english"):  (0.75, 0.95),
    ("german", "english"):  (0.80, 1.00),
    ("spanish", "english"): (0.80, 1.00),
    ("japanese", "english"): (1.50, 2.50),
    ("chinese", "english"): (1.50, 2.50),
    ("chinese", "french"):  (1.80, 2.80),
    ("chinese", "german"):  (1.80, 2.80),
    ("japanese", "french"): (1.80, 2.80),
}

DEFAULT_RATIO = (0.95, 1.30)


def get_output_ratio(src_lang: str, tgt_lang: str) -> tuple[float, float]:
    if not src_lang or not tgt_lang:
        return DEFAULT_RATIO
    key = (src_lang.lower().strip(), tgt_lang.lower().strip())
    return LANGUAGE_RATIOS.get(key, DEFAULT_RATIO)
