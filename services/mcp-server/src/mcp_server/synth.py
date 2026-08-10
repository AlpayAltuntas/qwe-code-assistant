"""Synthetic test-invoice generation — Faker-sourced fictional data only.

Never seeded from real payload values (see docs/architecture.md Phase 5
note and the original brief: "no real customer data"). `seed` controls
Faker's RNG for reproducible fixtures, not any real-world source data.
"""

from faker import Faker

from mcp_server.edifact import write_segments
from mcp_server.ubl import InvoiceFields, build_invoice_xml
from mcp_server.zugferd import assemble_pdf, build_cii_xml


def _fake(seed: int | None) -> Faker:
    f = Faker()
    if seed is not None:
        Faker.seed(seed)
    return f


def generate_synthetic_edifact_invoic(seed: int | None = None, num_lines: int = 2) -> str:
    fake = _fake(seed)

    invoice_number = str(fake.random_int(min=10000, max=99999))
    issue_date = fake.date_this_year().strftime("%Y%m%d")
    supplier_id = str(fake.random_int(min=1000, max=9999))
    buyer_id = str(fake.random_int(min=1000, max=9999))

    rows: list[tuple[str, list[list[str]]]] = [
        ("UNH", [["1"], ["INVOIC", "D", "01B", "UN"]]),
        ("BGM", [["380"], [invoice_number]]),
        ("DTM", [["137", issue_date, "102"]]),
        ("NAD", [["SU"], [supplier_id, "", "9"], [""], [fake.company()]]),
        ("NAD", [["BY"], [buyer_id, "", "9"], [""], [fake.company()]]),
    ]

    total = 0.0
    for i in range(1, num_lines + 1):
        qty = fake.random_int(min=1, max=50)
        price = round(fake.pyfloat(min_value=1, max_value=500, right_digits=2), 2)
        amount = round(qty * price, 2)
        total += amount
        rows += [
            ("LIN", [[str(i)], [""], [fake.word().upper(), "EN"]]),
            ("IMD", [["F"], [""], ["", "", "", fake.catch_phrase()]]),
            ("QTY", [["47", str(qty)]]),
            ("PRI", [["AAA", f"{price:.2f}"]]),
            ("MOA", [["203", f"{amount:.2f}"]]),
        ]

    rows.append(("UNS", [["S"]]))  # Section Control: marks detail -> summary transition
    rows.append(("MOA", [["77", f"{total:.2f}"]]))
    body_count = len(rows) + 1  # +1 for UNT itself, matching this module's own validator convention
    rows.append(("UNT", [[str(body_count)], ["1"]]))

    return write_segments(rows)


def generate_synthetic_ubl_invoice(seed: int | None = None, num_lines: int = 2) -> str:
    fake = _fake(seed)

    lines = []
    total = 0.0
    for i in range(1, num_lines + 1):
        qty = fake.random_int(min=1, max=50)
        price = round(fake.pyfloat(min_value=1, max_value=500, right_digits=2), 2)
        amount = round(qty * price, 2)
        total += amount
        lines.append(
            {
                "id": i,
                "quantity": qty,
                "unit_code": "EA",
                "line_extension_amount": f"{amount:.2f}",
                "item_name": fake.catch_phrase(),
                "price_amount": f"{price:.2f}",
            }
        )

    fields = InvoiceFields(
        invoice_id=str(fake.random_int(min=10000, max=99999)),
        issue_date=fake.date_this_year().isoformat(),
        currency=fake.random_element(elements=("EUR", "USD", "GBP")),
        invoice_type_code="380",
        supplier_name=fake.company(),
        customer_name=fake.company(),
        payable_amount=f"{total:.2f}",
        lines=lines,
    )
    return build_invoice_xml(fields)


VAT_RATE = 19  # fixed test rate — synthetic data, not a real jurisdiction lookup


def generate_synthetic_zugferd_invoice(
    seed: int | None = None, num_lines: int = 2
) -> tuple[str, bytes]:
    """Returns (cii_xml_text, pdf_bytes) — a Factur-X/ZUGFeRD (EN16931
    level) invoice with the CII XML embedded in a minimal PDF/A-3
    carrier. See zugferd.py for the "blank visual layer" scope note."""
    fake = _fake(seed)
    issue_date = fake.date_this_year()

    lines = []
    net_total = 0.0
    for i in range(1, num_lines + 1):
        qty = fake.random_int(min=1, max=50)
        price = round(fake.pyfloat(min_value=1, max_value=500, right_digits=2), 2)
        amount = round(qty * price, 2)
        net_total += amount
        lines.append(
            {
                "BT-126": str(i),
                "BT-153": fake.catch_phrase(),
                "BT-146": f"{price:.2f}",
                "BT-129": str(qty),
                "BT-130": "EA",
                "BT-131": f"{amount:.2f}",
                "BT-151": "S",
                "BT-152": str(VAT_RATE),
            }
        )

    tax_amount = round(net_total * VAT_RATE / 100, 2)
    grand_total = round(net_total + tax_amount, 2)

    data_dict = {
        "BT-24": None,
        "BT-1": str(fake.random_int(min=10000, max=99999)),
        "BT-2": issue_date,
        "BT-3": "380",
        "BT-5": "EUR",
        "BT-72": issue_date,
        "BT-27": fake.company(),
        "BT-40": "DE",
        "BT-44": fake.company(),
        "BT-55": fake.random_element(elements=("DE", "FR", "NL", "BE")),
        "BT-106": f"{net_total:.2f}",
        "BT-109": f"{net_total:.2f}",
        "BT-110": f"{tax_amount:.2f}",
        "BT-110-1": "EUR",
        "BT-112": f"{grand_total:.2f}",
        "BT-115": f"{grand_total:.2f}",
        "BG-23": [
            {"BT-116": f"{net_total:.2f}", "BT-117": f"{tax_amount:.2f}", "BT-118": "S", "BT-119": str(VAT_RATE)}
        ],
        "BG-25": lines,
    }

    xml_text = build_cii_xml(data_dict, level="en16931")
    pdf_bytes = assemble_pdf(xml_text)
    return xml_text, pdf_bytes
