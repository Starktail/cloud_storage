# Copyright (c) 2026, AgriTheory and contributors
# For license information, please see license.txt

import json
from io import BytesIO

import frappe
import pytest

from cloud_storage import get_files_for_document

pytestmark = pytest.mark.usefixtures("mocked_s3_client")


def make_communication(subject):
	return frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Sent",
			"status": "Linked",
			"subject": subject,
			"sender": "Administrator",
			"recipients": "supplier@example.com",
			"content": subject,
			"reference_doctype": "Role",
			"reference_name": "System Manager",
		}
	).insert(ignore_permissions=True)


def attach(communication, file_name, content):
	# what frappe.core.doctype.communication.email.add_attachments does for a sent email
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"attached_to_doctype": "Communication",
			"attached_to_name": communication.name,
			"folder": "Home/Attachments",
			"content": content,
			"decode": False,
			"is_private": 1,
		}
	).save(ignore_permissions=True)


def test_same_attachment_emailed_twice_is_listed_on_both_communications():
	"""The second email's File is merged into the first one and steals `attached_to`, so core's
	`attached_to`-based lookups list the attachment on one Communication only."""
	from PIL import Image

	frappe.set_user("Administrator")
	buffer = BytesIO()
	Image.new("RGB", (5, 9), (200, 30, 90)).save(buffer, format="PNG")
	content = buffer.getvalue()

	first = make_communication("RFQ to supplier 1")
	second = make_communication("RFQ to supplier 2")
	try:
		attach(first, "drawing.png", content)
		attach(second, "drawing.png", content)

		# one physical File survives, now attached_to the second Communication
		owners = frappe.get_all(
			"File", filters={"file_name": "drawing.png"}, pluck="attached_to_name"
		)
		assert owners == [second.name]

		for comm in (first, second):
			files = get_files_for_document("Communication", comm.name)
			assert [f.file_name for f in files] == ["drawing.png"]
			assert [f.file_name for f in comm.get_attachments()] == ["drawing.png"]

		# what the form timeline renders for each email
		timeline = {
			c.name: json.loads(c.attachments)
			for c in frappe.desk.form.load._get_communications("Role", "System Manager", limit=50)
			if c.name in (first.name, second.name)
		}
		assert len(timeline) == 2
		for files in timeline.values():
			assert len(files) == 1
			assert "?key=" in files[0]["file_url"]
	finally:
		for comm in (first, second):
			frappe.delete_doc("Communication", comm.name, ignore_permissions=True, force=True)
