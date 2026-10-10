"""Cloud admission shim; frozen owner source and response semantics stay intact.

A proxy CONNECT rejection is not an ordinary connection failure and must never
trigger the owner's direct fallback. No request is performed during import or
class construction. The caller supplies the already admitted owner module.
"""
import re
from functools import wraps

_CONNECT_REJECTION=re.compile(r'Tunnel connection failed:\s*([45]\d\d)(?:\D|$)',re.IGNORECASE)


def guarded_transport_class(owner_transport):
    class CloudTransport(owner_transport.ProxyAwareHTTPTransport):
        def _attempt(self,*args,**kwargs):
            try:
                return super()._attempt(*args,**kwargs)
            except owner_transport.HTTPContractError:
                raise
            except owner_transport.TransportError as error:
                # The original bounded error text includes urllib's CONNECT
                # rejection. Do not label it an upstream HTTP response.
                match=_CONNECT_REJECTION.search(str(error.receipt.get('error','')))
                if match and kwargs.get('proxy_used') and not kwargs.get('fallback_used'):
                    receipt=dict(error.receipt,proxy_connect_status=int(match.group(1)),
                        v5_transport_policy='CONNECT_REJECTION_NO_DIRECT_FALLBACK')
                    raise owner_transport.HTTPContractError('V5_PROXY_CONNECT_REJECTED',receipt=receipt) from error
                raise
    return CloudTransport


def run_original_us_cli(owner,owner_transport,argv,*,allow_network_capture=False,transport_options=None):
    """Inject one guarded transport through the original producer's explicit seam.

    This is a synchronous fresh-process entry, not a service/scheduler hook.
    Owner admission, IO roots, windows, locks and exit codes remain original.
    It restores both original functions even when parsing or capture fails.
    """
    if allow_network_capture is not True:
        raise ValueError('V5_CLOUD_CAPTURE_EXPLICIT_AUTHORIZATION_REQUIRED')
    guarded=guarded_transport_class(owner_transport)(**(transport_options or {}))
    names=('materialize_us_market_phase','materialize_us_historical_backfill')
    originals={name:getattr(owner,name) for name in names}
    def bind(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            if 'transport' in kwargs:
                raise ValueError('V5_CLOUD_TRANSPORT_OVERRIDE_FORBIDDEN')
            return function(*args,transport=guarded,**kwargs)
        return wrapped
    try:
        for name,function in originals.items():setattr(owner,name,bind(function))
        return owner.main(argv)
    finally:
        for name,function in originals.items():setattr(owner,name,function)


def main(argv=None):
    """Explicit cloud entry; use an already SHA-admitted private owner PYTHONPATH."""
    import sys
    args=list(sys.argv[1:] if argv is None else argv)
    if not args or args.pop(0)!='--allow-network-capture':
        raise ValueError('V5_CLOUD_CAPTURE_EXPLICIT_AUTHORIZATION_REQUIRED')
    if args and args[0]=='--':args.pop(0)
    from ops import us_market_digest
    from infrastructure import http_transport
    return run_original_us_cli(us_market_digest,http_transport,args,allow_network_capture=True)


if __name__=='__main__':
    raise SystemExit(main())
