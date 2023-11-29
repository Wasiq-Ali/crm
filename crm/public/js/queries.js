frappe.provide("crm.queries");

$.extend(crm.queries, {
	lead: function(filters) {
		return {
			query: "erpnext.controllers.queries.lead_query",
			filters: filters,
		};
	},
});
