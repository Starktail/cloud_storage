# Copyright (c) 2024, AgriTheory and contributors
# For license information, please see license.txt

__version__ = "15.7.4"


import json

import frappe
import frappe.desk.form.load
from frappe.core.doctype.communication.communication import Communication
from frappe.core.doctype.file import file as file_module
from frappe.query_builder import DocType

import cloud_storage.permissions  # noqa: F401 — must load before silencing stock File list hook


def empty_file_permission_query_conditions(user=None, doctype=None):
	return None


file_module.get_permission_query_conditions = empty_file_permission_query_conditions


@frappe.whitelist()
def patched_get_attachments(dt, dn):
	if "cloud_storage" not in frappe.get_installed_apps():
		return frappe.get_all(
			"File",
			fields=["name", "file_name", "file_url", "is_private"],
			filters={"attached_to_name": dn, "attached_to_doctype": dt},
		)

	File = DocType("File")
	FileAssociation = DocType("File Association")
	return (
		frappe.qb.from_(FileAssociation)
		.inner_join(File)
		.on(File.name == FileAssociation.parent)
		.select(File.name, File.file_name, File.file_url, File.is_private)
		.where(FileAssociation.link_doctype == dt)
		.where(FileAssociation.link_name == dn)
	).run(as_dict=True)


frappe.desk.form.load.get_attachments = patched_get_attachments


ATTACHMENT_FIELDS = ["name", "file_name", "file_url", "is_private"]


def get_files_for_document(dt, dn, fields=ATTACHMENT_FIELDS):
	"""All File rows that belong to a document, by `attached_to_*` or by File Association.
	"""
	files = frappe.get_all(
		"File", fields=fields, filters={"attached_to_doctype": dt, "attached_to_name": str(dn)}
	)
	if "cloud_storage" not in frappe.get_installed_apps():
		return files

	seen = {f.name for f in files}
	linked = frappe.get_all(
		"File Association", filters={"link_doctype": dt, "link_name": str(dn)}, pluck="parent"
	)
	missing = [name for name in set(linked) if name not in seen]
	if missing:
		files += frappe.get_all("File", fields=fields, filters={"name": ["in", missing]})
	return files


def patched_get_communications(doctype, name, start=0, limit=20):
	"""
	HASH: 48366c6ecbad44ed24e6d02bdd8f8f189ce58927
	REPO: https://github.com/frappe/frappe
	PATH: frappe/desk/form/load.py
	METHOD: _get_communications

	Core looks attachments up by `attached_to_*` only, so when the same files are emailed
	from one document several times only the last email lists them in the timeline.
	"""
	communications = frappe.desk.form.load.get_communication_data(doctype, name, start, limit)
	for c in communications:
		if c.communication_type in ("Communication", "Automated Message"):
			c.attachments = json.dumps(get_files_for_document("Communication", c.name))

	return communications


def patched_communication_get_attachments(self):
	"""
	HASH: 48366c6ecbad44ed24e6d02bdd8f8f189ce58927
	REPO: https://github.com/frappe/frappe
	PATH: frappe/core/doctype/communication/communication.py
	METHOD: get_attachments
	"""
	return get_files_for_document(self.DOCTYPE, self.name)


frappe.desk.form.load._get_communications = patched_get_communications
Communication.get_attachments = patched_communication_get_attachments
