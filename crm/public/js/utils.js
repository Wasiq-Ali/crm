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

	get_contact_details: function(frm, party_type_field) {
		if (frm.updating_party_details) {
			return;
		}

		let lead = crm.utils.get_lead_from_doc(frm, party_type_field);

		return frappe.call({
			method: "crm.crm.utils.get_contact_details",
			args: {
				contact: frm.doc.contact_person || "",
				lead: lead,
			},
			callback: function(r) {
				if (r.message) {
					return frm.set_value(r.message);
				}
			}
		});
	},

	get_address_display: function(frm, party_type_field, address_field, display_field) {
		if (frm.updating_party_details) {
			return;
		}

		let lead = erpnext.utils.get_lead_from_doc(frm, party_type_field);

		return frappe.call({
			method: "crm.crm.utils.get_address_display",
			args: {
				address: frm.doc[address_field] || "",
				lead: lead
			},
			callback: function(r) {
				if (!r.exc) {
					frm.set_value(display_field, r.message);
				}
			}
		})
	},

	get_lead_from_doc: function (frm, party_type_field) {
		if (frm.doc.party_name && frm.doc[party_type_field] === "Lead") {
			return frm.doc.party_name
		}
	}
});
