// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Appointment Type', {
	setup: function(frm) {
		frm.set_query("sales_persons", () => {
			return {
				filters: {
					is_group: 0,
				}
			}
		})
	}
});
