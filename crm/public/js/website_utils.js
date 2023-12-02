frappe.provide("erpnext");
frappe.provide("crm");

// Lead Form
crm.send_message = function(opts, btn) {
	return frappe.call({
		type: "POST",
		method: "crm.crm.doctype.opportunity.opportunity.make_opportunity_from_lead_form",
		btn: btn,
		args: opts.args,
		callback: opts.callback,
		error: opts.error,
	});
};
frappe.send_message = crm.send_message;
erpnext.send_message = crm.send_message;

// Newsletter Subscription
crm.subscribe_to_newsletter = function(opts, btn) {
	return frappe.call({
		type: "POST",
		method: "frappe.email.doctype.newsletter.newsletter.subscribe",
		btn: btn,
		args: {"email": opts.email},
		callback: opts.callback,
		error: opts.error,
	});
};
frappe.subscribe_to_newsletter = crm.subscribe_to_newsletter;
erpnext.subscribe_to_newsletter = crm.subscribe_to_newsletter;
