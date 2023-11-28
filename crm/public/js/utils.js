frappe.provide("crm.utils");

$.extend(crm.utils, {
	get_sales_person_from_user: function (callback) {
		return frappe.call({
			method: "crm.crm.doctype.sales_person.sales_person.get_sales_person_from_user",
			callback: function (r) {
				if (!r.exc && callback) {
					callback(r.message);
				}
			}
		});
	},
});
