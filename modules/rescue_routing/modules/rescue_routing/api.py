"""FastAPI REST service providing rescue routing and fleet dispatch endpoints."""

from typing import Any
try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError:
    # optional dependency
    FastAPI = None
    HTTPException = None
    BaseModel = object

from .osm_loader import load_network
from .router import RescueRouter, VehicleType
from .dispatch import assign_fleet

if FastAPI:
    app = FastAPI(title="HighWater Rescue Routing API", version="2.0.0")
else:
    app = None

_graph = None
_router = None


def get_router() -> RescueRouter:
    """Get or initialize singleton router instance."""
    global _graph, _router
    if _router is None:
        _graph = load_network()
        _router = RescueRouter(_graph)
    return _router


if FastAPI and BaseModel is not object:
    class RouteRequest(BaseModel):
        origin: str
        destination: str
        vehicle_type: str = "AMBULANCE"
        rainfall_rate: float = 15.0
        blocked_edges: list[list[str]] | None = None
        depth_map: dict[str, float] | None = None
        depart_in_min: float = 0.0

    class DispatchRequest(BaseModel):
        incidents: list[dict[str, Any]]
        fleet: list[dict[str, Any]]
        rainfall_rate: float = 15.0
        blocked_edges: list[list[str]] | None = None
        depth_map: dict[str, float] | None = None

    @app.get("/network")
    def get_network() -> dict:
        """Get network topology as a GeoJSON FeatureCollection."""
        router = get_router()
        return router.export_network_geojson()

    @app.post("/route")
    def calculate_route(req: RouteRequest) -> dict:
        """Calculate single-vehicle flood-aware rescue route."""
        router = get_router()
        d_map = None
        if req.depth_map:
            d_map = {}
            for k, v in req.depth_map.items():
                if "|" in k:
                    u, w = k.split("|")
                    d_map[tuple(sorted((u.strip(), w.strip())))] = float(v)
                else:
                    d_map[k] = float(v)

        b_edges = None
        if req.blocked_edges:
            b_edges = [tuple(e) for e in req.blocked_edges]

        v_type = req.vehicle_type
        if v_type == VehicleType.RESCUE_BOAT.value:
            return router.find_multimodal_route(
                req.origin,
                req.destination,
                rainfall_rate=req.rainfall_rate,
                blocked_edges=b_edges,
                depth_map=d_map,
                depart_in_min=req.depart_in_min,
            )
        return router.find_route(
            req.origin,
            req.destination,
            v_type,
            rainfall_rate=req.rainfall_rate,
            blocked_edges=b_edges,
            depth_map=d_map,
            depart_in_min=req.depart_in_min,
        )

    @app.post("/dispatch")
    def dispatch_fleet(req: DispatchRequest) -> dict:
        """Assign fleet assets to incidents maximizing total prioritized value."""
        router = get_router()
        d_map = None
        if req.depth_map:
            d_map = {}
            for k, v in req.depth_map.items():
                if "|" in k:
                    u, w = k.split("|")
                    d_map[tuple(sorted((u.strip(), w.strip())))] = float(v)
                else:
                    d_map[k] = float(v)

        b_edges = None
        if req.blocked_edges:
            b_edges = [tuple(e) for e in req.blocked_edges]

        try:
            return assign_fleet(
                req.incidents,
                req.fleet,
                router,
                rainfall_rate=req.rainfall_rate,
                blocked_edges=b_edges,
                depth_map=d_map,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
