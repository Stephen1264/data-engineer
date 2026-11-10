"""葡语短句的高精度证据规则及分流信号。"""

import re

CATEGORIES = (
    "delivery_late", "wrong_product", "quality_defect", "missing_item",
    "seller_communication", "packaging", "other",
)
SEVERITIES = ("low", "medium", "high")
SELLER_ACTIONS = set(CATEGORIES) - {"delivery_late", "other"}

# 每个英文短语只翻译它匹配的葡语片段，保留原始大小写和重音作为证据。
PATTERNS = {
    "delivery_late": (
        ("high", r"(?:ainda )?n[ãa]o recebi (?:o |meu )?produto(?!\s+(?:correto|certo|que|solicitado))",
         "I have not received the product"),
        ("high", r"(?:ainda )?n[ãa]o recebi (?:o |meu )pedido(?!\s+(?:correto|certo|que|solicitado))",
         "I have not received the order"),
        ("high", r"(?:ainda )?n[ãa]o recebi (?:a|minha) mercadoria", "I have not received the goods"),
        ("high", r"^(?:pq |porque )?n[ãa]o entregou(?=[.!?\s]*$)", "It was not delivered"),
        ("high", r"n[ãa]o recebi[.!?]+\s+passou o dia de entrega", "I did not receive it. The delivery date has passed"),
        ("high", r"(?:ainda )?n[ãa]o (?:foi entregue|chegou)(?=[.!?\s]*$)", "It has not arrived"),
        ("high", r"produto n[ãa]o (?:foi )?entregue", "The product was not delivered"),
        ("high", r"pedido n[ãa]o (?:foi )?entregue", "The order was not delivered"),
        ("high", r"n[ãa]o envi(?:ou|aram) (?:o |meu )?pedido", "The order was not shipped"),
        ("high", r"(?:pedido|produto) (?:ainda )?n[ãa]o chegou", "It has not arrived"),
        ("high", r"(?:a |minha )?compra (?:ainda )?n[ãa]o chegou", "The purchase has not arrived"),
        ("medium", r"(?:foi )?entregue com atraso", "Delivered late"),
        ("medium", r"recebi (?:o )?produto com atraso", "I received the product late"),
        ("medium", r"produto (?:est[áa] )?em atraso", "The product is overdue"),
        ("medium", r"pedido (?:est[áa] )?em atraso", "The order is overdue"),
        ("medium", r"j[áa] passou do prazo", "The deadline has already passed"),
        ("medium", r"atraso na entrega", "Delivery delay"),
        ("medium", r"demora na entrega", "Slow delivery"),
        ("medium", r"entrega atrasou", "Delivery was late"),
        ("medium", r"chegou atrasad[oa]", "It arrived late"),
        ("medium", r"entrega fora do prazo", "Delivery after the deadline"),
    ),
    "wrong_product": (
        ("high", r"recebi (?:o |um )?produto errado", "I received the wrong product"),
        ("high", r"veio (?:o |um )?produto errado", "The wrong product arrived"),
        ("high", r"enviaram (?:o |um )?produto errado", "They sent the wrong product"),
        ("medium", r"produto diferente do anunciado", "Product different from the listing"),
        ("medium", r"produto diferente da foto anunciada", "Product different from the advertised photo"),
        ("medium", r"mercadoria veio errada", "The wrong goods arrived"),
        ("medium", r"pedido veio errado", "The wrong order arrived"),
        ("medium", r"produto (?:totalmente )?diferente do solicitado", "Product different from what was requested"),
        ("high", r"(?:mandou|mandaram) errado", "They sent the wrong one"),
        ("medium", r"cor diferente da solicitada", "Color different from the one requested"),
        ("medium", r"modelo errado", "Wrong model"),
        ("medium", r"tamanho errado", "Wrong size"),
    ),
    "quality_defect": (
        ("high", r"(?:veio|chegou) quebrad[oa]", "It arrived broken"),
        ("high", r"(?:veio|chegou) com defeito", "It arrived defective"),
        ("high", r"(?:veio|chegou) com o vidro quebrado", "It arrived with broken glass"),
        ("high", r"(?:veio|chegou) com a tela quebrada", "It arrived with a broken screen"),
        ("high", r"microfone (?:totalmente )?quebrado", "Broken microphone"),
        ("medium", r"arranh[õo]es (?:no corpo|na carca[çc]a)", "Scratches on the casing"),
        ("medium", r"(?:o )?adesivo (?:das medidas )?descolado", "The label had come unstuck"),
        ("medium", r"apresenta avarias em seus componentes", "Its components are damaged"),
        ("medium", r"baterias que vieram gastas", "The batteries arrived drained"),
        ("high", r"parou de funcionar", "It stopped working"),
        ("medium", r"p[ée]ssima qualidade", "Terrible quality"),
        ("medium", r"baixa qualidade", "Poor quality"),
    ),
    "missing_item": (
        ("high", r"comprei (?:dois|duas|2) (?:produtos|unidades) e (?:s[óo]|apenas|somente) recebi (?:um|uma|1)",
         "I bought two items and received only one"),
        ("high", r"comprei (?:tr[eê]s|3) (?:produtos|unidades) e vieram (?:s[óo]|apenas|somente) (?:dois|duas|2)",
         "I bought three items and only two arrived"),
        ("high", r"veio faltando", "It arrived with something missing"),
        ("high", r"faltou uma pe[çc]a", "A part was missing"),
        ("high", r"faltou um item", "An item was missing"),
        ("high", r"faltou um produto", "A product was missing"),
        ("high", r"n[ãa]o recebi (?:um|uma) dos produtos", "I did not receive one of the products"),
        ("high", r"recebi (?:somente|apenas|s[óo]) (?:um|1) item", "I received only one item"),
        ("high", r"aguardo a entrega do segundo produto", "I am waiting for the second product to be delivered"),
        ("high", r"n[ãa]o veio o manual", "The manual did not come"),
        ("high", r"(?:veio|chegou) a\s?penas um(?=\s+e|[.!?\s]*$)", "Only one arrived"),
        ("high", r"pedido (?:veio |chegou )?incompleto", "The order was incomplete"),
    ),
    "seller_communication": (
        ("medium", r"(?:o )?vendedor n[ãa]o (?:me )?respondeu", "The seller did not reply"),
        ("medium", r"sem retorno do vendedor", "No reply from the seller"),
        ("medium", r"n[ãa]o consigo (?:entrar em contato com|contatar) (?:o )?vendedor", "I cannot contact the seller"),
        ("medium", r"cancelou sem avisar", "They canceled without notifying me"),
    ),
    "packaging": (
        ("medium", r"embalagem (?:estava )?danificada", "The packaging was damaged"),
        ("medium", r"caixa (?:estava |chegou )?amassada", "The box was dented"),
        ("medium", r"embalagem totalmente sem seguran[çc]a", "The packaging provided no protection"),
        ("medium", r"solt[oa] dentro da caixa", "Loose inside the box"),
        ("medium", r"caixa (?:estava |veio )?(?:toda )?rasgada", "The box was torn"),
        ("medium", r"embalagem (?:ficou |foi )?(?:toda )?amassada", "The packaging was dented"),
        ("medium", r"mal embalad[oa]", "Poorly packaged"),
    ),
    "other": (
        ("medium", r"(?:a )?compra foi cancelada", "The purchase was canceled"),
        ("medium", r"n[ãa]o foi entregue na minha casa", "It was not delivered to my home"),
        ("medium", r"tive que ir retirar", "I had to go and pick it up"),
        ("medium", r"chave de NF-e inv[áa]lida", "Invalid electronic invoice key"),
    ),
}
RULES = [
    (category, severity, re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE), translation)
    for category, entries in PATTERNS.items()
    for severity, pattern, translation in entries
]
CLUES = {
    "delivery_late": r"atras|prazo|entreg|recebi|chegou",
    "wrong_product": r"errad|diferente|cor\b|tamanho|modelo",
    "quality_defect": r"quebrad|defeito|qualidade|funcion|rasgad",
    "missing_item": r"falt|incompleto|apenas|somente|quantidade",
    "seller_communication": r"vendedor|contato|respond|retorno",
    "packaging": r"embalag|caixa|embalad",
}
CLUE_RULES = {key: re.compile(value, re.IGNORECASE) for key, value in CLUES.items()}
TIME_EVIDENCE = re.compile(r"atras|prazo|dia de entrega|demora", re.IGNORECASE)
POSITIVE_SHORT = re.compile(
    r"(?:muito )?(?:bom|boa)|bom produto|[óo]tim[oa]|excelente|recomendo|gostei|satisfeit[oa]", re.IGNORECASE,
)
PRIVATE_QUOTE = re.compile(
    r"https?://|[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:\d[\s().-]*){8,}|"
    r"\b(?:meu nome|meu cpf|meu endere[çc]o|moro na|rua|avenida)\b",
    re.IGNORECASE,
)


def quote_is_safe(quote: str, text: str) -> bool:
    return 3 <= len(quote) <= 180 and quote in text and not PRIVATE_QUOTE.search(quote)


def detect_issues(text: str) -> list[dict]:
    issues = {}
    for category, severity, pattern, translation in RULES:
        if category in issues:
            continue
        match = pattern.search(text)
        if not match:
            continue
        quote = match.group()
        lead = text[max(0, match.start() - 22):match.start()]
        # 局部否定会改变含义，例如“não veio quebrado”。
        if re.search(r"\b(?:n[ãa]o|nunca)(?:\s+\w+)?\s+$", lead, re.IGNORECASE):
            continue
        if quote_is_safe(quote, text):
            issues[category] = {
                "category": category, "severity": severity,
                "evidence_quote": quote, "evidence_quote_en": translation,
            }
    return list(issues.values())


def review_cues(text: str) -> set[str]:
    return {name for name, pattern in CLUE_RULES.items() if pattern.search(text)}


def baseline_sentiment(score: int, text: str) -> float:
    if not text:
        return 0.0
    if POSITIVE_SHORT.fullmatch(text.strip(" .!\r\n")):
        return 0.5
    return {1: -0.9, 2: -0.65, 3: -0.35}[score]
