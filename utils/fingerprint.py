def generate_fingerprint(client_data):
    source = client_data.get("_source")
    cid = client_data.get("cid")

    base = {
        "callsign": client_data.get("callsign"),
        "cid": cid,
    }

    if source == "pilot":
        fp = client_data.get("flight_plan", {})
        aircraft = fp.get("aircraft_short") or fp.get("aircraft")
        base.update({
            "transponder": client_data.get("transponder"),
            "assigned_transponder": fp.get("assigned_transponder"),
            "aircraft": aircraft,
            "route": fp.get("route"),
            "dep": fp.get("departure"),
            "arr": fp.get("arrival"),
            "alt": fp.get("altitude"),
            # NOTE: No position or address in fingerprint anymore
        })
    elif source == "controller":
        base.update({
            "frequency": client_data.get("frequency"),
            "facility": client_data.get("facility"),
            "visual_range": client_data.get("visual_range"),
            "text_atis": "\n".join(client_data.get("text_atis", []))
        })

    return base
