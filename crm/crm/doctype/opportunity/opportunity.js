// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("crm");

crm.Opportunity = class Opportunity extends frappe.ui.form.Controller {
	setup() {
		this.frm.custom_make_buttons = {
			"Appointment": "Appointment",
		};

		this.frm.email_field = "contact_email";
		this.setup_queries();
	}

	refresh() {
		this.set_opportunity_from()
		this.set_dynamic_link();
		this.update_dynamic_fields();
		this.set_sales_person_from_user();
		this.setup_buttons();
		this.setup_dashboard();
	}

	setup_buttons() {
		this.setup_notification_buttons();

		if (!this.frm.doc.__islocal) {
			if (this.frm.perm[0].write) {
				this.frm.add_custom_button(__("Schedule Follow Up"), () => this.schedule_follow_up(),
					__("Communication"));

				this.frm.add_custom_button(__("Submit Communication"), () => this.submit_communication(),
					__("Communication"));

				if (!["Lost", "Closed", "Converted"].includes(this.frm.doc.status)) {
					this.frm.add_custom_button(__("Lost"), () => {
						crm.utils.set_as_lost_dialog(this.frm);
					}, __("Status"));

					this.frm.add_custom_button(__("Close"), () => {
						this.frm.set_value("status", "Closed");
						this.frm.save();
					}, __("Status"));
				}

				if (["Lost", "Closed"].includes(this.frm.doc.status)) {
					this.frm.add_custom_button(__("Reopen"), () => {
						if (this.frm.doc.status == "Lost") {
							crm.utils.update_lost_status(this.frm, false);
						} else {
							this.frm.set_value("lost_reasons", [])
							this.frm.set_value("order_lost_reason", null)
							this.frm.set_value("status", "Open");
							this.frm.save();
						}
					}, __("Status"));
				}
			}

			if (this.frm.doc.status !== "Lost") {
				if (!this.frm.doc.conversion_document || this.frm.doc.conversion_document == "Appointment") {
					this.frm.add_custom_button(__('Appointment'), () => this.create_appointment(),
						__("Create"));
				}
			}

			this.frm.page.set_inner_btn_group_as_primary(__("Create"));
		}
	}

	setup_notification_buttons() {
		if (this.frm.is_new()) {
			return
		}

		if (this.can_notify("Opportunity Greeting")) {
			let confirmation_count = frappe.get_notification_count(this.frm, 'Opportunity Greeting', 'SMS');
			let label = __("Opportunity Greeting{0}", [confirmation_count ? " (Resend)" : ""]);
			this.frm.add_custom_button(label, () => this.send_sms('Opportunity Greeting'),
				__("Notify"));
		}

		this.frm.add_custom_button(__("Custom Message"), () => this.send_sms('Custom Message'),
			__("Notify"));
	}

	setup_queries() {
		let me = this;

		me.frm.set_query("opportunity_from", () => {
			return {
				"filters": {
					"name": ["in", this.get_allowed_party_types()],
				}
			}
		});

		me.frm.set_query('customer_address', frappe.contacts.address_query);
		me.frm.set_query('contact_person', frappe.contacts.contact_query);
	}

	set_opportunity_from() {
		let allowed_party_types = this.get_allowed_party_types();
		if (allowed_party_types.length == 1 && !this.frm.doc.opportunity_from) {
			this.frm.set_value("opportunity_from", allowed_party_types[0]);
			this.frm.set_df_property("opportunity_from", "hidden", 1);
		}
	}

	get_allowed_party_types() {
		return ["Lead"]
	}

	setup_dashboard() {
		if (this.frm.is_new()) {
			return
		}

		this.frm.dashboard.stats_area_row.empty();

		let reminder_count = frappe.get_notification_count(this.frm, 'Opportunity Greeting', 'SMS');
		let reminder_status = reminder_count ? __("{0} SMS", [reminder_count]) : __("Not Sent");
		let reminder_color = reminder_count ? "green"
			: this.can_notify('Opportunity Greeting') ? "yellow" : "grey";

		this.frm.dashboard.add_indicator(__('Opportunity Greeting: {0}', [reminder_status]), reminder_color);
	}

	update_dynamic_fields() {
		let me = this;

		if (me.frm.doc.opportunity_from) {
			me.frm.set_df_property("party_name", "label", __(me.frm.doc.opportunity_from));
			me.frm.set_df_property("customer_address", "label", __(me.frm.doc.opportunity_from + " Address"));
			me.frm.set_df_property("contact_person", "label", __(me.frm.doc.opportunity_from + " Contact Person"));
		} else {
			me.frm.set_df_property("party_name", "label", __("Party"));
			me.frm.set_df_property("customer_address", "label", __("Address"));
			me.frm.set_df_property("contact_person", "label", __("Contact Person"));
		}
	}

	set_dynamic_link() {
		frappe.dynamic_link = {
			doc: this.frm.doc,
			fieldname: 'party_name',
			doctype: this.frm.doc.opportunity_from || "Lead"
		}
	}

	set_sales_person_from_user() {
		if (!this.frm.get_field('sales_person') || this.frm.doc.sales_person || !this.frm.doc.__islocal) {
			return;
		}

		crm.utils.get_sales_person_from_user(sales_person => {
			if (sales_person) {
				this.frm.set_value('sales_person', sales_person);
			}
		});
	}

	opportunity_from() {
		this.set_dynamic_link();
		this.update_dynamic_fields();
		this.frm.set_value("party_name", "");
	}

	opportunity_type() {
		this.setup_buttons()
		this.update_dynamic_fields()
	}

	contact_person() {
		return crm.utils.get_contact_details(this.frm, "opportunity_from");
	}

	customer_address() {
		return crm.utils.get_address_display(this.frm, "opportunity_from", "customer_address", "address_display");
	}

	party_name() {
		return this.get_customer_details();
	}

	get_customer_details() {
		let me = this;

		if (me.frm.doc.company && me.frm.doc.opportunity_from && me.frm.doc.party_name) {
			return frappe.call({
				method: "crm.crm.doctype.opportunity.opportunity.get_customer_details",
				args: {
					args: {
						doctype: me.frm.doc.doctype,
						company: me.frm.doc.company,
						opportunity_from: me.frm.doc.opportunity_from,
						party_name: me.frm.doc.party_name,
					}
				},
				callback: function (r) {
					if (r.message && !r.exc) {
						return me.frm.set_value(r.message);
					}
				}
			});
		}
	}

	schedule_follow_up() {
		let me = this;
		me.frm.check_if_unsaved();

		let dialog = new frappe.ui.Dialog({
			title: __('Schedule a Follow Up'),
			doc: {},
			fields: [
				{
					label : "Follow Up in Days",
					fieldname: "follow_up_days",
					fieldtype: "Int",
					default: 0,
					onchange: () => {
						let today = frappe.datetime.nowdate();
						let contact_date = frappe.datetime.add_days(today, dialog.get_value('follow_up_days'));
						dialog.set_value('schedule_date', contact_date);
					}
				},
				{
					fieldtype: "Column Break"
				},
				{
					label : "Schedule Date",
					fieldname: "schedule_date",
					fieldtype: "Date",
					reqd: 1,
					onchange: () => {
						let today = frappe.datetime.get_today();
						let schedule_date = dialog.get_value('schedule_date');
						dialog.doc.follow_up_days = frappe.datetime.get_diff(schedule_date, today);
						dialog.get_field('follow_up_days').refresh();
					}
				},
				{
					fieldtype: "Section Break"
				},
				{
					label : "To Discuss",
					fieldname: "to_discuss",
					fieldtype: "Small Text",
				},
			],
			primary_action: function() {
				let data = dialog.get_values();

				frappe.call({
					method: "crm.crm.doctype.opportunity.opportunity.schedule_follow_up",
					args: {
						name: me.frm.doc.name,
						schedule_date: data.schedule_date,
						to_discuss: data.to_discuss || ""
					},
					callback: function (r) {
						if (!r.exc) {
							me.frm.reload_doc();
						}
					}
				});
				dialog.hide();
			},
			primary_action_label: __('Schedule')
		});
		dialog.show();
	}

	submit_communication() {
		let me = this;
		me.frm.check_if_unsaved();

		let row = this.frm.doc.contact_schedule.find(element => !element.contact_date);

		let dialog = new frappe.ui.Dialog({
			title: __('Submit Communication'),
			fields: [
				{
					"label" : "Schedule Date",
					"fieldname": "schedule_date",
					"fieldtype": "Date",
					"default": row && row.schedule_date,
					"read_only": 1
				},
				{
					fieldtype: "Column Break"
				},
				{
					"label" : "Contact Date",
					"fieldname": "contact_date",
					"fieldtype": "Date",
					"reqd": 1,
					"default": frappe.datetime.nowdate()
				},
				{
					fieldtype: "Section Break"
				},
				{
					"label" : "To Discuss",
					"fieldname": "to_discuss",
					"fieldtype": "Small Text",
					"default": row && row.to_discuss,
					"read_only": 1
				},
				{
					"label" : "Remarks",
					"fieldname": "remarks",
					"fieldtype": "Small Text",
					"reqd": 1
				},
			],
			primary_action: function() {
				let data = dialog.get_values();

				frappe.call({
					method: "crm.crm.doctype.opportunity.opportunity.submit_communication",
					args: {
						opportunity: me.frm.doc.name,
						contact_date: data.contact_date,
						remarks: data.remarks,
					},
					callback: function (r) {
						if (!r.exc) {
							me.frm.reload_doc();
						}
					}
				});
				dialog.hide();
			},
			primary_action_label: __('Submit')
		});
		dialog.show();
	}

	create_appointment() {
		frappe.model.open_mapped_doc({
			method: "crm.crm.doctype.opportunity.opportunity.make_appointment",
			frm: this.frm
		});
	}

	can_notify(what) {
		if (this.frm.doc.__onload && this.frm.doc.__onload.can_notify) {
			return this.frm.doc.__onload.can_notify[what];
		} else {
			return false;
		}
	}

	send_sms(notification_type) {
		new frappe.SMSManager(this.frm.doc, {
			notification_type: notification_type,
			mobile_no: this.frm.doc.contact_mobile || this.frm.doc.contact_phone,
			party_doctype: this.frm.doc.opportunity_from,
			party: this.frm.doc.party_name,
		});
	}
};

extend_cscript(cur_frm.cscript, new crm.Opportunity({frm: cur_frm}));
