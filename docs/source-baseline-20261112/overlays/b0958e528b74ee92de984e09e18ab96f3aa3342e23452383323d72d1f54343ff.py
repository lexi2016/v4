"""Frozen research selection policy; no data access or trading permission."""
import hashlib
import json

POLICY_VERSION = "US_HK_SELECTION_20261023_V1"
POLICY = dict(version=POLICY_VERSION, primary_return_min="1", close_ma20_min="1",
    close_ma20_max="1.1", return5_max="15", turnover20_hkd_min="20000000",
    max_selected=10, max_theme=3, close_sessions=21, amount_sessions=20,
    price_basis="PIT_ADJUSTED", amount_unit="HKD", currency="HKD",
    primary_order="RELATIONSHIP_TYPE_THEN_US_SYMBOL_THEN_PATH_ID_BEFORE_RETURN",
    secondary_conflict_max="-1", sector_paths="CONTEXT_ONLY",
    state_precedence=["REJECT", "PENDING", "PASS"])
RELATIONSHIP_A = (
    "NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER",
    "NAMED_CLOUD_CONNECTIVITY_PARTNERSHIP",
    "NAMED_COMPONENT_OPTION",
    "CO_DESIGNED_PRODUCT_PARTNERSHIP",
)
ETF_SYMBOLS = frozenset("SPY QQQ DIA IWM XBI SOXX KBE GLD XLE FCG XLY XLP XLK XLF XLV XLI XLU XLB XLRE XLC ARKK SMH GDX SLV USO TLT HYG EEM FXI KWEB ARKX BOTZ CLOU COPX DRIV GRID ICLN ITA LIT NLR REMX TAN UFO".split())
US_SYMBOL_THEMES = dict(NVDA="半导体", AMD="半导体", STX="存储", VRT="数据中心",
    EQIX="数据中心", DLR="数据中心")
# Exact source-enum adaptation. These certify bounded research use only; none
# supplies the positive transmission/target/history proof required by strict.
CURRENT_RESEARCH_SCOPE_ALIASES = frozenset({
    "CURRENT_DIRECTORY_IDENTITY_SUPPORTED_NO_EXECUTABILITY_CONFIRMATION",
    "CURRENT_NAMED_LICENSE_PUBLIC_TERRITORY_AND_CONDITIONAL_ECONOMICS_SUPPORTED",
})
DATED_RESEARCH_SCOPE_ALIASES = frozenset({
    "SUPPORTED_LIMITED_REPORT_PERIOD_SCOPE", "SUPPORTED_LIMITED_DOCUMENTARY_SCOPE",
    "SUPPORTED_H1_NAMED_RELATIONSHIP_WITH_CONTRACT_LIMITS", "SUPPORTED_H1_CHANNEL_WITH_CONTRACT_LIMITS",
    "SUPPORTED_H1_CONTRACT_PERFORMANCE_WITH_PROJECT_SPECIFIC_FUTURE_GAPS",
    "H1_Q2_SCOPE_SUPPORTED; PRODUCT_MIX_AND_ACQUISITION_BASELINES_SEPARATED",
    "H1_Q2_OPERATING_COMPARISON_SUPPORTED; Q3_FCX_UPDATE_PRELIMINARY_NOT_FINAL",
    "H1_LICENSE_AND_PAYMENT_SUPPORTED; OCTOBER_LIFECYCLE_NOT_CONFIRMED",
})
POLICY.update(specific_relationships=list(RELATIONSHIP_A), etf_symbols=sorted(ETF_SYMBOLS), themes=US_SYMBOL_THEMES,
    current_research_scope_aliases=sorted(CURRENT_RESEARCH_SCOPE_ALIASES),dated_research_scope_aliases=sorted(DATED_RESEARCH_SCOPE_ALIASES))
POLICY_SHA256 = hashlib.sha256(json.dumps(POLICY, sort_keys=True,
    separators=(",", ":")).encode()).hexdigest()
