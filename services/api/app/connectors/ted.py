from typing import Any

from ..models import TedSearchRequest
from .base import BaseConnector


class TedConnector(BaseConnector):
    source_code = "TED"

    async def search(self, request: TedSearchRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": request.query,
            "fields": request.fields,
            "limit": request.limit,
            "paginationMode": request.pagination_mode,
        }
        if request.pagination_mode == "PAGE_NUMBER":
            body["page"] = request.page
        elif request.iteration_next_token:
            body["iterationNextToken"] = request.iteration_next_token

        response = await self.request(
            "POST",
            f"{self.base_url}/v3/notices/search",
            json=body,
            headers={"Accept": "application/json"},
        )
        return response.json()
