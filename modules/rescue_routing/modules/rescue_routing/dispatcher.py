"""Tactical dispatch briefing generator using Groq or deterministic offline fallback."""

import os

try:
    from groq import Groq
except ImportError:
    Groq = None


def generate_tactical_briefing(payload: dict) -> tuple[str, str]:
    """Generate a 2-sentence dispatch briefing via Groq or deterministic fallback."""
    api_key = os.environ.get("GROQ_API_KEY")
    if api_key and Groq is not None:
        try:
            client = Groq(api_key=api_key, timeout=5.0)
            model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
            user_msg = (
                f"Status: {payload.get('status')}, Vehicle: {payload.get('vehicle_type')}, "
                f"Origin: {payload.get('origin')}, Destination: {payload.get('destination')}, "
                f"ETA: {payload.get('eta_minutes')} min, Distance: {payload.get('distance_km')} km, "
                f"Predictive Detour: {payload.get('is_predictive_detour')}, "
                f"Avoided Hazards: {payload.get('avoided_hazards', [])}"
            )
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a military emergency dispatch commander. "
                            "Generate a 2-sentence crisp, operational dispatch briefing for rescue teams."
                        ),
                    },
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
            )
            content = resp.choices[0].message.content
            if content:
                return content.strip(), "groq"
        except Exception:
            pass

    # deterministic two-sentence fallback for offline continuity
    if payload.get("status") == "INVALID_REQUEST":
        dest = payload.get("destination", "target")
        reason = payload.get("reason", "invalid request parameters")
        return f"Routing request invalid for target destination {dest}. Operation aborted due to {reason}.", "offline"

    if payload.get("status") == "UNREACHABLE":
        text = (
            f"Target destination {payload.get('destination')} is isolated and unreachable "
            f"by {payload.get('vehicle_type')} due to severed transit corridors. "
            f"Immediate aerial supply drop (airdrop) required for personnel in the isolated sector."
        )
        return text, "offline"

    dest = payload.get("destination", "destination")
    veh = str(payload.get("vehicle_type", "vehicle"))
    is_boat = "BOAT" in veh
    is_heli = "HELICOPTER" in veh
    eta = float(payload.get("eta_minutes", 0.0))
    dist = float(payload.get("distance_km", 0.0))
    rel = payload.get("route_reliability")
    rel_clause = f" with {rel:.1%} route reliability" if rel is not None else ""

    delta = payload.get("eta_delta_min")
    if delta is None and isinstance(payload.get("counterfactual"), dict):
        delta = payload["counterfactual"].get("eta_delta_min")

    if is_heli:
        s1 = f"Air corridor cleared for {veh} to {dest} with ETA of {eta:.1f} minutes covering {dist:.2f} km."
        if (
            payload.get("surface_access_severed")
            or payload.get("scenario_id") in {"scenario_3b_total_isolation_airdrop", "scenario_5_full_cascade"}
            or payload.get("assumption")
        ):
            s2 = "Surface access corridors are completely severed by floodwaters, requiring priority aerial insertion."
        else:
            s2 = "Direct aerial flight path operates clear of ground topography and surface inundation."
    elif is_boat:
        if payload.get("legs"):
            slipway = payload["legs"][0]["path_nodes"][-1]
            s1 = f"Multimodal route cleared for {veh} staging at {slipway} slipway with ETA of {eta:.1f} minutes covering {dist:.2f} km{rel_clause}."
        else:
            s1 = f"Route cleared for {veh} to {dest} along river corridor with ETA of {eta:.1f} minutes covering {dist:.2f} km{rel_clause}."

        if payload.get("avoided_hazards"):
            s2 = "Transit diverted to avoid submerged or blocked infrastructure along the primary corridor."
        else:
            s2 = "All assigned river corridors report nominal navigable flow conditions without active debris hazards."
    else:
        s1 = f"Route cleared for {veh} to {dest} with ETA of {eta:.1f} minutes covering {dist:.2f} km{rel_clause}."
        if payload.get("note") == "ORIGIN_EQUALS_DESTINATION":
            s2 = "Origin equals destination with zero transit required."
        elif payload.get("is_predictive_detour"):
            if delta is not None and delta > 0:
                s2 = f"Predictive flood routing active with +{delta:.1f} min detour to bypass high risk bridgehead crossings."
            else:
                s2 = "Predictive flood routing active to bypass high risk bridgehead crossings."
        elif payload.get("avoided_hazards"):
            s2 = "Transit diverted to avoid submerged or blocked infrastructure along the primary corridor."
        else:
            s2 = "All assigned road segments and bridgeheads report nominal surface conditions without active flood threats."

    return f"{s1} {s2}", "offline"
