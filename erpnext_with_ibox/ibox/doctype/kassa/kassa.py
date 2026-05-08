# Copyright (c) 2025, abdulloh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt
from erpnext.accounts.party import get_party_account as erpnext_get_party_account

MODE_OF_PAYMENT_CASH_UZS_NAMES = ("Наличый UZS", "Наличный UZS")
MODE_OF_PAYMENT_CASH_USD_NAMES = ("Наличый USD", "Наличный USD")
MODE_OF_PAYMENT_BANK = "Р/С"
DIVIDEND_ACCOUNT_NUMBERS = {
    "Дивиденд": "3200",
}
EXPENSE_PARENT_ACCOUNT_NUMBER = "5200"


def is_cash_uzs_mode_of_payment(mode_of_payment):
    return mode_of_payment in MODE_OF_PAYMENT_CASH_UZS_NAMES


def is_cash_usd_mode_of_payment(mode_of_payment):
    return mode_of_payment in MODE_OF_PAYMENT_CASH_USD_NAMES


def is_dividend_party_type(party_type):
    return party_type in DIVIDEND_ACCOUNT_NUMBERS


class Kassa(Document):
    def validate(self):
        self.set_default_company()
        self.set_cash_account()
        self.set_cash_account_currency()
        self.set_party_currency()
        self.set_display_currencies()
        self.set_payment_exchange_details()
        self.set_balance()
        self.validate_party()
        self.validate_transfer()
        self.validate_conversion()
        self.validate_amount()
        self.validate_currency()

    def on_submit(self):
        """Submit bo'lganda Payment Entry yoki Journal Entry yaratish"""
        if self.transaction_type in ["Приход", "Расход"]:
            if self.party_type in ["Customer", "Supplier", "Employee"]:
                self.create_payment_entry()
            elif is_dividend_party_type(self.party_type):
                self.create_dividend_journal_entry()
            elif self.party_type == "Расходы":
                self.create_expense_journal_entry()
        elif self.transaction_type == "Перемещения":
            self.create_transfer_payment_entry()
        elif self.transaction_type == "Конвертация":
            self.create_conversion_payment_entry()

    def on_cancel(self):
        """Cancel bo'lganda bog'langan Payment Entry yoki Journal Entry ni cancel qilish"""
        self.cancel_linked_entries()

    def create_payment_entry(self):
        """Customer/Supplier/Employee uchun Payment Entry yaratish"""
        payment_type = "Receive" if self.transaction_type == "Приход" else "Pay"
        party_account = self.get_party_account()
        party_account_currency = frappe.get_cached_value("Account", party_account, "account_currency")
        cash_currency = self.cash_account_currency or frappe.get_cached_value(
            "Account", self.cash_account, "account_currency"
        )
        same_currency = cash_currency == party_account_currency

        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = payment_type
        pe.posting_date = self.date
        pe.company = self.company
        pe.mode_of_payment = self.mode_of_payment
        pe.party_type = self.party_type
        pe.party = self.party

        pe.paid_from = self.get_paid_from_account(payment_type, party_account)
        pe.paid_to = self.get_paid_to_account(payment_type, party_account)

        if same_currency:
            pe.paid_amount = flt(self.amount)
            pe.received_amount = flt(self.amount)
        else:
            pe.source_exchange_rate = self.get_company_exchange_rate(
                frappe.get_cached_value("Account", pe.paid_from, "account_currency")
            )
            pe.target_exchange_rate = self.get_company_exchange_rate(
                frappe.get_cached_value("Account", pe.paid_to, "account_currency")
            )

            if payment_type == "Pay":
                pe.paid_amount = flt(self.amount)
                pe.received_amount = flt(self.credit_amount)
            else:
                pe.paid_amount = flt(self.credit_amount)
                pe.received_amount = flt(self.amount)

        pe.reference_no = self.name
        pe.reference_date = self.date
        pe.remarks = self.remarks or f"Payment for {self.name}"

        pe.flags.ignore_permissions = True
        pe.insert()
        pe.submit()

        self.set_linked_document("Payment Entry", pe.name)

        frappe.msgprint(_("Payment Entry {0} создан").format(
            frappe.utils.get_link_to_form("Payment Entry", pe.name)
        ))

    def get_paid_from_account(self, payment_type, party_account=None):
        if payment_type == "Receive":
            return party_account or self.get_party_account()
        else:
            return self.cash_account

    def get_paid_to_account(self, payment_type, party_account=None):
        if payment_type == "Receive":
            return self.cash_account
        else:
            return party_account or self.get_party_account()

    def get_party_account(self):
        if self.party_type in ["Customer", "Supplier"]:
            return erpnext_get_party_account(self.party_type, self.party, self.company)

        if self.party_type == "Employee":
            payable_account = frappe.db.get_value(
                "Account",
                {
                    "company": self.company,
                    "account_type": "Payable",
                    "is_group": 0,
                },
                "name",
            )
            if payable_account:
                return payable_account

        frappe.throw(_("Не удалось определить счет контрагента для {0}").format(self.party_type))

    def is_party_multicurrency_payment(self):
        return (
            self.transaction_type in ["Приход", "Расход"]
            and self.party_type in ["Customer", "Supplier", "Employee"]
            and self.cash_account
            and self.party
            and self.party_currency
            and self.cash_account_currency
            and self.cash_account_currency != self.party_currency
        )

    def get_company_exchange_rate(self, currency):
        company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
        if not currency or currency == company_currency:
            return 1

        rate = get_exchange_rate(currency, company_currency, self.date)
        if not rate or flt(rate) <= 0:
            frappe.throw(_("Не найден курс {0} к валюте компании {1}").format(currency, company_currency))
        return flt(rate)

    def set_payment_exchange_details(self):
        if not self.is_party_multicurrency_payment():
            if self.transaction_type in ["Приход", "Расход"]:
                self.exchange_rate = 0
                self.debit_amount = 0
                self.credit_amount = 0
                self.manual_credit_amount = 0
            return

        if not self.exchange_rate or flt(self.exchange_rate) <= 0 or flt(self.exchange_rate) == 1:
            self.exchange_rate = get_exchange_rate(
                self.cash_account_currency, self.party_currency, self.date
            )

        if not self.exchange_rate or flt(self.exchange_rate) <= 0:
            frappe.throw(
                _("Не найден курс {0} к {1} на дату {2}").format(
                    self.cash_account_currency, self.party_currency, self.date
                )
            )

        self.debit_amount = flt(self.amount)

        if cint(self.manual_credit_amount) and flt(self.credit_amount) > 0:
            self.credit_amount = flt(self.credit_amount, 2)
        else:
            self.credit_amount = flt(flt(self.amount) * flt(self.exchange_rate), 2)
            self.manual_credit_amount = 0

    def create_dividend_journal_entry(self):
        """Dividend uchun Journal Entry yaratish."""
        account_number = DIVIDEND_ACCOUNT_NUMBERS.get(self.party_type, "3200")
        dividend_account = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_number": account_number, "is_group": 0},
            "name",
        )

        if not dividend_account:
            frappe.throw(
                _("Счет дивидендов ({0}) не найден для компании {1}").format(account_number, self.company)
            )

        cash_currency = frappe.get_cached_value("Account", self.cash_account, "account_currency")
        company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
        dividend_currency = frappe.get_cached_value(
            "Account", dividend_account, "account_currency"
        ) or company_currency

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.posting_date = self.date
        je.company = self.company
        je.cheque_no = self.name
        je.cheque_date = self.date
        je.user_remark = self.remarks or f"Dividend payment from {self.name}"

        is_multicurrency = (
            cash_currency != company_currency
            or dividend_currency != company_currency
        )

        if is_multicurrency:
            je.multi_currency = 1

            if cash_currency == company_currency:
                cash_exchange_rate = 1
            else:
                cash_exchange_rate = get_exchange_rate(cash_currency, company_currency, self.date)
                if not cash_exchange_rate or cash_exchange_rate == 0:
                    frappe.throw(_("Не найден курс {0} к {1}").format(cash_currency, company_currency))

            if dividend_currency == company_currency:
                dividend_exchange_rate = 1
            else:
                dividend_exchange_rate = get_exchange_rate(dividend_currency, company_currency, self.date)
                if not dividend_exchange_rate or dividend_exchange_rate == 0:
                    frappe.throw(_("Не найден курс {0} к {1}").format(dividend_currency, company_currency))

            je.append("accounts", {
                "account": self.cash_account,
                "account_currency": cash_currency,
                "exchange_rate": cash_exchange_rate,
                "credit_in_account_currency": flt(self.amount),
                "credit": flt(self.amount) * cash_exchange_rate,
                "debit_in_account_currency": 0,
                "debit": 0,
            })

            if cash_currency == dividend_currency:
                dividend_amount = flt(self.amount)
            else:
                company_amount = flt(self.amount) * cash_exchange_rate
                if dividend_exchange_rate and dividend_exchange_rate != 0:
                    dividend_amount = company_amount / dividend_exchange_rate
                else:
                    dividend_amount = company_amount

            je.append("accounts", {
                "account": dividend_account,
                "account_currency": dividend_currency,
                "exchange_rate": dividend_exchange_rate,
                "debit_in_account_currency": flt(dividend_amount),
                "debit": flt(dividend_amount) * dividend_exchange_rate,
                "credit_in_account_currency": 0,
                "credit": 0,
            })

        else:
            je.append("accounts", {
                "account": self.cash_account,
                "credit_in_account_currency": flt(self.amount),
                "credit": flt(self.amount),
                "debit_in_account_currency": 0,
                "debit": 0,
            })

            je.append("accounts", {
                "account": dividend_account,
                "debit_in_account_currency": flt(self.amount),
                "debit": flt(self.amount),
                "credit_in_account_currency": 0,
                "credit": 0,
            })

        je.flags.ignore_permissions = True
        je.insert()
        je.submit()

        self.set_linked_document("Journal Entry", je.name)

        frappe.msgprint(_("Journal Entry {0} для дивидендов создан").format(
            frappe.utils.get_link_to_form("Journal Entry", je.name)
        ))

    def create_expense_journal_entry(self):
        """Расходы uchun Journal Entry yaratish"""
        if not self.expense_account:
            frappe.throw(_("Пожалуйста, выберите счет расходов"))

        cost_center = frappe.db.get_value(
            "Expense Cost Center",
            {"expense_account": self.expense_account},
            "cost_center"
        )

        cash_currency = frappe.get_cached_value("Account", self.cash_account, "account_currency")
        company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
        expense_currency = frappe.get_cached_value(
            "Account", self.expense_account, "account_currency"
        ) or company_currency

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.posting_date = self.date
        je.company = self.company
        je.cheque_no = self.name
        je.cheque_date = self.date
        je.user_remark = self.remarks or f"Expense payment from {self.name}"

        is_multicurrency = (
            cash_currency != company_currency
            or expense_currency != company_currency
        )

        if is_multicurrency:
            je.multi_currency = 1

            if cash_currency == company_currency:
                cash_exchange_rate = 1
            else:
                cash_exchange_rate = get_exchange_rate(cash_currency, company_currency, self.date)
                if not cash_exchange_rate or cash_exchange_rate == 0:
                    frappe.throw(_("Не найден курс {0} к {1}").format(cash_currency, company_currency))

            if expense_currency == company_currency:
                expense_exchange_rate = 1
            else:
                expense_exchange_rate = get_exchange_rate(expense_currency, company_currency, self.date)
                if not expense_exchange_rate or expense_exchange_rate == 0:
                    frappe.throw(_("Не найден курс {0} к {1}").format(expense_currency, company_currency))

            je.append("accounts", {
                "account": self.cash_account,
                "account_currency": cash_currency,
                "exchange_rate": cash_exchange_rate,
                "credit_in_account_currency": flt(self.amount),
                "credit": flt(self.amount) * cash_exchange_rate,
                "debit_in_account_currency": 0,
                "debit": 0,
            })

            if cash_currency == expense_currency:
                expense_amount = flt(self.amount)
            else:
                company_amount = flt(self.amount) * cash_exchange_rate
                if expense_exchange_rate and expense_exchange_rate != 0:
                    expense_amount = company_amount / expense_exchange_rate
                else:
                    expense_amount = company_amount

            je.append("accounts", {
                "account": self.expense_account,
                "cost_center": cost_center,
                "account_currency": expense_currency,
                "exchange_rate": expense_exchange_rate,
                "debit_in_account_currency": flt(expense_amount),
                "debit": flt(expense_amount) * expense_exchange_rate,
                "credit_in_account_currency": 0,
                "credit": 0,
            })

        else:
            je.append("accounts", {
                "account": self.cash_account,
                "credit_in_account_currency": flt(self.amount),
                "credit": flt(self.amount),
                "debit_in_account_currency": 0,
                "debit": 0,
            })

            je.append("accounts", {
                "account": self.expense_account,
                "cost_center": cost_center,
                "debit_in_account_currency": flt(self.amount),
                "debit": flt(self.amount),
                "credit_in_account_currency": 0,
                "credit": 0,
            })

        je.flags.ignore_permissions = True
        je.insert()
        je.submit()

        self.set_linked_document("Journal Entry", je.name)

        frappe.msgprint(_("Journal Entry {0} для расходов создан").format(
            frappe.utils.get_link_to_form("Journal Entry", je.name)
        ))

    def create_transfer_payment_entry(self):
        """Перемещения uchun Internal Transfer Payment Entry yaratish"""
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Internal Transfer"
        pe.posting_date = self.date
        pe.company = self.company
        pe.mode_of_payment = self.mode_of_payment

        pe.paid_from = self.cash_account
        pe.paid_to = self.cash_account_to
        pe.paid_amount = flt(self.amount)
        pe.received_amount = flt(self.amount)

        pe.reference_no = self.name
        pe.reference_date = self.date
        pe.remarks = self.remarks or f"Transfer from {self.name}"

        pe.flags.ignore_permissions = True
        pe.insert()
        pe.submit()

        self.set_linked_document("Payment Entry", pe.name)

        frappe.msgprint(_("Payment Entry {0} для перемещения создан").format(
            frappe.utils.get_link_to_form("Payment Entry", pe.name)
        ))

    def create_conversion_payment_entry(self):
        """Конвертация uchun Internal Transfer Payment Entry yaratish (kurs farqi bilan)"""
        from_currency = frappe.get_cached_value("Account", self.cash_account, "account_currency")
        to_currency = frappe.get_cached_value("Account", self.cash_account_to, "account_currency")

        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Internal Transfer"
        pe.posting_date = self.date
        pe.company = self.company
        pe.mode_of_payment = self.mode_of_payment

        pe.paid_from = self.cash_account
        pe.paid_to = self.cash_account_to
        pe.paid_amount = flt(self.debit_amount)
        pe.received_amount = flt(self.credit_amount)
        pe.source_exchange_rate = self.get_company_exchange_rate(from_currency)
        pe.target_exchange_rate = self.get_company_exchange_rate(to_currency)

        pe.reference_no = self.name
        pe.reference_date = self.date
        pe.remarks = self.remarks or f"Conversion from {self.name}"

        pe.flags.ignore_permissions = True
        pe.insert()
        pe.submit()

        self.set_linked_document("Payment Entry", pe.name)

        frappe.msgprint(_("Payment Entry {0} для конвертации создан").format(
            frappe.utils.get_link_to_form("Payment Entry", pe.name)
        ))

    def cancel_linked_entries(self):
        payment_entries = frappe.get_all("Payment Entry",
            filters={"reference_no": self.name, "docstatus": 1},
            pluck="name")

        for pe_name in payment_entries:
            pe = frappe.get_doc("Payment Entry", pe_name)
            pe.flags.ignore_permissions = True
            pe.cancel()
            frappe.msgprint(_("Payment Entry {0} отменен").format(pe_name))

        journal_entries = frappe.get_all("Journal Entry",
            filters={"cheque_no": self.name, "docstatus": 1},
            pluck="name")

        for je_name in journal_entries:
            je_doc = frappe.get_doc("Journal Entry", je_name)
            je_doc.flags.ignore_permissions = True
            je_doc.cancel()
            frappe.msgprint(_("Journal Entry {0} отменен").format(je_name))

    def set_linked_document(self, doctype, name):
        self.linked_doctype = doctype
        self.linked_entry = name
        self.db_set("linked_doctype", doctype, update_modified=False)
        self.db_set("linked_entry", name, update_modified=False)

    def set_default_company(self):
        if self.transaction_type == "Перемещения" and not self.company:
            default_company = frappe.db.get_single_value("Global Defaults", "default_company")
            if default_company:
                self.company = default_company
            else:
                frappe.throw(_("Пожалуйста, установите компанию по умолчанию в настройках"))

    def set_cash_account(self):
        if self.mode_of_payment and self.company:
            cash_account = get_cash_account(self.mode_of_payment, self.company)
            if cash_account:
                self.cash_account = cash_account

        if self.mode_of_payment_to and self.company:
            cash_account_to = get_cash_account(self.mode_of_payment_to, self.company)
            if cash_account_to:
                self.cash_account_to = cash_account_to

    def set_cash_account_currency(self):
        if self.cash_account:
            self.cash_account_currency = frappe.get_cached_value("Account", self.cash_account, "account_currency")
        if self.cash_account_to:
            self.cash_account_to_currency = frappe.get_cached_value(
                "Account", self.cash_account_to, "account_currency"
            )

    def set_party_currency(self):
        if self.party and self.party_type in ["Customer", "Supplier", "Employee"] and self.company:
            self.party_currency = get_party_currency(self.party_type, self.party, self.company)

    def set_display_currencies(self):
        self.target_amount_currency = None

        if self.transaction_type == "Конвертация":
            self.target_amount_currency = self.cash_account_to_currency or self.party_currency or None
        elif self.is_party_multicurrency_payment():
            self.target_amount_currency = self.party_currency or None

    def set_balance(self):
        if self.cash_account:
            self.balance = get_account_balance(self.cash_account, self.company)

        if self.cash_account_to:
            self.balance_to = get_account_balance(self.cash_account_to, self.company)

    def validate_party(self):
        if self.transaction_type in ["Приход", "Расход"]:
            if not self.party_type:
                frappe.throw(_("Пожалуйста, выберите тип контрагента"))

            if self.party_type == "Расходы":
                if not self.expense_account:
                    frappe.throw(_("Пожалуйста, выберите счет расходов"))
                validate_expense_account(self.expense_account, self.company)
                self.party = None
            elif is_dividend_party_type(self.party_type):
                self.party = None
                self.expense_account = None
            else:
                if not self.party:
                    frappe.throw(_("Пожалуйста, выберите контрагента"))
                self.expense_account = None

    def validate_transfer(self):
        if self.transaction_type == "Перемещения":
            if not self.mode_of_payment_to:
                frappe.throw(_("Пожалуйста, выберите способ оплаты (куда)"))

            if self.mode_of_payment == self.mode_of_payment_to:
                frappe.throw(_("Способ оплаты источника и назначения должны отличаться"))

            from_currency = frappe.get_cached_value("Account", self.cash_account, "account_currency") if self.cash_account else None
            to_currency = frappe.get_cached_value("Account", self.cash_account_to, "account_currency") if self.cash_account_to else None

            if not from_currency or not to_currency:
                frappe.throw(_("Не удалось определить валюту счетов для перемещения"))

            if from_currency != to_currency:
                frappe.throw(_("Для перемещения способы оплаты должны иметь одинаковую валюту"))

    def validate_conversion(self):
        if self.transaction_type == "Конвертация":
            if not self.mode_of_payment_to:
                frappe.throw(_("Пожалуйста, выберите способ оплаты (куда)"))

            if not self.exchange_rate or flt(self.exchange_rate) <= 0:
                frappe.throw(_("Пожалуйста, укажите курс обмена"))

            if flt(self.debit_amount) <= 0:
                frappe.throw(_("Пожалуйста, укажите сумму расхода"))

            if flt(self.credit_amount) <= 0:
                frappe.throw(_("Пожалуйста, укажите сумму прихода"))

            from_currency = frappe.get_cached_value("Account", self.cash_account, "account_currency") if self.cash_account else None
            to_currency = frappe.get_cached_value("Account", self.cash_account_to, "account_currency") if self.cash_account_to else None

            if not from_currency or not to_currency:
                frappe.throw(_("Не удалось определить валюту счетов для конвертации"))

            if from_currency == to_currency:
                frappe.throw(
                    _("Для конвертации способы оплаты должны иметь разные валюты")
                )

    def validate_amount(self):
        if self.transaction_type == "Конвертация":
            return

        if flt(self.amount) <= 0:
            frappe.throw(_("Сумма должна быть больше нуля"))

        if self.is_party_multicurrency_payment():
            if not self.exchange_rate or flt(self.exchange_rate) <= 0:
                frappe.throw(_("Пожалуйста, укажите курс обмена"))

            if flt(self.credit_amount) <= 0:
                frappe.throw(_("Не удалось рассчитать сумму в валюте контрагента"))

        if self.transaction_type == "Расход" and flt(self.amount) > flt(self.balance):
            frappe.msgprint(
                _("Внимание: Сумма расхода ({0}) превышает остаток кассы ({1})").format(
                    frappe.format_value(self.amount, {"fieldtype": "Currency"}),
                    frappe.format_value(self.balance, {"fieldtype": "Currency"})
                ),
                indicator="orange",
                alert=True
            )

    def validate_currency(self):
        return


@frappe.whitelist()
def get_cash_account(mode_of_payment, company):
    if not mode_of_payment or not company:
        return None

    account = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account"
    )
    return account


@frappe.whitelist()
def get_cash_account_with_currency(mode_of_payment, company):
    if not mode_of_payment or not company:
        return {"account": None, "currency": None}

    account = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account"
    )

    if account:
        currency = frappe.get_cached_value("Account", account, "account_currency")
        return {"account": account, "currency": currency}

    return {"account": None, "currency": None}


@frappe.whitelist()
def get_party_currency(party_type, party, company):
    if not party_type or not party or not company:
        return None

    currency = None

    if party_type in ["Customer", "Supplier"]:
        account = erpnext_get_party_account(party_type, party, company)
        if account:
            currency = frappe.get_cached_value("Account", account, "account_currency")
        if not currency:
            default_field = "default_currency"
            currency = frappe.get_cached_value(party_type, party, default_field)
        if not currency:
            currency = frappe.get_cached_value("Company", company, "default_currency")
    elif party_type == "Employee":
        account = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Payable", "is_group": 0},
            "name"
        )
        if account:
            currency = frappe.get_cached_value("Account", account, "account_currency")
        if not currency:
            currency = frappe.get_cached_value("Company", company, "default_currency")
    else:
        currency = frappe.get_cached_value("Company", company, "default_currency")

    return currency


@frappe.whitelist()
def get_account_balance(account, company):
    if not account:
        return 0

    balance = frappe.db.sql("""
        SELECT SUM(debit_in_account_currency) - SUM(credit_in_account_currency) as balance
        FROM `tabGL Entry`
        WHERE account = %s
        AND company = %s
        AND is_cancelled = 0
    """, (account, company), as_dict=True)

    if balance and balance[0].balance:
        return flt(balance[0].balance)
    return 0


@frappe.whitelist()
def get_expense_accounts(doctype, txt, searchfield, start, page_len, filters):
    company = (filters or {}).get("company")
    parent_account = get_expense_parent_account(company)

    if not parent_account:
        return []

    return frappe.db.sql("""
        SELECT name, account_name
        FROM `tabAccount`
        WHERE company = %(company)s
        AND root_type = 'Expense'
        AND is_group = 0
        AND lft > %(parent_lft)s
        AND rgt < %(parent_rgt)s
        AND (name LIKE %(txt)s OR account_name LIKE %(txt)s)
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """, {
        "company": company,
        "parent_lft": parent_account.lft,
        "parent_rgt": parent_account.rgt,
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })


def get_expense_parent_account(company):
    if not company:
        return None

    accounts = frappe.db.sql(
        """
        SELECT name, lft, rgt
        FROM `tabAccount`
        WHERE company = %(company)s
        AND (
            account_number = %(account_number)s
            OR name LIKE %(name_pattern)s
        )
        ORDER BY
            CASE WHEN account_number = %(account_number)s THEN 0 ELSE 1 END,
            is_group DESC,
            name
        LIMIT 1
        """,
        {
            "company": company,
            "account_number": EXPENSE_PARENT_ACCOUNT_NUMBER,
            "name_pattern": f"{EXPENSE_PARENT_ACCOUNT_NUMBER}%",
        },
        as_dict=True,
    )

    return accounts[0] if accounts else None


def validate_expense_account(expense_account, company):
    parent_account = get_expense_parent_account(company)

    if not parent_account:
        frappe.throw(_("Не найден счет расходов {0} для компании {1}").format(
            EXPENSE_PARENT_ACCOUNT_NUMBER,
            company,
        ))

    account = frappe.db.get_value(
        "Account",
        expense_account,
        ["company", "root_type", "is_group", "lft", "rgt"],
        as_dict=True,
    )

    if (
        not account
        or account.company != company
        or account.root_type != "Expense"
        or cint(account.is_group)
        or account.lft <= parent_account.lft
        or account.rgt >= parent_account.rgt
    ):
        frappe.throw(_("Счет расходов должен быть внутри счета {0}").format(
            parent_account.name
        ))


@frappe.whitelist()
def get_exchange_rate(from_currency, to_currency, date=None):
    if not date:
        date = frappe.utils.today()

    exchange_rate = frappe.db.get_value(
        "Currency Exchange",
        {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "date": ("<=", date)
        },
        "exchange_rate",
        order_by="date desc"
    )

    if exchange_rate:
        return flt(exchange_rate)

    reverse_rate = frappe.db.get_value(
        "Currency Exchange",
        {
            "from_currency": to_currency,
            "to_currency": from_currency,
            "date": ("<=", date)
        },
        "exchange_rate",
        order_by="date desc"
    )

    if reverse_rate and flt(reverse_rate) > 0:
        return flt(1 / flt(reverse_rate), 4)

    return 0
