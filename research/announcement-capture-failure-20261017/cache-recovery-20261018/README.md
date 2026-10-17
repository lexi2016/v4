# Issue 44 cached-product recovery — running validation

An explicit POST binds an original failed task and its existing immutable capture product to a distinct recovery job. The route checks the failed attempt, product SHA/schema/size/owner/source, target date and cutoff, and rejects arbitrary paths. Recovery skips capture lease/session/network collection and uses the normal full-product runner and existing historical-success reuse contract.

Independent Reviewer ran 30 focused tests against the exact candidate with the active V4 Python runtime: PASS. One nonblocking P2 remains for cursor write failure after asynchronous submit; a failed POST must be audited before retry. The local candidate is deployed. A real recovery POST returned 202, created job c3717353b23c4257af5a10be41a69db9, and produced a model first_content event. New task results and final API/UI binding are still pending, not accepted by this commit.

The three integrated-source files are the exact bounded overlay applied to the verified active base. Canonical api.py contains unrelated preexisting work; that work is preserved locally and excluded from this deployment and upload. verification.json separately records canonical and integrated source hashes. The material branch is not a complete live runtime tree.

No raw announcement product, business responses/model outputs, credentials, runtime release tree, logs or backups are uploaded. This is manual research-only validation. The original cutoff is preserved; all trading/production gates remain unchanged. Existing displayed candidates do not establish this new run's acceptance.
