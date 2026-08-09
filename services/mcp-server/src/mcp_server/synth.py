"""Synthetic test-invoice generation — Faker-sourced fictional data only.

Never seeded from real payload values (see docs/architecture.md Phase 5
note and the original brief: "no real customer data"). `seed` controls
Faker's RNG for reproducible fixtures, not any real-world source data.
"""

from faker import Faker

from mcp_server.edifact import write_segments
from mcp_server.ubl import InvoiceFields, build_invoice_xml


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
