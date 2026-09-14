"""Static permission-scope contracts; native Terraform validation is separate."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "infra/gcp/codex_operator.tf").read_text(encoding="utf-8")


def resource(kind, name):
    # Narrow source check for these top-level blocks, not a general HCL parser.
    pattern = rf'^resource "{re.escape(kind)}" "{re.escape(name)}" {{\n(.*?)^}}'
    matches = re.findall(pattern, SOURCE, re.MULTILINE | re.DOTALL)
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one {kind}.{name}, found {len(matches)}")
    return matches[0]


class OperatorResultsAccessTests(unittest.TestCase):
    def test_results_reader_is_only_an_unconditional_additive_member(self):
        body = resource("google_storage_bucket_iam_member", "codex_results_reader")
        self.assertEqual(body.strip(), '\n'.join([
            'bucket = google_storage_bucket.results.name',
            '  role   = "roles/storage.objectViewer"',
            '  member = "serviceAccount:${google_service_account.codex_operator.email}"',
        ]))
        self.assertNotIn("condition", body)
        self.assertNotIn('resource "google_storage_bucket_iam_policy"', SOURCE)
        self.assertNotIn('resource "google_storage_bucket_iam_binding"', SOURCE)

    def test_existing_market_read_and_create_grants_are_unchanged(self):
        body = resource("google_storage_bucket_iam_member", "codex_market_publisher")
        self.assertEqual(body.strip(), '\n'.join([
            'for_each = toset(["roles/storage.objectCreator", "roles/storage.objectViewer"])',
            '  bucket   = google_storage_bucket.market_data.name',
            '  role     = each.value',
            '  member   = "serviceAccount:${google_service_account.codex_operator.email}"',
        ]))
        self.assertEqual(SOURCE.count('resource "google_storage_bucket_iam_member"'), 2)

    def test_no_new_project_roles_or_public_principals(self):
        self.assertNotRegex(SOURCE, r'resource "google_project_iam_(?:member|binding|policy)"')
        self.assertNotIn("allUsers", SOURCE)
        self.assertNotIn("allAuthenticatedUsers", SOURCE)
        self.assertEqual(set(re.findall(r'"(roles/[^"\s]+)"', SOURCE)), {
            "roles/iam.workloadIdentityUser", "roles/run.invoker",
            "roles/storage.objectCreator", "roles/storage.objectViewer",
        })

    def test_operator_impersonation_remains_branch_restricted(self):
        body = resource("google_service_account_iam_member", "codex_operator_github_wif")
        self.assertIn('role               = "roles/iam.workloadIdentityUser"', body)
        self.assertIn('attribute.ref/refs/heads/${var.codex_operator_branch}', body)
        self.assertNotIn("attribute.repository", body)
        self.assertIn('default     = "agent/cloud-autonomous-access"', SOURCE)


if __name__ == "__main__":
    unittest.main()
