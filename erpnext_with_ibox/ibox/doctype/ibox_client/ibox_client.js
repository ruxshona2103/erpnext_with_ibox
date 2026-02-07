// Copyright (c) 2026, asadbek.backend@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("iBox Client", {
    refresh(frm) {
        if (!frm.is_new()) {
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

            frm.add_custom_button(__("Sync Now"), function () {
                frappe.call({
                    method: "sync_now",
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __("Starting sync..."),
                    callback: function (r) {
                        frappe.msgprint({
                            title: __("Sync Started"),
                            indicator: "blue",
                            message: r.message.message
                        });
                    }
                });
            }, __("Actions"));
        }
    }
});
