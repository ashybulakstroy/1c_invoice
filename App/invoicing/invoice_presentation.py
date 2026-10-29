"""Shared print fields matching the supplied 1C payment invoices."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from num2words import num2words


PAYMENT_TERMS = (
    "Внимание! Оплата данного счета означает согласие с условиями поставки товара. "
    "Уведомление об оплате обязательно, в противном случае не гарантируется наличие товара на складе. "
    "Товар отпускается по факту прихода денег на р/с Поставщика, самовывозом, при наличии "
    "доверенности и документов удостоверяющих личность."
)
VALIDITY_NOTE = "Счет действителен в течение 3-х календарных дней с даты выписки"
TAX_NOTICE = (
    "Информируем Вас, что с 01.01.2026г наша организация сохраняет "
    "общеустановленный режим налогообложения, является плательщиком НДС."
)
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")


def print_number(value, minimum=2):
    if value is None or value == "":
        return ""
    value = Decimal(str(value))
    places = max(minimum, -value.normalize().as_tuple().exponent)
    return f"{value:,.{places}f}".replace(",", " ").replace(".", ",")


def print_fields(document):
    issuer = document["issuer"]
    try:
        date = datetime.strptime(document.get("date") or "", "%d.%m.%Y")
        date_text = f"{date.day} {MONTHS[date.month-1]} {date.year} г."
    except ValueError:
        date_text = document.get("date") or ""
    total = document.get("total")
    words = ""
    if total is not None:
        amount = Decimal(str(total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        whole = int(amount)
        words = f"{num2words(whole, lang='ru').capitalize()} теңге {int((amount-whole)*100):02d} тиын"
    supplier = ", ".join(str(value) for value in (
        f"БИН / ИИН {issuer['tax_id']}" if issuer.get("tax_id") else "", issuer.get("name"), issuer.get("address")) if value)
    return {
        "terms": issuer.get("payment_terms", PAYMENT_TERMS), "validity": issuer.get("validity_note", VALIDITY_NOTE),
        "tax_notice": issuer.get("tax_notice", TAX_NOTICE), "date": date_text,
        "supplier": supplier, "buyer": document.get("buyer") or "", "contract": document.get("contract") or "",
        "total": print_number(total), "vat": print_number(document.get("vat_amount")), "amount_words": words,
        "items": [{"quantity": print_number(row.get("quantity"), 3), "price": print_number(row.get("price")),
                   "amount": print_number(row.get("amount"))} for row in document["items"]],
    }
