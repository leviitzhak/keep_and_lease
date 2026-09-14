# Isolated private saved-run cost probe

This bounded diagnostic uses the existing keyless cloud operator identity and its
existing IAM grants only. It does not deploy, rerun a strategy, change service or
bucket permissions, impersonate a human, or bypass the API's owner checks.
It resolves a single user-authorized run by a fixed SHA-256 identifier digest in
at most 2,000 result-directory entries, then attempts to read only that result
and audit manifest. No unrelated run contents are read. A denied read is reported
as a failure, not worked around by escalating identity.

All private output is gzip-compressed, AES-256-GCM authenticated-encrypted, with
the random AES key wrapped to a temporary RSA-3072 public key using OAEP-SHA256.
The private decryption key remains outside GitHub and outside Google Cloud.
Only ciphertext is uploaded, with one-day retention. No parameters, result
bodies, identifiers, raw error messages, access tokens, or credentials are logged
or committed. The public script and workflow contain no private plaintext.

The path-restricted workflow is staged with CI skipped; only the bounded JSON
request triggers this diagnostic. Request-only changes do not replace the GCP
preview. This probe does not itself implement new application statistics.
