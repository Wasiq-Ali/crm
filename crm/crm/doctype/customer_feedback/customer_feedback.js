// Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.provide("crm");

crm.CustomerFeedback = class CustomerFeedback extends frappe.ui.form.Controller {
	setup() {
		this.setup_queries();
	}

	refresh () {
		this.set_feedback_from();
	}

	setup_queries() {
		let me = this;

		me.frm.set_query("feedback_from", () => {
			return {
				"filters": {
					"name": ["in", crm.utils.get_feedback_allowed_party_types()],
				}
			}
		});
	}

	set_feedback_from() {
		let allowed_party_types = crm.utils.get_feedback_allowed_party_types();
		if (allowed_party_types.length == 1 && !this.frm.doc.feedback_from) {
			this.frm.set_value("feedback_from", allowed_party_types[0]);
			this.frm.set_df_property("feedback_from", "hidden", 1);
		}
	}

	feedback_from () {
		this.update_dynamic_fields();
		this.frm.set_value("party_name", "");
	}

	party_name() {
		return this.get_customer_name();
	}

	update_dynamic_fields() {
		if (this.frm.doc.feedback_from) {
			this.frm.set_df_property("party_name", "label", __(this.frm.doc.feedback_from));
		} else {
			this.frm.set_df_property("party_name", "label", __("Party"));
		}
	}

	get_customer_name() {
		if (this.frm.doc.feedback_from && this.frm.doc.party_name) {
			return frappe.call({
				method: "crm.crm.doctype.customer_feedback.customer_feedback.get_customer_name",
				args: {
					feedback_from: this.frm.doc.feedback_from,
					party_name: this.frm.doc.party_name,
				},
				callback: (r) => {
					if (!r.exc) {
						this.frm.set_value("customer_name", r.message);
					}
				}
			});
		}
	}

	reference_doctype() {
		this.frm.set_value("reference_name", null);
	}

	reference_name () {
		return this.determine_party();
	}

	determine_party() {
		if (this.frm.doc.reference_doctype && this.frm.doc.reference_name) {
			return this.frm.call({
				method: "determine_party_from_reference_name",
				doc: this.frm.doc,
				callback: () => {
					this.frm.refresh_fields();
				}
			});
		}
	}
}

extend_cscript(cur_frm.cscript, new crm.CustomerFeedback({frm: cur_frm}));
