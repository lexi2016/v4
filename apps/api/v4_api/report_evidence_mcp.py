"""Optional stdio MCP facade; exact same owner-backed service and allowlist as HTTP.

Start explicitly with V4_RESEARCH_DATA_ROOT and V4_REPORT_EVIDENCE_INDEX_ROOT.
This entry never starts services or builds an index, and exposes no path argument.
"""
import os
from apps.api.v4_api.report_evidence_router import configured_service

def service():
    root=os.environ.get('V4_RESEARCH_DATA_ROOT')
    if not root:
        raise RuntimeError('RESEARCH_OWNER_NOT_CONFIGURED')
    result=configured_service(root)
    if result is None:
        raise RuntimeError('REPORT_INDEX_NOT_CONFIGURED')
    return result

async def report_search(text: str, security: str='',market: str='',source: str='',date_from: str='',date_to: str='',
                        mode: str='current_research',as_of: str|None=None,limit: int=10):
    return await service().search(text,security=security,market=market,source=source,date_from=date_from,date_to=date_to,mode=mode,as_of=as_of,limit=limit)

def report_read(chunk_id: str):
    return service().read(chunk_id)

if __name__=='__main__':
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    mcp=FastMCP('V4 report evidence read-only')
    annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False)
    mcp.tool(annotations=annotations)(report_search)
    mcp.tool(annotations=annotations)(report_read)
    mcp.run(transport='stdio')
