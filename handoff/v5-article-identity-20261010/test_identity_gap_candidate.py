"""Synthetic RED candidates. NOT_RUN; requires pinned checkout and original test dependencies."""
import test_archive_article_v2 as chain

class IdentityGapCandidate(chain.ArticleV2ChainTests):
    def test_control_valid_capture_is_accepted(self):
        self.publish()

    def _require_identity_rejection(self, field):
        # All capture bytes/receipts/body/time stay unchanged; one valid-format identity changes.
        original = self.original['articles'][0][field]
        replacement = ('e' if original != 'e' * 64 else 'd') * 64
        self.original['articles'][0][field] = replacement
        process, value = self.invoke()
        self.assertNotEqual(process.returncode, 0,
            'Identity mutation unexpectedly accepted: ' + field + ' ' + repr(value))
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_article_id_mutation_must_be_rejected(self):
        self._require_identity_rejection('article_id')

    def test_dedupe_key_mutation_must_be_rejected(self):
        self._require_identity_rejection('dedupe_key')
