// Copyright (c) 2026, asadbek.backend@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("iBox Client", {
    refresh(frm) {
        if (!frm.is_new()) {

            // ── Test Connection ───────────────────────────────────────
            frm.add_custom_button(__("Test Connection"), function () {
                frappe.call({
                    method: "test_connection",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Testing connection..."),
                    callback: function (r) {
                        if (r.message.success) {
                            frappe.msgprint({
                                title: __("Success"),
                                indicator: "green",
                                message: r.message.message
                            });
                        } else {
                            frappe.msgprint({
                                title: __("Error"),
                                indicator: "red",
                                message: r.message.message
                            });
                        }
                    }
                });
            });

            // ── Sync Now (To'liq Master Sinxronizatsiya) ──────────────
            frm.add_custom_button(__("Sync Now"), function () {
                frappe.confirm(
                    __(
                        "To'liq sinxronizatsiya boshlandi. " +
                        "Bu barcha taminotchi, mijoz va mahsulotlarni yangilaydi.\n\n" +
                        "Tartib: Omborlar → Taminotchilar → Mijozlar → Mahsulotlar\n\n" +
                        "Davom etishni xohlaysizmi?"
                    ),
                    function () {
                        frappe.call({
                            method: "sync_now",
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __("To'liq sinxronizatsiya navbatga qo'shilmoqda..."),
                            callback: function (r) {
                                frappe.msgprint({
                                    title: __("Sinxronizatsiya Boshlandi"),
                                    indicator: "blue",
                                    message: r.message.message
                                });
                                // Statusni ko'rish uchun formdagi sync_status ni yangilash
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }, __("Actions"));

            // ── Omborlarni Yuklash ────────────────────────────────────
            frm.add_custom_button(__("Omborlarni Yuklash"), function () {
                frappe.call({
                    method: "sync_warehouses",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Omborxonalar yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                    }
                });
            }, __("Actions"));

            // ── Taminotchilarni Yuklash ───────────────────────────────
            frm.add_custom_button(__("Taminotchilarni Yuklash"), function () {
                frappe.call({
                    method: "sync_suppliers",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Taminotchilar yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                    }
                });
            }, __("Actions"));

            // ── Mijozlarni Yuklash ────────────────────────────────────
            frm.add_custom_button(__("Mijozlarni Yuklash"), function () {
                frappe.call({
                    method: "sync_customers",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Mijozlar yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                    }
                });
            }, __("Actions"));

            // ── Xaridlarni Yuklash (faqat xarid, vozvrat emas) ───────
            frm.add_custom_button(__("Xaridlarni Yuklash"), function () {
                frappe.call({
                    method: "sync_purchases",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Xaridlar yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                    }
                });
            }, __("Actions"));

            // ── To'lovlarni Yuklash (faqat to'lovlar) ────────────────────
            frm.add_custom_button(__("To'lovlarni Yuklash"), function () {
                frappe.call({
                    method: "sync_payments",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("To'lovlar yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                    }
                });
            }, __("Actions"));


            // ── Vozvratlarni Yuklash (faqat vozvrat, xarid emas) ─────
            frm.add_custom_button(__("Vozvratlarni Yuklash"), function () {
                frappe.call({
                    method: "sync_returns",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Vozvratlar yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                    }
                });
            }, __("Actions"));

            // ── Valyuta Kurslarini Yuklash ───────────────────────────
            frm.add_custom_button(__("Valyuta Kurslarini Yuklash"), function () {
                frappe.call({
                    method: "sync_exchange_rates",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Valyuta kurslari yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                        frm.reload_doc();
                    }
                });
            }, __("Actions"));

            // ── Kassalarni Yuklash ───────────────────────────────────
            frm.add_custom_button(__("Kassalarni Yuklash"), function () {
                frappe.call({
                    method: "sync_cashboxes",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Kassalar (Cashboxes) yuklanmoqda..."),
                    callback: function (r) {
                        if (!r.exc) {
                            frappe.msgprint({
                                title: __("Sinxronizatsiya Yakunlandi"),
                                indicator: "green",
                                message: r.message.message || __("Kassalar muvaffaqiyatli yuklandi.")
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }, __("Actions"));

            // ── Mahsulotlarni Yuklash ─────────────────────────────────
            frm.add_custom_button(__("Mahsulotlarni Yuklash"), function () {
                frappe.call({
                    method: "sync_items",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Mahsulotlar yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                        frm.reload_doc();
                    },
                    error: function () {
                        frappe.msgprint({
                            title: __("Xato"),
                            indicator: "red",
                            message: "Mahsulotlar sinxronizatsiyasini boshlashda xatolik"
                        });
                    }
                });
            }, __("Actions"));

            // ── Sotuvlarni Yuklash ───────────────────────────────────
            frm.add_custom_button(__("Sotuvlarni Yuklash"), function () {
                frappe.call({
                    method: "sync_sales",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Sotuvlar yuklanmoqda..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                        frm.reload_doc();
                    }
                });
            }, __("Actions"));

            // ── Sinxronizatsiyani To'xtatish ─────────────────────────
            frm.add_custom_button(__("Sinxronizatsiyani To'xtatish"), function () {
                frappe.confirm(
                    __("Ishlab turgan sinxronizatsiyani to'xtatishni xohlaysizmi?"),
                    function () {
                        frappe.call({
                            method: "stop_sync",
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __("To'xtatish buyrug'i yuborilmoqda..."),
                            callback: function (r) {
                                frappe.msgprint({
                                    title: __("To'xtatildi"),
                                    indicator: "orange",
                                    message: r.message.message
                                });
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }, __("Actions"));

        }
    }
});
