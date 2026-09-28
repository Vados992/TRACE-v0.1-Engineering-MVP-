from typing import Any

from .base import BaseConnector


class GleifConnector(BaseConnector):
    source_code = "GLEIF"

    async def search_by_name(self, name: str, page_size: int = 10) -> dict[str, Any]:
        params = {
            "filter[entity.legalName]": name,
            "page[size]": min(max(page_size, 1), 100),
        }
        response = await self.request(
            "GET",
            f"{self.base_url}/lei-records",
            params=params,
            headers={"Accept": "application/vnd.api+json"},
        )
        return response.json()

    async def get_lei(self, lei: str) -> dict[str, Any]:
        response = await self.request(
            "GET",
            f"{self.base_url}/lei-records/{lei}",
            headers={"Accept": "application/vnd.api+json"},
        )
        return response.json()

    async def relationship(self, lei: str, rel: str) -> dict[str, Any] | None:
        allowed = {
            "direct-parent",
            "ultimate-parent",
            "direct-children",
            "ultimate-children",
            "successor-entities",
        }
        if rel not in allowed:
            raise ValueError(f"unsupported relationship: {rel}")
        response = await self.request_optional(
            "GET",
            f"{self.base_url}/lei-records/{lei}/{rel}",
            headers={"Accept": "application/vnd.api+json"},
        )
        return response.json() if response is not None else None

    async def direct_parent(self, lei: str) -> dict[str, Any] | None:
        return await self.relationship(lei, "direct-parent")

    async def ultimate_parent(self, lei: str) -> dict[str, Any] | None:
        return await self.relationship(lei, "ultimate-parent")
