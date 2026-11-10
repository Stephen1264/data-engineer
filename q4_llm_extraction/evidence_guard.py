"""用类别相关的葡语线索筛查模型所选的原文证据。"""

import re
import unicodedata


def normalized(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


EXPLICIT_LATE = re.compile(
    r"\b(?:atras\w*|demor\w*|fora do prazo|depois do prazo|passou (?:d?o|da) prazo)\b",
)
MISSED_DEADLINE = re.compile(
    r"\bnao (?:(?:foi |foram )?entreg\w*|cheg\w*|receb\w*) (?:no|dentro do) prazo\b|"
    r"\bnao cumpr\w* o prazo\b",
)
NOT_RECEIVED = re.compile(
    r"\b(?:nao|nunca|nem|n)\s+(?:me |ainda |foi |foram |ter )?"
    r"(?:receb\w+|cheg\w+|entreg\w+|envi\w+|mand\w+)\b",
)
QUANTITY = r"(?:[0-9]{1,2}|um|uma|dois|duas|tres|metade)\b(?! (?:dias?|semanas?|meses?|horas?|anos?|vezes|minutos?)\b)"
RECEIPT = r"(?:recebi|veio|vieram|chegou|chegaram|foi entregue|foram entregues|entregaram)"
PARTIAL_DELIVERY = re.compile(
    rf"\b{RECEIPT} (?:um|uma) d[oa]s\b.{{0,85}}\b(?:outr[oa]|restante)\b.{{0,25}}"
    r"\bnao (?:cheg\w*|veio|foi entregue)\b|"
    r"\bnao (?:foi |foram )?(?:mand\w+|envi\w+|entreg\w+) (?:todos|todas)\b",
)
PARTIAL = re.compile(
    r"\b(?:falt(?:a|ou|am|ando|aram|ante\w*)|incomplet\w*|"
    r"nao (?:foi |foram )?(?:mand\w+|envi\w+|entreg\w+) (?:todos|todas)|"
    r"nao recebi (?:um|uma) d[oa]s|nao (?:veio|vieram) (?:com |o |a |os |as )?"
    r"(?:peca\w*|acessorio\w*|manual|cabo\w*|parafuso\w*))\b|"
    rf"\b(?:{RECEIPT} (?:ate agora )?(?:so|apenas|somente) {QUANTITY}|"
    rf"(?:so|apenas|somente) (?:me )?{RECEIPT} {QUANTITY}|"
    rf"(?:so|apenas|somente) {QUANTITY} (?:foi entregue|foram entregues|chegou|veio))",
)
MISMATCH = re.compile(
    r"\b(?:errad\w*|diferent\w*|falsific\w*|fals[oa]s?|replica\w*|usad[oa]s?|"
    r"outro (?:produto|modelo|item)|outra (?:marca|cor|versao)|"
    r"nao (?:e|era|foi) (?:o|a) que (?:eu )?(?:pedi|comprei|solicitei))\b",
)
ORDER_AND_RECEIPT = re.compile(
    r"\b(?:comprei|pedi|solicitei|comprado)\b.{3,130}\b(?:recebi|veio|chegou|mandaram|fornecido|entregaram)\b",
)
DEFECT = re.compile(
    r"\b(?:defeit\w*|danific\w*|quebr\w*|furad\w*|furo\w*|arranh\w*|rach\w*|riscad\w*|"
    r"descol\w*|rasgad\w*|avari\w*|fragil\w*|fraco|fraca|gasta\w*|tort\w*|"
    r"mal encaix\w*|nao (?:liga|funciona|aguenta|serve)|parou de funcionar|"
    r"(?:pessim\w*|ruim|baixa|ma) qualidade|"
    r"(?:material|tecido|acabamento|qualidade)\b.{0,35}\b(?:ruim|pessim\w*|fraco|fraca|deixou a desejar))\b",
)
COMMUNICATION = re.compile(
    r"\b(?:(?:nao|nunca|nem|sem|ninguem|nenhum[ao]?)\b(?:\W+\w+){0,4}\W+"
    r"(?:respond\w*|respost\w*|retorn\w*|contat\w*|avis\w*|comunic\w*|"
    r"informac\w*|lig\w*|atend\w*)|"
    r"(?:pessim\w*|mau|ruim) atendimento|atendimento\b.{0,22}\b(?:ruim|pessim\w*)|"
    r"(?:aguardo|esperando) (?:um |uma )?(?:retorno|resposta)\b.{0,25}\bha (?:dias|semanas))\b",
)
PACKAGE = re.compile(
    r"\b(?:mal embalad\w*|sem (?:a |o )?(?:embalagem|caixa|lacre|protecao)|"
    r"(?:embalag\w*|caixa\w*|lacre\w*|plastico bolha|papelao)\b[^.!?;]{0,45}"
    r"\b(?:danific\w*|rasgad\w*|amassad\w*|quebrad\w*|abert\w*|violad\w*|"
    r"vazad\w*|suj\w*|sem seguranca|sem protecao|inadequad\w*))\b",
)
OTHER = re.compile(
    r"\b(?:nota fiscal|nf-e|cancel\w*|cobr\w*|indisponiv\w*|endereco|"
    r"retir\w* (?:n[oa]s? )?(?:agencia|correios?)|"
    r"(?:sem|nao (?:tem|consigo|recebi))\b.{0,35}\b(?:rastrei\w*|estorno|reembolso))\b",
)


def supports_category(category: str, quote: str) -> bool:
    source = normalized(quote)
    partial = bool(PARTIAL.search(source) or PARTIAL_DELIVERY.search(source))
    if category == "delivery_late":
        late = MISSED_DEADLINE.search(source) or (
            EXPLICIT_LATE.search(source) and not re.search(
                r"\b(?:sem atraso|nenhum atraso|dentro do prazo|antes do prazo|cheg\w* no prazo)\b", source,
            )
        )
        return bool(late or (NOT_RECEIVED.search(source) and not partial and not MISMATCH.search(source)))
    if category == "missing_item":
        return partial and not bool(re.search(r"\bfalt\w* (?:a |uma )?nota fiscal\b", source))
    if category == "wrong_product":
        return bool(MISMATCH.search(source) or (
            not partial and not NOT_RECEIVED.search(source) and ORDER_AND_RECEIPT.search(source)
        ))
    pattern = {
        "quality_defect": DEFECT, "seller_communication": COMMUNICATION, "packaging": PACKAGE, "other": OTHER,
    }[category]
    return bool(pattern.search(source))


def ground_issue(issue: dict) -> dict | None:
    category, quote = issue["category"], issue["evidence_quote"]
    if supports_category(category, quote):
        return issue
    if category == "delivery_late" and PARTIAL_DELIVERY.search(normalized(quote)):
        return {**issue, "category": "missing_item"}
    return None
