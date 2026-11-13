"""Bound logical selector reads for the released Review Core candidate."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from ops.research_panel_logical import META, LogicalFile, digest, is_logical, stamp


def _date(value):
    text = str(value)
    if len(text) != 8 or datetime.strptime(text, '%Y%m%d').strftime('%Y%m%d') != text:
        raise ValueError('REVIEW_CORE_LOGICAL_DATE_INVALID')
    return text


@dataclass(frozen=True)
class LogicalSelector:
    """Verified owner binding. Date/row proof does not establish PIT."""

    file: LogicalFile
    source_date: str
    anchor_sha256: str
    producer_sha256: str
    generation_id: str
    pit_certified: bool

    @classmethod
    def open(cls, path, source_date, *, anchor_sha256, producer_sha256):
        source_date = _date(source_date)
        file = LogicalFile(path)
        if digest(file.path) != anchor_sha256 or stamp(file.path) != file.anchor_stat:
            raise ValueError('REVIEW_CORE_LOGICAL_ANCHOR_SHA_MISMATCH')
        meta = json.loads(file.schema_arrow.metadata[META])
        receipt = Path(meta['generation_manifest_path'])
        stamp(receipt)
        raw = receipt.read_bytes()
        if hashlib.sha256(raw).hexdigest() != producer_sha256:
            raise ValueError('REVIEW_CORE_LOGICAL_PRODUCER_SHA_MISMATCH')
        producer = json.loads(raw)
        flags = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
        if (
            producer.get('schema') != 'a_share_qfq_panel_v1'
            or producer.get('status') != 'CANDIDATE_READY'
            or _date(producer['target_date']) != source_date
            or _date(meta['asof_date']) != source_date
            or producer.get('candidates', {}).get('selector') != str(file.path)
            or producer.get('candidate_sha256', {}).get('selector') != anchor_sha256
            or not producer.get('generation_id') or producer['generation_id'] != meta.get('generation_id')
            or type(producer.get('pit_certified')) is not bool
            or producer['pit_certified'] is not meta.get('pit_certified')
            or any(producer.get(k) is not v or meta.get(k) is not v for k, v in flags.items())
        ):
            raise ValueError('REVIEW_CORE_LOGICAL_OWNER_IDENTITY_CONFLICT')
        return cls(file, source_date, anchor_sha256, producer_sha256,
                   producer['generation_id'], producer['pit_certified'])

    def exact(self, columns):
        table = self.file.read(columns=columns, filters=[('trade_date', '==', self.source_date)])
        if not table.num_rows:
            raise ValueError('REVIEW_CORE_LOGICAL_EXACT_DATE_EMPTY')
        return table

    def evidence(self):
        table = self.exact(['ts_code', 'trade_date'])
        symbols = table['ts_code'].to_pylist()
        if not all(symbols) or len(set(symbols)) != table.num_rows:
            raise ValueError('REVIEW_CORE_LOGICAL_EXACT_KEYS_INVALID')
        return dict(
            schema='v4.review_core.logical_selector_read.v1',
            status='EXACT_DATE_READ_VERIFIED', source_date=self.source_date,
            path=str(self.file.path), selector_sha256=self.anchor_sha256,
            producer_receipt_sha256=self.producer_sha256, generation_id=self.generation_id,
            row_count=table.num_rows, producer_pit_certified=self.pit_certified,
            RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
        )

    def scanner(self, *, columns, batch_size):
        # Reuse the original consumer's streaming historical name map.
        return _LogicalBatches(self.file, columns, batch_size)

@dataclass(frozen=True)
class _LogicalBatches:
    file: LogicalFile
    columns: list[str]
    batch_size: int

    def to_batches(self):
        return self.file.iter_batches(columns=self.columns, batch_size=self.batch_size)


def candidate_selector(path, source_date, *, expected_sha256=None):
    """Bind the exact-role child to the candidate's independently pinned pair."""
    if not is_logical(path):
        return None
    anchor_sha = os.environ.get('V4_REVIEW_LOGICAL_SELECTOR_SHA256')
    producer_sha = os.environ.get('V4_REVIEW_LOGICAL_PRODUCER_RECEIPT_SHA256')
    if not anchor_sha or not producer_sha or (expected_sha256 is not None and anchor_sha != expected_sha256):
        raise ValueError('REVIEW_CORE_LOGICAL_EXPECTED_IDENTITY_MISSING_OR_CONFLICT')
    return LogicalSelector.open(path, source_date, anchor_sha256=anchor_sha, producer_sha256=producer_sha)
