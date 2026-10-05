import httpx
import pytest
from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.statistical import (
    EurostatConnector,
    EurostatQuery,
    ImfDataMapperConnector,
    ImfQuery,
    IneSpainConnector,
    IneSpainQuery,
    OecdConnector,
    OecdQuery,
    OnsUkConnector,
    OnsUkQuery,
    WorldBankConnector,
    WorldBankQuery,
)


@pytest.fixture
def public_https(monkeypatch):
    async def accepted(url):
        assert str(url).startswith("https://")

    monkeypatch.setattr(BaseConnector, "validate_url", staticmethod(accepted))


def mock_client(monkeypatch, responder):
    factory = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(responder), **kwargs),
    )


@pytest.mark.asyncio
async def test_eurostat_jsonstat_normalizes_dimensions(monkeypatch, public_https):
    def responder(request):
        assert request.url.host == "ec.europa.eu"
        return httpx.Response(
            200,
            json={
                "class": "dataset",
                "label": "Synthetic transport fixture from official-schema mock",
                "id": ["freq", "unit", "geo", "time"],
                "size": [1, 1, 1, 2],
                "dimension": {
                    "freq": {"category": {"index": {"A": 0}}},
                    "unit": {"category": {"index": {"NR": 0}}},
                    "geo": {
                        "category": {
                            "index": {"PT": 0},
                            "label": {"PT": "Portugal"},
                        }
                    },
                    "time": {"category": {"index": {"2023": 0, "2024": 1}}},
                },
                "value": {"0": 10, "1": 12},
            },
        )

    mock_client(monkeypatch, responder)
    snapshot = await EurostatConnector(
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0"
    ).fetch(
        EurostatQuery(
            dataset_code="demo_test",
            filters={"geo": "PT"},
            start_period="2023",
            end_period="2024",
        )
    )
    assert [row.value for row in snapshot.observations] == [10, 12]
    assert snapshot.observations[0].geo_code == "PT"
    assert snapshot.observations[0].unit == "NR"


@pytest.mark.asyncio
async def test_world_bank_requires_complete_pagination(monkeypatch, public_https):
    def responder(request):
        page = int(request.url.params["page"])
        rows = [
            {
                "indicator": {"id": "SP.POP.TOTL", "value": "Population"},
                "country": {"id": "PT", "value": "Portugal"},
                "countryiso3code": "PRT",
                "date": str(2023 + page),
                "value": 10 + page,
                "unit": "",
                "obs_status": "",
                "decimal": 0,
            }
        ]
        return httpx.Response(
            200,
            json=[
                {"page": page, "pages": 2, "per_page": "1", "total": 2},
                rows,
            ],
        )

    mock_client(monkeypatch, responder)
    snapshot = await WorldBankConnector("https://api.worldbank.org/v2").fetch(
        WorldBankQuery(
            indicator="SP.POP.TOTL",
            countries=["PRT"],
            page_size=1,
            max_pages=2,
        )
    )
    assert len(snapshot.observations) == 2
    assert snapshot.observations[0].geo_code == "PRT"

    with pytest.raises(ConnectorError, match="complete-query page bound"):
        await WorldBankConnector("https://api.worldbank.org/v2").fetch(
            WorldBankQuery(
                indicator="SP.POP.TOTL",
                countries=["PRT"],
                page_size=1,
                max_pages=1,
            )
        )


@pytest.mark.asyncio
async def test_oecd_sdmx_csv_normalizes_observations(monkeypatch, public_https):
    def responder(request):
        assert request.url.host == "sdmx.oecd.org"
        return httpx.Response(
            200,
            text=(
                "STRUCTURE,STRUCTURE_ID,FREQ,REF_AREA,UNIT_MEASURE,TIME_PERIOD,"
                "OBS_VALUE,OBS_STATUS\n"
                "dataflow,DF_TEST,A,PRT,PC,2023,2.5,A\n"
                "dataflow,DF_TEST,A,PRT,PC,2024,3.0,A\n"
            ),
            headers={"content-type": "text/csv"},
        )

    mock_client(monkeypatch, responder)
    snapshot = await OecdConnector("https://sdmx.oecd.org/public/rest").fetch(
        OecdQuery(
            agency="OECD.SDD.TEST",
            dataflow="DSD_TEST@DF_TEST",
            version="1.0",
            key="all",
        )
    )
    assert len(snapshot.observations) == 2
    assert snapshot.observations[0].geo_code == "PRT"
    assert snapshot.observations[0].frequency == "A"


@pytest.mark.asyncio
async def test_imf_datamapper_v2_normalizes_time_series(monkeypatch, public_https):
    def responder(request):
        assert request.url.host == "www.imf.org"
        return httpx.Response(
            200,
            json={
                "api": {"version": "2"},
                "values": {
                    "NGDP_RPCH": {
                        "PRT": {"2023": 2.3, "2024": 1.9},
                    }
                },
            },
        )

    mock_client(monkeypatch, responder)
    snapshot = await ImfDataMapperConnector(
        "https://www.imf.org/external/datamapper/api/v2"
    ).fetch(ImfQuery(indicator="NGDP_RPCH", economies=["PRT"], periods=["2023", "2024"]))
    assert len(snapshot.observations) == 2
    assert snapshot.observations[0].series_code == "NGDP_RPCH"


@pytest.mark.asyncio
async def test_spain_ine_json_table_normalizes_series(monkeypatch, public_https):
    def responder(request):
        assert request.url.host == "servicios.ine.es"
        return httpx.Response(
            200,
            json=[
                {
                    "COD": "IPC_TEST",
                    "Nombre": "Consumer price test series",
                    "FK_Unidad": 1,
                    "FK_Periodicidad": 12,
                    "Data": [
                        {"Fecha": "2024M12", "Anyo": 2024, "Valor": 110.2},
                    ],
                }
            ],
        )

    mock_client(monkeypatch, responder)
    snapshot = await IneSpainConnector(
        "https://servicios.ine.es/wstempus/js/EN"
    ).fetch(IneSpainQuery(table_id="50902", nult=1))
    assert snapshot.observations[0].series_code == "IPC_TEST"
    assert snapshot.observations[0].value == 110.2


@pytest.mark.asyncio
async def test_ons_requires_explicit_single_observations(monkeypatch, public_https):
    def responder(request):
        if request.url.path == "/v1/datasets/cpih01":
            return httpx.Response(
                200,
                json={
                    "links": {
                        "latest_version": {
                            "id": "12",
                            "href": "https://api.beta.ons.gov.uk/v1/datasets/cpih01/"
                            "editions/time-series/versions/12",
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "dimensions": {
                    "aggregate": {"option": {"id": "cpih1dim1A0"}},
                    "geography": {"option": {"id": "K02000001"}},
                    "time": {"option": {"id": "Oct-11"}},
                },
                "observations": [{"observation": "94.5"}],
                "total_observations": 1,
                "unit_of_measure": "Index: 2015=100",
            },
        )

    mock_client(monkeypatch, responder)
    snapshot = await OnsUkConnector("https://api.beta.ons.gov.uk/v1").fetch(
        OnsUkQuery(
            dataset_id="cpih01",
            edition="time-series",
            version="latest",
            dimension_sets=[
                {
                    "time": "Oct-11",
                    "geography": "K02000001",
                    "aggregate": "cpih1dim1A0",
                }
            ],
        )
    )
    assert snapshot.metadata["version"] == 12
    assert snapshot.observations[0].value == "94.5"
    assert snapshot.observations[0].geo_code == "K02000001"


def test_connector_hosts_are_pinned_to_official_domains():
    with pytest.raises(ConnectorError):
        EurostatConnector("https://example.com/eurostat/api/dissemination/statistics/1.0")
    with pytest.raises(ConnectorError):
        WorldBankConnector("https://example.com/v2")
    with pytest.raises(ConnectorError):
        OecdConnector("https://example.com/public/rest")
    with pytest.raises(ConnectorError):
        ImfDataMapperConnector("https://example.com/external/datamapper/api/v2")
    with pytest.raises(ConnectorError):
        IneSpainConnector("https://example.com/wstempus/js/EN")
    with pytest.raises(ConnectorError):
        OnsUkConnector("https://example.com/v1")
