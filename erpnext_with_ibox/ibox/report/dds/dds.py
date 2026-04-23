# Copyright (c) 2026, abdulloh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

CATEGORY_MAP = {
	"Покупатели": "customer",
	"Поставщики": "supplier",
	"Расходы": "expense",
	"Дивиденды": "dividend",
	"Сотрудники": "employee",
	"Перемещения": "transfer",
}


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	summary_html = get_summary_html(data)
	return columns, data, summary_html


def get_columns():
	return [
		{
			"fieldname": "posting_date",
			"label": _("Сана"),
			"fieldtype": "Date",
			"width": 100
		},
		{
			"fieldname": "voucher_type",
			"label": _("Тип"),
			"fieldtype": "Data",
			"width": 0,
			"hidden": 1
		},
		{
			"fieldname": "voucher_no",
			"label": _("Документ"),
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 180
		},
		{
			"fieldname": "description",
			"label": _("Контрагент / Изоҳ"),
			"fieldtype": "Data",
			"width": 280
		},
		{
			"fieldname": "kirim",
			"label": _("Кирим"),
			"fieldtype": "Currency",
			"width": 130
		},
		{
			"fieldname": "chiqim",
			"label": _("Чиқим"),
			"fieldtype": "Currency",
			"width": 130
		},
		{
			"fieldname": "balance",
			"label": _("Қолдиқ"),
			"fieldtype": "Currency",
			"width": 130
		},
	]


def get_data(filters):
	cash_accounts = get_cash_accounts(filters)
	if not cash_accounts:
		return []

	opening_balance = get_opening_balance(cash_accounts, filters)
	transactions = get_transactions(cash_accounts, filters)

	pe_vouchers = [r.voucher_no for r in transactions if r.voucher_type == "Payment Entry"]
	je_vouchers = [r.voucher_no for r in transactions if r.voucher_type == "Journal Entry"]

	pe_info = get_payment_entry_info_batch(pe_vouchers)
	je_info = get_journal_entry_info_batch(je_vouchers)

	data = []

	# Filterlar
	filter_party_type = filters.get("party_type")
	filter_party = filters.get("party")
	category_filter_val = filters.get("category")
	filter_category = CATEGORY_MAP.get(category_filter_val)

	expense_summaries = {}
	balance = opening_balance
	total_kirim = 0
	total_chiqim = 0

	# 1-qadam: Tranzaksiyalarni qayta ishlash va xarajatlarni guruhlash
	for row in transactions:
		kirim = flt(row.debit_in_account_currency)
		chiqim = flt(row.credit_in_account_currency)

		info = resolve_transaction_info(row, pe_info, je_info, cash_accounts)

		# Category filter
		if filter_category and info["category"] != filter_category:
			balance += kirim - chiqim
			continue

		# Party filter
		if filter_party_type and info.get("party_type") != filter_party_type:
			balance += kirim - chiqim
			continue
		if filter_party and info.get("party") != filter_party:
			balance += kirim - chiqim
			continue

		balance += kirim - chiqim
		total_kirim += kirim
		total_chiqim += chiqim

		# Xarajatlarni guruhlash
		if info["category"] == "expense":
			desc = info["description"]
			if desc not in expense_summaries:
				expense_summaries[desc] = {"kirim": 0, "chiqim": 0}
			expense_summaries[desc]["kirim"] += kirim
			expense_summaries[desc]["chiqim"] += chiqim

		data.append({
			"posting_date": row.posting_date,
			"voucher_type": row.voucher_type,
			"voucher_no": row.voucher_no,
			"description": info["description"],
			"kirim": kirim,
			"chiqim": chiqim,
			"balance": balance,
			"category": info["category"],
		})

	# 2-qadam: Summary qatorlarni tayyorlash
	summary_rows = []
	if category_filter_val == "Расходы" and expense_summaries:
		for desc, totals in expense_summaries.items():
			if totals["kirim"] or totals["chiqim"]:
				summary_rows.append({
					"description": f"<b>ИТОГО: {desc}</b>",
					"kirim": totals["kirim"],
					"chiqim": totals["chiqim"],
					"is_total": 1,
					"indent": 1
				})

	# 3-qadam: Yakuniy data ro'yxatini yig'ish (Opening Balance + Summary + Transactions)
	final_data = []
	final_data.append({
		"posting_date": None,
		"voucher_type": None,
		"voucher_no": None,
		"description": _("Нач. остаток"),
		"kirim": 0,
		"chiqim": 0,
		"balance": opening_balance,
		"is_opening": 1,
	})

	if summary_rows:
		final_data.extend(summary_rows)

	final_data.extend(data)

	final_data.append({
		"posting_date": None,
		"voucher_type": None,
		"voucher_no": None,
		"description": "<b>ИТОГО</b>",
		"kirim": total_kirim,
		"chiqim": total_chiqim,
		"balance": balance,
		"is_total": 1,
	})

	return final_data


def get_cash_accounts(filters):
	conditions = {}
	if filters.get("mode_of_payment"):
		conditions["parent"] = filters["mode_of_payment"]

	accounts = frappe.get_all(
		"Mode of Payment Account",
		filters=conditions,
		fields=["default_account"],
		pluck="default_account"
	)

	return list(set(a for a in accounts if a))


def get_opening_balance(cash_accounts, filters):
	placeholders = ", ".join(["%s"] * len(cash_accounts))

	result = frappe.db.sql("""
        SELECT IFNULL(SUM(debit_in_account_currency) - SUM(credit_in_account_currency), 0)
        FROM `tabGL Entry`
        WHERE account IN ({placeholders})
          AND posting_date < %s
          AND is_cancelled = 0
    """.format(placeholders=placeholders),
						   tuple(cash_accounts) + (filters["from_date"],)
						   )

	return flt(result[0][0]) if result else 0


def get_transactions(cash_accounts, filters):
	placeholders = ", ".join(["%s"] * len(cash_accounts))

	return frappe.db.sql("""
        SELECT
            posting_date, voucher_type, voucher_no,
            party_type, party, against,
            debit_in_account_currency, credit_in_account_currency,
            account
        FROM `tabGL Entry`
        WHERE account IN ({placeholders})
          AND posting_date BETWEEN %s AND %s
          AND is_cancelled = 0
        ORDER BY posting_date, creation
    """.format(placeholders=placeholders),
						 tuple(cash_accounts) + (filters["from_date"], filters["to_date"]),
						 as_dict=True
						 )


def get_payment_entry_info_batch(voucher_nos):
	if not voucher_nos:
		return {}

	entries = frappe.db.sql("""
        SELECT name, party_type, party, payment_type
        FROM `tabPayment Entry`
        WHERE name IN %s
    """, (voucher_nos,), as_dict=True)

	return {e.name: e for e in entries}


def get_journal_entry_info_batch(voucher_nos):
	if not voucher_nos:
		return {}

	entries = frappe.db.sql("""
        SELECT jea.parent, jea.account, jea.party_type, jea.party,
               acc.root_type, acc.account_type, acc.account_name
        FROM `tabJournal Entry Account` jea
        LEFT JOIN `tabAccount` acc ON acc.name = jea.account
        WHERE jea.parent IN %s
    """, (voucher_nos,), as_dict=True)

	result = {}
	for e in entries:
		result.setdefault(e.parent, []).append(e)
	return result


def resolve_transaction_info(row, pe_info, je_info, cash_accounts):
	# 1. GL Entry'da party bor
	if row.party_type and row.party:
		party_name = get_party_name(row.party_type, row.party)
		display_name = party_name or row.party
		suffix = "Приход" if flt(row.debit_in_account_currency) > 0 else "Расход"
		return {
			"description": f"{display_name} ({suffix})",
			"category": get_category_from_party_type(row.party_type),
			"party_type": row.party_type,
			"party": row.party,
		}

	# 2. Payment Entry
	if row.voucher_type == "Payment Entry" and row.voucher_no in pe_info:
		pe = pe_info[row.voucher_no]
		if pe.payment_type == "Internal Transfer":
			return {"description": "Перемещение", "category": "transfer", "party_type": None,
					"party": None}
		if pe.party_type and pe.party:
			party_name = get_party_name(pe.party_type, pe.party)
			display_name = party_name or pe.party
			suffix = "Приход" if pe.payment_type == "Receive" else "Расход"
			return {
				"description": f"{display_name} ({suffix})",
				"category": get_category_from_party_type(pe.party_type),
				"party_type": pe.party_type,
				"party": pe.party,
			}

	# 3. Journal Entry
	if row.voucher_type == "Journal Entry" and row.voucher_no in je_info:
		for acc in je_info[row.voucher_no]:
			if acc.account in cash_accounts:
				continue
			if acc.party_type and acc.party:
				party_name = get_party_name(acc.party_type, acc.party)
				return {
					"description": party_name or acc.party,
					"category": get_category_from_party_type(acc.party_type),
					"party_type": acc.party_type,
					"party": acc.party,
				}
			if acc.root_type == "Expense":
				return {"description": f"Расходы: {acc.account_name}", "category": "expense",
						"party_type": None, "party": None}
			if acc.root_type == "Equity":
				return {"description": f"Дивиденды: {acc.account_name}", "category": "dividend",
						"party_type": None, "party": None}

	# 4. Against field (fallback)
	if row.against:
		against_account = row.against.split(",")[0].strip() if "," in row.against else row.against

		is_cash = frappe.db.get_value("Mode of Payment Account",
									  {"default_account": against_account}, "parent")
		if is_cash:
			direction = "из" if flt(row.debit_in_account_currency) > 0 else "в"
			return {"description": f"Перемещение {direction} {is_cash}", "category": "transfer",
					"party_type": None, "party": None}

		acc_info = frappe.db.get_value("Account", against_account,
									   ["account_name", "root_type", "account_type"], as_dict=True)
		if acc_info:
			if acc_info.root_type == "Expense":
				return {"description": f"Расходы: {acc_info.account_name}", "category": "expense",
						"party_type": None, "party": None}
			if acc_info.root_type == "Equity":
				return {"description": f"Дивиденды: {acc_info.account_name}",
						"category": "dividend", "party_type": None, "party": None}
			if acc_info.account_type == "Receivable":
				return {"description": acc_info.account_name, "category": "customer",
						"party_type": "Customer", "party": None}
			if acc_info.account_type == "Payable":
				return {"description": acc_info.account_name, "category": "supplier",
						"party_type": "Supplier", "party": None}
			return {"description": acc_info.account_name, "category": "other", "party_type": None,
					"party": None}

	return {"description": row.voucher_no or "", "category": "other", "party_type": None,
			"party": None}


def get_category_from_party_type(party_type):
	return {"Customer": "customer", "Supplier": "supplier", "Employee": "employee"}.get(party_type,
																						"other")


def get_party_name(party_type, party):
	field = {"Customer": "customer_name", "Supplier": "supplier_name",
			 "Employee": "employee_name"}.get(party_type)
	if field:
		return frappe.db.get_value(party_type, party, field)
	return party


def get_summary_html(data):
	if not data or len(data) <= 1:
		return ""

	opening = 0
	closing = 0

	# Har bir kategoriya uchun IKKI TOMONI ham track qilinadi
	customer_kirim = 0
	customer_chiqim = 0  # BUG FIX: avval bu yo'q edi
	supplier_kirim = 0  # BUG FIX: avval bu yo'q edi
	supplier_chiqim = 0
	expense_kirim = 0
	expense_chiqim = 0
	dividend_kirim = 0
	dividend_chiqim = 0
	transfer_kirim = 0
	transfer_chiqim = 0
	employee_kirim = 0
	employee_chiqim = 0
	other_kirim = 0
	other_chiqim = 0

	for row in data:
		if row.get("is_opening"):
			opening = flt(row.get("balance"))
			continue
		if row.get("is_total"):
			# Closing = ИТОГО qatoridagi balance (detail bilan har doim mos keladi)
			closing = flt(row.get("balance"))
			continue

		category = row.get("category") or "other"
		kirim = flt(row.get("kirim"))
		chiqim = flt(row.get("chiqim"))

		if category == "customer":
			customer_kirim += kirim
			customer_chiqim += chiqim
		elif category == "supplier":
			supplier_kirim += kirim
			supplier_chiqim += chiqim
		elif category == "expense":
			expense_kirim += kirim
			expense_chiqim += chiqim
		elif category == "dividend":
			dividend_kirim += kirim
			dividend_chiqim += chiqim
		elif category == "transfer":
			transfer_kirim += kirim
			transfer_chiqim += chiqim
		elif category == "employee":
			employee_kirim += kirim
			employee_chiqim += chiqim
		else:
			other_kirim += kirim
			other_chiqim += chiqim

	def fmt(val):
		return f"{flt(val):,.2f}"

	def dash_or_val(val):
		return "—" if flt(val) == 0 else f"<span style='color: inherit;'>{fmt(val)}</span>"

	html = f"""
    <div style="margin-top: 20px; padding: 15px; background-color: #f9f9f9; border-radius: 5px;">
        <table style="width: 100%; border-collapse: collapse; background: white;">
            <thead>
                <tr style="background-color: #f0f0f0;">
                    <th style="padding: 10px; text-align: left; border: 1px solid #ddd; width: 40%;"></th>
                    <th style="padding: 10px; text-align: right; border: 1px solid #ddd; width: 30%; color: #388e3c; font-weight: bold;">Кирим</th>
                    <th style="padding: 10px; text-align: right; border: 1px solid #ddd; width: 30%; color: #d32f2f; font-weight: bold;">Чиқим</th>
                </tr>
            </thead>
            <tbody>
                <tr style="background-color: #e3f2fd;">
                    <td style="padding: 10px; border: 1px solid #ddd; font-weight: bold;">Начальный остаток</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; font-weight: bold;" colspan="2">{fmt(opening)}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Покупатели</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #388e3c;">{fmt(customer_kirim) if customer_kirim else '—'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #d32f2f;">{fmt(customer_chiqim) if customer_chiqim else '—'}</td>
                </tr>
                <tr style="background-color: #fafafa;">
                    <td style="padding: 10px; border: 1px solid #ddd;">Поставщики</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #388e3c;">{fmt(supplier_kirim) if supplier_kirim else '—'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #d32f2f;">{fmt(supplier_chiqim) if supplier_chiqim else '—'}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Расходы</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #388e3c;">{fmt(expense_kirim) if expense_kirim else '—'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #d32f2f;">{fmt(expense_chiqim) if expense_chiqim else '—'}</td>
                </tr>
                <tr style="background-color: #fafafa;">
                    <td style="padding: 10px; border: 1px solid #ddd;">Дивиденды</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #388e3c;">{fmt(dividend_kirim) if dividend_kirim else '—'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #d32f2f;">{fmt(dividend_chiqim) if dividend_chiqim else '—'}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Сотрудники</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #388e3c;">{fmt(employee_kirim) if employee_kirim else '—'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #d32f2f;">{fmt(employee_chiqim) if employee_chiqim else '—'}</td>
                </tr>
                <tr style="background-color: #fafafa;">
                    <td style="padding: 10px; border: 1px solid #ddd;">Перемещения</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #388e3c;">{fmt(transfer_kirim) if transfer_kirim else '—'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #d32f2f;">{fmt(transfer_chiqim) if transfer_chiqim else '—'}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;">Прочие</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #388e3c;">{fmt(other_kirim) if other_kirim else '—'}</td>
                    <td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: #d32f2f;">{fmt(other_chiqim) if other_chiqim else '—'}</td>
                </tr>
                <tr style="background-color: #e3f2fd; font-weight: bold;">
                    <td style="padding: 12px; border: 1px solid #ddd; font-weight: bold;">Конечный остаток</td>
                    <td style="padding: 12px; border: 1px solid #ddd; text-align: right; font-weight: bold;" colspan="2">{fmt(closing)}</td>
                </tr>
            </tbody>
        </table>
    </div>
    """

	return html
