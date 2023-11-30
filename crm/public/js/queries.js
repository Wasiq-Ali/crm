frappe.provide("crm.queries");

$.extend(crm.queries, {
	lead: function(filters) {
		return {
			query: "crm.queries.lead_query",
			filters: filters,
		};
	},
});
